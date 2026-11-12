"""Render deterministic concept previews for the desktop pet, not runtime sprites."""

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "pet-preview-v2"
INK = "#0D0C14"
FRONT = "#443A53"
LIGHT = "#655971"
SIDE = "#54465F"
SHADOW = "#2C283B"
RIM = "#8D7C9E"
FACE = "#191621"
MINT = "#97E4C2"
MINT_DARK = "#568F80"
PINK = "#C7849C"
EYE_LIGHT = "#CEF2DF"
TEXT = "#F2EBF4"
MUTED = "#A49AB4"
SHEET = "#D6D9E0"
GUIDE = "#596071"
DESKTOP = "#171522"


def box(painter: QPainter, x: int, y: int, w: int, h: int, color: str) -> None:
    painter.fillRect(x, y, w, h, QColor(color))


def shape(painter: QPainter, points: list[tuple[int, int]], color: str) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))


def limb(painter: QPainter, y: int, left: bool = True) -> None:
    if left:
        shape(painter, [(15, y), (11, y), (11, y + 2), (8, y + 2),
                        (8, y + 8), (10, y + 8), (10, y + 10),
                        (15, y + 10), (17, y + 7), (17, y + 2)], INK)
        box(painter, 10, y + 4, 5, 4, SIDE)
        box(painter, 10, y + 7, 4, 2, FRONT)
        box(painter, 13, y + 3, 3, 2, FRONT)
        box(painter, 10, y + 4, 1, 3, RIM)
    else:
        painter.save()
        painter.translate(63, 0)
        painter.scale(-1, 1)
        limb(painter, y, True)
        painter.restore()


def feet(painter: QPainter, y: int, dangling: bool = False) -> None:
    for x in (21, 37):
        box(painter, x, y, 8, 10, INK)
        box(painter, x + 2, y, 4, 6, SHADOW)
        box(painter, x + 1, y + 6, 8, 3, SIDE)
        box(painter, x + 1, y + 8, 9 if not dangling else 7, 2, INK)
        box(painter, x + 3, y + 5, 3, 2, MINT_DARK)
        box(painter, x + 1, y + 6, 1, 2, RIM)


def body(painter: QPainter, y: int, blink: bool = False, wide: bool = False,
         arms: bool = True, legs: bool = True, dangling: bool = False,
         feet_y: int | None = None) -> None:
    if legs:
        feet(painter, feet_y if feet_y is not None else y + (32 if dangling else 33),
             dangling)
    if arms:
        limb(painter, y + 20)
        limb(painter, y + 20, False)

    shape(painter, [(18, y), (45, y), (45, y + 2), (48, y + 2),
                    (48, y + 5), (50, y + 5), (50, y + 28),
                    (48, y + 28), (48, y + 32), (16, y + 32),
                    (16, y + 29), (14, y + 29), (14, y + 6),
                    (16, y + 6), (16, y + 3), (18, y + 3)], INK)
    box(painter, 17, y + 12, 31, 17, SHADOW)
    box(painter, 18, y + 13, 26, 16, FRONT)
    box(painter, 44, y + 13, 3, 16, SIDE)
    box(painter, 19, y + 29, 25, 1, SIDE)
    box(painter, 44, y + 29, 3, 1, SHADOW)
    shape(painter, [(19, y + 2), (44, y + 2), (44, y + 4),
                    (47, y + 4), (47, y + 11), (16, y + 11),
                    (16, y + 7), (19, y + 7)], SIDE)
    shape(painter, [(19, y + 2), (43, y + 2), (43, y + 4),
                    (46, y + 4), (46, y + 8), (18, y + 8),
                    (18, y + 5), (19, y + 5)], LIGHT)
    box(painter, 19, y + 2, 24, 1, RIM)
    box(painter, 17, y + 13, 1, 15, RIM)
    box(painter, 47, y + 13, 1, 15, LIGHT)
    box(painter, 19, y + 29, 25, 1, LIGHT)
    box(painter, 20, y + 10, 26, 2, INK)
    box(painter, 21, y + 15, 22, 13, INK)
    box(painter, 22, y + 16, 20, 11, FACE)
    box(painter, 23, y + 17, 18, 1, SIDE)
    if blink:
        box(painter, 25, y + 22, 5, 1, MINT)
        box(painter, 35, y + 22, 5, 1, MINT)
    else:
        height = 4 if wide else 3
        box(painter, 26, y + 20, 3, height, MINT)
        box(painter, 36, y + 20, 3, height, MINT)
        box(painter, 26, y + 20, 1, 1, EYE_LIGHT)
        box(painter, 36, y + 20, 1, 1, EYE_LIGHT)
    box(painter, 23, y + 25, 2, 1, PINK)
    box(painter, 40, y + 25, 2, 1, PINK)
    box(painter, 31, y + 25, 3, 1, RIM)


def peek_left(painter: QPainter, angle: float = 34, eye_height: int = 4) -> None:
    # Draw a separate three-quarter face and lean around the hidden lower body.
    leaning = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    leaning.fill(Qt.GlobalColor.transparent)
    pose = QPainter(leaning)
    pose.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    pose.translate(14, 45)
    pose.rotate(angle)
    pose.translate(-32, -44)
    shape(pose, [(18, 12), (45, 12), (45, 14), (48, 14), (48, 17),
                 (50, 17), (50, 40), (48, 40), (48, 44), (16, 44),
                 (16, 41), (14, 41), (14, 18), (16, 18), (16, 15),
                 (18, 15)], INK)
    box(pose, 17, 18, 30, 23, FRONT)
    box(pose, 17, 18, 7, 23, SIDE)
    box(pose, 46, 18, 2, 22, SHADOW)
    box(pose, 18, 41, 29, 2, SHADOW)
    shape(pose, [(19, 14), (44, 14), (44, 16), (47, 16),
                 (47, 18), (17, 18), (17, 17), (19, 17)], LIGHT)
    box(pose, 19, 14, 25, 1, RIM)
    box(pose, 47, 18, 1, 21, LIGHT)
    box(pose, 20, 41, 24, 1, LIGHT)
    box(pose, 28, 20, 18, 14, INK)
    box(pose, 29, 21, 16, 12, FACE)
    box(pose, 30, 21, 14, 1, SIDE)
    for x in (34, 42):
        if eye_height == 1:
            box(pose, x, 26, 4, 1, MINT)
        else:
            box(pose, x, 28 - eye_height, 3, eye_height, MINT)
            box(pose, x + 1, 28 - eye_height, 1, 1, EYE_LIGHT)
    box(pose, 43, 30, 2, 1, PINK)
    box(pose, 36, 31, 3, 1, RIM)
    pose.end()
    painter.save()
    painter.setClipRect(QRect(24, 0, 40, 64))
    painter.drawImage(0, 0, leaning)
    shape(painter, [(34, 39), (37, 41), (34, 47), (30, 49),
                    (26, 47), (28, 42)], INK)
    shape(painter, [(34, 41), (35, 42), (32, 46), (28, 46),
                    (29, 43)], SIDE)
    box(painter, 24, 41, 7, 10, INK)
    box(painter, 24, 42, 5, 7, FRONT)
    box(painter, 24, 42, 1, 7, RIM)
    box(painter, 25, 42, 4, 2, LIGHT)
    box(painter, 25, 46, 3, 1, MINT_DARK)
    box(painter, 25, 49, 4, 1, SIDE)
    painter.restore()


def sprite(name: str) -> QImage:
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    if name == "idle":
        body(painter, 12)
    elif name == "breath":
        body(painter, 11, feet_y=45)
    elif name == "blink":
        body(painter, 12, blink=True)
    elif name == "drag":
        body(painter, 10, wide=True, dangling=True)
    elif name == "left":
        peek_left(painter)
    elif name == "right":
        left = sprite("left")
        painter.drawImage(0, 0, left.flipped(Qt.Orientation.Horizontal))
    elif name == "bottom":
        body(painter, 13, arms=False, legs=False)
        for x in (17, 39):
            box(painter, x, 40, 10, 11, INK)
            box(painter, x + 1, 42, 8, 7, FRONT)
            box(painter, x + 1, 49, 8, 2, SIDE)
            box(painter, x + 2, 40, 6, 2, SIDE)
            box(painter, x + 1, 42, 1, 7, RIM)
    elif name == "top":
        body(painter, 19, arms=False)
        for x in (18, 41):
            box(painter, x, 15, 7, 13, INK)
            box(painter, x + 1, 16, 5, 9, FRONT)
            box(painter, x + 1, 15, 5, 2, SIDE)
            box(painter, x + 2, 17, 2, 2, PINK)
            box(painter, x + 1, 16, 1, 9, RIM)
    painter.end()
    return image


def text(painter: QPainter, rect: QRect, value: str, size: int, color: str,
         weight: QFont.Weight = QFont.Weight.Normal,
         align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft) -> None:
    font = QFont("Microsoft YaHei UI", size)
    font.setWeight(weight)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, value)


def scaled(painter: QPainter, image: QImage, x: int, y: int, scale: int) -> None:
    painter.drawImage(QRect(x, y, 64 * scale, 64 * scale), image)


def guide(painter: QPainter, name: str, x: int, y: int, scale: int) -> None:
    painter.setPen(QPen(QColor(GUIDE), 2))
    if name == "left":
        gx = x + 24 * scale
        painter.drawLine(gx, y + 6 * scale, gx, y + 57 * scale)
    elif name == "right":
        gx = x + 40 * scale
        painter.drawLine(gx, y + 6 * scale, gx, y + 57 * scale)
    elif name == "top":
        gy = y + 15 * scale
        painter.drawLine(x + 8 * scale, gy, x + 56 * scale, gy)
    elif name == "bottom":
        gy = y + 51 * scale
        painter.drawLine(x + 8 * scale, gy, x + 56 * scale, gy)


def save_sheet() -> None:
    image = QImage(1328, 746, QImage.Format.Format_RGB32)
    image.fill(QColor(SHEET))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    text(painter, QRect(56, 24, 900, 54), "敲敲  /  深色角色与探身姿态", 22, FACE, QFont.Weight.DemiBold)
    text(painter, QRect(56, 78, 1000, 26), "第二轮 · 深灰紫机身 / 薄荷绿眼睛 / 柔粉点缀 · 4 倍展示", 10, GUIDE)
    entries = [
        ("idle", "01  桌面待机"), ("breath", "02  轻呼吸"),
        ("blink", "03  眨眼"), ("drag", "04  拖动提起"),
        ("left", "05  左边倾身探头"), ("right", "06  右边倾身探头"),
        ("bottom", "07  底边趴伏"), ("top", "08  顶边悬挂"),
    ]
    for index, (name, label) in enumerate(entries):
        col, row = index % 4, index // 4
        x = 40 + col * 320
        y = 108 + row * 298
        guide(painter, name, x, y, 4)
        scaled(painter, sprite(name), x, y, 4)
        text(painter, QRect(x + 12, y + 248, 260, 38), label, 11, FACE,
             QFont.Weight.DemiBold)
    painter.setPen(QPen(QColor("#A9AFBB"), 1))
    painter.drawLine(56, 706, 1272, 706)
    text(painter, QRect(56, 710, 1200, 28),
         "细线仅表示屏幕边界；姿态草案，不是运行用动画素材。", 9, GUIDE)
    painter.end()
    image.save(str(OUTPUT / "pose-sheet.png"))


def save_desktop() -> None:
    image = QImage(1280, 720, QImage.Format.Format_RGB32)
    image.fill(QColor(DESKTOP))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    # A restrained desktop context, deliberately not a capture of user data.
    shape(painter, [(0, 0), (480, 0), (350, 674), (0, 674)], "#1D1928")
    shape(painter, [(930, 0), (1280, 0), (1280, 674), (1080, 674)], "#201B2B")
    painter.setPen(QPen(QColor("#322B40"), 2))
    painter.drawLine(350, 674, 480, 0)
    painter.drawLine(930, 0, 1080, 674)
    text(painter, QRect(64, 70, 600, 55), "桌面上的敲敲 / 深色版", 25, TEXT, QFont.Weight.DemiBold)
    text(painter, QRect(66, 130, 900, 32), "128 × 128 像素画布 · 多位置合成示意，实际只显示一只宠物", 11, MUTED)
    for x, label in ((73, "文件"), (159, "项目")):
        box(painter, x + 12, 235, 35, 33, "#54465F")
        box(painter, x + 12, 230, 15, 7, "#A49AB4")
        box(painter, x + 15, 238, 29, 27, "#E59AAC")
        text(painter, QRect(x, 275, 70, 26), label, 10, TEXT,
             align=Qt.AlignmentFlag.AlignHCenter)
    scaled(painter, sprite("idle"), 842, 406, 2)
    scaled(painter, sprite("left"), -48, 334, 2)
    scaled(painter, sprite("right"), 1200, 334, 2)
    scaled(painter, sprite("bottom"), 549, 572, 2)
    scaled(painter, sprite("top"), 1090, -30, 2)
    box(painter, 0, 674, 1280, 46, "#24202F")
    box(painter, 0, 674, 1280, 2, SHADOW)
    for x, y in ((24, 689), (35, 689), (24, 700), (35, 700)):
        box(painter, x, y, 8, 8, MINT)
    box(painter, 80, 693, 85, 3, "#54465F")
    box(painter, 80, 703, 55, 3, "#54465F")
    for x, color in ((201, PINK), (249, MINT_DARK), (297, SIDE)):
        box(painter, x, 688, 25, 25, INK)
        box(painter, x + 3, 691, 19, 19, color)
    text(painter, QRect(1158, 686, 100, 29), "10:24", 10, TEXT,
         align=Qt.AlignmentFlag.AlignRight)
    painter.end()
    image.save(str(OUTPUT / "desktop-scale.png"))


def save_edges() -> None:
    image = QImage(1120, 692, QImage.Format.Format_RGB32)
    image.fill(QColor("#20202A"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    text(painter, QRect(40, 20, 1000, 48), "左右探身 / 上半身先露出", 20, TEXT, QFont.Weight.DemiBold)
    text(painter, QRect(40, 69, 1000, 30),
         "身体向桌面内倾斜约 34°，下半身与脚藏在屏幕外；手扶住边缘。", 10, MUTED)
    for name, label, left, boundary in (
        ("left", "左边探头", 40, 168),
        ("right", "右边探头", 580, 952),
    ):
        box(painter, left, 120, 500, 294, DESKTOP)
        outside_x = left if name == "left" else boundary
        box(painter, outside_x, 120, 128, 294, "#30303A")
        painter.setPen(QPen(QColor(MUTED), 1))
        painter.drawLine(boundary, 120, boundary, 414)
        sx = boundary - (24 if name == "left" else 40) * 5
        scaled(painter, sprite(name), sx, 115, 5)
        text(painter, QRect(left, 420, 500, 32), label, 11, TEXT,
             QFont.Weight.DemiBold, Qt.AlignmentFlag.AlignHCenter)
    text(painter, QRect(40, 470, 450, 25), "缩至实际尺寸 / 深浅背景", 10, MUTED)
    for x, background in ((40, DESKTOP), (300, SHEET)):
        box(painter, x, 507, 240, 128, background)
        scaled(painter, sprite("idle"), x, 507, 2)
        boundary = x + 139
        painter.setPen(QPen(QColor(GUIDE), 1))
        painter.drawLine(boundary, 507, boundary, 635)
        scaled(painter, sprite("left"), boundary - 48, 507, 2)
    for index, (color, label) in enumerate((
        (FRONT, "主体"), (LIGHT, "顶面"), (RIM, "棱边"),
        (FACE, "面板"), (MINT, "眼睛"), (PINK, "点缀"),
    )):
        x = 594 + index * 79
        box(painter, x, 525, 48, 28, color)
        text(painter, QRect(x - 2, 558, 70, 25), label, 9, TEXT)
    text(painter, QRect(40, 650, 1040, 25),
         "明线为示意边界；放大图使用最近邻缩放，无模糊与光晕。", 9, MUTED)
    painter.end()
    image.save(str(OUTPUT / "edge-details.png"))


def main() -> None:
    app = QApplication([])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    save_sheet()
    save_desktop()
    save_edges()
    app.quit()


if __name__ == "__main__":
    main()
