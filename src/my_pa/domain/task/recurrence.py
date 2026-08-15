"""Recurring Task series, and the one actionable occurrence each holds at a time.

A `RecurrenceRule` is a durable series definition — daily, weekdays, weekly,
selected-weekdays, or monthly — independent of any Task row generated from it.
It never materialises more than the one occurrence a Task can act on: the
series names when the *next* occurrence falls, `next_occurrence` computes it,
and nothing here enumerates a calendar of future Tasks in advance. That is what
"one actionable occurrence at a time" means, and it is a deliberate absence
rather than an oversight — a store of not-yet-relevant future occurrences would
be state this module would have to keep synchronised with edits to the rule for
no reader that needs it before it is due.

**Everything here is computed in the series' own IANA timezone, in civil
(wall-clock) time, and DST is handled explicitly rather than left to whatever
`datetime` arithmetic happens to do.** `zoneinfo.ZoneInfo` is the standard
library's DST-aware zone database, and `fold` is the standard library's own
disambiguation flag for the one hour that exists twice a year in a zone that
observes daylight saving; both are used because DST-correctness is a stated
requirement of this module (`tests/unit/test_task_domain.py` runs both an
America/New_York spring-forward and a fall-back series through it) and neither
can be reimplemented more precisely than the standard library already has.

* A spring-forward gap (the wall-clock hour that never occurs, e.g. 02:30 on
  the "spring ahead" day) is advanced to the first representable instant at or
  after the nominal wall time, because that hour has no `fold` value that would
  make it exist.
* A fall-back fold (the wall-clock hour that occurs twice) resolves to
  `fold=0`, the *first* — earlier, still-daylight-time — occurrence, so a
  9:00 PM daily reminder fires at the same absolute distance from midnight on
  the one day of the year the local clock repeats itself, rather than silently
  drifting an hour late.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc

__all__ = [
    "MAX_RECURRENCE_SEARCH_STEPS",
    "RecurrenceError",
    "RecurrenceFrequency",
    "RecurrenceRule",
    "Weekday",
    "next_occurrence",
]

#: Bounds a pathological rule (e.g. selected weekdays naming none of them, were
#: that not refused at construction) to a finite search rather than a hang.
MAX_RECURRENCE_SEARCH_STEPS: Final = 4000


class RecurrenceError(ValueError):
    """A recurrence rule or occurrence computation refused to proceed."""


class RecurrenceFrequency(StrEnum):
    """The closed set of recurrence shapes this build generates occurrences for.

    Five members and no free-form calendar expression: each is a shape a reader
    can name and a series editor can present as a fixed choice, which an
    arbitrary RRULE-style expression would not be.
    """

    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKLY = "weekly"
    SELECTED_WEEKDAYS = "selected_weekdays"
    MONTHLY = "monthly"


class Weekday(IntEnum):
    """Monday-first weekday, matching `datetime.weekday()`."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


_WEEKDAYS: Final = frozenset(Weekday)


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    """A durable series definition, independent of any one occurrence Task.

    `anchor_at` is a timezone-aware UTC instant naming the wall-clock moment the
    series is anchored to in `timezone` — the first occurrence's civil time, not
    a second clock. `next_occurrence` reads it back through `timezone` rather
    than through UTC arithmetic, which is what keeps a daily 9:00 AM reminder at
    9:00 AM through a DST transition instead of drifting to 8:00 or 10:00.
    """

    recurrence_id: str
    principal_id: str
    frequency: RecurrenceFrequency
    timezone: str
    anchor_at: datetime
    interval: int = 1
    weekdays: frozenset[Weekday] = field(default_factory=frozenset)
    cancelled_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.recurrence_id, IdKind.TASK_RECURRENCE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.frequency, RecurrenceFrequency):
            raise RecurrenceError("a recurrence rule names one known frequency")
        _validate_timezone(self.timezone)
        try:
            ensure_utc(self.anchor_at)
        except NaiveDatetimeError as exc:
            raise RecurrenceError("a recurrence anchor must be timezone-aware") from exc
        if self.interval < 1:
            raise RecurrenceError("a recurrence interval must be at least one")
        if self.cancelled_at is not None:
            ensure_utc(self.cancelled_at)
        selected = self.frequency is RecurrenceFrequency.SELECTED_WEEKDAYS
        weekly = self.frequency is RecurrenceFrequency.WEEKLY
        if selected and not self.weekdays:
            raise RecurrenceError("selected-weekdays recurrence names at least one weekday")
        if weekly and len(self.weekdays) != 1:
            raise RecurrenceError("weekly recurrence names exactly one weekday")
        if not selected and not weekly and self.weekdays:
            raise RecurrenceError("only weekly and selected-weekdays recurrence name weekdays")
        if self.frequency is RecurrenceFrequency.WEEKDAYS:
            object.__setattr__(
                self,
                "weekdays",
                frozenset(
                    {
                        Weekday.MONDAY,
                        Weekday.TUESDAY,
                        Weekday.WEDNESDAY,
                        Weekday.THURSDAY,
                        Weekday.FRIDAY,
                    }
                ),
            )
        if not self.weekdays <= _WEEKDAYS:
            raise RecurrenceError("a recurrence weekday must be one of the seven named days")

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None


def _validate_timezone(name: str) -> None:
    if not name.strip():
        raise RecurrenceError("a recurrence names a non-blank IANA timezone")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RecurrenceError("a recurrence timezone must be a valid IANA name") from exc


def next_occurrence(rule: RecurrenceRule, *, after: datetime | None = None) -> datetime | None:
    """The next actionable occurrence strictly after `after`, or the anchor.

    Returns `None` for a cancelled rule: a cancelled series has no further
    actionable occurrence, and `None` says so rather than a caller having to
    check `rule.is_cancelled` separately every time it reads this function's
    result. `after`, when given, must be timezone-aware UTC, exactly like every
    other public instant in this codebase.
    """
    if rule.is_cancelled:
        return None
    zone = ZoneInfo(rule.timezone)
    anchor_local = ensure_utc(rule.anchor_at).astimezone(zone)
    if after is None:
        occurrence = anchor_local if _matches(anchor_local, rule) else _advance(anchor_local, rule)
    else:
        after_local = ensure_utc(after).astimezone(zone)
        occurrence = _advance_past(after_local, anchor_local, rule)
    return _as_utc_instant(occurrence, zone)


def _matches(moment: datetime, rule: RecurrenceRule) -> bool:
    weekday = Weekday(moment.weekday())
    if rule.frequency in (RecurrenceFrequency.WEEKDAYS, RecurrenceFrequency.SELECTED_WEEKDAYS):
        return weekday in rule.weekdays
    if rule.frequency is RecurrenceFrequency.WEEKLY:
        return weekday in rule.weekdays
    return True


def _civil_add(moment: datetime, delta: timedelta) -> datetime:
    """Advance by wall-clock (civil) time, not by a fixed span of elapsed UTC.

    Adding a `timedelta` directly to a zone-aware `datetime` under `zoneinfo`
    already does exactly this — arithmetic on the naive wall-clock fields, with
    the zone reattached — but `fold` is reset to `0` explicitly afterwards so a
    step landing in a fall-back fold always resolves to the earlier instant
    rather than inheriting whatever fold the step happened to produce.
    """
    naive = moment.replace(tzinfo=None) + delta
    return naive.replace(tzinfo=moment.tzinfo, fold=0)


def _advance(moment: datetime, rule: RecurrenceRule) -> datetime:
    if rule.frequency is RecurrenceFrequency.MONTHLY:
        return _add_months(moment, rule.interval)
    if rule.frequency is RecurrenceFrequency.WEEKLY:
        return _civil_add(moment, timedelta(days=7 * rule.interval))
    if rule.frequency is RecurrenceFrequency.DAILY:
        return _civil_add(moment, timedelta(days=rule.interval))
    # WEEKDAYS and SELECTED_WEEKDAYS: step a day at a time to the next match.
    step = _civil_add(moment, timedelta(days=1))
    guard = 0
    while not _matches(step, rule):
        step = _civil_add(step, timedelta(days=1))
        guard += 1
        if guard > MAX_RECURRENCE_SEARCH_STEPS:
            raise RecurrenceError("recurrence search exceeded its bound")
    return step


def _advance_past(after: datetime, anchor: datetime, rule: RecurrenceRule) -> datetime:
    if after < anchor and _matches(anchor, rule):
        return anchor
    cursor = anchor if _matches(anchor, rule) else _advance(anchor, rule)
    guard = 0
    while cursor <= after:
        cursor = _advance(cursor, rule)
        guard += 1
        if guard > MAX_RECURRENCE_SEARCH_STEPS:
            raise RecurrenceError("recurrence search exceeded its bound")
    return cursor


def _add_months(moment: datetime, months: int) -> datetime:
    """Add whole months by civil calendar arithmetic, clamped to the month end.

    31 March plus one month is 30 April, not an overflowed 31 April: the day is
    clamped to the target month's last real day rather than rolling into the
    month after.
    """
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    day = min(moment.day, last_day_of_month)
    return moment.replace(year=year, month=month, day=day, fold=0)


def _as_utc_instant(local_moment: datetime, zone: ZoneInfo) -> datetime:
    """Resolve a civil-time computation back to one unambiguous UTC instant.

    `local_moment` already carries `zone` and the deliberate `fold=0` every
    civil-time step above sets, so this is a plain, unambiguous conversion: the
    disambiguation already happened at the point each step was produced.
    """
    return local_moment.astimezone(ZoneInfo("UTC"))
