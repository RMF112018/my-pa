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

* `RecordEventFamily` -- the twenty canonical record families the feed covers;
  a later family is an explicit enum, schema and migration change;
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
from my_pa.domain.meeting.model import MeetingActor
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.domain.relationship.governance import ActorClass, MutationAuthority
from my_pa.domain.relationship.memory import MemoryActorClass, MemoryAuthority
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor

__all__ = [
    "CONSTRAINT_ACTOR_CLASSES",
    "ENTITY_ACTOR_CLASSES",
    "ENTITY_AUTHORITIES",
    "MAX_CHANGED_FIELDS",
    "MAX_CHANGED_FIELD_CHARACTERS",
    "MAX_SOURCE_CAPABILITY_CHARACTERS",
    "MEETING_ACTOR_CLASSES",
    "MEMORY_ACTOR_CLASSES",
    "MEMORY_AUTHORITIES",
    "NON_MEMORY_CLASSIFICATION",
    "TASK_ACTOR_CLASSES",
    "InvalidRecordEventError",
    "RecordEvent",
    "RecordEventActorClass",
    "RecordEventAuthority",
    "RecordEventDraft",
    "RecordEventFamily",
    "RecordEventKind",
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

#: The classification every non-memory event carries (G1-EM-009). Only a
#: Relationship Memory event takes its classification from the committed
#: version it describes.
NON_MEMORY_CLASSIFICATION: Final = Classification.PRIVATE_LOCAL


class RecordEventFamily(StrEnum):
    """The twenty canonical record families the feed names (section 3.2).

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
        source_receipt_id=_optional_identifier(source_receipt_id, None, "source_receipt_id"),
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
