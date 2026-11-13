"""Author the second motion review separately from the installed pet atlas."""

import hashlib
import json
import sys
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_pet_atlas as base
from tools import render_pet_preview as art


OUTPUT = ROOT / "docs" / "pet-animation-v2"
POSES = {"free": "自由摆放", "left": "左边探身", "right": "右边探身",
         "top": "顶边悬挂", "bottom": "底边趴伏"}


@dataclass(frozen=True)
class State:
    dy: int = 0
    dx: int = 0
    squash: int = 0
    eyes: str = "open"
    gaze: tuple[int, int] = (0, 0)
    hands: tuple[str, str] = ("rest", "rest")
    kicks: tuple[int, int] = (0, 0)
    hop: int = 0
    lean: int = 0


REST = State()


@lru_cache(maxsize=1)
def reference_frames() -> dict[str, QImage]:
    return {a.name: a.images[0] for a in base.actions()}


@dataclass
class Clip:
    name: str
    label: str
    group: str
    states: list[State]
    durations: list[int]
    loop: bool = False
    next_action: str = "rest"
    note: str = ""


def clips() -> list[Clip]:
    return [
        Clip("rest", "原有待机参考", "参考", [REST], [1600], True,
             note="沿用当前程序的第一帧，作为衔接基准。"),
        Clip("tap", "单次敲击", "敲击",
             [REST, State(dy=1, squash=1, eyes="wide", hands=("tap", "rest")),
              State(dy=2, squash=2, hands=("tap", "rest")),
              State(dy=-1, hands=("lift", "rest")), REST],
             [30, 60, 70, 70, 70], note="轻压、落手、回弹；一轮 300 ms。"),
        Clip("typing", "连续敲击", "敲击",
             [State(dy=1, squash=1, hands=("tap", "lift")),
              State(hands=("lift", "rest")), State(dy=-1),
              State(dy=1, squash=1, hands=("lift", "tap")),
              State(hands=("rest", "lift")), REST],
             [80] * 6, True, note="左右手交替，480 ms 循环；接入后由敲击延长播放。"),
        Clip("celebrate", "千次庆祝", "庆祝",
             [REST, State(dy=2, squash=2, eyes="half", hands=("lift", "lift")),
              State(hop=-2, eyes="happy", hands=("up", "up")),
              State(hop=-4, eyes="happy", hands=("up", "up")),
              State(hop=-2, eyes="happy", hands=("up", "up")),
              State(dy=2, squash=2, eyes="happy", hands=("lift", "lift")),
              State(dy=-1, eyes="happy"), REST],
             [100, 160, 140, 260, 140, 150, 230, 220],
             note="一次小跳、举手和笑眼；贴边时变为身体提起与空闲肢体欢呼。"),
        Clip("celebrate_big", "万次庆祝", "庆祝",
             [REST, State(dy=2, squash=2, eyes="half", hands=("lift", "lift")),
              State(hop=-4, eyes="happy", hands=("up", "up")),
              State(hop=-2, eyes="happy", hands=("up", "up")),
              State(dy=2, squash=2, eyes="happy"),
              State(hop=-5, eyes="happy", hands=("up", "up")),
              State(hop=-3, eyes="happy", hands=("up", "up")),
              State(dy=2, squash=2, eyes="happy", hands=("lift", "lift")),
              State(dy=-1, eyes="happy", hands=("up", "lift")),
              State(eyes="happy", hands=("up", "lift")),
              State(eyes="happy"), REST],
             [100, 140, 200, 120, 140, 240, 140, 140, 240, 460, 200, 180],
             note="两次小跳后得意停顿；不增加闪屏、文字或彩纸。"),
        Clip("hover", "悬停招呼", "鼠标",
             [REST, State(dy=-1, eyes="wide"),
              State(dy=-1, eyes="wide", gaze=(1, 0)),
              State(dy=-1, eyes="closed", gaze=(1, 0)),
              State(dy=-1, gaze=(1, 0)), State(gaze=(1, 0))],
             [80, 120, 180, 80, 100, 100], next_action="hover_hold",
             note="抬头、望向鼠标、轻眨眼；预览以鼠标在右侧为例。"),
        Clip("hover_hold", "悬停注视", "鼠标",
             [State(gaze=(1, 0)), State(dy=-1, gaze=(1, 0)),
              State(dy=-1, gaze=(1, 0)), State(gaze=(1, 0))],
             [800, 450, 450, 700], True,
             note="只轻呼吸，不反复打招呼；此处为向右注视。"),
        Clip("hover_left", "向左注视", "鼠标",
             [State(gaze=(-1, 0)), State(dy=-1, gaze=(-1, 0)), State(gaze=(-1, 0))],
             [900, 600, 900], True),
        Clip("hover_up", "向上注视", "鼠标",
             [State(gaze=(0, -1)), State(dy=-1, gaze=(0, -1)), State(gaze=(0, -1))],
             [900, 600, 900], True),
        Clip("hover_down", "向下注视", "鼠标",
             [State(gaze=(0, 1)), State(dy=-1, gaze=(0, 1)), State(gaze=(0, 1))],
             [900, 600, 900], True),
        Clip("hover_leave", "移开回望", "鼠标",
             [State(gaze=(1, 0)), State(eyes="half"), REST], [60, 60, 80],
             note="收回注视，200 ms 回到当前姿态。"),
        Clip("click", "单击回应", "鼠标",
             [REST, State(dy=1, squash=1, eyes="wide"),
              State(dx=1, eyes="wide", hands=("cheek", "rest")),
              State(dx=1, eyes="happy", hands=("cheek", "rest")),
              State(eyes="happy", hands=("cheek", "rest")),
              State(eyes="happy", hands=("lift", "rest")), REST],
             [40, 90, 100, 140, 100, 80, 100],
             note="惊讶、轻歪、摸脸和笑眼；双手扶边时改为身体轻侧摆。"),
        Clip("look", "左右张望", "待机",
             [REST, State(gaze=(-1, 0)), State(dx=-1, gaze=(-1, 0)),
              State(eyes="half"), State(gaze=(1, 0)),
              State(dx=1, gaze=(1, 0)), State(eyes="half"), REST],
             [200, 200, 600, 100, 200, 600, 100, 200],
             note="先左后右，再回正；没有自主移动。"),
        Clip("stretch", "伸个懒腰", "待机",
             [REST, State(dy=1, squash=1, eyes="half", hands=("lift", "lift")),
              State(dy=-1, eyes="closed", hands=("up", "up")),
              State(dy=-2, eyes="closed", hands=("stretch", "stretch")),
              State(dy=-1, eyes="happy", hands=("stretch", "stretch")),
              State(hands=("up", "up")), State(hands=("lift", "lift")), REST],
             [180, 200, 280, 640, 420, 260, 220, 200],
             note="上举、舒展、放松；顶边保持抓握并伸展身体和腿。"),
        Clip("play", "摆手踢脚", "待机",
             [REST, State(dx=-1, hands=("up", "lift"), kicks=(-3, 0)),
              State(dx=-1, eyes="happy", hands=("lift", "up"), kicks=(-2, 0)),
              REST, State(dx=1, hands=("lift", "up"), kicks=(0, -3)),
              State(dx=1, eyes="happy", hands=("up", "lift"), kicks=(0, -2)),
              State(eyes="happy"), REST],
             [200, 300, 320, 180, 300, 320, 360, 220],
             note="原地左右摆手踢脚；边缘只活动没有承担支撑的肢体。"),
        Clip("doze", "打瞌睡", "休息",
             [REST, State(eyes="half"), State(dy=1, eyes="half"),
              State(dy=2, squash=1, eyes="closed"),
              State(dy=2, squash=1, eyes="closed"), State(dy=-1, eyes="wide"),
              State(eyes="half"), REST],
             [300, 450, 450, 500, 350, 180, 300, 270],
             note="眼皮下垂、点头后短暂清醒。"),
        Clip("sleep", "浅睡呼吸", "休息",
             [State(dy=2, squash=1, eyes="closed"),
              State(dy=1, squash=1, eyes="closed"),
              State(dy=1, squash=1, eyes="closed"),
              State(dy=2, squash=1, eyes="closed")],
             [1400, 700, 700, 1200], True,
             note="闭眼慢呼吸；保持贴边抓握，无漂浮睡眠符号。"),
        Clip("wake", "醒来", "休息",
             [State(dy=2, squash=1, eyes="closed"), State(dy=1, eyes="half"),
              State(dy=-1, eyes="wide"), State(eyes="wide"), REST],
             [40, 50, 60, 50, 60], note="260 ms 睁眼回正，之后可接敲击或单击。"),
    ]


def drag_clips() -> list[Clip]:
    return [
        Clip("pickup", "提起一惊", "拖动",
             [REST, State(dy=-1, eyes="wide", hands=("lift", "lift")),
              State(dy=-2, eyes="wide", hands=("up", "lift"))],
             [40, 50, 60], next_action="struggle"),
        Clip("struggle", "拖动挣扎", "拖动",
             [State(dx=-1, eyes="wide", hands=("up", "lift"), kicks=(0, -3)),
              State(dx=-1, eyes="wide", hands=("stretch", "tap"), kicks=(-3, 0)),
              State(eyes="wide", hands=("lift", "up"), kicks=(-2, 0)),
              State(dx=1, eyes="wide", hands=("tap", "stretch"), kicks=(0, -3)),
              State(dx=1, eyes="wide", hands=("lift", "up"), kicks=(-3, 0)),
              State(eyes="wide", hands=("up", "lift"), kicks=(0, -2)),
              State(dx=-1, eyes="wide", hands=("stretch", "tap"), kicks=(0, -3)),
              State(eyes="wide", hands=("up", "lift"))],
             [90] * 8, True, note="双手交替挥动、腿交替踢动；画布和提起参考点固定。"),
        Clip("release", "放下回弹", "拖动",
             [State(dy=-2, eyes="wide"), State(dy=1, squash=1),
              State(dy=2, squash=2), State(dy=-1), REST],
             [50, 50, 60, 60, 80], note="300 ms 落稳；仅展示自由位置释放。"),
    ]


def eyes(painter: QPainter, positions: tuple[int, int], y: int,
         state: State, *, side: bool = False) -> None:
    gx, gy = state.gaze
    for x in positions:
        x += gx
        if state.eyes == "closed":
            art.box(painter, x - (0 if side else 1), y + 2 + gy,
                    3 if side else 5, 1, art.MINT)
        elif state.eyes == "happy":
            if side:
                art.box(painter, x, y + gy, 3, 2, art.MINT)
                art.box(painter, x, y + 2 + gy, 1, 1, art.MINT)
                art.box(painter, x + 2, y + 2 + gy, 1, 1, art.MINT)
            else:
                art.box(painter, x + 1, y + gy, 1, 1, art.MINT)
                art.box(painter, x, y + 1 + gy, 1, 2, art.MINT)
                art.box(painter, x + 2, y + 1 + gy, 1, 2, art.MINT)
        else:
            height = {"wide": 4, "half": 2, "open": 4 if side else 3}[state.eyes]
            ey = y + gy + (1 if height == 2 else 0)
            art.box(painter, x, ey, 3, height, art.MINT)
            art.box(painter, x, ey, 1, 1, art.EYE_LIGHT)


def head(state: State) -> QImage:
    image = base.canvas()
    painter = QPainter(image)
    art.body(painter, 12, arms=False, legs=False)
    art.box(painter, 24, 30, 17, 7, art.FACE)
    eyes(painter, (26, 36), 32, state)
    if state.eyes == "happy":
        art.box(painter, 31, 37, 1, 1, art.RIM)
        art.box(painter, 32, 38, 2, 1, art.RIM)
        art.box(painter, 34, 37, 1, 1, art.RIM)
    painter.end()
    return image


def stroke(painter: QPainter, points: list[tuple[int, int]], color: str, width: int) -> None:
    painter.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
    for start, end in zip(points, points[1:]):
        painter.drawLine(QPoint(*start), QPoint(*end))


def palm(painter: QPainter, x: int, y: int) -> None:
    art.box(painter, x - 3, y - 3, 7, 7, art.INK)
    art.box(painter, x - 2, y - 2, 5, 4, art.SIDE)
    art.box(painter, x - 2, y + 1, 5, 2, art.FRONT)
    art.box(painter, x - 2, y - 2, 1, 3, art.RIM)


def arm(painter: QPainter, side: int, mode: str, y: int, dx: int) -> None:
    if mode == "rest":
        painter.save()
        painter.translate(dx, 0)
        art.limb(painter, y + 20, side == 0)
        painter.restore()
        return
    positions = {"tap": (10, y + 28), "lift": (9, y + 17),
                 "up": (11, y + 6), "stretch": (7, y + 2),
                 "cheek": (20, y + 24)}
    x, hy = positions[mode]
    shoulder = (16, y + 22)
    elbow = (9 if mode != "cheek" else 11, y + 24 if mode == "cheek" else y + 17)
    points = [shoulder, elbow, (x, hy)]
    if side:
        points = [(63 - px, py) for px, py in points]
    points = [(px + dx, py) for px, py in points]
    stroke(painter, points, art.INK, 5)
    stroke(painter, points, art.SIDE, 3)
    palm(painter, *points[-1])


def foot(painter: QPainter, x: int, y: int, body_y: int, *, dangling: bool) -> None:
    art.box(painter, x, body_y + 28, 8, max(1, y + 6 - body_y - 28), art.INK)
    art.box(painter, x + 2, body_y + 28, 4, max(1, y + 6 - body_y - 28), art.SHADOW)
    art.box(painter, x, y, 8, 10, art.INK)
    art.box(painter, x + 2, y, 4, 6, art.SHADOW)
    art.box(painter, x + 1, y + 6, 8, 3, art.SIDE)
    art.box(painter, x + 1, y + 8, 7 if dangling else 9, 2, art.INK)
    art.box(painter, x + 3, y + 5, 3, 2, art.MINT_DARK)
    art.box(painter, x + 1, y + 6, 1, 2, art.RIM)


def side_frame(state: State, right: bool) -> QImage:
    if right:
        state = replace(state, gaze=(-state.gaze[0], state.gaze[1]))
    image = base.canvas()
    painter = QPainter(image)
    angle = 34 + state.lean - state.dy + min(3, -state.hop)
    art.peek_left(painter, angle=angle, eye_height=3)
    painter.save()
    painter.setClipRect(QRect(24, 0, 40, 64))
    painter.translate(14, 45)
    painter.rotate(angle)
    painter.translate(-32, -44)
    art.box(painter, 29, 22, 17, 11, art.FACE)
    # A slightly wider face aperture allows one-pixel gaze changes at either edge.
    eyes(painter, (34, 42), 24, state, side=True)
    art.box(painter, 43, 30, 2, 1, art.PINK)
    art.box(painter, 36, 31, 3, 1, art.RIM)
    painter.restore()
    mode = state.hands[1] if state.hands[1] != "rest" else state.hands[0]
    if mode != "rest":
        endpoint = {"tap": (40, 43), "lift": (44, 35), "up": (50, 25),
                    "stretch": (53, 20), "cheek": (41, 40)}[mode]
        points = [(32, 39), (40, 38), endpoint]
        arm_image = base.canvas()
        arm_painter = QPainter(arm_image)
        stroke(arm_painter, points, art.INK, 5)
        stroke(arm_painter, points, art.SIDE, 3)
        palm(arm_painter, *endpoint)
        arm_painter.end()
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
        painter.drawImage(0, 0, arm_image)
        painter.restore()
    # Repaint the original grip last so free-hand motion cannot overwrite support.
    grip = reference_frames()["left"].copy(24, 41, 7, 10)
    painter.drawImage(24, 41, grip)
    painter.end()
    return image.flipped(Qt.Orientation.Horizontal) if right else image


def draw_frame(pose: str, state: State, *, lifted: bool = False) -> QImage:
    if state == REST and not lifted:
        return reference_frames()["idle" if pose == "free" else pose].copy()
    if pose in ("left", "right"):
        return side_frame(state, pose == "right")
    image = base.canvas()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    dy = state.dy
    hop = state.hop
    if pose in ("top", "bottom"):
        dy = max(-2, min(2, dy + hop))
        hop = 0
    y = (19 if pose == "top" else 13 if pose == "bottom" else 10 if lifted else 12) + dy + hop
    dx = state.dx
    if pose != "bottom":
        fy = y + 32 if pose == "top" else (42 if lifted else 45) + hop
        if pose == "top" and "stretch" in state.hands:
            fy = 53
        for i, x in enumerate((21, 37)):
            foot(painter, x + dx, fy + state.kicks[i], y, dangling=lifted)
    if pose == "free":
        for side, mode in enumerate(state.hands):
            arm(painter, side, mode, y, dx)
    painter.drawImage(QRect(14 + dx, y, 36, 32 - state.squash),
                      head(state), QRect(14, 12, 36, 32))
    if pose == "free":
        for side, mode in enumerate(state.hands):
            if mode == "cheek":
                palm(painter, (20 if side == 0 else 43) + dx, y + 24)
    elif pose == "bottom":
        for i, x in enumerate((17, 39)):
            art.box(painter, x, 40, 10, 11, art.INK)
            art.box(painter, x + 1, 42, 8, 7, art.FRONT)
            art.box(painter, x + 1, 49, 8, 2, art.SIDE)
            art.box(painter, x + 2, 40, 6, 2, art.SIDE)
            art.box(painter, x + 1, 42, 1, 7, art.RIM)
            if state.hands[i] in ("tap", "up", "stretch"):
                art.box(painter, x + 2, 41, 6, 2, art.LIGHT)
    elif pose == "top":
        for x in (18, 41):
            art.box(painter, x, 15, 7, max(13, y + 8 - 15), art.INK)
            art.box(painter, x + 1, 16, 5, max(9, y + 6 - 16), art.FRONT)
            art.box(painter, x + 1, 15, 5, 2, art.SIDE)
            art.box(painter, x + 2, 17, 2, 2, art.PINK)
            art.box(painter, x + 1, 16, 1, max(9, y + 6 - 16), art.RIM)
    painter.end()
    return image


def placement(pose: str) -> dict:
    return {
        "free": {"anchor": [32, 55], "contacts": [[26, 55], [42, 55]], "boundary": None},
        "left": {"anchor": [24, 46], "contacts": [[24, 46]], "boundary": ["x", 24]},
        "right": {"anchor": [40, 46], "contacts": [[40, 46]], "boundary": ["x", 40]},
        "top": {"anchor": [32, 15], "contacts": [[21, 15], [44, 15]], "boundary": ["y", 15]},
        "bottom": {"anchor": [32, 51], "contacts": [[22, 51], [44, 51]], "boundary": ["y", 51]},
        "drag": {"anchor": [32, 24], "contacts": [], "boundary": None},
    }[pose]


def export() -> dict:
    entries = [(pose, clip) for pose in POSES for clip in clips()]
    entries.extend(("drag", clip) for clip in drag_clips())
    columns = 12
    atlas = QImage(columns * 64, len(entries) * 64, QImage.Format.Format_ARGB32_Premultiplied)
    atlas.fill(Qt.GlobalColor.transparent)
    manifest = {
        "review_schema_version": 1, "status": "awaiting-visual-approval",
        "character": "qiaoqiao-keycap", "design_version": 2,
        "image": "atlas.png", "frame_size": [64, 64], "display_size": [128, 128],
        "atlas_size": [atlas.width(), atlas.height()], "columns": columns,
        "rows": len(entries), "sampling": "nearest", "palette": base.PALETTE,
        "poses": {**POSES, "drag": "拖动中"},
        "runtime_integration": False,
        "actions": {},
    }
    painter = QPainter(atlas)
    for row, (pose, clip) in enumerate(entries):
        metadata = {
            "pose": pose, "behavior": clip.name, "label": clip.label,
            "group": clip.group, "loop": clip.loop, "note": clip.note,
            "next": (f"drag.{clip.next_action}" if pose == "drag" and clip.name == "pickup" else
                     "free.rest" if pose == "drag" else f"{pose}.{clip.next_action}"),
            "duration_ms": sum(clip.durations), **placement(pose), "frames": [],
        }
        if pose == "free" and clip.name in ("celebrate", "celebrate_big", "play"):
            metadata["contacts"] = []
        if pose == "drag" and clip.name == "release":
            metadata["anchor"] = [32, 55]
        for col, (state, duration) in enumerate(zip(clip.states, clip.durations, strict=True)):
            if pose == "drag":
                lifted = clip.name != "release"
                image = draw_frame("free", state, lifted=lifted)
                if clip.name == "pickup" and col == 0:
                    image = draw_frame("free", REST)
            else:
                image = draw_frame(pose, state)
            painter.drawImage(col * 64, row * 64, image)
            metadata["frames"].append({
                "rect": [col * 64, row * 64, 64, 64], "duration_ms": duration,
                "bounds": base.opaque_bounds(image),
            })
        manifest["actions"][f"{pose}.{clip.name}"] = metadata
    painter.end()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    base.save_png(atlas, OUTPUT / "atlas.png")
    manifest["sha256"] = hashlib.sha256((OUTPUT / "atlas.png").read_bytes()).hexdigest()
    (OUTPUT / "atlas.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print(f"Review atlas: {len(entries)} clips, "
          f"{sum(len(a['frames']) for a in manifest['actions'].values())} frames")
    return manifest


def main() -> None:
    app = QApplication([])
    export()
    app.quit()


if __name__ == "__main__":
    main()
