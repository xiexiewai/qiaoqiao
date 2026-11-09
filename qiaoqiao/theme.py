"""Shared pixel theme for native Qt controls and the keyboard painter."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap, QPolygonF, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget, QDateEdit, QLabel, QPushButton, QStyle, QToolButton, QWidget,
)

BACKGROUND = "#171522"
BOARD = "#1D1928"
GRID = "#2A2435"
TEXT = "#F2EBF4"
MUTED = "#A49AB4"
MINT = "#97E4C2"
PINK = "#E59AAC"
BORDER = "#54465F"
SHADOW = "#0D0C14"
KEY_IDLE = "#2C283B"
KEY_DISABLED = "#252230"
KEY_MUTED = "#B2A6C2"
KEY_DARK_TEXT = "#271E30"
ERROR = "#FF9E91"
HEAT_STOPS = ((0, "#4C355E"), (.4, "#8A517C"), (.7, "#C47D98"), (1, "#FFE6B5"))

STYLE = f"""
QWidget {{ font-family: "Microsoft YaHei UI"; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#body {{ background: {BACKGROUND}; }}
QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 21pt; font-weight: 700; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#range {{ font-size: 14pt; font-weight: 600; }}
QLabel#total {{ color: {MINT}; }}
QLabel#status {{ color: {MINT}; }}
QLabel[state="error"], QLabel#muted[state="error"], QLabel#status[state="error"] {{ color: {ERROR}; }}
QLabel#status[state="paused"] {{ color: {PINK}; }}
QLabel#muted[state="muted"] {{ color: {MUTED}; }}
QFrame#divider {{ background: #3D324B; border: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: #24202F; color: {MUTED}; border-bottom: 2px solid {BORDER};
    padding: 8px 24px; margin-right: 8px;
}}
QTabBar::tab:selected {{ color: {PINK}; background: #342A40; border-bottom-color: {PINK}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:focus {{ border-bottom-color: {MINT}; }}
QWidget#trendPage, QWidget#trendViewport {{ background: {BACKGROUND}; }}
QFrame#trendCard {{ background: {BOARD}; border: 1px solid {BORDER}; }}
QLabel#trendValue {{ font-family: "Consolas"; font-size: 20pt; font-weight: 600; color: {MINT}; }}
QLabel#trendValue[state="empty"] {{ font-family: "Microsoft YaHei UI"; }}
QLabel#trendDetail {{ font-size: 9pt; color: {MUTED}; }}
QPushButton, QToolButton {{
    background: #24202F; border: 1px solid {BORDER}; border-radius: 0;
    padding: 6px 10px; min-height: 22px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {PINK}; }}
QPushButton:checked {{ color: {PINK}; background: #342A40; }}
QPushButton:disabled, QToolButton:disabled {{ color: #796F86; }}
QPushButton:focus, QToolButton:focus {{ border-color: {MINT}; }}
QDateEdit {{
    background: transparent; border: none; padding: 6px 10px;
    min-width: 158px; min-height: 22px; selection-background-color: #70475F;
}}
QDateEdit:disabled {{ color: #796F86; }}
QDateEdit::drop-down {{ width: 24px; border: none; background: transparent; }}
QDateEdit::down-arrow {{ image: none; width: 0; height: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QWidget#keyboardViewport, QWidget#totalViewport {{ background: {BACKGROUND}; }}
QScrollBar:horizontal {{ background: #24202F; height: 10px; margin: 0; }}
QScrollBar:vertical {{ background: #24202F; width: 10px; margin: 0; }}
QScrollBar::handle {{ background: #685472; min-width: 22px; min-height: 22px; }}
QScrollBar::handle:hover {{ background: #A36B94; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QToolTip {{ color: {TEXT}; background: #292335; border: 1px solid #A36B94; padding: 6px; }}
QMenu {{ color: {TEXT}; background: #24202F; border: 1px solid #A36B94; padding: 5px; }}
QMenu::item {{ padding: 8px 28px; }}
QMenu::item:selected {{ background: #4C355E; }}
QMenu::item:disabled {{ color: #796F86; }}
QMenu::indicator:checked {{ background: {MINT}; border: 3px solid #24202F; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QCalendarWidget QWidget {{ background: #24202F; }}
QCalendarWidget QAbstractItemView {{
    background: #24202F; alternate-background-color: #30283E;
    selection-background-color: #70475F; selection-color: {TEXT};
}}
QCalendarWidget QToolButton {{ color: {TEXT}; }}
QCalendarWidget QSpinBox {{ background: #30283E; color: {TEXT}; }}
QMessageBox {{ background: {BACKGROUND}; }}
"""


def palette() -> QPalette:
    result = QPalette()
    for role, ink in (
        (QPalette.ColorRole.Window, BACKGROUND), (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, BOARD), (QPalette.ColorRole.AlternateBase, KEY_IDLE),
        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, KEY_IDLE),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, "#70475F"),
        (QPalette.ColorRole.HighlightedText, TEXT), (QPalette.ColorRole.ToolTipBase, KEY_IDLE),
        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, MUTED),
    ):
        result.setColor(role, QColor(ink))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor("#796F86"))
    return result


def set_state(widget: QWidget, state: str) -> None:
    # Dynamic QSS properties need repolishing, but only when the state changes.
    if widget.property("state") != state:
        widget.setProperty("state", state)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def blend(first: str | QColor, second: str | QColor, amount: float) -> QColor:
    a, b = QColor(first), QColor(second)
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    )


def heat_color(ratio: float) -> QColor:
    ratio = max(0, min(1, ratio))
    for (low, left), (high, right) in zip(HEAT_STOPS, HEAT_STOPS[1:]):
        if ratio <= high:
            return blend(left, right, (ratio - low) / (high - low))
    return QColor(HEAT_STOPS[-1][1])


def key_ink(fill: QColor) -> QColor:
    # Choose the higher-contrast text across the continuous heat scale.
    def linear(channel):
        return channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4

    def luminance(color):
        return sum(weight * linear(channel) for weight, channel in
                   zip((.2126, .7152, .0722), (color.redF(), color.greenF(), color.blueF())))

    value = luminance(fill)
    light, dark = QColor(TEXT), QColor(KEY_DARK_TEXT)
    return light if (luminance(light) + .05) / (value + .05) >= (
        (value + .05) / (luminance(dark) + .05)
    ) else dark


def pixel_shape(painter: QPainter, rect: QRectF, fill: str | QColor, cut: float = 4) -> None:
    # Twelve orthogonal vertices remove a square at each corner. Snap to physical
    # pixels at fractional DPI; antialias only text, never these stepped edges.
    dpr = painter.device().devicePixelRatioF()
    snap = lambda value: round(value * dpr) / dpr
    x, y, right, bottom = map(snap, (rect.left(), rect.top(), rect.right(), rect.bottom()))
    cut = min(cut, rect.width() / 2, rect.height() / 2)
    xl, xr, yt, yb = map(snap, (x + cut, right - cut, y + cut, bottom - cut))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawPolygon(QPolygonF([
        QPointF(xl, y), QPointF(xr, y), QPointF(xr, yt), QPointF(right, yt),
        QPointF(right, yb), QPointF(xr, yb), QPointF(xr, bottom), QPointF(xl, bottom),
        QPointF(xl, yb), QPointF(x, yb), QPointF(x, yt), QPointF(xl, yt),
    ]))


def draw_icon(painter: QPainter, rect: QRectF, icon: QIcon, ink: str | QColor) -> None:
    pixmap = icon.pixmap(rect.size().toSize(), painter.device().devicePixelRatioF())
    tint = QPainter(pixmap)
    tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    tint.fillRect(pixmap.rect(), QColor(ink))
    tint.end()
    painter.drawPixmap(rect.toRect(), pixmap)


def configure_calendar(calendar: QCalendarWidget) -> None:
    calendar.setPalette(palette())
    weekend = QTextCharFormat()
    weekend.setForeground(QColor(PINK))
    for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        calendar.setWeekdayTextFormat(day, weekend)
    # Qt's calendar uses explicit weekend formats and cached navigation icons,
    # which do not follow QSS text colors. Tint the standard icons in both states.
    for name, standard in (
        ("qt_calendar_prevmonth", QStyle.StandardPixmap.SP_ArrowLeft),
        ("qt_calendar_nextmonth", QStyle.StandardPixmap.SP_ArrowRight),
    ):
        button = calendar.findChild(QToolButton, name)
        if button is None:
            continue
        source = calendar.style().standardIcon(standard)
        icon = QIcon()
        dpr = calendar.devicePixelRatioF()
        for mode, ink in ((QIcon.Mode.Normal, TEXT), (QIcon.Mode.Disabled, "#796F86")):
            pixmap = QPixmap(round(16 * dpr), round(16 * dpr))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            draw_icon(painter, QRectF(0, 0, 16, 16), source, ink)
            painter.end()
            icon.addPixmap(pixmap, mode)
        button.setIcon(icon)


def control_face(painter: QPainter, widget: QWidget, down: bool = False, checked: bool = False) -> QRectF:
    rect = QRectF(widget.rect()).adjusted(0, 0, 0, -3)
    pixel_shape(painter, rect.translated(0, 3), SHADOW, 3)
    if down:
        rect.translate(0, 2)
    border = MINT if widget.hasFocus() else PINK if checked or widget.underMouse() else BORDER
    fill = "#342A40" if checked or down else "#30283E" if widget.underMouse() else "#24202F"
    if not widget.isEnabled():
        border, fill = "#383044", "#211E2D"
    pixel_shape(painter, rect, border, 3)
    inset = 2 if widget.hasFocus() else 1
    pixel_shape(painter, rect.adjusted(inset, inset, -inset, -inset), fill, 2)
    if checked:
        painter.fillRect(rect.adjusted(5, rect.height() - 3, -5, -1), QColor(PINK))
    return rect


def paint_button(widget: QPushButton | QToolButton) -> None:
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    rect = control_face(painter, widget, widget.isDown(), widget.isChecked())
    ink = "#796F86" if not widget.isEnabled() else PINK if widget.isChecked() else TEXT
    content = rect.adjusted(10, 0, -10, 0)
    if widget.menu() is not None:
        draw_icon(painter, QRectF(rect.right() - 23, rect.center().y() - 6, 12, 12),
                  widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown), ink)
        content.adjust(0, 0, -18, 0)
    if not widget.icon().isNull():
        draw_icon(painter, QRectF(rect.center().x() - 8, rect.center().y() - 8, 16, 16), widget.icon(), ink)
    else:
        painter.setPen(QColor(ink))
        painter.setFont(widget.font())
        painter.drawText(content, Qt.AlignmentFlag.AlignCenter, widget.text())
    painter.end()


class PixelButton(QPushButton):
    def paintEvent(self, event):
        # Keep QPushButton's activation, focus and exclusive-group semantics.
        paint_button(self)


class PixelToolButton(QToolButton):
    def paintEvent(self, event):
        paint_button(self)


class PixelDateEdit(QDateEdit):
    def paintEvent(self, event):
        painter = QPainter(self)
        control_face(painter, self)
        painter.end()
        # Native date editing and the calendar popup remain keyboard accessible.
        super().paintEvent(event)
        painter = QPainter(self)
        draw_icon(painter, QRectF(self.width() - 21, self.height() / 2 - 7, 12, 12),
                  self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
                  MUTED if self.isEnabled() else "#796F86")
        painter.end()


DIGITS = {
    "0": ("01110", "11011", "11011", "11011", "11011", "11011", "01110"),
    "1": ("00110", "01110", "00110", "00110", "00110", "00110", "01111"),
    "2": ("11110", "00011", "00011", "01110", "11000", "11000", "11111"),
    "3": ("11110", "00011", "00011", "01110", "00011", "00011", "11110"),
    "4": ("11011", "11011", "11011", "11111", "00011", "00011", "00011"),
    "5": ("11111", "11000", "11000", "11110", "00011", "00011", "11110"),
    "6": ("01110", "11000", "11000", "11110", "11011", "11011", "01110"),
    "7": ("11111", "00011", "00110", "00110", "01100", "01100", "01100"),
    "8": ("01110", "11011", "11011", "01110", "11011", "11011", "01110"),
    "9": ("01110", "11011", "11011", "01111", "00011", "00011", "01110"),
    ",": ("00", "00", "00", "00", "00", "01", "01", "10"),
}


class PixelTotalLabel(QLabel):
    def setText(self, text: str) -> None:
        super().setText(text)
        # QLabel retains the exact text for accessibility. Very large values
        # scroll at a fixed glyph size instead of shrinking or losing digits.
        self.setAccessibleDescription(text)
        self.setMinimumWidth(self.sizeHint().width())
        self.update()

    def sizeHint(self) -> QSize:
        width = sum((len(DIGITS[c][0]) + 1) * 4 for c in self.text()) - 4
        return QSize(max(20, width), 34)

    def paintEvent(self, event):
        painter = QPainter(self)
        x = self.width() - self.sizeHint().width()
        for character in self.text():
            bitmap = DIGITS[character]
            for row, cells in enumerate(bitmap):
                for col, bit in enumerate(cells):
                    if bit == "1":
                        painter.fillRect(QRectF(x + col * 4, 2 + row * 4, 4, 4), QColor(MINT))
            x += (len(bitmap[0]) + 1) * 4
        painter.end()


class HeatLegend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(270, 24)
        self.setAccessibleName("按键热度由低到高；薄荷绿边框表示实时敲击")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(0, 0, 20, 24), Qt.AlignmentFlag.AlignVCenter, "低")
        for index in range(9):
            painter.fillRect(QRectF(24 + index * 12, 8, 9, 8),
                             QColor(KEY_IDLE) if index == 0 else heat_color(index / 8))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(139, 0, 20, 24), Qt.AlignmentFlag.AlignVCenter, "高")
        pixel_shape(painter, QRectF(174, 6, 12, 12), MINT, 2)
        pixel_shape(painter, QRectF(176, 8, 8, 8), BACKGROUND, 1)
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(196, 0, 74, 24), Qt.AlignmentFlag.AlignVCenter, "实时敲击")
        painter.end()
