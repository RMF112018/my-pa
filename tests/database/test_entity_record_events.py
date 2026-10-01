"""WP-RE-04: Entity-plane Record Events on a real database (RE-AC-044..046).

Marked `database` and routed to `database-current-head`. Every write runs inside
the production `SqlAlchemyUnitOfWork`, through `uow.entities` -- so what is
checked is the unit of work's own stager injected into `SqlEntityRepository`,
the seam staging on the applied branch, and the exit flush committing the feed
with the canonical change:

* **S-A** (`admit_mutation`, P2b E1-E10): the primary event and its derived
  drafts (G1-EM-001) -- a create's children, the FORMER_NAME alias, a
  supersession's predecessor, and the parent Entity every child operation
  advances (MR-05), in P2b's order, each caused by the primary;
* **S-B** (`_append_mutation`, E11-E16);
* **S-C** (`record_mutation_event`, E17-E33): the family writes with their
  predecessors, and observations at their feed version (T-002);
* **G1-EM-002**: `resolve_mention`'s `create_new` Entity, cause of the
  observation event;
* **RE-AC-046**: a replay stages nothing and advances no sequence -- including
  the silent same-digest `return` inside `record_mutation_event`.

Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select

from my_pa.application.commands import (
    AddEntityAddress,
    AddEntityCommunicationMethod,
    AddEntityName,
    CreateEntityAffiliation,
    CreateEntityAssignment,
    CreateEntityParticipation,
    EndEntityAffiliation,
    RetireEntityName,
    ReviseEntityAffiliation,
    SupersedeEntityName,
)
from my_pa.application.entity_authoring import EntityAuthoringService, NamedValue
from my_pa.application.entity_directed import EntityDirectedService
from my_pa.application.entity_family_writes import EntityFamilyWriteService
from my_pa.application.entity_governance import (
    EntityGovernanceService,
    ObserveCommand,
    ResolveMentionCommand,
)
from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.contracts.ports import AssignmentWriteRequest, RelationshipWriteRequest
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import EntityEventShape, RecordEventKind
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    AliasType,
    AssignmentType,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    DirectedWriteOperation,
    Entity,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    NameTypeCode,
    ParticipationStatusCode,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityMutationEvent,
    EntityObservation,
    MutationAuthority,
    MutationRecordFamily,
    ObservationAuthority,
    ObservationKind,
    ResolutionDisposition,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.resolution import EntityResolution
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.tables import (
    entities,
    entity_mutation_events,
    entity_observations,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database

PRINCIPAL: Final = "prn_rcevwp04aaaa0001"
PERSON: Final = "ent_rcevwp04aaaa0001"
ORGANIZATION: Final = "ent_rcevwp04aaaa0002"
PROJECT: Final = "ent_rcevwp04aaaa0003"
MENTION: Final = "eobs_rcevwp04aaaa0001"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)


def _entity(entity_id: str, name: str, kind: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=kind,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """A person, an organization and a project, written without a feed.

    `SqlEntityRepository.create` writes no ledger row, and a repository built
    outside a unit of work stages into a buffer nothing flushes -- so the feed
    starts empty and every event below is one the code under test committed.
    """
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL, _entity(PERSON, "Alice Synthetic", EntityType.PERSON))
        repository.create(
            PRINCIPAL, _entity(ORGANIZATION, "Acme Synthetic", EntityType.ORGANIZATION)
        )
        repository.create(PRINCIPAL, _entity(PROJECT, "Synthetic Tower", EntityType.PROJECT))
    assert feed(migrated_engine, PRINCIPAL) == []
    return migrated_engine


@contextmanager
def unit(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    """One production unit of work: its exit flushes the feed with the change."""
    with SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)) as uow:
        yield uow  # type: ignore[misc]


def _context() -> dict[str, Any]:
    return {
        "principal_id": PRINCIPAL,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "at": WHEN,
    }


def _entity_version(engine: Engine, entity_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(entities.c.version).where(entities.c.entity_id == entity_id)
            ).scalar_one()
        )


def _shape(events: list[dict[str, Any]]) -> list[tuple[str, str, str, int]]:
    return [
        (event["record_family"], event["record_id"], event["event_kind"], event["record_version"])
        for event in events
    ]


def _assert_one_write(events: list[dict[str, Any]], receipt: str) -> None:
    """One ledger row's events: one receipt; every derived draft caused by the first."""
    primary, *derived = events
    assert primary["causation_event_id"] is None
    assert {event["source_receipt_id"] for event in events} == {receipt}
    assert all(event["causation_event_id"] == primary["event_id"] for event in derived)
    assert len({event["correlation_id"] for event in events}) == 1
    assert all(event["classification"] == "private_local" for event in events)


# ---- S-A: entities.* authoring (E1-E10) --------------------------------------


def test_an_entity_create_commits_the_entity_then_its_children(staged: Engine) -> None:
    """E1: the Entity `created`, then one `created` per initial alias and identifier."""
    with unit(staged) as uow:
        admitted = EntityAuthoringService().create(
            uow.entities,
            entity_type=EntityType.PERSON,
            display_name="Bea Synthetic",
            aliases=(NamedValue("nickname", "Bea"),),
            identifiers=(NamedValue("email", "bea@example.invalid"),),
            reason=None,
            idempotency_key="rcev-wp04-create-0001",
            **_context(),
        )
    events = feed(staged, PRINCIPAL)
    entity_id = admitted.receipt.entity_id
    assert [(e["record_family"], e["event_kind"], e["record_version"]) for e in events] == [
        ("entity", "created", 1),
        ("entity_alias", "created", 1),
        ("entity_identifier", "created", 1),
    ]
    assert events[0]["record_id"] == entity_id
    assert events[0]["changed_fields"] == [
        "canonical_name",
        "display_name",
        "entity_type",
        "status",
    ]
    assert events[0]["source_capability"] == "entities.create"
    assert events[0]["actor_class"] == "principal"
    assert events[0]["authority"] == "user_confirmed_assertion"
    _assert_one_write(events, admitted.receipt.event_id)
    assert_gap_free(staged, PRINCIPAL)


def test_a_canonical_rename_commits_the_update_and_the_former_name_alias(staged: Engine) -> None:
    """E2: the Entity `updated` names what changed; the FORMER_NAME alias follows it."""
    with unit(staged) as uow:
        admitted = EntityAuthoringService().update(
            uow.entities,
            entity_id=PERSON,
            expected_version=1,
            display_name="Alice Renamed",
            canonical_name="Alice Renamed",
            status=None,
            reason="renamed",
            idempotency_key="rcev-wp04-update-0001",
            **_context(),
        )
    events = feed(staged, PRINCIPAL)
    assert _shape(events) == [
        ("entity", PERSON, "updated", 2),
        ("entity_alias", str(admitted.receipt.child_id), "created", 1),
    ]
    assert events[0]["changed_fields"] == ["canonical_name", "display_name"]
    _assert_one_write(events, admitted.receipt.event_id)


def test_an_identical_update_is_a_version_only_change(staged: Engine) -> None:
    """G1-EM-010: the write still advanced the version, so the event says only that."""
    with unit(staged) as uow:
        EntityAuthoringService().update(
            uow.entities,
            entity_id=PERSON,
            expected_version=1,
            display_name="Alice Synthetic",
            canonical_name=None,
            status=None,
            reason="no change",
            idempotency_key="rcev-wp04-update-same",
            **_context(),
        )
    (event,) = feed(staged, PRINCIPAL)
    assert (event["event_kind"], event["record_version"], event["changed_fields"]) == (
        "updated",
        2,
        ["version"],
    )


def test_archive_and_restore_commit_state_changes(staged: Engine) -> None:
    """E3/E4."""
    service = EntityAuthoringService()
    with unit(staged) as uow:
        service.archive(
            uow.entities,
            entity_id=PERSON,
            expected_version=1,
            reason="archived",
            idempotency_key="rcev-wp04-archive-0001",
            **_context(),
        )
    with unit(staged) as uow:
        service.restore(
            uow.entities,
            entity_id=PERSON,
            expected_version=2,
            reason="restored",
            idempotency_key="rcev-wp04-restore-0001",
            **_context(),
        )
    events = feed(staged, PRINCIPAL)
    assert _shape(events) == [
        ("entity", PERSON, "state_changed", 2),
        ("entity", PERSON, "state_changed", 3),
    ]
    assert all(e["changed_fields"] == ["archived_from_status", "status"] for e in events)


def test_every_identifier_operation_also_commits_the_entity_it_advanced(staged: Engine) -> None:
    """E5-E7 and MR-05, in P2b's order: the identifier, [its predecessor,] the Entity."""
    service = EntityAuthoringService()
    with unit(staged) as uow:
        bound = service.bind_identifier(
            uow.entities,
            entity_id=PERSON,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="alice@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="rcev-wp04-bind-0001",
            **_context(),
        )
    first = bound.receipt.record_id
    with unit(staged) as uow:
        superseded = service.supersede_identifier(
            uow.entities,
            entity_id=PERSON,
            expected_version=2,
            identifier_id=first,
            expected_identifier_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="alice.two@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason="moved",
            idempotency_key="rcev-wp04-supersede-0001",
            **_context(),
        )
    replacement = superseded.receipt.record_id
    with unit(staged) as uow:
        retired = service.retire_identifier(
            uow.entities,
            entity_id=PERSON,
            expected_version=3,
            identifier_id=replacement,
            expected_identifier_version=1,
            reason="gone",
            idempotency_key="rcev-wp04-retire-0001",
            **_context(),
        )
    events = feed(staged, PRINCIPAL)
    assert _shape(events) == [
        ("entity_identifier", first, "created", 1),
        ("entity", PERSON, "updated", 2),
        ("entity_identifier", replacement, "created", 1),
        ("entity_identifier", first, "state_changed", 2),
        ("entity", PERSON, "updated", 3),
        ("entity_identifier", replacement, "state_changed", 2),
        ("entity", PERSON, "updated", 4),
    ]
    assert _entity_version(staged, PERSON) == 4
    for entity_event in (events[1], events[4], events[6]):
        assert entity_event["changed_fields"] == ["version"]
    assert events[3]["changed_fields"] == ["retired_at", "state", "superseded_by_identifier_id"]
    _assert_one_write(events[0:2], bound.receipt.event_id)
    _assert_one_write(events[2:5], superseded.receipt.event_id)
    _assert_one_write(events[5:7], retired.receipt.event_id)
    assert_gap_free(staged, PRINCIPAL)


def test_every_alias_operation_also_commits_the_entity_it_advanced(staged: Engine) -> None:
    """E8-E10 and MR-05."""
    service = EntityAuthoringService()
    with unit(staged) as uow:
        added = service.add_alias(
            uow.entities,
            entity_id=PERSON,
            expected_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Ally",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="rcev-wp04-alias-add-0001",
            **_context(),
        )
    first = added.receipt.record_id
    with unit(staged) as uow:
        superseded = service.supersede_alias(
            uow.entities,
            entity_id=PERSON,
            expected_version=2,
            alias_id=first,
            expected_alias_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Al",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason="shorter",
            idempotency_key="rcev-wp04-alias-supersede-0001",
            **_context(),
        )
    replacement = superseded.receipt.record_id
    with unit(staged) as uow:
        service.retire_alias(
            uow.entities,
            entity_id=PERSON,
            expected_version=3,
            alias_id=replacement,
            expected_alias_version=1,
            reason="gone",
            idempotency_key="rcev-wp04-alias-retire-0001",
            **_context(),
        )
    events = feed(staged, PRINCIPAL)
    assert _shape(events) == [
        ("entity_alias", first, "created", 1),
        ("entity", PERSON, "updated", 2),
        ("entity_alias", replacement, "created", 1),
        ("entity_alias", first, "state_changed", 2),
        ("entity", PERSON, "updated", 3),
        ("entity_alias", replacement, "state_changed", 2),
        ("entity", PERSON, "updated", 4),
    ]
    _assert_one_write(events[2:5], superseded.receipt.event_id)


def test_an_authoring_replay_commits_nothing(staged: Engine) -> None:
    """RE-AC-046 for S-A: `mutation_replay_for` answers before any write."""
    service = EntityAuthoringService()
    arguments: dict[str, Any] = {
        "entity_id": PERSON,
        "expected_version": 1,
        "alias_type": AliasType.NICKNAME,
        "display_value": "Ally",
        "effective_from": None,
        "effective_to": None,
        "evidence": (),
        "reason": None,
        "idempotency_key": "rcev-wp04-alias-replay",
    }
    with unit(staged) as uow:
        service.add_alias(uow.entities, **arguments, **_context())
    before = feed(staged, PRINCIPAL)
    with unit(staged) as uow:
        replayed = service.add_alias(uow.entities, **arguments, **_context())
    assert replayed.created is False
    assert feed(staged, PRINCIPAL) == before
    assert next_sequence(staged, PRINCIPAL) == len(before) + 1


def test_a_refused_authoring_write_commits_no_event(staged: Engine) -> None:
    """A stale write raises inside the block: the buffer goes with the rollback."""
    with pytest.raises(Exception), unit(staged) as uow:  # noqa: B017
        EntityAuthoringService().archive(
            uow.entities,
            entity_id=PERSON,
            expected_version=9,
            reason="stale",
            idempotency_key="rcev-wp04-archive-stale",
            **_context(),
        )
    assert feed(staged, PRINCIPAL) == []
    assert next_sequence(staged, PRINCIPAL) is None


# ---- S-B: directed writes (E11-E16) ------------------------------------------


def _assignment(**overrides: object) -> AssignmentWriteRequest:
    values: dict[str, Any] = {
        "operation": DirectedWriteOperation.CREATE,
        "assignment_id": None,
        "principal_id": PRINCIPAL,
        "entity_id": PERSON,
        "expected_entity_version": 1,
        "assignment_type": AssignmentType.PROJECT_ASSIGNMENT,
        "scope_entity_id": PROJECT,
        "expected_scope_version": 1,
        "expected_version": None,
        "role": "Lead",
        "discipline": None,
        "responsibility_class": None,
        "effective_from": None,
        "effective_to": None,
        "cleared": (),
        "evidence_refs": (),
        "reason": None,
        "idempotency_key": "rcev-wp04-assignment-0001",
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "server_received_at": WHEN,
    }
    values.update(overrides)
    return AssignmentWriteRequest(**values)


def _edge(**overrides: object) -> RelationshipWriteRequest:
    values: dict[str, Any] = {
        "operation": DirectedWriteOperation.CREATE,
        "relationship_id": None,
        "principal_id": PRINCIPAL,
        "from_entity_id": PERSON,
        "expected_from_version": 1,
        "relationship_type": EntityRelationshipType.WORKS_FOR,
        "to_entity_id": ORGANIZATION,
        "expected_to_version": 1,
        "scope_entity_id": None,
        "expected_scope_version": None,
        "expected_version": None,
        "effective_from": None,
        "effective_to": None,
        "cleared": (),
        "evidence_refs": (),
        "reason": None,
        "idempotency_key": "rcev-wp04-edge-0001",
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "server_received_at": WHEN,
    }
    values.update(overrides)
    return RelationshipWriteRequest(**values)


def test_assignment_create_revise_and_end_commit_their_events(staged: Engine) -> None:
    """E11-E13: created; updated with the typed difference; state_changed."""
    with unit(staged) as uow:
        created = uow.entities.create_assignment(_assignment())
    assignment_id = created.record_id
    with unit(staged) as uow:
        uow.entities.revise_assignment(
            _assignment(
                operation=DirectedWriteOperation.REVISE,
                assignment_id=assignment_id,
                expected_version=1,
                entity_id=None,
                assignment_type=None,
                scope_entity_id=None,
                expected_entity_version=None,
                expected_scope_version=None,
                role="Principal",
                idempotency_key="rcev-wp04-assignment-revise",
            )
        )
    with unit(staged) as uow:
        uow.entities.end_assignment(
            _assignment(
                operation=DirectedWriteOperation.END,
                assignment_id=assignment_id,
                expected_version=2,
                entity_id=None,
                assignment_type=None,
                scope_entity_id=None,
                expected_entity_version=None,
                expected_scope_version=None,
                role=None,
                effective_to=WHEN,
                reason="the assignment ended",
                idempotency_key="rcev-wp04-assignment-end",
            )
        )
    events = feed(staged, PRINCIPAL)
    assert _shape(events) == [
        ("entity_assignment", assignment_id, "created", 1),
        ("entity_assignment", assignment_id, "updated", 2),
        ("entity_assignment", assignment_id, "state_changed", 3),
    ]
    assert [event["changed_fields"] for event in events] == [
        ["assignment_type", "entity_id", "state"],
        ["role"],
        ["effective_to", "ended_at", "state"],
    ]
    assert events[0]["source_receipt_id"] == created.mutation_event_id
    assert events[0]["source_capability"] == "entities.assignments.create"


def test_relationship_create_and_end_commit_their_events(staged: Engine) -> None:
    """E14/E16."""
    with unit(staged) as uow:
        created = uow.entities.create_relationship(_edge())
    with unit(staged) as uow:
        uow.entities.end_relationship(
            _edge(
                operation=DirectedWriteOperation.END,
                relationship_id=created.record_id,
                expected_version=1,
                from_entity_id=None,
                to_entity_id=None,
                relationship_type=None,
                expected_from_version=None,
                expected_to_version=None,
                effective_to=WHEN,
                reason="the relationship ended",
                idempotency_key="rcev-wp04-edge-end",
            )
        )
    assert _shape(feed(staged, PRINCIPAL)) == [
        ("entity_relationship", created.record_id, "created", 1),
        ("entity_relationship", created.record_id, "state_changed", 2),
    ]


# ---- S-C: family writes (E19-E33) --------------------------------------------


def test_the_five_families_commit_created_events(staged: Engine) -> None:
    service = EntityFamilyWriteService()
    context = {"principal_id": PRINCIPAL, "audit_id": issue_identifier(IdKind.AUDIT), "at": WHEN}
    with unit(staged) as uow:
        name = service.add_name(
            uow.entities,
            AddEntityName(
                entity_id=PERSON,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Alice Synthetic",
                idempotency_key="rcev-wp04-name-add",
            ),
            **context,
        )
        address = service.add_address(
            uow.entities,
            AddEntityAddress(
                entity_id=PERSON,
                address_type_code=AddressTypeCode.BUSINESS,
                raw_value="1 Synthetic Way",
                idempotency_key="rcev-wp04-address-add",
            ),
            **context,
        )
        channel = service.add_communication_method(
            uow.entities,
            AddEntityCommunicationMethod(
                entity_id=PERSON,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="alice@example.test",
                idempotency_key="rcev-wp04-channel-add",
            ),
            **context,
        )
        participation = service.create_participation(
            uow.entities,
            CreateEntityParticipation(
                project_entity_id=PROJECT,
                participant_entity_id=PERSON,
                project_display_name="Alice on Synthetic Tower",
                role_basis_code=RoleBasisCode.CONTRACTUAL,
                stakeholder_side_code=StakeholderSideCode.DESIGN,
                stakeholder_class_code=StakeholderClassCode.CORE,
                relationship_status_code=ParticipationStatusCode.ACTIVE,
                idempotency_key="rcev-wp04-participation-add",
            ),
            **context,
        )
        affiliation = service.create_affiliation(
            uow.entities,
            CreateEntityAffiliation(
                person_entity_id=PERSON,
                affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
                idempotency_key="rcev-wp04-affiliation-add",
                organization_entity_id=ORGANIZATION,
                job_title="Engineer",
            ),
            **context,
        )
    events = feed(staged, PRINCIPAL)
    assert _shape(events) == [
        ("entity_name", name.record_id, "created", 1),
        ("entity_address", address.record_id, "created", 1),
        ("entity_communication_method", channel.record_id, "created", 1),
        ("entity_project_participation", participation.record_id, "created", 1),
        ("person_organization_affiliation", affiliation.record_id, "created", 1),
    ]
    assert all(event["changed_fields"] == ["entity_id", "state"] for event in events)
    assert [event["source_receipt_id"] for event in events] == [
        receipt.mutation_event_id
        for receipt in (name, address, channel, participation, affiliation)
    ]
    assert_gap_free(staged, PRINCIPAL)


def test_a_family_supersession_commits_the_successor_then_its_predecessor(
    staged: Engine,
) -> None:
    """E20 (G1-EM-001(b)): the predecessor at `expected_version + 1`, caused by the successor."""
    service = EntityFamilyWriteService()
    context = {"principal_id": PRINCIPAL, "audit_id": issue_identifier(IdKind.AUDIT), "at": WHEN}
    with unit(staged) as uow:
        added = service.add_name(
            uow.entities,
            AddEntityName(
                entity_id=PERSON,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Alice Synthetic",
                idempotency_key="rcev-wp04-name-add",
            ),
            **context,
        )
    with unit(staged) as uow:
        corrected = service.supersede_name(
            uow.entities,
            SupersedeEntityName(
                entity_name_id=added.record_id,
                expected_version=1,
                entity_id=PERSON,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Alice Synthetic Corrected",
                idempotency_key="rcev-wp04-name-supersede",
            ),
            **context,
        )
    with unit(staged) as uow:
        service.retire_name(
            uow.entities,
            RetireEntityName(
                entity_name_id=corrected.record_id,
                expected_version=1,
                idempotency_key="rcev-wp04-name-retire",
            ),
            **context,
        )
    events = feed(staged, PRINCIPAL)
    assert _shape(events) == [
        ("entity_name", added.record_id, "created", 1),
        ("entity_name", corrected.record_id, "created", 1),
        ("entity_name", added.record_id, "state_changed", 2),
        ("entity_name", corrected.record_id, "state_changed", 2),
    ]
    _assert_one_write(events[1:3], corrected.mutation_event_id)


def test_an_affiliation_revise_and_end_commit_their_events(staged: Engine) -> None:
    """E32/E33: a revise supersedes (successor + predecessor); an end is a state change."""
    service = EntityFamilyWriteService()
    context = {"principal_id": PRINCIPAL, "audit_id": issue_identifier(IdKind.AUDIT), "at": WHEN}
    with unit(staged) as uow:
        created = service.create_affiliation(
            uow.entities,
            CreateEntityAffiliation(
                person_entity_id=PERSON,
                affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
                idempotency_key="rcev-wp04-affiliation-add",
                organization_entity_id=ORGANIZATION,
                job_title="Engineer",
            ),
            **context,
        )
    with unit(staged) as uow:
        revised = service.revise_affiliation(
            uow.entities,
            ReviseEntityAffiliation(
                affiliation_id=created.record_id,
                expected_version=1,
                person_entity_id=PERSON,
                affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
                organization_entity_id=ORGANIZATION,
                idempotency_key="rcev-wp04-affiliation-revise",
                job_title="Principal Engineer",
            ),
            **context,
        )
    with unit(staged) as uow:
        service.end_affiliation(
            uow.entities,
            EndEntityAffiliation(
                affiliation_id=revised.record_id,
                expected_version=1,
                idempotency_key="rcev-wp04-affiliation-end",
            ),
            **context,
        )
    assert _shape(feed(staged, PRINCIPAL)) == [
        ("person_organization_affiliation", created.record_id, "created", 1),
        ("person_organization_affiliation", revised.record_id, "created", 1),
        ("person_organization_affiliation", created.record_id, "state_changed", 2),
        ("person_organization_affiliation", revised.record_id, "state_changed", 2),
    ]


def test_a_family_replay_commits_nothing(staged: Engine) -> None:
    """RE-AC-046 for the family writes: `directed_replay` answers before any write."""
    service = EntityFamilyWriteService()
    command = AddEntityName(
        entity_id=PERSON,
        name_type_code=NameTypeCode.LEGAL,
        display_value="Alice Synthetic",
        idempotency_key="rcev-wp04-name-replay",
    )
    context = {"principal_id": PRINCIPAL, "audit_id": issue_identifier(IdKind.AUDIT), "at": WHEN}
    with unit(staged) as uow:
        service.add_name(uow.entities, command, **context)
    with unit(staged) as uow:
        replayed = service.add_name(uow.entities, command, **context)
    assert replayed.replayed is True
    assert len(feed(staged, PRINCIPAL)) == 1
    assert next_sequence(staged, PRINCIPAL) == 2


def _ledger_event(key: str, *, record_id: str = PERSON) -> EntityMutationEvent:
    return EntityMutationEvent(
        event_id=issue_identifier(IdKind.ENTITY_MUTATION_EVENT),
        principal_id=PRINCIPAL,
        capability="entities.names.add",
        record_family=MutationRecordFamily.ENTITY,
        record_id=record_id,
        new_version=1,
        authority=MutationAuthority.USER_CONFIRMED_ASSERTION,
        actor_class=ActorClass.USER,
        idempotency_key=key,
        request_digest="0" * 64,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        recorded_at=WHEN,
    )


def test_the_ledgers_silent_replay_return_stages_nothing(staged: Engine) -> None:
    """RE-AC-046 / G1-EM-016: S-C follows the INSERT, not the method entry.

    The same key and digest a second time returns silently inside
    `record_mutation_event`; the event is staged only for the row it inserted.
    """
    shape = EntityEventShape(event_kind=RecordEventKind.CREATED, changed_fields=("state",))
    with unit(staged) as uow:
        uow.entities.record_mutation_event(
            PRINCIPAL, _ledger_event("rcev-wp04-silent"), shape=shape
        )
    with unit(staged) as uow:
        uow.entities.record_mutation_event(
            PRINCIPAL, _ledger_event("rcev-wp04-silent"), shape=shape
        )
        assert uow.record_events.pending_count == 0
    assert len(feed(staged, PRINCIPAL)) == 1
    with staged.connect() as connection:
        rows = connection.execute(
            select(entity_mutation_events.c.event_id).where(
                entity_mutation_events.c.principal_id == PRINCIPAL
            )
        ).all()
    assert len(rows) == 1


# ---- S-C observations and G1-EM-002 (E17/E18) --------------------------------


def _mention() -> EntityObservation:
    return EntityObservation(
        observation_id=MENTION,
        principal_id=PRINCIPAL,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Brand New Person",
        normalized_value=normalize_name("Brand New Person"),
        mention_display_name="Brand New Person",
        source_id="src_rcevwp04aaaa0001",
        source_object_id="obj_rcevwp04aaaa0001",
        source_version_id="ver_rcevwp04aaaa0001",
        observed_at=WHEN,
        recorded_at=WHEN,
    )


def _resolution_version(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(entity_observations.c.resolution_version).where(
                    entity_observations.c.observation_id == MENTION
                )
            ).scalar_one()
        )


def _resolve(uow: SqlAlchemyUnitOfWork, disposition: ResolutionDisposition, **extra: Any) -> Any:  # noqa: ANN401
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
            idempotency_key="rcev-wp04-resolve-0001",
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
def mentioned(staged: Engine) -> Engine:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_observation(PRINCIPAL, _mention())
    return staged


def test_create_new_commits_the_entity_then_the_observation_it_caused(mentioned: Engine) -> None:
    """G1-EM-002 / E18: the unledgered Entity `created`, then the observation `updated`
    at its feed version (T-002), caused by the Entity event."""
    with unit(mentioned) as uow:
        outcome = _resolve(
            uow,
            ResolutionDisposition.CREATE_NEW,
            entity_type=EntityType.PERSON,
            canonical_name="Brand New Person",
        )
    events = feed(mentioned, PRINCIPAL)
    assert len(events) == 2
    created, observed = events
    assert (created["record_family"], created["record_id"], created["event_kind"]) == (
        "entity",
        outcome.entity_id,
        "created",
    )
    assert created["record_version"] == 1
    assert created["source_receipt_id"] == outcome.mutation_event_id
    assert created["source_capability"] == "entities.unresolved_mentions.resolve"
    assert (observed["record_family"], observed["record_id"], observed["event_kind"]) == (
        "entity_observation",
        MENTION,
        "updated",
    )
    assert observed["record_version"] == _resolution_version(mentioned) + 1 == 2
    assert observed["changed_fields"] == ["entity_id", "resolution_version"]
    assert observed["causation_event_id"] == created["event_id"]
    assert observed["source_receipt_id"] == outcome.mutation_event_id
    assert_gap_free(mentioned, PRINCIPAL)


def test_a_quarantine_commits_one_observation_state_change(mentioned: Engine) -> None:
    with unit(mentioned) as uow:
        _resolve(uow, ResolutionDisposition.QUARANTINE, reason="not enough identity evidence")
    (event,) = feed(mentioned, PRINCIPAL)
    assert (event["event_kind"], event["record_version"]) == ("state_changed", 2)
    assert event["changed_fields"] == ["resolution_version", "state", "state_reason"]
    assert event["causation_event_id"] is None


def test_every_observation_event_satisfies_the_feed_floor(mentioned: Engine) -> None:
    """T-002: no `entity_observation` event is below `resolution_version + 1` of its row."""
    with unit(mentioned) as uow:
        _resolve(uow, ResolutionDisposition.DEFER, reason="later")
    events = [e for e in feed(mentioned, PRINCIPAL) if e["record_family"] == "entity_observation"]
    assert events
    assert all(e["record_version"] >= _resolution_version(mentioned) + 1 for e in events)


def test_an_ingested_observation_commits_created_at_its_feed_version(staged: Engine) -> None:
    """E17 (G1-EM-003): the ledger says `new_version=1` while the canonical
    `resolution_version` is 0; the event carries the feed version, 0 + 1."""
    with unit(staged) as uow:
        admitted = EntityGovernanceService(uow.entities).ingest(
            ObserveCommand(
                principal_id=PRINCIPAL,
                kind=ObservationKind.USER_STATEMENT,
                authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
                observed_value="Someone Stated",
                observed_at=WHEN,
                idempotency_key="rcev-wp04-observe-0001",
                capture_id=issue_identifier(IdKind.CAPTURE),
                capture_version_id=issue_identifier(IdKind.CAPTURE_VERSION),
            ),
            sources=uow.sources,
            at=WHEN,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
        )
    (event,) = feed(staged, PRINCIPAL)
    assert (event["record_family"], event["record_id"], event["event_kind"]) == (
        "entity_observation",
        admitted.observation_id,
        "created",
    )
    assert event["record_version"] == admitted.resolution_version + 1 == 1
    assert event["changed_fields"] == ["authority", "kind", "state"]
    assert event["source_receipt_id"] == admitted.mutation_event_id
    assert event["source_capability"] == "entities.observe"


def test_a_directed_replay_commits_nothing(staged: Engine) -> None:
    """RE-AC-046 for S-B: `directed_replay` answers a replay before any write."""
    command = CreateEntityAssignment(
        entity_id=PERSON,
        expected_entity_version=1,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        scope_entity_id=PROJECT,
        expected_scope_version=1,
        role="Lead",
        idempotency_key="rcev-wp04-assign-replay",
    )
    receipts = []
    for _ in range(2):
        with unit(staged) as uow:
            receipts.append(
                EntityDirectedService().create_assignment(
                    uow.entities,
                    command,
                    principal_id=PRINCIPAL,
                    audit_id=issue_identifier(IdKind.AUDIT),
                    at=WHEN,
                )
            )
    assert [receipt.replayed for receipt in receipts] == [False, True]
    assert len(feed(staged, PRINCIPAL)) == 1
    assert next_sequence(staged, PRINCIPAL) == 2
