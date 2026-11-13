import math
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QDate, QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QSystemTrayIcon

from qiaoqiao.app import Controller, InstanceGuard, milestone_message
from qiaoqiao.keys import PhysicalEvent
from qiaoqiao.layouts import LAYOUTS
from qiaoqiao.runtime import Runtime
from qiaoqiao.storage import Database
from qiaoqiao.theme import ERROR, KEY_IDLE, MINT, MUTED, heat_color
from qiaoqiao.ui import SHORT_ARROW_LABELS, StatsWindow


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
        self.assertTrue(self.controller.pet.isVisible())
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
        self.assertTrue(self.controller.pet.isVisible())
        self.tap()
        self.controller.window.restore()
        self.assertTrue(self.controller.window.isVisible())
        self.assertFalse(self.controller.pet.isVisible())
        self.assertEqual(self.controller.window.total_label.text(), "1")
        self.assertTrue(self.controller.listener.active)

    def test_pet_visibility_topmost_and_tray_actions_persist(self):
        controller = self.controller
        controller.window.close()
        self.assertTrue(controller.pet.isVisible())
        self.assertTrue(controller.pet._animation_timer.isActive())
        self.assertTrue(controller.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        controller.topmost_action.setChecked(False)
        self.assertTrue(controller.pet.isVisible())
        self.assertFalse(controller.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        controller.pet_action.setChecked(False)
        self.assertFalse(controller.pet.isVisible())
        self.assertFalse(controller.pet._animation_timer.isActive())
        self.tap()
        self.assertEqual(sum(controller.model.totals("day", date.today()).values()), 1)
        self.assertEqual(controller.settings.value("pet/enabled", type=bool), False)
        self.assertEqual(controller.settings.value("pet/topmost", type=bool), False)
        controller.pet_action.setChecked(True)
        self.assertTrue(controller.pet.isVisible())
        self.assertTrue(controller.pet._animation_timer.isActive())
        controller.open_action.trigger()
        self.assertTrue(controller.window.isVisible())
        self.assertFalse(controller.pet.isVisible())
        self.assertFalse(controller.pet._animation_timer.isActive())

    def test_pet_hides_during_session_pause_and_restores_afterward(self):
        self.controller.window.close()
        self.controller.listener.locked = True
        self.controller.tick()
        self.assertFalse(self.controller.pet.isVisible())
        self.assertFalse(self.controller.pet._animation_timer.isActive())
        self.controller.listener.locked = False
        self.controller.tick()
        self.assertTrue(self.controller.pet.isVisible())
        self.assertTrue(self.controller.pet._animation_timer.isActive())
        self.controller.listener.suspended = True
        self.controller.tick()
        self.assertFalse(self.controller.pet.isVisible())
        self.assertFalse(self.controller.pet._animation_timer.isActive())

    def test_pet_double_click_requests_main_window(self):
        self.controller.window.close()
        self.controller.pet.open_requested.emit()
        self.assertTrue(self.controller.window.isVisible())
        self.assertFalse(self.controller.pet.isVisible())

    def test_pet_only_receives_accepted_physical_presses_without_callback_painting(self):
        controller = self.controller
        controller.window.close()
        with patch.object(controller.pet, "on_key_press", wraps=controller.pet.on_key_press) as feedback, \
                patch.object(controller.pet, "_start_action") as start:
            down = PhysicalEvent(1, "1e", True)
            for _ in range(10):
                controller._key(down)
            controller._key(PhysicalEvent(1, "1e", False))
            controller._key(PhysicalEvent(2, "1e", True))
            self.assertEqual(feedback.call_count, 2)
            start.assert_not_called()
        self.assertEqual(sum(controller.model.totals("day", date.today()).values()), 2)
        controller.pet._animate()
        self.assertIn(controller.pet._behavior, ("tap", "typing"))

    def test_pet_preference_survives_controller_recreation(self):
        self.controller.topmost_action.setChecked(False)
        self.controller.pet_action.setChecked(False)
        restored = Controller(APPLICATION, self.database, FakeListener)
        try:
            self.assertFalse(restored.topmost_action.isChecked())
            self.assertFalse(restored.pet_action.isChecked())
            self.assertFalse(restored.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        finally:
            restored.dispose()
            restored.pet.deleteLater()
            restored.pet_menu.deleteLater()
            restored.window.deleteLater()
            restored.menu.deleteLater()
            restored.deleteLater()

    def test_trend_tab_keeps_capture_save_and_tray_restore_working(self):
        window = self.controller.window
        window.set_keyboard_layout("60")
        window.tabs.setCurrentIndex(1)
        self.tap("47")
        self.controller.refresh()
        self.assertTrue(self.controller.persistence.flush())
        window.close()
        with patch.object(self.controller.model, "trends", wraps=self.controller.model.trends) as aggregate:
            self.tap("47")
            self.controller.tick()
            aggregate.assert_not_called()
            self.assertTrue(self.controller.persistence.flush())
            self.controller.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
            aggregate.assert_called_once()
        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(window.trends.cards[0].value.text(), "2")
        self.assertEqual(window.trends.snapshot.top_keys, (("47", 2),))
        self.assertTrue(self.controller.listener.active)
        self.assertFalse(window.keyboard._feedback_timer.isActive())
        self.assertEqual(self.database.load()[(date.today().isoformat(), "47")], 2)
        window.tabs.setCurrentIndex(0)
        self.assertEqual(window.total_label.text(), "2")
        self.assertIn("Num 7: 2", window.other_label.text().replace("\u00a0", " "))

    def test_trend_tab_failed_exit_keeps_counts_and_error_status_until_retry(self):
        window = self.controller.window
        window.tabs.setCurrentIndex(1)
        self.tap()
        with patch.object(self.database, "save", side_effect=OSError("disk full")):
            with patch.object(self.controller, "_show_error"):
                self.assertFalse(self.controller.request_exit())
        self.assertTrue(window.isVisible())
        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(window.trends.cards[0].value.text(), "1")
        self.assertEqual(window.save_label.text(), "保存失败，正在重试")
        self.assertTrue(window.save_label.isVisible())
        self.assertEqual(window.status_label.text(), "正在统计")
        self.tap()
        with patch.object(APPLICATION, "quit"):
            self.assertTrue(self.controller.request_exit())
        self.assertEqual(self.database.load()[(date.today().isoformat(), "1e")], 2)
        self.assertTrue(self.controller.closed)

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
        metrics = QFontMetricsF(QFont("Consolas", 7, QFont.Weight.DemiBold))
        for key, rect in self.controller.window.keyboard.key_rects():
            count = self.controller.window.keyboard.counts.get(key.key_id, 0)
            self.assertLessEqual(metrics.horizontalAdvance(f"{count:,}"), rect.width() - 8)

    def test_menu_click_switches_layout_without_changing_totals_or_capture(self):
        self.tap("1e")
        self.tap("47")
        self.controller.refresh()
        window = self.controller.window

        def select_tkl():
            action = window.layout_actions["tkl"]
            QTest.mouseMove(window.layout_menu, window.layout_menu.actionGeometry(action).center())
            QTest.mouseClick(window.layout_menu, Qt.MouseButton.LeftButton,
                             pos=window.layout_menu.actionGeometry(action).center())

        timeout = QTimer(window)
        timeout.setSingleShot(True)
        timeout.timeout.connect(window.layout_menu.close)
        timeout.start(1500)
        QTimer.singleShot(50, select_tkl)
        QTest.mouseClick(window.layout_button, Qt.MouseButton.LeftButton)
        QTest.qWait(100)
        timeout.stop()
        self.assertEqual(window.keyboard.keyboard_layout.layout_id, "tkl")
        self.assertTrue(window.layout_actions["tkl"].isChecked())
        self.assertFalse(window.layout_actions["full"].isChecked())
        self.assertEqual(window.total_label.text(), "2")
        self.assertIn("Num 7: 1", window.other_label.text().replace("\u00a0", " "))
        self.assertFalse(window.other_label.isHidden())
        self.tap("47")
        self.controller.refresh()
        self.assertEqual(window.total_label.text(), "3")
        self.assertIn("Num 7: 2", window.other_label.text().replace("\u00a0", " "))
        window.layout_actions["full"].trigger()
        self.assertTrue(window.other_label.isHidden())
        self.assertEqual(window.keyboard.counts["47"], 2)

    def test_layout_preference_and_counts_survive_window_recreation(self):
        self.tap()
        self.controller.window.set_keyboard_layout("laptop")
        self.assertTrue(self.controller.persistence.flush())
        restored = Controller(APPLICATION, self.database, FakeListener)
        try:
            restored.refresh()
            self.assertEqual(restored.window.keyboard.keyboard_layout.layout_id, "laptop")
            self.assertTrue(restored.window.layout_actions["laptop"].isChecked())
            self.assertEqual(restored.window.total_label.text(), "1")
            self.assertEqual(restored.window.keyboard.counts["1e"], 1)
            preferences = QSettings(str(self.database.path.parent / "preferences.ini"), QSettings.Format.IniFormat)
            self.assertEqual(preferences.value("keyboard/layout"), "laptop")
        finally:
            restored.dispose()
            restored.window.deleteLater()
            restored.menu.deleteLater()
            restored.deleteLater()

    def test_invalid_saved_layout_falls_back_to_full(self):
        for saved in ("unknown-layout", ["60", "65"]):
            with self.subTest(saved=saved):
                self.controller.settings.setValue("keyboard/layout", saved)
                window = StatsWindow(self.controller.settings)
                try:
                    self.assertEqual(window.keyboard.keyboard_layout.layout_id, "full")
                    self.assertTrue(window.layout_actions["full"].isChecked())
                finally:
                    window.allow_close = True
                    window.close()
                    window.deleteLater()

    def test_preference_failure_keeps_layout_and_counting_usable(self):
        with patch.object(self.controller.settings, "status", return_value=QSettings.Status.AccessError):
            self.controller.window.set_keyboard_layout("65")
        self.assertTrue(self.controller.window.layout_button.toolTip())
        self.tap()
        self.controller.refresh()
        self.assertEqual(self.controller.window.keyboard.keyboard_layout.layout_id, "65")
        self.assertEqual(self.controller.window.total_label.text(), "1")

    def test_switch_recomputes_heat_from_visible_keys_and_preserves_pressed_state(self):
        window = self.controller.window
        self.controller.model.counts[(date.today().isoformat(), "47")] = 1000
        self.controller.listener.on_key(PhysicalEvent(1, "1e", True))
        self.controller.refresh()
        self.assertEqual(window.keyboard.heat_maximum(), 1000)
        window.set_keyboard_layout("tkl")
        self.assertEqual(window.keyboard.heat_maximum(), 1)
        self.assertEqual(window.keyboard.pressed, {"1e"})
        self.assertEqual(window.total_label.text(), "1,001")
        self.assertEqual(window.keyboard.counts["47"], 1000)
        self.controller.listener.on_key(PhysicalEvent(1, "1e", False))
        self.controller.refresh()
        self.assertFalse(window.keyboard.pressed)

    def test_layout_switch_preserves_historical_range_and_unknown_keys(self):
        yesterday = date.today() - timedelta(days=1)
        self.controller.model.counts[(yesterday.isoformat(), "e0_64")] = 3
        self.controller.model.revision += 1
        window = self.controller.window
        window.date_edit.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        window.set_keyboard_layout("60")
        self.tap()
        self.controller.refresh()
        self.assertEqual(window.anchor, yesterday)
        self.assertEqual(window.total_label.text(), "3")
        self.assertIn("Scan E0_64: 3", window.other_label.text().replace("\u00a0", " "))
        window.go_today()
        self.assertEqual(window.total_label.text(), "1")
        self.assertTrue(window.other_label.isHidden())
        self.assertEqual(window.keyboard.keyboard_layout.layout_id, "60")

    def test_every_layout_fits_and_heatmap_pixels_reflect_counts(self):
        window = self.controller.window
        for layout in LAYOUTS:
            for size in ((1040, 570), (1260, 680)):
                with self.subTest(layout=layout.layout_id, size=size):
                    window.resize(*size)
                    window.set_keyboard_layout(layout.layout_id)
                    window.keyboard.set_counts({"1e": 100, "30": 1, "47": 10000}, set())
                    APPLICATION.processEvents()
                    keyboard = window.keyboard
                    rects = keyboard.key_rects()
                    image = keyboard.grab().toImage()
                    colors = {}
                    for index, (key, rect) in enumerate(rects):
                        self.assertGreaterEqual(rect.left(), 0)
                        self.assertGreaterEqual(rect.top(), 0)
                        self.assertLessEqual(rect.right(), keyboard.width())
                        self.assertLessEqual(rect.bottom(), keyboard.height())
                        for _, other in rects[index + 1:]:
                            self.assertFalse(rect.intersects(other))
                        colors[key.key_id] = image.pixelColor(
                            round((rect.left() + 7) * image.devicePixelRatio()),
                            round((rect.top() + rect.height() * 0.55) * image.devicePixelRatio()),
                        )
                    self.assertEqual(colors["2e"].name(), KEY_IDLE.lower())
                    self.assertGreater(colors["1e"].red(), colors["30"].red())
                    self.assertGreater(colors["30"].red(), colors["2e"].red())
                    self.assertEqual(
                        colors["1e"], heat_color(math.log1p(100) / math.log1p(keyboard.heat_maximum())),
                    )

    def test_extreme_counts_fit_all_layouts_including_half_height_arrows(self):
        window = self.controller.window
        window.resize(1040, 570)
        metrics = QFontMetricsF(QFont("Consolas", 7, QFont.Weight.DemiBold))
        for layout in LAYOUTS:
            with self.subTest(layout=layout.layout_id):
                window.set_keyboard_layout(layout.layout_id)
                window.keyboard.set_counts({key: 123456789012 for key in layout.key_ids}, set())
                APPLICATION.processEvents()
                for key, rect in window.keyboard.key_rects():
                    if key.key_id is None:
                        continue
                    text_width = metrics.horizontalAdvance("123,456,789,012")
                    if key.height < 1:
                        text_width += metrics.horizontalAdvance(SHORT_ARROW_LABELS[key.key_id]) + 10
                        self.assertLessEqual(metrics.height(), rect.height())
                    self.assertLessEqual(text_width, rect.width() - 10)

    def test_fast_tap_feedback_expires_without_changing_count_or_heat(self):
        self.controller.timer.stop()
        keyboard = self.controller.window.keyboard
        with patch("qiaoqiao.ui.monotonic", return_value=10):
            self.tap()
        self.controller.refresh()
        self.assertFalse(keyboard.pressed)
        self.assertIn("1e", keyboard._flashes)
        self.assertTrue(keyboard._feedback_timer.isActive())
        rect = next(rect for key, rect in keyboard.key_rects() if key.key_id == "1e")
        image = keyboard.grab().toImage()
        dpr = image.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(rect.center().x() * dpr), round(rect.top() * dpr)).name(),
                         MINT.lower())
        with patch("qiaoqiao.ui.monotonic", return_value=10.2):
            keyboard._advance_feedback()
        self.assertFalse(keyboard._flashes)
        self.assertFalse(keyboard._feedback_timer.isActive())
        self.assertEqual(keyboard.counts["1e"], 1)
        self.assertEqual(keyboard.heat_maximum(), 1)

    def test_repeat_does_not_restart_feedback_and_hidden_window_stops_it(self):
        keyboard = self.controller.window.keyboard
        with patch("qiaoqiao.ui.monotonic", return_value=10):
            self.controller.listener.on_key(PhysicalEvent(1, "1e", True))
        original = dict(keyboard._flashes)
        with patch("qiaoqiao.ui.monotonic", return_value=11):
            self.controller.listener.on_key(PhysicalEvent(1, "1e", True))
        self.assertEqual(keyboard._flashes, original)
        self.controller.window.hide()
        self.assertFalse(keyboard._feedback_timer.isActive())
        self.assertFalse(keyboard._flashes)
        self.tap("30")
        self.assertFalse(keyboard._feedback_timer.isActive())
        self.assertFalse(keyboard._flashes)

    def test_layout_switch_drops_hidden_feedback_and_fn_never_flashes(self):
        window = self.controller.window
        self.tap("47")
        self.assertIn("47", window.keyboard._flashes)
        window.set_keyboard_layout("laptop")
        self.assertNotIn("47", window.keyboard._flashes)
        self.tap("47")
        self.assertNotIn("47", window.keyboard._flashes)
        self.assertEqual(window.total_label.text(), "1")
        self.controller.refresh()
        self.assertEqual(window.total_label.text(), "2")
        self.assertIsNone(next(key for key in window.keyboard.keyboard_layout.keys if key.label == "Fn").key_id)

    def test_pixel_buttons_keep_keyboard_activation_and_disabled_date_controls(self):
        window = self.controller.window
        week = window.period_buttons["week"]
        week.setFocus()
        QTest.keyClick(week, Qt.Key.Key_Space)
        self.assertEqual(window.period, "week")
        self.assertTrue(week.isChecked())
        self.assertFalse(window.period_buttons["day"].isChecked())
        QTest.mouseClick(window.period_buttons["all"], Qt.MouseButton.LeftButton)
        self.assertFalse(window.previous.isEnabled())
        self.assertFalse(window.next.isEnabled())
        self.assertFalse(window.date_edit.isEnabled())
        self.assertFalse(window.today_button.isEnabled())
        self.assertTrue(window.layout_button.isEnabled())

    def test_error_theme_recovers_without_leaving_local_styles(self):
        window = self.controller.window
        self.controller.persistence.error = "disk full"
        self.controller.listener.last_error = "input error"
        self.controller.refresh()
        APPLICATION.processEvents()
        self.assertEqual(window.save_label.property("state"), "error")
        self.assertEqual(window.status_label.property("state"), "error")
        self.assertEqual(window.save_label.palette().color(window.save_label.foregroundRole()).name(), ERROR.lower())
        self.assertIn("保存失败", window.save_label.text())
        self.controller.persistence.error = None
        self.controller.listener.last_error = None
        self.controller.refresh()
        APPLICATION.processEvents()
        self.assertEqual(window.status_label.property("state"), "normal")
        self.assertEqual(window.save_label.palette().color(window.save_label.foregroundRole()).name(), MUTED.lower())
        self.assertFalse(window.save_label.styleSheet())

    def test_pixel_date_popup_keeps_keyboard_selection_and_today_navigation(self):
        window = self.controller.window
        edit = window.date_edit
        QTest.mouseClick(edit, Qt.MouseButton.LeftButton, pos=QPoint(edit.width() - 12, edit.height() // 2))
        APPLICATION.processEvents()
        calendar = edit.calendarWidget()
        self.assertTrue(calendar.isVisible())
        view = calendar.findChild(QAbstractItemView)
        QTest.keyClick(view, Qt.Key.Key_Left)
        QTest.keyClick(view, Qt.Key.Key_Return)
        APPLICATION.processEvents()
        self.assertEqual(window.anchor, date.today() - timedelta(days=1))
        self.assertFalse(calendar.isVisible())
        QTest.mouseClick(window.today_button, Qt.MouseButton.LeftButton)
        self.assertEqual(window.anchor, date.today())

    def test_very_large_total_scrolls_without_widening_the_window(self):
        window = self.controller.window
        window.resize(1040, 570)
        number = 10 ** 30
        self.controller.model.counts[(date.today().isoformat(), "1e")] = number
        self.controller.model.revision += 1
        self.controller.refresh()
        APPLICATION.processEvents()
        self.assertEqual(window.total_label.text(), f"{number:,}")
        self.assertEqual(window.width(), 1040)
        self.assertGreater(window.total_scroll.horizontalScrollBar().maximum(), 0)
        self.assertGreaterEqual(window.total_label.width(), window.total_label.sizeHint().width())


class MilestoneAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "counts.sqlite3")
        self.database.initialize()
        self.settings = QSettings(str(self.database.path.parent / "preferences.ini"), QSettings.Format.IniFormat)
        self.controllers = []
        self.today = date.today()
        self.now = datetime.combine(self.today, datetime.min.time()).replace(hour=12)
        patches = {
            "clock": patch("qiaoqiao.app.datetime"),
            "monotonic": patch("qiaoqiao.app.monotonic", return_value=100.0),
            "notifications": patch.object(QSystemTrayIcon, "showMessage"),
            "supports_messages": patch.object(QSystemTrayIcon, "supportsMessages", return_value=True),
            "tray_available": patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True),
        }
        for name, patcher in patches.items():
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.clock.now.return_value = self.now

    def tearDown(self):
        for controller in self.controllers:
            controller.dispose()
            controller.window.deleteLater()
            controller.menu.deleteLater()
            controller.deleteLater()
        APPLICATION.processEvents()
        self.temp.cleanup()

    def make_controller(self, total=None):
        if total is not None:
            self.database.save({(self.today.isoformat(), "1e"): total})
        controller = Controller(APPLICATION, self.database, FakeListener)
        self.controllers.append(controller)
        controller._tray_tip_shown = True
        controller.start()
        # Tests drive the existing timer explicitly; no OS notifications escape
        # the mock and no real keyboard input is generated.
        controller.timer.stop()
        return controller

    def tap(self, controller, count=1, key="1e", device=1):
        for _ in range(count):
            controller.listener.on_key(PhysicalEvent(device, key, True))
            controller.listener.on_key(PhysicalEvent(device, key, False))

    def test_hidden_threshold_waits_for_tick_without_callback_io_or_history_scan(self):
        controller = self.make_controller(999)
        controller.window.close()
        with patch.object(controller.settings, "sync") as sync:
            with patch.object(controller.model, "totals") as totals:
                self.tap(controller)
                self.tap(controller, key="30")
                totals.assert_not_called()
            sync.assert_not_called()
        self.notifications.assert_not_called()
        controller.tick()
        controller.tick()
        self.notifications.assert_called_once()
        self.assertIn("今日敲击已达 1,000 次", self.notifications.call_args.args[1])
        self.assertFalse(controller.window.isVisible())
        self.assertEqual(controller.settings.value("milestones/last_threshold"), 1000)
        self.assertEqual(controller.settings.value("milestones/last_day"), self.today.isoformat())

    def test_pet_celebrates_new_threshold_once_even_without_system_notifications(self):
        controller = self.make_controller(9999)
        controller.window.close()
        self.supports_messages.return_value = False
        with patch.object(controller.pet, "celebrate", wraps=controller.pet.celebrate) as celebrate:
            self.tap(controller)
            self.tap(controller, 20)
            celebrate.assert_called_once_with(10000)
        controller.pet._animate()
        self.assertEqual(controller.pet._behavior, "celebrate_big")
        with self.assertLogs("qiaoqiao", level="WARNING"):
            controller.tick()
        self.notifications.assert_not_called()
        self.assertEqual(controller.milestones.handled, 10000)

    def test_hidden_pet_does_not_replay_threshold_on_show_or_tray_delivery(self):
        controller = self.make_controller(999)
        self.tap(controller)
        self.assertIsNone(controller.pet._pending_celebration)
        controller.window.close()
        controller.tick()
        controller.pet._animate()
        self.assertIsNone(controller.pet._pending_celebration)
        self.assertEqual(controller.pet._behavior, "idle")
        self.notifications.assert_called_once()

    def test_disabling_milestones_cancels_pet_and_new_day_clears_deferred_celebration(self):
        controller = self.make_controller(999)
        controller.window.close()
        self.tap(controller)
        controller.pet._animate()
        self.assertEqual(controller.pet._behavior, "celebrate")
        controller.milestone_action.setChecked(False)
        self.assertEqual(controller.pet._behavior, "idle")
        self.tap(controller, 1000)
        self.assertIsNone(controller.pet._pending_celebration)
        controller.milestone_action.setChecked(True)
        self.assertIsNone(controller.pet._pending_celebration)
        self.tap(controller, 1000)
        self.assertIsNotNone(controller.pet._pending_celebration)
        self.clock.now.return_value = self.now + timedelta(days=1)
        controller.tick()
        self.assertIsNone(controller.pet._pending_celebration)

    def test_repeat_and_release_do_not_retrigger_but_other_device_counts(self):
        controller = self.make_controller(998)
        down = PhysicalEvent(1, "1e", True)
        for _ in range(10):
            controller.listener.on_key(down)
        controller.tick()
        self.notifications.assert_not_called()
        controller.listener.on_key(PhysicalEvent(2, "1e", True))
        controller.tick()
        for _ in range(10):
            controller.listener.on_key(down)
        controller.listener.on_key(PhysicalEvent(1, "1e", False))
        self.monotonic.return_value = 110
        controller.tick()
        self.notifications.assert_called_once()
        self.assertEqual(controller.milestones.total, 1000)

    def test_visible_window_gets_each_thousand_after_notification_spacing(self):
        controller = self.make_controller(999)
        self.tap(controller)
        controller.tick()
        self.tap(controller, 1000)
        controller.tick()
        self.notifications.assert_called_once()
        self.monotonic.return_value = 106
        controller.tick()
        self.assertEqual(self.notifications.call_count, 2)
        self.assertIn("2,000", self.notifications.call_args.args[1])
        self.assertTrue(controller.window.isVisible())

    def test_startup_does_not_backfill_and_uses_absolute_daily_threshold(self):
        controller = self.make_controller(4320)
        controller.tick()
        self.tap(controller, 679)
        controller.tick()
        self.notifications.assert_not_called()
        self.tap(controller)
        controller.tick()
        self.assertIn("5,000", self.notifications.call_args.args[1])

    def test_restart_restores_attempted_checkpoint_even_before_counts_save(self):
        controller = self.make_controller(999)
        self.tap(controller)
        # Exercise the crash-window case without touching production data:
        # the notification checkpoint is saved, but counts stay at 999 on disk.
        with patch.object(controller.persistence, "tick"):
            controller.tick()
        controller.dispose()
        restored = self.make_controller()
        self.notifications.reset_mock()
        self.tap(restored)
        restored.tick()
        self.notifications.assert_not_called()
        self.tap(restored, 1000)
        restored.tick()
        self.assertIn("2,000", self.notifications.call_args.args[1])

    def test_saved_restart_skips_existing_threshold_and_old_date_checkpoint(self):
        self.settings.setValue("milestones/last_day", (self.today - timedelta(days=1)).isoformat())
        self.settings.setValue("milestones/last_threshold", 50000)
        self.settings.sync()
        controller = self.make_controller(999)
        self.tap(controller)
        controller.tick()
        self.assertIn("1,000", self.notifications.call_args.args[1])
        self.assertTrue(controller.persistence.flush())
        controller.dispose()
        restored = self.make_controller()
        self.notifications.reset_mock()
        restored.tick()
        self.notifications.assert_not_called()
        self.tap(restored, 1000)
        restored.tick()
        self.assertIn("2,000", self.notifications.call_args.args[1])

    def test_tray_menu_mouse_click_toggles_and_persists_preference(self):
        controller = self.make_controller(0)
        action = controller.milestone_action
        self.assertTrue(action.isChecked())
        for enabled in (False, True):
            controller.menu.popup(controller.window.mapToGlobal(QPoint(30, 30)))
            QTest.qWait(30)
            position = controller.menu.actionGeometry(action).center()
            QTest.mouseMove(controller.menu, position)
            QTest.mouseClick(controller.menu, Qt.MouseButton.LeftButton, pos=position)
            self.assertEqual(action.isChecked(), enabled)
            self.assertEqual(controller.milestones.enabled, enabled)
            self.settings.sync()
            self.assertEqual(self.settings.value("milestones/enabled", type=bool), enabled)
            self.assertFalse(controller.menu.isVisible())

    def test_toggling_discards_backlog_and_persists_disabled_preference(self):
        controller = self.make_controller(999)
        self.tap(controller)
        controller.milestone_action.trigger()
        self.assertFalse(controller.milestone_action.isChecked())
        self.tap(controller, 1000)
        controller.milestone_action.trigger()
        controller.tick()
        self.notifications.assert_not_called()
        self.tap(controller, 1000)
        controller.tick()
        self.assertIn("3,000", self.notifications.call_args.args[1])
        controller.milestone_action.trigger()
        self.assertTrue(controller.persistence.flush())
        controller.dispose()
        restored = self.make_controller()
        self.assertFalse(restored.milestones.enabled)
        self.assertFalse(restored.milestone_action.isChecked())

    def test_midnight_discards_old_pending_and_does_not_recount_held_key(self):
        controller = self.make_controller(999)
        down = PhysicalEvent(1, "1e", True)
        controller.listener.on_key(down)
        self.clock.now.return_value = self.now + timedelta(days=1)
        controller.tick()
        controller.listener.on_key(down)
        self.assertEqual(controller.milestones.total, 0)
        self.notifications.assert_not_called()
        controller.listener.on_key(PhysicalEvent(1, "1e", False))
        self.tap(controller, 1000)
        controller.tick()
        self.notifications.assert_called_once()
        self.assertEqual(controller.settings.value("milestones/last_day"),
                         (self.today + timedelta(days=1)).isoformat())

    def test_first_event_after_date_change_is_not_swallowed_into_baseline(self):
        tomorrow = self.today + timedelta(days=1)
        self.database.save({(tomorrow.isoformat(), "1e"): 999})
        controller = self.make_controller(5000)
        self.clock.now.return_value = self.now + timedelta(days=1)
        self.tap(controller)
        controller.tick()
        self.notifications.assert_called_once()
        self.assertIn("1,000", self.notifications.call_args.args[1])
        self.assertEqual(controller.milestones.total, 1000)

    def test_history_period_and_layout_do_not_filter_today_milestone(self):
        yesterday = self.today - timedelta(days=1)
        self.database.save({
            (self.today.isoformat(), "47"): 998,
            (self.today.isoformat(), "e0_64"): 1,
            (yesterday.isoformat(), "1e"): 3000,
        })
        controller = self.make_controller()
        window = controller.window
        window.date_edit.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        window.set_keyboard_layout("60")
        self.tap(controller, key="47")
        controller.tick()
        self.assertIn("1,000", self.notifications.call_args.args[1])
        self.assertEqual(window.total_label.text(), "3,000")
        window.set_period("all")
        self.monotonic.return_value = 110
        controller.tick()
        self.notifications.assert_called_once()

    def test_paused_or_failed_listener_defers_pending_until_recovery(self):
        controller = self.make_controller(999)
        self.tap(controller)
        for name, value, restored in (
            ("locked", True, False), ("suspended", True, False),
            ("active", False, True), ("last_error", "input error", None),
        ):
            with self.subTest(state=name):
                setattr(controller.listener, name, value)
                controller.tick()
                self.notifications.assert_not_called()
                setattr(controller.listener, name, restored)
        controller.tick()
        self.notifications.assert_called_once()

    def test_save_warning_has_priority_and_recovery_coalesces_backlog(self):
        controller = self.make_controller(999)
        self.tap(controller)
        with patch.object(controller.persistence, "tick"):
            controller.persistence.error = "disk full"
            with self.assertLogs("qiaoqiao", level="ERROR"):
                controller.tick()
            self.assertEqual(self.notifications.call_args.args[2], QSystemTrayIcon.MessageIcon.Warning)
            self.tap(controller, 2000)
            controller.tick()
            self.notifications.assert_called_once()
            controller.persistence.error = None
            controller.tick()
            self.notifications.assert_called_once()
            self.monotonic.return_value = 106
            controller.tick()
        self.assertEqual(self.notifications.call_count, 2)
        self.assertIn("3,000", self.notifications.call_args.args[1])

    def test_first_hide_tip_is_not_immediately_replaced(self):
        controller = self.make_controller(999)
        controller._tray_tip_shown = False
        self.tap(controller)
        controller.window.close()
        controller.tick()
        self.notifications.assert_called_once()
        self.assertIn("仍在统计", self.notifications.call_args.args[0])
        self.monotonic.return_value = 104
        controller.tick()
        self.assertEqual(self.notifications.call_count, 2)
        self.assertIn("1,000", self.notifications.call_args.args[1])

    def test_first_hide_tip_does_not_shorten_existing_milestone_cooldown(self):
        controller = self.make_controller(999)
        controller._tray_tip_shown = False
        self.tap(controller)
        controller.tick()
        self.monotonic.return_value = 101
        controller.window.close()
        self.tap(controller, 1000)
        self.monotonic.return_value = 104
        controller.tick()
        self.assertEqual(self.notifications.call_count, 2)
        self.assertEqual(controller.milestones.pending, 2000)
        self.monotonic.return_value = 105
        controller.tick()
        self.assertEqual(self.notifications.call_count, 3)
        self.assertIn("2,000", self.notifications.call_args.args[1])

    def test_unsupported_notifications_consume_threshold_without_retry_loop(self):
        controller = self.make_controller(999)
        self.supports_messages.return_value = False
        self.tap(controller)
        with self.assertLogs("qiaoqiao", level="WARNING"):
            controller.tick()
        self.supports_messages.return_value = True
        controller.tick()
        self.notifications.assert_not_called()
        self.assertEqual(controller.milestones.handled, 1000)

    def test_notification_exception_does_not_interrupt_counting_or_retry(self):
        controller = self.make_controller(999)
        self.notifications.side_effect = RuntimeError("notification unavailable")
        self.tap(controller)
        with self.assertLogs("qiaoqiao", level="ERROR"):
            controller.tick()
        self.notifications.side_effect = None
        self.monotonic.return_value = 110
        self.tap(controller)
        controller.tick()
        self.notifications.assert_called_once()
        self.assertTrue(controller.persistence.flush())
        self.assertEqual(self.database.load()[(self.today.isoformat(), "1e")], 1001)
        self.assertIsNone(controller.listener.last_error)

    def test_preference_failure_is_visible_but_preserves_counting_and_memory_dedup(self):
        controller = self.make_controller(999)
        with patch.object(controller.settings, "status", return_value=QSettings.Status.AccessError):
            with self.assertLogs("qiaoqiao", level="WARNING"):
                controller.milestone_action.trigger()
                controller.milestone_action.trigger()
                self.tap(controller)
                controller.tick()
            self.assertIn("偏好保存失败", controller.milestone_action.text())
            self.assertTrue(controller.milestone_action.toolTip())
            self.monotonic.return_value = 110
            controller.tick()
            self.notifications.assert_called_once()
        controller.milestone_action.trigger()
        self.assertEqual(controller.milestone_action.text(), "千次里程碑提醒")
        self.assertEqual(controller.milestones.total, 1000)

    def test_invalid_preferences_fall_back_without_blocking_startup(self):
        for saved_day, threshold in (("invalid", 1000), ([], 1000),
                                     (self.today.isoformat(), -1000), (self.today.isoformat(), "bad"),
                                     (self.today.isoformat(), [1000]), (self.today.isoformat(), 1500),
                                     (self.today.isoformat(), True)):
            with self.subTest(day=saved_day, threshold=threshold):
                self.settings.setValue("milestones/last_day", saved_day)
                self.settings.setValue("milestones/last_threshold", threshold)
                self.settings.setValue("milestones/enabled", ["invalid"])
                self.settings.sync()
                controller = self.make_controller(999)
                self.assertTrue(controller.milestones.enabled)
                self.assertEqual(controller.milestones.handled, 0)
                controller.dispose()

    def test_notification_click_restores_window_without_repeating_milestone(self):
        controller = self.make_controller(999)
        controller.window.close()
        self.tap(controller)
        controller.tick()
        controller.tray.messageClicked.emit()
        self.assertTrue(controller.window.isVisible())
        self.assertEqual(controller.window.total_label.text(), "1,000")
        controller.tick()
        self.notifications.assert_called_once()

    def test_exit_and_disposal_do_not_deliver_pending_notifications(self):
        controller = self.make_controller(999)
        self.tap(controller)
        controller.exiting = True
        with patch.object(controller.persistence, "tick") as persistence_tick:
            controller.tick()
            persistence_tick.assert_not_called()
        controller.exiting = False
        with patch.object(APPLICATION, "quit"):
            self.assertTrue(controller.request_exit())
        controller.tick()
        self.notifications.assert_not_called()
        self.assertEqual(self.database.load()[(self.today.isoformat(), "1e")], 1000)

    def test_failed_exit_keeps_pending_for_recovery(self):
        controller = self.make_controller(999)
        self.tap(controller)
        with patch.object(self.database, "save", side_effect=OSError("disk full")):
            with patch.object(controller, "_show_error"):
                self.assertFalse(controller.request_exit())
        controller.timer.stop()
        self.notifications.assert_not_called()
        self.assertEqual(controller.milestones.pending, 1000)
        self.assertTrue(controller.persistence.flush())
        controller.tick()
        self.notifications.assert_called_once()


class MilestoneMessageTests(unittest.TestCase):
    def test_exact_thousands_and_tier_boundaries_have_complete_numbers(self):
        for threshold in (1000, 2000, 4000, 5000, 9000, 10000, 11000, 19000, 20000,
                          23000, 30000, 40000, 50000, 51000, 100000, 1000000):
            with self.subTest(threshold=threshold):
                title, message = milestone_message(threshold)
                self.assertIn(f"今日敲击已达 {threshold:,} 次。", message)
                self.assertEqual("万次里程碑" in title, threshold % 10000 == 0)
                self.assertNotIn("纪录", message)
                if threshold != 1000:
                    self.assertNotIn("第一个", message)
                if threshold != 20000:
                    self.assertNotIn("两万次达成", message)
                if threshold >= 50000:
                    self.assertIn("双手", message)

    def test_encouragement_rotates_within_each_tier(self):
        for floor in (1000, 5000, 10000, 20000, 30000, 50000):
            copies = {milestone_message(floor + step * 1000)[1].split("\n")[1] for step in (1, 2, 3)}
            self.assertEqual(len(copies), 3)


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
