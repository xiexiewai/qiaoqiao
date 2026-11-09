"""Pure counting and calendar rules. No keyboard event history is retained."""

from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from .keys import PhysicalEvent

Period = Literal["day", "week", "month", "all"]
Counts = dict[tuple[str, str], int]
MILESTONE_INTERVAL = 1000


@dataclass(frozen=True)
class DailyTotal:
    day: date
    count: int | None


@dataclass(frozen=True)
class TrendSnapshot:
    today: date
    week_start: date
    month_start: date
    recent_days: tuple[DailyTotal, ...]
    month_days: tuple[DailyTotal, ...]
    top_keys: tuple[tuple[str, int], ...]
    today_total: int
    week_total: int
    month_total: int
    peak: DailyTotal | None


def date_range(period: Period, anchor: date) -> tuple[date | None, date | None]:
    if period == "all":
        return None, None
    if period == "day":
        return anchor, anchor
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        return anchor.replace(day=1), anchor.replace(day=monthrange(anchor.year, anchor.month)[1])
    raise ValueError(f"Unsupported period: {period}")


def move_date(anchor: date, period: Period, offset: int) -> date:
    if period in ("day", "week"):
        return anchor + timedelta(days=offset * (7 if period == "week" else 1))
    if period == "month":
        months = anchor.year * 12 + anchor.month - 1 + offset
        year, month0 = divmod(months, 12)
        month = month0 + 1
        return date(year, month, min(anchor.day, monthrange(year, month)[1]))
    return anchor


class MilestoneTracker:
    """Derived daily progress; the counter model remains the source of totals."""

    def __init__(self, day: date, total: int, enabled: bool = True, handled: int = 0):
        self.enabled = enabled
        self.reset(day, total, handled)

    def reset(self, day: date, total: int, handled: int = 0) -> None:
        self.day = day
        self.total = total
        # Existing counts are a baseline, not a backlog to celebrate on startup.
        # A saved checkpoint can be ahead of counts after an interrupted save.
        self.handled = max(total // MILESTONE_INTERVAL * MILESTONE_INTERVAL, handled)
        self.pending: int | None = None

    def record_press(self) -> None:
        """Call only after CounterModel accepts a new physical press."""
        self.total += 1
        reached = self.total // MILESTONE_INTERVAL * MILESTONE_INTERVAL
        if reached > self.handled:
            if self.enabled:
                # Retain only the newest threshold if delivery is temporarily paused.
                self.pending = reached
            else:
                self.handled = reached

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.handled = max(self.handled, self.total // MILESTONE_INTERVAL * MILESTONE_INTERVAL)
        self.pending = None

    def take_pending(self) -> int | None:
        threshold = self.pending
        if threshold is not None:
            self.handled = threshold
            self.pending = None
        return threshold


class CounterModel:
    def __init__(self, initial: Counts | None = None):
        self.counts: Counts = dict(initial or {})
        self.pressed: set[tuple[int, str]] = set()
        self.dirty: set[tuple[str, str]] = set()
        self.revision = 0

    def accept(self, event: PhysicalEvent, day: date, *, counting: bool = True) -> bool:
        identity = (event.device, event.key_id)
        if not event.is_down:
            self.pressed.discard(identity)
            return False
        if identity in self.pressed:
            return False
        if not event.pulse:
            self.pressed.add(identity)
        if not counting:
            return False
        key = (day.isoformat(), event.key_id)
        self.counts[key] = self.counts.get(key, 0) + 1
        self.dirty.add(key)
        self.revision += 1
        return True

    def release_device(self, device: int):
        self.pressed = {key for key in self.pressed if key[0] != device}

    def release_all(self):
        self.pressed.clear()

    def snapshot_dirty(self) -> Counts:
        snapshot = {key: self.counts[key] for key in self.dirty}
        self.dirty.clear()
        return snapshot

    def retry(self, snapshot: Counts):
        # Retry current absolute totals, never an old snapshot's smaller values.
        self.dirty.update(snapshot)

    def restored_counts(self, start: date, end: date, replacement: Counts) -> Counts:
        """Prepare the post-import model before the database can commit."""
        lower, upper = start.isoformat(), end.isoformat()
        if start > end or any(not lower <= day <= upper for day, _ in replacement):
            raise ValueError("导入记录必须位于所选日期范围内。")
        result = {key: value for key, value in self.counts.items() if not lower <= key[0] <= upper}
        result.update(replacement)
        return result

    def apply_restored_counts(self, counts: Counts) -> None:
        # Persistence has saved all pre-import dirty values and committed the
        # replacement. Keep physical held-state, but discard old dirty identities.
        self.counts = counts
        self.dirty.clear()
        self.revision += 1

    def totals(self, period: Period, anchor: date) -> Counter:
        start, end = date_range(period, anchor)
        lower = start.isoformat() if start else ""
        upper = end.isoformat() if end else "9999-12-31"
        result = Counter()
        for (day, key_id), count in self.counts.items():
            if lower <= day <= upper:
                result[key_id] += count
        return result

    def trends(self, today: date) -> TrendSnapshot:
        """One consistent view of saved and unsaved daily aggregates.

        Missing past days are unknown: this database does not track uptime.
        Only today can default to zero recorded so far. Future rows are ignored.
        """
        week_start, _ = date_range("week", today)
        month_start, month_end = date_range("month", today)
        recent_start = today - timedelta(days=6)
        lower = min(week_start, month_start, recent_start).isoformat()
        upper = today.isoformat()
        week_lower = week_start.isoformat()
        daily: Counter[str] = Counter()
        weekly: Counter[str] = Counter()
        for (day, key_id), count in self.counts.items():
            if lower <= day <= upper:
                daily[day] += count
                if day >= week_lower:
                    weekly[key_id] += count

        def value(day: date) -> DailyTotal:
            return DailyTotal(day, daily.get(day.isoformat(), 0 if day == today else None))

        recent = tuple(value(recent_start + timedelta(days=i)) for i in range(7))
        month = tuple(value(month_start + timedelta(days=i)) for i in range(month_end.day))
        observed = [item for item in month if item.count is not None and item.count > 0]
        return TrendSnapshot(
            today=today, week_start=week_start, month_start=month_start,
            recent_days=recent, month_days=month,
            top_keys=tuple(sorted(
                ((key, count) for key, count in weekly.items() if count > 0),
                key=lambda item: (-item[1], item[0]),
            )[:10]),
            today_total=daily.get(upper, 0),
            week_total=sum(weekly.values()),
            month_total=sum(item.count or 0 for item in month),
            peak=max(observed, key=lambda item: item.count) if observed else None,
        )

    @property
    def first_day(self) -> date | None:
        return date.fromisoformat(min(day for day, _ in self.counts)) if self.counts else None
