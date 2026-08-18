"""The five entity capabilities, through the application service.

The unit suites prove the repository, the resolver, and the card. This proves
the *capability* — that a request carrying the right purpose reaches the right
handler, that the answer has the shape the contract publishes, and that the
refusals the plane is built around survive the trip out to a payload.

The last of those is the point of the file. A resolver that refuses to guess is
worth nothing if the transport layer flattens `AMBIGUOUS` into an error, or
drops the candidate list, or returns the first candidate as though it had been
chosen. Each of those is a plausible mistake and each is asserted against here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.application.commands import (
    GetEntity,
    GetEntityContext,
    GetEntityRelationships,
    ResolveEntity,
    SearchEntities,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import (
    AliasType,
    Assignment,
    AssignmentType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name

ALICE = "ent_alice0001alice0001"
ALICE_TWO = "ent_alice0002alice0002"
ACME = "ent_acme0003acme000003"
TOWER = "ent_tower0004tower0004"
WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _entity(
    entity_id: str,
    display_name: str,
    principal_id: str,
    entity_type: EntityType = EntityType.PERSON,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(scene: Scene) -> Scene:
    """Two people who share a name, an employer, and a project.

    Deliberately the collision shape: a suite that staged one distinct person
    would let a handler that returned "the first row" pass every assertion here.
    """
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(_entity(ALICE, "Alice Chen", principal_id))
        entities.create(_entity(ALICE_TWO, "Alice Chen", principal_id))
        entities.create(_entity(ACME, "Acme Construction", principal_id, EntityType.ORGANIZATION))
        entities.create(_entity(TOWER, "Harbour Tower", principal_id, EntityType.PROJECT))
        entities.bind_identifier(
            principal_id,
            ALICE,
            ExternalIdentifier(
                identifier_id="xid_alice0001alice0001",
                entity_id=ALICE,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalize_identifier(
                    ExternalIdentifierNamespace.EMAIL, "a.chen@acme.test"
                ),
                display_value="a.chen@acme.test",
                principal_id=principal_id,
                verified=True,
            ),
        )
        entities.record_alias(
            principal_id,
            EntityAlias(
                alias_id="eals_alice0001alice001",
                entity_id=ALICE,
                alias_type=AliasType.NICKNAME,
                normalized_value=normalize_name("Ali"),
                display_value="Ali",
                principal_id=principal_id,
            ),
        )
        entities.record_assignment(
            principal_id,
            Assignment(
                assignment_id="asn_alice0001alice0001",
                entity_id=ALICE,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                principal_id=principal_id,
                scope_entity_id=TOWER,
                role="structural engineer",
            ),
        )
        entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_alice0001alice01",
                from_entity_id=ALICE,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=ACME,
                principal_id=principal_id,
            ),
        )
    return scene


def _invoke(scene: Scene, capability: Capability, command: object) -> dict[str, object]:
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(capability, Purpose.ENTITY_READ, scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    return envelope.to_canonical_dict()


def _payload(scene: Scene, capability: Capability, command: object) -> dict[str, object]:
    body = _invoke(scene, capability, command)
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    return result


# --- entities.search --------------------------------------------------------


def test_search_returns_both_people_who_share_a_name(staged: Scene) -> None:
    result = _payload(staged, Capability.ENTITIES_SEARCH, SearchEntities(query="Alice"))
    found = result["entities"]
    assert isinstance(found, list)
    assert {entry["entity_id"] for entry in found} == {ALICE, ALICE_TWO}


def test_search_filters_by_entity_type(staged: Scene) -> None:
    result = _payload(
        staged,
        Capability.ENTITIES_SEARCH,
        SearchEntities(query="a", entity_type="organization"),
    )
    assert [entry["entity_id"] for entry in result["entities"]] == [ACME]  # type: ignore[union-attr]


def test_search_matching_nothing_is_an_empty_list_not_an_error(staged: Scene) -> None:
    """A search is a question with a legitimate empty answer."""
    result = _payload(staged, Capability.ENTITIES_SEARCH, SearchEntities(query="Nobody Whatsoever"))
    assert result["entities"] == []


def test_search_refuses_an_unknown_entity_type(staged: Scene) -> None:
    body = _invoke(
        staged, Capability.ENTITIES_SEARCH, SearchEntities(query="Alice", entity_type="wombat")
    )
    assert body["error"]["code"] == ErrorCode.INVALID_REQUEST.value  # type: ignore[index]


# --- entities.get -----------------------------------------------------------


def test_get_returns_the_entity(staged: Scene) -> None:
    result = _payload(staged, Capability.ENTITIES_GET, GetEntity(entity_id=ALICE))
    entity = result["entity"]
    assert isinstance(entity, dict)
    assert entity["entity_id"] == ALICE
    assert entity["display_name"] == "Alice Chen"
    assert entity["canonical_name"] == "alice chen"


def test_get_of_an_unknown_entity_is_not_found(staged: Scene) -> None:
    body = _invoke(staged, Capability.ENTITIES_GET, GetEntity(entity_id="ent_absent0001absent01"))
    assert body["error"]["code"] == ErrorCode.NOT_FOUND.value  # type: ignore[index]


# --- entities.resolve -------------------------------------------------------


def test_resolve_by_verified_identifier_names_one_entity(staged: Scene) -> None:
    result = _payload(
        staged,
        Capability.ENTITIES_RESOLVE,
        ResolveEntity(reference="A.Chen@ACME.test", namespace="email"),
    )
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    assert resolution["outcome"] == "resolved_exact"
    assert resolution["entity_id"] == ALICE


def test_resolve_of_a_shared_name_is_ambiguous_and_carries_both(staged: Scene) -> None:
    """The refusal, all the way out to a payload.

    Three ways this could have been flattened on the way here, each asserted
    against: an error instead of an answer, a chosen `entity_id`, or a dropped
    candidate list.
    """
    body = _invoke(staged, Capability.ENTITIES_RESOLVE, ResolveEntity(reference="Alice Chen"))
    assert body.get("error") is None
    resolution = body["result"]["resolution"]  # type: ignore[index]
    assert resolution["outcome"] == "ambiguous"
    assert resolution["entity_id"] is None
    assert {entry["entity_id"] for entry in resolution["candidates"]} == {ALICE, ALICE_TWO}
    assert "several_entities_share_this_name" in resolution["warnings"]


def test_resolve_of_nothing_is_an_answer_rather_than_an_error(staged: Scene) -> None:
    """`not_found` is an outcome here, not an error code.

    "I know of no such person" is information a caller acts on, and turning it
    into an error would put it in the same bucket as a malformed request.
    """
    body = _invoke(
        staged, Capability.ENTITIES_RESOLVE, ResolveEntity(reference="Nobody Whatsoever")
    )
    assert body.get("error") is None
    resolution = body["result"]["resolution"]  # type: ignore[index]
    assert resolution["outcome"] == "not_found"
    assert resolution["entity_id"] is None
    assert resolution["candidates"] == []


def test_resolve_narrowed_by_a_scope_says_it_was_contextual(staged: Scene) -> None:
    result = _payload(
        staged,
        Capability.ENTITIES_RESOLVE,
        ResolveEntity(reference="Alice Chen", scope_entity_id=TOWER),
    )
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    assert resolution["outcome"] == "resolved_contextual"
    assert resolution["entity_id"] == ALICE
    assert "narrowed_by_supplied_scope" in resolution["warnings"]
    assert resolution["candidates"][0]["signals"] == ["assigned_to_the_named_scope"]


def test_every_resolution_candidate_states_what_it_matched_on(staged: Scene) -> None:
    """Explainability survives serialization, or it is not explainability."""
    result = _payload(staged, Capability.ENTITIES_RESOLVE, ResolveEntity(reference="Alice Chen"))
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    for candidate in resolution["candidates"]:
        assert candidate["matched_on"]


def test_resolve_refuses_an_unknown_namespace(staged: Scene) -> None:
    body = _invoke(
        staged,
        Capability.ENTITIES_RESOLVE,
        ResolveEntity(reference="a.chen@acme.test", namespace="carrier_pigeon"),
    )
    assert body["error"]["code"] == ErrorCode.INVALID_REQUEST.value  # type: ignore[index]


# --- entities.context -------------------------------------------------------


def test_the_context_card_carries_every_record_around_the_entity(staged: Scene) -> None:
    result = _payload(staged, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    card = result["context_card"]
    assert isinstance(card, dict)
    assert card["entity"]["entity_id"] == ALICE
    assert [alias["display_value"] for alias in card["aliases"]] == ["Ali"]
    assert [item["display_value"] for item in card["identifiers"]] == ["a.chen@acme.test"]
    assert [item["role"] for item in card["assignments"]] == ["structural engineer"]
    assert [edge["to_entity_id"] for edge in card["relationships"]] == [ACME]
    assert card["limitations"] == []
    assert card["is_complete"] is True


def test_a_context_card_for_an_unknown_entity_is_not_found(staged: Scene) -> None:
    body = _invoke(
        staged,
        Capability.ENTITIES_CONTEXT,
        GetEntityContext(entity_id="ent_absent0001absent01"),
    )
    assert body["error"]["code"] == ErrorCode.NOT_FOUND.value  # type: ignore[index]


# --- entities.relationships -------------------------------------------------


def test_relationships_returns_the_typed_edge(staged: Scene) -> None:
    result = _payload(
        staged, Capability.ENTITIES_RELATIONSHIPS, GetEntityRelationships(entity_id=ALICE)
    )
    edges = result["relationships"]
    assert isinstance(edges, list)
    assert [edge["relationship_type"] for edge in edges] == ["works_for"]
    assert [edge["to_entity_id"] for edge in edges] == [ACME]


def test_relationships_respects_direction(staged: Scene) -> None:
    outgoing = _payload(
        staged,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=ALICE, direction="outgoing"),
    )
    incoming = _payload(
        staged,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=ALICE, direction="incoming"),
    )
    assert len(outgoing["relationships"]) == 1  # type: ignore[arg-type]
    assert incoming["relationships"] == []


def test_relationships_of_an_unknown_entity_is_not_found_rather_than_empty(
    staged: Scene,
) -> None:
    """An absent person and a person with no edges are different answers."""
    body = _invoke(
        staged,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id="ent_absent0001absent01"),
    )
    assert body["error"]["code"] == ErrorCode.NOT_FOUND.value  # type: ignore[index]


def test_relationships_refuses_an_unknown_direction() -> None:
    """Refused at the command, before it could be read as "any"."""
    with pytest.raises(InvalidRequestError):
        GetEntityRelationships(entity_id=ALICE, direction="sideways")
