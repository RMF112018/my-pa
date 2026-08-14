"""Task and Commitment values: lifecycle, dates, recurrence, and commitments.

Nothing here reads a clock, a store, or a principal from a payload. Callers
supply identity, times, and the intended next state; this module refuses
impossible combinations rather than guessing.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import IntEnum, StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc

__all__ = [
    "ALLOWED_TRANSITIONS",
    "IDEMPOTENCY_KEY_PATTERN",
    "MAX_DESCRIPTION_CHARACTERS",
    "MAX_SUMMARY_CHARACTERS",
    "MAX_TITLE_CHARACTERS",
    "AcceptanceKind",
    "Commitment",
    "CommitmentDirection",
    "CommitmentState",
    "ContextLinkKind",
    "ContinuityEvidenceState",
    "RecurrenceFrequency",
    "RecurrenceRule",
    "Task",
    "TaskContextLink",
    "TaskError",
    "TaskOrigin",
    "TaskPriority",
    "TaskRevision",
    "TaskRole",
    "TaskState",
    "TemporalFields",
    "Weekday",
    "can_transition",
    "next_occurrence",
    "normalize_priority",
    "occurrence_key_for",
    "validate_temporal_pair",
]

MAX_TITLE_CHARACTERS: Final = 256
MAX_DESCRIPTION_CHARACTERS: Final = 8000
MAX_SUMMARY_CHARACTERS: Final = 512
IDEMPOTENCY_KEY_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{8,128}\Z")

_OPTIONAL_PREFIX: Final = re.compile(r"\A(per|prj|sit)_[A-Za-z0-9]{8,64}\Z")


class TaskError(ValueError):
    """A task or commitment value refused to exist. Names the rule, never the value."""


class TaskState(StrEnum):
    """Execution lifecycle. Archive, schedule, and defer are orthogonal."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskRole(StrEnum):
    """What kind of work the Task is, not where it sits in the lifecycle."""

    ACTION = "action"
    FOLLOW_UP = "follow_up"
    REVIEW = "review"
    PREPARE = "prepare"


class TaskPriority(StrEnum):
    """Principal-assigned rank. Attention ranking must not write this field."""

    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


class RecurrenceFrequency(StrEnum):
    """MVP recurrences. Exotic calendar expressions are out of scope."""

    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKLY = "weekly"
    SELECTED_WEEKDAYS = "selected_weekdays"
    MONTHLY = "monthly"


class Weekday(IntEnum):
    """Monday-first weekday, matching ``date.weekday()``."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class CommitmentDirection(StrEnum):
    """Who is entitled to expect the obligation."""

    OWED_BY_PRINCIPAL = "owed_by_principal"
    OWED_TO_PRINCIPAL = "owed_to_principal"


class CommitmentState(StrEnum):
    """Commitment lifecycle. Independent of any linked Task."""

    OPEN = "open"
    CLOSED = "closed"


class ContinuityEvidenceState(StrEnum):
    """Whether the record is accepted product state or still a proposal."""

    ACCEPTED = "accepted"
    PROPOSED = "proposed"


class AcceptanceKind(StrEnum):
    """How an accepted Task became accepted.

    ``direct_principal`` is a durable receipt that the human instructed the
    write. ``review`` names a real review decision. ``none`` is the proposed
    state. There is no fake review identifier on the direct path.
    """

    DIRECT_PRINCIPAL = "direct_principal"
    REVIEW = "review"
    NONE = "none"


class TaskOrigin(StrEnum):
    """What produced this revision."""

    PRINCIPAL_DIRECT = "principal_direct"
    REVIEW_PROMOTION = "review_promotion"
    SYSTEM_RECURRENCE = "system_recurrence"


class ContextLinkKind(StrEnum):
    """Typed context a Task may cite. No foreign key is implied."""

    PERSON = "person"
    PROJECT = "project"
    SITUATION = "situation"
    COMMITMENT = "commitment"
    CAPTURE = "capture"
    PROPOSAL = "proposal"
    REVIEW_DECISION = "review_decision"
    SOURCE_EVIDENCE = "source_evidence"
    MEETING = "meeting"


ALLOWED_TRANSITIONS: Final[dict[TaskState, frozenset[TaskState]]] = {
    TaskState.OPEN: frozenset(
        {
            TaskState.IN_PROGRESS,
            TaskState.WAITING,
            TaskState.BLOCKED,
            TaskState.COMPLETED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.IN_PROGRESS: frozenset(
        {
            TaskState.OPEN,
            TaskState.WAITING,
            TaskState.BLOCKED,
            TaskState.COMPLETED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.WAITING: frozenset(
        {
            TaskState.OPEN,
            TaskState.IN_PROGRESS,
            TaskState.BLOCKED,
            TaskState.COMPLETED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.BLOCKED: frozenset(
        {
            TaskState.OPEN,
            TaskState.IN_PROGRESS,
            TaskState.WAITING,
            TaskState.COMPLETED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.COMPLETED: frozenset({TaskState.OPEN}),
    TaskState.CANCELLED: frozenset({TaskState.OPEN}),
}

TERMINAL_STATES: Final[frozenset[TaskState]] = frozenset({TaskState.COMPLETED, TaskState.CANCELLED})


def can_transition(current: TaskState, target: TaskState) -> bool:
    """Whether ``current`` may move to ``target`` in one recorded step."""
    return target in ALLOWED_TRANSITIONS[current]


def normalize_priority(value: str | TaskPriority) -> TaskPriority:
    """Map a Principal alias or canonical token onto ``TaskPriority``.

    Unknown tokens are refused rather than defaulted: inventing P3 from a
    misspelling would silently mis-rank work.
    """
    if isinstance(value, TaskPriority):
        return value
    if not isinstance(value, str):
        raise TaskError("priority must be a string")
    token = value.strip().lower()
    aliases = {
        "urgent": TaskPriority.P1,
        "p1": TaskPriority.P1,
        "high": TaskPriority.P2,
        "p2": TaskPriority.P2,
        "normal": TaskPriority.P3,
        "default": TaskPriority.P3,
        "p3": TaskPriority.P3,
        "low": TaskPriority.P4,
        "p4": TaskPriority.P4,
    }
    try:
        return aliases[token]
    except KeyError:
        raise TaskError("priority is not a recognized alias or canonical value") from None


@dataclass(frozen=True, slots=True)
class TemporalFields:
    """One date-only field XOR one instant, plus the timezone that interprets it."""

    date_only: date | None
    at: datetime | None
    timezone: str | None

    def __post_init__(self) -> None:
        validate_temporal_pair(self.date_only, self.at, self.timezone)


def validate_temporal_pair(
    date_only: date | None, at: datetime | None, timezone: str | None
) -> None:
    """Refuse both a date and an instant, and refuse a naive instant.

    Date-only stays date-only. An instant is stored UTC; ``timezone`` is the
    IANA zone the Principal used to interpret wall time, not a second clock.
    """
    if date_only is not None and at is not None:
        raise TaskError("a date-only field and an instant cannot both be set")
    if at is not None:
        try:
            ensure_utc(at)
        except NaiveDatetimeError as exc:
            raise TaskError("an instant must be timezone-aware") from exc
    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except (KeyError, ValueError) as exc:
            raise TaskError("timezone must be a valid IANA name") from exc


def _bounded_text(value: str, *, name: str, ceiling: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskError(f"{name} must be a non-empty string")
    stripped = value.strip()
    if len(stripped) > ceiling:
        raise TaskError(f"{name} exceeds the stored bound")
    return stripped


def _optional_context_id(value: str | None, *, kind: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _OPTIONAL_PREFIX.fullmatch(value):
        raise TaskError(f"{kind} must be an opaque prefixed identifier")
    expected = {"person": "per", "project": "prj", "situation": "sit"}[kind]
    if not value.startswith(f"{expected}_"):
        raise TaskError(f"{kind} must use its own prefix")
    return value


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    """A durable series definition, independent of any one occurrence Task."""

    recurrence_id: str
    principal_id: str
    frequency: RecurrenceFrequency
    timezone: str
    interval: int = 1
    weekdays: frozenset[Weekday] = frozenset()
    start_date: date | None = None
    start_at: datetime | None = None
    series_title: str = ""

    def __post_init__(self) -> None:
        validate_identifier(self.recurrence_id, IdKind.TASK_RECURRENCE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.interval < 1:
            raise TaskError("recurrence interval must be at least one")
        validate_temporal_pair(self.start_date, self.start_at, self.timezone)
        if self.start_date is None and self.start_at is None:
            raise TaskError("a recurrence must name a start date or instant")
        selected = self.frequency is RecurrenceFrequency.SELECTED_WEEKDAYS
        weekly = self.frequency is RecurrenceFrequency.WEEKLY
        if selected and not self.weekdays:
            raise TaskError("selected weekdays require at least one weekday")
        if weekly and len(self.weekdays) != 1:
            raise TaskError("weekly recurrence names exactly one weekday")
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
        if self.series_title:
            object.__setattr__(
                self,
                "series_title",
                _bounded_text(self.series_title, name="title", ceiling=MAX_TITLE_CHARACTERS),
            )


def occurrence_key_for(when: date | datetime, timezone: str) -> str:
    """Stable occurrence identity in the series timezone, never an invented midnight."""
    zone = ZoneInfo(timezone)
    if isinstance(when, datetime):
        local = ensure_utc(when).astimezone(zone)
        return local.date().isoformat()
    return when.isoformat()


def next_occurrence(
    rule: RecurrenceRule, *, after: date | datetime | None = None
) -> date | datetime:
    """The next actionable occurrence strictly after ``after``, or the start.

    Wall-clock times are interpreted in ``rule.timezone``. A civil time that
    falls into a DST spring-forward gap is moved forward to the first representable
    instant; a fall-back fold uses the later (standard-time) occurrence.
    """
    zone = ZoneInfo(rule.timezone)
    start = _local_anchor(rule, zone)
    if after is None:
        cursor = start if _matches(start, rule) else _advance(start, rule)
    else:
        cursor = _advance_past(_as_local(after, zone), start, rule)
    return _to_stored(cursor, rule, zone)


def _local_anchor(rule: RecurrenceRule, zone: ZoneInfo) -> datetime:
    if rule.start_at is not None:
        return ensure_utc(rule.start_at).astimezone(zone)
    if rule.start_date is None:
        raise TaskError("a recurrence must name a start date or instant")
    return datetime.combine(rule.start_date, time(0, 0), tzinfo=zone)


def _as_local(value: date | datetime, zone: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value).astimezone(zone)
    return datetime.combine(value, time(0, 0), tzinfo=zone)


def _matches(moment: datetime, rule: RecurrenceRule) -> bool:
    weekday = Weekday(moment.weekday())
    if rule.frequency is RecurrenceFrequency.DAILY:
        return True
    if rule.frequency in {RecurrenceFrequency.WEEKDAYS, RecurrenceFrequency.SELECTED_WEEKDAYS}:
        return weekday in rule.weekdays
    if rule.frequency is RecurrenceFrequency.WEEKLY:
        return weekday in rule.weekdays
    return True


def _civil(moment: datetime, delta: timedelta) -> datetime:
    """Advance by civil time so DST gaps do not invent a different wall hour."""
    naive = moment.replace(tzinfo=None) + delta
    return datetime(
        naive.year,
        naive.month,
        naive.day,
        naive.hour,
        naive.minute,
        naive.second,
        naive.microsecond,
        tzinfo=moment.tzinfo,
        fold=0,
    )


def _advance(moment: datetime, rule: RecurrenceRule) -> datetime:
    if rule.frequency is RecurrenceFrequency.MONTHLY:
        return _add_months(moment, rule.interval)
    if rule.frequency is RecurrenceFrequency.WEEKLY:
        return _civil(moment, timedelta(days=7 * rule.interval))
    if rule.frequency is RecurrenceFrequency.DAILY:
        return _civil(moment, timedelta(days=rule.interval))
    step = _civil(moment, timedelta(days=1))
    while not _matches(step, rule):
        step = _civil(step, timedelta(days=1))
    return step


def _advance_past(after: datetime, start: datetime, rule: RecurrenceRule) -> datetime:
    cursor = start
    if after < start and _matches(start, rule):
        return start
    guard = 0
    while cursor.date() <= after.date() or not _matches(cursor, rule):
        nxt = _advance(cursor, rule)
        if nxt <= cursor:
            raise TaskError("recurrence failed to advance")
        cursor = nxt
        guard += 1
        if guard > 4000:
            raise TaskError("recurrence search exceeded its bound")
        if cursor > after and _matches(cursor, rule):
            break
    return cursor


def _add_months(moment: datetime, months: int) -> datetime:
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    day = min(moment.day, last)
    naive = moment.replace(tzinfo=None, year=year, month=month, day=day)
    return datetime(
        naive.year,
        naive.month,
        naive.day,
        naive.hour,
        naive.minute,
        naive.second,
        naive.microsecond,
        tzinfo=moment.tzinfo,
        fold=0,
    )


def _to_stored(moment: datetime, rule: RecurrenceRule, zone: ZoneInfo) -> date | datetime:
    if rule.start_at is None:
        return moment.date()
    localized = datetime(
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond,
        tzinfo=zone,
        fold=0,
    )
    return localized.astimezone(ZoneInfo("UTC"))


@dataclass(frozen=True, slots=True)
class Task:
    """One executable action the Principal holds."""

    task_id: str
    principal_id: str
    title: str
    state: TaskState
    task_role: TaskRole
    priority: TaskPriority
    evidence_state: ContinuityEvidenceState
    acceptance_kind: AcceptanceKind
    current_version: int
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    accepted_by_review_decision_id: str | None = None
    origin_evidence_ref: str | None = None
    due_date: date | None = None
    due_at: datetime | None = None
    due_timezone: str | None = None
    scheduled_date: date | None = None
    scheduled_at: datetime | None = None
    deferred_until: datetime | None = None
    archived_at: datetime | None = None
    recurrence_id: str | None = None
    occurrence_key: str | None = None
    project_id: str | None = None
    situation_id: str | None = None
    person_id: str | None = None
    closed_at: datetime | None = None
    closure_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.task_id, IdKind.TASK)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        object.__setattr__(
            self, "title", _bounded_text(self.title, name="title", ceiling=MAX_TITLE_CHARACTERS)
        )
        if self.description is not None:
            object.__setattr__(
                self,
                "description",
                _bounded_text(
                    self.description, name="description", ceiling=MAX_DESCRIPTION_CHARACTERS
                ),
            )
        if self.current_version < 1:
            raise TaskError("task version starts at one")
        validate_temporal_pair(self.due_date, self.due_at, self.due_timezone)
        validate_temporal_pair(self.scheduled_date, self.scheduled_at, self.due_timezone)
        if self.scheduled_date is not None and self.scheduled_at is not None:
            raise TaskError("scheduled date and instant cannot both be set")
        if self.deferred_until is not None:
            try:
                ensure_utc(self.deferred_until)
            except NaiveDatetimeError as exc:
                raise TaskError("deferred_until must be timezone-aware") from exc
        if self.archived_at is not None:
            ensure_utc(self.archived_at)
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        if (self.state in TERMINAL_STATES) is not (self.closed_at is not None):
            raise TaskError("a terminal task records closed_at and an open task does not")
        if self.recurrence_id is not None:
            validate_identifier(self.recurrence_id, IdKind.TASK_RECURRENCE)
        if (self.recurrence_id is None) is not (self.occurrence_key is None):
            raise TaskError("an occurrence names both a recurrence and an occurrence key")
        if self.accepted_by_review_decision_id is not None:
            validate_identifier(self.accepted_by_review_decision_id, IdKind.REVIEW_DECISION)
        if self.acceptance_kind is AcceptanceKind.REVIEW and (
            self.accepted_by_review_decision_id is None
        ):
            raise TaskError("review acceptance names the review decision")
        if self.acceptance_kind is AcceptanceKind.DIRECT_PRINCIPAL and (
            self.accepted_by_review_decision_id is not None
        ):
            raise TaskError("direct Principal acceptance does not invent a review decision")
        if self.evidence_state is ContinuityEvidenceState.PROPOSED:
            if self.acceptance_kind is not AcceptanceKind.NONE:
                raise TaskError("a proposed task has no acceptance")
        else:
            if self.acceptance_kind is AcceptanceKind.NONE:
                raise TaskError("an accepted task records how it was accepted")
        object.__setattr__(self, "person_id", _optional_context_id(self.person_id, kind="person"))
        object.__setattr__(
            self, "project_id", _optional_context_id(self.project_id, kind="project")
        )
        object.__setattr__(
            self, "situation_id", _optional_context_id(self.situation_id, kind="situation")
        )
        if self.origin_evidence_ref is not None and len(self.origin_evidence_ref) > 128:
            raise TaskError("origin evidence ref exceeds the stored bound")

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transitioned(self, target: TaskState, *, at: datetime, version: int) -> Task:
        """Return a copy in ``target`` if the graph allows it."""
        if not can_transition(self.state, target):
            raise TaskError("the requested transition is not allowed")
        if version != self.current_version:
            raise TaskError("the expected version does not match")
        closed = at if target in TERMINAL_STATES else None
        return Task(
            task_id=self.task_id,
            principal_id=self.principal_id,
            title=self.title,
            description=self.description,
            state=target,
            task_role=self.task_role,
            priority=self.priority,
            evidence_state=self.evidence_state,
            acceptance_kind=self.acceptance_kind,
            accepted_by_review_decision_id=self.accepted_by_review_decision_id,
            origin_evidence_ref=self.origin_evidence_ref,
            due_date=self.due_date,
            due_at=self.due_at,
            due_timezone=self.due_timezone,
            scheduled_date=self.scheduled_date,
            scheduled_at=self.scheduled_at,
            deferred_until=self.deferred_until,
            archived_at=self.archived_at,
            current_version=self.current_version + 1,
            recurrence_id=self.recurrence_id,
            occurrence_key=self.occurrence_key,
            project_id=self.project_id,
            situation_id=self.situation_id,
            person_id=self.person_id,
            opened_at=self.opened_at,
            closed_at=closed,
            closure_evidence_ref=self.closure_evidence_ref,
            created_at=self.created_at,
            updated_at=at,
        )


@dataclass(frozen=True, slots=True)
class TaskRevision:
    """Append-only snapshot of one committed mutation."""

    revision_id: str
    task_id: str
    principal_id: str
    version: int
    origin: TaskOrigin
    state: TaskState
    priority: TaskPriority
    recorded_at: datetime
    title: str
    prior_revision_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.revision_id, IdKind.TASK_REVISION)
        validate_identifier(self.task_id, IdKind.TASK)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.prior_revision_id is not None:
            validate_identifier(self.prior_revision_id, IdKind.TASK_REVISION)
        if self.version < 1:
            raise TaskError("revision version starts at one")
        ensure_utc(self.recorded_at)


@dataclass(frozen=True, slots=True)
class TaskContextLink:
    """A typed citation from a Task to another record. No foreign key."""

    link_id: str
    task_id: str
    principal_id: str
    kind: ContextLinkKind
    target_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.link_id, IdKind.TASK_LINK)
        validate_identifier(self.task_id, IdKind.TASK)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.target_id, str) or not self.target_id:
            raise TaskError("a context link names a target")


@dataclass(frozen=True, slots=True)
class Commitment:
    """A social obligation. Independent of any Task that chases it."""

    commitment_id: str
    principal_id: str
    counterparty_person_id: str
    direction: CommitmentDirection
    summary: str
    state: CommitmentState
    evidence_state: ContinuityEvidenceState
    current_version: int
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    origin_evidence_ref: str | None = None
    due_date: date | None = None
    due_at: datetime | None = None
    due_timezone: str | None = None
    closed_at: datetime | None = None
    closure_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.commitment_id, IdKind.COMMITMENT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.counterparty_person_id, IdKind.PERSON)
        object.__setattr__(
            self,
            "summary",
            _bounded_text(self.summary, name="summary", ceiling=MAX_SUMMARY_CHARACTERS),
        )
        if self.current_version < 1:
            raise TaskError("commitment version starts at one")
        validate_temporal_pair(self.due_date, self.due_at, self.due_timezone)
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        if (self.state is CommitmentState.CLOSED) is not (self.closed_at is not None):
            raise TaskError("a closed commitment records closed_at")
