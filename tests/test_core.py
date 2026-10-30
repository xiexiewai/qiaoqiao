import unittest
from datetime import date

from qiaoqiao.core import CounterModel, date_range, move_date
from qiaoqiao.keys import KEYS, PhysicalEvent, normalize


class CountingTests(unittest.TestCase):
    def setUp(self):
        self.model = CounterModel()
        self.day = date(2026, 10, 30)

    def press(self, device=1, key="1e", down=True, day=None):
        return self.model.accept(PhysicalEvent(device, key, down), day or self.day)

    def test_hold_only_counts_once_and_release_rearms(self):
        self.press()
        for _ in range(100):
            self.press()
        self.press(down=False)
        self.press()
        self.assertEqual(self.model.totals("day", self.day)["1e"], 2)

    def test_devices_do_not_share_pressed_state(self):
        self.press(1)
        self.press(2)
        self.press(1)
        self.assertEqual(self.model.totals("day", self.day)["1e"], 2)

    def test_chord_counts_each_physical_key(self):
        self.press(key="1d")
        self.press(key="2e")
        self.assertEqual(sum(self.model.totals("day", self.day).values()), 2)

    def test_cross_midnight_hold_is_not_recounted(self):
        tomorrow = date(2026, 10, 31)
        self.press()
        self.press(day=tomorrow)
        self.assertEqual(sum(self.model.totals("day", tomorrow).values()), 0)
        self.press(down=False, day=tomorrow)
        self.press(day=tomorrow)
        self.assertEqual(self.model.totals("day", tomorrow)["1e"], 1)

    def test_device_removal_clears_only_that_device(self):
        self.press(1)
        self.press(2)
        self.model.release_device(1)
        self.press(1)
        self.press(2)
        self.assertEqual(self.model.totals("all", self.day)["1e"], 3)

    def test_recovery_clears_stuck_states(self):
        self.press()
        self.model.release_all()
        self.press()
        self.assertEqual(self.model.totals("all", self.day)["1e"], 2)

    def test_failed_snapshot_retry_uses_latest_values(self):
        self.press()
        old = self.model.snapshot_dirty()
        self.press(down=False)
        self.press()
        self.model.retry(old)
        self.assertEqual(self.model.snapshot_dirty()[(self.day.isoformat(), "1e")], 2)

    def test_aggregation_contains_saved_history_and_live_counts(self):
        model = CounterModel({("2026-10-29", "1e"): 3, ("2026-09-30", "1e"): 10})
        model.accept(PhysicalEvent(1, "1e", True), self.day)
        self.assertEqual(model.totals("day", self.day)["1e"], 1)
        self.assertEqual(model.totals("week", self.day)["1e"], 4)
        self.assertEqual(model.totals("month", self.day)["1e"], 4)
        self.assertEqual(model.totals("all", self.day)["1e"], 14)


class KeyMappingTests(unittest.TestCase):
    def test_104_unique_physical_positions(self):
        self.assertEqual(len(KEYS), 104)
        self.assertEqual(len({key.key_id for key in KEYS}), 104)

    def test_left_right_and_numpad_are_distinct(self):
        for code, vk in ((0x1D, 0x11), (0x38, 0x12), (0x1C, 0x0D), (0x48, 0x26)):
            self.assertNotEqual(normalize(1, code, 0, vk).key_id, normalize(1, code, 2, vk).key_id)

    def test_num_lock_does_not_change_numpad_key_identity(self):
        self.assertEqual(normalize(1, 0x47, 0, 0x67).key_id, normalize(1, 0x47, 0, 0x24).key_id)
        self.assertEqual(normalize(1, 0x45, 2, 0x90).key_id, "45")

    def test_fake_prefixes_and_overrun_ignored(self):
        for code, flags, vk in ((0x2A, 2, 0x10), (0x36, 2, 0x10), (0x1D, 4, 0x11),
                                (0xFF, 0, 0xFF), (0, 0, 0), (0x30, 0, 0xFF)):
            self.assertIsNone(normalize(1, code, flags, vk))

    def test_print_screen_alt_variant_is_same_key(self):
        self.assertEqual(normalize(1, 0x54, 0, 0x2C).key_id, "e0_37")

    def test_pause_without_release_can_be_pressed_again(self):
        model = CounterModel()
        for _ in range(2):
            model.accept(normalize(1, 0x45, 4, 0x13), date(2026, 10, 30))
        self.assertEqual(model.totals("all", date.today())["e1_45"], 2)
        self.assertFalse(model.pressed)

    def test_unknown_scan_code_preserved(self):
        self.assertEqual(normalize(9, 0x64, 2, 0x7C).key_id, "e0_64")


class CalendarTests(unittest.TestCase):
    def test_week_crosses_year(self):
        self.assertEqual(date_range("week", date(2027, 1, 1)), (date(2026, 12, 28), date(2027, 1, 3)))

    def test_month_leap_day(self):
        self.assertEqual(date_range("month", date(2028, 2, 12)), (date(2028, 2, 1), date(2028, 2, 29)))

    def test_month_navigation_clamps_day(self):
        self.assertEqual(move_date(date(2026, 1, 31), "month", 1), date(2026, 2, 28))
        self.assertEqual(move_date(date(2026, 12, 31), "month", 1), date(2027, 1, 31))


if __name__ == "__main__":
    unittest.main()
