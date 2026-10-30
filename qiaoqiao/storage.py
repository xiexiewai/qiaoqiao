"""Transactional absolute totals, written serially outside the UI thread."""

import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .core import Counts, CounterModel


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
        self._collect()
        if time.monotonic() - self._last_attempt >= 1:
            self._submit()

    def flush(self) -> bool:
        self._collect(wait=True)
        self._submit()
        self._collect(wait=True)
        return not self.model.dirty and self.error is None

    def close(self):
        self.executor.shutdown(wait=True)
