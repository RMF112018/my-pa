"""WP-RE-04 (FAST): the Entity-plane Record Event emitters, without a database.

What is decidable from typed values alone is proven here:

* seam S-A's event list per operation (`_outcome_events`, P2b E1-E10): the
  primary first, the derived drafts after it (G1-EM-001), each caused by the
  primary and carrying its receipt, actor, authority and capability -- the
  child operations' parent-Entity `updated` included (MR-05);
* `resolve_mention`'s observation shape per disposition (P2b E18);
* the family writes' `_account_for` shapes, predecessor included (E19-E33).

Placement -- after the ledger INSERT, never on replay -- needs the database and
is proven in `tests/database/test_entity_record_events.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from my_pa.application.entity_authoring import EntityAuthoringService
from my_pa.application.entity_family_writes import EntityFamilyWriteService
from my_pa.application.entity_governance import (
    EntityGovernanceService,
    ResolveMentionCommand,
    _resolution_shape,
)
from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.contracts.ports import EntityWriteRequest, InitialAlias, InitialIdentifier
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventAuthority,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.relationship.authoring import EntityWriteOperation
from my_pa.domain.relationship.entity import (
    AliasType,
    EntityStatus,
    EntityType,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityObservation,
    MutationAuthority,
    MutationRecordFamily,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.proposal_validation import ResolutionDisposition
from my_pa.domain.relationship.resolution import EntityResolution
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.entity_authoring import _Outcome, _outcome_events
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_entityevents0001"
ENTITY = "ent_entityevents0001"
TARGET_ALIAS = "eals_entityevents0001"
TARGET_IDENTIFIER = "xid_entityevents0001"
WHEN = datetime(2026, 9, 29, 12, tzinfo=UTC)
MENTION = "eobs_entityevents0001"


def _request(operation: EntityWriteOperation, **fields: Any) -> EntityWriteRequest:  # noqa: ANN401
    base: dict[str, Any] = {
        "capability": "entities.test",
        "principal_id": PRINCIPAL,
        "entity_id": ENTITY,
        "expected_version": 3,
        "idempotency_key": "key-entity-events",
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "at": WHEN,
    }
    base.update(fields)
    return EntityAuthoringService()._request(operation, **base)


def _outcome(**fields: Any) -> _Outcome:  # noqa: ANN401
    base: dict[str, Any] = {
        "entity_id": ENTITY,
        "entity_version": 4,
        "entity_status": EntityStatus.ACTIVE,
        "prior_version": None,
        "new_version": 1,
        "before_state": {},
        "event_kind": RecordEventKind.CREATED,
        "changed_fields": ("state",),
    }
    base.update(fields)
    return _Outcome(**base)


def _shape(events: list[Any]) -> list[tuple[RecordEventFamily, str, RecordEventKind, int]]:
    return [
        (event.record_family, event.record_id, event.event_kind, event.record_version)
        for event in events
    ]


def _assert_one_write(request: EntityWriteRequest, events: list[Any]) -> None:
    """Every draft of one write shares its receipt and provenance; derived ones name the primary."""
    primary, *derived = events
    assert primary.causation_event_id is None
    for event in events:
        assert event.source_receipt_id == request.event_id
        assert event.correlation_id == request.correlation_id
        assert event.principal_id == PRINCIPAL
        assert event.occurred_at == WHEN
    for event in derived:
        assert event.causation_event_id == primary.event_id
        assert event.source_capability == primary.source_capability
        assert event.actor_class is primary.actor_class
        assert event.authority is primary.authority


def test_a_create_stages_the_entity_then_its_aliases_then_its_identifiers() -> None:
    """E1: +1 alias per initial alias and +1 identifier per initial identifier, v1."""
    aliases = tuple(
        InitialAlias(
            alias_id=issue_identifier(IdKind.ENTITY_ALIAS),
            alias_type=AliasType.NICKNAME,
            normalized_value=f"alias {index}",
            display_value=f"Alias {index}",
        )
        for index in range(2)
    )
    identifier = InitialIdentifier(
        identifier_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value="someone@example.test",
        display_value="someone@example.test",
    )
    request = _request(
        EntityWriteOperation.CREATE,
        entity_id=None,
        expected_version=None,
        minted_entity_id=ENTITY,
        entity_type=EntityType.PERSON,
        display_name="Someone",
        canonical_name="someone",
        initial_aliases=aliases,
        initial_identifiers=(identifier,),
    )
    events = _outcome_events(
        request,
        _outcome(
            entity_version=1,
            record_id=ENTITY,
            changed_fields=("canonical_name", "display_name", "entity_type", "status"),
        ),
    )
    assert _shape(events) == [
        (RecordEventFamily.ENTITY, ENTITY, RecordEventKind.CREATED, 1),
        (RecordEventFamily.ENTITY_ALIAS, aliases[0].alias_id, RecordEventKind.CREATED, 1),
        (RecordEventFamily.ENTITY_ALIAS, aliases[1].alias_id, RecordEventKind.CREATED, 1),
        (
            RecordEventFamily.ENTITY_IDENTIFIER,
            identifier.identifier_id,
            RecordEventKind.CREATED,
            1,
        ),
    ]
    assert events[0].changed_fields == ("canonical_name", "display_name", "entity_type", "status")
    _assert_one_write(request, events)


def test_an_update_that_kept_a_former_name_stages_the_alias_it_wrote() -> None:
    """E2: +the FORMER_NAME alias, caused by the Entity `updated`."""
    child = issue_identifier(IdKind.ENTITY_ALIAS)
    request = _request(
        EntityWriteOperation.UPDATE,
        canonical_name="someone else",
        minted_child_id=child,
    )
    events = _outcome_events(
        request,
        _outcome(
            record_id=ENTITY,
            prior_version=3,
            new_version=4,
            event_kind=RecordEventKind.UPDATED,
            changed_fields=("canonical_name",),
            child_id=child,
        ),
    )
    assert _shape(events) == [
        (RecordEventFamily.ENTITY, ENTITY, RecordEventKind.UPDATED, 4),
        (RecordEventFamily.ENTITY_ALIAS, child, RecordEventKind.CREATED, 1),
    ]
    _assert_one_write(request, events)


def test_an_update_that_wrote_no_former_name_stages_the_entity_alone() -> None:
    request = _request(EntityWriteOperation.UPDATE, display_name="Someone")
    events = _outcome_events(
        request,
        _outcome(record_id=ENTITY, prior_version=3, new_version=4),
    )
    assert [event.record_family for event in events] == [RecordEventFamily.ENTITY]


@pytest.mark.parametrize("operation", [EntityWriteOperation.ARCHIVE, EntityWriteOperation.RESTORE])
def test_archive_and_restore_stage_one_event(operation: EntityWriteOperation) -> None:
    """E3/E4: the Entity is the ledger row's record; nothing else changed."""
    request = _request(operation, reason="because")
    events = _outcome_events(
        request,
        _outcome(
            record_id=ENTITY,
            prior_version=3,
            new_version=4,
            event_kind=RecordEventKind.STATE_CHANGED,
            changed_fields=("archived_from_status", "status"),
        ),
    )
    assert _shape(events) == [(RecordEventFamily.ENTITY, ENTITY, RecordEventKind.STATE_CHANGED, 4)]


@pytest.mark.parametrize(
    ("operation", "family", "fields"),
    [
        (
            EntityWriteOperation.BIND_IDENTIFIER,
            RecordEventFamily.ENTITY_IDENTIFIER,
            {
                "namespace": ExternalIdentifierNamespace.EMAIL,
                "normalized_value": "x@example.test",
                "display_value": "x@example.test",
            },
        ),
        (
            EntityWriteOperation.ADD_ALIAS,
            RecordEventFamily.ENTITY_ALIAS,
            {
                "alias_type": AliasType.NICKNAME,
                "normalized_value": "x",
                "display_value": "X",
            },
        ),
    ],
)
def test_a_child_addition_also_stages_the_entity_it_advanced(
    operation: EntityWriteOperation, family: RecordEventFamily, fields: dict[str, Any]
) -> None:
    """E5/E8 (MR-05): +`entity` `updated` at the advanced version, `("version",)`."""
    kind = (
        IdKind.EXTERNAL_IDENTIFIER
        if family is RecordEventFamily.ENTITY_IDENTIFIER
        else (IdKind.ENTITY_ALIAS)
    )
    child = issue_identifier(kind)
    request = _request(operation, minted_child_id=child, **fields)
    events = _outcome_events(request, _outcome(record_id=child, entity_version=4, child_id=child))
    assert _shape(events) == [
        (family, child, RecordEventKind.CREATED, 1),
        (RecordEventFamily.ENTITY, ENTITY, RecordEventKind.UPDATED, 4),
    ]
    assert events[1].changed_fields == ("version",)
    _assert_one_write(request, events)


@pytest.mark.parametrize(
    ("operation", "family", "target"),
    [
        (
            EntityWriteOperation.RETIRE_IDENTIFIER,
            RecordEventFamily.ENTITY_IDENTIFIER,
            TARGET_IDENTIFIER,
        ),
        (EntityWriteOperation.RETIRE_ALIAS, RecordEventFamily.ENTITY_ALIAS, TARGET_ALIAS),
    ],
)
def test_a_child_retirement_also_stages_the_entity_it_advanced(
    operation: EntityWriteOperation, family: RecordEventFamily, target: str
) -> None:
    """E6/E9 (MR-05)."""
    request = _request(operation, target_child_id=target, target_child_version=2, reason="gone")
    events = _outcome_events(
        request,
        _outcome(
            record_id=target,
            prior_version=2,
            new_version=3,
            event_kind=RecordEventKind.STATE_CHANGED,
            changed_fields=("retired_at", "state"),
        ),
    )
    assert _shape(events) == [
        (family, target, RecordEventKind.STATE_CHANGED, 3),
        (RecordEventFamily.ENTITY, ENTITY, RecordEventKind.UPDATED, 4),
    ]
    _assert_one_write(request, events)


@pytest.mark.parametrize(
    ("operation", "family", "target", "kind", "fields", "superseded_by"),
    [
        (
            EntityWriteOperation.SUPERSEDE_IDENTIFIER,
            RecordEventFamily.ENTITY_IDENTIFIER,
            TARGET_IDENTIFIER,
            IdKind.EXTERNAL_IDENTIFIER,
            {
                "namespace": ExternalIdentifierNamespace.EMAIL,
                "normalized_value": "y@example.test",
                "display_value": "y@example.test",
            },
            "superseded_by_identifier_id",
        ),
        (
            EntityWriteOperation.SUPERSEDE_ALIAS,
            RecordEventFamily.ENTITY_ALIAS,
            TARGET_ALIAS,
            IdKind.ENTITY_ALIAS,
            {
                "alias_type": AliasType.NICKNAME,
                "normalized_value": "y",
                "display_value": "Y",
            },
            "superseded_by_alias_id",
        ),
    ],
)
def test_a_supersession_stages_replacement_then_predecessor_then_entity(
    operation: EntityWriteOperation,
    family: RecordEventFamily,
    target: str,
    kind: IdKind,
    fields: dict[str, Any],
    superseded_by: str,
) -> None:
    """E7/E10, in P2b's order: the replacement `created`, the predecessor
    `state_changed` at `target_child_version + 1`, then the Entity `updated`."""
    replacement = issue_identifier(kind)
    request = _request(
        operation,
        minted_child_id=replacement,
        target_child_id=target,
        target_child_version=5,
        **fields,
    )
    events = _outcome_events(
        request,
        _outcome(record_id=replacement, child_id=replacement, superseded_ids=(target,)),
    )
    assert _shape(events) == [
        (family, replacement, RecordEventKind.CREATED, 1),
        (family, target, RecordEventKind.STATE_CHANGED, 6),
        (RecordEventFamily.ENTITY, ENTITY, RecordEventKind.UPDATED, 4),
    ]
    assert events[1].changed_fields == ("retired_at", "state", superseded_by)
    _assert_one_write(request, events)


def test_a_review_promoted_write_names_review_decide_and_review_accepted() -> None:
    """OD-6 / RE-AC-047 for S-A: the ledger's capability is the writer's, not the request's."""
    request = _request(
        EntityWriteOperation.ARCHIVE,
        reason="accepted",
        authority=MutationAuthority.REVIEW_ACCEPTED,
        actor_class=ActorClass.REVIEW_PROMOTION,
    )
    (event,) = _outcome_events(
        request,
        _outcome(record_id=ENTITY, prior_version=3, new_version=4),
    )
    assert event.source_capability == "review.decide"
    assert event.actor_class is RecordEventActorClass.REVIEW_PROMOTION
    assert event.authority is RecordEventAuthority.REVIEW_ACCEPTED


@pytest.mark.parametrize(
    ("disposition", "kind", "fields"),
    [
        (
            ResolutionDisposition.LINK_EXISTING,
            RecordEventKind.UPDATED,
            ("entity_id", "resolution_version"),
        ),
        (
            ResolutionDisposition.CREATE_NEW,
            RecordEventKind.UPDATED,
            ("entity_id", "resolution_version"),
        ),
        (
            ResolutionDisposition.QUARANTINE,
            RecordEventKind.STATE_CHANGED,
            ("resolution_version", "state", "state_reason"),
        ),
        (ResolutionDisposition.REJECT, RecordEventKind.UPDATED, ("resolution_version",)),
        (ResolutionDisposition.DEFER, RecordEventKind.UPDATED, ("resolution_version",)),
    ],
)
def test_a_resolution_shape_names_what_the_decision_wrote(
    disposition: ResolutionDisposition, kind: RecordEventKind, fields: tuple[str, ...]
) -> None:
    """E18: the kind and fields `decide_observation` actually writes per disposition."""
    cause = issue_identifier(IdKind.RECORD_EVENT)
    shape = _resolution_shape(disposition, cause=cause)
    assert (shape.event_kind, shape.changed_fields) == (kind, fields)
    binds = disposition in (ResolutionDisposition.LINK_EXISTING, ResolutionDisposition.CREATE_NEW)
    assert shape.causation_event_id == (cause if binds else None)


class _RecordingLedger:
    """Only what `_account_for` touches: the ledger append, with its shape."""

    def __init__(self) -> None:
        self.shapes: list[Any] = []

    def record_mutation_event(self, principal_id: str, event: Any, *, shape: Any = None) -> None:  # noqa: ANN401
        self.shapes.append(shape)


def _account(ledger: _RecordingLedger, **fields: Any) -> None:  # noqa: ANN401
    base: dict[str, Any] = {
        "capability": Capability.ENTITIES_NAMES_SUPERSEDE,
        "family": MutationRecordFamily.NAME,
        "record_id": "enam_entityevents0002",
        "prior_version": None,
        "new_version": 1,
        "state": "active",
        "before_state": None,
        "superseded_id": None,
        "digest": "0" * 64,
        "idempotency_key": "key-entity-family",
        "principal_id": PRINCIPAL,
        "audit_id": issue_identifier(IdKind.AUDIT),
        "at": WHEN,
        "authority": MutationAuthority.USER_CONFIRMED_ASSERTION,
        "actor_class": ActorClass.USER,
    }
    base.update(fields)
    EntityFamilyWriteService()._account_for(ledger, **base)


def test_a_family_addition_is_a_create_with_no_predecessor() -> None:
    """E19/E22/E25/E28/E31."""
    ledger = _RecordingLedger()
    _account(ledger)
    (shape,) = ledger.shapes
    assert (shape.event_kind, shape.changed_fields, shape.superseded) == (
        RecordEventKind.CREATED,
        ("entity_id", "state"),
        None,
    )


def test_a_family_correction_names_its_predecessor_at_the_superseded_version() -> None:
    """E20 and the four revises (G1-EM-001(b)): `(predecessor, expected_version + 1)`."""
    ledger = _RecordingLedger()
    _account(
        ledger,
        superseded_id="enam_entityevents0001",
        superseded_version=4,
        before_state={"record_id": "enam_entityevents0001", "version": 3},
    )
    (shape,) = ledger.shapes
    assert shape.event_kind is RecordEventKind.CREATED
    assert shape.superseded == ("enam_entityevents0001", 4)
    assert shape.superseded_fields == ("state",)


def test_a_family_retirement_is_a_state_change() -> None:
    """E21/E24/E27/E30/E33."""
    ledger = _RecordingLedger()
    _account(ledger, prior_version=2, new_version=3, state="retired")
    (shape,) = ledger.shapes
    assert (shape.event_kind, shape.changed_fields, shape.superseded) == (
        RecordEventKind.STATE_CHANGED,
        ("state",),
        None,
    )


# ---- G1-EM-002: resolve_mention's unledgered Entity create -------------------


def _resolve_over(world: World, disposition: ResolutionDisposition, **extra: Any) -> Any:  # noqa: ANN401
    uow = FakeUnitOfWork(world)
    with uow:
        resolver = EntityResolutionService(uow.entities)

        def resolve(
            observation: EntityObservation, refused: frozenset[str], at: datetime
        ) -> EntityResolution:
            return resolver.resolve(
                observation.principal_id,
                ResolutionRequest(
                    raw_reference=observation.observed_value, at=at, refused_entity_ids=refused
                ),
            )

        return EntityGovernanceService(uow.entities).resolve_mention(
            ResolveMentionCommand(
                principal_id=PRINCIPAL,
                observation_id=MENTION,
                expected_resolution_version=0,
                disposition=disposition,
                idempotency_key="resolve-entity-events",
                **extra,
            ),
            resolve=resolve,
            at=WHEN,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            decided_by=PRINCIPAL,
            actor_class=ActorClass.USER,
        )


@pytest.fixture
def mentioned(world: World) -> World:
    FakeUnitOfWork(world).entities.record_observation(
        PRINCIPAL,
        EntityObservation(
            observation_id=MENTION,
            principal_id=PRINCIPAL,
            kind=ObservationKind.MESSAGE_PARTICIPANT,
            observed_value="Nobody Known",
            normalized_value=normalize_name("Nobody Known"),
            mention_display_name="Nobody Known",
            source_id="src_entityevents0001",
            source_object_id="obj_entityevents0001",
            source_version_id="ver_entityevents0001",
            observed_at=WHEN,
            recorded_at=WHEN,
        ),
    )
    return world


def test_create_new_stages_the_entity_it_minted(mentioned: World) -> None:
    """The Entity `created` at version 1, receipt the resolve ledger row, into the
    unit of work's own buffer (the fake ledger's S-C seam stages nothing)."""
    outcome = _resolve_over(
        mentioned,
        ResolutionDisposition.CREATE_NEW,
        entity_type=EntityType.PERSON,
        canonical_name="Nobody Known",
    )
    assert len(mentioned.record_events) == 1
    (event,) = mentioned.record_events
    assert (event.record_family, event.record_id, event.event_kind, event.record_version) == (
        RecordEventFamily.ENTITY,
        outcome.entity_id,
        RecordEventKind.CREATED,
        1,
    )
    assert event.source_receipt_id == outcome.mutation_event_id
    assert event.source_capability == "entities.unresolved_mentions.resolve"
    assert event.changed_fields == ("canonical_name", "display_name", "entity_type", "status")


@pytest.mark.parametrize(
    "disposition", [ResolutionDisposition.DEFER, ResolutionDisposition.QUARANTINE]
)
def test_a_decision_that_creates_nothing_stages_no_entity(
    mentioned: World, disposition: ResolutionDisposition
) -> None:
    _resolve_over(mentioned, disposition, reason="not yet")
    assert mentioned.record_events == []
