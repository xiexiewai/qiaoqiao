"""Compact keyboard-first Qt Widgets interface."""

import math
from datetime import date
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QDate, QEvent, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QFont, QFontMetricsF, QIcon, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QScrollArea, QSizePolicy, QStyle, QToolTip, QVBoxLayout, QWidget,
)

from .core import CounterModel, date_range, move_date
from .keys import key_name
from .layouts import DEFAULT_LAYOUT, LAYOUTS, LAYOUT_BY_ID
from .theme import (
    BACKGROUND, BOARD, BORDER, GRID, KEY_DISABLED, KEY_IDLE, KEY_MUTED, MINT, MUTED,
    PINK, SHADOW, STYLE, HeatLegend, PixelButton, PixelDateEdit, PixelToolButton,
    PixelTotalLabel, blend, configure_calendar, draw_icon, heat_color, key_ink, palette, pixel_shape,
)

SHORT_ARROW_LABELS = {"e0_48": "\u2191", "e0_50": "\u2193"}


def application_icon() -> QIcon:
    # PyInstaller preserves this relative layout inside the bundled data directory.
    return QIcon(str(Path(__file__).resolve().parents[1] / "assets" / "qiaoqiao.ico"))


class KeyboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.keyboard_layout = DEFAULT_LAYOUT
        self.counts = {}
        self.pressed = set()
        self.hovered = None
        self._flashes: dict[str, float] = {}
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setInterval(33)
        self._feedback_timer.timeout.connect(self._advance_feedback)
        self._arrow_icons = {
            key: self.style().standardIcon(icon) for key, icon in (
                ("e0_48", QStyle.StandardPixmap.SP_ArrowUp),
                ("e0_50", QStyle.StandardPixmap.SP_ArrowDown),
                ("e0_4b", QStyle.StandardPixmap.SP_ArrowLeft),
                ("e0_4d", QStyle.StandardPixmap.SP_ArrowRight),
            )
        }
        self.set_keyboard_layout(DEFAULT_LAYOUT)

    def sizeHint(self):
        return QSize(math.ceil(self.keyboard_layout.width * 50 + 32), 365)

    def set_keyboard_layout(self, layout):
        self.keyboard_layout = layout
        self.hovered = None
        self._flashes = {key: until for key, until in self._flashes.items() if key in layout.key_ids}
        self.setAccessibleName(f"{layout.name}键盘统计图")
        self._update_minimum_size()
        QToolTip.hideText()
        self.updateGeometry()
        self.update()

    def key_rects(self) -> list[tuple[object, QRectF]]:
        width, height = self.keyboard_layout.width, self.keyboard_layout.height
        unit = min((self.width() - 32) / width, (self.height() - 32) / height)
        left, top = (self.width() - width * unit) / 2, (self.height() - height * unit) / 2
        return [
            (key, QRectF(left + key.x * unit + 2, top + key.y * unit + 2,
                         key.width * unit - 7, key.height * unit - 7))
            for key in self.keyboard_layout.keys
        ]

    def _update_minimum_size(self):
        metrics = QFontMetricsF(QFont("Consolas", 7, QFont.Weight.DemiBold))
        label_metrics = QFontMetricsF(QFont("Consolas", 7))
        # Leave vertical room for two readable text lines and a hard shadow.
        unit = max(46, math.ceil(metrics.height() + label_metrics.height() + 18))
        for key in self.keyboard_layout.keys:
            if key.key_id is None:
                continue
            content_width = metrics.horizontalAdvance(f"{self.counts.get(key.key_id, 0):,}") + 21
            if key.height < 1:
                content_width += metrics.horizontalAdvance(SHORT_ARROW_LABELS[key.key_id]) + 10
                unit = max(unit, (metrics.height() + 15) / key.height)
            content_width = max(content_width, label_metrics.horizontalAdvance(key.label) + 21)
            unit = max(unit, content_width / key.width)
        # Both dimensions grow together, including for half-height laptop arrows.
        self.setMinimumSize(
            max(600, math.ceil(unit * self.keyboard_layout.width + 32)),
            max(300, math.ceil(unit * self.keyboard_layout.height + 32)),
        )

    def set_counts(self, counts, pressed):
        if self.counts != counts or self.pressed != pressed:
            changed = self.counts != counts
            self.counts = dict(counts)
            self.pressed = set(pressed)
            if changed:
                self._update_minimum_size()
            self.update()

    def heat_maximum(self):
        return max((self.counts.get(key_id, 0) for key_id in self.keyboard_layout.key_ids), default=0)

    def flash_key(self, key_id: str) -> None:
        if not self.isVisible() or key_id not in self.keyboard_layout.key_ids:
            return
        # Only keep an expiring visual state per key, never an input event log.
        # A bounded timer coalesces quick taps; counting/saving stays at its
        # existing cadence and hidden windows do not animate.
        self._flashes[key_id] = monotonic() + .18
        if not self._feedback_timer.isActive():
            self._feedback_timer.start()

    def _advance_feedback(self) -> None:
        now = monotonic()
        self._flashes = {key: until for key, until in self._flashes.items() if until > now}
        self.update()
        if not self._flashes:
            self._feedback_timer.stop()

    def hideEvent(self, event):
        self._feedback_timer.stop()
        self._flashes.clear()
        self.hovered = None
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), QColor(BACKGROUND))
        board = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        pixel_shape(painter, board, "#43364E", 6)
        pixel_shape(painter, board.adjusted(1, 1, -1, -1), BOARD, 5)
        # Clip the static grid to the damaged area, especially on wide,
        # horizontally scrolled keyboards containing unusually large counts.
        visible = event.rect().intersected(self.rect())
        for x in range(max(16, visible.left() // 16 * 16), min(self.width() - 8, visible.right()) + 1, 16):
            for y in range(max(16, visible.top() // 16 * 16), min(self.height() - 8, visible.bottom()) + 1, 16):
                painter.fillRect(QRectF(x, y, 1, 1), QColor(GRID))
        for x, y in ((5, 5), (self.width() - 10, 5), (5, self.height() - 9),
                     (self.width() - 10, self.height() - 9)):
            painter.fillRect(QRectF(x, y, 5, 2), QColor("#A36B94"))
            painter.fillRect(QRectF(x, y, 2, 5), QColor("#A36B94"))
        maximum = self.heat_maximum()
        for key, rect in self.key_rects():
            count = self.counts.get(key.key_id, 0)
            if key.key_id is None:
                fill = QColor(KEY_DISABLED)
            elif count and maximum:
                ratio = math.log1p(count) / math.log1p(maximum)
                fill = heat_color(ratio)
            else:
                fill = QColor(KEY_IDLE)
            pressed = key.key_id in self.pressed or key.key_id in self._flashes
            # The outline and face displacement fit within the key's reserved
            # gap, including the two half-height laptop arrows.
            pixel_shape(painter, rect.translated(0, 3), SHADOW, 3)
            edge = MINT if pressed else PINK if key.key_id == self.hovered and key.key_id else (
                blend(fill, "#FFFFFF", .19) if count else BORDER
            )
            pixel_shape(painter, rect, edge, 3)
            face = rect.adjusted(2, 2, -2, -4)
            if pressed:
                face.translate(0, 2)
            pixel_shape(painter, face, fill, 2)
            painter.fillRect(QRectF(face.x() + 3, face.y() + 1, face.width() - 6, 1),
                             blend(fill, "#FFFFFF", .16))
            ink = key_ink(fill) if count else QColor(KEY_MUTED)
            painter.setPen(ink)
            if key.key_id is None:
                painter.setPen(QColor(MUTED))
                painter.setFont(QFont("Consolas", 9))
                painter.drawText(face, Qt.AlignmentFlag.AlignCenter, key.label)
                continue
            if key.height < 1:
                # Short laptop arrows keep the label and exact count on one line.
                painter.setFont(QFont("Consolas", 7, QFont.Weight.DemiBold))
                text_rect = face.adjusted(4, 0, -4, 0)
                painter.drawText(
                    text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    SHORT_ARROW_LABELS[key.key_id],
                )
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{count:,}")
                continue
            label_font = QFont("Consolas", 8 if len(key.label) > 5 else 9)
            painter.setFont(label_font)
            label_rect = QRectF(face.x() + 4, face.y() + 2, face.width() - 8, 17)
            while painter.fontMetrics().horizontalAdvance(key.label) > label_rect.width() and label_font.pointSizeF() > 7:
                label_font.setPointSizeF(label_font.pointSizeF() - 0.5)
                painter.setFont(label_font)
            if key.key_id in self._arrow_icons:
                draw_icon(painter, QRectF(label_rect.x(), label_rect.y() + 2, 12, 12),
                          self._arrow_icons[key.key_id], ink)
            else:
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, key.label)
            value_rect = face.adjusted(4, 19, -4, -1)
            value_font = QFont("Consolas", 10, QFont.Weight.DemiBold)
            painter.setFont(value_font)
            text = f"{count:,}"
            while painter.fontMetrics().horizontalAdvance(text) > value_rect.width() and value_font.pointSizeF() > 7:
                value_font.setPointSizeF(value_font.pointSizeF() - 0.5)
                painter.setFont(value_font)
            painter.setPen(ink)
            painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, text)
            if key.key_id in ("21", "24"):
                painter.fillRect(QRectF(face.center().x() - 4, face.bottom() - 1, 8, 1),
                                 blend(fill, ink, .3))
        painter.end()

    def mouseMoveEvent(self, event):
        for key, rect in self.key_rects():
            if rect.contains(event.position()):
                if self.hovered != key.key_id:
                    self.hovered = key.key_id
                    self.update()
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{key_name(key.key_id)}\n{self.counts.get(key.key_id, 0):,} 次"
                    if key.key_id is not None else "Fn\n此键位不单独统计", self,
                )
                return
        if self.hovered is not None:
            self.hovered = None
            self.update()
        QToolTip.hideText()

    def leaveEvent(self, event):
        self.hovered = None
        self.update()
        QToolTip.hideText()


class StatsWindow(QMainWindow):
    view_changed = Signal()
    hidden_to_tray = Signal()

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle("敲敲 - 键盘统计")
        self.setWindowIcon(application_icon())
        self.setPalette(palette())
        self.setStyleSheet(STYLE)
        self.resize(1260, 680)
        self.setMinimumSize(1040, 570)
        self.period = "day"
        self.anchor = date.today()
        self.follow_today = True
        self.last_today = date.today()
        self.allow_close = False
        self._render_key = None
        self.settings = settings
        saved_layout = settings.value("keyboard/layout", "full") if settings is not None else "full"
        self.keyboard_layout = (
            LAYOUT_BY_ID.get(saved_layout, DEFAULT_LAYOUT) if isinstance(saved_layout, str) else DEFAULT_LAYOUT
        )
        self._build()

    def _build(self):
        body = QWidget()
        body.setObjectName("body")
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 18, 28, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(application_icon().pixmap(QSize(48, 48)))
        logo.setFixedSize(48, 48)
        header.addWidget(logo)
        brand_titles = QVBoxLayout()
        brand_titles.setSpacing(0)
        brand = QLabel("敲敲")
        brand.setObjectName("brand")
        brand_titles.addWidget(brand)
        subtitle = QLabel("键盘统计")
        subtitle.setObjectName("muted")
        brand_titles.addWidget(subtitle)
        header.addLayout(brand_titles)
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
            button = PixelButton(text)
            button.setFixedSize(60, 38)
            button.setCheckable(True)
            button.setChecked(period == "day")
            button.setAccessibleName(f"按{text}统计")
            button.setToolTip(f"按{text}统计")
            button.clicked.connect(lambda checked=False, p=period: self.set_period(p))
            self.period_group.addButton(button)
            self.period_buttons[period] = button
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.previous = self._arrow(QStyle.StandardPixmap.SP_ArrowLeft, "上一时段")
        self.previous.clicked.connect(lambda: self.navigate(-1))
        toolbar.addWidget(self.previous)
        self.date_edit = PixelDateEdit(QDate.currentDate())
        self.date_edit.setFixedHeight(38)
        self.date_edit.setDisplayFormat("yyyy / MM / dd")
        self.date_edit.setCalendarPopup(True)
        configure_calendar(self.date_edit.calendarWidget())
        self.date_edit.setMaximumDate(QDate.currentDate())
        self.date_edit.setMinimumDate(QDate(1900, 1, 1))
        self.date_edit.setAccessibleName("统计日期")
        self.date_edit.dateChanged.connect(self._date_changed)
        toolbar.addWidget(self.date_edit)
        self.next = self._arrow(QStyle.StandardPixmap.SP_ArrowRight, "下一时段")
        self.next.clicked.connect(lambda: self.navigate(1))
        toolbar.addWidget(self.next)
        self.today_button = PixelButton("今天")
        self.today_button.setFixedSize(66, 38)
        self.today_button.clicked.connect(self.go_today)
        toolbar.addWidget(self.today_button)
        layout.addLayout(toolbar)
        separator = QFrame()
        separator.setObjectName("divider")
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFixedHeight(1)
        layout.addWidget(separator)

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
        total_column = QVBoxLayout()
        total_column.setSpacing(2)
        total_caption = QLabel("总敲击")
        total_caption.setObjectName("muted")
        total_column.addWidget(total_caption, alignment=Qt.AlignmentFlag.AlignRight)
        self.total_label = PixelTotalLabel()
        self.total_label.setText("0")
        self.total_label.setObjectName("total")
        self.total_label.setAccessibleName("总敲击次数")
        self.total_scroll = QScrollArea()
        self.total_scroll.setWidgetResizable(True)
        self.total_scroll.setFixedSize(360, 44)
        self.total_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.total_scroll.viewport().setObjectName("totalViewport")
        self.total_scroll.setWidget(self.total_label)
        total_column.addWidget(self.total_scroll)
        summary.addLayout(total_column)
        layout.addLayout(summary)

        legend = QHBoxLayout()
        legend.addWidget(QLabel("按键热度"))
        legend.addStretch()
        legend.addWidget(HeatLegend())
        layout.addLayout(legend)
        self.keyboard = KeyboardWidget()
        self.keyboard.set_keyboard_layout(self.keyboard_layout)
        keyboard_scroll = QScrollArea()
        keyboard_scroll.viewport().setObjectName("keyboardViewport")
        keyboard_scroll.setWidgetResizable(True)
        keyboard_scroll.setWidget(self.keyboard)
        layout.addWidget(keyboard_scroll, stretch=1)
        self.other_label = QLabel()
        self.other_label.setWordWrap(True)
        self.other_label.setObjectName("muted")
        self.other_label.hide()
        layout.addWidget(self.other_label)

        footer = QHBoxLayout()
        self.layout_button = PixelToolButton()
        self.layout_button.setFixedHeight(38)
        self.layout_button.setAccessibleName("切换键盘布局")
        self.layout_button.setToolTip("切换键盘布局")
        self.layout_button.setPopupMode(PixelToolButton.ToolButtonPopupMode.InstantPopup)
        self.layout_menu = QMenu(self.layout_button)
        self.layout_group = QActionGroup(self)
        self.layout_group.setExclusive(True)
        self.layout_actions = {}
        for preset in LAYOUTS:
            action = self.layout_menu.addAction(preset.name)
            action.setCheckable(True)
            action.setChecked(preset == self.keyboard_layout)
            action.triggered.connect(lambda checked=False, layout_id=preset.layout_id: self.set_keyboard_layout(layout_id))
            self.layout_group.addAction(action)
            self.layout_actions[preset.layout_id] = action
        self.layout_button.setMenu(self.layout_menu)
        self.layout_button.setText(f"键盘布局：{self.keyboard_layout.name}")
        layout_metrics = QFontMetricsF(QFont("Microsoft YaHei UI", 10))
        self.layout_button.setFixedWidth(
            math.ceil(max(layout_metrics.horizontalAdvance(f"键盘布局：{preset.name}") for preset in LAYOUTS)) + 48
        )
        footer.addWidget(self.layout_button)
        info = QLabel("所有键盘")
        info.setObjectName("muted")
        footer.addWidget(info)
        footer.addStretch()
        self.save_label = QLabel("本地数据")
        self.save_label.setObjectName("muted")
        footer.addWidget(self.save_label)
        layout.addLayout(footer)
        self._update_controls()

    def set_keyboard_layout(self, layout_id):
        preset = LAYOUT_BY_ID.get(layout_id, DEFAULT_LAYOUT)
        if preset == self.keyboard_layout:
            return
        self.keyboard_layout = preset
        self.keyboard.set_keyboard_layout(preset)
        self.layout_actions[preset.layout_id].setChecked(True)
        self.layout_button.setText(f"键盘布局：{preset.name}")
        self.layout_button.setToolTip("切换键盘布局")
        if self.settings is not None:
            self.settings.setValue("keyboard/layout", preset.layout_id)
            self.settings.sync()
            if self.settings.status() != QSettings.Status.NoError:
                self.layout_button.setToolTip("布局偏好保存失败，下次启动可能需要重新选择")
        self._render_key = None
        self.view_changed.emit()

    def _arrow(self, icon, tooltip):
        button = PixelToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(38, 38)
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
        render_key = (model.revision, self.period, self.anchor, self.keyboard_layout.layout_id)
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
            visible_ids = self.keyboard_layout.key_ids
            other = [(key, count) for key, count in totals.items() if key not in visible_ids and count]
            self.other_label.setText("布局外按键  " + "    ".join(
                key_name(key).replace(" ", "\u00a0") + f":\u00a0{count:,}" for key, count in sorted(other)
            ))
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
