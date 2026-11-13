import ctypes
import json
import sys
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QContextMenuEvent, QEnterEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from qiaoqiao.pet import DOZE_AFTER, PET_SIZE, SLEEP_AFTER, PetWindow, load_actions, snap_placement


APPLICATION = QApplication.instance() or QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)


class PlacementTests(unittest.TestCase):
    def test_free_and_four_edges_with_negative_screen_origin(self):
        area = QRect(-1920, -240, 1920, 1040)
        size = QSize(128, 128)
        for position, expected in (
            (QPoint(-1200, 100), ""),
            (QPoint(-1900, 100), "left"),
            (QPoint(-140, 100), "right"),
            (QPoint(-1200, -225), "top"),
            (QPoint(-1200, 670), "bottom"),
        ):
            with self.subTest(edge=expected):
                result, edge = snap_placement(position, area, size)
                self.assertEqual(edge, expected)
                self.assertTrue(area.contains(QRect(result, size)))

    def test_corner_ties_keep_previous_edge_otherwise_peek(self):
        area = QRect(0, 0, 800, 600)
        position = QPoint(0, 0)
        self.assertEqual(snap_placement(position, area, PET_SIZE)[1], "left")
        self.assertEqual(snap_placement(position, area, PET_SIZE, "top")[1], "top")


class PetWindowTests(unittest.TestCase):
    def setUp(self):
        clock = patch("qiaoqiao.pet.monotonic", return_value=100.0)
        self.now = clock.start()
        self.addCleanup(clock.stop)
        cursor = patch("qiaoqiao.pet.QCursor.pos", return_value=QPoint(-99999, -99999))
        self.cursor = cursor.start()
        self.addCleanup(cursor.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "preferences.ini"), QSettings.Format.IniFormat)
        self.menu = QMenu()
        self.menu.addAction("打开主界面")
        self.pet = PetWindow(self.settings, self.menu)
        self.pet.show()
        APPLICATION.processEvents()

    def tearDown(self):
        self.pet.close()
        self.menu.close()
        self.pet.deleteLater()
        self.menu.deleteLater()
        APPLICATION.processEvents()
        self.temp.cleanup()

    def test_sprite_mask_clips_peeking_within_widget(self):
        area = QRect(0, 0, 800, 600)
        self.pet._place(QPoint(0, 150), area, "left")
        region = self.pet.mask()
        self.assertTrue(region.contains(QPoint(10, 64)))
        self.assertFalse(region.contains(QPoint(100, 64)))
        self.assertFalse(region.contains(QPoint(0, 0)))
        self.pet._place(QPoint(672, 150), area, "right")
        region = self.pet.mask()
        self.assertTrue(region.contains(QPoint(115, 64)))
        self.assertFalse(region.contains(QPoint(20, 64)))

    def test_drag_release_snaps_and_persists_screen_and_edge(self):
        area = APPLICATION.primaryScreen().availableGeometry()
        self.pet._place(QPoint(area.left(), area.top() + 100), area, "left")
        self.pet._screen_name = APPLICATION.primaryScreen().name()
        QTest.mousePress(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(32, 64))
        QTest.mouseMove(self.pet, QPoint(80, 64), delay=10)
        self.assertEqual(self.pet._action, "drag.pickup")
        self.pet._advance_animation(150)
        self.assertEqual(self.pet._action, "drag.struggle")
        QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 64))
        self.assertEqual(self.pet._edge, "")
        self.assertEqual(self.pet._action, "drag.release")
        self.assertEqual(self.settings.value("pet/edge"), "")
        self.assertEqual(self.settings.value("pet/screen"), APPLICATION.primaryScreen().name())
        self.assertTrue(area.contains(self.pet.geometry()))

    def test_frame_timing_blink_and_settle_return_to_idle(self):
        self.pet._start_action("idle")
        position = self.pet.pos()
        for elapsed, expected in ((999, 0), (1000, 1), (1450, 2), (2100, 3), (3000, 0)):
            self.pet._advance_animation(elapsed)
            self.assertEqual(self.pet._frame_index, expected)
            self.assertEqual(self.pet.pos(), position)
        self.pet._advance_animation(6000)
        self.assertEqual(self.pet._action, "blink")
        self.pet._advance_animation(70)
        self.assertEqual(self.pet._frame_index, 2)
        self.pet._advance_animation(220)
        self.assertEqual(self.pet._action, "idle")
        self.pet._start_action("settle")
        self.pet._advance_animation(100)
        self.assertEqual(self.pet._frame_index, 2)
        self.pet._advance_animation(300)
        self.assertEqual(self.pet._action, "idle")
        self.assertEqual(self.pet.pos(), position)

    def test_timer_runs_only_while_visible_and_resumes_resting_pose(self):
        self.pet._start_action("blink")
        with patch.object(self.pet, "_advance_animation", wraps=self.pet._advance_animation) as advance:
            timeout = QSignalSpy(self.pet._animation_timer.timeout)
            self.assertTrue(timeout.wait(2000))
            advance.assert_called()
        self.assertTrue(self.pet._animation_timer.isActive())
        self.pet.hide()
        frame = self.pet._frame_index
        self.assertFalse(self.pet._animation_timer.isActive())
        QTest.qWait(240)
        self.assertEqual(self.pet._frame_index, frame)
        self.pet.show()
        self.assertEqual(self.pet._action, self.pet._edge or "idle")
        self.assertEqual(self.pet._frame_index, 0)
        self.assertTrue(self.pet._animation_timer.isActive())
        self.pet.close()
        self.assertFalse(self.pet._animation_timer.isActive())

    def test_edge_frames_keep_contact_at_screen_boundary_without_extra_clipping(self):
        area = QRect(-1920, -200, 1920, 1000)
        for edge in ("left", "right", "top", "bottom"):
            with self.subTest(edge=edge):
                self.pet._place(area.center(), area, edge)
                self.assertEqual(self.pet._action, edge)
                position = self.pet.pos()
                action = self.pet._actions[edge]
                elapsed = 0
                for frame in action.frames:
                    self.pet._advance_animation(elapsed)
                    self.assertEqual(self.pet.pos(), position)
                    expected = frame.mask.translated(action.offset)
                    self.assertEqual(self.pet.mask(), expected)
                    self.assertTrue(self.pet.rect().contains(expected.boundingRect()))
                    bounds = self.pet.mask().boundingRect().translated(self.pet.pos())
                    if edge == "left":
                        self.assertEqual(bounds.left(), area.left())
                    elif edge == "right":
                        self.assertEqual(bounds.right(), area.right())
                    elif edge == "top":
                        self.assertEqual(bounds.top(), area.top())
                    else:
                        self.assertEqual(bounds.bottom(), area.bottom())
                    elapsed += frame.duration_ms
                self.pet._advance_animation(action.duration_ms * 100 + 4700)
                self.assertEqual(self.pet._action, edge)
                self.assertGreater(self.pet._animation_timer.interval(), 0)

    def test_animation_mask_updates_and_matches_rendered_alpha(self):
        self.pet._start_action("idle")
        initial = self.pet.mask()
        self.pet._advance_animation(1000)
        self.assertNotEqual(self.pet.mask(), initial)
        for name, action in self.pet._actions.items():
            with self.subTest(action=name):
                self.pet._start_action(name)
                image = self.pet.grab().toImage()
                scale = image.devicePixelRatio()
                for y in range(self.pet.height()):
                    for x in range(self.pet.width()):
                        alpha = image.pixelColor(round(x * scale), round(y * scale)).alpha()
                        self.assertEqual(bool(alpha), self.pet.mask().contains(QPoint(x, y)))

    def test_click_does_not_drag_and_drag_keeps_pointer_offset(self):
        area = APPLICATION.primaryScreen().availableGeometry()
        self.pet._place(area.topLeft() + QPoint(200, 200), area, "")
        position = self.pet.pos()
        press = QPoint(60, 64)
        QTest.mouseClick(self.pet, Qt.MouseButton.LeftButton, pos=press)
        self.assertEqual(self.pet._action, "idle")
        self.assertEqual(self.pet.pos(), position)
        QTest.mousePress(self.pet, Qt.MouseButton.LeftButton, pos=press)
        QTest.mouseMove(self.pet, press + QPoint(40, 20), delay=10)
        self.assertEqual(self.pet._action, "drag.pickup")
        self.assertEqual(self.pet.pos(), position + QPoint(40, 20))
        self.pet.hide()
        self.assertFalse(self.pet._dragging)
        self.assertIsNone(self.pet._press_global)
        self.assertFalse(self.pet._animation_timer.isActive())
        self.pet.show()
        self.assertEqual(self.pet._action, self.pet._edge or "idle")

    def test_edge_release_uses_edge_action_instead_of_floor_settle(self):
        area = APPLICATION.primaryScreen().availableGeometry()
        self.pet._place(area.topLeft() + QPoint(250, 200), area, "")
        QTest.mousePress(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        QTest.mouseMove(self.pet, QPoint(84, 64), delay=10)
        self.pet.move(area.topLeft() + QPoint(4, 200))
        QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        self.assertEqual(self.pet._action, "left")
        self.assertEqual(self.settings.value("pet/edge"), "left")

    def test_topmost_can_toggle_without_hiding_pet(self):
        self.assertTrue(self.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        position = self.pet.pos()
        self.pet.set_topmost(False)
        self.assertTrue(self.pet.isVisible())
        self.assertEqual(self.pet.pos(), position)
        self.assertTrue(self.pet._animation_timer.isActive())
        self.assertFalse(self.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.pet.set_topmost(True)
        self.assertTrue(self.pet.isVisible())
        self.assertEqual(self.pet.pos(), position)
        self.assertTrue(self.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_double_click_opens_main_window_and_context_menu_appears(self):
        opened = QSignalSpy(self.pet.open_requested)
        QTest.mouseDClick(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        self.assertEqual(opened.count(), 1)
        context = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, QPoint(64, 64), self.pet.mapToGlobal(QPoint(64, 64)),
        )
        QApplication.sendEvent(self.pet, context)
        APPLICATION.processEvents()
        self.assertTrue(self.menu.isVisible())
        self.menu.hide()

    def test_invalid_saved_location_falls_back_inside_screen(self):
        self.settings.setValue("pet/x", "nan")
        self.settings.setValue("pet/y", "invalid")
        self.settings.setValue("pet/edge", "unknown")
        self.pet._restore_placement()
        self.assertEqual(self.pet._edge, "")
        self.assertTrue(APPLICATION.primaryScreen().availableGeometry().contains(self.pet.geometry()))

    def test_saved_edge_and_position_survive_window_recreation(self):
        screen = APPLICATION.primaryScreen()
        area = screen.availableGeometry()
        self.pet._screen_name = screen.name()
        self.pet._place(QPoint(area.right(), area.top() + 100), area, "right")
        self.pet._save_placement()
        restored = PetWindow(self.settings, self.menu)
        try:
            self.assertEqual(restored._edge, "right")
            self.assertEqual(restored.pos(), self.pet.pos())
            self.assertEqual(restored._action, "right")
            self.assertFalse(restored._animation_timer.isActive())
        finally:
            restored.close()
            restored.deleteLater()

    def finish_action(self):
        self.pet._advance_animation(self.pet._actions[self.pet._action].duration_ms)

    def enter_pet(self):
        self.pet.enterEvent(QEnterEvent(QPointF(64, 64), QPointF(64, 64),
                                       QPointF(self.cursor.return_value)))

    def test_key_burst_finishes_tap_then_loops_without_restarting_each_key(self):
        self.pet.on_key_press()
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.tap")
        self.pet._advance_animation(100)
        for _ in range(50):
            self.now.return_value += 0.002
            self.pet.on_key_press()
            self.pet._animate()
        self.finish_action()
        self.assertEqual(self.pet._action, "free.typing")
        with patch.object(self.pet, "_start_action", wraps=self.pet._start_action) as start:
            for _ in range(100):
                self.now.return_value += 0.002
                self.pet.on_key_press()
                self.pet._animate()
            start.assert_not_called()
        self.now.return_value += 0.7
        self.pet._animate()
        self.assertEqual(self.pet._action, "idle")
        self.assertFalse(self.pet._key_pending)

    def test_celebration_preempts_typing_merges_and_expires_during_drag(self):
        self.pet.on_key_press()
        self.pet._animate()
        self.pet.celebrate(1000)
        self.pet.celebrate(10000)
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.celebrate_big")
        self.pet.on_key_press()
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.celebrate_big")
        self.pet._dragging = True
        self.pet._start_action("drag.struggle")
        self.pet.celebrate(11000)
        self.now.return_value += 6
        self.pet._animate()
        self.pet._dragging = False
        self.pet._start_action("idle")
        self.pet._animate()
        self.assertIsNone(self.pet._pending_celebration)
        self.assertEqual(self.pet._action, "idle")

    def test_queued_celebration_after_short_drag_uses_new_edge(self):
        self.pet._dragging = True
        self.pet._start_action("drag.struggle")
        self.pet.celebrate(1000)
        self.pet._animate()
        self.assertEqual(self.pet._action, "drag.struggle")
        area = APPLICATION.primaryScreen().availableGeometry()
        self.pet._place(area.topLeft(), area, "top")
        self.pet._clear_press()
        self.pet._animate()
        self.assertEqual(self.pet._action, "top.celebrate")

    def test_single_click_waits_for_double_click_interval_and_is_cancelled_by_double(self):
        opened = QSignalSpy(self.pet.open_requested)
        QTest.mouseClick(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        self.pet._animate()
        self.assertEqual(self.pet._action, "idle")
        self.now.return_value += QApplication.doubleClickInterval() / 1000 + 0.01
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.click")
        self.assertEqual(opened.count(), 0)
        self.finish_action()
        QTest.mouseClick(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        QTest.mouseDClick(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        self.now.return_value += 1
        self.pet._animate()
        self.assertEqual(opened.count(), 1)
        self.assertEqual(self.pet._click_due, 0)
        self.assertEqual(self.pet._action, "idle")

    def test_drag_cancels_single_click_and_does_not_open_main_window(self):
        opened = QSignalSpy(self.pet.open_requested)
        QTest.mouseClick(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        QTest.mousePress(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        QTest.mouseMove(self.pet, QPoint(94, 64), delay=10)
        self.assertEqual(self.pet._click_due, 0)
        self.now.return_value += 1
        self.pet._animate()
        self.assertEqual(opened.count(), 0)
        self.assertEqual(self.pet._action, "drag.pickup")

    def test_hover_debounce_gaze_and_leave_use_current_pose(self):
        area = APPLICATION.primaryScreen().availableGeometry()
        self.pet._place(area.center(), area, "right")
        self.cursor.return_value = self.pet.mapToGlobal(QPoint(110, 64))
        self.enter_pet()
        self.pet._animate()
        self.assertEqual(self.pet._action, "right")
        self.now.return_value += 0.16
        self.pet._animate()
        self.assertEqual(self.pet._action, "right.hover")
        self.finish_action()
        self.assertEqual(self.pet._action, "right.hover_hold")
        with patch.object(self.pet, "_gaze_motion", return_value="hover_left"):
            self.pet._animate()
        self.assertEqual(self.pet._action, "right.hover_left")
        self.pet.leaveEvent(QEvent(QEvent.Type.Leave))
        self.now.return_value += 0.16
        self.pet._animate()
        self.assertTrue(self.pet._hovered, "Moving alpha pixels must not end stationary hover")
        self.cursor.return_value = QPoint(-99999, -99999)
        self.pet.leaveEvent(QEvent(QEvent.Type.Leave))
        self.now.return_value += 0.16
        self.pet._animate()
        self.assertEqual(self.pet._action, "right.hover_leave")
        self.finish_action()
        self.assertEqual(self.pet._action, "right")

    def test_brief_hover_does_not_interrupt_and_click_returns_to_gaze(self):
        self.cursor.return_value = self.pet.mapToGlobal(QPoint(64, 64))
        self.enter_pet()
        self.pet.leaveEvent(QEvent(QEvent.Type.Leave))
        self.cursor.return_value = QPoint(-99999, -99999)
        self.now.return_value += 0.2
        self.pet._animate()
        self.assertEqual(self.pet._action, "idle")
        self.cursor.return_value = self.pet.mapToGlobal(QPoint(64, 64))
        self.pet._hovered = True
        self.pet._start_motion("hover_hold")
        QTest.mouseClick(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(64, 64))
        self.now.return_value += QApplication.doubleClickInterval() / 1000 + 0.01
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.click")
        self.finish_action()
        self.assertTrue(self.pet._behavior.startswith("hover_"))

    def test_idle_variety_doze_sleep_and_key_wakeup(self):
        self.now.return_value = 141
        self.pet._animate()
        first = self.pet._behavior
        self.assertIn(first, ("look", "stretch", "play"))
        self.finish_action()
        self.now.return_value = 182
        self.pet._animate()
        self.assertIn(self.pet._behavior, ("look", "stretch", "play"))
        self.assertNotEqual(self.pet._behavior, first)
        self.finish_action()
        self.now.return_value = 100 + DOZE_AFTER
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.doze")
        self.finish_action()
        self.now.return_value = 100 + SLEEP_AFTER
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.sleep")
        self.pet.on_key_press()
        self.pet._animate()
        self.assertEqual(self.pet._action, "free.wake")
        self.finish_action()
        self.assertEqual(self.pet._action, "free.tap")
        self.assertEqual(self.pet._last_activity, self.now.return_value)

    def test_sleep_can_wake_for_hover_click_or_celebration(self):
        for trigger, expected in (
                (lambda: self.pet.celebrate(10000), "celebrate_big"),
                (lambda: setattr(self.pet, "_click_due", self.now.return_value), "click"),
                (lambda: setattr(self.pet, "_hovered", True), "hover")):
            with self.subTest(expected=expected):
                self.pet._reset_interactions()
                self.pet._start_motion("sleep")
                self.cursor.return_value = self.pet.mapToGlobal(QPoint(64, 64))
                trigger()
                self.pet._animate()
                self.assertEqual(self.pet._action, "free.wake")
                self.finish_action()
                self.assertEqual(self.pet._action, f"free.{expected}")

    def test_hidden_events_and_context_menu_do_not_queue_or_run_timers(self):
        self.pet.on_key_press()
        self.pet.celebrate(1000)
        self.pet._click_due = 100.5
        self.pet.hide()
        self.pet.on_key_press()
        self.pet.celebrate(10000)
        self.assertIsNone(self.pet._pending_celebration)
        self.assertFalse(self.pet._key_pending)
        self.assertEqual(self.pet._click_due, 0)
        self.assertFalse(self.pet._animation_timer.isActive())
        self.pet.show()
        self.assertEqual(self.pet._action, "idle")
        self.pet._menu_opened()
        self.pet.on_key_press()
        self.pet.celebrate(1000)
        self.assertFalse(self.pet._animation_timer.isActive())
        self.assertIsNone(self.pet._pending_celebration)
        self.pet._menu_closed()
        self.assertTrue(self.pet._animation_timer.isActive())
        self.assertEqual(self.pet._action, "idle")

    def test_every_motion_preserves_placement_and_edge_contact(self):
        area = QRect(-1920, -200, 1920, 1000)
        for edge in ("left", "right", "top", "bottom"):
            self.pet._place(area.center(), area, edge)
            position = self.pet.pos()
            for name, action in self.pet._actions.items():
                if not name.startswith(f"{edge}."):
                    continue
                self.pet._start_action(name)
                elapsed = 0
                for frame in action.frames:
                    with self.subTest(action=name, elapsed=elapsed):
                        self.pet._advance_animation(elapsed)
                        region = frame.mask.translated(action.offset)
                        self.assertEqual(self.pet.pos(), position)
                        self.assertEqual(self.pet.mask(), region)
                        self.assertTrue(self.pet.rect().contains(region.boundingRect()))
                        bounds = region.boundingRect().translated(position)
                        side = {"left": "left", "right": "right", "top": "top", "bottom": "bottom"}[edge]
                        self.assertEqual(getattr(bounds, side)(), getattr(area, side)())
                    elapsed += frame.duration_ms

    @unittest.skipUnless(sys.platform == "win32", "Native window checks require Windows.")
    def test_native_topmost_no_focus_and_window_region(self):
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int)
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        gdi32 = ctypes.windll.gdi32
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = ctypes.c_void_p
        gdi32.PtInRegion.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_int)
        gdi32.DeleteObject.argtypes = (ctypes.c_void_p,)
        user32.GetWindowRgn.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        area = APPLICATION.primaryScreen().availableGeometry()
        target = QPoint(area.center().x() - 64, area.center().y() - 64)
        self.pet._place(target, area, "")
        base = QWidget()
        base.setGeometry(QRect(target - QPoint(40, 40), QSize(240, 240)))
        self.pet.set_topmost(False)
        base.show()
        base.raise_()
        base.activateWindow()
        APPLICATION.processEvents()
        try:
            base_hwnd = int(base.winId())
            self.pet.hide()
            foreground = user32.GetForegroundWindow()
            self.pet.show()
            APPLICATION.processEvents()
            self.assertEqual(user32.GetForegroundWindow(), foreground)
            pet_hwnd = int(self.pet.winId())
            self.pet.set_topmost(True)
            APPLICATION.processEvents()
            self.assertEqual(user32.GetForegroundWindow(), foreground)
            self.assertTrue(user32.GetWindowLongW(pet_hwnd, -20) & 0x00000008)
            self.assertTrue(user32.GetWindowLongW(pet_hwnd, -20) & 0x00000080)
            region = gdi32.CreateRectRgn(0, 0, 0, 0)
            try:
                self.assertEqual(user32.GetWindowRgn(pet_hwnd, region), 3)
                scale = self.pet.devicePixelRatioF()
                self.assertTrue(gdi32.PtInRegion(region, round(64 * scale), round(64 * scale)))
                self.assertFalse(gdi32.PtInRegion(region, 0, 0))
            finally:
                gdi32.DeleteObject(region)
            self.pet.set_topmost(False)
            APPLICATION.processEvents()
            self.assertFalse(user32.GetWindowLongW(int(self.pet.winId()), -20) & 0x00000008)
        finally:
            base.close()
            base.deleteLater()


class AssetLoadingTests(unittest.TestCase):
    def test_loading_does_not_depend_on_working_directory(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            actions = load_actions()
        self.assertEqual(len(actions), 96)
        self.assertEqual(actions["left"].offset, QPoint(-48, 0))
        self.assertEqual(actions["right"].offset, QPoint(48, 0))
        self.assertEqual(actions["top"].offset, QPoint(0, -30))
        self.assertEqual(actions["bottom"].offset, QPoint(0, 26))

    def test_missing_mismatched_or_invalid_assets_fail_clearly(self):
        source = Path(__file__).resolve().parents[1] / "assets" / "pet" / "qiaoqiao-v2"
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            with self.assertRaises(FileNotFoundError):
                load_actions(directory)
            manifest = json.loads((source / "atlas.json").read_text(encoding="utf-8"))
            (directory / "atlas.png").write_bytes((source / "atlas.png").read_bytes())
            for key, value in (("sha256", "wrong"), ("schema_version", 99)):
                invalid = dict(manifest, **{key: value})
                (directory / "atlas.json").write_text(json.dumps(invalid), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_actions(directory)
            manifest["actions"]["idle"]["frames"][0]["duration_ms"] = 0
            (directory / "atlas.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_actions(directory)


if __name__ == "__main__":
    unittest.main()
