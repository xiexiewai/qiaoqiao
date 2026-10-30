"""Compact keyboard-first Qt Widgets interface."""

import math
from datetime import date

from PySide6.QtCore import QDate, QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QDateEdit, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from .core import CounterModel, date_range, move_date
from .keys import KEYS, KEY_BY_ID, key_name

STYLE = """
QWidget { font-family: "Microsoft YaHei UI"; font-size: 10pt; color: #20262B; }
QMainWindow, QWidget#body { background: #F3F5F7; }
QLabel { background: transparent; }
QLabel#brand { font-size: 21pt; font-weight: 700; }
QLabel#muted { color: #6B7279; }
QLabel#range { font-size: 14pt; font-weight: 600; }
QLabel#total { font-family: "Segoe UI"; font-size: 25pt; font-weight: 600; }
QLabel#status { color: #147D68; }
QPushButton, QToolButton, QDateEdit {
    background: white; border: 1px solid #D5DBE0; border-radius: 5px;
    padding: 6px 10px; min-height: 22px;
}
QPushButton:hover, QToolButton:hover { background: #E7EEEC; border-color: #93B5AA; }
QPushButton:checked { color: white; background: #147D68; border-color: #147D68; }
QPushButton:disabled, QToolButton:disabled, QDateEdit:disabled { color: #A8AFB5; background: #EDF0F2; }
QPushButton:focus, QToolButton:focus, QDateEdit:focus { border: 2px solid #147D68; }
QDateEdit { min-width: 158px; }
QScrollArea { border: none; background: transparent; }
QToolTip { color: #20262B; background: white; border: 1px solid #CDD5DA; padding: 6px; }
QMenu { background: white; border: 1px solid #CDD5DA; padding: 5px; }
QMenu::item { padding: 8px 24px; }
QMenu::item:selected { background: #E4EEEA; }
"""


def application_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 64, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 64, size / 64)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#147D68"))
        painter.drawRoundedRect(QRectF(2, 10, 60, 44), 7, 7)
        painter.setBrush(QColor("#FFFFFF"))
        for row in range(2):
            for col in range(5):
                painter.drawRoundedRect(QRectF(9 + col * 10, 18 + row * 10, 6, 6), 1, 1)
        painter.drawRoundedRect(QRectF(19, 39, 26, 6), 1, 1)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class KeyboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(970, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAccessibleName("104 键键盘统计图")
        self.counts = {}
        self.pressed = set()

    def sizeHint(self):
        return QSize(1170, 365)

    def key_rects(self) -> list[tuple[object, QRectF]]:
        unit = min((self.width() - 4) / 23, (self.height() - 4) / 6.5)
        left, top = (self.width() - 23 * unit) / 2, (self.height() - 6.5 * unit) / 2
        return [
            (key, QRectF(left + key.x * unit + 2, top + key.y * unit + 2,
                         key.width * unit - 5, key.height * unit - 5))
            for key in KEYS
        ]

    def set_counts(self, counts, pressed):
        if self.counts != counts or self.pressed != pressed:
            if self.counts != counts:
                metrics = QFontMetricsF(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
                # Grow the scrollable keyboard before large exact totals would clip.
                unit = max(
                    (metrics.horizontalAdvance(f"{counts.get(key.key_id, 0):,}") + 15) / key.width
                    for key in KEYS
                )
                self.setMinimumSize(max(970, math.ceil(unit * 23 + 4)), max(300, math.ceil(unit * 6.5 + 4)))
            self.counts = dict(counts)
            self.pressed = set(pressed)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        maximum = max(self.counts.values(), default=0)
        for key, rect in self.key_rects():
            count = self.counts.get(key.key_id, 0)
            if count and maximum:
                ratio = math.log1p(count) / math.log1p(maximum)
                fill = QColor.fromRgbF(0.98, 0.96 - ratio * 0.22, 0.88 - ratio * 0.42)
            else:
                fill = QColor("#FFFFFF")
            pressed = key.key_id in self.pressed
            painter.setPen(QPen(QColor("#147D68" if pressed else "#D3DAE0"), 2 if pressed else 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#465059"))
            label_font = QFont("Segoe UI", 8 if len(key.label) > 5 else 9)
            painter.setFont(label_font)
            label_rect = rect.adjusted(5, 5, -4, -rect.height() + 21)
            while painter.fontMetrics().horizontalAdvance(key.label) > label_rect.width() and label_font.pointSizeF() > 7:
                label_font.setPointSizeF(label_font.pointSizeF() - 0.5)
                painter.setFont(label_font)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, key.label)
            value_rect = rect.adjusted(4, 21, -4, -3)
            value_font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
            painter.setFont(value_font)
            text = f"{count:,}"
            while painter.fontMetrics().horizontalAdvance(text) > value_rect.width() and value_font.pointSizeF() > 7:
                value_font.setPointSizeF(value_font.pointSizeF() - 0.5)
                painter.setFont(value_font)
            painter.setPen(QColor("#20262B" if count else "#939CA4"))
            painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

    def mouseMoveEvent(self, event):
        for key, rect in self.key_rects():
            if rect.contains(event.position()):
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{key_name(key.key_id)}\n{self.counts.get(key.key_id, 0):,} 次", self,
                )
                return
        QToolTip.hideText()

    def leaveEvent(self, event):
        QToolTip.hideText()


class StatsWindow(QMainWindow):
    view_changed = Signal()
    hidden_to_tray = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("敲敲 - 键盘统计")
        self.setWindowIcon(application_icon())
        self.resize(1260, 680)
        self.setMinimumSize(1040, 570)
        self.period = "day"
        self.anchor = date.today()
        self.follow_today = True
        self.last_today = date.today()
        self.allow_close = False
        self._render_key = None
        self._build()

    def _build(self):
        body = QWidget()
        body.setObjectName("body")
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 22, 28, 18)
        layout.setSpacing(18)
        header = QHBoxLayout()
        brand = QLabel("敲敲")
        brand.setObjectName("brand")
        header.addWidget(brand)
        subtitle = QLabel("键盘统计")
        subtitle.setObjectName("muted")
        header.addWidget(subtitle)
        header.addStretch()
        self.status_label = QLabel("正在启动")
        self.status_label.setObjectName("status")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.period_buttons = {}
        self.period_group = QButtonGroup(self)
        for period, text in (("day", "日"), ("week", "周"), ("month", "月"), ("all", "全部")):
            button = QPushButton(text)
            button.setFixedWidth(60)
            button.setCheckable(True)
            button.setChecked(period == "day")
            button.setAccessibleName(f"按{text}统计")
            button.clicked.connect(lambda checked=False, p=period: self.set_period(p))
            self.period_group.addButton(button)
            self.period_buttons[period] = button
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.previous = self._arrow(QStyle.StandardPixmap.SP_ArrowLeft, "上一时段")
        self.previous.clicked.connect(lambda: self.navigate(-1))
        toolbar.addWidget(self.previous)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy / MM / dd")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setMaximumDate(QDate.currentDate())
        self.date_edit.setMinimumDate(QDate(1900, 1, 1))
        self.date_edit.setAccessibleName("统计日期")
        self.date_edit.dateChanged.connect(self._date_changed)
        toolbar.addWidget(self.date_edit)
        self.next = self._arrow(QStyle.StandardPixmap.SP_ArrowRight, "下一时段")
        self.next.clicked.connect(lambda: self.navigate(1))
        toolbar.addWidget(self.next)
        self.today_button = QPushButton("今天")
        self.today_button.clicked.connect(self.go_today)
        toolbar.addWidget(self.today_button)
        layout.addLayout(toolbar)

        summary = QHBoxLayout()
        summary.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.range_label = QLabel()
        self.range_label.setObjectName("range")
        self.active_label = QLabel()
        self.active_label.setObjectName("muted")
        titles.addWidget(self.range_label)
        titles.addWidget(self.active_label)
        summary.addLayout(titles)
        summary.addStretch()
        total_caption = QLabel("总敲击")
        total_caption.setObjectName("muted")
        summary.addWidget(total_caption, alignment=Qt.AlignmentFlag.AlignBottom)
        self.total_label = QLabel("0")
        self.total_label.setObjectName("total")
        self.total_label.setAccessibleName("总敲击次数")
        summary.addWidget(self.total_label, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(summary)

        self.keyboard = KeyboardWidget()
        keyboard_scroll = QScrollArea()
        keyboard_scroll.setWidgetResizable(True)
        keyboard_scroll.setWidget(self.keyboard)
        layout.addWidget(keyboard_scroll, stretch=1)
        self.other_label = QLabel()
        self.other_label.setWordWrap(True)
        self.other_label.setObjectName("muted")
        self.other_label.hide()
        layout.addWidget(self.other_label)

        footer = QHBoxLayout()
        info = QLabel("104 键  /  所有键盘")
        info.setObjectName("muted")
        footer.addWidget(info)
        footer.addStretch()
        self.save_label = QLabel("本地数据")
        self.save_label.setObjectName("muted")
        footer.addWidget(self.save_label)
        layout.addLayout(footer)
        self._update_controls()

    def _arrow(self, icon, tooltip):
        button = QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(36, 36)
        return button

    def set_period(self, period):
        self.period = period
        self.period_buttons[period].setChecked(True)
        self._update_controls()
        self.view_changed.emit()

    def _date_changed(self, value):
        self.anchor = value.toPython()
        self.follow_today = self.anchor == date.today()
        self._update_controls()
        self.view_changed.emit()

    def navigate(self, amount):
        target = move_date(self.anchor, self.period, amount)
        self.date_edit.setDate(QDate(target.year, target.month, target.day))

    def go_today(self):
        self.date_edit.setDate(QDate.currentDate())
        self.follow_today = True
        self.view_changed.emit()

    def _update_controls(self):
        enabled = self.period != "all"
        self.date_edit.setEnabled(enabled)
        self.previous.setEnabled(enabled and self.anchor > date(1900, 1, 1))
        self.today_button.setEnabled(enabled and self.anchor != date.today())
        next_start, _ = date_range(self.period, move_date(self.anchor, self.period, 1))
        self.next.setEnabled(enabled and next_start is not None and next_start <= date.today())

    def refresh(self, model: CounterModel):
        today = date.today()
        if today != self.last_today:
            self.last_today = today
            self.date_edit.setMaximumDate(QDate.currentDate())
            if self.follow_today:
                self.go_today()
            self._update_controls()
        render_key = (model.revision, self.period, self.anchor)
        if render_key != self._render_key:
            totals = model.totals(self.period, self.anchor)
            start, end = date_range(self.period, self.anchor)
            if self.period == "day":
                label = self.anchor.strftime("%Y / %m / %d")
                if self.anchor == today:
                    label += "  今天"
            elif self.period == "month":
                label = self.anchor.strftime("%Y 年 %m 月")
            elif self.period == "week":
                label = f"{start:%Y/%m/%d} - {end:%Y/%m/%d}"
            else:
                label = "全部累计"
                if model.first_day:
                    label += f"  自 {model.first_day:%Y/%m/%d}"
            self.range_label.setText(label)
            self.total_label.setText(f"{sum(totals.values()):,}")
            used = sum(1 for count in totals.values() if count)
            self.active_label.setText(f"已使用 {used} 个按键")
            other = [(key, count) for key, count in totals.items() if key not in KEY_BY_ID and count]
            self.other_label.setText("其他按键  " + "    ".join(f"{key_name(key)}: {count:,}" for key, count in sorted(other)))
            self.other_label.setVisible(bool(other))
            self.keyboard.set_counts(totals, {key for _, key in model.pressed})
            self._render_key = render_key
        else:
            self.keyboard.set_counts(self.keyboard.counts, {key for _, key in model.pressed})

    def restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.view_changed.emit()

    def closeEvent(self, event):
        if self.allow_close:
            event.accept()
        else:
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._hide_minimized)
        super().changeEvent(event)

    def _hide_minimized(self):
        if self.isMinimized():
            self.hide()
            self.hidden_to_tray.emit()
