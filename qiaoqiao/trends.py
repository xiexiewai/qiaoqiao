"""Native charts over daily aggregates; no event history or database access."""

import math
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QScrollArea, QSizePolicy, QToolTip, QVBoxLayout, QWidget,
)

from .core import DailyTotal, TrendSnapshot
from .keys import key_name
from .theme import (
    BACKGROUND, BOARD, BORDER, GRID, KEY_DISABLED, KEY_IDLE, MINT, MUTED,
    PINK, TEXT, heat_color, key_ink, pixel_shape, set_state,
)


def chart_font(*, bold: bool = False, numbers: bool = False) -> QFont:
    return QFont("Consolas" if numbers else "Microsoft YaHei UI", 10,
                 QFont.Weight.DemiBold if bold else QFont.Weight.Normal)


def day_tooltip(item: DailyTotal, today: date) -> str:
    if item.day > today:
        detail = "尚未到来"
    elif item.count is None:
        detail = "无记录"
    else:
        detail = f"{item.count:,} 次" + ("（截至当前）" if item.day == today else "")
    return f"{item.day:%Y/%m/%d}\n{detail}"


class SummaryCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("trendCard")
        self.setMinimumWidth(180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(0)
        self.title = QLabel(title)
        self.title.setObjectName("muted")
        layout.addWidget(self.title)
        self.value = QLabel("0")
        self.value.setObjectName("trendValue")
        self.value.setAccessibleName(title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(41)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.value)
        layout.addWidget(self.scroll)
        self.detail = QLabel()
        self.detail.setObjectName("trendDetail")
        layout.addWidget(self.detail)

    def set_value(self, count: int | None, detail: str) -> None:
        text = f"{count:,}" if count is not None else "暂无"
        set_state(self.value, "empty" if count is None else "normal")
        self.value.setText(text)
        self.value.setMinimumWidth(math.ceil(self.value.fontMetrics().horizontalAdvance(text)) + 4)
        self.value.setAccessibleDescription(f"{text}；{detail}")
        self.detail.setText(detail)
        self.setToolTip(f"{self.title.text()}\n{text}\n{detail}")


class Chart(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.snapshot: TrendSnapshot | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(title)

    def set_snapshot(self, snapshot: TrendSnapshot) -> None:
        self.snapshot = snapshot
        QToolTip.hideText()
        self.update()

    def painter(self, subtitle: str) -> QPainter:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), QColor(BACKGROUND))
        painter.setFont(chart_font(bold=True))
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(0, 0, self.width(), 24), Qt.AlignmentFlag.AlignVCenter, self.title)
        painter.setFont(chart_font())
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(0, 25, self.width(), 22), Qt.AlignmentFlag.AlignVCenter, subtitle)
        return painter

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class DateChart(Chart):
    day_activated = Signal(object)

    def __init__(self, title: str):
        super().__init__(title)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.focused_day: date | None = None
        self.hovered_day: date | None = None

    def set_snapshot(self, snapshot: TrendSnapshot) -> None:
        super().set_snapshot(snapshot)
        if self.focused_day not in [item.day for item, _ in self.date_rects() if item.day <= snapshot.today]:
            self.focused_day = snapshot.today
        self.setAccessibleDescription("\n".join(
            day_tooltip(item, snapshot.today) for item, _ in self.date_rects()
        ))

    def date_rects(self) -> list[tuple[DailyTotal, QRectF]]:
        raise NotImplementedError

    def mouseMoveEvent(self, event):
        self.hovered_day = None
        for item, rect in self.date_rects():
            if rect.contains(event.position()):
                self.hovered_day = item.day
                self.setCursor(Qt.CursorShape.PointingHandCursor if item.day <= self.snapshot.today
                               else Qt.CursorShape.ArrowCursor)
                QToolTip.showText(event.globalPosition().toPoint(), day_tooltip(item, self.snapshot.today), self)
                break
        else:
            self.unsetCursor()
            QToolTip.hideText()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for item, rect in self.date_rects():
                if rect.contains(event.position()) and item.day <= self.snapshot.today:
                    self.focused_day = item.day
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                    self.day_activated.emit(item.day)
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        days = [item.day for item, _ in self.date_rects() if item.day <= self.snapshot.today]
        if not days:
            return super().keyPressEvent(event)
        index = days.index(self.focused_day) if self.focused_day in days else len(days) - 1
        steps = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1,
                 Qt.Key.Key_Up: -7, Qt.Key.Key_Down: 7}
        if event.key() in steps:
            self.focused_day = days[max(0, min(len(days) - 1, index + steps[event.key()]))]
        elif event.key() == Qt.Key.Key_Home:
            self.focused_day = days[0]
        elif event.key() == Qt.Key.Key_End:
            self.focused_day = days[-1]
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.day_activated.emit(days[index])
            return
        else:
            return super().keyPressEvent(event)
        self.update()
        for item, rect in self.date_rects():
            if item.day == self.focused_day:
                QToolTip.showText(self.mapToGlobal(rect.center().toPoint()),
                                  day_tooltip(item, self.snapshot.today), self)
                break

    def leaveEvent(self, event):
        self.hovered_day = None
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        QToolTip.hideText()
        super().focusOutEvent(event)


class DailyLineChart(DateChart):
    def __init__(self):
        super().__init__("近 7 天每日敲击")
        self.setMinimumSize(460, 180)
        self.axis_maximum = 4
        self.axis_width = 40

    def set_snapshot(self, snapshot: TrendSnapshot) -> None:
        maximum = max(item.count or 0 for item in snapshot.recent_days)
        self.axis_maximum = max(4, ((maximum + 3) // 4) * 4)
        metrics = QFontMetricsF(chart_font(numbers=True))
        self.axis_width = math.ceil(metrics.horizontalAdvance(f"{self.axis_maximum:,}")) + 12
        self.setMinimumWidth(self.axis_width + 7 * 60)
        super().set_snapshot(snapshot)

    def plot_rect(self) -> QRectF:
        # Leave half a date label between the first point and the axis numbers.
        return QRectF(self.axis_width + 30, 60, self.width() - self.axis_width - 62, self.height() - 92)

    def date_rects(self) -> list[tuple[DailyTotal, QRectF]]:
        if self.snapshot is None:
            return []
        plot = self.plot_rect()
        step = plot.width() / 6
        return [(item, QRectF(plot.left() + index * step - step / 2, plot.top(),
                              step, plot.height() + 30))
                for index, item in enumerate(self.snapshot.recent_days)]

    def point(self, index: int, count: int) -> QPointF:
        plot = self.plot_rect()
        return QPointF(plot.left() + index * plot.width() / 6,
                       plot.bottom() - count / self.axis_maximum * plot.height())

    def paintEvent(self, event):
        if self.snapshot is None:
            return
        data = self.snapshot
        painter = self.painter(f"{data.recent_days[0].day:%m/%d} - {data.today:%m/%d}   今日截至当前")
        plot = self.plot_rect()
        painter.setFont(chart_font(numbers=True))
        for tick in range(5):
            y = plot.bottom() - tick * plot.height() / 4
            painter.setPen(QColor(GRID))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(0, y - 10, self.axis_width - 10, 20),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{self.axis_maximum * tick // 4:,}")
        previous = None
        for index, item in enumerate(data.recent_days):
            x = self.point(index, 0).x()
            selected = item.day == self.hovered_day or (self.hasFocus() and item.day == self.focused_day)
            if selected:
                painter.setPen(QPen(QColor(PINK), 1, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            if item.count is None:
                previous = None
                painter.setFont(chart_font())
                painter.setPen(QColor(MUTED))
                painter.drawText(QRectF(x - 25, plot.bottom() - 24, 50, 20),
                                 Qt.AlignmentFlag.AlignCenter, "无记录")
            else:
                point = self.point(index, item.count)
                if previous is not None:
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setPen(QPen(QColor(MINT), 2))
                    painter.drawLine(previous, point)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                painter.fillRect(QRectF(point.x() - 3, point.y() - 3, 6, 6),
                                 QColor(PINK if selected else MINT))
                previous = point
            painter.setFont(chart_font(numbers=True))
            painter.setPen(QColor(MINT if item.day == data.today else MUTED))
            painter.drawText(QRectF(x - 30, plot.bottom() + 7, 60, 22),
                             Qt.AlignmentFlag.AlignCenter, f"{item.day:%m/%d}")
        painter.end()


class KeyRankingChart(Chart):
    def __init__(self):
        super().__init__("本周最常用的 10 个键")
        self.setMinimumSize(330, 410)
        self.name_width = 85
        self.count_width = 50

    def set_snapshot(self, snapshot: TrendSnapshot) -> None:
        metrics = QFontMetricsF(chart_font(numbers=True))
        self.name_width = math.ceil(max(
            (metrics.horizontalAdvance(key_name(key)) for key, _ in snapshot.top_keys), default=70,
        )) + 10
        self.count_width = math.ceil(max(
            (metrics.horizontalAdvance(f"{count:,}") for _, count in snapshot.top_keys), default=40,
        )) + 12
        self.setMinimumWidth(max(330, self.name_width + self.count_width + 150))
        self.setAccessibleDescription("\n".join(
            f"{key_name(key)}：{count:,} 次，占本周 {count / snapshot.week_total:.1%}"
            for key, count in snapshot.top_keys
        ) or "本周暂无记录")
        super().set_snapshot(snapshot)

    def row_rects(self) -> list[QRectF]:
        height = (self.height() - 60) / 10
        return [QRectF(0, 57 + i * height, self.width(), height)
                for i in range(len(self.snapshot.top_keys) if self.snapshot else 0)]

    def bar_rect(self, row: QRectF, count: int) -> QRectF:
        left = 30 + self.name_width
        width = self.width() - left - self.count_width - 8
        return QRectF(left, row.center().y() - 6, width * count / self.snapshot.top_keys[0][1], 12)

    def paintEvent(self, event):
        if self.snapshot is None:
            return
        data = self.snapshot
        painter = self.painter(f"{data.week_start:%m/%d} - {data.today:%m/%d}   截至当前")
        if not data.top_keys:
            painter.setFont(chart_font())
            painter.drawText(QRectF(0, 60, self.width(), 100),
                             Qt.AlignmentFlag.AlignCenter, "本周暂无记录")
        painter.setFont(chart_font(numbers=True))
        for index, ((key, count), row) in enumerate(zip(data.top_keys, self.row_rects())):
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(0, row.top(), 24, row.height()),
                             Qt.AlignmentFlag.AlignVCenter, f"{index + 1:02}")
            painter.setPen(QColor(TEXT))
            painter.drawText(QRectF(30, row.top(), self.name_width, row.height()),
                             Qt.AlignmentFlag.AlignVCenter, key_name(key))
            bar = self.bar_rect(row, count)
            painter.fillRect(QRectF(bar.left(), bar.top(),
                                    self.width() - bar.left() - self.count_width - 8, 12), QColor(GRID))
            painter.fillRect(bar, QColor(PINK if index == 0 else MINT))
            painter.setPen(QColor(TEXT))
            painter.drawText(QRectF(self.width() - self.count_width, row.top(), self.count_width, row.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{count:,}")
        painter.end()

    def mouseMoveEvent(self, event):
        for (key, count), rect in zip(self.snapshot.top_keys if self.snapshot else (), self.row_rects()):
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"{key_name(key)}\n{count:,} 次\n占本周 {count / self.snapshot.week_total:.1%}", self)
                return
        QToolTip.hideText()


class MonthHeatmap(DateChart):
    def __init__(self):
        super().__init__("本月每日热度")
        self.setMinimumSize(460, 220)

    def date_rects(self) -> list[tuple[DailyTotal, QRectF]]:
        if self.snapshot is None:
            return []
        first = self.snapshot.month_start.weekday()
        rows = math.ceil((first + len(self.snapshot.month_days)) / 7)
        cell_width = self.width() / 7
        cell_height = (self.height() - 98) / rows
        return [(item, QRectF((first + index) % 7 * cell_width + 2,
                              72 + (first + index) // 7 * cell_height,
                              cell_width - 5, cell_height - 3))
                for index, item in enumerate(self.snapshot.month_days)]

    def cell_color(self, item: DailyTotal) -> QColor:
        if item.day > self.snapshot.today:
            return QColor(KEY_DISABLED)
        if item.count is None:
            return QColor(BOARD)
        if not item.count:
            return QColor(KEY_IDLE)
        maximum = max(day.count or 0 for day in self.snapshot.month_days)
        return heat_color(math.log1p(item.count) / math.log1p(maximum))

    def paintEvent(self, event):
        if self.snapshot is None:
            return
        data = self.snapshot
        painter = self.painter(f"{data.today:%Y 年 %m 月}   截至当前")
        for index, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            painter.drawText(QRectF(index * self.width() / 7, 48, self.width() / 7, 21),
                             Qt.AlignmentFlag.AlignCenter, name)
        for item, rect in self.date_rects():
            future = item.day > data.today
            fill = self.cell_color(item)
            selected = item.day == self.hovered_day or (self.hasFocus() and item.day == self.focused_day)
            edge = MINT if item.day == data.today else PINK if selected and not future else (
                BORDER if item.count is None and not future else fill
            )
            pixel_shape(painter, rect, edge, 2)
            pixel_shape(painter, rect.adjusted(2, 2, -2, -2), fill, 1)
            painter.setPen(QColor(MUTED) if future or item.count is None else key_ink(fill))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(item.day.day))
        y = self.height() - 22
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(0, y, 28, 22), Qt.AlignmentFlag.AlignVCenter, "低")
        for index in range(6):
            painter.fillRect(QRectF(24 + index * 14, y + 7, 10, 9),
                             QColor(KEY_IDLE) if index == 0 else heat_color(index / 5))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(112, y, 120, 22), Qt.AlignmentFlag.AlignVCenter, "高（本月相对）")
        pixel_shape(painter, QRectF(240, y + 5, 14, 14), BORDER, 2)
        pixel_shape(painter, QRectF(242, y + 7, 10, 10), BOARD, 1)
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(260, y, 62, 22), Qt.AlignmentFlag.AlignVCenter, "无记录")
        painter.fillRect(QRectF(336, y + 5, 14, 14), QColor(KEY_DISABLED))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(356, y, 80, 22), Qt.AlignmentFlag.AlignVCenter, "未到日期")
        painter.end()


class TrendPage(QScrollArea):
    day_activated = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.viewport().setObjectName("trendViewport")
        content = QWidget()
        content.setObjectName("trendPage")
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)
        cards = QGridLayout()
        cards.setSpacing(10)
        self.cards = tuple(SummaryCard(title) for title in (
            "今日敲击", "本周累计", "本月累计", "本月单日最高",
        ))
        for index, card in enumerate(self.cards):
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        layout.addLayout(cards)
        charts = QGridLayout()
        charts.setHorizontalSpacing(28)
        charts.setVerticalSpacing(10)
        self.line = DailyLineChart()
        self.ranking = KeyRankingChart()
        self.month = MonthHeatmap()
        charts.addWidget(self.line, 0, 0)
        charts.addWidget(self.month, 1, 0)
        charts.addWidget(self.ranking, 0, 1, 2, 1)
        charts.setColumnStretch(0, 3)
        charts.setColumnStretch(1, 2)
        layout.addLayout(charts, 1)
        self.line.day_activated.connect(self.day_activated)
        self.month.day_activated.connect(self.day_activated)
        self.snapshot: TrendSnapshot | None = None

    def set_snapshot(self, snapshot: TrendSnapshot) -> None:
        self.snapshot = snapshot
        self.cards[0].set_value(snapshot.today_total, f"{snapshot.today:%Y/%m/%d}  截至当前")
        self.cards[1].set_value(snapshot.week_total, f"{snapshot.week_start:%m/%d} - {snapshot.today:%m/%d}  截至当前")
        self.cards[2].set_value(snapshot.month_total, f"{snapshot.month_start:%m/%d} - {snapshot.today:%m/%d}  截至当前")
        self.cards[3].set_value(snapshot.peak.count if snapshot.peak else None,
                                f"{snapshot.peak.day:%Y/%m/%d}" + (
                                    "  截至当前" if snapshot.peak.day == snapshot.today else ""
                                ) if snapshot.peak else "本月暂无敲击记录")
        for chart in (self.line, self.ranking, self.month):
            chart.set_snapshot(snapshot)
