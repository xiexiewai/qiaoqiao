import math
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from qiaoqiao.core import CounterModel
from qiaoqiao.keys import PhysicalEvent
from qiaoqiao.theme import BOARD, KEY_DISABLED, KEY_IDLE, MINT
from qiaoqiao.trends import chart_font, day_tooltip
from qiaoqiao.ui import StatsWindow


APPLICATION = QApplication.instance() or QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)


class TrendViewTests(unittest.TestCase):
    def setUp(self):
        self.today = date.today()
        self.model = CounterModel()
        self.window = StatsWindow()
        self.window.view_changed.connect(lambda: self.window.refresh(self.model))
        self.window.show()
        self.window.refresh(self.model)
        APPLICATION.processEvents()

    def tearDown(self):
        QToolTip.hideText()
        self.window.allow_close = True
        self.window.close()
        self.window.deleteLater()
        APPLICATION.processEvents()

    def show_trends(self):
        QTest.mouseClick(self.window.tabs.tabBar(), Qt.MouseButton.LeftButton,
                         pos=self.window.tabs.tabBar().tabRect(1).center())
        APPLICATION.processEvents()
        return self.window.trends

    def tap(self, key="1e"):
        self.model.accept(PhysicalEvent(1, key, True), self.today)
        self.model.accept(PhysicalEvent(1, key, False), self.today)

    def test_tab_switch_preserves_keyboard_history_layout_and_uses_live_totals(self):
        yesterday = self.today - timedelta(days=1)
        self.model.counts[(yesterday.isoformat(), "30")] = 13
        self.model.revision += 1
        self.window.date_edit.setDate(QDate(yesterday))
        self.window.set_keyboard_layout("60")
        self.tap("47")
        self.window.refresh(self.model)
        self.assertEqual(self.window.total_label.text(), "13")
        page = self.show_trends()
        self.assertEqual(page.cards[0].value.text(), "1")
        self.assertIn(("47", 1), page.snapshot.top_keys)
        self.assertFalse(self.window.layout_button.isVisible())
        self.assertTrue(self.window.save_label.isVisible())
        self.assertTrue(self.window.status_label.isVisible())
        self.tap("47")
        self.window.tabs.setCurrentIndex(0)
        self.assertEqual(self.window.anchor, yesterday)
        self.assertEqual(self.window.keyboard_layout.layout_id, "60")
        self.assertEqual(self.window.total_label.text(), "13")
        self.window.tabs.setCurrentIndex(1)
        self.assertEqual(page.cards[0].value.text(), "2")
        self.assertEqual(self.model.dirty, {(self.today.isoformat(), "47")})

    def test_refresh_is_cached_throttled_and_skipped_when_hidden(self):
        with patch.object(self.model, "trends", wraps=self.model.trends) as aggregate:
            with patch("qiaoqiao.ui.monotonic", return_value=100) as clock:
                self.show_trends()
                aggregate.assert_called_once()
                self.window.refresh(self.model)
                self.tap()
                clock.return_value = 100.9
                self.window.refresh(self.model)
                aggregate.assert_called_once()
                clock.return_value = 101
                self.window.refresh(self.model)
                self.assertEqual(aggregate.call_count, 2)
                self.assertEqual(self.window.trends.cards[0].value.text(), "1")
                clock.return_value = 105
                self.window.refresh(self.model)
                self.assertEqual(aggregate.call_count, 2)
                self.window.hide()
                self.tap()
                self.window.refresh(self.model)
                self.assertEqual(aggregate.call_count, 2)
                self.window.restore()
                self.assertEqual(aggregate.call_count, 3)
                self.assertEqual(self.window.trends.cards[0].value.text(), "2")
                self.window.tabs.setCurrentIndex(0)
                self.tap()
                self.window.refresh(self.model)
                self.assertEqual(aggregate.call_count, 3)

    def test_midnight_refreshes_without_new_press_and_preserves_history(self):
        yesterday = self.today - timedelta(days=1)
        tomorrow = self.today + timedelta(days=1)
        self.window.date_edit.setDate(QDate(yesterday))
        page = self.show_trends()
        with patch("qiaoqiao.ui.date") as clock:
            clock.today.return_value = tomorrow
            clock.side_effect = date
            with patch("qiaoqiao.ui.monotonic", return_value=self.window._trend_updated_at + .1):
                self.window.refresh(self.model)
        self.assertEqual(page.snapshot.today, tomorrow)
        self.assertEqual(self.window.anchor, yesterday)
        self.assertEqual(page.snapshot.today_total, 0)

    def test_date_mouse_and_keyboard_navigation_open_day_without_losing_layout(self):
        page = self.show_trends()
        self.window.set_keyboard_layout("laptop")
        target, rect = page.line.date_rects()[1]
        QTest.mouseClick(page.line, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
        self.assertEqual(self.window.tabs.currentIndex(), 0)
        self.assertEqual((self.window.period, self.window.anchor), ("day", target.day))
        self.assertEqual(self.window.keyboard_layout.layout_id, "laptop")
        self.window.tabs.setCurrentIndex(1)
        page.month.setFocus()
        QTest.keyClick(page.month, Qt.Key.Key_Home)
        QTest.keyClick(page.month, Qt.Key.Key_Return)
        self.assertEqual(self.window.anchor, self.today.replace(day=1))
        self.assertEqual(self.window.tabs.currentIndex(), 0)

    def test_future_calendar_cells_do_not_navigate_and_missing_dates_have_tooltips(self):
        page = self.show_trends()
        snapshot = self.model.trends(date(2026, 11, 3))
        page.set_snapshot(snapshot)
        future, rect = page.month.date_rects()[3]
        QTest.mouseClick(page.month, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertEqual(day_tooltip(future, snapshot.today), "2026/11/04\n尚未到来")
        missing = snapshot.month_days[0]
        self.assertIn("无记录", day_tooltip(missing, snapshot.today))
        self.assertEqual(page.month.cell_color(missing), QColor(BOARD))
        self.assertEqual(page.month.cell_color(snapshot.month_days[2]), QColor(KEY_IDLE))
        self.assertEqual(page.month.cell_color(future), QColor(KEY_DISABLED))
        self.assertIn("无记录", page.line.accessibleDescription())

    def test_snapshot_is_shared_and_ranking_uses_week_total_for_percentage(self):
        # 11 positive keys; the denominator must include the omitted eleventh.
        self.model = CounterModel({(self.today.isoformat(), f"{i:02x}"): i for i in range(1, 12)})
        page = self.show_trends()
        self.assertIs(page.snapshot, page.line.snapshot)
        self.assertIs(page.snapshot, page.month.snapshot)
        self.assertIs(page.snapshot, page.ranking.snapshot)
        self.assertEqual(len(page.snapshot.top_keys), 10)
        self.assertIn("16.7%", page.ranking.accessibleDescription())
        self.assertEqual(page.cards[1].value.text(), "66")

    def test_empty_charts_and_calendar_geometry_at_default_and_minimum_size(self):
        page = self.show_trends()
        self.assertEqual(page.cards[3].value.text(), "暂无")
        self.assertEqual(page.ranking.accessibleDescription(), "本周暂无记录")
        for size in ((1260, 680), (1040, 570)):
            self.window.resize(*size)
            for day in (date(2026, 11, 3), date(2027, 2, 15), date(2028, 2, 29)):
                page.set_snapshot(self.model.trends(day))
                APPLICATION.processEvents()
                self.assertEqual(self.window.size().width(), size[0])
                rects = page.month.date_rects()
                for index, (item, rect) in enumerate(rects):
                    self.assertGreaterEqual(rect.left(), 0)
                    self.assertLessEqual(rect.right(), page.month.width())
                    self.assertLessEqual(rect.bottom(), page.month.height() - 22)
                    self.assertGreater(rect.height(), 16)
                    for _, other in rects[index + 1:]:
                        self.assertFalse(rect.intersects(other))
                self.assertEqual(
                    math.floor(rects[0][1].left() / (page.month.width() / 7)),
                    day.replace(day=1).weekday(),
                )
                self.assertFalse(page.grab().isNull())

    def test_extreme_values_scroll_without_widening_window_or_truncating_labels(self):
        huge = 9_223_372_036_854_775_807
        self.model = CounterModel({(self.today.isoformat(), "e0_64"): huge})
        self.window.resize(1040, 570)
        page = self.show_trends()
        APPLICATION.processEvents()
        self.assertEqual(self.window.width(), 1040)
        for card in page.cards:
            self.assertEqual(card.value.text(), f"{huge:,}")
            self.assertGreaterEqual(card.value.minimumWidth(),
                                    card.value.fontMetrics().horizontalAdvance(card.value.text()))
            self.assertGreater(card.scroll.horizontalScrollBar().maximum(), 0)
        ranking = page.ranking
        metrics = QFontMetricsF(chart_font(numbers=True))
        self.assertGreaterEqual(ranking.count_width, metrics.horizontalAdvance(f"{huge:,}"))
        self.assertGreaterEqual(ranking.name_width, metrics.horizontalAdvance("Scan E0_64"))
        self.assertGreater(page.horizontalScrollBar().maximum(), 0)
        self.assertGreater(page.line.plot_rect().width(), 350)

    def test_heatmap_and_line_render_data_pixels_and_today_outline(self):
        self.tap()
        page = self.show_trends()
        APPLICATION.processEvents()
        image = page.line.grab().toImage()
        point = page.line.point(6, 1)
        scale = image.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(point.x() * scale), round(point.y() * scale)), QColor(MINT))
        image = page.month.grab().toImage()
        rect = next(rect for item, rect in page.month.date_rects() if item.day == self.today)
        scale = image.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(rect.center().x() * scale),
                                         round((rect.top() + .5) * scale)), QColor(MINT))
        ranking = page.ranking
        self.assertGreater(ranking.bar_rect(ranking.row_rects()[0], 1).width(), 0)

    def test_line_has_visible_segments_but_never_bridges_missing_dates(self):
        self.model = CounterModel({
            ((self.today - timedelta(days=offset)).isoformat(), "1e"): 2
            for offset in (6, 5, 3, 2, 0)
        })
        line = self.show_trends().line
        APPLICATION.processEvents()
        image = line.grab().toImage()
        scale = image.devicePixelRatio()

        def has_line_at(x):
            y = line.point(0, 2).y()
            return any(
                image.pixelColor(round(x * scale), round(y * scale) + offset) == QColor(MINT)
                for offset in range(-2, 3)
            )

        self.assertTrue(has_line_at((line.point(0, 2).x() + line.point(1, 2).x()) / 2))
        self.assertFalse(has_line_at(line.point(2, 2).x()))
        self.assertFalse(has_line_at(line.point(5, 2).x()))

    def test_entering_trends_stops_keyboard_feedback_and_new_keys_do_not_animate(self):
        self.window.keyboard.flash_key("1e")
        self.assertTrue(self.window.keyboard._feedback_timer.isActive())
        self.show_trends()
        self.assertFalse(self.window.keyboard._feedback_timer.isActive())
        self.window.keyboard.flash_key("1e")
        self.assertFalse(self.window.keyboard._feedback_timer.isActive())
        self.assertFalse(self.window.keyboard._flashes)


if __name__ == "__main__":
    unittest.main()
