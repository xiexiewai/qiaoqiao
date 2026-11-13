"""Application lifecycle, tray, single instance and periodic persistence."""

import hashlib
import logging
import sys
from concurrent.futures import Future
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import QLockFile, QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMenu, QMessageBox, QStyle, QSystemTrayIcon

from .backup import Backup, read_backup, write_backup
from .core import MILESTONE_INTERVAL, CounterModel, MilestoneTracker
from .pet import PetWindow
from .raw_input import RawInputListener
from .runtime import Runtime, parse_runtime
from .storage import Database, Persistence
from .theme import STYLE, palette, set_state
from .ui import BackupDialog, StatsWindow, application_icon

LOGGER = logging.getLogger("qiaoqiao")
MILESTONE_ACTION_TEXT = "千次里程碑提醒"
MILESTONE_MESSAGES = (
    (1000, (
        "又一个千次达成，今天的节奏已经起来了！",
        "一点点积累，又走到了新的里程碑，做得不错！",
        "新的千次节点，给认真投入的自己一个赞！",
    )),
    (5000, (
        "又一个千次里程碑！今天的投入值得一个大大的赞！",
        "这一路的积累真不错，为你的专注鼓掌！",
        "新的里程碑达成！今天这份认真，值得好好肯定！",
    )),
    (10000, (
        "万次之后又进一步！为这份持续的专注喝彩！",
        "新的千次成就解锁！给今天投入的自己一阵掌声！",
        "又抵达一个里程碑！今天的专注值得热烈祝贺！",
    )),
    (20000, (
        "两万次之后再进一步！今天这一程值得热烈庆祝！",
        "又一个里程碑达成！为今天认真的自己大声喝彩！",
        "新的千次成就到手！给这份持续投入热烈的掌声！",
    )),
    (30000, (
        "三万次之后的新里程碑！今天的投入值得一场掌声！",
        "又一座千次里程碑！为这份坚持送上隆重的祝贺！",
        "新的成就达成！请给今天的自己一次热烈的庆祝！",
    )),
    (50000, (
        "五万次之后的新成就！隆重喝彩，也给双手一点休息时间吧！",
        "又一个高阶里程碑！热烈祝贺，接下来也给双手放个小假！",
        "这份投入值得隆重庆祝！给自己掌声，也记得放松双手！",
    )),
)


def milestone_message(threshold: int) -> tuple[str, str]:
    """Use local, rotating copy without claiming an unverified personal record."""
    floor, messages = next(item for item in reversed(MILESTONE_MESSAGES) if threshold >= item[0])
    encouragement = messages[(threshold - floor) // MILESTONE_INTERVAL % len(messages)]
    title = "千次里程碑"
    if threshold == MILESTONE_INTERVAL:
        encouragement = "第一个千次达成，今天的节奏已经起来了！"
    elif threshold % 10000 == 0:
        title = "万次里程碑！"
        encouragement = {
            10000: "一万次达成！为今天专注投入的你喝彩！",
            20000: "两万次达成！今天这一程，值得热烈庆祝！",
            30000: "三万次里程碑！给今天认真投入的自己一场掌声！",
            50000: "五万次达成！这份投入值得隆重喝彩，也给双手一点休息时间吧！",
        }.get(threshold, encouragement)
    return title, f"今日敲击已达 {threshold:,} 次。\n{encouragement}"


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
        self._saved_milestone_day, self._saved_milestone_threshold = self._read_milestone_checkpoint()
        today = datetime.now().date()
        enabled = str(self.settings.value("milestones/enabled", True)).lower() != "false"
        self.milestones = MilestoneTracker(
            today, sum(self.model.totals("day", today).values()), enabled,
            self._saved_milestone_threshold if self._saved_milestone_day == today else 0,
        )
        self._notification_not_before = 0.0
        self.window = StatsWindow(self.settings)
        self.window.setWindowTitle(f"{self.runtime.title} - 键盘统计")
        self.window.view_changed.connect(self.refresh)
        self.window.hidden_to_tray.connect(self._hidden)
        self._data_flow = False
        self._data_dialog: QDialog | None = None
        self._transfer_kind: str | None = None
        self._transfer_future: Future | None = None
        self._transfer_path: Path | None = None
        self._import_span: tuple[date, date] | None = None
        self.export_action = QAction(self.window.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
                                     "导出数据…", self)
        self.import_action = QAction(self.window.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
                                     "导入数据…", self)
        self.export_action.triggered.connect(self.export_data)
        self.import_action.triggered.connect(self.import_data)
        self.window.data_menu.addActions([self.export_action, self.import_action])
        self.tray = QSystemTrayIcon(application_icon(), self)
        self.menu = QMenu()
        self.menu.setPalette(palette())
        self.menu.setStyleSheet(STYLE)
        self.open_action = QAction("打开主界面", self)
        self.open_action.triggered.connect(self.restore_window)
        self.pet_action = QAction("显示宠物", self)
        self.pet_action.setCheckable(True)
        self.pet_action.setChecked(str(self.settings.value("pet/enabled", True)).lower() != "false")
        self.pet_action.toggled.connect(self._set_pet_enabled)
        self.topmost_action = QAction("宠物顶置", self)
        self.topmost_action.setCheckable(True)
        self.topmost_action.setChecked(str(self.settings.value("pet/topmost", True)).lower() != "false")
        self.topmost_action.toggled.connect(self._set_pet_topmost)
        self.milestone_action = QAction(MILESTONE_ACTION_TEXT, self)
        self.milestone_action.setCheckable(True)
        self.milestone_action.setChecked(enabled)
        self.milestone_action.toggled.connect(self._set_milestone_enabled)
        self.exit_action = QAction("退出程序", self)
        self.exit_action.triggered.connect(lambda: self.request_exit())
        self.menu.addAction(self.open_action)
        self.menu.addAction(self.pet_action)
        self.menu.addAction(self.topmost_action)
        self.menu.addAction(self.milestone_action)
        self.tray_data_menu = self.menu.addMenu("数据管理")
        self.tray_data_menu.addActions([self.export_action, self.import_action])
        self.menu.addSeparator()
        self.menu.addAction(self.exit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self.restore_window)
        self.pet_menu = QMenu()
        self.pet_menu.setPalette(palette())
        self.pet_menu.setStyleSheet(STYLE)
        self.pet_menu.addActions((self.open_action, self.pet_action, self.topmost_action))
        self.pet_menu.addSeparator()
        self.pet_menu.addAction(self.exit_action)
        self.pet = PetWindow(self.settings, self.pet_menu, self.topmost_action.isChecked())
        self.pet.open_requested.connect(self.restore_window)
        self.window.view_changed.connect(self._sync_pet_visibility)
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
            self.pet.close()
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
        self._sync_pet_visibility()

    def restore_window(self) -> None:
        self.pet.hide()
        self.window.restore()

    def _sync_pet_visibility(self) -> None:
        listener = self.listener
        show = (self.pet_action.isChecked() and not self.window.isVisible()
                and not self.closed and not self.exiting
                and listener is not None and not listener.locked and not listener.suspended)
        if show and not self.pet.isVisible():
            self.pet.show()
        elif not show and self.pet.isVisible():
            self.pet.hide()

    def _set_pet_enabled(self, enabled: bool) -> None:
        self.settings.setValue("pet/enabled", enabled)
        self.settings.sync()
        self._sync_pet_visibility()

    def _set_pet_topmost(self, enabled: bool) -> None:
        self.pet.set_topmost(enabled)
        self.settings.setValue("pet/topmost", enabled)
        self.settings.sync()

    def _key(self, event):
        day = datetime.now().date()
        if self.persistence.import_future is not None:
            # Track only physical hold/release state while counts are paused.
            # A key held across the restore must not be counted again on repeat.
            self.model.accept(event, day, counting=False)
            return
        # Rebase before accepting the first event of a new day, so it is neither
        # swallowed into the baseline nor counted twice. No settings I/O here.
        self._sync_milestone_day(day)
        if self.model.accept(event, day):
            previous_threshold = self.milestones.pending
            self.milestones.record_press()
            # Feedback follows accepted physical presses, so key repeat never
            # retriggers it. The UI coalesces redraws without changing storage.
            self.window.keyboard.flash_key(event.key_id)
            self.pet.on_key_press()
            threshold = self.milestones.pending
            if threshold is not None and threshold != previous_threshold:
                self.pet.celebrate(threshold)

    def _input_error(self, message):
        LOGGER.error("Keyboard listener: %s", message)
        self.refresh()

    def tick(self):
        if self.closed or self.exiting:
            return
        self._poll_transfer()
        self._sync_milestone_day(datetime.now().date())
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
                self._notification_not_before = monotonic() + 5
        self._notify_milestone()
        self._sync_pet_visibility()
        if self.window.isVisible():
            self.refresh()

    def _read_milestone_checkpoint(self) -> tuple[date | None, int]:
        try:
            day = date.fromisoformat(self.settings.value("milestones/last_day", ""))
            value = self.settings.value("milestones/last_threshold", 0)
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                return None, 0
            threshold = int(value)
        except (TypeError, ValueError):
            return None, 0
        if threshold < 0 or threshold % MILESTONE_INTERVAL:
            return None, 0
        return day, threshold

    def _sync_milestone_day(self, day: date) -> None:
        if self.milestones.day != day:
            self.pet.clear_celebration()
            self.milestones.reset(
                day, sum(self.model.totals("day", day).values()),
                self._saved_milestone_threshold if self._saved_milestone_day == day else 0,
            )

    def _set_milestone_enabled(self, enabled: bool) -> None:
        self._sync_milestone_day(datetime.now().date())
        # Both toggles discard pending celebrations; re-enabling never replays
        # thresholds reached while the user had notifications disabled.
        self.milestones.set_enabled(enabled)
        self.pet.clear_celebration()
        self.settings.setValue("milestones/enabled", enabled)
        self._save_milestone_preferences()

    def _save_milestone_preferences(self) -> None:
        self._saved_milestone_day = self.milestones.day
        self._saved_milestone_threshold = self.milestones.handled
        self.settings.setValue("milestones/last_day", self.milestones.day.isoformat())
        self.settings.setValue("milestones/last_threshold", self.milestones.handled)
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            LOGGER.warning("Milestone preferences could not be saved: %s", self.settings.status())
            self.milestone_action.setText(f"{MILESTONE_ACTION_TEXT}（偏好保存失败）")
            self.milestone_action.setToolTip("本次设置仍有效，下次启动可能无法恢复；统计不受影响")
        else:
            self.milestone_action.setText(MILESTONE_ACTION_TEXT)
            self.milestone_action.setToolTip("")

    def _notify_milestone(self) -> None:
        listener = self.listener
        if (self.milestones.pending is None or not self.milestones.enabled
                or listener is None or not listener.active or listener.locked or listener.suspended
                or listener.last_error or self.persistence.error or self._dialogs or self._data_flow
                or monotonic() < self._notification_not_before):
            return
        threshold = self.milestones.take_pending()
        if threshold is None:
            return
        # This checkpoint means "notification attempted", not "seen by the user".
        # Persist before sending: Windows can suppress a banner without reporting
        # delivery, and repeatedly retrying it would only create notification spam.
        self._save_milestone_preferences()
        if not QSystemTrayIcon.supportsMessages():
            LOGGER.warning("System tray notifications are unavailable")
            return
        title, message = milestone_message(threshold)
        try:
            self.tray.showMessage(
                f"{self.runtime.name} · {title}", message,
                QSystemTrayIcon.MessageIcon.Information, 5000,
            )
        except RuntimeError:
            LOGGER.exception("Milestone notification failed")
        self._notification_not_before = monotonic() + 5

    def refresh(self):
        self.window.refresh(self.model)
        if self.persistence.import_future is not None:
            state = "导入中，统计暂停"
        elif self.listener is None:
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
        if self._transfer_kind is not None:
            saved = {"read": "正在校验备份", "export": "正在导出数据", "import": "正在备份并覆盖数据"}[
                self._transfer_kind
            ]
        elif self.persistence.error:
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

    def _update_data_actions(self) -> None:
        available = not self._data_flow and not self.exiting and not self.closed
        self.export_action.setEnabled(available)
        self.import_action.setEnabled(available)
        self.exit_action.setEnabled(self._transfer_kind is None)

    def _end_data_flow(self) -> None:
        self._data_flow = False
        self._transfer_kind = None
        self._transfer_future = None
        self._update_data_actions()

    def _open_data_dialog(self, dialog: QDialog, accepted) -> None:
        self._data_dialog = dialog
        self._dialogs.append(dialog)

        def finished(result):
            self._dialogs.remove(dialog)
            self._data_dialog = None
            try:
                if self.closed or self.exiting or result != QDialog.DialogCode.Accepted:
                    self._end_data_flow()
                else:
                    accepted(dialog)
            except Exception as error:
                LOGGER.exception("Backup dialog failed")
                self._end_data_flow()
                self._show_error("数据操作失败", str(error))
            finally:
                dialog.deleteLater()

        dialog.finished.connect(finished)
        dialog.open()

    def export_data(self) -> None:
        if self._data_flow or self.closed or self.exiting:
            return
        self._data_flow = True
        self._update_data_actions()
        self.restore_window()
        dialog = BackupDialog(self.model.counts, parent=self.window)
        self._open_data_dialog(dialog, lambda chosen: self._choose_export_path(*chosen.selected_range()))

    def _choose_export_path(self, start: date, end: date) -> None:
        dialog = QFileDialog(self.window, "保存敲敲备份")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter("敲敲备份 (*.qiaoqiao.json)")
        dialog.setDefaultSuffix("qiaoqiao.json")
        dialog.selectFile(f"Qiaoqiao-{start.isoformat()}_{end.isoformat()}.qiaoqiao.json")
        self._open_data_dialog(
            dialog, lambda chosen: self.start_export(Path(chosen.selectedFiles()[0]), start, end),
        )

    def start_export(self, path: Path, start: date, end: date) -> None:
        if self._transfer_kind is not None or self.closed or self.exiting:
            raise RuntimeError("已有数据操作正在执行。")
        if not path.name.lower().endswith(".qiaoqiao.json"):
            raise ValueError("备份文件名必须以 .qiaoqiao.json 结尾。")
        # Capture once on the GUI thread; serialization and file I/O use the
        # existing worker, while incoming keys continue to update the live model.
        snapshot = dict(self.model.counts)
        future = self.persistence.executor.submit(write_backup, path, snapshot, start, end)
        self._transfer_future = future
        self._transfer_path = path
        self._transfer_kind = "export"
        self._data_flow = True
        self._update_data_actions()
        self.refresh()

    def import_data(self) -> None:
        if self._data_flow or self.closed or self.exiting:
            return
        self._data_flow = True
        self._update_data_actions()
        self.restore_window()
        dialog = QFileDialog(self.window, "选择敲敲备份")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter("敲敲备份 (*.qiaoqiao.json);;JSON 文件 (*.json)")
        self._open_data_dialog(dialog, lambda chosen: self._read_import(Path(chosen.selectedFiles()[0])))

    def _read_import(self, path: Path) -> None:
        future = self.persistence.executor.submit(read_backup, path)
        self._transfer_future = future
        self._transfer_path = path
        self._transfer_kind = "read"
        self._update_data_actions()
        self.refresh()

    def _preview_import(self, backup: Backup) -> None:
        dialog = BackupDialog(self.model.counts, backup, self.window)
        self._open_data_dialog(
            dialog, lambda chosen: self.start_import(backup, *chosen.selected_range()),
        )

    def start_import(self, backup: Backup, start: date, end: date) -> None:
        if self._transfer_kind is not None or self.closed or self.exiting:
            raise RuntimeError("已有数据操作正在执行。")
        totals = backup.select(start, end)
        path = self.runtime.directory / "backups" / (
            f"before-import-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:12]}.qiaoqiao.json"
        )
        self.persistence.begin_import(start, end, totals, path)
        self._transfer_path = path
        self._import_span = (start, end)
        self._transfer_kind = "import"
        self._data_flow = True
        self._update_data_actions()
        self.refresh()

    def _poll_transfer(self, wait: bool = False, notify: bool = True) -> None:
        kind = self._transfer_kind
        if kind is None:
            return
        committed = False
        try:
            result = None
            if kind == "import":
                if not self.persistence.finish_import(wait):
                    return
                committed = True
                self.window.invalidate_counts()
                today = datetime.now().date()
                if self._import_span[0] <= today <= self._import_span[1]:
                    self.pet.clear_celebration()
                    self.milestones.reset(today, sum(self.model.totals("day", today).values()))
                    self._save_milestone_preferences()
            else:
                if not wait and not self._transfer_future.done():
                    return
                result = self._transfer_future.result()
        except Exception as error:
            LOGGER.exception("Data %s failed", kind)
            self._end_data_flow()
            if notify:
                self._show_error(
                    "数据操作失败",
                    f"{error}\n\n" + (
                        "统计已导入，但界面或提醒偏好更新失败；请重新打开主界面。"
                        if committed else "未覆盖原统计，计数已恢复。请处理错误后重新导入。" if kind == "import"
                        else "请检查备份文件、磁盘空间和文件权限后重试。"
                    ),
                )
            self.refresh()
            return
        self._transfer_kind = None
        self._transfer_future = None
        if kind == "read" and notify:
            self._update_data_actions()
            try:
                self._preview_import(result)
            except ValueError as error:
                self._end_data_flow()
                self._show_error("无法导入", str(error))
        else:
            self._end_data_flow()
            if notify:
                if kind == "import":
                    self._show_result(
                        "导入完成",
                        f"已覆盖 {self._import_span[0]} 至 {self._import_span[1]}，范围外数据保留。\n"
                        f"原数据备份：\n{self._transfer_path}",
                    )
                elif kind == "export":
                    self._show_result("导出完成", f"备份已保存：\n{self._transfer_path}")
        self.refresh()

    def _show_result(self, title: str, message: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, title, message, QMessageBox.StandardButton.Ok, self.window)
        box.setTextFormat(Qt.TextFormat.PlainText)
        self._dialogs.append(box)
        box.finished.connect(lambda result: self._dialogs.remove(box))
        box.open()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_window()

    def _hidden(self):
        self._sync_pet_visibility()
        if not self._tray_tip_shown:
            self.tray.showMessage(
                f"{self.runtime.name}仍在统计", "可通过托盘图标打开窗口，或选择“退出程序”。",
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )
            self._tray_tip_shown = True
            # The first-hide hint must not shorten an existing milestone/error cooldown.
            self._notification_not_before = max(self._notification_not_before, monotonic() + 3)

    def _show_error(self, title, message):
        box = QMessageBox(QMessageBox.Icon.Warning, title, message, QMessageBox.StandardButton.Ok, self.window)
        box.setTextFormat(Qt.TextFormat.PlainText)
        self._dialogs.append(box)
        box.finished.connect(lambda result: self._dialogs.remove(box))
        box.open()

    def request_exit(self, system=False) -> bool:
        if self.closed:
            return True
        if self.exiting:
            return False
        if self._transfer_kind is not None and not system:
            self._show_error("数据操作进行中", "请等待数据操作完成后，再退出程序。")
            return False
        self.exiting = True
        self.pet.hide()
        self.timer.stop()
        try:
            self.listener.stop()
            self._poll_transfer(wait=True, notify=False)
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
            self.restore_window()
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
        self.pet.close()
        self.pet_menu.close()
        if self.listener:
            try:
                self.listener.close()
            except Exception:
                LOGGER.exception("Listener cleanup failed")
        self._poll_transfer(wait=True, notify=False)
        if self._data_dialog is not None:
            self._data_dialog.reject()
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
    application.styleHints().setColorScheme(Qt.ColorScheme.Dark)
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
        guard.activated.connect(controller.restore_window)
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
                controller._poll_transfer(wait=True, notify=False)
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
