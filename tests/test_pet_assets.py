"""Check the exported animation contract independently of the drawing helpers."""

import hashlib
import json
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "pet" / "qiaoqiao-v2"


def points(image, predicate=lambda color: color.alpha() > 0):
    return {(x, y) for y in range(image.height()) for x in range(image.width())
            if predicate(image.pixelColor(x, y))}


def components(pixels):
    remaining = set(pixels)
    result = []
    while remaining:
        start = remaining.pop()
        pending, group = [start], {start}
        while pending:
            x, y = pending.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    point = (x + dx, y + dy)
                    if point in remaining:
                        remaining.remove(point)
                        group.add(point)
                        pending.append(point)
        result.append(group)
    return result


class PetAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ASSETS / "atlas.json").read_text(encoding="utf-8"))
        cls.path = ASSETS / cls.manifest["image"]
        cls.image = QImage(str(cls.path))
        cls.actions = cls.manifest["actions"]

    def frames(self, name):
        return [self.image.copy(*frame["rect"]) for frame in self.actions[name]["frames"]]

    def test_atlas_layout_timing_and_checksum(self):
        self.assertFalse(self.image.isNull())
        self.assertEqual(self.manifest["frame_size"], [64, 64])
        self.assertEqual([self.image.width(), self.image.height()], self.manifest["atlas_size"])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.manifest["sha256"])
        self.assertEqual(set(self.actions), {"idle", "blink", "drag", "left", "right", "bottom", "top", "settle"})
        for row, (name, action) in enumerate(self.actions.items()):
            self.assertEqual(action["row"], row)
            self.assertLessEqual(len(action["frames"]), self.manifest["columns"])
            self.assertEqual(sum(f["duration_ms"] for f in action["frames"]), action["duration_ms"])
            self.assertEqual(action["next"], None if action["loop"] else "idle")
            for col, frame in enumerate(action["frames"]):
                self.assertEqual(frame["rect"], [col * 64, row * 64, 64, 64])
                self.assertGreater(frame["duration_ms"], 0)
            for col in range(len(action["frames"]), self.manifest["columns"]):
                self.assertFalse(points(self.image.copy(col * 64, row * 64, 64, 64)), name)

    def test_alpha_palette_and_tight_bounds(self):
        allowed = {color.lower() for color in self.manifest["palette"].values()}
        for name, action in self.actions.items():
            for index, (image, metadata) in enumerate(zip(self.frames(name), action["frames"])):
                with self.subTest(action=name, frame=index):
                    occupied = points(image)
                    self.assertTrue(occupied)
                    for y in range(64):
                        for x in range(64):
                            color = image.pixelColor(x, y)
                            self.assertIn(color.alpha(), (0, 255))
                            if color.alpha():
                                self.assertIn(color.name(), allowed)
                            else:
                                self.assertEqual(color.rgb() & 0xFFFFFF, 0)
                    x0, y0 = min(x for x, _ in occupied), min(y for _, y in occupied)
                    x1, y1 = max(x for x, _ in occupied), max(y for _, y in occupied)
                    self.assertEqual(metadata["bounds"], [x0, y0, x1 - x0 + 1, y1 - y0 + 1])
                    self.assertTrue(0 < x0 <= x1 < 63 and 0 < y0 <= y1 < 63)

    def test_body_is_connected_and_both_eyes_remain_visible(self):
        eye_colors = {self.manifest["palette"][name].lower() for name in ("MINT", "EYE_LIGHT")}
        for name in self.actions:
            for index, image in enumerate(self.frames(name)):
                with self.subTest(action=name, frame=index):
                    self.assertEqual(len(components(points(image))), 1, "Detached limb or stray pixel")
                    eyes = points(image, lambda color: color.alpha() and color.name() in eye_colors)
                    self.assertEqual(len(components(eyes)), 2, "Missing or merged eyes")

    def test_contact_pixels_remain_fixed_and_no_edge_leaks(self):
        patches = {
            "idle": [(21, 47, 10, 8), (37, 47, 10, 8)],
            "blink": [(21, 47, 10, 8), (37, 47, 10, 8)],
            "left": [(24, 42, 5, 8)],
            "right": [(35, 42, 5, 8)],
            "bottom": [(17, 42, 10, 9), (39, 42, 10, 9)],
            "top": [(18, 15, 7, 4), (41, 15, 7, 4)],
        }
        for name, rects in patches.items():
            frames = self.frames(name)
            for index, image in enumerate(frames):
                with self.subTest(action=name, frame=index):
                    for rect in rects:
                        self.assertEqual(image.copy(*rect), frames[0].copy(*rect))
                    occupied = points(image)
                    if name == "left":
                        self.assertTrue(all(x >= 24 for x, _ in occupied))
                    elif name == "right":
                        self.assertTrue(all(x < 40 for x, _ in occupied))
                    elif name == "bottom":
                        self.assertTrue(all(y < 51 for _, y in occupied))
                    elif name == "top":
                        self.assertTrue(all(y >= 15 for _, y in occupied))
                    else:
                        self.assertEqual(max(y for _, y in occupied), 54)

    def test_motion_varies_and_one_shots_return_to_idle(self):
        for name in self.actions:
            frames = self.frames(name)
            self.assertTrue(any(image != frames[0] for image in frames[1:]), name)
        idle = self.frames("idle")[0]
        self.assertEqual(self.frames("blink")[0], idle)
        self.assertEqual(self.frames("blink")[-1], idle)
        self.assertEqual(self.frames("settle")[-1], idle)
        self.assertEqual(self.frames("settle")[0], self.frames("drag")[0])
        for left, right in zip(self.frames("left"), self.frames("right")):
            self.assertEqual(right, left.flipped(Qt.Orientation.Horizontal))


if __name__ == "__main__":
    unittest.main()
