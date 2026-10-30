"""Pure counting and calendar rules. No keyboard event history is retained."""

from calendar import monthrange
from collections import Counter
from datetime import date, timedelta
from typing import Literal

from .keys import PhysicalEvent

Period = Literal["day", "week", "month", "all"]
Counts = dict[tuple[str, str], int]


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


class CounterModel:
    def __init__(self, initial: Counts | None = None):
        self.counts: Counts = dict(initial or {})
        self.pressed: set[tuple[int, str]] = set()
        self.dirty: set[tuple[str, str]] = set()
        self.revision = 0

    def accept(self, event: PhysicalEvent, day: date) -> bool:
        identity = (event.device, event.key_id)
        if not event.is_down:
            self.pressed.discard(identity)
            return False
        if identity in self.pressed:
            return False
        if not event.pulse:
            self.pressed.add(identity)
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

    def totals(self, period: Period, anchor: date) -> Counter:
        start, end = date_range(period, anchor)
        lower = start.isoformat() if start else ""
        upper = end.isoformat() if end else "9999-12-31"
        result = Counter()
        for (day, key_id), count in self.counts.items():
            if lower <= day <= upper:
                result[key_id] += count
        return result

    @property
    def first_day(self) -> date | None:
        return date.fromisoformat(min(day for day, _ in self.counts)) if self.counts else None
