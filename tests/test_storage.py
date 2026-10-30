import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
