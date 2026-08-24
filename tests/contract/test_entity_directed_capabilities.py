"""The seven directed-relationship capabilities, through the application service.

`tests/unit/test_entity_directed_writes.py` proves the domain, the commands and
the repository contract. This proves the *capability*: that a request carrying
the right purpose reaches the right handler, that authority is the server's and
never the payload's, that the answer has the shape the completion contract
publishes, and that each refusal survives the trip out to a rendered problem.

**The refusals are the point of the file.** A repository that refuses a
duplicate, a stale version or a foreign entity is worth nothing if the layer
above flattens the three into one code, or renders `not_found` for one Principal
and `denied` for another, or lets a write through on a purpose issued for a read.
Each of those is a plausible mistake and each is asserted against here.

**Every capability in this family fails end-to-end against a real database until
Phase A's Alembic revision lands**, because `knowledge.audit_events` refuses a
capability its stored `capability_is_known` CHECK does not name, and the audit row
is written before the handler runs. Nothing in this file reaches that constraint:
the audit sink here is the in-memory double, so what is proved is the
application's behaviour and not the schema's admission of it. The database tier
says which of its own tests carry that dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    CreateEntityAssignment,
    CreateEntityRelationship,
    EndEntityAssignment,
    EndEntityRelationship,
    ListEntityAssignments,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import (
    AssignmentType,
    Entity,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import ActorClass, MutationAuthority
from my_pa.domain.relationship.normalization import normalize_name

ALICE: Final = "ent_alice0001alice0001"
ACME: Final = "ent_acme0002acme000002"
TOWER: Final = "ent_tower0003tower003"
WHEN: Final = datetime(2026, 8, 23, 12, tzinfo=UTC)

#: The whole family, derived rather than listed, so a capability added to it
#: without a row here reddens by name.
DIRECTED: Final[frozenset[Capability]] = frozenset(
    capability
    for capability in Capability
    if capability.value.startswith(("entities.assignments.", "entities.relationships."))
    and capability is not Capability.ENTITIES_RELATIONSHIPS
)


def _entity(entity_id: str, name: str, principal_id: str, kind: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=kind,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(scene: Scene) -> Scene:
    """One person, one organization, one project, and nothing else."""
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(principal_id, _entity(ALICE, "Alice Chen", principal_id, EntityType.PERSON))
        entities.create(
            principal_id, _entity(ACME, "Acme Construction", principal_id, EntityType.ORGANIZATION)
        )
        entities.create(
            principal_id, _entity(TOWER, "Harbour Tower", principal_id, EntityType.PROJECT)
        )
    return scene


def _invoke(
    scene: Scene, capability: Capability, command: object, purpose: Purpose | None = None
) -> dict[str, Any]:
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(
            capability,
            purpose or sorted(permitted_purposes(capability))[0],
            scene.principal,
        ),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    return envelope.to_canonical_dict()


def _result(scene: Scene, capability: Capability, command: object) -> dict[str, Any]:
    body = _invoke(scene, capability, command)
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    return result


def _error(scene: Scene, capability: Capability, command: object) -> dict[str, Any]:
    body = _invoke(scene, capability, command)
    error = body.get("error")
    assert isinstance(error, dict), body
    return error


def _create_assignment(scene: Scene, key: str, **overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "entity_id": ALICE,
        "expected_entity_version": 1,
        "assignment_type": AssignmentType.PROJECT_ASSIGNMENT,
        "idempotency_key": key,
        "scope_entity_id": TOWER,
        "expected_scope_version": 1,
        "role": "Lead",
    }
    values.update(overrides)
    return _result(scene, Capability.ENTITIES_ASSIGNMENTS_CREATE, CreateEntityAssignment(**values))


def _create_edge(scene: Scene, key: str, **overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "from_entity_id": ALICE,
        "expected_from_version": 1,
        "relationship_type": EntityRelationshipType.WORKS_FOR,
        "to_entity_id": ACME,
        "expected_to_version": 1,
        "idempotency_key": key,
    }
    values.update(overrides)
    return _result(
        scene, Capability.ENTITIES_RELATIONSHIPS_CREATE, CreateEntityRelationship(**values)
    )


# --- the family is what this file says it is --------------------------------


def test_this_file_is_about_the_seven_capabilities_the_package_adds() -> None:
    """Guards every sweep below: an empty family makes them all vacuous."""
    assert {capability.value for capability in DIRECTED} == {
        "entities.assignments.list",
        "entities.assignments.create",
        "entities.assignments.revise",
        "entities.assignments.end",
        "entities.relationships.create",
        "entities.relationships.revise",
        "entities.relationships.end",
    }


# --- authorization ----------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(DIRECTED, key=lambda c: c.value))
def test_no_directed_capability_is_reachable_on_a_purpose_it_does_not_permit(
    staged: Scene, capability: Capability
) -> None:
    """A grant issued to read the plane must not reach a write on it.

    Driven with the *read* purpose against every name in the family, because the
    six writes are exactly the ones a widened `entity_read` would open. The read
    is driven with a write purpose for the mirror of the same rule.
    """
    wrong = (
        Purpose.ENTITY_AUTHORING
        if Purpose.ENTITY_READ in permitted_purposes(capability)
        else Purpose.ENTITY_READ
    )
    body = _invoke(
        staged,
        capability,
        _command_for(capability),
        purpose=wrong,
    )
    error = body.get("error")
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.DENIED.value


def _command_for(capability: Capability) -> object:
    """One well-formed command per capability, for the sweeps that need any."""
    return {
        Capability.ENTITIES_ASSIGNMENTS_LIST: ListEntityAssignments(entity_id=ALICE),
        Capability.ENTITIES_ASSIGNMENTS_CREATE: CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            idempotency_key="contract-assignment-create",
        ),
        Capability.ENTITIES_ASSIGNMENTS_REVISE: ReviseEntityAssignment(
            assignment_id="asn_contract01contract",
            expected_version=1,
            role="Lead",
            idempotency_key="contract-assignment-revise",
        ),
        Capability.ENTITIES_ASSIGNMENTS_END: EndEntityAssignment(
            assignment_id="asn_contract01contract",
            expected_version=1,
            reason="a synthetic withdrawal",
            end_now=True,
            idempotency_key="contract-assignment-end",
        ),
        Capability.ENTITIES_RELATIONSHIPS_CREATE: CreateEntityRelationship(
            from_entity_id=ALICE,
            expected_from_version=1,
            relationship_type=EntityRelationshipType.WORKS_FOR,
            to_entity_id=ACME,
            expected_to_version=1,
            idempotency_key="contract-relationship-create",
        ),
        Capability.ENTITIES_RELATIONSHIPS_REVISE: ReviseEntityRelationship(
            relationship_id="erel_contract1contract",
            expected_version=1,
            idempotency_key="contract-relationship-revise",
        ),
        Capability.ENTITIES_RELATIONSHIPS_END: EndEntityRelationship(
            relationship_id="erel_contract1contract",
            expected_version=1,
            reason="a synthetic withdrawal",
            end_now=True,
            idempotency_key="contract-relationship-end",
        ),
    }[capability]


def test_a_build_without_the_plane_refuses_every_directed_write(staged: Scene) -> None:
    """`unsupported`, not `denied`: a fact about the build, not the request."""
    service = build_service(staged.world, staged.providers, relationship_intelligence_enabled=False)
    for capability in sorted(DIRECTED, key=lambda c: c.value):
        envelope = service.invoke(
            metadata_for(capability, sorted(permitted_purposes(capability))[0], staged.principal),
            _command_for(capability),  # type: ignore[arg-type]
            principal=staged.principal,
        )
        body = envelope.to_canonical_dict()
        error = body.get("error")
        assert isinstance(error, dict), capability.value
        assert error["code"] == ErrorCode.UNSUPPORTED.value, capability.value


# --- the answer's shape -----------------------------------------------------


def test_a_create_answers_with_every_field_the_completion_contract_names(
    staged: Scene,
) -> None:
    """One receipt shape, and each field is a separate claim about what happened."""
    payload = _create_assignment(staged, "contract-assignment-0001")
    assert set(payload) == {
        "record_id",
        "record_family",
        "prior_version",
        "version",
        "state",
        "receipt_id",
        "audit_id",
        "idempotency_key",
        "superseded_id",
        "evidence_refs",
        "replayed",
        "issued_at",
    }
    assert payload["record_id"].startswith("asn_")
    assert payload["record_family"] == "assignment"
    assert payload["prior_version"] is None
    assert payload["version"] == 1
    assert payload["state"] == "active"
    assert payload["receipt_id"].startswith("emut_")
    assert payload["audit_id"].startswith("audit_")
    assert payload["idempotency_key"] == "contract-assignment-0001"
    assert payload["superseded_id"] is None
    assert payload["replayed"] is False


def test_the_receipt_names_the_audit_row_the_request_actually_wrote(staged: Scene) -> None:
    """A receipt that named a different audit row would be unfollowable."""
    payload = _create_assignment(staged, "contract-assignment-0001")
    assert payload["audit_id"] in {event.audit_id for event in staged.world.audit}


def test_the_ledger_records_the_authority_and_the_actor_the_server_chose(
    staged: Scene,
) -> None:
    """Not the caller's: there is no field on the command for either."""
    _create_assignment(staged, "contract-assignment-0001")
    row = staged.world.entity_mutation_events[-1]
    assert row.authority is MutationAuthority.USER_CONFIRMED_ASSERTION
    assert row.actor_class is ActorClass.USER
    assert row.capability == Capability.ENTITIES_ASSIGNMENTS_CREATE.value
    assert row.principal_id == staged.principal.principal_id
    # Null, on the whole plane. The receipt this request was handed back is this
    # row's own `event_id`; `receipt_id` points at a separate receipt record and
    # this build keeps none.
    assert row.receipt_id is None


def test_a_revise_reports_the_version_it_moved_from_and_to(staged: Scene) -> None:
    created = _create_assignment(staged, "contract-assignment-0001")
    revised = _result(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        ReviseEntityAssignment(
            assignment_id=created["record_id"],
            expected_version=1,
            role="Deputy Lead",
            idempotency_key="contract-assignment-revise",
        ),
    )
    assert revised["prior_version"] == 1
    assert revised["version"] == 2
    assert revised["state"] == "active"


def test_an_end_reports_the_lifecycle_state_it_moved_the_record_to(staged: Scene) -> None:
    created = _create_assignment(staged, "contract-assignment-0001")
    ended = _result(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_END,
        EndEntityAssignment(
            assignment_id=created["record_id"],
            expected_version=1,
            reason="the role was handed over",
            end_now=True,
            idempotency_key="contract-assignment-end",
        ),
    )
    assert ended["state"] == "ended"
    assert ended["version"] == 2


def test_the_listing_hands_back_the_version_a_revise_will_need(staged: Scene) -> None:
    """Otherwise a caller reads twice and revises against the older answer."""
    created = _create_assignment(staged, "contract-assignment-0001")
    page = _result(
        staged, Capability.ENTITIES_ASSIGNMENTS_LIST, ListEntityAssignments(entity_id=ALICE)
    )
    assignments = page["assignments"]
    assert [held["assignment_id"] for held in assignments] == [created["record_id"]]
    assert assignments[0]["version"] == 1
    assert assignments[0]["entity_id"] == ALICE


def test_the_listing_answers_not_found_for_an_entity_that_is_not_there(
    staged: Scene,
) -> None:
    """An empty page and an unknown person are different answers."""
    error = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_LIST,
        ListEntityAssignments(entity_id="ent_absent0001absen"),
    )
    assert error["code"] == ErrorCode.NOT_FOUND.value


# --- the refusals -----------------------------------------------------------


def test_a_duplicate_active_assignment_is_a_conflict_and_names_no_row(
    staged: Scene,
) -> None:
    _create_assignment(staged, "contract-assignment-0001")
    error = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            scope_entity_id=TOWER,
            expected_scope_version=1,
            role=" LEAD ",
            idempotency_key="contract-assignment-0002",
        ),
    )
    assert error["code"] == ErrorCode.CONFLICT.value
    # The existing row's identifier is not disclosed: `safe_details` is a closed
    # token set and every member of it names a field.
    assert all(not detail.startswith("asn_") for detail in error["safe_details"])


def test_a_stale_expected_version_is_a_conflict_that_writes_nothing(staged: Scene) -> None:
    created = _create_assignment(staged, "contract-assignment-0001")
    events = len(staged.world.entity_mutation_events)
    error = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        ReviseEntityAssignment(
            assignment_id=created["record_id"],
            expected_version=9,
            role="Deputy Lead",
            idempotency_key="contract-assignment-revise",
        ),
    )
    assert error["code"] == ErrorCode.CONFLICT.value
    assert "expected_version" in error["safe_details"]
    assert len(staged.world.entity_mutation_events) == events
    page = _result(
        staged, Capability.ENTITIES_ASSIGNMENTS_LIST, ListEntityAssignments(entity_id=ALICE)
    )
    assert page["assignments"][0]["role"] == "Lead"
    assert page["assignments"][0]["version"] == 1


def test_a_stale_endpoint_version_and_a_stale_record_version_answer_alike(
    staged: Scene,
) -> None:
    """A caller that could tell them apart would learn the scope entity exists."""
    record_stale = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        ReviseEntityAssignment(
            assignment_id=_create_assignment(staged, "contract-assignment-0001")["record_id"],
            expected_version=9,
            role="Deputy Lead",
            idempotency_key="contract-assignment-revise",
        ),
    )
    endpoint_stale = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=9,
            assignment_type=AssignmentType.EMPLOYMENT,
            idempotency_key="contract-assignment-0002",
        ),
    )
    for field in ("code", "message", "retry", "safe_details"):
        assert record_stale[field] == endpoint_stale[field], field


def test_an_absent_record_and_an_absent_entity_answer_alike(staged: Scene) -> None:
    """One `not_found` for every unreachable thing, on the plane's own rule."""
    absent_record = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        ReviseEntityAssignment(
            assignment_id="asn_absent0001absent1",
            expected_version=1,
            role="Lead",
            idempotency_key="contract-assignment-revise",
        ),
    )
    absent_entity = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        CreateEntityAssignment(
            entity_id="ent_absent0001absen",
            expected_entity_version=1,
            assignment_type=AssignmentType.EMPLOYMENT,
            idempotency_key="contract-assignment-0002",
        ),
    )
    assert absent_record["code"] == ErrorCode.NOT_FOUND.value
    for field in ("code", "message", "retry", "safe_details"):
        assert absent_record[field] == absent_entity[field], field


def test_an_evidence_reference_outside_the_partition_is_refused(staged: Scene) -> None:
    """And is refused as absent: which of the two it was is not disclosed."""
    error = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.EMPLOYMENT,
            idempotency_key="contract-assignment-0002",
            evidence_refs=("eobs_absent0001absen",),
        ),
    )
    assert error["code"] == ErrorCode.NOT_FOUND.value


# --- idempotency, end to end -----------------------------------------------


def test_an_exact_replay_returns_the_same_receipt_and_writes_no_second_row(
    staged: Scene,
) -> None:
    first = _create_assignment(staged, "contract-assignment-0001")
    rows = len(staged.world.entity_assignments)
    second = _create_assignment(staged, "contract-assignment-0001")
    assert second["record_id"] == first["record_id"]
    assert second["version"] == first["version"]
    assert second["receipt_id"] == first["receipt_id"]
    assert second["replayed"] is True
    assert first["replayed"] is False
    assert len(staged.world.entity_assignments) == rows


def test_one_key_with_a_different_request_is_an_idempotency_conflict(
    staged: Scene,
) -> None:
    _create_assignment(staged, "contract-assignment-0001")
    error = _error(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.EMPLOYMENT,
            idempotency_key="contract-assignment-0001",
        ),
    )
    assert error["code"] == ErrorCode.CONFLICT.value
    assert "idempotency_key" in error["safe_details"]


def test_a_replayed_end_does_not_move_the_record_a_second_time(staged: Scene) -> None:
    created = _create_assignment(staged, "contract-assignment-0001")
    command = EndEntityAssignment(
        assignment_id=created["record_id"],
        expected_version=1,
        reason="the role was handed over",
        end_now=True,
        idempotency_key="contract-assignment-end",
    )
    first = _result(staged, Capability.ENTITIES_ASSIGNMENTS_END, command)
    second = _result(staged, Capability.ENTITIES_ASSIGNMENTS_END, command)
    assert second["version"] == first["version"] == 2
    assert second["replayed"] is True
    page = _result(
        staged,
        Capability.ENTITIES_ASSIGNMENTS_LIST,
        ListEntityAssignments(entity_id=ALICE, active_only=False),
    )
    assert [held["version"] for held in page["assignments"]] == [2]


# --- direction is first class ----------------------------------------------


def test_creating_one_edge_creates_exactly_one_edge(staged: Scene) -> None:
    """No reciprocal, asserted through the capability rather than the repository."""
    _create_edge(staged, "contract-relationship-0001")
    assert len(staged.world.entity_relationships) == 1


def test_the_inverse_edge_is_admitted_and_is_a_different_record(staged: Scene) -> None:
    forward = _create_edge(staged, "contract-relationship-0001")
    backward = _create_edge(
        staged,
        "contract-relationship-0002",
        from_entity_id=ACME,
        to_entity_id=ALICE,
        relationship_type=EntityRelationshipType.MANAGES,
    )
    assert backward["record_id"] != forward["record_id"]
    assert backward["version"] == 1


def test_ending_one_edge_leaves_the_inverse_active(staged: Scene) -> None:
    forward = _create_edge(staged, "contract-relationship-0001")
    _create_edge(
        staged,
        "contract-relationship-0002",
        from_entity_id=ACME,
        to_entity_id=ALICE,
        relationship_type=EntityRelationshipType.MANAGES,
    )
    _result(
        staged,
        Capability.ENTITIES_RELATIONSHIPS_END,
        EndEntityRelationship(
            relationship_id=forward["record_id"],
            expected_version=1,
            reason="the engagement ended",
            end_now=True,
            idempotency_key="contract-relationship-end",
        ),
    )
    states = {edge.relationship_id: edge.state.value for edge in staged.world.entity_relationships}
    assert states[forward["record_id"]] == "ended"
    assert sorted(states.values()) == ["active", "ended"]


# --- the published contract -------------------------------------------------


@pytest.mark.parametrize("capability", sorted(DIRECTED, key=lambda c: c.value))
def test_every_directed_tool_schema_is_closed(capability: Capability) -> None:
    """`additionalProperties: false`, so a server-owned field cannot be smuggled in."""
    from my_pa.adapters.mcp.tools import _COMMANDS

    schema = payload_schema_for(_COMMANDS[capability])
    assert schema["additionalProperties"] is False
    assert "principal_id" not in schema["properties"]
    assert "authority" not in schema["properties"]
    assert "version" not in schema["properties"]


def test_the_schema_publishes_the_closed_vocabularies_rather_than_bare_strings() -> None:
    from my_pa.adapters.mcp.tools import _COMMANDS

    assignment = payload_schema_for(_COMMANDS[Capability.ENTITIES_ASSIGNMENTS_CREATE])
    edge = payload_schema_for(_COMMANDS[Capability.ENTITIES_RELATIONSHIPS_CREATE])
    assert assignment["properties"]["assignment_type"]["enum"] == [
        member.value for member in AssignmentType
    ]
    assert edge["properties"]["relationship_type"]["enum"] == [
        member.value for member in EntityRelationshipType
    ]


@pytest.mark.parametrize("capability", sorted(DIRECTED, key=lambda c: c.value))
def test_normalisation_builds_the_command_the_handler_dispatches_on(
    staged: Scene, capability: Capability
) -> None:
    """The transport adds nothing: a JSON payload becomes the same command.

    Driven for the whole family rather than one name, because the conversion a
    directed write needs -- a vocabulary string to an enum member, an RFC 3339
    string to a datetime, a JSON array to a tuple -- is per-command and a single
    row would prove it for whichever one happened to be picked.
    """
    payloads: dict[Capability, dict[str, Any]] = {
        Capability.ENTITIES_ASSIGNMENTS_LIST: {"entity_id": ALICE},
        Capability.ENTITIES_ASSIGNMENTS_CREATE: {
            "entity_id": ALICE,
            "expected_entity_version": 1,
            "assignment_type": "project_assignment",
            "idempotency_key": "contract-assignment-create",
            "effective_from": "2026-08-23T12:00:00+00:00",
            "evidence_refs": [],
        },
        Capability.ENTITIES_ASSIGNMENTS_REVISE: {
            "assignment_id": "asn_contract01contract",
            "expected_version": 1,
            "role": "Lead",
            "clear": ["discipline"],
            "idempotency_key": "contract-assignment-revise",
        },
        Capability.ENTITIES_ASSIGNMENTS_END: {
            "assignment_id": "asn_contract01contract",
            "expected_version": 1,
            "reason": "a synthetic withdrawal",
            "end_now": True,
            "idempotency_key": "contract-assignment-end",
        },
        Capability.ENTITIES_RELATIONSHIPS_CREATE: {
            "from_entity_id": ALICE,
            "expected_from_version": 1,
            "relationship_type": "works_for",
            "to_entity_id": ACME,
            "expected_to_version": 1,
            "idempotency_key": "contract-relationship-create",
        },
        Capability.ENTITIES_RELATIONSHIPS_REVISE: {
            "relationship_id": "erel_contract1contract",
            "expected_version": 1,
            "effective_to": "2026-08-23T12:00:00+00:00",
            "idempotency_key": "contract-relationship-revise",
        },
        Capability.ENTITIES_RELATIONSHIPS_END: {
            "relationship_id": "erel_contract1contract",
            "expected_version": 1,
            "reason": "a synthetic withdrawal",
            "end_now": True,
            "idempotency_key": "contract-relationship-end",
        },
    }
    document = {
        "request_id": f"req-{capability.value}",
        "purpose": sorted(permitted_purposes(capability))[0].value,
        "principal_id": staged.principal.principal_id,
        "requested_at": "2026-08-23T12:00:00+00:00",
        "payload": payloads[capability],
    }
    metadata, command = normalize(capability.value, document)
    assert metadata.capability is capability
    assert command.capability is capability
