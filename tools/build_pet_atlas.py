"""Export the selected character as transparent frames, timing and contact points."""

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import render_pet_preview as art


OUTPUT = ROOT / "assets" / "pet" / "qiaoqiao-v2"
PREVIEW = ROOT / "docs" / "pet-animation-v1"
SIZE = 64
COLUMNS = 8
PALETTE = {
    name: getattr(art, name) for name in (
        "INK", "FRONT", "LIGHT", "SIDE", "SHADOW", "RIM", "FACE",
        "MINT", "MINT_DARK", "PINK", "EYE_LIGHT",
    )
}


@dataclass
class Action:
    name: str
    label: str
    images: list[QImage]
    durations: list[int]
    loop: bool
    anchor: tuple[int, int]
    contacts: list[tuple[int, int]]
    boundary: tuple[str, int] | None = None
    next_action: str | None = None


def canvas() -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return image


def torso(painter: QPainter, y: int, eye_height: int = 3,
          foot_y: int | None = 45, arm_offset: int = 0, dangling: bool = False,
          arms: bool = True) -> None:
    if foot_y is not None:
        art.feet(painter, foot_y, dangling)
        # The concept's feet start below the body: extend the legs through that gap.
        for x in (21, 37):
            art.box(painter, x, y + 30, 8, max(0, foot_y + 2 - y - 30), art.INK)
            art.box(painter, x + 2, y + 30, 4, max(0, foot_y + 2 - y - 30), art.SHADOW)
    if arms:
        art.limb(painter, y + 20 + arm_offset)
        art.limb(painter, y + 20 + arm_offset, False)
    art.body(painter, y, arms=False, legs=False)
    art.box(painter, 24, y + 19, 17, 5, art.FACE)
    for x in (26, 36):
        if eye_height == 1:
            art.box(painter, x - 1, y + 22, 5, 1, art.MINT)
        else:
            eye_y = y + (20 if eye_height >= 3 else 21)
            art.box(painter, x, eye_y, 3, eye_height, art.MINT)
            art.box(painter, x, eye_y, 1, 1, art.EYE_LIGHT)


def frame(pose: str, *, y: int = 12, eyes: int = 3, arm: int = 0,
          dx: int = 0, foot_y: int = 45, angle: float = 34) -> QImage:
    image = canvas()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    if pose in ("left", "right"):
        art.peek_left(painter, angle=angle, eye_height=eyes)
    elif pose == "bottom":
        torso(painter, y, eyes, foot_y=None, arms=False)
        for x in (17, 39):
            art.box(painter, x, 40, 10, 11, art.INK)
            art.box(painter, x + 1, 42, 8, 7, art.FRONT)
            art.box(painter, x + 1, 49, 8, 2, art.SIDE)
            art.box(painter, x + 2, 40, 6, 2, art.SIDE)
            art.box(painter, x + 1, 42, 1, 7, art.RIM)
    elif pose == "top":
        painter.save()
        painter.translate(dx, 0)
        torso(painter, y, eyes, foot_y=y + 32, arms=False)
        painter.restore()
        for x in (18, 41):
            art.box(painter, x, 15, 7, 13, art.INK)
            art.box(painter, x + 1, 16, 5, 9, art.FRONT)
            art.box(painter, x + 1, 15, 5, 2, art.SIDE)
            art.box(painter, x + 2, 17, 2, 2, art.PINK)
            art.box(painter, x + 1, 16, 1, 9, art.RIM)
    else:
        torso(painter, y, eyes, foot_y=foot_y, arm_offset=arm, dangling=pose == "drag")
    painter.end()
    return image.flipped(Qt.Orientation.Horizontal) if pose == "right" else image


def actions() -> list[Action]:
    floor = [(26, 55), (42, 55)]
    result = [
        Action("idle", "待机呼吸",
               [frame("idle", y=y, arm=arm) for y, arm in ((12, 0), (11, 1), (11, 0), (12, -1))],
               [1000, 450, 650, 900], True, (32, 55), floor),
        Action("blink", "待机眨眼",
               [frame("idle", eyes=eyes) for eyes in (3, 2, 1, 2, 3)],
               [30, 40, 80, 40, 30], False, (32, 55), floor, next_action="idle"),
        Action("drag", "拖动提起",
               [frame("drag", y=10, eyes=4, foot_y=42, arm=arm) for arm in (0, -1, 0, 1)],
               [220, 180, 220, 180], True, (32, 24), []),
    ]
    peek = ((34, 4), (35, 4), (36, 4), (36, 2), (36, 1), (36, 2), (35, 4), (34, 4))
    for name, label, boundary in (("left", "左边探身", 24), ("right", "右边探身", 40)):
        result.append(Action(
            name, label, [frame(name, angle=angle, eyes=eyes) for angle, eyes in peek],
            [4600, 140, 600, 40, 80, 40, 140, 1260], True,
            (boundary, 46), [(boundary, 46)], ("x", boundary),
        ))
    result.extend([
        Action("bottom", "底边趴伏",
               [frame("bottom", y=y, eyes=eyes) for y, eyes in
                ((13, 3), (12, 3), (12, 2), (12, 1), (12, 2), (12, 3), (13, 3), (13, 3))],
               [2200, 900, 40, 80, 40, 740, 900, 1100], True,
               (32, 51), [(22, 51), (44, 51)], ("y", 51)),
        Action("top", "顶边悬挂",
               [frame("top", y=19, dx=dx, eyes=eyes) for dx, eyes in
                ((0, 3), (1, 3), (0, 3), (-1, 3), (0, 3), (0, 2), (0, 1), (0, 2))],
               [1800, 650, 900, 650, 1840, 40, 80, 40], True,
               (32, 15), [(21, 15), (44, 15)], ("y", 15)),
        Action("settle", "松开回弹",
               [frame("drag" if index == 0 else "idle", y=y,
                      eyes=4 if index == 0 else 3, foot_y=42 if index == 0 else 45)
                for index, y in enumerate((10, 13, 14, 11, 12))],
               [50, 50, 60, 60, 80], False,
               (32, 55), [], next_action="idle"),
    ])
    return result


def opaque_bounds(image: QImage) -> list[int]:
    points = [(x, y) for y in range(SIZE) for x in range(SIZE)
              if image.pixelColor(x, y).alpha()]
    x0, y0 = min(x for x, _ in points), min(y for _, y in points)
    x1, y1 = max(x for x, _ in points), max(y for _, y in points)
    return [x0, y0, x1 - x0 + 1, y1 - y0 + 1]


def save_png(image: QImage, path: Path) -> None:
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not write {path}")


def write_atlas(items: list[Action], *, columns: int = COLUMNS, schema_version: int = 1) -> dict:
    atlas = QImage(columns * SIZE, len(items) * SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    atlas.fill(Qt.GlobalColor.transparent)
    manifest = {
        "schema_version": schema_version,
        "character": "qiaoqiao-keycap",
        "design_version": 2,
        "status": "runtime" if schema_version == 2 else "motion-review",
        "image": "atlas.png",
        "frame_size": [SIZE, SIZE],
        "atlas_size": [atlas.width(), atlas.height()],
        "columns": columns,
        "rows": len(items),
        "recommended_scale": 2,
        "sampling": "nearest",
        "palette": PALETTE,
        "coordinates": "Top-left origin; anchors and contacts use pixel boundaries.",
        "actions": {},
    }
    painter = QPainter(atlas)
    for row, action in enumerate(items):
        frames = []
        for column, (image, duration) in enumerate(zip(action.images, action.durations, strict=True)):
            rect = [column * SIZE, row * SIZE, SIZE, SIZE]
            painter.drawImage(rect[0], rect[1], image)
            frames.append({"rect": rect, "duration_ms": duration, "bounds": opaque_bounds(image)})
        manifest["actions"][action.name] = {
            "label": action.label,
            "row": row,
            "loop": action.loop,
            "next": action.next_action,
            "anchor": action.anchor,
            "contacts": action.contacts,
            "boundary": {"axis": action.boundary[0], "value": action.boundary[1]} if action.boundary else None,
            "duration_ms": sum(action.durations),
            "frames": frames,
        }
    painter.end()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "atlas.png"
    save_png(atlas, path)
    manifest["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUTPUT / "atlas.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return manifest


def draw_guide(painter: QPainter, action: Action, x: int, y: int, scale: int) -> None:
    if action.boundary is None:
        return
    axis, value = action.boundary
    painter.setPen(QPen(QColor("#8A8994"), 1))
    if axis == "x":
        painter.drawLine(x + value * scale, y + 4 * scale, x + value * scale, y + 60 * scale)
    else:
        painter.drawLine(x + 8 * scale, y + value * scale, x + 56 * scale, y + value * scale)


def write_contact_sheet(items: list[Action]) -> None:
    width, row_height = 1328, 164
    sheet = QImage(width, 112 + row_height * len(items), QImage.Format.Format_RGB32)
    sheet.fill(QColor("#E1E2E7"))
    painter = QPainter(sheet)
    art.text(painter, QRect(24, 12, 1250, 44), "敲敲 / 动作图集第一版", 20, art.FACE, QFont.Weight.DemiBold)
    art.text(painter, QRect(24, 59, 1250, 32), "64 × 64 透明帧 · 此图按 2 倍展示 · 每帧下方为停留时长", 10, art.GUIDE)
    for row, action in enumerate(items):
        y = 104 + row * row_height
        if row % 2:
            art.box(painter, 0, y, width, row_height, "#D5D7DE")
        art.text(painter, QRect(24, y + 36, 160, 34), action.label, 13, art.FACE, QFont.Weight.DemiBold)
        art.text(painter, QRect(24, y + 76, 170, 27),
                 f"{len(action.images)} 帧 / {sum(action.durations)} ms", 9, art.GUIDE)
        art.text(painter, QRect(24, y + 104, 160, 27),
                 "循环" if action.loop else "单次后回待机", 9, art.GUIDE)
        for column, (image, duration) in enumerate(zip(action.images, action.durations, strict=True)):
            x = 192 + column * 140
            draw_guide(painter, action, x, y, 2)
            art.scaled(painter, image, x, y, 2)
            art.text(painter, QRect(x, y + 128, 128, 28), f"{duration} ms", 9, art.GUIDE,
                     align=Qt.AlignmentFlag.AlignHCenter)
    painter.end()
    PREVIEW.mkdir(parents=True, exist_ok=True)
    save_png(sheet, PREVIEW / "contact-sheet.png")


def main() -> None:
    from tools.build_pet_runtime import runtime_actions

    app = QApplication([])
    items = runtime_actions()
    manifest = write_atlas(items, columns=12, schema_version=2)
    write_contact_sheet(actions())
    print(f"Atlas: {OUTPUT / 'atlas.png'}")
    print(f"Manifest: {OUTPUT / 'atlas.json'}")
    print(f"Actions: {len(items)}; frames: {sum(len(a.images) for a in items)}")
    print(f"SHA256: {manifest['sha256']}")
    app.quit()


if __name__ == "__main__":
    main()
