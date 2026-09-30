"""WP-RE-01: the Record Event domain carrier.

A Record Event says *that* one canonical record changed, in which family, to
which version, through which operation -- and nothing else. It is an
invalidation feed, not a history: a consumer that sees an event rereads the
named record through its own family's read. Nothing here carries a record body,
a narrative value, a request body, a query or a before/after snapshot
(hardened package RE-I-007); the only free-form-looking field, `changed_fields`,
is a sorted set of lower-snake field-name *tokens*.

Pure domain apart from one deliberate exception: `RecordEventDraft.issue` mints
the event's opaque identifier at staging time, because one event in a composite
transaction must be able to name an earlier staged event as its cause before
either has a sequence number (hardened package section 3.6).

The closed vocabularies are:

* `RecordEventFamily` -- the twenty-two canonical record families the feed
  covers (WP-RE-08 added the Capture and Task-comment planes); a later family is
  an explicit enum, schema and migration change;
* `RecordEventKind` -- `created`, `updated`, `state_changed`; the exact operation
  is `source_capability`, so no duplicate verb vocabulary exists here;
* `RecordEventActorClass` -- the four actor classes, with one map per source
  vocabulary (section 3.4);
* `RecordEventAuthority` -- the six source-plane authority tokens (G1-MG-004):
  the union of `relationship.governance.MutationAuthority` (the Entity plane's
  mutation ledger) and `relationship.memory.MemoryAuthority` (the Relationship
  Memory version), which share `user_confirmed_assertion`. Those are the only two
  source planes in scope whose writes record an authority at all; every other
  in-scope family records none, and its events carry `authority=None`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    validate_identifier,
)
from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.meeting.model import MeetingActor
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.domain.relationship.governance import (
    ActorClass,
    MutationAuthority,
    MutationRecordFamily,
)
from my_pa.domain.relationship.identity_correction import IdentityEffectFamily
from my_pa.domain.relationship.memory import MemoryActorClass, MemoryAuthority, MemoryOperation
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor

__all__ = [
    "CONSTRAINT_ACTOR_CLASSES",
    "ENTITY_ACTOR_CLASSES",
    "ENTITY_AUTHORITIES",
    "ENTITY_FLOOR_CAPABILITY",
    "ENTITY_FLOOR_FAMILIES",
    "ENTITY_RECORD_FAMILIES",
    "IDENTITY_EFFECT_RECORD_FAMILIES",
    "MAX_CHANGED_FIELDS",
    "MAX_CHANGED_FIELD_CHARACTERS",
    "MAX_SOURCE_CAPABILITY_CHARACTERS",
    "MEETING_ACTOR_CLASSES",
    "MEMORY_ACTOR_CLASSES",
    "MEMORY_AUTHORITIES",
    "MEMORY_CAPABILITIES",
    "NON_MEMORY_CLASSIFICATION",
    "RECORD_EVENT_FAMILY_READS",
    "REVIEW_PROMOTION_CAPABILITY",
    "TASK_ACTOR_CLASSES",
    "EntityEventShape",
    "InvalidRecordEventError",
    "RecordEvent",
    "RecordEventActorClass",
    "RecordEventAuthority",
    "RecordEventDraft",
    "RecordEventFamily",
    "RecordEventKind",
    "entity_record_event",
    "entity_source_capability",
    "field_set",
    "memory_source_capability",
    "observation_feed_version",
    "validate_changed_fields",
    "validate_source_capability",
]

#: At most this many field-name tokens on one event (section 3.5).
MAX_CHANGED_FIELDS: Final = 64
#: Each field-name token is 1..64 characters of lower snake case.
MAX_CHANGED_FIELD_CHARACTERS: Final = 64
#: `source_capability` is a `Capability.value` or a bounded internal token.
MAX_SOURCE_CAPABILITY_CHARACTERS: Final = 128

#: One field-name token: lower snake case, starting with a letter, 1..64
#: characters. The same shape `project_controls.history` uses for its failure
#: code, and the pattern the `record_events.changed_fields` CHECK restates.
CHANGED_FIELD_PATTERN: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
#: A dotted lower-snake operation name. Every `Capability.value` matches it, and
#: so does every bounded internal token a non-request path uses.
SOURCE_CAPABILITY_PATTERN: Final = re.compile(r"\A[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z")
#: A receipt identifier of any kind: an opaque lower-case prefix and the
#: standard suffix -- exactly the `record_events` receipt CHECK. Wider than
#: `IdKind` on purpose: a receipt ledger may mint an identifier that is not a
#: contract-v1 kind (the Project Controls settings ledger's `cpsh_`, which
#: `project_controls.history` deliberately keeps out of `IdKind`). Still no
#: path, host, dot, colon, space or `@` can pass.
RECEIPT_IDENTIFIER_PATTERN: Final = re.compile(r"\A[a-z]+_[A-Za-z0-9]{8,64}\Z")

#: The classification every other event carries (G1-EM-009, amended by
#: WP-RE-08 under OD-W8-5). Two families take their classification from the
#: committed version they describe instead: a Relationship Memory event and a
#: Capture event.
NON_MEMORY_CLASSIFICATION: Final = Classification.PRIVATE_LOCAL


class RecordEventFamily(StrEnum):
    """The twenty-two canonical record families the feed names (section 3.2).

    Closed: a free-form family name is refused, and a later family is an
    explicit enum, schema and migration change.
    """

    TASK = "task"
    COMMITMENT = "commitment"
    PROJECT = "project"
    ENTITY = "entity"
    ENTITY_IDENTIFIER = "entity_identifier"
    ENTITY_ALIAS = "entity_alias"
    ENTITY_ASSIGNMENT = "entity_assignment"
    ENTITY_RELATIONSHIP = "entity_relationship"
    ENTITY_OBSERVATION = "entity_observation"
    ENTITY_NAME = "entity_name"
    ENTITY_ADDRESS = "entity_address"
    ENTITY_COMMUNICATION_METHOD = "entity_communication_method"
    ENTITY_PROJECT_PARTICIPATION = "entity_project_participation"
    PERSON_ORGANIZATION_AFFILIATION = "person_organization_affiliation"
    RELATIONSHIP_MEMORY = "relationship_memory"
    CONSTRAINT = "constraint"
    CONSTRAINT_CATEGORY = "constraint_category"
    PROJECT_CONTROLS_SETTINGS = "project_controls_settings"
    MEETING = "meeting"
    MEETING_SERIES = "meeting_series"
    CAPTURE = "capture"
    TASK_COMMENT = "task_comment"


class RecordEventKind(StrEnum):
    """What happened to the record (section 3.3); the operation is `source_capability`."""

    CREATED = "created"
    UPDATED = "updated"
    STATE_CHANGED = "state_changed"


class RecordEventActorClass(StrEnum):
    """What class of actor committed the change (section 3.4)."""

    PRINCIPAL = "principal"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    REVIEW_PROMOTION = "review_promotion"


class RecordEventAuthority(StrEnum):
    """What admitted the change, where the source plane records it (G1-MG-004).

    Six members: the union of the Entity mutation ledger's `MutationAuthority`
    and the Relationship Memory version's `MemoryAuthority`, which share
    `user_confirmed_assertion`. Spelled as the source planes spell them so an
    event and the ledger row it points at can never disagree about one write.
    """

    USER_CONFIRMED_ASSERTION = "user_confirmed_assertion"
    REVIEW_ACCEPTED = "review_accepted"
    SYSTEM_DETERMINISTIC = "system_deterministic"
    USER_AUTHORED_PRIVATE_NOTE = "user_authored_private_note"
    SOURCE_BACKED_ASSERTION = "source_backed_assertion"
    PUBLIC_ASSERTION = "public_assertion"


def _frozen[K, V](mapping: dict[K, V]) -> Mapping[K, V]:
    return MappingProxyType(mapping)


#: Section 3.4 actor maps, one per source vocabulary. Each is total over its
#: source enum; `tests/unit/test_record_event_domain.py` holds them to that.
TASK_ACTOR_CLASSES: Final[Mapping[TaskMutationActor, RecordEventActorClass]] = _frozen(
    {
        TaskMutationActor.PRINCIPAL: RecordEventActorClass.PRINCIPAL,
        TaskMutationActor.ASSISTANT: RecordEventActorClass.ASSISTANT,
        TaskMutationActor.SYSTEM: RecordEventActorClass.SYSTEM,
    }
)
CONSTRAINT_ACTOR_CLASSES: Final[Mapping[ConstraintMutationActor, RecordEventActorClass]] = _frozen(
    {
        ConstraintMutationActor.PRINCIPAL: RecordEventActorClass.PRINCIPAL,
        ConstraintMutationActor.ASSISTANT: RecordEventActorClass.ASSISTANT,
        ConstraintMutationActor.SYSTEM: RecordEventActorClass.SYSTEM,
    }
)
MEETING_ACTOR_CLASSES: Final[Mapping[MeetingActor, RecordEventActorClass]] = _frozen(
    {
        MeetingActor.PRINCIPAL: RecordEventActorClass.PRINCIPAL,
        MeetingActor.ASSISTANT: RecordEventActorClass.ASSISTANT,
        MeetingActor.SYSTEM: RecordEventActorClass.SYSTEM,
    }
)
ENTITY_ACTOR_CLASSES: Final[Mapping[ActorClass, RecordEventActorClass]] = _frozen(
    {
        ActorClass.USER: RecordEventActorClass.PRINCIPAL,
        ActorClass.REVIEW_PROMOTION: RecordEventActorClass.REVIEW_PROMOTION,
        ActorClass.SYSTEM_DETERMINISTIC: RecordEventActorClass.SYSTEM,
    }
)
MEMORY_ACTOR_CLASSES: Final[Mapping[MemoryActorClass, RecordEventActorClass]] = _frozen(
    {
        MemoryActorClass.USER: RecordEventActorClass.PRINCIPAL,
        MemoryActorClass.REVIEW_PROMOTION: RecordEventActorClass.REVIEW_PROMOTION,
        MemoryActorClass.SYSTEM_DETERMINISTIC: RecordEventActorClass.SYSTEM,
    }
)

#: The two source-plane authority vocabularies, mapped by spelling.
ENTITY_AUTHORITIES: Final[Mapping[MutationAuthority, RecordEventAuthority]] = _frozen(
    {member: RecordEventAuthority(member.value) for member in MutationAuthority}
)
MEMORY_AUTHORITIES: Final[Mapping[MemoryAuthority, RecordEventAuthority]] = _frozen(
    {member: RecordEventAuthority(member.value) for member in MemoryAuthority}
)


class InvalidRecordEventError(ValueError):
    """Raised when a Record Event or draft violates the section 3.5 contract.

    The message names the offending *field*, never the rejected value: a
    rejected value could be exactly the narrative this carrier must not hold.
    """


def validate_changed_fields(values: Iterable[object]) -> tuple[str, ...]:
    """Return `values` as a tuple, or raise if it is not a bounded token set.

    The tuple must already be sorted and unique: an emitter declares the set it
    changed in canonical order, and a silent re-sort here would let two
    emitters that disagree about order both look correct.
    """
    if isinstance(values, str):
        raise InvalidRecordEventError("changed_fields must be a sequence of field names")
    candidates = tuple(values)
    if len(candidates) > MAX_CHANGED_FIELDS:
        raise InvalidRecordEventError(f"changed_fields holds more than {MAX_CHANGED_FIELDS}")
    fields: list[str] = []
    for token in candidates:
        if not isinstance(token, str) or not CHANGED_FIELD_PATTERN.fullmatch(token):
            raise InvalidRecordEventError("changed_fields holds a token that is not lower_snake")
        fields.append(token)
    if len(set(fields)) != len(fields):
        raise InvalidRecordEventError("changed_fields holds a duplicate")
    if fields != sorted(fields):
        raise InvalidRecordEventError("changed_fields is not sorted")
    return tuple(fields)


def validate_source_capability(value: object) -> str:
    """Return `value` unchanged if it is a bounded dotted operation name."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_SOURCE_CAPABILITY_CHARACTERS
        or not SOURCE_CAPABILITY_PATTERN.fullmatch(value)
    ):
        raise InvalidRecordEventError("source_capability is not a bounded operation name")
    return value


def _identifier(value: object, kind: IdKind | None, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidRecordEventError(f"{field} is not an opaque identifier")
    try:
        return validate_identifier(value, kind)
    except InvalidIdentifierError as exc:
        raise InvalidRecordEventError(f"{field} is not an opaque identifier") from exc


def _optional_identifier(value: object, kind: IdKind | None, field: str) -> str | None:
    return None if value is None else _identifier(value, kind, field)


def _receipt(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not RECEIPT_IDENTIFIER_PATTERN.fullmatch(value):
        raise InvalidRecordEventError("source_receipt_id is not an opaque identifier")
    return value


def _positive(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidRecordEventError(f"{field} must be an integer >= 1")
    return value


def _instant(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise InvalidRecordEventError(f"{field} must be a datetime")
    try:
        return ensure_utc(value)
    except NaiveDatetimeError as exc:
        raise InvalidRecordEventError(f"{field} must be timezone-aware") from exc


def _member[E: StrEnum](enum: type[E], value: object, field: str) -> E:
    if not isinstance(value, str):
        raise InvalidRecordEventError(f"{field} is not a known value")
    try:
        return enum(value)
    except ValueError as exc:
        raise InvalidRecordEventError(f"{field} is not a known value") from exc


@dataclass(frozen=True, slots=True)
class _Semantics:
    """The fields a draft and a committed event share, validated once."""

    event_id: str
    principal_id: str
    record_family: RecordEventFamily
    record_id: str
    event_kind: RecordEventKind
    record_version: int
    changed_fields: tuple[str, ...]
    source_capability: str
    actor_class: RecordEventActorClass
    classification: Classification
    occurred_at: datetime
    source_receipt_id: str | None
    authority: RecordEventAuthority | None
    correlation_id: str | None
    causation_event_id: str | None


def _validated(
    *,
    event_id: object,
    principal_id: object,
    record_family: object,
    record_id: object,
    event_kind: object,
    record_version: object,
    changed_fields: object,
    source_capability: object,
    actor_class: object,
    classification: object,
    occurred_at: object,
    source_receipt_id: object,
    authority: object,
    correlation_id: object,
    causation_event_id: object,
) -> _Semantics:
    event = _identifier(event_id, IdKind.RECORD_EVENT, "event_id")
    cause = _optional_identifier(causation_event_id, IdKind.RECORD_EVENT, "causation_event_id")
    if cause is not None and cause == event:
        raise InvalidRecordEventError("causation_event_id names the event itself")
    if not isinstance(changed_fields, tuple | list):
        raise InvalidRecordEventError("changed_fields must be a sequence of field names")
    return _Semantics(
        event_id=event,
        principal_id=_identifier(principal_id, IdKind.PRINCIPAL, "principal_id"),
        record_family=_member(RecordEventFamily, record_family, "record_family"),
        record_id=_identifier(record_id, None, "record_id"),
        event_kind=_member(RecordEventKind, event_kind, "event_kind"),
        record_version=_positive(record_version, "record_version"),
        changed_fields=validate_changed_fields(changed_fields),
        source_capability=validate_source_capability(source_capability),
        actor_class=_member(RecordEventActorClass, actor_class, "actor_class"),
        classification=_member(Classification, classification, "classification"),
        occurred_at=_instant(occurred_at, "occurred_at"),
        source_receipt_id=_receipt(source_receipt_id),
        authority=(
            None if authority is None else _member(RecordEventAuthority, authority, "authority")
        ),
        correlation_id=_optional_identifier(correlation_id, IdKind.CORRELATION, "correlation_id"),
        causation_event_id=cause,
    )


def _normalize(instance: object, semantics: _Semantics) -> None:
    for name in _Semantics.__slots__:
        object.__setattr__(instance, name, getattr(semantics, name))


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordEventDraft:
    """One staged, not yet sequenced, Record Event (section 3.6).

    Immutable. `event_id` is issued when the draft is built (`issue`), so a
    later draft in the same transaction can name it as `causation_event_id`.
    There is no `sequence_number` -- the allocator assigns it at flush -- and no
    `recorded_at`, which the server sets.
    """

    event_id: str
    principal_id: str
    record_family: RecordEventFamily
    record_id: str
    event_kind: RecordEventKind
    record_version: int
    changed_fields: tuple[str, ...]
    source_capability: str
    actor_class: RecordEventActorClass
    classification: Classification
    occurred_at: datetime
    source_receipt_id: str | None = None
    authority: RecordEventAuthority | None = None
    correlation_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        _normalize(
            self,
            _validated(**{name: getattr(self, name) for name in _Semantics.__slots__}),
        )

    @classmethod
    def issue(
        cls,
        *,
        principal_id: str,
        record_family: RecordEventFamily,
        record_id: str,
        event_kind: RecordEventKind,
        record_version: int,
        changed_fields: tuple[str, ...],
        source_capability: str,
        actor_class: RecordEventActorClass,
        classification: Classification,
        occurred_at: datetime,
        source_receipt_id: str | None = None,
        authority: RecordEventAuthority | None = None,
        correlation_id: str | None = None,
        causation_event_id: str | None = None,
    ) -> RecordEventDraft:
        """Build a draft with a freshly issued `rcev_` identifier."""
        return cls(
            event_id=issue_identifier(IdKind.RECORD_EVENT),
            principal_id=principal_id,
            record_family=record_family,
            record_id=record_id,
            event_kind=event_kind,
            record_version=record_version,
            changed_fields=changed_fields,
            source_capability=source_capability,
            actor_class=actor_class,
            classification=classification,
            occurred_at=occurred_at,
            source_receipt_id=source_receipt_id,
            authority=authority,
            correlation_id=correlation_id,
            causation_event_id=causation_event_id,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordEvent:
    """One committed Record Event (section 3.5)."""

    event_id: str
    principal_id: str
    sequence_number: int
    record_family: RecordEventFamily
    record_id: str
    event_kind: RecordEventKind
    record_version: int
    changed_fields: tuple[str, ...]
    source_capability: str
    actor_class: RecordEventActorClass
    classification: Classification
    occurred_at: datetime
    recorded_at: datetime
    source_receipt_id: str | None = None
    authority: RecordEventAuthority | None = None
    correlation_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        _normalize(
            self,
            _validated(**{name: getattr(self, name) for name in _Semantics.__slots__}),
        )
        object.__setattr__(
            self, "sequence_number", _positive(self.sequence_number, "sequence_number")
        )
        object.__setattr__(self, "recorded_at", _instant(self.recorded_at, "recorded_at"))

    @classmethod
    def from_draft(
        cls, draft: RecordEventDraft, *, sequence_number: int, recorded_at: datetime
    ) -> RecordEvent:
        """The committed form of `draft` at its allocated sequence number."""
        return cls(
            sequence_number=sequence_number,
            recorded_at=recorded_at,
            **{name: getattr(draft, name) for name in _Semantics.__slots__},
        )


# --- WP-RE-04: the Entity and Relationship Memory emitter vocabulary ----------

#: RE-AC-045: every `MutationRecordFamily` the Entity mutation ledger can name,
#: mapped to the feed family it is (P2b section 1.4). Total and one-to-one;
#: `tests/unit/test_record_event_domain.py` holds it to both.
ENTITY_RECORD_FAMILIES: Final[Mapping[MutationRecordFamily, RecordEventFamily]] = _frozen(
    {
        MutationRecordFamily.ENTITY: RecordEventFamily.ENTITY,
        MutationRecordFamily.IDENTIFIER: RecordEventFamily.ENTITY_IDENTIFIER,
        MutationRecordFamily.ALIAS: RecordEventFamily.ENTITY_ALIAS,
        MutationRecordFamily.ASSIGNMENT: RecordEventFamily.ENTITY_ASSIGNMENT,
        MutationRecordFamily.RELATIONSHIP: RecordEventFamily.ENTITY_RELATIONSHIP,
        MutationRecordFamily.OBSERVATION: RecordEventFamily.ENTITY_OBSERVATION,
        MutationRecordFamily.NAME: RecordEventFamily.ENTITY_NAME,
        MutationRecordFamily.ADDRESS: RecordEventFamily.ENTITY_ADDRESS,
        MutationRecordFamily.COMMUNICATION_METHOD: RecordEventFamily.ENTITY_COMMUNICATION_METHOD,
        MutationRecordFamily.PROJECT_PARTICIPATION: RecordEventFamily.ENTITY_PROJECT_PARTICIPATION,
        MutationRecordFamily.PERSON_ORGANIZATION_AFFILIATION: (
            RecordEventFamily.PERSON_ORGANIZATION_AFFILIATION
        ),
    }
)

#: Merge/split effects to the feed family they name (P2b section 1.4): twelve.
#: A family absent here gets no event of its own (OD-3): ORGANIZATION_PROFILE,
#: PROPOSAL, REVIEW_CASE, MEMORY_PROPOSAL and DERIVED_CONTEXT. A retargeted
#: MEMORY_CONTEXT_LINK is named through the memory that owns it (OD-2 (b)).
IDENTITY_EFFECT_RECORD_FAMILIES: Final[Mapping[IdentityEffectFamily, RecordEventFamily]] = _frozen(
    {
        IdentityEffectFamily.ENTITY: RecordEventFamily.ENTITY,
        IdentityEffectFamily.IDENTIFIER: RecordEventFamily.ENTITY_IDENTIFIER,
        IdentityEffectFamily.ALIAS: RecordEventFamily.ENTITY_ALIAS,
        IdentityEffectFamily.ASSIGNMENT: RecordEventFamily.ENTITY_ASSIGNMENT,
        IdentityEffectFamily.RELATIONSHIP: RecordEventFamily.ENTITY_RELATIONSHIP,
        IdentityEffectFamily.NAME: RecordEventFamily.ENTITY_NAME,
        IdentityEffectFamily.ADDRESS: RecordEventFamily.ENTITY_ADDRESS,
        IdentityEffectFamily.COMMUNICATION_METHOD: RecordEventFamily.ENTITY_COMMUNICATION_METHOD,
        IdentityEffectFamily.PROJECT_PARTICIPATION: (
            RecordEventFamily.ENTITY_PROJECT_PARTICIPATION
        ),
        IdentityEffectFamily.PERSON_ORGANIZATION_AFFILIATION: (
            RecordEventFamily.PERSON_ORGANIZATION_AFFILIATION
        ),
        IdentityEffectFamily.OBSERVATION: RecordEventFamily.ENTITY_OBSERVATION,
        IdentityEffectFamily.RELATIONSHIP_MEMORY: RecordEventFamily.RELATIONSHIP_MEMORY,
    }
)

#: OD-6: every event a review promotion causes names the request capability
#: that caused it, whichever canonical writer performed the change.
REVIEW_PROMOTION_CAPABILITY: Final = Capability.REVIEW_DECIDE.value

#: The public capability behind each Relationship Memory write (P2b M1-M4).
MEMORY_CAPABILITIES: Final[Mapping[MemoryOperation, str]] = _frozen(
    {
        MemoryOperation.CREATE: Capability.RELATIONSHIP_MEMORY_CREATE.value,
        MemoryOperation.REVISE: Capability.RELATIONSHIP_MEMORY_REVISE.value,
        MemoryOperation.ARCHIVE: Capability.RELATIONSHIP_MEMORY_ARCHIVE.value,
        MemoryOperation.RESTORE: Capability.RELATIONSHIP_MEMORY_RESTORE.value,
    }
)


def entity_source_capability(capability: str, actor_class: ActorClass) -> str:
    """The `source_capability` of an Entity-plane event (OD-6, G1-EM-004).

    The ledger records the canonical writer's capability (`entities.create`
    and the like) even when `review.decide` executed it. The actor class is
    what tells the two apart, and it is trustworthy for that: no transport
    command carries it, and `EntityWriteRequest` / `_check_write_authority`
    refuse `review_promotion` on anything but the promotion path.
    """
    if actor_class is ActorClass.REVIEW_PROMOTION:
        return REVIEW_PROMOTION_CAPABILITY
    return capability


def memory_source_capability(operation: MemoryOperation, actor: MemoryActorClass) -> str:
    """`entity_source_capability` for a Relationship Memory write."""
    if actor is MemoryActorClass.REVIEW_PROMOTION:
        return REVIEW_PROMOTION_CAPABILITY
    return MEMORY_CAPABILITIES[operation]


def observation_feed_version(resolution_version: int) -> int:
    """OD-2 (d-i), T-002: the one `entity_observation` feed version function.

    `resolution_version + 1`, from the *post-write* canonical value. The
    canonical column starts at 0 and a merge reparent does not advance it, so
    the feed version is not a dedup key: a consumer rereads an observation on
    every event and never skips an equal version.
    """
    if isinstance(resolution_version, bool) or not isinstance(resolution_version, int):
        raise InvalidRecordEventError("resolution_version must be an integer")
    if resolution_version < 0:
        raise InvalidRecordEventError("resolution_version must be an integer >= 0")
    return resolution_version + 1


def field_set(*names: str) -> tuple[str, ...]:
    """A `changed_fields` value in the canonical (sorted, unique) order."""
    return tuple(sorted(set(names)))


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityEventShape:
    """What an Entity ledger caller knows about the event its row implies.

    Passed to `EntitiesRepository.record_mutation_event`, whose seam (S-C) stages
    the event only after the ledger INSERT -- never on its silent replay return
    (G1-EM-016). The shape is typed, so the event is never re-derived from the
    ledger row's before/after JSON (P2b R2/R3).

    `superseded` names the predecessor a family supersession transitioned, as
    `(record_id, version after the supersession)`; it becomes a derived
    `state_changed` (G1-EM-001(b)). `causation_event_id` names an earlier
    staged event this one follows from (the `resolve_mention` Entity create,
    G1-EM-002).
    """

    event_kind: RecordEventKind
    changed_fields: tuple[str, ...]
    superseded: tuple[str, int] | None = None
    superseded_fields: tuple[str, ...] = ("state",)
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_kind", _member(RecordEventKind, self.event_kind, "event_kind")
        )
        object.__setattr__(self, "changed_fields", validate_changed_fields(self.changed_fields))
        object.__setattr__(
            self, "superseded_fields", validate_changed_fields(self.superseded_fields)
        )
        if self.superseded is not None:
            record_id, version = self.superseded
            _identifier(record_id, None, "superseded")
            _positive(version, "superseded")


def entity_record_event(
    *,
    principal_id: str,
    family: MutationRecordFamily,
    record_id: str,
    event_kind: RecordEventKind,
    record_version: int,
    changed_fields: tuple[str, ...],
    capability: str,
    authority: MutationAuthority,
    actor_class: ActorClass,
    occurred_at: datetime,
    receipt_id: str | None,
    correlation_id: str | None,
    causation_event_id: str | None = None,
) -> RecordEventDraft:
    """One Entity-plane draft, with the section 3.4/3.5 maps applied in one place."""
    return RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=ENTITY_RECORD_FAMILIES[family],
        record_id=record_id,
        event_kind=event_kind,
        record_version=record_version,
        changed_fields=changed_fields,
        source_capability=entity_source_capability(capability, actor_class),
        actor_class=ENTITY_ACTOR_CLASSES[actor_class],
        classification=NON_MEMORY_CLASSIFICATION,
        occurred_at=occurred_at,
        source_receipt_id=receipt_id,
        authority=ENTITY_AUTHORITIES[authority],
        correlation_id=correlation_id,
        causation_event_id=causation_event_id,
    )


# --- WP-RE-08: the Capture plane (Amendment 01) --------------------------------

#: What every capture create names: every non-narrative, non-digest field the
#: capture read views (`CaptureVersionView`, `CaptureListEntry`) expose that a
#: first version always materializes (MR-11, the WP-RE-02/05 created-event
#: precedent). Tokens are the public read field names. Never the text, a digest
#: or a label value. Not named: `capture_id` and the version's own
#: `version_id`/`version_number` (the event's `record_id`/`record_version`, and
#: `latest_version_*`); `is_current` (derived); `supersedes_version_id` (null on
#: a first version); and server bookkeeping times (`server_received_at`,
#: `accepted_at`, `recorded_at`, `created_at`, `latest_recorded_at`).
CAPTURE_CREATED_FIELDS: Final = field_set(
    "character_count",
    "classification",
    "latest_version_id",
    "latest_version_number",
    "owner_principal_id",
    "processing_policy",
    "version_count",
)

#: What every capture revise names, whatever else differs: the new head, and
#: the current version's `supersedes_version_id` (`capture.read`'s
#: `CaptureVersionView`), which a revise always moves -- from nothing to the
#: first version, or from one predecessor to the next (MR-11, literal reading).
CAPTURE_HEAD_FIELDS: Final = field_set(
    "latest_version_id", "latest_version_number", "supersedes_version_id", "version_count"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureVersionFacts:
    """The non-narrative, caller-visible facts one capture version holds.

    Exactly the version fields `capture.read` exposes that a revise can change
    independently: compared field by field between the predecessor (read by the
    same head statement that orders the chain) and the version just written.
    `character_count` is a count, neither narrative nor a digest, so it is named
    when it moves (MR-11). No text, no digest, no label, no key -- so nothing
    narrative can cross into a token. Server bookkeeping times
    (`server_received_at`, `accepted_at`, `recorded_at`) are not fields, the
    Task precedent.
    """

    classification: Classification
    processing_policy: str
    client_created_at: datetime | None
    occurred_at: datetime | None
    character_count: int


def _capture_version_values(facts: CaptureVersionFacts) -> dict[str, object]:
    """The compared fields, spelled attribute by attribute rather than by string."""
    return {
        "character_count": facts.character_count,
        "classification": facts.classification,
        "client_created_at": facts.client_created_at,
        "occurred_at": facts.occurred_at,
        "processing_policy": facts.processing_policy,
    }


def capture_changed_fields(
    *,
    prior: CaptureVersionFacts | None,
    written: CaptureVersionFacts,
    label_recorded: bool,
    project_bound: bool,
) -> tuple[str, ...]:
    """The exact `changed_fields` of one capture admission (RE-AC-088, MR-07/MR-11).

    A create (`prior is None`) names `CAPTURE_CREATED_FIELDS` plus each optional
    field it wrote non-null: `client_created_at`, `occurred_at`, the first
    `display_label` and the bound `project_id`. A revise names the new head
    and its `supersedes_version_id`, plus each version field whose value
    differs from the predecessor's; a revise writes no label and never binds a
    Project.
    """
    values = _capture_version_values(written)
    if prior is None:
        present = [
            name for name in ("client_created_at", "occurred_at") if values[name] is not None
        ]
        if label_recorded:
            present.append("display_label")
        if project_bound:
            present.append("project_id")
        return field_set(*CAPTURE_CREATED_FIELDS, *present)
    if label_recorded or project_bound:
        raise InvalidRecordEventError("a capture revise writes no label and binds no Project")
    was = _capture_version_values(prior)
    diff = [name for name, value in values.items() if was[name] != value]
    return field_set(*CAPTURE_HEAD_FIELDS, *diff)


def capture_record_event(
    *,
    principal_id: str,
    capture_id: str,
    event_kind: RecordEventKind,
    version_number: int,
    changed_fields: tuple[str, ...],
    capability: str,
    classification: Classification,
    occurred_at: datetime,
    receipt_id: str,
    correlation_id: str | None,
) -> RecordEventDraft:
    """The one draft a created capture version stages (E-CAP-1/E-CAP-2).

    `classification` is the committed version's (OD-W8-5, amending G1-EM-009):
    a capture event, like a memory event, carries the classification of the
    version it announces. Every capture admission is the authenticated
    Principal's own, and no capture plane records an authority.
    """
    return RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=RecordEventFamily.CAPTURE,
        record_id=capture_id,
        event_kind=event_kind,
        record_version=version_number,
        changed_fields=changed_fields,
        source_capability=capability,
        actor_class=RecordEventActorClass.PRINCIPAL,
        classification=classification,
        occurred_at=occurred_at,
        source_receipt_id=receipt_id,
        correlation_id=correlation_id,
    )


# --- WP-RE-08: the Task-comment plane (Amendment 01) ---------------------------

#: What every comment create names: the non-narrative fields a comment holds,
#: as `tasks.comments.list` names them. Never `body` (narrative, MR-11) and
#: never `created_at` (bookkeeping, the Task precedent).
TASK_COMMENT_CREATED_FIELDS: Final = field_set("author_id", "author_kind", "task_id")


def task_comment_record_event(
    *,
    principal_id: str,
    comment_id: str,
    actor: TaskMutationActor,
    capability: str,
    occurred_at: datetime,
    correlation_id: str | None,
) -> RecordEventDraft:
    """The one draft a created (never replayed) Task comment stages (E-TC-1).

    A comment is append-only, so it is always version 1 and always `created`.
    It names no receipt (OD-W8-6: the comment row is its own), no causation,
    and never a `task` event: a comment does not advance the Task's version.
    A consumer rereads it through `tasks.comments.list`, keyed by its Task
    (MR-13).
    """
    return RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=RecordEventFamily.TASK_COMMENT,
        record_id=comment_id,
        event_kind=RecordEventKind.CREATED,
        record_version=1,
        changed_fields=TASK_COMMENT_CREATED_FIELDS,
        source_capability=capability,
        actor_class=TASK_ACTOR_CLASSES[actor],
        classification=NON_MEMORY_CLASSIFICATION,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
    )


# --- WP-RE-06: which read discloses which family (plan section 6.1) -----------

#: Every family, and the existing read capabilities that disclose its canonical
#: records; any one suffices. Written out row by row and never derived from a
#: capability name prefix: a read that does not return a family's records is
#: never a fallback for it, because that would widen a grant (REQUEST section
#: 5.K). `tests/unit/test_record_event_family_reads.py` holds the table to the
#: plan literally, so a change here is a reviewed decision.
#:
#: Composition is checked on these reads too: a family is composed iff one of
#: its reads is in `ApplicationService.available_capabilities`.
RECORD_EVENT_FAMILY_READS: Final[Mapping[RecordEventFamily, frozenset[Capability]]] = _frozen(
    {
        RecordEventFamily.TASK: frozenset({Capability.TASKS_READ, Capability.TASKS_LIST}),
        RecordEventFamily.COMMITMENT: frozenset(
            {Capability.COMMITMENTS_READ, Capability.COMMITMENTS_LIST}
        ),
        RecordEventFamily.PROJECT: frozenset(
            {Capability.CONTINUITY_PROJECTS_READ, Capability.CONTINUITY_PROJECTS}
        ),
        RecordEventFamily.ENTITY: frozenset({Capability.ENTITIES_GET}),
        RecordEventFamily.ENTITY_IDENTIFIER: frozenset({Capability.ENTITIES_IDENTIFIERS_LIST}),
        RecordEventFamily.ENTITY_ALIAS: frozenset({Capability.ENTITIES_ALIASES_LIST}),
        RecordEventFamily.ENTITY_ASSIGNMENT: frozenset({Capability.ENTITIES_ASSIGNMENTS_LIST}),
        RecordEventFamily.ENTITY_RELATIONSHIP: frozenset({Capability.ENTITIES_RELATIONSHIPS}),
        RecordEventFamily.ENTITY_OBSERVATION: frozenset({Capability.ENTITIES_OBSERVATIONS_LIST}),
        RecordEventFamily.ENTITY_NAME: frozenset(
            {Capability.ENTITIES_NAMES_LIST, Capability.ENTITIES_PROFILE}
        ),
        RecordEventFamily.ENTITY_ADDRESS: frozenset(
            {Capability.ENTITIES_ADDRESSES_LIST, Capability.ENTITIES_PROFILE}
        ),
        RecordEventFamily.ENTITY_COMMUNICATION_METHOD: frozenset(
            {Capability.ENTITIES_COMMUNICATION_LIST, Capability.ENTITIES_PROFILE}
        ),
        RecordEventFamily.ENTITY_PROJECT_PARTICIPATION: frozenset(
            {Capability.ENTITIES_PARTICIPATIONS_LIST, Capability.ENTITIES_PROFILE}
        ),
        # No affiliation list read exists; the profile is its only disclosure.
        RecordEventFamily.PERSON_ORGANIZATION_AFFILIATION: frozenset({Capability.ENTITIES_PROFILE}),
        RecordEventFamily.RELATIONSHIP_MEMORY: frozenset(
            {Capability.RELATIONSHIP_MEMORY_GET, Capability.RELATIONSHIP_MEMORY_LIST}
        ),
        RecordEventFamily.CONSTRAINT: frozenset(
            {Capability.CONSTRAINTS_READ, Capability.CONSTRAINTS_LIST}
        ),
        RecordEventFamily.CONSTRAINT_CATEGORY: frozenset({Capability.CONSTRAINT_CATEGORIES_LIST}),
        RecordEventFamily.PROJECT_CONTROLS_SETTINGS: frozenset(
            {Capability.PROJECT_CONTROLS_STATUS}
        ),
        RecordEventFamily.MEETING: frozenset({Capability.MEETINGS_READ, Capability.MEETINGS_LIST}),
        # No series read exists; the Meeting reads carry the series (and, under
        # OD-7 (i), its `series_version`).
        RecordEventFamily.MEETING_SERIES: frozenset(
            {Capability.MEETINGS_READ, Capability.MEETINGS_LIST}
        ),
        # WP-RE-08. `capture.search` returns identifiers without records, so it
        # is not a disclosure of the family (the `tasks.search` precedent).
        RecordEventFamily.CAPTURE: frozenset({Capability.CAPTURE_READ, Capability.CAPTURE_LIST}),
        # The only comment read is keyed by the Task (MR-13, OD-W8-9); no floor
        # (OD-W8-1 (i)): a comment event names no Task field.
        RecordEventFamily.TASK_COMMENT: frozenset({Capability.TASKS_COMMENTS_LIST}),
    }
)

#: OD-10 (i), the entity floor: the base Entity read every Entity-plane family
#: needs *in addition to* one of its own mapped reads. Conjunctive, so it only
#: ever narrows visibility; the `entity` family's own mapped read is this one.
ENTITY_FLOOR_CAPABILITY: Final = Capability.ENTITIES_GET

#: The ten families the floor is ANDed onto (plan section 6.1, rows 5-14).
ENTITY_FLOOR_FAMILIES: Final[frozenset[RecordEventFamily]] = frozenset(
    {
        RecordEventFamily.ENTITY_IDENTIFIER,
        RecordEventFamily.ENTITY_ALIAS,
        RecordEventFamily.ENTITY_ASSIGNMENT,
        RecordEventFamily.ENTITY_RELATIONSHIP,
        RecordEventFamily.ENTITY_OBSERVATION,
        RecordEventFamily.ENTITY_NAME,
        RecordEventFamily.ENTITY_ADDRESS,
        RecordEventFamily.ENTITY_COMMUNICATION_METHOD,
        RecordEventFamily.ENTITY_PROJECT_PARTICIPATION,
        RecordEventFamily.PERSON_ORGANIZATION_AFFILIATION,
    }
)
