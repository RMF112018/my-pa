"""The compatibility pin for the three established entity *read* capabilities.

`RULING-M7` of the Robust Entity Data Model campaign says compatibility is a
test obligation and not an assertion: "no consumer broke" is only true once a
test says so at the exact head. This file is that test for `entities.get`,
`entities.search`, and `entities.context`.

**Why it has to exist separately from the capability suites.** The response
shape of these three reads is defined in exactly one place — the private view
builders in `my_pa.application.service` (`_entity_view`,
`_entity_summary_view`, `_alias_view`, `_identifier_view`, `_assignment_view`,
`_relationship_view`, `_observation_view`, `_context_card_view`) — and nowhere
else. There is no response JSON Schema, no `pydantic` response model, and no
generated contract document for these payloads, so nothing in the tree fails
when a key is added, renamed, or dropped. The existing suites assert that the
keys a given test cares about are *present*; every one of them still passes
against a view that grew a field or renamed a neighbour. That is precisely the
drift a legacy backfill is able to introduce while looking harmless.

So the pin here is exhaustive equality (`set(...) == {...}`) and never
containment. An added key fails it, a removed key fails it, a renamed key fails
it twice. If a shape change is *intended*, this file is the place the intent
gets recorded — and the failure is the reminder that a published read shape has
consumers.

**How each assertion is protected from vacuity.** A key-set assertion over the
elements of an empty list is a loop that never runs: it cannot fail, and this
campaign has already shipped one. Every element-level assertion below is
therefore guarded two ways. First, `staged_card` builds a card in which each of
the seven collections (`coverage`, `aliases`, `identifiers`, `assignments`,
`relationships`, `observations`, `memories`) has at least one member, admitted
through the real repositories so the rows are ones a writer could have
produced. Second, each test asserts the collection it is about is non-empty
*before* it looks at an element, so a future change that empties a collection
turns into a red test rather than a silently vacant one. The
`test_every_context_card_collection_is_non_empty` case states the same
guarantee once, up front, as its own failure surface.

The suite is FAST-tier by construction: `FakeUnitOfWork` over an in-memory
`World`, no database, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.application.commands import (
    GetEntity,
    GetEntityContext,
    SearchEntities,
)
from my_pa.contracts.ports import MemoryWriteRequest
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
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
from my_pa.domain.relationship.governance import EntityObservation, ObservationKind
from my_pa.domain.relationship.memory import (
    DIRECT_USER_AUTHORITY,
    MemoryActorClass,
    MemoryKind,
    MemoryOperation,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.source.registry import issue_identifier

#: The one person every collection on the card hangs off, plus the employer and
#: the project the edge and the assignment point at. Distinct names on purpose:
#: this file is about *shape*, so nothing here should depend on the resolver's
#: ambiguity behaviour the way the capability suite's collision fixture does.
SUBJECT = "ent_shape0001shape0001"
EMPLOYER = "ent_shape0002shape0002"
PROJECT = "ent_shape0003shape0003"
WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)

#: Synthetic, and about a working preference rather than a person's private
#: life, for the reason the capability suite's own staged memory is.
SUBJECT_MEMORY = "Blake checks the survey control before signing a set"


# --- the pinned shapes ------------------------------------------------------
#
# Read off the view builders in `my_pa.application.service`, which are the only
# definition of these payloads that exists. Named as module constants rather
# than inlined so that the *same* entity shape asserted by `entities.get` and by
# the context card's nested `entity` is provably the same set, not two lists
# that happen to agree today.

ENTITY_KEYS = {
    "entity_id",
    "entity_type",
    "canonical_name",
    "display_name",
    "status",
    "created_at",
    "updated_at",
    "version",
    "superseded_by_entity_id",
}

ENTITY_SUMMARY_KEYS = {
    "entity_id",
    "entity_type",
    "canonical_name",
    "display_name",
    "status",
}

CONTEXT_CARD_KEYS = {
    "entity",
    "assembled_at",
    "coverage",
    "most_recent_observation_at",
    "limitations",
    "is_complete",
    "aliases",
    "identifiers",
    "assignments",
    "relationships",
    "observations",
    "memories",
}

COVERAGE_KEYS = {
    "source_id",
    "observation_count",
    "most_recent_observation_at",
}

ALIAS_KEYS = {
    "alias_id",
    "alias_type",
    "display_value",
    "effective_from",
    "effective_to",
}

IDENTIFIER_KEYS = {
    "identifier_id",
    "namespace",
    "display_value",
    "verified",
    "effective_from",
    "effective_to",
}

ASSIGNMENT_KEYS = {
    "assignment_id",
    "entity_id",
    "assignment_type",
    "scope_entity_id",
    "role",
    "discipline",
    "responsibility_class",
    "status",
    "is_current",
    "effective_from",
    "effective_to",
    "version",
}

RELATIONSHIP_KEYS = {
    "relationship_id",
    "is_current",
    "from_entity_id",
    "relationship_type",
    "to_entity_id",
    "scope_entity_id",
    "state",
    "effective_from",
    "effective_to",
    "version",
}

OBSERVATION_KEYS = {
    "observation_id",
    "kind",
    "source_id",
    "source_object_id",
    "source_version_id",
    "observed_at",
    "recorded_at",
}

MEMORY_KEYS = {
    "memory_id",
    "kind",
    "statement",
    "authority",
    "classification",
    "pinned",
    "effective_from",
    "effective_to",
    "recorded_at",
}

#: The seven collections on a context card whose *element* shape is pinned
#: below, and the key set each element carries. The vacuity guard iterates this
#: mapping, so a collection added to `CONTEXT_CARD_KEYS` without a fixture row
#: behind it is a failure here rather than an untested key.
CARD_COLLECTIONS = {
    "coverage": COVERAGE_KEYS,
    "aliases": ALIAS_KEYS,
    "identifiers": IDENTIFIER_KEYS,
    "assignments": ASSIGNMENT_KEYS,
    "relationships": RELATIONSHIP_KEYS,
    "observations": OBSERVATION_KEYS,
    "memories": MEMORY_KEYS,
}


# --- local fixtures ---------------------------------------------------------
#
# Deliberately built here rather than imported from `test_entity_capabilities`:
# a test module is not a library, and a pin that broke because another suite
# retuned its fixture would be reporting the wrong thing.


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
def staged_card(scene: Scene) -> Scene:
    """One entity carrying at least one row of every collection the card holds.

    This is the vacuity guarantee the module docstring names. Each write goes
    through the repository the capability itself reads, so no row here is one a
    writer could not have produced — a hand-placed row would be a shape the
    card's own invariants were never asked about.

    `coverage` is not written directly: the card derives it from the
    observations, so the single staged observation is what makes that collection
    non-empty. The memory is admitted through `RelationshipMemoryRepository` for
    the same reason, and it is what makes `memories` non-empty.
    """
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(principal_id, _entity(SUBJECT, "Blake Reyes", principal_id))
        entities.create(
            principal_id,
            _entity(EMPLOYER, "Meridian Works", principal_id, EntityType.ORGANIZATION),
        )
        entities.create(
            principal_id, _entity(PROJECT, "Quay Bridge", principal_id, EntityType.PROJECT)
        )
        entities.bind_identifier(
            principal_id,
            SUBJECT,
            ExternalIdentifier(
                identifier_id="xid_shape0001shape0001",
                entity_id=SUBJECT,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalize_identifier(
                    ExternalIdentifierNamespace.EMAIL, "b.reyes@meridian.test"
                ),
                display_value="b.reyes@meridian.test",
                principal_id=principal_id,
                verified=True,
            ),
        )
        entities.record_alias(
            principal_id,
            EntityAlias(
                alias_id="eals_shape0001shape001",
                entity_id=SUBJECT,
                alias_type=AliasType.NICKNAME,
                normalized_value=normalize_name("Blake"),
                display_value="Blake",
                principal_id=principal_id,
            ),
        )
        entities.record_assignment(
            principal_id,
            Assignment(
                assignment_id="asn_shape0001shape0001",
                entity_id=SUBJECT,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                principal_id=principal_id,
                scope_entity_id=PROJECT,
                role="surveyor",
            ),
        )
        entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_shape0001shape01",
                from_entity_id=SUBJECT,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=EMPLOYER,
                principal_id=principal_id,
            ),
        )
        entities.record_observation(
            principal_id,
            EntityObservation(
                observation_id="eobs_shape0001shape001",
                principal_id=principal_id,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value="Blake Reyes <b.reyes@meridian.test>",
                normalized_value=normalize_name("Blake Reyes"),
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                source_version_id="ver_shape0001shape0001",
                observed_at=WHEN,
                recorded_at=WHEN,
                entity_id=SUBJECT,
            ),
        )
    _record_memory(scene, SUBJECT, SUBJECT_MEMORY)
    return scene


def _record_memory(scene: Scene, entity_id: str, statement: str) -> str:
    """One memory about `entity_id`, admitted through the memory plane."""
    with FakeUnitOfWork(scene.world) as unit_of_work:
        admission = unit_of_work.relationship_memory.admit(
            MemoryWriteRequest(
                operation=MemoryOperation.CREATE,
                memory_id=None,
                memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                expected_version=None,
                principal_id=scene.principal.principal_id,
                subject_entity_id=entity_id,
                memory_kind=MemoryKind.PERSONAL_DETAIL,
                statement=statement,
                statement_sha256=statement_digest(statement),
                structured_value=None,
                authority=DIRECT_USER_AUTHORITY,
                classification=Classification.PRIVATE_LOCAL,
                created_by_actor=MemoryActorClass.USER,
                context_links=(),
                pinned=False,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                correction_reason=None,
                idempotency_key=issue_identifier(IdKind.CORRELATION),
                correlation_id=issue_identifier(IdKind.CORRELATION),
                server_received_at=WHEN,
            )
        )
    return admission.receipt.memory_id


def _payload(scene: Scene, capability: Capability, command: object) -> dict[str, object]:
    """The `result` object one read answered with, or the error that stopped it."""
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(capability, Purpose.ENTITY_READ, scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    return result


def _card(scene: Scene) -> dict[str, object]:
    result = _payload(scene, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=SUBJECT))
    card = result["context_card"]
    assert isinstance(card, dict)
    return card


def _elements(card: dict[str, object], name: str) -> list[dict[str, object]]:
    """One card collection, proven non-empty before anything reads an element.

    The guard is the whole point: `for element in []` asserts nothing, and a
    key-set pin that iterates an empty collection is a test that cannot go red.
    """
    collection = card[name]
    assert isinstance(collection, list)
    assert collection, f"the fixture must stage at least one {name} row for this pin to bite"
    for element in collection:
        assert isinstance(element, dict)
    return collection  # type: ignore[return-value]


# --- the vacuity guard, stated once and first -------------------------------


def test_every_context_card_collection_is_non_empty(staged_card: Scene) -> None:
    """The fixture stages a row of each collection, so no element pin is vacant.

    Asserted separately from the pins that depend on it so that a fixture which
    stopped staging one collection reports *that*, rather than turning the
    corresponding key-set assertion into a loop over nothing and staying green.
    """
    card = _card(staged_card)
    empty = [name for name in CARD_COLLECTIONS if not card[name]]
    assert empty == []


# --- entities.get -----------------------------------------------------------


def test_entities_get_result_shape_is_unchanged(staged_card: Scene) -> None:
    """The `result` object carries the entity and nothing else.

    Set equality rather than `"entity" in result`: a handler that started
    returning a second top-level key would satisfy containment and would be a
    new response shape.
    """
    result = _payload(staged_card, Capability.ENTITIES_GET, GetEntity(entity_id=SUBJECT))
    assert set(result) == {"entity"}


def test_entities_get_entity_shape_is_unchanged(staged_card: Scene) -> None:
    """`_entity_view`'s nine keys, pinned exhaustively.

    Not vacuous: `result["entity"]` is a single object rather than a collection,
    and `_payload` has already refused an error envelope, so the object is here
    or the test has failed before reaching this line.
    """
    result = _payload(staged_card, Capability.ENTITIES_GET, GetEntity(entity_id=SUBJECT))
    entity = result["entity"]
    assert isinstance(entity, dict)
    assert set(entity) == ENTITY_KEYS


# --- entities.search --------------------------------------------------------


def test_entities_search_result_shape_is_unchanged(staged_card: Scene) -> None:
    """One top-level key. The truncation disclosure lives on the envelope."""
    result = _payload(staged_card, Capability.ENTITIES_SEARCH, SearchEntities(query="Blake"))
    assert set(result) == {"entities"}


def test_entities_search_entry_shape_is_unchanged(staged_card: Scene) -> None:
    """`_entity_summary_view`'s five keys, on every row of the page.

    Not vacuous: the page is asserted non-empty first, and the query matches the
    staged subject. A search returning nothing would fail here rather than skip
    the pin.
    """
    result = _payload(staged_card, Capability.ENTITIES_SEARCH, SearchEntities(query="Blake"))
    found = result["entities"]
    assert isinstance(found, list)
    assert found, "the search must match the staged entity for this pin to bite"
    for entry in found:
        assert isinstance(entry, dict)
        assert set(entry) == ENTITY_SUMMARY_KEYS


def test_the_search_summary_is_a_strict_subset_of_the_full_entity(staged_card: Scene) -> None:
    """Browse and fetch describe the same record with the same field names.

    The two views are separate functions, so nothing but this stops a rename in
    one from drifting past the other — a caller that reads `entity_id` off a
    search row and then re-reads it off `entities.get` depends on the agreement.
    """
    assert ENTITY_SUMMARY_KEYS < ENTITY_KEYS


# --- entities.context -------------------------------------------------------


def test_entities_context_result_shape_is_unchanged(staged_card: Scene) -> None:
    result = _payload(staged_card, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=SUBJECT))
    assert set(result) == {"context_card"}


def test_entities_context_card_shape_is_unchanged(staged_card: Scene) -> None:
    """`_context_card_view`'s twelve keys, pinned exhaustively.

    Not vacuous: the card is a single object, and `_card` has already asserted
    it is a dict on a non-error envelope.
    """
    assert set(_card(staged_card)) == CONTEXT_CARD_KEYS


def test_the_card_entity_is_the_same_shape_entities_get_returns(staged_card: Scene) -> None:
    """The nested `entity` is `_entity_view`, not a card-local summary.

    Worth its own assertion because the card *could* plausibly have carried a
    summary here, and a change in that direction would drop four keys from a
    payload consumers read.
    """
    entity = _card(staged_card)["entity"]
    assert isinstance(entity, dict)
    assert set(entity) == ENTITY_KEYS


@pytest.mark.parametrize(("collection", "keys"), sorted(CARD_COLLECTIONS.items()))
def test_every_card_collection_element_shape_is_unchanged(
    staged_card: Scene, collection: str, keys: set[str]
) -> None:
    """Each nested element type on the card, pinned exhaustively.

    Not vacuous on two counts: `_elements` refuses an empty collection before
    the loop runs, and `test_every_context_card_collection_is_non_empty` states
    the same guarantee independently, so a fixture regression cannot quietly
    turn all seven of these into no-ops at once.
    """
    for element in _elements(_card(staged_card), collection):
        assert set(element) == keys


# --- the request shapes -----------------------------------------------------
#
# Compatibility is not only what comes back. A field added to a command changes
# the tool schema an MCP client validates against, and a field removed breaks a
# client that still sends it; `additionalProperties: False` is what makes the
# second of those a refusal rather than a silent drop, so it is pinned too.


@pytest.mark.parametrize(
    ("command", "properties"),
    [
        (SearchEntities, {"query", "entity_type", "page_size", "after"}),
        (GetEntity, {"entity_id"}),
        (GetEntityContext, {"entity_id"}),
    ],
    ids=["entities.search", "entities.get", "entities.context"],
)
def test_the_request_payload_schema_is_unchanged(command: type, properties: set[str]) -> None:
    """The published request shape of each read, exhaustively.

    Not vacuous: `payload_schema_for` always returns a `properties` mapping, and
    an empty one would fail these equalities rather than pass them.
    """
    schema = payload_schema_for(command)
    assert set(schema["properties"]) == properties
    assert schema["additionalProperties"] is False
