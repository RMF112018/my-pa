"""P6 `CALENDAR.clndr_data` blob: parse and render (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` section 3.4. The
blob is a bracketed tree of nodes `(0||<name>(<attributes>)(<children>))`
with spaces and `0x7F` bytes between nodes:

* `DaysOfWeek` children are named `1` (Sunday) to `7` (Saturday); each holds
  interval nodes `s|HH:MM|f|HH:MM`. A day without an interval is non-working.
* An interval end of `00:00` is minute 1,440 (the end of the day).
* `Exceptions` children carry `d|N`, N days since 1899-12-30; an exception
  without an interval is a non-working day (a holiday).
* `VIEW` is display state and, like any other node this profile does not
  read, is ignored.

The week is returned Monday first, as the scenario engine and the storage
shape of section 8.2 hold it. Caps (section 5.4): tree depth and node count
are checked before a node is allocated, the exception count as it grows.
Pure, standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Final

from my_pa.domain.schedule.p6.model import Bound

__all__ = [
    "CALENDAR_EPOCH",
    "CalendarBoundError",
    "CalendarData",
    "CalendarDataError",
    "parse_calendar_data",
    "render_calendar_data",
]

#: Section 3.4: `d|N` counts days from this date (the OLE automation epoch).
CALENDAR_EPOCH: Final = date(1899, 12, 30)
_MINUTES_PER_DAY: Final = 1440
_SEPARATORS: Final = frozenset(" \x7f")
_CLOCK: Final = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_DAY_NUMBER: Final = re.compile(r"^[1-7]$")
_SERIAL: Final = re.compile(r"^[0-9]{1,6}$")
_ORDINAL: Final = re.compile(r"^[0-9]{1,9}$")
#: Section 5.4: dates are years 1900-2199.
_FIRST_YEAR: Final = 1900
_LAST_YEAR: Final = 2199

type Intervals = tuple[tuple[int, int], ...]


class CalendarDataError(ValueError):
    """The blob is not a calendar this profile can read (never carries blob text)."""


class CalendarBoundError(ValueError):
    """A section 5.4 calendar cap was exceeded."""

    def __init__(self, bound: Bound) -> None:
        super().__init__(bound.value)
        self.bound = bound


@dataclass(frozen=True, slots=True)
class CalendarData:
    """A parsed blob. `week` is None when the blob has no `DaysOfWeek` (section 3.4)."""

    week: tuple[Intervals, ...] | None
    exceptions: tuple[tuple[date, Intervals], ...]


@dataclass(frozen=True, slots=True)
class _Node:
    name: str
    attributes: str
    children: tuple[_Node, ...]


class _Reader:
    def __init__(self, text: str, *, max_depth: int, max_nodes: int) -> None:
        self.text = text
        self.position = 0
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.nodes = 0

    def _skip(self) -> None:
        text = self.text
        while self.position < len(text) and text[self.position] in _SEPARATORS:
            self.position += 1

    def _expect(self, token: str) -> None:
        if not self.text.startswith(token, self.position):
            raise CalendarDataError("calendar tree malformed")
        self.position += len(token)

    def _until(self, stop: str) -> str:
        end = self.text.find(stop, self.position)
        if end < 0:
            raise CalendarDataError("calendar tree malformed")
        piece = self.text[self.position : end]
        if "(" in piece or ")" in piece:
            raise CalendarDataError("calendar tree malformed")
        self.position = end
        return piece

    def node(self, depth: int) -> _Node:
        if depth > self.max_depth:
            raise CalendarBoundError(Bound.CALENDAR_TREE_DEPTH)
        self.nodes += 1
        if self.nodes > self.max_nodes:
            raise CalendarBoundError(Bound.CALENDAR_TREE_NODES)
        self._expect("(")
        if not _ORDINAL.match(self._until("||")):
            raise CalendarDataError("calendar tree malformed")
        self._expect("||")
        name = self._until("(")
        self._expect("(")
        attributes = self._until(")")
        self._expect(")")
        self._expect("(")
        children: list[_Node] = []
        while True:
            self._skip()
            if self.text.startswith(")", self.position):
                self.position += 1
                break
            children.append(self.node(depth + 1))
        self._skip()
        self._expect(")")
        return _Node(name, attributes, tuple(children))

    def document(self) -> _Node:
        self._skip()
        root = self.node(1)
        self._skip()
        if self.position != len(self.text):
            raise CalendarDataError("calendar tree malformed")
        return root


def _clock(text: str, *, end: bool) -> int:
    match = _CLOCK.match(text)
    if match is None:
        raise CalendarDataError("calendar time malformed")
    minute = int(match.group(1)) * 60 + int(match.group(2))
    if end and minute == 0:
        return _MINUTES_PER_DAY
    return minute


def _intervals(nodes: tuple[_Node, ...]) -> Intervals:
    found: list[tuple[int, int]] = []
    for node in nodes:
        if node.children:
            raise CalendarDataError("calendar interval malformed")
        parts = node.attributes.split("|")
        if len(parts) != 4 or {parts[0], parts[2]} != {"s", "f"}:
            raise CalendarDataError("calendar interval malformed")
        values = {parts[0]: parts[1], parts[2]: parts[3]}
        start = _clock(values["s"], end=False)
        finish = _clock(values["f"], end=True)
        if start >= finish:
            raise CalendarDataError("calendar interval empty")
        found.append((start, finish))
    found.sort()
    for (_, previous_end), (start, _) in pairwise(found):
        if start < previous_end:
            raise CalendarDataError("calendar intervals overlap")
    return tuple(found)


def _week(node: _Node) -> tuple[Intervals, ...]:
    days: dict[int, Intervals] = {}
    for child in node.children:
        if not _DAY_NUMBER.match(child.name) or child.attributes:
            raise CalendarDataError("calendar day malformed")
        number = int(child.name)
        if number in days:
            raise CalendarDataError("calendar day repeated")
        days[number] = _intervals(child.children)
    # 1 = Sunday ... 7 = Saturday; Monday first: 2, 3, 4, 5, 6, 7, 1.
    return tuple(days.get(number, ()) for number in (2, 3, 4, 5, 6, 7, 1))


def _exceptions(node: _Node, *, max_exceptions: int) -> tuple[tuple[date, Intervals], ...]:
    found: dict[date, Intervals] = {}
    for child in node.children:
        if len(found) >= max_exceptions:
            raise CalendarBoundError(Bound.CALENDAR_EXCEPTIONS)
        parts = child.attributes.split("|")
        if len(parts) != 2 or parts[0] != "d" or not _SERIAL.match(parts[1]):
            raise CalendarDataError("calendar exception malformed")
        day = CALENDAR_EPOCH + timedelta(days=int(parts[1]))
        if not _FIRST_YEAR <= day.year <= _LAST_YEAR:
            raise CalendarDataError("calendar exception out of range")
        if day in found:
            raise CalendarDataError("calendar exception repeated")
        found[day] = _intervals(child.children)
    return tuple(sorted(found.items()))


def parse_calendar_data(
    text: str, *, max_depth: int, max_nodes: int, max_exceptions: int
) -> CalendarData:
    """Parse a `clndr_data` blob; raises `CalendarDataError` or `CalendarBoundError`."""
    root = _Reader(text, max_depth=max_depth, max_nodes=max_nodes).document()
    if root.name != "CalendarData":
        raise CalendarDataError("calendar root malformed")
    week: tuple[Intervals, ...] | None = None
    exceptions: tuple[tuple[date, Intervals], ...] = ()
    seen: set[str] = set()
    for child in root.children:
        if child.name in {"DaysOfWeek", "Exceptions"}:
            if child.name in seen:
                raise CalendarDataError("calendar section repeated")
            seen.add(child.name)
        if child.name == "DaysOfWeek":
            week = _week(child)
        elif child.name == "Exceptions":
            exceptions = _exceptions(child, max_exceptions=max_exceptions)
    return CalendarData(week=week, exceptions=exceptions)


def _render_clock(minute: int) -> str:
    minute %= _MINUTES_PER_DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _render_intervals(intervals: Intervals) -> str:
    return "".join(
        f"\x7f\x7f(0||{index}(s|{_render_clock(start)}|f|{_render_clock(end)})())"
        for index, (start, end) in enumerate(intervals)
    )


def render_calendar_data(data: CalendarData) -> str:
    """The P6 blob form of `data` (the inverse of `parse_calendar_data`)."""
    parts = ["(0||CalendarData()("]
    if data.week is not None:
        parts.append("\x7f\x7f(0||DaysOfWeek()(")
        # Monday-first storage back to 1 = Sunday ... 7 = Saturday.
        for number, intervals in zip((2, 3, 4, 5, 6, 7, 1), data.week, strict=True):
            parts.append(f"\x7f\x7f(0||{number}()({_render_intervals(intervals)}))")
        parts.append("))")
    parts.append("\x7f\x7f(0||VIEW(ShowTotal|Y)())")
    if data.exceptions:
        parts.append("\x7f\x7f(0||Exceptions()(")
        for index, (day, intervals) in enumerate(data.exceptions):
            serial = (day - CALENDAR_EPOCH).days
            parts.append(f"\x7f\x7f(0||{index}(d|{serial})({_render_intervals(intervals)}))")
        parts.append("))")
    parts.append("))")
    return "".join(parts)
