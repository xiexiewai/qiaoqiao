"""Application lifecycle, tray, single instance and periodic persistence."""

import hashlib
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QSettings, QTimer, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .core import CounterModel
from .raw_input import RawInputListener
from .runtime import Runtime, parse_runtime
from .storage import Database, Persistence
from .theme import STYLE, palette, set_state
from .ui import StatsWindow, application_icon

LOGGER = logging.getLogger("qiaoqiao")


class InstanceGuard(QObject):
    activated = Signal()

    def __init__(self, directory: Path):
        super().__init__()
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(directory / "app.lock"))
        self.lock.setStaleLockTime(0)
        identity = str(directory.resolve()).casefold().encode("utf-8")
        self.name = "qiaoqiao-" + hashlib.sha256(identity).hexdigest()[:24]
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._activate)

    def acquire(self) -> bool:
        if not self.lock.tryLock(0):
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise OSError("无法创建运行锁，请检查数据目录的写入权限。")
            return False
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise OSError(f"无法创建本地唤醒通道：{self.server.errorString()}")
        return True

    def notify_existing(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        connected = socket.waitForConnected(1500)
        socket.disconnectFromServer()
        return connected

    def _activate(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activated.emit()

    def close(self):
        self.server.close()
        self.lock.unlock()


class Controller(QObject):
    def __init__(self, application, database, listener_factory=RawInputListener, runtime=None):
        super().__init__()
        self.application = application
        self.database = database
        self.runtime = runtime or Runtime(True, database.path.parent)
        self.model = CounterModel(database.load())
        self.persistence = Persistence(self.model, database)
        self.settings = QSettings(str(self.runtime.directory / "preferences.ini"), QSettings.Format.IniFormat)
        self.window = StatsWindow(self.settings)
        self.window.setWindowTitle(f"{self.runtime.title} - 键盘统计")
        self.window.view_changed.connect(self.refresh)
        self.window.hidden_to_tray.connect(self._hidden)
        self.tray = QSystemTrayIcon(application_icon(), self)
        self.menu = QMenu()
        self.menu.setPalette(palette())
        self.menu.setStyleSheet(STYLE)
        self.open_action = QAction("打开主界面", self)
        self.open_action.triggered.connect(self.window.restore)
        self.exit_action = QAction("退出程序", self)
        self.exit_action.triggered.connect(lambda: self.request_exit())
        self.menu.addAction(self.open_action)
        self.menu.addSeparator()
        self.menu.addAction(self.exit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self.window.restore)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.closed = False
        self.exiting = False
        self.listener = None
        self._tray_tip_shown = False
        self._reported_save_error = None
        self._dialogs = []
        try:
            self.listener = listener_factory(
                self._key, self.model.release_device, self.model.release_all,
                self._input_error, lambda: self.request_exit(system=True),
            )
        except Exception:
            self.persistence.close()
            self.window.deleteLater()
            raise

    def start(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("当前 Windows 会话的系统托盘不可用，请在正常桌面会话中启动。")
        self.listener.start()
        self.tray.show()
        self.timer.start()
        self.refresh()
        self.window.show()

    def _key(self, event):
        if self.model.accept(event, datetime.now().date()):
            # Feedback follows accepted physical presses, so key repeat never
            # retriggers it. The UI coalesces redraws without changing storage.
            self.window.keyboard.flash_key(event.key_id)

    def _input_error(self, message):
        LOGGER.error("Keyboard listener: %s", message)
        self.refresh()

    def tick(self):
        self.persistence.tick()
        if self.persistence.error != self._reported_save_error:
            self._reported_save_error = self.persistence.error
            if self.persistence.error:
                LOGGER.error("Save failed: %s", self.persistence.error)
                self.tray.showMessage(
                    f"{self.runtime.name}：暂时无法保存",
                    "统计仍在内存中，程序会自动重试。请打开主界面查看保存状态。",
                    QSystemTrayIcon.MessageIcon.Warning,
                )
        if self.window.isVisible():
            self.refresh()

    def refresh(self):
        self.window.refresh(self.model)
        if self.listener is None:
            state = "正在启动"
        elif self.listener.last_error:
            state = "监听异常"
        elif self.listener.locked or self.listener.suspended:
            state = "会话暂停"
        elif self.listener.active:
            state = "正在统计"
        else:
            state = "统计已停止"
        self.window.status_label.setText(state)
        set_state(self.window.status_label, "error" if state == "监听异常" else (
            "normal" if state == "正在统计" else "paused"
        ))
        self.window.status_label.setToolTip(self.listener.last_error or "" if self.listener else "")
        self.tray.setToolTip(f"{self.runtime.title} · {state}")
        if self.persistence.error:
            saved = "保存失败，正在重试"
        elif self.model.dirty or self.persistence.future is not None:
            saved = "正在保存"
        elif self.persistence.last_saved:
            saved = f"已保存  {self.persistence.last_saved:%H:%M:%S}"
        else:
            saved = "数据已保存在本机"
        self.window.save_label.setText(saved)
        self.window.save_label.setToolTip(self.persistence.error or str(self.database.path))
        set_state(self.window.save_label, "error" if self.persistence.error else "muted")

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.window.restore()

    def _hidden(self):
        if not self._tray_tip_shown:
            self.tray.showMessage(
                f"{self.runtime.name}仍在统计", "可通过托盘图标打开窗口，或选择“退出程序”。",
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )
            self._tray_tip_shown = True

    def _show_error(self, title, message):
        box = QMessageBox(QMessageBox.Icon.Warning, title, message, QMessageBox.StandardButton.Ok, self.window)
        self._dialogs.append(box)
        box.finished.connect(lambda result: self._dialogs.remove(box))
        box.open()

    def request_exit(self, system=False) -> bool:
        if self.closed:
            return True
        if self.exiting:
            return False
        self.exiting = True
        self.timer.stop()
        try:
            self.listener.stop()
            saved = self.persistence.flush()
        except Exception as error:
            LOGGER.exception("Exit preparation failed")
            self.persistence.error = str(error)
            saved = False
        if not saved and not system:
            # Keep the model and dirty totals alive so a failed exit is recoverable.
            try:
                self.listener.start()
            except Exception as error:
                self.listener.last_error = str(error)
                LOGGER.exception("Could not restart keyboard listener")
            self.exiting = False
            self.timer.start()
            self.window.restore()
            self._show_error(
                "退出前保存失败",
                f"程序暂未退出，尚未保存的统计仍保留在内存中，并会自动重试。\n"
                f"请检查磁盘空间和数据目录权限后，再从托盘退出。\n\n"
                f"{self.database.path}\n{self.persistence.error}",
            )
            return False
        if not saved:
            LOGGER.error("System shutdown with unsaved totals: %s", self.persistence.error)
        self.dispose()
        self.application.quit()
        return True

    def dispose(self):
        if self.closed:
            return
        self.timer.stop()
        if self.listener:
            try:
                self.listener.close()
            except Exception:
                LOGGER.exception("Listener cleanup failed")
        self.persistence.close()
        self.tray.hide()
        self.window.allow_close = True
        self.window.close()
        self.menu.close()
        self.closed = True


def main(argv=None) -> int:
    runtime = parse_runtime(argv)
    application = QApplication([sys.argv[0]])
    application.setApplicationName("Qiaoqiao-dev" if runtime.development else "Qiaoqiao")
    application.setApplicationDisplayName(runtime.title)
    application.setOrganizationName("Qiaoqiao")
    application.setQuitOnLastWindowClosed(False)
    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 10))
    application.setWindowIcon(application_icon())
    guard = None
    controller = None
    handler = None
    try:
        directory = runtime.directory
        guard = InstanceGuard(directory)
        if not guard.acquire():
            if not guard.notify_existing():
                QMessageBox.information(
                    None, f"{runtime.name}已在运行", "程序已经打开或正在启动，请通过托盘图标打开主界面。",
                )
            return 0
        handler = RotatingFileHandler(directory / "app.log", maxBytes=256_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.WARNING)
        database = Database(directory / "counts.sqlite3")
        database.initialize()
        controller = Controller(application, database, runtime=runtime)
        guard.activated.connect(controller.window.restore)
        controller.start()
        return application.exec()
    except Exception as error:
        LOGGER.exception("Startup failed")
        QMessageBox.critical(None, f"{runtime.name}启动失败", f"无法启动程序：\n{error}")
        return 1
    finally:
        if controller and not controller.closed:
            try:
                controller.listener.stop()
                controller.persistence.flush()
            finally:
                controller.dispose()
        if guard:
            guard.close()
        if handler:
            LOGGER.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
