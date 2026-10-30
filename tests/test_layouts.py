import unittest

from qiaoqiao.keys import KEY_BY_ID
from qiaoqiao.layouts import DEFAULT_LAYOUT, LAYOUTS, LAYOUT_BY_ID


class LayoutTests(unittest.TestCase):
    def test_presets_have_expected_positions_and_unique_physical_keys(self):
        expected = {"full": 104, "tkl": 87, "75": 84, "65": 68, "60": 61, "laptop": 78}
        self.assertEqual(set(LAYOUT_BY_ID), set(expected))
        for layout in LAYOUTS:
            with self.subTest(layout=layout.layout_id):
                ids = [key.key_id for key in layout.keys if key.key_id is not None]
                self.assertEqual(len(layout.keys), expected[layout.layout_id])
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(set(ids) <= KEY_BY_ID.keys())
                self.assertTrue({"1e", "39", "1c", "1d", "2a", "36"} <= set(ids))
                self.assertTrue(all(KEY_BY_ID[key.key_id].label == key.label
                                    for key in layout.keys if key.key_id is not None))

    def test_geometry_has_no_overlaps_in_any_preset(self):
        for layout in LAYOUTS:
            for index, key in enumerate(layout.keys):
                with self.subTest(layout=layout.layout_id, key=key.label):
                    self.assertGreater(key.width, 0)
                    self.assertGreater(key.height, 0)
                    self.assertGreaterEqual(key.x, 0)
                    self.assertGreaterEqual(key.y, 0)
                    for other in layout.keys[index + 1:]:
                        overlap = (
                            key.x < other.x + other.width and other.x < key.x + key.width
                            and key.y < other.y + other.height and other.y < key.y + key.height
                        )
                        self.assertFalse(overlap, (key.label, other.label))

    def test_tkl_removes_only_numpad_and_shrinks_bounds(self):
        full = LAYOUT_BY_ID["full"]
        tkl = LAYOUT_BY_ID["tkl"]
        self.assertEqual(full.key_ids - tkl.key_ids, {
            "45", "e0_35", "37", "4a", "47", "48", "49", "4e", "4b",
            "4c", "4d", "4f", "50", "51", "e0_1c", "52", "53",
        })
        self.assertLess(tkl.width, full.width)

    def test_mini_presets_have_escape_and_keep_hidden_keys_distinct(self):
        for layout_id in ("65", "60"):
            layout = LAYOUT_BY_ID[layout_id]
            self.assertIn("01", layout.key_ids)
            self.assertNotIn("29", layout.key_ids)
            self.assertNotIn("3b", layout.key_ids)
        self.assertIn("e0_48", LAYOUT_BY_ID["65"].key_ids)
        self.assertNotIn("e0_48", LAYOUT_BY_ID["60"].key_ids)

    def test_fn_is_a_non_recordable_placeholder(self):
        for layout in LAYOUTS:
            fn = [key for key in layout.keys if key.label == "Fn"]
            self.assertEqual(len(fn), 0 if layout.layout_id in ("full", "tkl") else 1)
            self.assertTrue(all(key.key_id is None for key in fn))
            self.assertNotIn(None, layout.key_ids)

    def test_laptop_arrows_have_independent_half_height_positions(self):
        keys = {key.key_id: key for key in LAYOUT_BY_ID["laptop"].keys}
        up, down = keys["e0_48"], keys["e0_50"]
        self.assertEqual(up.height, 0.5)
        self.assertEqual(down.height, 0.5)
        self.assertEqual(up.x, down.x)
        self.assertEqual(up.y + up.height, down.y)
        self.assertIs(DEFAULT_LAYOUT, LAYOUT_BY_ID["full"])


if __name__ == "__main__":
    unittest.main()
