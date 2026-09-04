"""`entities.graph` is a seeded, page-bounded neighborhood — not a directory.

A canvas that walked `entities.relationships` one hop at a time would invent
completeness, unbounded N+1, and client-derived authority. This capability is
the server-owned projection that walk is replaced by: one or two hops, a unified
edge stream, overflow disclosed, currency computed here when `as_of` is given.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for, operator

from my_pa.application.commands import GetEntityGraph
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.producer_origin import ProducerOrigin
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import (
    Assignment,
    AssignmentState,
    AssignmentType,
    Entity,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    RelationshipState,
)
from my_pa.domain.relationship.normalization import normalize_name

FOCUS: Final = "ent_focus0001person"
ORG_A: Final = "ent_orgaaaa0001org"
ORG_B: Final = "ent_orgbbbb0001org"
PEER: Final = "ent_peer00001person"
DISTANT: Final = "ent_dist00001person"
RETAINED: Final = "ent_keep00001person"
REDIRECT: Final = "ent_gone00001person"
MISSING: Final = "ent_miss00001person"
WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)
HUB_EDGES: Final = 10


def _entity(
    entity_id: str,
    display_name: str,
    principal_id: str,
    kind: EntityType,
    *,
    status: EntityStatus = EntityStatus.ACTIVE,
    superseded_by_entity_id: str | None = None,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=kind,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=status,
        superseded_by_entity_id=superseded_by_entity_id,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _envelope(
    scene: Scene, command: GetEntityGraph, *, principal: Principal | None = None
) -> ResponseEnvelope:
    actor = principal or scene.principal
    service = build_service(scene.world, scene.providers)
    return service.invoke(
        metadata_for(Capability.ENTITIES_GRAPH, Purpose.ENTITY_READ, actor),
        command,
        principal=actor,
    )


def _result(envelope: ResponseEnvelope) -> dict[str, Any]:
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    return result


@pytest.fixture
def neighborhood(scene: Scene) -> Scene:
    """Focus person, two orgs, a peer, and a 2-hop-only distant person."""
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(principal_id, _entity(FOCUS, "Pat Focus", principal_id, EntityType.PERSON))
        entities.create(
            principal_id, _entity(ORG_A, "Acme Construction", principal_id, EntityType.ORGANIZATION)
        )
        entities.create(
            principal_id, _entity(ORG_B, "Beta Studio", principal_id, EntityType.ORGANIZATION)
        )
        entities.create(principal_id, _entity(PEER, "Alex Peer", principal_id, EntityType.PERSON))
        entities.create(
            principal_id, _entity(DISTANT, "Dana Distant", principal_id, EntityType.PERSON)
        )
        entities.create(
            principal_id, _entity(RETAINED, "Kept Identity", principal_id, EntityType.PERSON)
        )
        entities.create(
            principal_id,
            _entity(
                REDIRECT,
                "Former Name",
                principal_id,
                EntityType.PERSON,
                status=EntityStatus.MERGED_REDIRECT,
                superseded_by_entity_id=RETAINED,
            ),
        )
        entities.record_assignment(
            principal_id,
            Assignment(
                assignment_id="asn_0001asgn0001",
                entity_id=FOCUS,
                assignment_type=AssignmentType.EMPLOYMENT,
                principal_id=principal_id,
                scope_entity_id=ORG_A,
                role="architect",
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                effective_to=datetime(2025, 1, 1, tzinfo=UTC),
                state=AssignmentState.ACTIVE,
                version=1,
            ),
        )
        entities.record_assignment(
            principal_id,
            Assignment(
                assignment_id="asn_0002asgn0002",
                entity_id=FOCUS,
                assignment_type=AssignmentType.MEMBERSHIP,
                principal_id=principal_id,
                scope_entity_id=ORG_B,
                role="member",
                state=AssignmentState.ACTIVE,
                version=1,
            ),
        )
        entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_0001peer0001",
                from_entity_id=FOCUS,
                relationship_type=EntityRelationshipType.REPORTS_TO,
                to_entity_id=PEER,
                principal_id=principal_id,
                state=RelationshipState.ACTIVE,
                version=1,
            ),
        )
        entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_0002far00002",
                from_entity_id=PEER,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=DISTANT,
                principal_id=principal_id,
                state=RelationshipState.ACTIVE,
                version=1,
            ),
        )
        entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_0003gone0003",
                from_entity_id=FOCUS,
                relationship_type=EntityRelationshipType.HISTORICAL_IDENTITY_OF,
                to_entity_id=REDIRECT,
                principal_id=principal_id,
                state=RelationshipState.ACTIVE,
                version=1,
            ),
        )
    return scene


@pytest.fixture
def hub(scene: Scene) -> Scene:
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(
            principal_id, _entity(ORG_A, "Acme Construction", principal_id, EntityType.ORGANIZATION)
        )
        for index in range(HUB_EDGES):
            person_id = f"ent_{index:04d}person{index:04d}"
            entities.create(
                principal_id,
                _entity(person_id, f"Person Number {index:04d}", principal_id, EntityType.PERSON),
            )
            entities.record_relationship(
                principal_id,
                EntityRelationship(
                    relationship_id=f"erel_{index:04d}edge{index:04d}",
                    from_entity_id=person_id,
                    relationship_type=EntityRelationshipType.WORKS_FOR,
                    to_entity_id=ORG_A,
                    principal_id=principal_id,
                    state=RelationshipState.ACTIVE,
                    version=1,
                ),
            )
    return scene


def test_a_small_graph_is_deterministic(neighborhood: Scene) -> None:
    first = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS)))
    second = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS)))
    assert first == second
    assert [node["entity_id"] for node in first["nodes"]] == sorted(
        node["entity_id"] for node in first["nodes"]
    )
    assert [edge["edge_id"] for edge in first["edges"]] == sorted(
        edge["edge_id"] for edge in first["edges"]
    )
    assert first["next_cursor"] is None


def test_the_same_entity_may_appear_under_two_projection_ids(neighborhood: Scene) -> None:
    result = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS)))
    framed = [
        node
        for node in result["nodes"]
        if node["entity_id"] == FOCUS and node["projection_id"] != f"gprj_{FOCUS}"
    ]
    assert {node["projection_id"] for node in framed} == {
        f"gprj_{FOCUS}_asn_0001asgn0001",
        f"gprj_{FOCUS}_asn_0002asgn0002",
    }


def test_assignment_edges_are_structural(neighborhood: Scene) -> None:
    result = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS)))
    assignments = [edge for edge in result["edges"] if edge["edge_kind"] == "assignment"]
    assert {edge["edge_id"] for edge in assignments} == {"asn_0001asgn0001", "asn_0002asgn0002"}
    assert {edge["to_entity_id"] for edge in assignments} == {ORG_A, ORG_B}
    assert all(edge["status"] == "active" for edge in assignments)
    assert all("state" not in edge for edge in assignments)


def test_as_of_is_computed_on_the_server(neighborhood: Scene) -> None:
    absent = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS)))
    assert all(edge["is_current"] is None for edge in absent["edges"])

    current = _result(
        _envelope(
            neighborhood,
            GetEntityGraph(focus_entity_id=FOCUS, as_of=datetime(2024, 6, 1, tzinfo=UTC)),
        )
    )
    historical = _result(
        _envelope(
            neighborhood,
            GetEntityGraph(focus_entity_id=FOCUS, as_of=datetime(2026, 6, 1, tzinfo=UTC)),
        )
    )
    ended = next(edge for edge in current["edges"] if edge["edge_id"] == "asn_0001asgn0001")
    later = next(edge for edge in historical["edges"] if edge["edge_id"] == "asn_0001asgn0001")
    still = next(edge for edge in historical["edges"] if edge["edge_id"] == "asn_0002asgn0002")
    assert ended["is_current"] is True
    assert later["is_current"] is False
    assert still["is_current"] is True


def test_two_hops_are_bounded_and_deeper_than_one(neighborhood: Scene) -> None:
    one = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS, hops=1)))
    two = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS, hops=2)))
    one_ids = {edge["edge_id"] for edge in one["edges"]}
    two_ids = {edge["edge_id"] for edge in two["edges"]}
    assert "erel_0002far00002" not in one_ids
    assert "erel_0002far00002" in two_ids
    assert DISTANT not in {node["entity_id"] for node in one["nodes"]}
    assert DISTANT in {node["entity_id"] for node in two["nodes"]}
    assert one_ids < two_ids


def test_a_dense_hub_discloses_truncation_and_the_cursor_continues(hub: Scene) -> None:
    first = _envelope(hub, GetEntityGraph(focus_entity_id=ORG_A, page_size=3))
    page = _result(first)
    assert len(page["edges"]) == 3
    assert first.disclosure.truncation.is_truncated
    assert first.disclosure.truncation.reason == "page_size_reached"
    cursor = page["next_cursor"]
    assert cursor == first.disclosure.truncation.next_cursor == page["edges"][-1]["edge_id"]

    second = _result(
        _envelope(hub, GetEntityGraph(focus_entity_id=ORG_A, page_size=3, after=cursor))
    )
    first_ids = [edge["edge_id"] for edge in page["edges"]]
    second_ids = [edge["edge_id"] for edge in second["edges"]]
    assert set(first_ids) & set(second_ids) == set()
    expected = [f"erel_{index:04d}edge{index:04d}" for index in range(HUB_EDGES)]
    assert first_ids + second_ids == expected[:6]


def test_filtering_types_does_not_make_the_seed_absent(neighborhood: Scene) -> None:
    result = _result(
        _envelope(
            neighborhood,
            GetEntityGraph(
                focus_entity_id=FOCUS,
                relationship_types=(EntityRelationshipType.REPORTS_TO.value,),
            ),
        )
    )
    assert FOCUS in {node["entity_id"] for node in result["nodes"]}
    kinds = {edge["type"] for edge in result["edges"] if edge["edge_kind"] == "relationship"}
    assert kinds <= {EntityRelationshipType.REPORTS_TO.value}
    assert EntityRelationshipType.WORKS_FOR.value not in kinds
    assert EntityRelationshipType.HISTORICAL_IDENTITY_OF.value not in kinds


def test_a_merged_redirect_is_labelled_on_the_node(neighborhood: Scene) -> None:
    result = _result(_envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS)))
    redirected = next(node for node in result["nodes"] if node["entity_id"] == REDIRECT)
    assert redirected["status"] == EntityStatus.MERGED_REDIRECT.value
    assert redirected["superseded_by_entity_id"] == RETAINED


def test_principal_b_does_not_learn_principal_a_exists(neighborhood: Scene) -> None:
    other = operator()
    neighborhood.world.producer_origins[other.principal_id] = ProducerOrigin(
        principal_id=other.principal_id,
        principal_kind=other.kind,
        method="rule",
        method_version="synthetic-rule-producer.1",
    )
    with FakeUnitOfWork(neighborhood.world) as unit_of_work:
        unit_of_work.entities.create(
            other.principal_id,
            _entity(MISSING, "Other Person", other.principal_id, EntityType.PERSON),
        )
    foreign = _envelope(neighborhood, GetEntityGraph(focus_entity_id=MISSING))
    body = foreign.to_canonical_dict()
    assert body["result"] is None
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.NOT_FOUND.value
    assert error["safe_details"] == [SafeDetail.FOCUS_ENTITY_ID.value]
    leaked = _envelope(neighborhood, GetEntityGraph(focus_entity_id=FOCUS), principal=other)
    leaked_body = leaked.to_canonical_dict()
    assert leaked_body["error"]["code"] == ErrorCode.NOT_FOUND.value
    result = leaked_body.get("result") or {}
    assert FOCUS not in {node.get("entity_id") for node in result.get("nodes", [])}


def test_an_unknown_focus_is_not_an_empty_graph(neighborhood: Scene) -> None:
    envelope = _envelope(neighborhood, GetEntityGraph(focus_entity_id=MISSING))
    body = envelope.to_canonical_dict()
    assert body["result"] is None
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.NOT_FOUND.value
    assert error["safe_details"] == [SafeDetail.FOCUS_ENTITY_ID.value]


def test_empty_seed_is_refused() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        GetEntityGraph()
    assert refused.value.safe_details == (SafeDetail.FOCUS_ENTITY_ID,)
    with pytest.raises(InvalidRequestError):
        GetEntityGraph(focus_entity_id=FOCUS, hops=3)
    with pytest.raises(InvalidRequestError):
        GetEntityGraph(focus_entity_id=FOCUS, relationship_types=())


def test_scope_only_seed_is_the_org_frame(neighborhood: Scene) -> None:
    result = _result(_envelope(neighborhood, GetEntityGraph(scope_entity_id=ORG_A)))
    assert ORG_A in {node["entity_id"] for node in result["nodes"]}
    assert any(
        edge["edge_kind"] == "assignment" and edge["to_entity_id"] == ORG_A
        for edge in result["edges"]
    )


def test_a_known_seed_with_no_edges_is_an_empty_graph_not_not_found(scene: Scene) -> None:
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.create(
            principal_id, _entity(FOCUS, "Lonely", principal_id, EntityType.PERSON)
        )
    result = _result(_envelope(scene, GetEntityGraph(focus_entity_id=FOCUS)))
    assert result["edges"] == []
    assert result["nodes"] == [
        {
            "entity_id": FOCUS,
            "projection_id": f"gprj_{FOCUS}",
            "entity_type": "person",
            "display_label": "Lonely",
            "status": "active",
            "superseded_by_entity_id": None,
        }
    ]
