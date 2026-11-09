"""Transactional absolute totals, written serially outside the UI thread."""

import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from .core import Counts, CounterModel
from .backup import select_counts, write_backup


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=1)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("数据库版本高于当前程序版本，请使用较新版本的敲敲。")
            connection.execute("PRAGMA journal_mode=WAL")
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS daily_counts (
                        day TEXT NOT NULL,
                        key_id TEXT NOT NULL,
                        count INTEGER NOT NULL CHECK(count >= 0),
                        PRIMARY KEY (day, key_id)
                    ) WITHOUT ROWID
                """)
                connection.execute("PRAGMA user_version=1")

    def load(self) -> Counts:
        with closing(sqlite3.connect(self.path, timeout=1)) as connection:
            rows = connection.execute("SELECT day, key_id, count FROM daily_counts")
            return {(day, key_id): count for day, key_id, count in rows}

    def save(self, totals: Counts):
        if not totals:
            return
        with closing(sqlite3.connect(self.path, timeout=1)) as connection:
            with connection:
                connection.executemany("""
                    INSERT INTO daily_counts(day, key_id, count) VALUES (?, ?, ?)
                    ON CONFLICT(day, key_id) DO UPDATE SET count=excluded.count
                """, ((day, key_id, count) for (day, key_id), count in totals.items()))

    def replace_range(self, start: date, end: date, totals: Counts) -> None:
        lower, upper = start.isoformat(), end.isoformat()
        if start > end or any(not lower <= day <= upper for day, _ in totals):
            raise ValueError("导入记录必须位于所选日期范围内。")
        with closing(sqlite3.connect(self.path, timeout=1)) as connection:
            with connection:
                connection.execute("DELETE FROM daily_counts WHERE day BETWEEN ? AND ?", (lower, upper))
                connection.executemany(
                    "INSERT INTO daily_counts(day, key_id, count) VALUES (?, ?, ?)",
                    ((day, key, count) for (day, key), count in totals.items()),
                )


class Persistence:
    def __init__(self, model: CounterModel, database: Database):
        self.model = model
        self.database = database
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="daily-counts")
        self.future: Future | None = None
        self.snapshot: Counts = {}
        self.last_saved: datetime | None = None
        self.error: str | None = None
        self._last_attempt = 0.0
        self.import_future: Future | None = None
        self._import_pending: Counts = {}
        self._import_counts: Counts = {}

    def _collect(self, wait=False):
        if self.future is None or (not wait and not self.future.done()):
            return
        try:
            self.future.result()
        except Exception as error:
            self.model.retry(self.snapshot)
            self.error = str(error)
        else:
            self.last_saved = datetime.now()
            self.error = None
        finally:
            self.future = None
            self.snapshot = {}

    def _submit(self):
        if self.future is not None or not self.model.dirty:
            return
        snapshot = self.model.snapshot_dirty()
        try:
            self.future = self.executor.submit(self.database.save, snapshot)
        except Exception:
            self.model.retry(snapshot)
            raise
        self.snapshot = snapshot
        self._last_attempt = time.monotonic()

    def tick(self):
        if self.import_future is not None:
            return
        self._collect()
        if time.monotonic() - self._last_attempt >= 1:
            self._submit()

    def flush(self) -> bool:
        # Even exit must reconcile a committed import before saving the model.
        self.finish_import(wait=True)
        self._collect(wait=True)
        self._submit()
        self._collect(wait=True)
        return not self.model.dirty and self.error is None

    def begin_import(self, start: date, end: date, totals: Counts, backup_path: Path) -> None:
        """The caller pauses counting until finish_import completes on the GUI thread."""
        if self.import_future is not None:
            raise RuntimeError("已有导入正在执行。")
        replacement = self.model.restored_counts(start, end, totals)
        pending = {key: self.model.counts[key] for key in self.model.dirty | self.snapshot.keys()}
        before = select_counts(self.model.counts, start, end)
        previous = self.future

        def restore():
            if previous is not None:
                try:
                    previous.result()
                except Exception:
                    # Its latest absolute values are included in pending below.
                    pass
            self.database.save(pending)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            write_backup(backup_path, before, start, end)
            self.database.replace_range(start, end, totals)

        future = self.executor.submit(restore)
        self.import_future = future
        self._import_pending = pending
        self._import_counts = replacement
        # Ownership of the old save and its retry moves to the import job.
        self.future = None
        self.snapshot = {}

    def finish_import(self, wait: bool = False) -> bool:
        if self.import_future is None or (not wait and not self.import_future.done()):
            return False
        try:
            self.import_future.result()
        except Exception:
            self.model.retry(self._import_pending)
            raise
        else:
            self.model.apply_restored_counts(self._import_counts)
            self.last_saved = datetime.now()
            self.error = None
            return True
        finally:
            self.import_future = None
            self._import_pending = {}
            self._import_counts = {}

    def close(self):
        self.executor.shutdown(wait=True)
