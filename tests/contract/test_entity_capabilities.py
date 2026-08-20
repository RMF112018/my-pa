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
    ListUnresolvedMentions,
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
from my_pa.domain.relationship.governance import EntityObservation, ObservationKind
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.relationship.resolution import ResolutionOutcome

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
    """Invoke against a build that never enabled the relationship plane."""
    service = build_service(scene.world, scene.providers, relationship_intelligence_enabled=False)
    envelope = service.invoke(
        metadata_for(capability, Purpose.ENTITY_READ, scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    return envelope.to_canonical_dict()


@pytest.mark.parametrize(
    ("capability", "command"),
    [
        (Capability.ENTITIES_SEARCH, SearchEntities(query="Alice")),
        (Capability.ENTITIES_GET, GetEntity(entity_id=ALICE)),
        (Capability.ENTITIES_RESOLVE, ResolveEntity(reference="Alice Chen")),
        (Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=ALICE)),
        (Capability.ENTITIES_RELATIONSHIPS, GetEntityRelationships(entity_id=ALICE)),
    ],
)
def test_a_disabled_plane_refuses_every_capability_rather_than_answering(
    staged: Scene, capability: Capability, command: object
) -> None:
    """Withholding the five from the manifest did not stop them executing.

    `available_capabilities` subtracts them, and two readers consult it —
    `capabilities.get` and the MCP tool list. The HTTP transport is not one of
    them: `/v1/{capability}` routes by path segment and dispatch goes straight to
    `_HANDLERS`, so each of the five answered with real rows on a build that
    reported it as `not_implemented`. Parameterized over all five deliberately:
    the floor was absent from every one of them, so a test covering a single
    capability would have gone green while four holes stayed open.

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
                normalized_value=normalize_name("A Chen"),
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
                source_version_id="ver_unplaced01unplaced",
                observed_at=WHEN,
                recorded_at=WHEN,
            ),
        )


def test_the_queue_lists_mentions_nothing_has_placed(staged: Scene) -> None:
    """`RI-AC-006`: unresolved is a state a person can look at, not an absence.

    The fixture stages one observation linked to nobody. It comes back with the
    form that would match — which is what makes the queue actionable — and
    without the raw text the source carried.
    """
    scene = staged
    _stage_unresolved(scene)
    body = _payload(scene, Capability.ENTITIES_UNRESOLVED_MENTIONS, ListUnresolvedMentions())
    mentions = body["mentions"]
    assert mentions, "an unlinked observation was staged, so this must not be empty"
    first = mentions[0]  # type: ignore[index]
    assert first["normalized_value"]  # type: ignore[index]
    assert "observed_value" not in first  # type: ignore[operator]


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
