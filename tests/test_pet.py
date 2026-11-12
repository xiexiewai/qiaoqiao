import ctypes
import json
import sys
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from qiaoqiao.pet import PET_SIZE, PetWindow, load_actions, snap_placement


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
        self.assertEqual(self.pet._action, "drag")
        QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton, pos=QPoint(80, 64))
        self.assertEqual(self.pet._edge, "")
        self.assertEqual(self.pet._action, "settle")
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
        QTest.qWait(110)
        self.assertGreater(self.pet._frame_index, 0)
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
        self.assertEqual(self.pet._action, "drag")
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
        self.assertEqual(len(actions), 8)
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
