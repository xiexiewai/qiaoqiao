import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QLineEdit, QSystemTrayIcon

from qiaoqiao.app import Controller
from qiaoqiao.backup import Backup, read_backup, write_backup
from qiaoqiao.keys import PhysicalEvent
from qiaoqiao.storage import Database
from qiaoqiao.ui import BackupDialog
from test_app import APPLICATION, FakeListener


class TestFileDialog(QFileDialog):
    __test__ = False

    def __init__(self, *args):
        super().__init__(*args)
        self.setOption(QFileDialog.Option.DontUseNativeDialog)


class BackupAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.database = Database(self.directory / "counts.sqlite3")
        self.database.initialize()
        self.controller = Controller(APPLICATION, self.database, FakeListener)
        self.controller._tray_tip_shown = True
        with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
            self.controller.start()
        self.controller.timer.stop()
        self.errors = patch.object(self.controller, "_show_error").start()
        self.results = patch.object(self.controller, "_show_result").start()
        self.today = date.today()
        self.yesterday = self.today - timedelta(days=1)
        APPLICATION.processEvents()

    def tearDown(self):
        self.controller.dispose()
        self.controller.window.deleteLater()
        self.controller.menu.deleteLater()
        self.controller.deleteLater()
        APPLICATION.processEvents()
        patch.stopall()
        self.temp.cleanup()

    def tap(self, key="1e"):
        self.controller._key(PhysicalEvent(1, key, True))
        self.controller._key(PhysicalEvent(1, key, False))

    def incoming(self, counts, start=None, end=None):
        path = self.directory / "incoming.qiaoqiao.json"
        write_backup(path, counts, start or self.today, end or self.today)
        return read_backup(path)

    def test_export_snapshot_includes_unsaved_counts_and_excludes_later_presses(self):
        self.tap()
        self.assertEqual(self.database.load(), {})
        path = self.directory / "export.qiaoqiao.json"
        self.controller.start_export(path, self.today, self.today)
        self.tap()
        self.controller._poll_transfer(wait=True)
        self.assertEqual(read_backup(path).counts, {(self.today.isoformat(), "1e"): 1})
        self.assertEqual(self.controller.model.counts[(self.today.isoformat(), "1e")], 2)
        self.assertTrue(self.controller.export_action.isEnabled())
        self.results.assert_called_once()

    def test_export_failure_keeps_counts_and_reenables_actions(self):
        self.tap()
        with self.assertLogs("qiaoqiao", level="ERROR"), \
                patch("qiaoqiao.app.write_backup", side_effect=OSError("disk full")):
            self.controller.start_export(self.directory / "export.qiaoqiao.json", self.today, self.today)
            self.controller._poll_transfer(wait=True)
        self.assertEqual(self.controller.model.counts[(self.today.isoformat(), "1e")], 1)
        self.assertTrue(self.controller.import_action.isEnabled())
        self.errors.assert_called_once()
        self.assertTrue(self.controller.persistence.flush())

    def test_import_replaces_lower_values_refreshes_both_tabs_and_rebases_milestone(self):
        original = {
            (self.today.isoformat(), "1e"): 7000, (self.today.isoformat(), "30"): 12,
            (self.yesterday.isoformat(), "1e"): 88,
        }
        self.database.save(original)
        self.controller.model.counts.update(original)
        self.controller.milestones.reset(self.today, 7012, handled=7000)
        self.controller._save_milestone_preferences()
        backup = self.incoming({(self.today.isoformat(), "1e"): 999})
        window = self.controller.window
        window.set_keyboard_layout("60")
        window.tabs.setCurrentIndex(1)
        self.controller.pet._pending_celebration = (7000, float("inf"))
        self.controller.start_import(backup, self.today, self.today)
        self.assertIn("暂停", window.status_label.text())
        self.controller._poll_transfer(wait=True)
        self.assertEqual(window.trends.cards[0].value.text(), "999")
        self.assertEqual(self.database.load(), {
            (self.today.isoformat(), "1e"): 999, (self.yesterday.isoformat(), "1e"): 88,
        })
        self.assertEqual(self.controller.milestones.handled, 0)
        self.assertEqual(self.controller.settings.value("milestones/last_threshold", type=int), 0)
        self.assertIsNone(self.controller.milestones.pending)
        self.assertIsNone(self.controller.pet._pending_celebration)
        self.assertEqual(window.keyboard_layout.layout_id, "60")
        window.tabs.setCurrentIndex(0)
        self.assertEqual(window.total_label.text(), "999")
        before = read_backup(self.controller._transfer_path)
        self.assertEqual(before.counts, {
            (self.today.isoformat(), "1e"): 7000, (self.today.isoformat(), "30"): 12,
        })
        self.tap()
        self.assertEqual(self.controller.milestones.pending, 1000)
        self.assertTrue(self.controller.persistence.flush())
        restarted = Controller(APPLICATION, self.database, FakeListener)
        try:
            self.assertEqual(restarted.model.counts[(self.today.isoformat(), "1e")], 1000)
            self.assertEqual(restarted.milestones.handled, 1000)
        finally:
            restarted.dispose()
            restarted.window.deleteLater()
            restarted.menu.deleteLater()
            restarted.deleteLater()

    def test_import_empty_subrange_preserves_other_days_and_today_milestone(self):
        oldest = self.today - timedelta(days=2)
        counts = {
            (oldest.isoformat(), "1e"): 4,
            (self.yesterday.isoformat(), "1e"): 100,
            (self.today.isoformat(), "1e"): 3000,
        }
        self.database.save(counts)
        self.controller.model.counts.update(counts)
        self.controller.milestones.reset(self.today, 3000, handled=4000)
        backup = self.incoming({}, oldest, self.today)
        self.controller.start_import(backup, self.yesterday, self.yesterday)
        self.controller._poll_transfer(wait=True)
        self.assertEqual(self.database.load(), {
            (oldest.isoformat(), "1e"): 4, (self.today.isoformat(), "1e"): 3000,
        })
        self.assertEqual(self.controller.milestones.handled, 4000)
        self.assertEqual(self.controller.model.trends(self.today).recent_days[-2].count, None)

    def test_import_pauses_counts_but_tracks_held_keys_and_releases(self):
        self.controller._key(PhysicalEvent(1, "1e", True))
        backup = self.incoming({(self.today.isoformat(), "1e"): 50})
        self.controller.start_import(backup, self.today, self.today)
        with patch.object(self.controller.pet, "on_key_press") as feedback, \
                patch.object(self.controller.pet, "celebrate") as celebrate:
            self.tap("30")
            self.controller._key(PhysicalEvent(1, "2e", True))
            self.controller._key(PhysicalEvent(1, "1e", True))
            feedback.assert_not_called()
            celebrate.assert_not_called()
        self.assertEqual(self.controller.model.counts, {(self.today.isoformat(), "1e"): 1})
        self.controller._poll_transfer(wait=True)
        self.controller._key(PhysicalEvent(1, "1e", True))
        self.controller._key(PhysicalEvent(1, "2e", True))
        self.assertEqual(self.controller.model.counts, {(self.today.isoformat(), "1e"): 50})
        self.controller._key(PhysicalEvent(1, "1e", False))
        self.tap()
        self.assertEqual(self.controller.model.counts[(self.today.isoformat(), "1e")], 51)

    def test_import_failure_resumes_counting_without_overwriting_memory(self):
        self.tap()
        backup = self.incoming({})
        with self.assertLogs("qiaoqiao", level="ERROR"), \
                patch("qiaoqiao.storage.write_backup", side_effect=OSError("cannot back up")):
            self.controller.start_import(backup, self.today, self.today)
            self.controller._poll_transfer(wait=True)
        self.errors.assert_called_once()
        self.assertEqual(self.controller.window.status_label.text(), "正在统计")
        self.assertTrue(self.controller.import_action.isEnabled())
        self.tap()
        self.assertTrue(self.controller.persistence.flush())
        self.assertEqual(self.database.load(), {(self.today.isoformat(), "1e"): 2})

    def test_committed_import_is_reconciled_on_system_exit_before_poll(self):
        self.tap()
        backup = self.incoming({(self.today.isoformat(), "30"): 50})
        self.controller.start_import(backup, self.today, self.today)
        self.controller.persistence.import_future.result(timeout=3)
        self.assertIn((self.today.isoformat(), "1e"), self.controller.model.counts)
        with patch.object(APPLICATION, "quit"):
            self.assertTrue(self.controller.request_exit(system=True))
        self.assertEqual(self.database.load(), {(self.today.isoformat(), "30"): 50})
        self.assertTrue(self.controller.closed)

    def test_busy_import_prevents_second_operation_and_normal_exit(self):
        backup = self.incoming({})
        self.controller.start_import(backup, self.today, self.today)
        self.assertFalse(self.controller.import_action.isEnabled())
        self.assertFalse(self.controller.exit_action.isEnabled())
        with self.assertRaises(RuntimeError):
            self.controller.start_import(backup, self.today, self.today)
        self.assertFalse(self.controller.request_exit())
        self.controller._poll_transfer(wait=True)
        self.assertTrue(self.controller.exit_action.isEnabled())

    def test_read_failure_does_not_pause_or_write_counts(self):
        self.tap()
        path = self.directory / "broken.qiaoqiao.json"
        path.write_text("{}", encoding="utf-8")
        self.controller._read_import(path)
        with self.assertLogs("qiaoqiao", level="ERROR"):
            self.controller._poll_transfer(wait=True)
        self.errors.assert_called_once()
        self.assertIsNone(self.controller._data_dialog)
        self.assertEqual(self.controller.model.counts, {(self.today.isoformat(), "1e"): 1})
        self.assertFalse((self.directory / "backups").exists())

    def test_read_preview_cancel_keeps_capture_and_data_untouched(self):
        backup = self.incoming({(self.today.isoformat(), "1e"): 50})
        self.controller._data_flow = True
        self.controller._read_import(self.directory / "incoming.qiaoqiao.json")
        self.controller._poll_transfer(wait=True)
        dialog = self.controller._data_dialog
        self.assertIsInstance(dialog, BackupDialog)
        self.assertEqual(dialog.backup, backup)
        self.tap()
        QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
        APPLICATION.processEvents()
        self.assertFalse(self.controller._data_flow)
        self.assertEqual(self.controller.model.counts, {(self.today.isoformat(), "1e"): 1})
        self.assertEqual(self.database.load(), {})

    def test_menu_and_export_dialog_flow(self):
        self.tap()
        self.assertIn(self.controller.export_action, self.controller.tray_data_menu.actions())
        self.assertIn(self.controller.import_action, self.controller.window.data_menu.actions())
        with patch("qiaoqiao.app.QFileDialog", TestFileDialog):
            self.controller.export_action.trigger()
            dialog = self.controller._data_dialog
            self.assertIsInstance(dialog, BackupDialog)
            QTest.mouseClick(dialog.submit_button, Qt.MouseButton.LeftButton)
            APPLICATION.processEvents()
            file_dialog = self.controller._data_dialog
            self.assertIsInstance(file_dialog, QFileDialog)
            path = self.directory / "flow.qiaoqiao.json"
            file_dialog.setDirectory(str(self.directory))
            name_edit = file_dialog.findChild(QLineEdit, "fileNameEdit")
            name_edit.selectAll()
            QTest.keyClicks(name_edit, path.name)
            self.assertEqual(Path(file_dialog.selectedFiles()[0]), path)
            file_dialog.accept()
            APPLICATION.processEvents()
        self.controller._poll_transfer(wait=True)
        self.assertEqual(read_backup(path).counts[(self.today.isoformat(), "1e")], 1)

    def test_import_file_picker_preview_and_confirmation_flow(self):
        self.incoming({(self.today.isoformat(), "1e"): 50})
        with patch("qiaoqiao.app.QFileDialog", TestFileDialog):
            self.controller.import_action.trigger()
            file_dialog = self.controller._data_dialog
            file_dialog.selectFile(str(self.directory / "incoming.qiaoqiao.json"))
            file_dialog.accept()
            APPLICATION.processEvents()
        self.controller._poll_transfer(wait=True)
        dialog = self.controller._data_dialog
        self.assertFalse(dialog.submit_button.isEnabled())
        QTest.mouseClick(dialog.confirm, Qt.MouseButton.LeftButton)
        QTest.mouseClick(dialog.submit_button, Qt.MouseButton.LeftButton)
        APPLICATION.processEvents()
        self.controller._poll_transfer(wait=True)
        self.assertEqual(self.database.load(), {(self.today.isoformat(), "1e"): 50})

    def test_post_commit_preference_error_never_restores_old_totals(self):
        self.tap()
        backup = self.incoming({(self.today.isoformat(), "1e"): 50})
        self.controller.window.tabs.setCurrentIndex(1)
        self.controller.start_import(backup, self.today, self.today)
        with self.assertLogs("qiaoqiao", level="ERROR"), \
                patch.object(self.controller, "_save_milestone_preferences", side_effect=OSError("preferences")):
            self.controller._poll_transfer(wait=True)
        self.assertIn("统计已导入", self.errors.call_args.args[1])
        self.assertEqual(self.controller.window.trends.cards[0].value.text(), "50")
        self.assertTrue(self.controller.persistence.flush())
        self.assertEqual(self.database.load(), {(self.today.isoformat(), "1e"): 50})

    def test_automatic_backup_can_restore_the_replaced_interval(self):
        self.tap()
        self.tap("30")
        original = dict(self.controller.model.counts)
        self.controller.start_import(self.incoming({}), self.today, self.today)
        self.controller._poll_transfer(wait=True)
        self.assertEqual(self.database.load(), {})
        before = read_backup(self.controller._transfer_path)
        self.controller.start_import(before, self.today, self.today)
        self.controller._poll_transfer(wait=True)
        self.assertEqual(self.database.load(), original)
        self.assertEqual(self.controller.model.counts, original)
        self.assertEqual(len(list((self.directory / "backups").glob("*.qiaoqiao.json"))), 2)

    def test_import_crossing_midnight_resumes_with_the_new_day_baseline(self):
        self.tap()
        backup = self.incoming({(self.today.isoformat(), "1e"): 5000})
        self.controller.start_import(backup, self.today, self.today)
        tomorrow = self.today + timedelta(days=1)
        with patch("qiaoqiao.app.datetime") as clock:
            clock.now.return_value = datetime.combine(tomorrow, datetime.min.time())
            self.tap("30")
            self.controller.tick()
            self.controller._poll_transfer(wait=True)
            self.tap()
        self.assertEqual(self.controller.milestones.day, tomorrow)
        self.assertEqual(self.controller.milestones.total, 1)
        self.assertIsNone(self.controller.milestones.pending)
        self.assertEqual(self.controller.model.counts, {
            (self.today.isoformat(), "1e"): 5000, (tomorrow.isoformat(), "1e"): 1,
        })


class BackupDialogTests(unittest.TestCase):
    def setUp(self):
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        APPLICATION.processEvents()

    def dialog(self, counts, backup=None):
        dialog = BackupDialog(counts, backup)
        self.dialogs.append(dialog)
        dialog.show()
        APPLICATION.processEvents()
        return dialog

    def test_month_export_caps_today_and_completed_month_includes_last_day(self):
        dialog = self.dialog({})
        today = date.today()
        self.assertEqual(dialog.selected_range(), (today.replace(day=1), today))
        QTest.keyClick(dialog.month_edit, Qt.Key.Key_Home)
        dialog.month_edit.setDate(QDate(2024, 2, 10))
        self.assertEqual(dialog.selected_range(), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertIn("清空", dialog.warning_label.text())
        self.assertFalse(dialog.mode_buttons["all"].isEnabled())

    def test_all_records_uses_observed_extent_and_custom_dates_are_validated(self):
        dialog = self.dialog({("2024-01-02", "1e"): 1, ("2024-02-04", "30"): 2})
        QTest.mouseClick(dialog.mode_buttons["all"], Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.selected_range(), (date(2024, 1, 2), date(2024, 2, 4)))
        QTest.mouseClick(dialog.mode_buttons["custom"], Qt.MouseButton.LeftButton)
        dialog.start_edit.setDate(QDate(2024, 3, 1))
        self.assertFalse(dialog.submit_button.isEnabled())
        self.assertIn("起始日期", dialog.warning_label.text())

    def test_import_subset_cannot_exceed_file_and_requires_fresh_confirmation(self):
        backup = Backup(date(2024, 2, 1), date(2024, 2, 29), {}, "0.2.2", "2024-03-01T10:00:00+08:00")
        dialog = self.dialog({("2024-02-09", "1e"): 100}, backup)
        self.assertFalse(dialog.submit_button.isEnabled())
        self.assertIn("清空", dialog.warning_label.text())
        QTest.mouseClick(dialog.confirm, Qt.MouseButton.LeftButton)
        self.assertTrue(dialog.submit_button.isEnabled())
        dialog.start_edit.setDate(QDate(2024, 2, 9))
        self.assertFalse(dialog.confirm.isChecked())
        dialog.start_edit.setDate(QDate(2024, 1, 1))
        dialog.end_edit.setDate(QDate(2024, 3, 1))
        self.assertEqual(dialog.selected_range(), (backup.start, backup.end))
        self.assertIn("100", dialog.summary_label.text())


if __name__ == "__main__":
    unittest.main()
