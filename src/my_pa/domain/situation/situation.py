"""The R5 continuity surface: Situation, Frame, Trace, Project, and PulseItem.

These are the durable objects the daily-orientation, project-continuity, and
briefing workflows (WF-01, WF-12, WF-10, WF-15) operate over. Each is defined by
the canonical object model:

- **Situation** — "purposeful operational context referencing one or more
  objects; does not own them." It carries `object_refs` (opaque references to
  the objects it is about) but never owns those objects, so closing a Situation
  never deletes what it referenced (WF-18).
- **Frame** — "current/saved view of what matters, evidence, alternatives,
  obligations, uncertainty, and next authority point." A Frame belongs to one
  Situation and is the reviewer's working view within it.
- **Trace** — "derived source-linked temporal reconstruction; not source
  evidence." A Trace reconstructs one object over a time range from the source
  events it cites and exposes the gaps it could not fill (WF-15). It is a
  projection and is never authoritative.
- **Project** — "durable work context with participants, sources, Situations,
  ..." A Project groups Situations and carries its participant set.
- **PulseItem** — "derived attention recommendation with reason, consequence,
  evidence, uncertainty, next step." A Pulse item is generated only from
  *accepted* state — `accepted_only` is structurally pinned true (the migration
  CHECK `pulse_reads_only_accepted_records`) so the WP-06 criterion "Today/Pulse
  read only accepted records" cannot be weakened by a writer.

**Every object carries `principal_id`.** These surfaces are read by Today/Pulse
and by the relationship/project briefing, all of which must be strictly
principal-scoped (invariant 11: `principal_id` is a mandatory predicate on every
read path). A Frame carries `principal_id` explicitly even though it inherits
its Situation's Principal, so a query can enforce the partition without joining
back to the parent — the same reasoning the WP-05 review partition used for span
tables.

`RelationshipEvent` and `RelationshipEventType` are re-exported from
`domain.relationship.event`; they are relationship-domain facts, not continuity
views, but a caller building a Project/Relationship timeline reaches them
alongside these objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "Frame",
    "FrameState",
    "Project",
    "ProjectState",
    "PulseItem",
    "PulseItemType",
    "PulseReasonCode",
    "Situation",
    "SituationState",
    "Trace",
]


class SituationState(StrEnum):
    """Where a Situation is in its lifecycle. Frozen in the `state` CHECK."""

    OPEN = "open"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class FrameState(StrEnum):
    """Whether a Frame is the current working view, a saved one, or archived."""

    CURRENT = "current"
    SAVED = "saved"
    ARCHIVED = "archived"


class ProjectState(StrEnum):
    """Whether a Project is active, paused, or closed."""

    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CLOSED = "closed"


class PulseItemType(StrEnum):
    """What kind of accepted record a Pulse item points at.

    Every member names a record class that only exists once *accepted*, which is
    the type-level half of the `accepted_only` gate: a Pulse item can only be
    about a commitment, decision, task, observation, relationship event, or
    situation that a human has already promoted.
    """

    COMMITMENT = "commitment"
    DECISION = "decision"
    TASK = "task"
    OBSERVATION = "observation"
    RELATIONSHIP_EVENT = "relationship_event"
    SITUATION = "situation"


class PulseReasonCode(StrEnum):
    """Why an item is on the Pulse *now*, from a closed vocabulary (WP-11).

    **This is the field that separates a Pulse from an activity feed.** A feed
    surfaces an item because something happened to it; a Pulse surfaces an item
    because a named, checkable condition holds about it right now. Every member
    here names such a condition, and each one is computed from evidence the
    reader can go and look at — a due moment that has passed, a due moment that
    is close, a decision waiting on a named authority point, an obligation on a
    Situation's current Frame that is still unmet.

    Closed, and closed in the schema too
    (`knowledge.pulse_items.a_pulse_reason_code_is_known`), because an open
    vocabulary would let "recently updated" be written here and the distinction
    would be gone in one commit. There is deliberately no member meaning
    "recent", "new", "active", or "changed": recency is not a reason, and the
    absence of a member for it is what makes that a structural claim rather than
    a stylistic one.
    """

    COMMITMENT_OVERDUE = "commitment_overdue"
    COMMITMENT_DUE_SOON = "commitment_due_soon"
    TASK_OVERDUE = "task_overdue"
    TASK_DUE_SOON = "task_due_soon"
    DECISION_AWAITING_AUTHORITY = "decision_awaiting_authority"
    SITUATION_OBLIGATION_UNMET = "situation_obligation_unmet"


@dataclass(frozen=True, slots=True)
class Situation:
    """A purposeful operational context that references objects but owns none.

    `object_refs` are opaque references the Situation is *about*; the Situation
    never owns them, so closing it (recording `outcome` and `closed_at`) leaves
    every referenced object intact. The closed-state/closed-time pairing mirrors
    the migration CHECK `a_closed_situation_records_when_it_closed`: a Situation
    is closed exactly when it records when it closed.
    """

    situation_id: str
    principal_id: str
    title: str
    state: SituationState
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    object_refs: tuple[str, ...] = ()
    closed_at: datetime | None = None
    outcome: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.situation_id, IdKind.SITUATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.title.strip():
            raise ValueError("a situation carries a non-blank title")
        if not isinstance(self.state, SituationState):
            raise ValueError("a situation names one lifecycle state")
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        if (self.state is SituationState.CLOSED) is not (self.closed_at is not None):
            raise ValueError("a closed situation records when it closed, and only then")


@dataclass(frozen=True, slots=True)
class Frame:
    """The current or saved view within one Situation of what matters.

    Carries `principal_id` explicitly so the partition can be enforced without
    joining back to the parent Situation, even though it inherits that
    Situation's Principal.
    """

    frame_id: str
    situation_id: str
    principal_id: str
    label: str
    state: FrameState
    created_at: datetime
    updated_at: datetime
    evidence_refs: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    uncertainty: str | None = None
    next_authority: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.frame_id, IdKind.FRAME)
        validate_identifier(self.situation_id, IdKind.SITUATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.label.strip():
            raise ValueError("a frame carries a non-blank label")
        if not isinstance(self.state, FrameState):
            raise ValueError("a frame names one state")
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)


@dataclass(frozen=True, slots=True)
class Trace:
    """A derived, source-linked temporal reconstruction of one object.

    A Trace is a projection, never source evidence: `source_events` records the
    events it reconstructed and `gaps` records the intervals it could not fill,
    so an incomplete reconstruction is legible as incomplete rather than passed
    off as whole. The range, when both ends are present, ends no earlier than it
    starts — the migration CHECK `a_trace_range_ends_after_it_starts`.
    """

    trace_id: str
    principal_id: str
    object_id: str
    object_type: str
    created_at: datetime
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    source_events: tuple[dict[str, object], ...] = ()
    gaps: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.trace_id, IdKind.TRACE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.object_id.strip():
            raise ValueError("a trace names the object it reconstructs")
        if not self.object_type.strip():
            raise ValueError("a trace records the kind of object it reconstructs")
        ensure_utc(self.created_at)
        if self.time_range_start is not None:
            ensure_utc(self.time_range_start)
        if self.time_range_end is not None:
            ensure_utc(self.time_range_end)
        if (
            self.time_range_start is not None
            and self.time_range_end is not None
            and self.time_range_end < self.time_range_start
        ):
            raise ValueError("a trace range ends no earlier than it starts")


@dataclass(frozen=True, slots=True)
class Project:
    """A durable work context with participants that groups Situations.

    The closed-state/closed-time pairing mirrors the migration CHECK
    `a_closed_project_records_when_it_closed`.
    """

    project_id: str
    principal_id: str
    name: str
    state: ProjectState
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    participants: tuple[str, ...] = ()
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.project_id, IdKind.PROJECT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.name.strip():
            raise ValueError("a project carries a non-blank name")
        if not isinstance(self.state, ProjectState):
            raise ValueError("a project names one lifecycle state")
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        if (self.state is ProjectState.CLOSED) is not (self.closed_at is not None):
            raise ValueError("a closed project records when it closed, and only then")


@dataclass(frozen=True, slots=True)
class PulseItem:
    """A derived attention recommendation generated only from accepted state.

    `accepted_only` is pinned true and validated as such: it is the domain half
    of the migration CHECK `pulse_reads_only_accepted_records`. The invariant is
    that a Pulse item is *derived from accepted records only* — never from a
    proposal — so `priority` orders attention among accepted facts and nothing
    here can surface an unaccepted one.

    **`reason_code` and `basis_refs` are mandatory (WP-11), and that is what
    makes "not an activity feed" a property rather than a promise.**
    `reason_code` is the closed why-now vocabulary; `basis_refs` are the records
    a reader can open to check the reason, and an empty basis is refused here and
    by the schema CHECK `a_pulse_item_carries_an_evidentiary_basis`. An item that
    is merely recent has no reason code to write and no basis to cite, so it
    cannot be constructed and cannot be stored.

    `attention_rank` is a bounded urgency rank on the *item*. Nothing here ranks,
    scores, or characterises a person: `§22` forbids it, and there is no field
    one could go in.
    """

    pulse_id: str
    principal_id: str
    item_type: PulseItemType
    item_ref: str
    reason: str
    reason_code: PulseReasonCode
    basis_refs: tuple[str, ...]
    generated_at: datetime
    consequence: str | None = None
    next_step: str | None = None
    attention_rank: int = 5
    accepted_only: bool = field(default=True)
    dismissed_at: datetime | None = None
    subject_title: str | None = None
    subject_state: str | None = None
    subject_version: int | None = None
    subject_priority: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.pulse_id, IdKind.PULSE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.item_type, PulseItemType):
            raise ValueError("a pulse item names one item type")
        if not self.item_ref.strip():
            raise ValueError("a pulse item points at one record")
        if not self.reason.strip():
            raise ValueError("a pulse item states why it is surfaced")
        if not isinstance(self.reason_code, PulseReasonCode):
            raise ValueError("a pulse item names one why-now reason code")
        if not self.basis_refs or any(not str(ref).strip() for ref in self.basis_refs):
            raise ValueError("a pulse item cites at least one non-blank evidentiary basis")
        if isinstance(self.attention_rank, bool) or not isinstance(self.attention_rank, int):
            raise ValueError("attention_rank is an integer")
        if not 1 <= self.attention_rank <= 10:
            raise ValueError("attention_rank is between one and ten")
        if self.accepted_only is not True:
            raise ValueError("a pulse item reads only accepted records")
        ensure_utc(self.generated_at)
        if self.dismissed_at is not None:
            ensure_utc(self.dismissed_at)
        if self.subject_version is not None and self.subject_version < 1:
            raise ValueError("subject_version must be >= 1 when set")
