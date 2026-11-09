import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from qiaoqiao.backup import MAX_COUNT, read_backup, write_backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "portable.qiaoqiao.json"
        self.start, self.end = date(2026, 10, 1), date(2026, 10, 31)
        self.counts = {
            ("2026-09-30", "1e"): 8,
            ("2026-10-01", "1e"): 0,
            ("2026-10-09", "e0_64"): 50,
            ("2026-10-31", "e1_45"): MAX_COUNT,
            ("2026-11-01", "1e"): 99,
        }
        write_backup(self.path, self.counts, self.start, self.end)
        self.payload = json.loads(self.path.read_text(encoding="utf-8"))

    def tearDown(self):
        self.temp.cleanup()

    def write_payload(self, payload, checksum=True):
        if checksum:
            content = {key: value for key, value in payload.items() if key != "checksum"}
            digest = hashlib.sha256(json.dumps(
                content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")).hexdigest()
            payload["checksum"] = {"algorithm": "sha256", "value": digest}
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_round_trip_includes_boundary_days_zero_and_layout_external_keys(self):
        backup = read_backup(self.path)
        self.assertEqual((backup.start, backup.end), (self.start, self.end))
        self.assertEqual(backup.counts, {
            key: count for key, count in self.counts.items() if "2026-10-01" <= key[0] <= "2026-10-31"
        })
        self.assertIsNotNone(datetime.fromisoformat(backup.exported_at).utcoffset())
        self.assertEqual(set(self.payload), {
            "format", "format_version", "app_version", "exported_at", "date_range", "daily_counts", "checksum",
        })

    def test_empty_range_is_explicit_and_can_be_restored(self):
        write_backup(self.path, {}, self.start, self.end)
        backup = read_backup(self.path)
        self.assertEqual(backup.counts, {})
        self.assertEqual((backup.start, backup.end), (self.start, self.end))

    def test_subrange_selection_does_not_change_file_scope(self):
        backup = read_backup(self.path)
        self.assertEqual(backup.select(date(2026, 10, 9), date(2026, 10, 9)), {("2026-10-09", "e0_64"): 50})
        for start, end in (
            (date(2026, 9, 30), self.end), (self.start, date(2026, 11, 1)),
            (self.end, self.start),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                backup.select(start, end)

    def test_tampering_with_scope_records_or_metadata_fails_checksum(self):
        for field in ("date_range", "daily_counts", "exported_at"):
            payload = deepcopy(self.payload)
            if field == "date_range":
                payload[field]["start"] = "2026-09-01"
            elif field == "daily_counts":
                payload[field][0]["count"] += 1
            else:
                payload[field] = "2026-11-01T08:30:00+08:00"
            self.write_payload(payload, checksum=False)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "校验失败"):
                read_backup(self.path)

    def test_invalid_records_rejected_even_with_valid_checksum(self):
        invalid = [
            {"count": True}, {"count": 1.5}, {"count": -1}, {"count": MAX_COUNT + 1},
            {"count": "50"}, {"key_id": "A"}, {"key_id": None}, {"key_id": "e0_80"},
            {"day": "2026-02-30"}, {"day": "20261001"}, {"day": "2026-09-30"},
            {"day": 20261001}, {"extra": "unsupported"},
        ]
        for change in invalid:
            payload = deepcopy(self.payload)
            payload["daily_counts"][0].update(change)
            self.write_payload(payload)
            with self.subTest(change=change), self.assertRaises(ValueError):
                read_backup(self.path)

    def test_duplicate_records_and_object_fields_rejected(self):
        payload = deepcopy(self.payload)
        payload["daily_counts"].append(dict(payload["daily_counts"][0]))
        self.write_payload(payload)
        with self.assertRaisesRegex(ValueError, "重复"):
            read_backup(self.path)
        self.path.write_text('{"format":"qiaoqiao-backup","format":"qiaoqiao-backup"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "重复"):
            read_backup(self.path)

    def test_invalid_metadata_and_unknown_versions_rejected(self):
        for change in (
            {"format": "other"}, {"format_version": 2}, {"format_version": True},
            {"exported_at": "2026-11-09T10:00:00"}, {"app_version": []},
            {"date_range": {"start": "2026-10-31", "end": "2026-10-01"}},
            {"date_range": {}}, {"daily_counts": {}}, {"extra": "unsupported"},
        ):
            payload = deepcopy(self.payload)
            payload.update(change)
            self.write_payload(payload)
            with self.subTest(change=change), self.assertRaises(ValueError):
                read_backup(self.path)

    def test_malformed_utf8_json_and_excessive_size_rejected(self):
        for raw in (b"\xff", b"{", b"[]", b"null"):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                read_backup(self.path)
        self.path.write_bytes(b" " * 17)
        with patch("qiaoqiao.backup.MAX_FILE_BYTES", 16), self.assertRaisesRegex(ValueError, "超过"):
            read_backup(self.path)

    def test_file_whitespace_and_utf8_bom_do_not_affect_checksum(self):
        self.path.write_text(json.dumps(self.payload, indent=4), encoding="utf-8-sig")
        self.assertEqual(len(read_backup(self.path).counts), 3)

    def test_atomic_replacement_failure_preserves_existing_backup(self):
        original = self.path.read_bytes()
        with patch("qiaoqiao.backup.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_backup(self.path, {}, self.start, self.end)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob(".qiaoqiao-*")), [])

    def test_invalid_export_leaves_existing_file_intact(self):
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            write_backup(self.path, {("2026-10-09", "1e"): -1}, self.start, self.end)
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
