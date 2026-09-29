"""WP-RE-01: the Record Event domain carrier (RE-AC-001..003, domain halves).

What is proved here, without a database:

* **RE-AC-001 -- opaque identity.** `event_id` is an `rcev_` identifier and
  nothing else; `principal_id` is a `prn_`; `record_id` and `source_receipt_id`
  are opaque identifiers of any kind (never a path, URL or free text);
  `causation_event_id` is another `rcev_` and never the event itself;
  `correlation_id` is a `corr_`. `RecordEventDraft.issue` mints a fresh `rcev_`
  identifier at staging time.
* **RE-AC-002 -- sequence starts positive.** `sequence_number >= 1` (and
  `record_version >= 1`); a bool is not an integer here.
* **RE-AC-003 -- changed_fields sorted/unique/bounded.** Sorted, unique, each
  token 1..64 lower_snake characters, at most 64 tokens.

Plus the closed vocabularies (20 families, 3 kinds, 4 actor classes, 6
authorities), the section 3.4 actor maps, the non-memory classification, UTC
normalization and immutability. Each guard has its own test so a prove-red that
disables one guard reddens exactly the test named for it.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, parse_identifier
from my_pa.domain.identity.operation import Capability
from my_pa.domain.meeting.model import MeetingActor
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.domain.record_events import (
    CONSTRAINT_ACTOR_CLASSES,
    ENTITY_ACTOR_CLASSES,
    ENTITY_AUTHORITIES,
    MAX_CHANGED_FIELDS,
    MEETING_ACTOR_CLASSES,
    MEMORY_ACTOR_CLASSES,
    MEMORY_AUTHORITIES,
    NON_MEMORY_CLASSIFICATION,
    TASK_ACTOR_CLASSES,
    InvalidRecordEventError,
    RecordEvent,
    RecordEventActorClass,
    RecordEventAuthority,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.relationship.governance import ActorClass, MutationAuthority
from my_pa.domain.relationship.memory import MemoryActorClass, MemoryAuthority
from my_pa.domain.task.history import TaskMutationActor

PRINCIPAL = "prn_recordevent0001"
EVENT = "rcev_recordevent0001"
OTHER_EVENT = "rcev_recordevent0002"
RECORD = "tsk_recordevent0001"
RECEIPT = "thst_recordevent0001"
CORRELATION = "corr_recordevent0001"
WHEN = datetime(2026, 9, 29, 12, tzinfo=UTC)


def _fields(**overrides: object) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "event_id": EVENT,
        "principal_id": PRINCIPAL,
        "record_family": RecordEventFamily.TASK,
        "record_id": RECORD,
        "event_kind": RecordEventKind.UPDATED,
        "record_version": 2,
        "changed_fields": ("title", "version"),
        "source_capability": Capability.TASKS_UPDATE.value,
        "actor_class": RecordEventActorClass.PRINCIPAL,
        "classification": Classification.PRIVATE_LOCAL,
        "occurred_at": WHEN,
        "source_receipt_id": RECEIPT,
        "authority": None,
        "correlation_id": CORRELATION,
        "causation_event_id": None,
    }
    fields.update(overrides)
    return fields


def _draft(**overrides: object) -> RecordEventDraft:
    return RecordEventDraft(**_fields(**overrides))


def _event(**overrides: object) -> RecordEvent:
    base = _fields()
    base.update(sequence_number=1, recorded_at=WHEN)
    base.update(overrides)
    return RecordEvent(**base)


# ---- RE-AC-001: opaque identity ---------------------------------------------


def test_the_record_event_identifier_kind_is_rcev() -> None:
    assert IdKind.RECORD_EVENT.value == "rcev"


def test_a_well_formed_draft_and_event_are_accepted() -> None:
    draft = _draft()
    event = RecordEvent.from_draft(draft, sequence_number=7, recorded_at=WHEN)
    assert event.event_id == EVENT
    assert event.sequence_number == 7
    assert event.changed_fields == ("title", "version")


def test_issue_mints_a_fresh_record_event_identifier_at_staging_time() -> None:
    fields = _fields()
    del fields["event_id"]
    first = RecordEventDraft.issue(**fields)
    second = RecordEventDraft.issue(**fields)
    assert parse_identifier(first.event_id)[0] is IdKind.RECORD_EVENT
    assert first.event_id != second.event_id


@pytest.mark.parametrize("value", ["tsk_recordevent0001", "rcev_short", "rcev_bad/path00", ""])
def test_event_id_must_be_a_record_event_identifier(value: str) -> None:
    with pytest.raises(InvalidRecordEventError, match="event_id"):
        _draft(event_id=value)


@pytest.mark.parametrize("value", ["tsk_recordevent0001", "prn_x", None])
def test_principal_id_must_be_a_principal_identifier(value: object) -> None:
    with pytest.raises(InvalidRecordEventError, match="principal_id"):
        _draft(principal_id=value)


@pytest.mark.parametrize(
    "value",
    ["/Users/someone/notes.txt", "https://example.com/x", "Buy milk", "zzzz_recordevent0001"],
)
def test_record_id_must_be_an_opaque_identifier(value: str) -> None:
    with pytest.raises(InvalidRecordEventError, match="record_id"):
        _draft(record_id=value)


def test_source_receipt_id_when_present_must_be_an_opaque_identifier() -> None:
    assert _draft(source_receipt_id=None).source_receipt_id is None
    with pytest.raises(InvalidRecordEventError, match="source_receipt_id"):
        _draft(source_receipt_id="receipt 1")


def test_causation_event_id_when_present_must_be_a_record_event_identifier() -> None:
    assert _draft(causation_event_id=OTHER_EVENT).causation_event_id == OTHER_EVENT
    with pytest.raises(InvalidRecordEventError, match="causation_event_id"):
        _draft(causation_event_id=RECORD)


def test_an_event_is_never_its_own_cause() -> None:
    with pytest.raises(InvalidRecordEventError, match="names the event itself"):
        _draft(causation_event_id=EVENT)


def test_correlation_id_when_present_must_be_a_correlation_identifier() -> None:
    assert _draft(correlation_id=None).correlation_id is None
    with pytest.raises(InvalidRecordEventError, match="correlation_id"):
        _draft(correlation_id=RECORD)


# ---- RE-AC-002: sequence and version start positive -------------------------


def test_sequence_number_one_is_the_first_accepted_value() -> None:
    assert _event(sequence_number=1).sequence_number == 1


@pytest.mark.parametrize("value", [0, -1, True, 1.0, "1"])
def test_sequence_number_must_be_a_positive_integer(value: object) -> None:
    with pytest.raises(InvalidRecordEventError, match="sequence_number"):
        _event(sequence_number=value)


@pytest.mark.parametrize("value", [0, -3, False, "2"])
def test_record_version_must_be_a_positive_integer(value: object) -> None:
    with pytest.raises(InvalidRecordEventError, match="record_version"):
        _draft(record_version=value)


# ---- RE-AC-003: changed_fields sorted / unique / bounded --------------------


def test_changed_fields_may_be_empty_and_are_kept_as_a_tuple() -> None:
    assert _draft(changed_fields=()).changed_fields == ()
    assert _draft(changed_fields=["a", "b"]).changed_fields == ("a", "b")


def test_changed_fields_must_be_sorted() -> None:
    with pytest.raises(InvalidRecordEventError, match="not sorted"):
        _draft(changed_fields=("version", "title"))


def test_changed_fields_must_be_unique() -> None:
    with pytest.raises(InvalidRecordEventError, match="duplicate"):
        _draft(changed_fields=("title", "title"))


@pytest.mark.parametrize(
    "token", ["", "Title", "due-date", "1st", "_leading", "a" * 65, "with space", "é"]
)
def test_each_changed_field_is_one_to_sixty_four_lower_snake_characters(token: str) -> None:
    with pytest.raises(InvalidRecordEventError, match="lower_snake"):
        _draft(changed_fields=(token,))


def test_a_sixty_four_character_token_is_accepted() -> None:
    token = "a" * 64
    assert _draft(changed_fields=(token,)).changed_fields == (token,)


def test_changed_fields_hold_at_most_sixty_four_tokens() -> None:
    at_the_bound = tuple(sorted(f"field_{index:02d}" for index in range(MAX_CHANGED_FIELDS)))
    assert len(_draft(changed_fields=at_the_bound).changed_fields) == 64
    over = tuple(sorted(f"field_{index:02d}" for index in range(MAX_CHANGED_FIELDS + 1)))
    with pytest.raises(InvalidRecordEventError, match="more than 64"):
        _draft(changed_fields=over)


def test_changed_fields_is_a_sequence_not_a_string() -> None:
    with pytest.raises(InvalidRecordEventError, match="sequence of field names"):
        _draft(changed_fields="title")


# ---- source_capability ------------------------------------------------------


def test_every_capability_value_is_an_accepted_source_capability() -> None:
    for capability in Capability:
        assert _draft(source_capability=capability.value).source_capability == capability.value


def test_a_bounded_internal_token_is_an_accepted_source_capability() -> None:
    assert _draft(source_capability="reenrichment.rebind").source_capability == (
        "reenrichment.rebind"
    )


@pytest.mark.parametrize(
    "value", ["", " ", "Tasks.Create", "tasks create", "tasks..create", "a" * 129, None]
)
def test_source_capability_is_a_bounded_operation_name(value: object) -> None:
    with pytest.raises(InvalidRecordEventError, match="source_capability"):
        _draft(source_capability=value)


# ---- closed vocabularies ----------------------------------------------------


def test_the_family_vocabulary_is_exactly_the_twenty_named_families() -> None:
    assert {member.value for member in RecordEventFamily} == {
        "task",
        "commitment",
        "project",
        "entity",
        "entity_identifier",
        "entity_alias",
        "entity_assignment",
        "entity_relationship",
        "entity_observation",
        "entity_name",
        "entity_address",
        "entity_communication_method",
        "entity_project_participation",
        "person_organization_affiliation",
        "relationship_memory",
        "constraint",
        "constraint_category",
        "project_controls_settings",
        "meeting",
        "meeting_series",
    }
    assert len(RecordEventFamily) == 20


def test_the_kind_vocabulary_is_created_updated_state_changed() -> None:
    assert {member.value for member in RecordEventKind} == {"created", "updated", "state_changed"}


def test_the_actor_class_vocabulary_is_the_four_classes() -> None:
    assert {member.value for member in RecordEventActorClass} == {
        "principal",
        "assistant",
        "system",
        "review_promotion",
    }


def test_the_authority_vocabulary_is_the_union_of_the_two_source_plane_authorities() -> None:
    union = {member.value for member in MutationAuthority} | {
        member.value for member in MemoryAuthority
    }
    assert {member.value for member in RecordEventAuthority} == union
    assert len(RecordEventAuthority) == 6


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("record_family", "tasks"),
        ("event_kind", "deleted"),
        ("actor_class", "model"),
        ("classification", "public"),
        ("authority", "model_inference"),
    ],
)
def test_a_value_outside_a_closed_vocabulary_is_refused(field: str, value: str) -> None:
    with pytest.raises(InvalidRecordEventError, match=field):
        _draft(**{field: value})


def test_closed_values_given_as_strings_are_normalized_to_members() -> None:
    draft = _draft(record_family="meeting", authority="review_accepted")
    assert draft.record_family is RecordEventFamily.MEETING
    assert draft.authority is RecordEventAuthority.REVIEW_ACCEPTED


# ---- section 3.4 actor maps and authority maps ------------------------------


def test_the_task_actor_map_is_total_and_one_to_one() -> None:
    assert set(TASK_ACTOR_CLASSES) == set(TaskMutationActor)
    assert {key.value: value.value for key, value in TASK_ACTOR_CLASSES.items()} == {
        "principal": "principal",
        "assistant": "assistant",
        "system": "system",
    }


def test_the_constraint_actor_map_is_total_and_one_to_one() -> None:
    assert set(CONSTRAINT_ACTOR_CLASSES) == set(ConstraintMutationActor)
    assert all(key.value == value.value for key, value in CONSTRAINT_ACTOR_CLASSES.items())


def test_the_meeting_actor_map_is_total_and_one_to_one() -> None:
    assert set(MEETING_ACTOR_CLASSES) == set(MeetingActor)
    assert all(key.value == value.value for key, value in MEETING_ACTOR_CLASSES.items())


def test_the_entity_actor_map_is_total() -> None:
    assert dict(ENTITY_ACTOR_CLASSES) == {
        ActorClass.USER: RecordEventActorClass.PRINCIPAL,
        ActorClass.REVIEW_PROMOTION: RecordEventActorClass.REVIEW_PROMOTION,
        ActorClass.SYSTEM_DETERMINISTIC: RecordEventActorClass.SYSTEM,
    }


def test_the_memory_actor_map_is_total() -> None:
    assert dict(MEMORY_ACTOR_CLASSES) == {
        MemoryActorClass.USER: RecordEventActorClass.PRINCIPAL,
        MemoryActorClass.REVIEW_PROMOTION: RecordEventActorClass.REVIEW_PROMOTION,
        MemoryActorClass.SYSTEM_DETERMINISTIC: RecordEventActorClass.SYSTEM,
    }


def test_the_authority_maps_preserve_each_source_spelling() -> None:
    assert set(ENTITY_AUTHORITIES) == set(MutationAuthority)
    assert set(MEMORY_AUTHORITIES) == set(MemoryAuthority)
    for source, target in (*ENTITY_AUTHORITIES.items(), *MEMORY_AUTHORITIES.items()):
        assert source.value == target.value


def test_the_maps_are_read_only() -> None:
    with pytest.raises(TypeError):
        TASK_ACTOR_CLASSES[TaskMutationActor.SYSTEM] = RecordEventActorClass.PRINCIPAL  # type: ignore[index]


def test_the_non_memory_classification_is_private_local() -> None:
    assert NON_MEMORY_CLASSIFICATION is Classification.PRIVATE_LOCAL


# ---- timestamps and immutability --------------------------------------------


def test_occurred_at_must_be_timezone_aware() -> None:
    with pytest.raises(InvalidRecordEventError, match="occurred_at"):
        _draft(occurred_at=datetime(2026, 9, 29, 12))


def test_recorded_at_must_be_timezone_aware() -> None:
    with pytest.raises(InvalidRecordEventError, match="recorded_at"):
        _event(recorded_at=datetime(2026, 9, 29, 12))


def test_timestamps_are_normalized_to_utc() -> None:
    offset = datetime(2026, 9, 29, 8, tzinfo=timezone(timedelta(hours=-4)))
    event = _event(occurred_at=offset, recorded_at=offset)
    assert event.occurred_at == WHEN
    assert event.occurred_at.tzinfo is UTC
    assert event.recorded_at.tzinfo is UTC


def test_a_draft_is_immutable_once_built() -> None:
    draft = _draft()
    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.record_version = 3  # type: ignore[misc]


def test_a_draft_carries_no_sequence_number_and_no_recorded_at() -> None:
    names = {field.name for field in dataclasses.fields(RecordEventDraft)}
    assert "sequence_number" not in names
    assert "recorded_at" not in names


def test_the_carrier_holds_no_payload_field() -> None:
    """RE-I-007: the carrier's field set is metadata only (the 17 columns)."""
    assert {field.name for field in dataclasses.fields(RecordEvent)} == {
        "event_id",
        "principal_id",
        "sequence_number",
        "record_family",
        "record_id",
        "event_kind",
        "record_version",
        "changed_fields",
        "source_capability",
        "source_receipt_id",
        "actor_class",
        "authority",
        "classification",
        "correlation_id",
        "causation_event_id",
        "occurred_at",
        "recorded_at",
    }
