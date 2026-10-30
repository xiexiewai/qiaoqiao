import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from qiaoqiao.app import Controller, InstanceGuard
from qiaoqiao.keys import PhysicalEvent
from qiaoqiao.runtime import Runtime
from qiaoqiao.storage import Database


APPLICATION = QApplication.instance() or QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)


class FakeListener:
    def __init__(self, on_key, on_remove, on_reset, on_error, on_shutdown):
        self.on_key, self.on_reset = on_key, on_reset
        self.active = False
        self.locked = self.suspended = False
        self.last_error = None

    def start(self):
        self.active = True

    def stop(self):
        self.active = False
        self.on_reset()

    def close(self):
        self.stop()


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "counts.sqlite3")
        self.database.initialize()
        self.controller = Controller(APPLICATION, self.database, FakeListener)
        self.controller._tray_tip_shown = True
        with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
            self.controller.start()
        APPLICATION.processEvents()

    def tearDown(self):
        self.controller.dispose()
        self.controller.window.deleteLater()
        self.controller.menu.deleteLater()
        self.controller.deleteLater()
        APPLICATION.processEvents()
        self.temp.cleanup()

    def tap(self, key="1e"):
        self.controller.listener.on_key(PhysicalEvent(1, key, True))
        self.controller.listener.on_key(PhysicalEvent(1, key, False))

    def test_close_hides_but_capture_and_persistence_continue(self):
        self.controller.window.close()
        self.assertFalse(self.controller.window.isVisible())
        self.assertTrue(self.controller.listener.active)
        self.assertTrue(self.controller.timer.isActive())
        self.tap()
        self.controller.tick()
        self.assertTrue(self.controller.persistence.flush())
        self.assertEqual(self.database.load()[(date.today().isoformat(), "1e")], 1)

    def test_minimize_hides_and_restore_refreshes(self):
        self.controller.window.showMinimized()
        QTest.qWait(30)
        self.assertFalse(self.controller.window.isVisible())
        self.tap()
        self.controller.window.restore()
        self.assertTrue(self.controller.window.isVisible())
        self.assertEqual(self.controller.window.total_label.text(), "1")
        self.assertTrue(self.controller.listener.active)

    def test_period_selection_and_history_do_not_change_capture_date(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        self.controller.model.counts[(yesterday.isoformat(), "30")] = 7
        self.controller.model.revision += 1
        self.controller.window.date_edit.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        self.tap()
        self.controller.refresh()
        self.assertEqual(self.controller.window.total_label.text(), "7")
        self.controller.window.set_period("all")
        self.assertEqual(self.controller.window.total_label.text(), "8")
        self.assertFalse(self.controller.window.date_edit.isEnabled())
        self.controller.window.set_period("day")
        self.controller.window.go_today()
        self.assertEqual(self.controller.window.total_label.text(), "1")

    def test_follow_today_moves_at_midnight_but_history_stays(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        window = self.controller.window
        window.date_edit.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        window.last_today = yesterday
        window.follow_today = True
        self.controller.refresh()
        self.assertEqual(window.anchor, today)
        window.date_edit.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        window.last_today = yesterday
        self.controller.refresh()
        self.assertEqual(window.anchor, yesterday)

    def test_tray_exit_saves_final_press_and_stops_listener(self):
        self.tap()
        self.controller.exit_action.trigger()
        self.assertTrue(self.controller.closed)
        self.assertFalse(self.controller.listener.active)
        self.assertFalse(self.controller.tray.isVisible())
        self.assertEqual(self.database.load()[(date.today().isoformat(), "1e")], 1)

    def test_failed_exit_keeps_memory_and_retries_without_double_counting(self):
        self.tap()
        with patch.object(self.database, "save", side_effect=OSError("disk full")):
            with patch.object(self.controller, "_show_error") as show_error:
                self.assertFalse(self.controller.request_exit())
                show_error.assert_called_once()
        self.assertFalse(self.controller.closed)
        self.assertTrue(self.controller.listener.active)
        self.assertTrue(self.controller.timer.isActive())
        self.tap()
        self.assertTrue(self.controller.request_exit())
        self.assertEqual(self.database.load()[(date.today().isoformat(), "1e")], 2)

    def test_release_clears_highlight_without_changing_total(self):
        self.controller.listener.on_key(PhysicalEvent(1, "1e", True))
        self.controller.refresh()
        self.assertEqual(self.controller.window.keyboard.pressed, {"1e"})
        self.controller.listener.on_key(PhysicalEvent(1, "1e", False))
        self.controller.refresh()
        self.assertEqual(self.controller.window.keyboard.pressed, set())
        self.assertEqual(self.controller.window.total_label.text(), "1")

    def test_window_and_tray_identify_development_mode(self):
        self.assertIn("开发版", self.controller.window.windowTitle())
        self.assertIn(self.controller.runtime.title, self.controller.tray.toolTip())

    def test_production_history_is_not_modified_by_development_capture(self):
        production = Database(Path(self.temp.name) / "production" / "counts.sqlite3")
        production.initialize()
        previous = {(date.today().isoformat(), "1e"): 123}
        production.save(previous)
        stable = Controller(
            APPLICATION, production, FakeListener, Runtime(False, production.path.parent),
        )
        try:
            stable.refresh()
            self.assertEqual(stable.window.total_label.text(), "123")
            self.assertNotIn("开发版", stable.window.windowTitle())
            self.tap()
            self.assertTrue(self.controller.persistence.flush())
            self.assertEqual(production.load(), previous)
            self.assertEqual(self.database.load()[(date.today().isoformat(), "1e")], 1)
        finally:
            stable.dispose()
            stable.window.deleteLater()
            stable.menu.deleteLater()
            stable.deleteLater()

    def test_layout_stays_inside_keyboard_and_keys_never_overlap(self):
        self.controller.window.resize(1040, 570)
        APPLICATION.processEvents()
        keyboard = self.controller.window.keyboard
        rects = keyboard.key_rects()
        for index, (_, rect) in enumerate(rects):
            self.assertGreater(rect.width(), 30)
            self.assertGreater(rect.height(), 30)
            self.assertGreaterEqual(rect.left(), 0)
            self.assertLessEqual(rect.right(), keyboard.width())
            self.assertLessEqual(rect.bottom(), keyboard.height())
            for _, other in rects[index + 1:]:
                self.assertFalse(rect.intersects(other))

    def test_large_exact_totals_fit_at_a_readable_minimum_font(self):
        self.controller.window.resize(1040, 570)
        self.controller.model.counts[(date.today().isoformat(), "1e")] = 123456789
        self.controller.model.revision += 1
        self.controller.refresh()
        APPLICATION.processEvents()
        metrics = QFontMetricsF(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        for key, rect in self.controller.window.keyboard.key_rects():
            count = self.controller.window.keyboard.counts.get(key.key_id, 0)
            self.assertLessEqual(metrics.horizontalAdvance(f"{count:,}"), rect.width() - 8)


class InstanceTests(unittest.TestCase):
    def test_production_and_development_instances_run_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            stable = InstanceGuard(Path(directory) / "Qiaoqiao")
            development = InstanceGuard(Path(directory) / "Qiaoqiao-dev")
            try:
                self.assertTrue(stable.acquire())
                self.assertTrue(development.acquire())
                self.assertNotEqual(stable.name, development.name)
            finally:
                stable.close()
                development.close()

    def test_second_instance_cannot_acquire_and_wakes_first(self):
        with tempfile.TemporaryDirectory() as directory:
            first = InstanceGuard(Path(directory))
            second = InstanceGuard(Path(directory))
            activations = []
            first.activated.connect(lambda: activations.append(True))
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                self.assertTrue(second.notify_existing())
                QTest.qWait(80)
                self.assertEqual(activations, [True])
                first.close()
                self.assertTrue(second.acquire())
            finally:
                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()
