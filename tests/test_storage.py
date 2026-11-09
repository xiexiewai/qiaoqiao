import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from qiaoqiao.backup import read_backup
from qiaoqiao.core import CounterModel
from qiaoqiao.keys import PhysicalEvent
from qiaoqiao.storage import Database, Persistence


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "counts.sqlite3")
        self.database.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_reopen_preserves_counts_and_repeated_write_is_idempotent(self):
        values = {("2026-10-30", "1e"): 20, ("2026-10-29", "e0_1d"): 4}
        self.database.save(values)
        self.database.save(values)
        self.assertEqual(Database(self.database.path).load(), values)

    def test_batch_rolls_back_as_a_unit(self):
        self.database.save({("2026-10-30", "1e"): 3})
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.save({("2026-10-30", "1e"): 99, ("2026-10-30", "30"): -1})
        self.assertEqual(self.database.load(), {("2026-10-30", "1e"): 3})

    def test_schema_only_contains_daily_aggregates(self):
        with closing(sqlite3.connect(self.database.path)) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(daily_counts)")]
        self.assertEqual(columns, ["day", "key_id", "count"])

    def test_newer_schema_is_not_silently_downgraded(self):
        with closing(sqlite3.connect(self.database.path)) as connection:
            connection.execute("PRAGMA user_version=2")
        with self.assertRaises(RuntimeError):
            self.database.initialize()

    def test_flush_includes_keys_pressed_while_previous_save_runs(self):
        started, finish = threading.Event(), threading.Event()
        actual_save = self.database.save

        def slow_save(values):
            started.set()
            self.assertTrue(finish.wait(3))
            actual_save(values)

        self.database.save = slow_save
        model = CounterModel()
        persistence = Persistence(model, self.database)
        try:
            model.accept(PhysicalEvent(1, "1e", True), date(2026, 10, 30))
            persistence.tick()
            self.assertTrue(started.wait(3))
            model.accept(PhysicalEvent(1, "1e", False), date(2026, 10, 30))
            model.accept(PhysicalEvent(1, "1e", True), date(2026, 10, 30))
            finish.set()
            self.assertTrue(persistence.flush())
            self.assertEqual(self.database.load()[("2026-10-30", "1e")], 2)
        finally:
            finish.set()
            persistence.close()

    def test_write_failure_keeps_latest_unsaved_totals_for_retry(self):
        actual_save = self.database.save
        self.database.save = lambda values: (_ for _ in ()).throw(OSError("disk full"))
        model = CounterModel()
        persistence = Persistence(model, self.database)
        try:
            model.accept(PhysicalEvent(1, "1e", True), date(2026, 10, 30))
            self.assertFalse(persistence.flush())
            self.assertEqual(persistence.error, "disk full")
            model.accept(PhysicalEvent(1, "1e", False), date(2026, 10, 30))
            model.accept(PhysicalEvent(1, "1e", True), date(2026, 10, 30))
            self.database.save = actual_save
            self.assertTrue(persistence.flush())
            self.assertEqual(self.database.load()[("2026-10-30", "1e")], 2)
            self.assertIsNone(persistence.error)
        finally:
            persistence.close()

    def test_replace_range_clears_missing_days_and_keys_preserving_outside(self):
        original = {
            ("2026-09-30", "1e"): 9, ("2026-10-01", "1e"): 8,
            ("2026-10-09", "1e"): 100, ("2026-10-09", "30"): 7,
            ("2026-10-31", "1e"): 6, ("2026-11-01", "1e"): 5,
        }
        self.database.save(original)
        incoming = {("2026-10-09", "1e"): 50}
        for _ in range(2):
            self.database.replace_range(date(2026, 10, 1), date(2026, 10, 31), incoming)
            self.assertEqual(self.database.load(), {
                ("2026-09-30", "1e"): 9, ("2026-10-09", "1e"): 50, ("2026-11-01", "1e"): 5,
            })
        self.database.replace_range(date(2026, 10, 1), date(2026, 10, 31), {})
        self.assertEqual(self.database.load(), {("2026-09-30", "1e"): 9, ("2026-11-01", "1e"): 5})

    def test_import_insert_failure_rolls_back_the_delete(self):
        original = {("2026-10-09", "1e"): 100}
        self.database.save(original)
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.replace_range(date(2026, 10, 1), date(2026, 10, 31), {
                ("2026-10-09", "1e"): 50, ("2026-10-10", "30"): -1,
            })
        self.assertEqual(self.database.load(), original)
        with self.assertRaises(ValueError):
            self.database.replace_range(date(2026, 10, 10), date(2026, 10, 31), original)
        self.assertEqual(self.database.load(), original)

    def test_import_waits_for_old_save_and_retries_latest_before_backup(self):
        for fail_old in (False, True):
            with self.subTest(fail_old=fail_old):
                started, finish = threading.Event(), threading.Event()
                original_save = self.database.save
                calls = []

                def save(values):
                    calls.append(dict(values))
                    if len(calls) == 1:
                        started.set()
                        self.assertTrue(finish.wait(3))
                        if fail_old:
                            raise OSError("old failure")
                    original_save(values)

                model = CounterModel({("2026-10-09", "1e"): 100})
                model.dirty.add(("2026-10-09", "1e"))
                persistence = Persistence(model, self.database)
                backup = Path(self.temp.name) / f"before-{fail_old}.qiaoqiao.json"
                try:
                    with patch.object(self.database, "save", side_effect=save):
                        persistence.tick()
                        self.assertTrue(started.wait(3))
                        model.accept(PhysicalEvent(1, "1e", True), date(2026, 10, 9))
                        model.counts[("2026-11-01", "30")] = 12
                        model.dirty.add(("2026-11-01", "30"))
                        persistence.begin_import(date(2026, 10, 1), date(2026, 10, 31),
                                                 {("2026-10-09", "1e"): 50}, backup)
                        persistence.tick()
                        finish.set()
                        self.assertTrue(persistence.finish_import(wait=True))
                    self.assertEqual(read_backup(backup).counts, {("2026-10-09", "1e"): 101})
                    self.assertEqual(model.counts[("2026-10-09", "1e")], 50)
                    self.assertEqual(model.counts[("2026-11-01", "30")], 12)
                    self.assertEqual(model.pressed, {(1, "1e")})
                    self.assertFalse(model.dirty)
                    self.assertTrue(persistence.flush())
                    self.assertEqual(self.database.load(), model.counts)
                    self.assertIsNone(persistence.error)
                finally:
                    finish.set()
                    persistence.close()

    def test_import_failure_preserves_model_and_retry_state(self):
        for target in ("save", "backup", "replace_range"):
            with self.subTest(target=target):
                original = {("2026-10-09", "1e"): 100, ("2026-11-01", "30"): 12}
                self.database.save(original)
                model = CounterModel(original)
                model.accept(PhysicalEvent(1, "1e", True), date(2026, 10, 9))
                expected = dict(model.counts)
                persistence = Persistence(model, self.database)
                backup = Path(self.temp.name) / f"before-{target}.qiaoqiao.json"
                failure = patch("qiaoqiao.storage.write_backup", side_effect=OSError("backup failed")) if (
                    target == "backup"
                ) else patch.object(self.database, target, side_effect=OSError("disk full"))
                try:
                    with failure:
                        persistence.begin_import(date(2026, 10, 1), date(2026, 10, 31), {}, backup)
                        with self.assertRaises(OSError):
                            persistence.finish_import(wait=True)
                    self.assertEqual(model.counts, expected)
                    self.assertIsNone(persistence.import_future)
                    self.assertTrue(persistence.flush())
                    self.assertEqual(self.database.load(), expected)
                    if target == "replace_range":
                        self.assertEqual(read_backup(backup).counts, {("2026-10-09", "1e"): 101})
                finally:
                    persistence.close()

    def test_flush_reconciles_committed_import_before_saving(self):
        original = {("2026-10-09", "1e"): 100}
        self.database.save(original)
        model = CounterModel(original)
        persistence = Persistence(model, self.database)
        try:
            persistence.begin_import(date(2026, 10, 1), date(2026, 10, 31), {},
                                     Path(self.temp.name) / "before.qiaoqiao.json")
            persistence.import_future.result(timeout=3)
            self.assertEqual(model.counts, original)
            self.assertTrue(persistence.flush())
            self.assertEqual(model.counts, {})
            self.assertEqual(self.database.load(), {})
        finally:
            persistence.close()

    def test_import_scheduling_failure_keeps_the_existing_save_owned(self):
        model = CounterModel()
        model.accept(PhysicalEvent(1, "1e", True), date(2026, 10, 9))
        persistence = Persistence(model, self.database)
        try:
            persistence.tick()
            previous, snapshot = persistence.future, persistence.snapshot
            with patch.object(persistence.executor, "submit", side_effect=RuntimeError("unavailable")):
                with self.assertRaises(RuntimeError):
                    persistence.begin_import(date(2026, 10, 1), date(2026, 10, 31), {},
                                             Path(self.temp.name) / "before.qiaoqiao.json")
            self.assertIsNone(persistence.import_future)
            self.assertIs(persistence.future, previous)
            self.assertEqual(persistence.snapshot, snapshot)
            self.assertTrue(persistence.flush())
            self.assertEqual(self.database.load(), {("2026-10-09", "1e"): 1})
        finally:
            persistence.close()


if __name__ == "__main__":
    unittest.main()
