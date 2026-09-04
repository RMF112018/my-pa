"""The entity capabilities, through the application service.

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
    AddEntityAddress,
    AddEntityAlias,
    AddEntityCommunicationMethod,
    AddEntityName,
    ArchiveEntity,
    BindEntityIdentifier,
    CreateEntity,
    CreateEntityAffiliation,
    CreateEntityAssignment,
    CreateEntityParticipation,
    CreateEntityProposal,
    CreateEntityRelationship,
    EndEntityAffiliation,
    EndEntityAssignment,
    EndEntityParticipation,
    EndEntityRelationship,
    GetEntity,
    GetEntityContext,
    GetEntityGraph,
    GetEntityIdentityHistory,
    GetEntityProfile,
    GetEntityRelationships,
    ListEntityAddresses,
    ListEntityAliases,
    ListEntityAssignments,
    ListEntityCommunicationMethods,
    ListEntityIdentifiers,
    ListEntityNames,
    ListEntityObservations,
    ListEntityParticipations,
    ListUnresolvedMentions,
    MergeEntities,
    ObserveEntityMention,
    PreviewEntityMerge,
    PreviewEntitySplit,
    ResolveEntity,
    ResolveUnresolvedMention,
    RestoreEntity,
    RetireEntityAddress,
    RetireEntityAlias,
    RetireEntityCommunicationMethod,
    RetireEntityIdentifier,
    RetireEntityName,
    ReviseEntityAddress,
    ReviseEntityAffiliation,
    ReviseEntityAssignment,
    ReviseEntityCommunicationMethod,
    ReviseEntityParticipation,
    ReviseEntityRelationship,
    SearchEntities,
    SplitEntity,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
    SupersedeEntityName,
    UpdateEntity,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.ports import MemoryWriteRequest
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    AliasType,
    Assignment,
    AssignmentType,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    NameTypeCode,
    ParticipationStatusCode,
    RelationshipState,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.relationship.governance import (
    EntityObservation,
    ObservationAuthority,
    ObservationKind,
    ResolutionDisposition,
)
from my_pa.domain.relationship.memory import (
    DIRECT_USER_AUTHORITY,
    MemoryActorClass,
    MemoryKind,
    MemoryOperation,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.relationship.proposal_payload import EntityProposalKind
from my_pa.domain.relationship.resolution import ResolutionOutcome
from my_pa.domain.source.registry import issue_identifier

ALICE = "ent_alice0001alice0001"
ALICE_TWO = "ent_alice0002alice0002"
ACME = "ent_acme0003acme000003"
TOWER = "ent_tower0004tower0004"
#: Two derived identifiers the off-switch sweep names. Derived rather than
#: staged: the plane is disabled in that sweep, so nothing is reached and no row
#: has to exist for the refusal to be the one under test.
ASSIGNMENT = "asn_offswitch01offswitch1"
RELATIONSHIP = "erel_offswitch1offswitch"
ENTITY_NAME = "enam_offswitch1offswitc"
ENTITY_ADDRESS = "eadr_offswitch1offswitc"
COMMUNICATION_METHOD = "ecmm_offswitch1offswit"
PARTICIPATION = "eppt_offswitch1offswit"
AFFILIATION = "poaf_offswitch1offswit"
WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)

#: What the one staged memory says. Synthetic and about a working preference, so
#: nothing here resembles a real note about a real person.
ALICE_MEMORY = "Alice reviews structural drawings before a site walk"


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
        entities.create(principal_id, _entity(ALICE, "Alice Chen", principal_id))
        entities.create(principal_id, _entity(ALICE_TWO, "Alice Chen", principal_id))
        entities.create(
            principal_id, _entity(ACME, "Acme Construction", principal_id, EntityType.ORGANIZATION)
        )
        entities.create(
            principal_id, _entity(TOWER, "Harbour Tower", principal_id, EntityType.PROJECT)
        )
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
        entities.record_observation(
            principal_id,
            EntityObservation(
                observation_id="eobs_alice0001alice001",
                principal_id=principal_id,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value="Alice Chen <a.chen@acme.test>",
                normalized_value=normalize_name("Alice Chen"),
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                source_version_id="ver_alice0001alice0001",
                observed_at=WHEN,
                recorded_at=WHEN,
                entity_id=ALICE,
            ),
        )
    return scene


def _record_memory(scene: Scene, entity_id: str, statement: str) -> str:
    """One memory about `entity_id`, and the identifier the plane gave it.

    Admitted through `RelationshipMemoryRepository` rather than pushed into
    `World`, for the reason the entities above go through `EntitiesRepository`:
    a row no writer could have produced is a row the card's own invariants were
    never asked about, and this is the collection the card is read for.

    Not in the `staged` fixture, because only the card is about memories and
    every other test in this file would then be asserting around one.
    """
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
    """Every collection around `ALICE`, memories included.

    The memory is staged here rather than asserted absent: the card reaches the
    memory plane in this build, so an unstaged entity would have the card
    reporting `no_memory_has_been_recorded` — an honest answer, and the wrong
    one for a test about what the card *carries*.
    """
    memory_id = _record_memory(staged, ALICE, ALICE_MEMORY)
    result = _payload(staged, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    card = result["context_card"]
    assert isinstance(card, dict)
    assert card["entity"]["entity_id"] == ALICE
    assert [alias["display_value"] for alias in card["aliases"]] == ["Ali"]
    assert [item["display_value"] for item in card["identifiers"]] == ["a.chen@acme.test"]
    assert [item["role"] for item in card["assignments"]] == ["structural engineer"]
    assert [edge["to_entity_id"] for edge in card["relationships"]] == [ACME]
    assert [held["memory_id"] for held in card["memories"]] == [memory_id]
    assert [held["statement"] for held in card["memories"]] == [ALICE_MEMORY]
    assert card["limitations"] == []
    assert card["is_complete"] is True


def test_the_context_card_states_its_coverage_and_freshness(staged: Scene) -> None:
    """`RI-AC-013`: coverage and freshness, before the records rather than after."""
    result = _payload(staged, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    card = result["context_card"]
    assert isinstance(card, dict)
    assert card["assembled_at"]
    assert [entry["source_id"] for entry in card["coverage"]] == [staged.source.source_id]
    assert card["coverage"][0]["observation_count"] == 1
    assert card["most_recent_observation_at"] is not None
    assert [item["observation_id"] for item in card["observations"]] == ["eobs_alice0001alice001"]


def test_a_context_card_observation_does_not_carry_the_text_it_observed(
    staged: Scene,
) -> None:
    """The card says a source spoke and when, not what it said."""
    result = _payload(staged, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    assert "a.chen@acme.test" not in str(result["context_card"]["observations"])  # type: ignore[index]


def test_an_entity_no_source_has_observed_says_so(staged: Scene) -> None:
    """Section 6.8: a lack of indexed evidence is not evidence of absence.

    `ACME` has no observations, and the card says that in a limitation rather
    than by carrying an empty list that looks the same as an unbuilt card.
    """
    result = _payload(staged, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ACME))
    card = result["context_card"]
    assert isinstance(card, dict)
    assert card["coverage"] == []
    assert "no_source_has_been_observed" in card["limitations"]
    assert card["is_complete"] is True


# --- RULING-M7: what these responses publish, exhaustively -------------------
#
# The assertions above name keys they care about; none of them compares the
# whole key set, so a field *added* to any of these responses satisfies every
# one of them. That is the change a consumer has to be told about, and
# `RI-ENT-WP-10` added a plane beside these five without touching any of them --
# a claim worth holding as a test rather than as a sentence in a report.
#
# Written out rather than derived from the view functions, deliberately. A set
# derived from `_context_card_view` would agree with itself after any edit and
# would prove nothing; these are the keys the published contract names, and the
# edit that changes one has to change this list too.


def test_the_context_card_publishes_exactly_twelve_keys(staged: Scene) -> None:
    """`entities.context` is unchanged by `RI-ENT-WP-10`, and this is the proof.

    Ordered comparison rather than set equality, because `RI-AC-013` is about
    reading order: coverage, freshness and exclusions belong *before* the
    records they qualify, and a card that moved `limitations` below `memories`
    would satisfy a set comparison while losing the property the order carries.
    """
    result = _payload(staged, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    card = result["context_card"]
    assert isinstance(card, dict)
    assert list(card) == [
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
    ]


def test_the_context_cards_nested_entries_publish_exactly_their_own_keys(
    staged: Scene,
) -> None:
    """The two collections a widening would most plausibly reach into.

    `coverage` and `memories` are the card's own composed shapes rather than a
    record view shared with another capability, so a field added to either
    would appear here and nowhere else.
    """
    _record_memory(staged, ALICE, ALICE_MEMORY)
    result = _payload(staged, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    card = result["context_card"]
    assert isinstance(card, dict)
    assert set(card["coverage"][0]) == {
        "source_id",
        "observation_count",
        "most_recent_observation_at",
    }
    assert set(card["memories"][0]) == {
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


def test_the_four_other_entity_reads_publish_exactly_the_keys_they_publish(
    staged: Scene,
) -> None:
    """`entities.get`, `.relationships`, `.identifiers.list` and `.aliases.list`.

    One test over the four, because the claim is one claim: none of these four
    responses changed. Each envelope and each record it carries is compared
    whole.
    """
    got = _payload(staged, Capability.ENTITIES_GET, GetEntity(entity_id=ALICE))
    assert set(got) == {"entity"}
    assert set(got["entity"]) == {  # type: ignore[arg-type]
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

    edges = _payload(
        staged, Capability.ENTITIES_RELATIONSHIPS, GetEntityRelationships(entity_id=ALICE)
    )
    assert set(edges) == {"relationships"}
    assert set(edges["relationships"][0]) == {  # type: ignore[index]
        "relationship_id",
        "from_entity_id",
        "relationship_type",
        "to_entity_id",
        "scope_entity_id",
        "state",
        "version",
        "effective_from",
        "effective_to",
        "is_current",
    }

    identifiers = _payload(
        staged, Capability.ENTITIES_IDENTIFIERS_LIST, ListEntityIdentifiers(entity_id=ALICE)
    )
    assert set(identifiers) == {"entity_id", "identifiers"}
    assert set(identifiers["identifiers"][0]) == {  # type: ignore[index]
        "identifier_id",
        "namespace",
        "display_value",
        "verified",
        "state",
        "version",
        "effective_from",
        "effective_to",
        "retired_at",
        "updated_at",
        "superseded_by_identifier_id",
    }

    aliases = _payload(staged, Capability.ENTITIES_ALIASES_LIST, ListEntityAliases(entity_id=ALICE))
    assert set(aliases) == {"entity_id", "aliases"}
    assert set(aliases["aliases"][0]) == {  # type: ignore[index]
        "alias_id",
        "alias_type",
        "display_value",
        "state",
        "version",
        "effective_from",
        "effective_to",
        "retired_at",
        "updated_at",
        "superseded_by_alias_id",
    }


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


# ---- the capability supplies the moment ------------------------------------


def test_the_capability_passes_its_own_clock_to_the_resolver(staged: Scene) -> None:
    """`entities.resolve` answers about *now*, and only the handler knows when now is.

    The resolver holds signals to a currency rule that needs a moment. Without
    one it falls back to "nobody wrote an end date", under which an assignment
    beginning in 2030 reads as in force and corroborates a bare canonical name
    into a confident answer. `ResolutionRequest.at` carries `authorization.at`
    for exactly that reason.

    Asserted here rather than only in the unit suite because the defect is not in
    the resolver -- it behaves correctly when told the moment -- but in the one
    line of the handler that tells it. Deleting `at=authorization.at` left the
    whole suite green while restoring the defect, so the wiring needs a test of
    its own.

    The scope is named so the resolver consults context at all; ALICE and
    ALICE_TWO share a canonical name, so a corroborated signal is the only thing
    that could lift either above `AMBIGUOUS`.
    """
    scene = staged
    principal_id = scene.principal.principal_id
    # A scope nobody has a *live* tie to, so the future assignment is the only
    # thing that could corroborate. Using the staged project would not isolate
    # the clock: ALICE already holds a current assignment there.
    harbour = "ent_harbour0007harbour"
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.create(
            principal_id, _entity(harbour, "Harbour Point", principal_id, EntityType.PROJECT)
        )
        unit_of_work.entities.record_assignment(
            principal_id,
            Assignment(
                assignment_id="asn_future0002future02",
                entity_id=ALICE,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                principal_id=principal_id,
                scope_entity_id=harbour,
                effective_from=datetime(2030, 1, 1, tzinfo=UTC),
            ),
        )
    body = _payload(
        scene,
        Capability.ENTITIES_RESOLVE,
        ResolveEntity(reference="Alice Chen", scope_entity_id=harbour),
    )
    resolution = body["resolution"]
    assert resolution["outcome"] == ResolutionOutcome.AMBIGUOUS.value  # type: ignore[index,call-overload]
    assert resolution.get("entity_id") is None  # type: ignore[union-attr]


# ---- the plane is off ------------------------------------------------------


def _disabled(scene: Scene, capability: Capability, command: object) -> dict[str, object]:
    """Invoke against a build that never enabled the relationship plane.

    The purpose is derived from the capability rather than fixed at
    `entity_read`. It was fixed while the plane was all reads, and a fixed
    purpose would now answer `denied` for the two writes -- a refusal that looks
    like the one this sweep is checking for and is a different one, which is
    exactly the kind of pass this file exists not to give.
    """
    service = build_service(scene.world, scene.providers, relationship_intelligence_enabled=False)
    # The purpose is derived rather than fixed at `entity_read`. Six of the
    # thirteen are writes and take `entity_authoring`, and a sweep that sent the
    # read purpose for all of them would meet `denied` before it reached the
    # gate -- proving that a mismatched purpose is refused, which is a different
    # test, while reading as proof that the plane was withheld.
    envelope = service.invoke(
        # The purpose the domain permits for *this* capability, not the read
        # purpose the plane had when this sweep was written: `WP-RI-A-02` gave
        # ten of its capabilities `entity_authoring`, and invoking one of those
        # under `entity_read` would be denied for the purpose rather than
        # refused for the missing plane — a green sweep over the wrong refusal.
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    return envelope.to_canonical_dict()


#: One command per entity capability, keyed by the capability itself so the
#: parameterization below can be checked for completeness rather than trusted.
#: A hand-written list is how `entities.unresolved_mentions` came to be covered
#: by a separate test instead of this sweep — and how the next one would be
#: missed.
_OFF_SWITCH_COMMANDS: dict[Capability, object] = {
    Capability.ENTITIES_SEARCH: SearchEntities(query="Alice"),
    Capability.ENTITIES_GET: GetEntity(entity_id=ALICE),
    Capability.ENTITIES_RESOLVE: ResolveEntity(reference="Alice Chen"),
    Capability.ENTITIES_CONTEXT: GetEntityContext(entity_id=ALICE),
    Capability.ENTITIES_RELATIONSHIPS: GetEntityRelationships(entity_id=ALICE),
    Capability.ENTITIES_GRAPH: GetEntityGraph(focus_entity_id=ALICE),
    Capability.ENTITIES_UNRESOLVED_MENTIONS: ListUnresolvedMentions(),
    # The authoring half (`WP-RI-A-02`). Every subject is `ALICE` and every
    # child identifier is minted: this sweep never reaches a handler, so what
    # each command has to be is well formed rather than resolvable.
    Capability.ENTITIES_IDENTIFIERS_LIST: ListEntityIdentifiers(entity_id=ALICE),
    Capability.ENTITIES_ALIASES_LIST: ListEntityAliases(entity_id=ALICE),
    # `RI-ENT-WP-10`'s five record-family reads, all naming `ALICE`.
    # `perspective` is spelled because the command has no default.
    Capability.ENTITIES_PROFILE: GetEntityProfile(entity_id=ALICE),
    Capability.ENTITIES_NAMES_LIST: ListEntityNames(entity_id=ALICE),
    Capability.ENTITIES_ADDRESSES_LIST: ListEntityAddresses(entity_id=ALICE),
    Capability.ENTITIES_COMMUNICATION_LIST: ListEntityCommunicationMethods(entity_id=ALICE),
    Capability.ENTITIES_PARTICIPATIONS_LIST: ListEntityParticipations(
        entity_id=ALICE, perspective="participant"
    ),
    # `RI-ENT-WP-11`'s record-family writes, all naming `ALICE` and a derived
    # name identifier, on the same terms as the lifecycle writes above: the
    # plane is disabled in this sweep, so what each command has to be is well
    # formed rather than resolvable.
    Capability.ENTITIES_NAMES_ADD: AddEntityName(
        entity_id=ALICE,
        name_type_code=NameTypeCode.LEGAL,
        display_value="Alice Chen",
        idempotency_key="off-switch-names-add",
    ),
    Capability.ENTITIES_NAMES_SUPERSEDE: SupersedeEntityName(
        entity_name_id=ENTITY_NAME,
        expected_version=1,
        entity_id=ALICE,
        name_type_code=NameTypeCode.LEGAL,
        display_value="Alice Chen",
        idempotency_key="off-switch-names-supersede",
    ),
    Capability.ENTITIES_NAMES_RETIRE: RetireEntityName(
        entity_name_id=ENTITY_NAME,
        expected_version=1,
        idempotency_key="off-switch-names-retire",
    ),
    Capability.ENTITIES_ADDRESSES_ADD: AddEntityAddress(
        entity_id=ALICE,
        address_type_code=AddressTypeCode.BUSINESS,
        raw_value="1 Synthetic Way",
        idempotency_key="off-switch-addresses-add",
    ),
    Capability.ENTITIES_ADDRESSES_REVISE: ReviseEntityAddress(
        entity_address_id=ENTITY_ADDRESS,
        expected_version=1,
        entity_id=ALICE,
        address_type_code=AddressTypeCode.BUSINESS,
        raw_value="2 Synthetic Way",
        idempotency_key="off-switch-addresses-revise",
    ),
    Capability.ENTITIES_ADDRESSES_RETIRE: RetireEntityAddress(
        entity_address_id=ENTITY_ADDRESS,
        expected_version=1,
        idempotency_key="off-switch-addresses-retire",
    ),
    Capability.ENTITIES_COMMUNICATION_ADD: AddEntityCommunicationMethod(
        entity_id=ALICE,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.CORPORATE,
        display_value="off.switch@example.test",
        idempotency_key="off-switch-communication-add",
    ),
    Capability.ENTITIES_COMMUNICATION_REVISE: ReviseEntityCommunicationMethod(
        communication_method_id=COMMUNICATION_METHOD,
        expected_version=1,
        entity_id=ALICE,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.CORPORATE,
        display_value="off.switch.corrected@example.test",
        idempotency_key="off-switch-communication-revise",
    ),
    Capability.ENTITIES_COMMUNICATION_RETIRE: RetireEntityCommunicationMethod(
        communication_method_id=COMMUNICATION_METHOD,
        expected_version=1,
        idempotency_key="off-switch-communication-retire",
    ),
    Capability.ENTITIES_PARTICIPATIONS_CREATE: CreateEntityParticipation(
        project_entity_id=TOWER,
        participant_entity_id=ALICE,
        project_display_name="Alice Chen on Tower",
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        idempotency_key="off-switch-participations-create",
    ),
    Capability.ENTITIES_PARTICIPATIONS_REVISE: ReviseEntityParticipation(
        participation_id=PARTICIPATION,
        expected_version=1,
        project_entity_id=TOWER,
        participant_entity_id=ALICE,
        project_display_name="Alice Chen on Tower, corrected",
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        idempotency_key="off-switch-participations-revise",
    ),
    Capability.ENTITIES_PARTICIPATIONS_END: EndEntityParticipation(
        participation_id=PARTICIPATION,
        expected_version=1,
        idempotency_key="off-switch-participations-end",
    ),
    Capability.ENTITIES_AFFILIATIONS_CREATE: CreateEntityAffiliation(
        person_entity_id=ALICE,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        idempotency_key="off-switch-affiliations-create",
        organization_entity_id=ACME,
    ),
    Capability.ENTITIES_AFFILIATIONS_REVISE: ReviseEntityAffiliation(
        affiliation_id=AFFILIATION,
        expected_version=1,
        person_entity_id=ALICE,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        organization_entity_id=ACME,
        idempotency_key="off-switch-affiliations-revise",
    ),
    Capability.ENTITIES_AFFILIATIONS_END: EndEntityAffiliation(
        affiliation_id=AFFILIATION,
        expected_version=1,
        idempotency_key="off-switch-affiliations-end",
    ),
    Capability.ENTITIES_CREATE: CreateEntity(
        entity_type=EntityType.PERSON,
        display_name="Alice Chen",
        idempotency_key="off-switch-create",
    ),
    Capability.ENTITIES_UPDATE: UpdateEntity(
        entity_id=ALICE,
        expected_version=1,
        display_name="Alice Chen",
        reason="A synthetic correction.",
        idempotency_key="off-switch-update",
    ),
    Capability.ENTITIES_ARCHIVE: ArchiveEntity(
        entity_id=ALICE,
        expected_version=1,
        reason="A synthetic withdrawal.",
        idempotency_key="off-switch-archive",
    ),
    Capability.ENTITIES_RESTORE: RestoreEntity(
        entity_id=ALICE,
        expected_version=1,
        reason="A synthetic restoration.",
        idempotency_key="off-switch-restore",
    ),
    Capability.ENTITIES_IDENTIFIERS_BIND: BindEntityIdentifier(
        entity_id=ALICE,
        expected_version=1,
        namespace=CallerNamespace.EMAIL,
        display_value="alice@example.invalid",
        idempotency_key="off-switch-bind",
    ),
    Capability.ENTITIES_IDENTIFIERS_RETIRE: RetireEntityIdentifier(
        entity_id=ALICE,
        expected_version=1,
        identifier_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
        expected_identifier_version=1,
        reason="A synthetic retirement.",
        idempotency_key="off-switch-retire-identifier",
    ),
    Capability.ENTITIES_IDENTIFIERS_SUPERSEDE: SupersedeEntityIdentifier(
        entity_id=ALICE,
        expected_version=1,
        identifier_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
        expected_identifier_version=1,
        namespace=CallerNamespace.EMAIL,
        display_value="alice.new@example.invalid",
        reason="A synthetic replacement.",
        idempotency_key="off-switch-supersede-identifier",
    ),
    Capability.ENTITIES_ALIASES_ADD: AddEntityAlias(
        entity_id=ALICE,
        expected_version=1,
        alias_type=AliasType.NICKNAME,
        display_value="Ali",
        idempotency_key="off-switch-add-alias",
    ),
    Capability.ENTITIES_ALIASES_RETIRE: RetireEntityAlias(
        entity_id=ALICE,
        expected_version=1,
        alias_id=issue_identifier(IdKind.ENTITY_ALIAS),
        expected_alias_version=1,
        reason="A synthetic retirement.",
        idempotency_key="off-switch-retire-alias",
    ),
    Capability.ENTITIES_ALIASES_SUPERSEDE: SupersedeEntityAlias(
        entity_id=ALICE,
        expected_version=1,
        alias_id=issue_identifier(IdKind.ENTITY_ALIAS),
        expected_alias_version=1,
        alias_type=AliasType.NICKNAME,
        display_value="Ally",
        reason="A synthetic correction.",
        idempotency_key="off-switch-supersede-alias",
    ),
    Capability.ENTITIES_ASSIGNMENTS_LIST: ListEntityAssignments(entity_id=ALICE),
    Capability.ENTITIES_ASSIGNMENTS_CREATE: CreateEntityAssignment(
        entity_id=ALICE,
        expected_entity_version=1,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        idempotency_key="off-switch-assignment-create",
    ),
    Capability.ENTITIES_ASSIGNMENTS_REVISE: ReviseEntityAssignment(
        assignment_id=ASSIGNMENT,
        expected_version=1,
        role="Synthetic Role",
        idempotency_key="off-switch-assignment-revise",
    ),
    Capability.ENTITIES_ASSIGNMENTS_END: EndEntityAssignment(
        assignment_id=ASSIGNMENT,
        expected_version=1,
        reason="A synthetic withdrawal.",
        end_now=True,
        idempotency_key="off-switch-assignment-end",
    ),
    Capability.ENTITIES_RELATIONSHIPS_CREATE: CreateEntityRelationship(
        from_entity_id=ALICE,
        expected_from_version=1,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=ACME,
        expected_to_version=1,
        idempotency_key="off-switch-relationship-create",
    ),
    Capability.ENTITIES_RELATIONSHIPS_REVISE: ReviseEntityRelationship(
        relationship_id=RELATIONSHIP,
        expected_version=1,
        idempotency_key="off-switch-relationship-revise",
    ),
    Capability.ENTITIES_RELATIONSHIPS_END: EndEntityRelationship(
        relationship_id=RELATIONSHIP,
        expected_version=1,
        reason="A synthetic withdrawal.",
        end_now=True,
        idempotency_key="off-switch-relationship-end",
    ),
    Capability.ENTITIES_OBSERVATIONS_LIST: ListEntityObservations(),
    Capability.ENTITIES_OBSERVE: ObserveEntityMention(
        kind=ObservationKind.CONTACT_RECORD,
        authority=ObservationAuthority.SOURCE_OBSERVATION,
        observed_value="Alice Chen",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        idempotency_key="off-switch-observe",
        source_id="src_offswitch0001",
        source_object_id="obj_offswitch0001",
        source_version_id="ver_offswitch0001",
    ),
    # `defer` rather than a disposition that binds, because this sweep is about
    # the composition gate: a refusal that needed a staged entity would be
    # indistinguishable from a missing fixture.
    Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE: ResolveUnresolvedMention(
        observation_id="eobs_offswitch0001",
        expected_resolution_version=0,
        disposition=ResolutionDisposition.DEFER,
        idempotency_key="off-switch-resolve",
        reason="the plane is off, so nothing decides this",
    ),
    # `WP-RI-B-05` and `WP-RI-B-06`. Three more names on the same prefix and so
    # three more rows in this sweep, which is exactly what the completeness
    # guard below is for: the plane grew and the sweep had to grow with it.
    Capability.ENTITIES_PROPOSALS_CREATE: CreateEntityProposal(
        kind=EntityProposalKind.RECORD_ALIAS,
        payload={"entity_id": ALICE, "display_value": "A. Chen", "alias_type": "nickname"},
        evidence=({"role": "direct", "entity_observation_id": "eobs_offswitch0001"},),
    ),
    Capability.ENTITIES_MERGE_PREVIEW: PreviewEntityMerge(
        survivor_entity_id=ALICE,
        expected_survivor_version=1,
        merged_away=({"entity_id": ALICE_TWO, "expected_version": 1},),
        reason="the plane is off, so nothing previews this",
    ),
    Capability.ENTITIES_MERGE: MergeEntities(
        preview_id="eipv_offswitch0001",
        preview_digest="0" * 64,
        reason="the plane is off, so nothing merges this",
    ),
    Capability.ENTITIES_IDENTITY_HISTORY: GetEntityIdentityHistory(entity_id=ALICE),
    Capability.ENTITIES_SPLIT_PREVIEW: PreviewEntitySplit(
        source_identity_operation_id="eiop_offswitch0001",
        reason="the plane is off, so nothing previews this split",
    ),
    Capability.ENTITIES_SPLIT: SplitEntity(
        preview_id="eipv_offswitch0002",
        preview_digest="1" * 64,
        reason="the plane is off, so nothing applies this split",
    ),
}


def test_the_off_switch_sweep_covers_every_capability_on_the_plane() -> None:
    """The completeness guard the sweep below cannot provide for itself.

    Derived from the `entities.` prefix and compared against the hand-written
    mapping, so a capability added to the plane without a command here fails
    *this* test by name rather than silently shrinking the sweep.
    """
    served = {capability for capability in Capability if capability.value.startswith("entities.")}
    assert set(_OFF_SWITCH_COMMANDS) == served
    # Fifty-five after `UI-IMP-WP15` added `entities.graph` to the
    # fifty-four `RI-ENT-WP-11` left. The count is asserted rather than derived
    # for the reason it always was -- it is what tells a reader the prefix scan
    # found the plane and not a substring of it.
    assert len(served) == 55


@pytest.mark.parametrize(
    ("capability", "command"),
    sorted(_OFF_SWITCH_COMMANDS.items(), key=lambda pair: pair[0].value),
    ids=lambda value: value.value if isinstance(value, Capability) else "",
)
def test_a_disabled_plane_refuses_every_capability_rather_than_answering(
    staged: Scene, capability: Capability, command: object
) -> None:
    """Withholding them from the manifest did not stop them executing.

    `available_capabilities` subtracts them, and two readers consult it —
    `capabilities.get` and the MCP tool list. The HTTP transport is not one of
    them: `/v1/{capability}` routes by path segment and dispatch goes straight to
    `_HANDLERS`, so each of them answered with real rows on a build that
    reported it as `not_implemented`. Parameterized over the whole family
    deliberately: the floor was absent from every one of them, so a test
    covering a single capability would have gone green while the rest stayed
    open. The family is derived and checked by the test above, because when
    `entities.unresolved_mentions` arrived this list was not extended.

    Staged data is used rather than an empty world so that a missing refusal
    fails loudly with a payload, instead of passing as an empty answer.
    """
    body = _disabled(staged, capability, command)
    assert body["result"] is None
    assert body["error"]["code"] == ErrorCode.UNSUPPORTED.value  # type: ignore[index]


# ---- the card labels currency so no surface re-derives it -------------------


def test_the_card_labels_each_assignment_current_or_historical(staged: Scene) -> None:
    """`PFE-AC-072` asks a surface to separate current from historical assignments.

    The raw columns were already on the wire, so a frontend could have derived
    it — and that is the failure this test exists to prevent. Currency on this
    plane is one rule, and it is the rule `entities.resolve` applies when
    deciding whether an assignment may corroborate an identity. A People detail
    screen that computed its own would be a second business logic plane
    (`RI-I-012`), diverging from the resolver at exactly the boundaries this
    campaign has already got wrong twice: a role that has not begun, and a
    contract with a recorded end date still running.
    """
    scene = staged
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.record_assignment(
            principal_id,
            Assignment(
                assignment_id="asn_ended0003ended0003",
                entity_id=ALICE,
                assignment_type=AssignmentType.EMPLOYMENT,
                principal_id=principal_id,
                scope_entity_id=ACME,
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                effective_to=datetime(2021, 1, 1, tzinfo=UTC),
            ),
        )
        unit_of_work.entities.record_assignment(
            principal_id,
            Assignment(
                assignment_id="asn_future0004future04",
                entity_id=ALICE,
                assignment_type=AssignmentType.EMPLOYMENT,
                principal_id=principal_id,
                scope_entity_id=ACME,
                effective_from=datetime(2030, 1, 1, tzinfo=UTC),
            ),
        )
    body = _payload(scene, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    labelled = {
        str(row["assignment_id"]): row["is_current"]  # type: ignore[index]
        for row in body["context_card"]["assignments"]  # type: ignore[index,union-attr]
    }
    # Staged live by the fixture, and open-ended.
    assert labelled["asn_alice0001alice0001"] is True
    # Over: its end date is in the past.
    assert labelled["asn_ended0003ended0003"] is False
    # Not begun: no end date at all, which the plane refuses to read as "current".
    assert labelled["asn_future0004future04"] is False


def test_the_card_labels_each_relationship_current_or_historical(staged: Scene) -> None:
    """The sibling of the test above, and it had none.

    `_relationship_view` computes `is_current` the same way `_assignment_view`
    does, and nothing asserted it: replacing the whole guard with a literal
    `True` left every test in the repository green. Half of a claim proved is
    the shape this branch keeps producing, so the edge half is pinned here.

    An edge is current when its state is active **and** it is in force at the
    card's moment. Both halves are staged, because a test that only ended a
    contract would pass against a rule that read the state and ignored the
    dates, and one that only expired the dates would pass against the reverse.
    """
    scene = staged
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_ended0002ended02",
                from_entity_id=ALICE,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=ACME,
                principal_id=principal_id,
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                effective_to=datetime(2021, 1, 1, tzinfo=UTC),
            ),
        )
        unit_of_work.entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_future003future3",
                from_entity_id=ALICE,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=ACME,
                principal_id=principal_id,
                effective_from=datetime(2030, 1, 1, tzinfo=UTC),
            ),
        )
        unit_of_work.entities.record_relationship(
            principal_id,
            EntityRelationship(
                relationship_id="erel_stopped04stoppd4",
                from_entity_id=ALICE,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=ACME,
                principal_id=principal_id,
                state=RelationshipState.ENDED,
            ),
        )
    body = _payload(scene, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE))
    labelled = {
        str(row["relationship_id"]): row["is_current"]  # type: ignore[index]
        for row in body["context_card"]["relationships"]  # type: ignore[index,union-attr]
    }
    # Staged live by the fixture: active state, no dates bounding it.
    assert labelled["erel_alice0001alice01"] is True
    # In force is not enough on its own — this one's state says it stopped.
    assert labelled["erel_stopped04stoppd4"] is False
    # Active state is not enough on its own either.
    assert labelled["erel_ended0002ended02"] is False
    assert labelled["erel_future003future3"] is False


# ---- the unresolved-mention queue ------------------------------------------


def _stage_unresolved(scene: Scene) -> None:
    """One observation nothing has linked — the shape the queue exists to list.

    The suite's own fixture links every observation it records, which is right
    for a card and wrong for this: a queue asserted against no rows is a queue
    asserted against nothing.
    """
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.record_observation(
            scene.principal.principal_id,
            EntityObservation(
                observation_id="eobs_unplaced01unplaced",
                principal_id=scene.principal.principal_id,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value="A. Chen <a.chen@northwind.test>",
                # Derived from the raw text **on purpose**. This is the write
                # the old design could not defend against: it is
                # `is_normalized_name`-true and carries the local part and the
                # domain, so no check over the string could refuse it. Staging
                # it here is what makes the assertions below adversarial rather
                # than a restatement of a well-behaved fixture.
                normalized_value=normalize_name("A. Chen <a.chen@northwind.test>"),
                mention_display_name="A. Chen",
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                source_version_id="ver_unplaced01unplaced",
                observed_at=WHEN,
                recorded_at=WHEN,
            ),
        )


def test_the_queue_lists_mentions_nothing_has_placed(staged: Scene) -> None:
    """`RI-AC-006`: unresolved is a state a person can look at, not an absence.

    The fixture stages one observation linked to nobody, and it comes back with
    the name a writer chose to publish.

    **The fixture derives `normalized_value` from the raw envelope on purpose,
    and that is what this test is really about.** The queue used to publish that
    field, on the argument that a matchable form is the same class of datum as a
    `canonical_name`. It is not: normalization removes no content, so the value
    staged here carries `northwind.test` and the local part and is
    `is_normalized_name`-true. Publishing it would have disclosed the envelope
    while every check on the plane stayed green.

    So the assertions are content checks, not key checks. Nothing the source
    wrote reaches the wire, and what does reach it is the field a writer filled
    in deliberately.
    """
    scene = staged
    _stage_unresolved(scene)
    body = _payload(scene, Capability.ENTITIES_UNRESOLVED_MENTIONS, ListUnresolvedMentions())
    mentions = body["mentions"]
    assert mentions, "an unlinked observation was staged, so this must not be empty"
    first = mentions[0]  # type: ignore[index]
    assert first["mention_display_name"] == "A. Chen"  # type: ignore[index]
    assert "observed_value" not in first  # type: ignore[operator]
    assert "normalized_value" not in first  # type: ignore[operator]
    # The envelope is not on the wire under any key, which a key check would not
    # have established.
    rendered = repr(body)
    assert "northwind" not in rendered
    assert "a.chen" not in rendered


def test_a_mention_nobody_named_is_queued_and_carries_no_text(staged: Scene) -> None:
    """Forgetting fails closed, which is the whole reason the column exists.

    `mention_display_name` is optional. A writer that fills nothing publishes
    nothing — and the mention is still queued, still carries its source
    pointers, and simply has no text beside it. The alternative the plane
    rejected was a field that always carried *something*, where the something
    was whatever matching happened to store.
    """
    scene = staged
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.record_observation(
            scene.principal.principal_id,
            EntityObservation(
                observation_id="eobs_unnamed01unnamed1",
                principal_id=scene.principal.principal_id,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value="B. Okafor <b.okafor@rival.test>",
                normalized_value=normalize_name("B. Okafor <b.okafor@rival.test>"),
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                source_version_id="ver_unnamed01unnamed01",
                observed_at=WHEN,
                recorded_at=WHEN,
            ),
        )
    body = _payload(scene, Capability.ENTITIES_UNRESOLVED_MENTIONS, ListUnresolvedMentions())
    queued = {str(row["observation_id"]): row for row in body["mentions"]}  # type: ignore[index,union-attr]
    assert "eobs_unnamed01unnamed1" in queued, "the mention must still be listed"
    assert queued["eobs_unnamed01unnamed1"]["mention_display_name"] is None  # type: ignore[index]
    # The source pointers are what make an unnamed mention still actionable.
    assert queued["eobs_unnamed01unnamed1"]["source_object_id"]  # type: ignore[index]
    rendered = repr(body)
    assert "rival" not in rendered
    assert "okafor" not in rendered.lower()


def test_the_queue_omits_mentions_that_have_been_placed(staged: Scene) -> None:
    """Linked observations are not unresolved, and a queue that showed them would lie."""
    scene = staged
    principal_id = scene.principal.principal_id
    _stage_unresolved(scene)
    before = _payload(scene, Capability.ENTITIES_UNRESOLVED_MENTIONS, ListUnresolvedMentions())
    assert before["mentions"], "nothing staged, so the emptiness below would prove nothing"
    listed = {str(row["observation_id"]) for row in before["mentions"]}  # type: ignore[index,union-attr]
    with FakeUnitOfWork(scene.world) as unit_of_work:
        for observation_id in listed:
            unit_of_work.entities.link_observation(principal_id, observation_id, ALICE)
    after = _payload(scene, Capability.ENTITIES_UNRESOLVED_MENTIONS, ListUnresolvedMentions())
    assert after["mentions"] == []


def test_the_queue_is_withheld_when_the_plane_is_off(staged: Scene) -> None:
    """The queue is gated exactly as the rest of the family is."""
    body = _disabled(staged, Capability.ENTITIES_UNRESOLVED_MENTIONS, ListUnresolvedMentions())
    assert body["result"] is None
    assert body["error"]["code"] == ErrorCode.UNSUPPORTED.value  # type: ignore[index]
