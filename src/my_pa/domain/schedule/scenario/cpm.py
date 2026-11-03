"""Schedule Scenarios S6-1: the deterministic CPM engine `my-pa-cpm-v1` (contract section 3).

`run_cpm(content)` is a pure function of the content (and the engine version):
no clock, randomness, environment, locale or unordered iteration reaches the
result, and no `float` exists anywhere. Activities are processed by their index
in key order, so every tie breaks by key.

Phases, in order, each counted against the operation budget (section 3.11):

1. validation (section 3.4; uncounted): `empty_network`, `unknown_calendar`,
   `dangling_relationship`, `missing_duration`; the first failing check
   rejects with 1 issue per offending element;
2. Kahn's sort with a min-heap on key; a residual set is a cycle, reported by
   the predecessor walk of section 3.4;
3. the forward pass (section 3.5), the backward pass (3.6), the slack phase
   (3.7) and the critical paths (3.8).

Counting rule (section 3.11, frozen with this engine version): +1 per heap
pop; +1 per relationship examined by the sort; +1 per activity entered and
+1 per relationship examined in the forward pass, the backward pass and the
slack phase (a complete activity's outgoing relationships are not examined in
the backward pass); +1 per outermost calendar-function call (`shift` counts as
its inner call; `snap`/`snap_back` call nothing for a zero duration); +1 per
depth-first step and per dynamic-programming node. Before each increment, if
the counter equals the budget, the run is rejected `operation_budget_exceeded`.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from my_pa.domain.schedule.scenario.calendar import (
    CalendarHorizonError,
    CompiledCalendar,
    compile_calendar,
    twenty_four_hour_calendar,
)
from my_pa.domain.schedule.scenario.calendar import advance as _advance
from my_pa.domain.schedule.scenario.calendar import next_work as _next_work
from my_pa.domain.schedule.scenario.calendar import prev_end as _prev_end
from my_pa.domain.schedule.scenario.calendar import retreat as _retreat
from my_pa.domain.schedule.scenario.calendar import working_minutes as _working_minutes
from my_pa.domain.schedule.scenario.canonical import RESULT_SCHEMA, content_sha256
from my_pa.domain.schedule.scenario.model import (
    ActivityState,
    ConstraintType,
    LagCalendar,
    ProgressPolicy,
    RelationshipType,
    ScenarioContent,
    activity_state,
    format_instant,
)

__all__ = [
    "CPM_OPERATION_BUDGET",
    "CRITICAL_PATH_COUNT_CAP",
    "ENGINE_VERSION",
    "ISSUE_SEVERITY",
    "MAX_CRITICAL_PATHS",
    "MAX_CRITICAL_PATH_KEYS",
    "MAX_CYCLE_KEYS",
    "MAX_LISTED",
    "CpmActivityResult",
    "CpmIssue",
    "CpmIssueCode",
    "CpmIssueSeverity",
    "CpmRelationshipResult",
    "CpmResult",
    "CpmStatus",
    "CpmSummary",
    "result_document",
    "run_cpm",
]

ENGINE_VERSION: Final = "my-pa-cpm-v1"
#: Production budget; a request can never set it (section 3.11).
CPM_OPERATION_BUDGET: Final = 4_000_000
MAX_CRITICAL_PATHS: Final = 16
MAX_CRITICAL_PATH_KEYS: Final = 50_000
CRITICAL_PATH_COUNT_CAP: Final = 1_000_000
#: Issues and open ends listed (all are counted).
MAX_LISTED: Final = 1_000
MAX_CYCLE_KEYS: Final = 100


class CpmStatus(StrEnum):
    COMPUTED = "computed"
    REJECTED = "rejected"


class CpmIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class CpmIssueCode(StrEnum):
    """Section 3.10, closed (16), in table order (the sort order)."""

    EMPTY_NETWORK = "empty_network"
    UNKNOWN_CALENDAR = "unknown_calendar"
    DANGLING_RELATIONSHIP = "dangling_relationship"
    MISSING_DURATION = "missing_duration"
    CYCLE_DETECTED = "cycle_detected"
    HORIZON_EXCEEDED = "horizon_exceeded"
    OPERATION_BUDGET_EXCEEDED = "operation_budget_exceeded"
    OUT_OF_SEQUENCE = "out_of_sequence"
    CONSTRAINT_IGNORED_STARTED = "constraint_ignored_started"
    MANDATORY_CONSTRAINT_OVERRIDES_LOGIC = "mandatory_constraint_overrides_logic"
    MANDATORY_CONSTRAINT_BEFORE_DATA_DATE = "mandatory_constraint_before_data_date"
    START_NO_LATER_THAN_VIOLATED = "start_no_later_than_violated"
    FINISH_NO_LATER_THAN_VIOLATED = "finish_no_later_than_violated"
    MUST_FINISH_BY_VIOLATED = "must_finish_by_violated"
    RELATIONSHIP_VIOLATED = "relationship_violated"
    DANGLING_FINISH = "dangling_finish"


_ERRORS: Final = (
    CpmIssueCode.EMPTY_NETWORK,
    CpmIssueCode.UNKNOWN_CALENDAR,
    CpmIssueCode.DANGLING_RELATIONSHIP,
    CpmIssueCode.MISSING_DURATION,
    CpmIssueCode.CYCLE_DETECTED,
    CpmIssueCode.HORIZON_EXCEEDED,
    CpmIssueCode.OPERATION_BUDGET_EXCEEDED,
)
ISSUE_SEVERITY: Final = {
    code: CpmIssueSeverity.ERROR if code in _ERRORS else CpmIssueSeverity.WARNING
    for code in CpmIssueCode
}
_CODE_ORDER: Final = {code: index for index, code in enumerate(CpmIssueCode)}


@dataclass(frozen=True, slots=True)
class CpmIssue:
    code: CpmIssueCode
    activity_key: str | None = None
    pred: str | None = None
    succ: str | None = None

    @property
    def severity(self) -> CpmIssueSeverity:
        return ISSUE_SEVERITY[self.code]


def _nullable(value: str | None) -> tuple[int, str]:
    return (0, "") if value is None else (1, value)


def _issue_order(issue: CpmIssue) -> tuple[object, ...]:
    return (
        0 if issue.severity is CpmIssueSeverity.ERROR else 1,
        _CODE_ORDER[issue.code],
        _nullable(issue.activity_key),
        _nullable(issue.pred),
        _nullable(issue.succ),
    )


@dataclass(frozen=True, slots=True)
class CpmSummary:
    data_date: int
    project_finish: int | None
    must_finish_by: int | None
    activity_count: int
    relationship_count: int
    critical_count: int = 0
    negative_float_count: int = 0
    open_start_count: int = 0
    open_finish_count: int = 0
    critical_path_count: int = 0
    critical_paths_truncated: bool = False
    cycle: tuple[str, ...] | None = None
    cycle_length: int | None = None
    residual_count: int | None = None


@dataclass(frozen=True, slots=True)
class CpmActivityResult:
    key: str
    state: ActivityState
    topo_index: int
    early_start: int
    remaining_start: int | None
    early_finish: int
    late_start: int
    late_finish: int
    total_float_minutes: int | None
    free_float_minutes: int | None
    critical: bool


@dataclass(frozen=True, slots=True)
class CpmRelationshipResult:
    pred: str
    succ: str
    considered: bool
    slack_minutes: int | None
    driving: bool


@dataclass(frozen=True, slots=True)
class CpmResult:
    """One run's `schedule-cpm-result-v1` (section 3.11); label `server_computed`."""

    input_content_sha256: str
    status: CpmStatus
    summary: CpmSummary
    issue_counts: dict[CpmIssueCode, int]
    issues: tuple[CpmIssue, ...]
    open_starts: tuple[str, ...]
    open_finishes: tuple[str, ...]
    critical_paths: tuple[tuple[str, ...], ...]
    activities: tuple[CpmActivityResult, ...]
    relationships: tuple[CpmRelationshipResult, ...]
    engine_version: str = ENGINE_VERSION
    #: Operations the run counted (section 3.11); not part of the document.
    operations: int = 0


def _instant_or_none(value: int | None) -> str | None:
    return None if value is None else format_instant(value)


def result_document(result: CpmResult) -> dict[str, object]:
    """The canonical `schedule-cpm-result-v1` object of a run."""
    summary = result.summary
    return {
        "schema": RESULT_SCHEMA,
        "engine_version": result.engine_version,
        "input_content_sha256": result.input_content_sha256,
        "status": result.status.value,
        "summary": {
            "data_date": format_instant(summary.data_date),
            "project_finish": _instant_or_none(summary.project_finish),
            "must_finish_by": _instant_or_none(summary.must_finish_by),
            "activity_count": summary.activity_count,
            "relationship_count": summary.relationship_count,
            "critical_count": summary.critical_count,
            "negative_float_count": summary.negative_float_count,
            "open_start_count": summary.open_start_count,
            "open_finish_count": summary.open_finish_count,
            "critical_path_count": summary.critical_path_count,
            "critical_paths_truncated": summary.critical_paths_truncated,
            "cycle": None if summary.cycle is None else list(summary.cycle),
            "cycle_length": summary.cycle_length,
            "residual_count": summary.residual_count,
        },
        "issue_counts": {code.value: result.issue_counts[code] for code in CpmIssueCode},
        "issues": [
            {
                "code": issue.code.value,
                "severity": issue.severity.value,
                "activity_key": issue.activity_key,
                "pred": issue.pred,
                "succ": issue.succ,
            }
            for issue in result.issues
        ],
        "open_starts": list(result.open_starts),
        "open_finishes": list(result.open_finishes),
        "critical_paths": [list(path) for path in result.critical_paths],
        "activities": [
            {
                "key": item.key,
                "state": item.state.value,
                "topo_index": item.topo_index,
                "early_start": format_instant(item.early_start),
                "remaining_start": _instant_or_none(item.remaining_start),
                "early_finish": format_instant(item.early_finish),
                "late_start": format_instant(item.late_start),
                "late_finish": format_instant(item.late_finish),
                "total_float_minutes": item.total_float_minutes,
                "free_float_minutes": item.free_float_minutes,
                "critical": item.critical,
            }
            for item in result.activities
        ],
        "relationships": [
            {
                "pred": item.pred,
                "succ": item.succ,
                "considered": item.considered,
                "slack_minutes": item.slack_minutes,
                "driving": item.driving,
            }
            for item in result.relationships
        ],
    }


# --- the run --------------------------------------------------------------------------


class _RejectedError(Exception):
    """Stops a run: its issues (and cycle report) become the rejected result."""

    def __init__(
        self,
        issues: Sequence[CpmIssue],
        cycle: tuple[str, ...] | None = None,
        cycle_length: int | None = None,
        residual_count: int | None = None,
    ) -> None:
        super().__init__("rejected")
        self.issues = tuple(issues)
        self.cycle = cycle
        self.cycle_length = cycle_length
        self.residual_count = residual_count


_BUDGET_ISSUE: Final = CpmIssue(CpmIssueCode.OPERATION_BUDGET_EXCEEDED)


def _validation_issues(content: ScenarioContent) -> list[CpmIssue]:
    """Section 3.4: the first failing check's issues, else none."""
    if not content.activities:
        return [CpmIssue(CpmIssueCode.EMPTY_NETWORK)]
    calendars = {calendar.key for calendar in content.calendars}
    default = content.settings.default_calendar
    unknown = [
        CpmIssue(CpmIssueCode.UNKNOWN_CALENDAR, activity_key=activity.key)
        for activity in content.activities
        if (activity.calendar or default) not in calendars
    ]
    if unknown:
        return unknown
    keys = {activity.key for activity in content.activities}
    dangling = [
        CpmIssue(CpmIssueCode.DANGLING_RELATIONSHIP, pred=item.pred, succ=item.succ)
        for item in content.relationships
        if item.pred not in keys or item.succ not in keys
    ]
    if dangling:
        return dangling
    return [
        CpmIssue(CpmIssueCode.MISSING_DURATION, activity_key=activity.key)
        for activity in content.activities
        if activity.remaining_minutes is None
        and activity_state(activity) is not ActivityState.COMPLETE
    ]


class _Engine:
    """One run over a validated content. Indices are positions in key order."""

    def __init__(self, content: ScenarioContent, budget: int) -> None:
        self.content = content
        self.budget = budget
        self.operations = 0
        settings = content.settings
        self.data_date = content.data_date
        self.retained = settings.progress_policy is ProgressPolicy.RETAINED_LOGIC
        activities = content.activities
        self.keys = [activity.key for activity in activities]
        index = {key: position for position, key in enumerate(self.keys)}
        compiled: dict[str, CompiledCalendar] = {}

        def calendar_of(key: str) -> CompiledCalendar:
            if key not in compiled:
                source = next(item for item in content.calendars if item.key == key)
                compiled[key] = compile_calendar(source)
            return compiled[key]

        default = settings.default_calendar
        self.calendars = [calendar_of(activity.calendar or default) for activity in activities]
        self.states = [activity_state(activity) for activity in activities]
        self.durations = [
            0 if state is ActivityState.COMPLETE else activity.remaining_minutes or 0
            for activity, state in zip(activities, self.states, strict=True)
        ]
        self.constraints = [
            {item.type: item.at for item in activity.constraints} for activity in activities
        ]
        # Actual dates where progress gives them (unused, 0, where it does not).
        self.actual_start = [
            0 if activity.progress is None else activity.progress.actual_start
            for activity in activities
        ]
        self.actual_finish = [
            0
            if activity.progress is None or activity.progress.actual_finish is None
            else activity.progress.actual_finish
            for activity in activities
        ]
        relationships = content.relationships
        self.preds = [index[item.pred] for item in relationships]
        self.succs = [index[item.succ] for item in relationships]
        self.types = [item.type for item in relationships]
        self.lags = [item.lag_minutes for item in relationships]
        count = len(activities)
        # Relationships are sorted by (pred, succ), so each outgoing list is in
        # successor key order; incoming lists are sorted by predecessor key.
        self.outgoing: list[list[int]] = [[] for _ in range(count)]
        self.incoming: list[list[int]] = [[] for _ in range(count)]
        for position in range(len(relationships)):
            self.outgoing[self.preds[position]].append(position)
        for position in sorted(range(len(relationships)), key=lambda r: self.preds[r]):
            self.incoming[self.succs[position]].append(position)
        lag_calendar = settings.lag_calendar
        all_day = twenty_four_hour_calendar()
        self.lag_calendars = [
            self.calendars[self.preds[r]]
            if lag_calendar is LagCalendar.PREDECESSOR
            else self.calendars[self.succs[r]]
            if lag_calendar is LagCalendar.SUCCESSOR
            else all_day
            for r in range(len(relationships))
        ]
        self.warnings: list[CpmIssue] = []

    # --- counting and calendar calls ------------------------------------------------

    def tick(self) -> None:
        if self.operations == self.budget:
            raise _RejectedError([_BUDGET_ISSUE])
        self.operations += 1

    def _call(self, function: Callable[[], int], activity: int, relationship: int | None) -> int:
        self.tick()
        try:
            return function()
        except CalendarHorizonError:
            raise _RejectedError([self._horizon_issue(activity, relationship)]) from None

    def _horizon_issue(self, activity: int, relationship: int | None) -> CpmIssue:
        if relationship is None:
            return CpmIssue(CpmIssueCode.HORIZON_EXCEEDED, activity_key=self.keys[activity])
        return CpmIssue(
            CpmIssueCode.HORIZON_EXCEEDED,
            activity_key=self.keys[activity],
            pred=self.keys[self.preds[relationship]],
            succ=self.keys[self.succs[relationship]],
        )

    def advance(
        self, calendar: CompiledCalendar, t: int, d: int, j: int, r: int | None = None
    ) -> int:
        return self._call(lambda: _advance(calendar, t, d), j, r)

    def retreat(
        self, calendar: CompiledCalendar, t: int, d: int, j: int, r: int | None = None
    ) -> int:
        return self._call(lambda: _retreat(calendar, t, d), j, r)

    def shift(self, calendar: CompiledCalendar, t: int, lag: int, j: int, r: int) -> int:
        if lag >= 0:
            return self.advance(calendar, t, lag, j, r)
        return self.retreat(calendar, t, -lag, j, r)

    def snap(self, j: int, t: int) -> int:
        if self.durations[j] == 0:
            return t
        calendar = self.calendars[j]
        return self._call(lambda: _next_work(calendar, t), j, None)

    def snap_back(self, j: int, t: int) -> int:
        if self.durations[j] == 0:
            return t
        calendar = self.calendars[j]
        return self._call(lambda: _prev_end(calendar, t), j, None)

    def worked(self, calendar: CompiledCalendar, a: int, b: int) -> int:
        self.tick()
        return _working_minutes(calendar, a, b)

    # --- section 3.4: order and cycles --------------------------------------------------

    def topological_order(self) -> list[int]:
        count = len(self.keys)
        indegree = [len(self.incoming[j]) for j in range(count)]
        heap = [j for j in range(count) if indegree[j] == 0]
        heapq.heapify(heap)
        order: list[int] = []
        while heap:
            self.tick()
            j = heapq.heappop(heap)
            order.append(j)
            for r in self.outgoing[j]:
                self.tick()
                k = self.succs[r]
                indegree[k] -= 1
                if indegree[k] == 0:
                    heapq.heappush(heap, k)
        if len(order) < count:
            raise self._cycle(set(range(count)) - set(order))
        return order

    def _cycle(self, residual: set[int]) -> _RejectedError:
        walk = [min(residual)]
        seen = {walk[0]: 0}
        while True:
            current = walk[-1]
            predecessor = min(
                self.preds[r] for r in self.incoming[current] if self.preds[r] in residual
            )
            if predecessor in seen:
                segment = walk[seen[predecessor] :]
                break
            seen[predecessor] = len(walk)
            walk.append(predecessor)
        successor_order = segment[::-1]
        start = successor_order.index(min(successor_order))
        cycle = successor_order[start:] + successor_order[:start]
        return _RejectedError(
            [CpmIssue(CpmIssueCode.CYCLE_DETECTED)],
            cycle=tuple(self.keys[j] for j in cycle[:MAX_CYCLE_KEYS]),
            cycle_length=len(cycle),
            residual_count=len(residual),
        )

    # --- section 3.5: forward pass -------------------------------------------------------

    def considered(self, r: int) -> bool:
        state = self.states[self.succs[r]]
        if state is ActivityState.COMPLETE:
            return False
        return not (state is ActivityState.IN_PROGRESS and not self.retained)

    def _out_of_sequence(self, r: int) -> bool:
        i, k = self.preds[r], self.succs[r]
        state_i, state_k = self.states[i], self.states[k]
        if state_k is ActivityState.NOT_STARTED:
            return False
        kind = self.types[r]
        if kind is RelationshipType.FS:
            return state_i is not ActivityState.COMPLETE
        if kind is RelationshipType.SS:
            return state_i is ActivityState.NOT_STARTED
        if state_k is not ActivityState.COMPLETE:
            return False
        if kind is RelationshipType.FF:
            return state_i is not ActivityState.COMPLETE
        return state_i is ActivityState.NOT_STARTED

    def _relationship_issue(self, code: CpmIssueCode, r: int) -> CpmIssue:
        return CpmIssue(code, pred=self.keys[self.preds[r]], succ=self.keys[self.succs[r]])

    def forward(self, order: Sequence[int]) -> None:
        count = len(self.keys)
        self.es: list[int] = [0] * count
        # The remaining start; a complete activity's is its actual start
        # internally and null in the result.
        self.rs: list[int] = [0] * count
        self.ef: list[int] = [0] * count
        self.anchor: dict[int, int] = {}
        self.kept_pin = [False] * count
        for j in order:
            self.tick()
            state = self.states[j]
            wants_bounds = state is ActivityState.NOT_STARTED or (
                state is ActivityState.IN_PROGRESS and self.retained
            )
            bounds: list[int] = []
            for r in self.incoming[j]:
                self.tick()
                if self._out_of_sequence(r):
                    self.warnings.append(self._relationship_issue(CpmIssueCode.OUT_OF_SEQUENCE, r))
                if wants_bounds:
                    bounds.append(self._forward_bound(j, r))
            if state is ActivityState.COMPLETE:
                self._constraint_ignored(j)
                self.es[j] = self.rs[j] = self.actual_start[j]
                self.ef[j] = self.actual_finish[j]
                continue
            if state is ActivityState.IN_PROGRESS:
                self._forward_in_progress(j, bounds)
            else:
                self._forward_not_started(j, bounds)

    def _forward_bound(self, j: int, r: int) -> int:
        i = self.preds[r]
        kind = self.types[r]
        origin = self.ef[i] if kind in (RelationshipType.FS, RelationshipType.FF) else self.es[i]
        anchor = self.shift(self.lag_calendars[r], origin, self.lags[r], j, r)
        self.anchor[r] = anchor
        if kind in (RelationshipType.FS, RelationshipType.SS):
            return anchor
        return self.retreat(self.calendars[j], anchor, self.durations[j], j, r)

    def _constraint_ignored(self, j: int) -> None:
        if self.constraints[j]:
            self.warnings.append(
                CpmIssue(CpmIssueCode.CONSTRAINT_IGNORED_STARTED, activity_key=self.keys[j])
            )

    def _forward_in_progress(self, j: int, bounds: list[int]) -> None:
        self._constraint_ignored(j)
        remaining_start = self.snap(j, max([self.data_date, *bounds]))
        self.es[j] = self.actual_start[j]
        self.rs[j] = remaining_start
        self.ef[j] = self.advance(self.calendars[j], remaining_start, self.durations[j], j)

    def _forward_not_started(self, j: int, bounds: list[int]) -> None:
        constraints = self.constraints[j]
        calendar, duration, key = self.calendars[j], self.durations[j], self.keys[j]
        candidates = [self.data_date, *bounds]
        if ConstraintType.SNET in constraints:
            candidates.append(constraints[ConstraintType.SNET])
        if ConstraintType.FNET in constraints:
            candidates.append(self.retreat(calendar, constraints[ConstraintType.FNET], duration, j))
        x = self.snap(j, max(candidates))
        pin: int | None = None
        if ConstraintType.MSO in constraints:
            pin = constraints[ConstraintType.MSO]
        elif ConstraintType.MFO in constraints:
            pin = self.retreat(calendar, constraints[ConstraintType.MFO], duration, j)
        if pin is not None:
            if pin < self.data_date:
                self.warnings.append(
                    CpmIssue(CpmIssueCode.MANDATORY_CONSTRAINT_BEFORE_DATA_DATE, activity_key=key)
                )
            else:
                if x > pin:
                    self.warnings.append(
                        CpmIssue(
                            CpmIssueCode.MANDATORY_CONSTRAINT_OVERRIDES_LOGIC, activity_key=key
                        )
                    )
                x = pin
                self.kept_pin[j] = True
        self.es[j] = self.rs[j] = x
        self.ef[j] = self.advance(calendar, x, duration, j)
        if ConstraintType.SNLT in constraints and self.es[j] > constraints[ConstraintType.SNLT]:
            self.warnings.append(
                CpmIssue(CpmIssueCode.START_NO_LATER_THAN_VIOLATED, activity_key=key)
            )
        if ConstraintType.FNLT in constraints and self.ef[j] > constraints[ConstraintType.FNLT]:
            self.warnings.append(
                CpmIssue(CpmIssueCode.FINISH_NO_LATER_THAN_VIOLATED, activity_key=key)
            )

    # --- section 3.6: backward pass --------------------------------------------------------

    def backward(self, order: Sequence[int], project_finish: int) -> None:
        count = len(self.keys)
        self.ls: list[int] = [0] * count
        self.lf: list[int] = [0] * count
        must_finish_by = self.content.settings.must_finish_by
        for j in reversed(order):
            self.tick()
            state = self.states[j]
            if state is ActivityState.COMPLETE:
                self.ls[j], self.lf[j] = self.es[j], self.ef[j]
                continue
            calendar, duration = self.calendars[j], self.durations[j]
            bounds: list[int] = []
            for r in self.outgoing[j]:
                self.tick()
                if not self.considered(r):
                    continue
                bound = self._backward_bound(j, r, state)
                if bound is not None:
                    bounds.append(bound)
            if not bounds:
                bounds.append(project_finish if must_finish_by is None else must_finish_by)
            constraints = self.constraints[j]
            if state is ActivityState.NOT_STARTED:
                if ConstraintType.FNLT in constraints:
                    bounds.append(constraints[ConstraintType.FNLT])
                if ConstraintType.SNLT in constraints:
                    bounds.append(
                        self.advance(calendar, constraints[ConstraintType.SNLT], duration, j)
                    )
            y = self.snap_back(j, min(bounds))
            if self.kept_pin[j]:
                if ConstraintType.MFO in constraints:
                    y = constraints[ConstraintType.MFO]
                else:
                    y = self.advance(calendar, constraints[ConstraintType.MSO], duration, j)
            self.lf[j] = y
            self.ls[j] = self.retreat(calendar, y, duration, j)

    def _backward_bound(self, j: int, r: int, state: ActivityState) -> int | None:
        k = self.succs[r]
        kind = self.types[r]
        lag_calendar, lag = self.lag_calendars[r], self.lags[r]
        if kind is RelationshipType.FS:
            return self.shift(lag_calendar, self.ls[k], -lag, j, r)
        if kind is RelationshipType.FF:
            return self.shift(lag_calendar, self.lf[k], -lag, j, r)
        if state is ActivityState.IN_PROGRESS:
            return None
        origin = self.ls[k] if kind is RelationshipType.SS else self.lf[k]
        shifted = self.shift(lag_calendar, origin, -lag, j, r)
        return self.advance(self.calendars[j], shifted, self.durations[j], j, r)

    # --- section 3.7: floats ------------------------------------------------------------------

    def slack(self, order: Sequence[int]) -> None:
        count = len(self.keys)
        self.total_float: list[int | None] = [None] * count
        self.free_float: list[int | None] = [None] * count
        self.relationship_slack: list[int | None] = [None] * len(self.preds)
        for j in order:
            self.tick()
            outgoing_slack: list[int] = []
            for r in self.outgoing[j]:
                self.tick()
                if not self.considered(r):
                    continue
                k = self.succs[r]
                kind = self.types[r]
                starts = kind in (RelationshipType.FS, RelationshipType.SS)
                target = self.rs[k] if starts else self.ef[k]
                value = self.worked(self.calendars[k], self.anchor[r], target)
                self.relationship_slack[r] = value
                outgoing_slack.append(value)
                if value < 0:
                    self.warnings.append(
                        self._relationship_issue(CpmIssueCode.RELATIONSHIP_VIOLATED, r)
                    )
            if self.states[j] is ActivityState.COMPLETE:
                continue
            total = self.worked(self.calendars[j], self.ef[j], self.lf[j])
            self.total_float[j] = total
            self.free_float[j] = min([total, *outgoing_slack])

    # --- section 3.8: critical paths ------------------------------------------------------------

    def critical_paths(
        self, order: Sequence[int], critical: list[bool]
    ) -> tuple[tuple[tuple[str, ...], ...], int]:
        count = len(self.keys)
        edges: list[list[int]] = [[] for _ in range(count)]
        has_incoming = [False] * count
        for r in range(len(self.preds)):
            i, k = self.preds[r], self.succs[r]
            if critical[i] and critical[k] and self.relationship_slack[r] == 0:
                edges[i].append(k)
                has_incoming[k] = True
        starts = [j for j in range(count) if critical[j] and not has_incoming[j]]
        paths: list[tuple[str, ...]] = []
        emitted_keys = 0
        stopped = False

        def emit(path: list[int]) -> bool:
            nonlocal emitted_keys
            if emitted_keys + len(path) > MAX_CRITICAL_PATH_KEYS:
                return False
            paths.append(tuple(self.keys[node] for node in path))
            emitted_keys += len(path)
            return len(paths) < MAX_CRITICAL_PATHS

        for start in starts:
            self.tick()
            path = [start]
            if not edges[start]:
                if not emit(path):
                    stopped = True
                    break
                continue
            stack = [iter(edges[start])]
            while stack and not stopped:
                following = next(stack[-1], None)
                if following is None:
                    stack.pop()
                    path.pop()
                    continue
                self.tick()
                path.append(following)
                if edges[following]:
                    stack.append(iter(edges[following]))
                    continue
                if not emit(path):
                    stopped = True
                path.pop()
            if stopped:
                break
        ways = [0] * count
        for j in reversed(order):
            if not critical[j]:
                continue
            self.tick()
            if not edges[j]:
                ways[j] = 1
            else:
                ways[j] = min(CRITICAL_PATH_COUNT_CAP, sum(ways[k] for k in edges[j]))
        total = min(CRITICAL_PATH_COUNT_CAP, sum(ways[j] for j in starts))
        return tuple(paths), total

    # --- the whole run ------------------------------------------------------------------------

    def compute(self, digest: str) -> CpmResult:
        content = self.content
        order = self.topological_order()
        self.forward(order)
        project_finish = max(self.ef)
        self.backward(order, project_finish)
        self.slack(order)
        threshold = content.settings.critical_float_threshold_minutes
        count = len(self.keys)
        critical = [total is not None and total <= threshold for total in self.total_float]
        paths, path_count = self.critical_paths(order, critical)
        for j in range(count):
            outgoing = self.outgoing[j]
            if (
                self.states[j] is not ActivityState.COMPLETE
                and outgoing
                and all(
                    self.types[r] in (RelationshipType.SS, RelationshipType.SF) for r in outgoing
                )
            ):
                self.warnings.append(
                    CpmIssue(CpmIssueCode.DANGLING_FINISH, activity_key=self.keys[j])
                )
        must_finish_by = content.settings.must_finish_by
        if must_finish_by is not None and project_finish > must_finish_by:
            self.warnings.append(CpmIssue(CpmIssueCode.MUST_FINISH_BY_VIOLATED))
        topo_index = [0] * count
        for position, j in enumerate(order):
            topo_index[j] = position
        open_starts = [self.keys[j] for j in range(count) if not self.incoming[j]]
        open_finishes = [self.keys[j] for j in range(count) if not self.outgoing[j]]
        issues = sorted(self.warnings, key=_issue_order)
        activities = tuple(
            CpmActivityResult(
                key=self.keys[j],
                state=self.states[j],
                topo_index=topo_index[j],
                early_start=self.es[j],
                remaining_start=None if self.states[j] is ActivityState.COMPLETE else self.rs[j],
                early_finish=self.ef[j],
                late_start=self.ls[j],
                late_finish=self.lf[j],
                total_float_minutes=self.total_float[j],
                free_float_minutes=self.free_float[j],
                critical=critical[j],
            )
            for j in range(count)
        )
        relationships = tuple(
            CpmRelationshipResult(
                pred=self.keys[self.preds[r]],
                succ=self.keys[self.succs[r]],
                considered=self.considered(r),
                slack_minutes=self.relationship_slack[r],
                driving=self.relationship_slack[r] == 0,
            )
            for r in range(len(self.preds))
        )
        summary = CpmSummary(
            data_date=content.data_date,
            project_finish=project_finish,
            must_finish_by=must_finish_by,
            activity_count=count,
            relationship_count=len(self.preds),
            critical_count=sum(critical),
            negative_float_count=sum(
                1 for value in self.total_float if value is not None and value < 0
            ),
            open_start_count=len(open_starts),
            open_finish_count=len(open_finishes),
            critical_path_count=path_count,
            critical_paths_truncated=path_count > len(paths),
        )
        return CpmResult(
            input_content_sha256=digest,
            status=CpmStatus.COMPUTED,
            summary=summary,
            issue_counts=_issue_counts(issues),
            issues=tuple(issues[:MAX_LISTED]),
            open_starts=tuple(open_starts[:MAX_LISTED]),
            open_finishes=tuple(open_finishes[:MAX_LISTED]),
            critical_paths=paths,
            activities=activities,
            relationships=relationships,
            operations=self.operations,
        )


def _issue_counts(issues: Sequence[CpmIssue]) -> dict[CpmIssueCode, int]:
    counts = dict.fromkeys(CpmIssueCode, 0)
    for issue in issues:
        counts[issue.code] += 1
    return counts


def _rejected(
    content: ScenarioContent, digest: str, rejection: _RejectedError, operations: int
) -> CpmResult:
    issues = sorted(rejection.issues, key=_issue_order)
    return CpmResult(
        input_content_sha256=digest,
        status=CpmStatus.REJECTED,
        summary=CpmSummary(
            data_date=content.data_date,
            project_finish=None,
            must_finish_by=content.settings.must_finish_by,
            activity_count=len(content.activities),
            relationship_count=len(content.relationships),
            cycle=rejection.cycle,
            cycle_length=rejection.cycle_length,
            residual_count=rejection.residual_count,
        ),
        issue_counts=_issue_counts(issues),
        issues=tuple(issues[:MAX_LISTED]),
        open_starts=(),
        open_finishes=(),
        critical_paths=(),
        activities=(),
        relationships=(),
        operations=operations,
    )


def run_cpm(content: ScenarioContent, *, operation_budget: int = CPM_OPERATION_BUDGET) -> CpmResult:
    """Compute one content under `my-pa-cpm-v1` (section 3). Never raises for content."""
    if type(operation_budget) is not int or operation_budget < 0:
        raise ValueError("the operation budget is a non-negative integer")
    if not isinstance(content, ScenarioContent):
        raise ValueError("run_cpm computes a ScenarioContent")
    digest = content_sha256(content)
    issues = _validation_issues(content)
    if issues:
        return _rejected(content, digest, _RejectedError(issues), 0)
    engine = _Engine(content, operation_budget)
    try:
        return engine.compute(digest)
    except _RejectedError as rejection:
        return _rejected(content, digest, rejection, engine.operations)
