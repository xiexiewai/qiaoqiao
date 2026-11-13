"""Animated desktop pet and screen-edge placement."""

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QMenu, QWidget

PET_SIZE = QSize(128, 128)
SNAP_DISTANCE = 28
EDGES = ("left", "right", "top", "bottom")
MOTIONS = (
    "tap", "typing", "celebrate", "celebrate_big", "hover", "hover_hold",
    "hover_left", "hover_up", "hover_down", "hover_leave", "click",
    "look", "stretch", "play", "doze", "sleep", "wake",
)
TYPING_GAP = 0.35
TYPING_TAIL = 0.65
HOVER_DELAY = 0.15
DOZE_AFTER = 90.0
SLEEP_AFTER = 180.0
CELEBRATION_TTL = 5.0


@dataclass
class PetFrame:
    sprite: QPixmap
    mask: QRegion
    duration_ms: int


@dataclass
class PetAction:
    frames: list[PetFrame]
    duration_ms: int
    loop: bool
    next_action: str | None
    offset: QPoint


def load_actions(directory: Path | None = None) -> dict[str, PetAction]:
    """Read bundled assets once; painting and animation never perform file I/O."""
    directory = directory or Path(__file__).resolve().parents[1] / "assets" / "pet" / "qiaoqiao-v2"
    manifest = json.loads((directory / "atlas.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != 2 or manifest["frame_size"] != [64, 64]:
        raise ValueError("不支持的宠物图集格式")
    image = (directory / manifest["image"]).read_bytes()
    if hashlib.sha256(image).hexdigest() != manifest["sha256"]:
        raise ValueError("宠物图集与配置不匹配")
    atlas = QPixmap()
    if not atlas.loadFromData(image, "PNG") or atlas.size() != QSize(*manifest["atlas_size"]):
        raise ValueError("无法加载宠物图集")
    definitions = manifest["actions"]
    required = {"idle", "blink", "drag", "settle", *EDGES,
                "drag.pickup", "drag.struggle", "drag.release"}
    required.update(f"{pose}.{motion}" for pose in ("free", *EDGES) for motion in MOTIONS)
    if set(definitions) != required:
        raise ValueError("宠物动作不完整")
    actions = {}
    for name, action in definitions.items():
        frames = []
        for frame in action["frames"]:
            rect = QRect(*frame["rect"])
            duration = frame["duration_ms"]
            if (rect.size() != QSize(64, 64) or not atlas.rect().contains(rect)
                    or type(duration) is not int or duration <= 0):
                raise ValueError(f"无效的宠物动作帧：{name}")
            sprite = atlas.copy(rect).scaled(
                PET_SIZE, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation,
            )
            frames.append(PetFrame(sprite, QRegion(sprite.mask()), duration))
        duration = sum(frame.duration_ms for frame in frames)
        if not frames or duration != action["duration_ms"]:
            raise ValueError(f"无效的宠物动作时长：{name}")
        if not action["loop"] and action["next"] not in definitions:
            raise ValueError(f"无效的宠物后续动作：{name}")
        # Edge art is already clipped. Align its contact line, not half of the image.
        offset = QPoint()
        pose = name.split(".")[0]
        if pose in EDGES:
            boundary = action["boundary"]
            expected_axis = "x" if pose in ("left", "right") else "y"
            if boundary["axis"] != expected_axis or not 0 < boundary["value"] < 64:
                raise ValueError(f"无效的宠物贴边位置：{name}")
            value = boundary["value"] * 2
            if pose == "left":
                offset.setX(-value)
            elif pose == "right":
                offset.setX(PET_SIZE.width() - value)
            elif pose == "top":
                offset.setY(-value)
            else:
                offset.setY(PET_SIZE.height() - value)
        elif name in ("blink", "settle"):
            offset = (QPoint(*definitions["idle"]["anchor"]) - QPoint(*action["anchor"])) * 2
        actions[name] = PetAction(frames, duration, action["loop"], action["next"], offset)
    return actions


def snap_placement(position: QPoint, area: QRect, size: QSize, previous: str = "") -> tuple[QPoint, str]:
    """Clamp a window to one screen's usable area and pick a nearby edge."""
    x = max(area.left(), min(position.x(), area.right() - size.width() + 1))
    y = max(area.top(), min(position.y(), area.bottom() - size.height() + 1))
    distances = {
        "left": x - area.left(),
        "right": area.right() - (x + size.width() - 1),
        "top": y - area.top(),
        "bottom": area.bottom() - (y + size.height() - 1),
    }
    nearest = min(distances.values())
    edge = ""
    if nearest <= SNAP_DISTANCE:
        tied = [side for side in EDGES if distances[side] == nearest]
        edge = previous if previous in tied else tied[0]
    return QPoint(x, y), edge


class PetWindow(QWidget):
    open_requested = Signal()

    def __init__(self, settings: QSettings, menu: QMenu, topmost: bool = True):
        super().__init__(None)
        self.settings = settings
        self.menu = menu
        self._topmost = topmost
        self._edge = ""
        self._screen_name = ""
        self._press_global: QPoint | None = None
        self._press_position: QPoint | None = None
        self._previous_edge = ""
        self._dragging = False
        self.setObjectName("desktopPet")
        self.setWindowTitle("敲敲桌面宠物")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(self._flags())
        self.setFixedSize(PET_SIZE)
        self.setMouseTracking(True)
        self._actions = load_actions()
        self._hover_regions: dict[str, QRegion] = {}
        for pose in ("free", *EDGES):
            region = QRegion()
            for name in (("idle" if pose == "free" else pose),
                         *(f"{pose}.{motion}" for motion in MOTIONS if motion.startswith("hover"))):
                action = self._actions[name]
                for frame in action.frames:
                    region |= frame.mask.translated(action.offset)
            self._hover_regions[pose] = region.intersected(QRegion(self.rect()))
        self._action = "idle"
        self._frame_index = 0
        self._clock = QElapsedTimer()
        self._animation_timer = QTimer(self)
        self._animation_timer.setSingleShot(True)
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation_timer.timeout.connect(self._animate)
        self._reset_interactions()
        self.menu.aboutToShow.connect(self._menu_opened)
        self.menu.aboutToHide.connect(self._menu_closed)
        self._restore_placement()
        self._watch_screens()

    @property
    def _behavior(self) -> str:
        return self._action.rsplit(".", 1)[-1]

    def _reset_interactions(self) -> None:
        now = monotonic()
        self._last_activity = now
        self._next_idle = now + random.uniform(20, 40)
        self._last_idle_motion = ""
        self._dozed = False
        self._last_key = -math.inf
        self._typing_until = 0.0
        self._typing_requested = False
        self._key_pending = False
        self._pending_celebration: tuple[int, float] | None = None
        self._wake_next: str | None = None
        self._click_due = 0.0
        self._click_not_before = 0.0
        self._hover_due = 0.0
        self._leave_due = 0.0
        self._hovered = False
        self._gaze_not_before = 0.0
        self._menu_open = False

    def _touch(self, now: float) -> None:
        self._last_activity = now
        self._dozed = False

    def _wake_scheduler(self) -> None:
        if self.isVisible() and not self._menu_open:
            if not self._animation_timer.isActive() or self._animation_timer.remainingTime() > 16:
                self._animation_timer.start(16)

    def on_key_press(self) -> None:
        """Coalesce accepted presses in memory; the native callback never draws."""
        if not self.isVisible() or self._menu_open:
            return
        now = monotonic()
        self._touch(now)
        self._typing_requested = now - self._last_key <= TYPING_GAP
        self._last_key = now
        self._typing_until = now + TYPING_TAIL
        self._key_pending = True
        self._wake_scheduler()

    def celebrate(self, threshold: int) -> None:
        if not self.isVisible() or self._menu_open:
            return
        now = monotonic()
        self._touch(now)
        pending = self._pending_celebration
        self._pending_celebration = (max(threshold, pending[0]) if pending else threshold,
                                     now + CELEBRATION_TTL)
        self._wake_scheduler()

    def clear_celebration(self) -> None:
        self._pending_celebration = None
        if self._wake_next in ("celebrate", "celebrate_big"):
            self._wake_next = None
        if self._behavior in ("celebrate", "celebrate_big"):
            self._start_action(self._edge or "idle")

    def _start_motion(self, motion: str) -> None:
        if self._behavior in ("doze", "sleep"):
            self._wake_next = motion
            self._start_action(f"{self._edge or 'free'}.wake")
        else:
            self._start_action(f"{self._edge or 'free'}.{motion}")

    def _start_action(self, name: str) -> None:
        self._animation_timer.stop()
        self._action = name
        self._frame_index = 0
        self._clock.start()
        self._update_mask()
        self.update()
        self._schedule_frame(self._actions[name].frames[0].duration_ms)

    def _animate(self) -> None:
        if not self.isVisible() or self._menu_open:
            self._animation_timer.stop()
            return
        if self._service_behavior(monotonic()):
            return
        self._advance_animation(self._clock.elapsed())

    def _schedule_frame(self, remaining_ms: int) -> None:
        if not self.isVisible() or self._menu_open:
            return
        now = monotonic()
        deadlines = [] if self._press_global is not None else [
            self._click_due, self._hover_due, self._leave_due,
        ]
        if self._press_global is None and self._behavior == "typing":
            deadlines.append(self._typing_until)
        if self._press_global is None and self._action in ("idle", "blink", *EDGES):
            deadlines.extend((max(self._next_idle, self._last_activity + 20),
                              self._last_activity + (SLEEP_AFTER if self._dozed else DOZE_AFTER)))
        for deadline in deadlines:
            if deadline:
                remaining_ms = min(remaining_ms, max(16, math.ceil((deadline - now) * 1000)))
        if self._hovered or self._hover_due:
            remaining_ms = min(remaining_ms, 100)
        self._animation_timer.start(max(1, remaining_ms))

    def _pointer_inside(self) -> bool:
        # Intent uses the resting/hover silhouettes to tolerate moving pixels;
        # the actual native hit region remains the current frame's alpha mask.
        point = self.mapFromGlobal(QCursor.pos())
        return self._hover_regions[self._edge or "free"].contains(point)

    def _gaze_motion(self) -> str:
        center = self._hover_regions[self._edge or "free"].boundingRect().center()
        delta = self.mapFromGlobal(QCursor.pos()) - center
        if delta.manhattanLength() < 6 and self._behavior in (
                "hover_hold", "hover_left", "hover_up", "hover_down"):
            return self._behavior
        if abs(delta.y()) > abs(delta.x()):
            return "hover_up" if delta.y() < 0 else "hover_down"
        return "hover_left" if delta.x() < 0 else "hover_hold"

    def _service_behavior(self, now: float) -> bool:
        pending = self._pending_celebration
        if pending and now >= pending[1]:
            self._pending_celebration = None
        if self._dragging or self._press_global is not None:
            return False
        if self._hovered and not self._pointer_inside() and not self._leave_due:
            self._leave_due = now + HOVER_DELAY
        if self._leave_due and now >= self._leave_due:
            self._leave_due = 0.0
            if not self._pointer_inside():
                self._hovered = False
                self._hover_due = 0.0
        if self._hover_due and now >= self._hover_due:
            self._hover_due = 0.0
            self._hovered = self._pointer_inside()
            if self._hovered:
                self._touch(now)
        behavior = self._behavior
        if behavior in ("celebrate", "celebrate_big"):
            self._click_due = 0.0
            return False
        if self._pending_celebration:
            threshold, _ = self._pending_celebration
            self._pending_celebration = None
            motion = "celebrate_big" if threshold % 10000 == 0 else "celebrate"
            self._click_due = 0.0
            if behavior == "wake":
                self._wake_next = motion
                return False
            self._start_motion(motion)
            return True
        if behavior == "wake":
            return False
        if self._click_due and now >= self._click_due:
            self._click_due = 0.0
            if now >= self._click_not_before:
                self._click_not_before = now + 0.8
                self._start_motion("click")
                return True
        if behavior in ("click", "release"):
            return False
        if self._hovered:
            self._touch(now)
            if behavior in ("hover_hold", "hover_left", "hover_up", "hover_down"):
                motion = self._gaze_motion()
                if motion != behavior and now >= self._gaze_not_before:
                    self._gaze_not_before = now + HOVER_DELAY
                    self._start_motion(motion)
                    return True
            elif behavior != "hover":
                self._start_motion("hover")
                return True
            return False
        if behavior.startswith("hover") and behavior != "hover_leave":
            self._start_motion("hover_leave")
            return True
        if now >= self._typing_until:
            self._key_pending = self._typing_requested = False
            if behavior == "typing":
                self._start_action(self._edge or "idle")
                return True
        if self._key_pending:
            if behavior == "tap":
                return False
            self._key_pending = False
            motion = "typing" if self._typing_requested else "tap"
            if behavior != motion:
                self._start_motion(motion)
                return True
        if self._action not in ("idle", "blink", *EDGES):
            return False
        quiet = now - self._last_activity
        if quiet >= SLEEP_AFTER:
            self._start_motion("sleep")
            return True
        if quiet >= DOZE_AFTER and not self._dozed:
            self._dozed = True
            self._start_motion("doze")
            return True
        if quiet >= 20 and now >= self._next_idle:
            choices = [name for name in ("look", "stretch", "play") if name != self._last_idle_motion]
            self._last_idle_motion = random.choice(choices)
            self._next_idle = now + random.uniform(20, 40)
            self._start_motion(self._last_idle_motion)
            return True
        return False

    def _advance_animation(self, elapsed: int) -> None:
        if not self.isVisible() or self._menu_open:
            self._animation_timer.stop()
            return
        action = self._actions[self._action]
        if self._action == "idle" and elapsed >= action.duration_ms * 2:
            self._start_action("blink")
            return
        if not action.loop and elapsed >= action.duration_ms:
            if self._behavior == "wake" and self._wake_next:
                motion, self._wake_next = self._wake_next, None
                self._start_action(f"{self._edge or 'free'}.{motion}")
            elif self._behavior == "tap" and self._typing_requested and monotonic() < self._typing_until:
                self._key_pending = False
                self._start_motion("typing")
            elif self._behavior == "click" and self._hovered:
                self._start_motion(self._gaze_motion())
            else:
                self._start_action(action.next_action)
            return
        # Delayed GUI events skip expired frames instead of replaying a backlog.
        elapsed %= action.duration_ms
        for index, frame in enumerate(action.frames):
            if elapsed < frame.duration_ms:
                if index != self._frame_index:
                    self._frame_index = index
                    self._update_mask()
                    self.update()
                self._schedule_frame(frame.duration_ms - elapsed)
                return
            elapsed -= frame.duration_ms

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._reset_interactions()
        self._start_action(self._edge or "idle")

    def hideEvent(self, event) -> None:
        self._animation_timer.stop()
        if self._dragging:
            self._finish_drag(self.geometry().center())
        self._clear_press()
        self._reset_interactions()
        self.menu.hide()
        super().hideEvent(event)

    def _menu_opened(self) -> None:
        if self._dragging:
            self._finish_drag(self.geometry().center())
        self._clear_press()
        self._reset_interactions()
        self._menu_open = True
        self._animation_timer.stop()

    def _menu_closed(self) -> None:
        self._reset_interactions()
        if self.isVisible():
            self._start_action(self._edge or "idle")

    def _flags(self) -> Qt.WindowType:
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        if self._topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def set_topmost(self, enabled: bool) -> None:
        if self._topmost == enabled:
            return
        self._topmost = enabled
        visible = self.isVisible()
        self.setWindowFlags(self._flags())
        if visible:
            self.show()
        self._update_mask()

    def _screen_for_name(self, name: str):
        return next((screen for screen in QGuiApplication.screens() if screen.name() == name),
                    QGuiApplication.primaryScreen())

    def _restore_placement(self) -> None:
        name = str(self.settings.value("pet/screen", ""))
        screen = self._screen_for_name(name)
        if screen is None:
            return
        area = screen.availableGeometry()
        try:
            ratio_x = float(self.settings.value("pet/x", 0.8))
            ratio_y = float(self.settings.value("pet/y", 0.8))
        except (TypeError, ValueError):
            ratio_x = ratio_y = 0.8
        ratio_x = max(0.0, min(1.0, ratio_x)) if math.isfinite(ratio_x) else 0.8
        ratio_y = max(0.0, min(1.0, ratio_y)) if math.isfinite(ratio_y) else 0.8
        position = QPoint(
            area.left() + round(max(0, area.width() - self.width()) * ratio_x),
            area.top() + round(max(0, area.height() - self.height()) * ratio_y),
        )
        edge = str(self.settings.value("pet/edge", ""))
        self._screen_name = screen.name()
        self._place(position, area, edge if edge in EDGES else "")

    def _place(self, position: QPoint, area: QRect, edge: str) -> None:
        position, _ = snap_placement(position, area, self.size())
        if edge == "left":
            position.setX(area.left())
        elif edge == "right":
            position.setX(area.right() - self.width() + 1)
        elif edge == "top":
            position.setY(area.top())
        elif edge == "bottom":
            position.setY(area.bottom() - self.height() + 1)
        self._edge = edge
        self.move(position)
        self._start_action(edge or "idle")

    def _save_placement(self) -> None:
        screen = self._screen_for_name(self._screen_name)
        if screen is None:
            return
        area = screen.availableGeometry()
        self.settings.setValue("pet/screen", self._screen_name)
        self.settings.setValue("pet/edge", self._edge)
        self.settings.setValue("pet/x", (self.x() - area.left()) / max(1, area.width() - self.width()))
        self.settings.setValue("pet/y", (self.y() - area.top()) / max(1, area.height() - self.height()))
        self.settings.sync()

    def _watch_screens(self) -> None:
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._screen_added)
        app.screenRemoved.connect(self._screen_removed)
        for screen in app.screens():
            self._screen_added(screen)

    def _screen_added(self, screen) -> None:
        screen.availableGeometryChanged.connect(self._screen_changed)
        screen.geometryChanged.connect(self._screen_changed)

    def _screen_removed(self, screen) -> None:
        self._screen_changed()

    def _screen_changed(self, *args) -> None:
        if self._dragging:
            return
        self._restore_placement()

    def _sprite_offset(self) -> QPoint:
        return self._actions[self._action].offset

    def _update_mask(self) -> None:
        frame = self._actions[self._action].frames[self._frame_index]
        region = frame.mask.translated(self._sprite_offset()).intersected(QRegion(self.rect()))
        if region != self.mask():
            self.setMask(region)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        frame = self._actions[self._action].frames[self._frame_index]
        painter.drawPixmap(self._sprite_offset(), frame.sprite)

    def enterEvent(self, event) -> None:
        if not self._dragging and not self._menu_open:
            self._leave_due = 0.0
            if not self._hovered:
                self._hover_due = monotonic() + HOVER_DELAY
            self._wake_scheduler()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._dragging:
            self._hover_due = 0.0
            if self._hovered:
                self._leave_due = monotonic() + HOVER_DELAY
                self._wake_scheduler()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._touch(monotonic())
            self._press_global = event.globalPosition().toPoint()
            self._press_position = self.pos()
            self._previous_edge = self._edge
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_global is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_global
            if not self._dragging and delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                self._edge = ""
                self._hovered = False
                self._hover_due = self._leave_due = self._click_due = 0.0
                self._wake_next = None
                self._start_action("drag.pickup")
            if self._dragging:
                self.move(self._press_position + delta)
            event.accept()
            return
        if self._hovered:
            self._wake_scheduler()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_global is not None:
            if self._dragging:
                self._finish_drag(event.globalPosition().toPoint())
            elif self.mask().contains(event.position().toPoint()):
                self._click_due = monotonic() + QApplication.doubleClickInterval() / 1000
                self._wake_scheduler()
            self._clear_press()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _finish_drag(self, pointer: QPoint) -> None:
        self._touch(monotonic())
        screen = QGuiApplication.screenAt(pointer)
        screen = screen or QGuiApplication.screenAt(self.geometry().center())
        screen = screen or QGuiApplication.primaryScreen()
        if screen is not None:
            position, edge = snap_placement(
                self.pos(), screen.availableGeometry(), self.size(), self._previous_edge,
            )
            self._screen_name = screen.name()
            self._place(position, screen.availableGeometry(), edge)
            if not edge:
                self._start_action("drag.release")
            self._save_placement()

    def _clear_press(self) -> None:
        self._press_global = self._press_position = None
        self._previous_edge = ""
        self._dragging = False

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_due = 0.0
            self._clear_press()
            self.open_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.menu.popup(event.globalPos())
        event.accept()
