"""Windows Raw Input bridge; never decodes typed characters."""

import ctypes
from ctypes import wintypes
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication, QWidget

from .keys import PhysicalEvent, normalize

WM_INPUT = 0x00FF
WM_INPUT_DEVICE_CHANGE = 0x00FE
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
WM_ENDSESSION = 0x0016
RID_INPUT = 0x10000003
UINT_ERROR = 0xFFFFFFFF


class RawInputDevice(ctypes.Structure):
    _fields_ = [
        ("usage_page", wintypes.USHORT), ("usage", wintypes.USHORT),
        ("flags", wintypes.DWORD), ("target", wintypes.HWND),
    ]


class RawInputHeader(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD), ("size", wintypes.DWORD),
        ("device", wintypes.HANDLE), ("wparam", ctypes.c_size_t),
    ]


class RawKeyboard(ctypes.Structure):
    _fields_ = [
        ("make_code", wintypes.USHORT), ("flags", wintypes.USHORT),
        ("reserved", wintypes.USHORT), ("vkey", wintypes.USHORT),
        ("message", wintypes.UINT), ("extra", wintypes.ULONG),
    ]


def parse_keyboard(buffer: bytes) -> PhysicalEvent | None:
    header_size = ctypes.sizeof(RawInputHeader)
    if len(buffer) < header_size:
        raise ValueError("Incomplete Raw Input header")
    header = RawInputHeader.from_buffer_copy(buffer)
    if header.type != 1:
        return None
    minimum = header_size + ctypes.sizeof(RawKeyboard)
    if len(buffer) < minimum or header.size < minimum or header.size > len(buffer):
        raise ValueError("Incomplete Raw Input keyboard packet")
    keyboard = RawKeyboard.from_buffer_copy(buffer, header_size)
    return normalize(int(header.device or 0), keyboard.make_code, keyboard.flags, keyboard.vkey)


class RawInputListener(QAbstractNativeEventFilter):
    def __init__(
        self,
        on_key: Callable[[PhysicalEvent], None],
        on_remove: Callable[[int], None],
        on_reset: Callable[[], None],
        on_error: Callable[[str], None],
        on_shutdown: Callable[[], None],
    ):
        super().__init__()
        self.on_key, self.on_remove, self.on_reset = on_key, on_remove, on_reset
        self.on_error, self.on_shutdown = on_error, on_shutdown
        self.window = QWidget()
        self.hwnd = int(self.window.winId())
        self.active = False
        self.locked = False
        self.suspended = False
        self.last_error: str | None = None
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.RegisterRawInputDevices.argtypes = [
            ctypes.POINTER(RawInputDevice), wintypes.UINT, wintypes.UINT,
        ]
        self.user32.RegisterRawInputDevices.restype = wintypes.BOOL
        self.user32.GetRawInputData.argtypes = [
            wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
            ctypes.POINTER(wintypes.UINT), wintypes.UINT,
        ]
        self.user32.GetRawInputData.restype = wintypes.UINT
        self.wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        self.wts.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.wts.WTSRegisterSessionNotification.restype = wintypes.BOOL
        self.wts.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
        self.wts.WTSUnRegisterSessionNotification.restype = wintypes.BOOL
        self.session_registered = bool(self.wts.WTSRegisterSessionNotification(self.hwnd, 0))
        if not self.session_registered:
            self.window.close()
            raise ctypes.WinError(ctypes.get_last_error())
        QApplication.instance().installNativeEventFilter(self)

    def start(self):
        if self.active:
            return
        # INPUTSINK receives background input; DEVNOTIFY reports unplugged devices.
        device = RawInputDevice(1, 6, 0x00000100 | 0x00002000, self.hwnd)
        if not self.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.active = True
        self.last_error = None

    def stop(self):
        if not self.active:
            return
        device = RawInputDevice(1, 6, 1, None)
        if not self.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.active = False
        self.on_reset()

    def close(self):
        self.stop()
        QApplication.instance().removeNativeEventFilter(self)
        if self.session_registered:
            self.wts.WTSUnRegisterSessionNotification(self.hwnd)
            self.session_registered = False
        self.window.close()

    def _read(self, handle):
        size = wintypes.UINT()
        header_size = ctypes.sizeof(RawInputHeader)
        if self.user32.GetRawInputData(handle, RID_INPUT, None, ctypes.byref(size), header_size) == UINT_ERROR:
            raise ctypes.WinError(ctypes.get_last_error())
        if size.value < header_size or size.value > 65536:
            raise ValueError("Invalid Raw Input packet length")
        buffer = ctypes.create_string_buffer(size.value)
        copied = self.user32.GetRawInputData(handle, RID_INPUT, buffer, ctypes.byref(size), header_size)
        if copied == UINT_ERROR:
            raise ctypes.WinError(ctypes.get_last_error())
        return parse_keyboard(buffer.raw[:copied])

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if msg.hWnd != self.hwnd:
            return False, 0
        try:
            if msg.message == WM_INPUT and self.active and not self.locked and not self.suspended:
                event = self._read(msg.lParam)
                if event is not None:
                    self.on_key(event)
                self.last_error = None
            elif msg.message == WM_INPUT_DEVICE_CHANGE and msg.wParam == 2:
                self.on_remove(int(msg.lParam))
            elif msg.message == WM_WTSSESSION_CHANGE and msg.wParam in (7, 8):
                self.locked = msg.wParam == 7
                self.on_reset()
            elif msg.message == WM_POWERBROADCAST and msg.wParam in (4, 7, 18):
                self.suspended = msg.wParam == 4
                self.on_reset()
            elif msg.message == WM_ENDSESSION and msg.wParam:
                self.on_shutdown()
        except Exception as error:
            self.last_error = str(error)
            self.on_error(str(error))
        # Qt/DefWindowProc must still receive WM_INPUT for Windows cleanup.
        return False, 0
