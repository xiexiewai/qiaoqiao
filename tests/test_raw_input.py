import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from qiaoqiao.keys import PhysicalEvent
from qiaoqiao.raw_input import (
    RawInputDevice, RawInputHeader, RawKeyboard, RawInputListener, parse_keyboard,
    WM_INPUT, WM_INPUT_DEVICE_CHANGE, WM_POWERBROADCAST, WM_WTSSESSION_CHANGE, WM_ENDSESSION,
)


class RawPacketTests(unittest.TestCase):
    def packet(self, code=0x1E, flags=0, vkey=0x41, device=0x123456789):
        header = RawInputHeader(1, ctypes.sizeof(RawInputHeader) + ctypes.sizeof(RawKeyboard), device, 0)
        keyboard = RawKeyboard(code, flags, 0, vkey, 0x100, 0)
        return bytes(header) + bytes(keyboard)

    def test_64bit_windows_abi(self):
        self.assertEqual(ctypes.sizeof(RawInputHeader), 24)
        self.assertEqual(ctypes.sizeof(RawKeyboard), 16)
        self.assertEqual(ctypes.sizeof(RawInputDevice), 16)

    def test_packet_preserves_full_device_handle_and_break(self):
        event = parse_keyboard(self.packet(flags=1))
        self.assertEqual(event.device, 0x123456789)
        self.assertEqual(event.key_id, "1e")
        self.assertFalse(event.is_down)

    def test_numpad_enter_packet(self):
        self.assertEqual(parse_keyboard(self.packet(0x1C, 2, 0x0D)).key_id, "e0_1c")

    def test_truncated_packet_rejected(self):
        with self.assertRaises(ValueError):
            parse_keyboard(self.packet()[:-1])
        with self.assertRaises(ValueError):
            parse_keyboard(b"")

    def test_other_devices_are_not_counted(self):
        header = RawInputHeader(0, ctypes.sizeof(RawInputHeader), 1, 0)
        self.assertIsNone(parse_keyboard(bytes(header)))


class NativeEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.on_key, self.on_remove, self.on_reset = Mock(), Mock(), Mock()
        self.on_error, self.on_shutdown = Mock(), Mock()
        self.listener = RawInputListener(
            self.on_key, self.on_remove, self.on_reset, self.on_error, self.on_shutdown,
        )

    def tearDown(self):
        self.listener.close()
        self.listener.window.deleteLater()

    def message(self, kind, wparam=0, lparam=0, hwnd=None):
        message = wintypes.MSG()
        message.hWnd = self.listener.hwnd if hwnd is None else hwnd
        message.message, message.wParam, message.lParam = kind, wparam, lparam
        return self.listener.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message))

    def test_actual_windows_registration_and_unregistration(self):
        self.listener.start()
        self.assertTrue(self.listener.active)
        self.assertTrue(self.listener.session_registered)
        self.listener.stop()
        self.assertFalse(self.listener.active)
        self.on_reset.assert_called_once()

    def test_native_dispatch_preserves_default_processing_and_routes_key(self):
        self.listener.start()
        event = PhysicalEvent(0x123456789, "e0_1c", True)
        with patch.object(self.listener, "_read", return_value=event) as read:
            self.assertEqual(self.message(WM_INPUT, lparam=123), (False, 0))
            read.assert_called_once_with(123)
            self.on_key.assert_called_once_with(event)
            self.message(WM_INPUT, hwnd=self.listener.hwnd + 1)
            self.on_key.assert_called_once()

    def test_lock_and_suspend_reset_and_suppress_events_until_resume(self):
        self.listener.start()
        with patch.object(self.listener, "_read", return_value=PhysicalEvent(1, "1e", True)) as read:
            self.message(WM_WTSSESSION_CHANGE, 7)
            self.assertTrue(self.listener.locked)
            self.message(WM_INPUT)
            read.assert_not_called()
            self.message(WM_WTSSESSION_CHANGE, 8)
            self.message(WM_POWERBROADCAST, 4)
            self.message(WM_INPUT)
            read.assert_not_called()
            self.message(WM_POWERBROADCAST, 18)
            self.assertFalse(self.listener.locked or self.listener.suspended)
            self.message(WM_INPUT)
            self.on_key.assert_called_once()
            self.assertEqual(self.on_reset.call_count, 4)

    def test_unplug_and_system_shutdown_callbacks(self):
        self.message(WM_INPUT_DEVICE_CHANGE, 2, 123456)
        self.on_remove.assert_called_once_with(123456)
        self.message(WM_ENDSESSION, 0)
        self.on_shutdown.assert_not_called()
        self.message(WM_ENDSESSION, 1)
        self.on_shutdown.assert_called_once()

    def test_native_read_failure_is_visible_and_does_not_escape_callback(self):
        self.listener.start()
        with patch.object(self.listener, "_read", side_effect=OSError("read failed")):
            self.assertEqual(self.message(WM_INPUT), (False, 0))
        self.on_error.assert_called_once_with("read failed")
        self.assertEqual(self.listener.last_error, "read failed")
        self.on_key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
