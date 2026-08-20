"""Every entity read answers a bounded page, and says so truthfully.

`RI-PR135-MAJOR-001`: `entities.relationships` was depth-bounded to one hop and
nothing else. Depth one bounds the *shape* of a traversal, not its *size* — an
organization every person on a programme works for has an edge per person, so
"one hop from Acme" and "a bounded number of rows" were being treated as the
same claim when only the first was ever made. `WP-RI-05` requires bounded output
and pagination; section 14.4 requires a tool schema that is "typed and bounded".

The assertions here are deliberately about the *indicator* rather than the
bound. A handler that silently returns twenty-five of two hundred edges has not
fixed anything: the caller reads twenty-five and concludes twenty-five. So each
test below stages more rows than the page admits and asserts three separate
things — that the page is short, that the disclosure says it is short, and that
the continuation it hands back actually reaches the rows it left out.

The last of those is what keeps the disclosure honest. `is_truncated` is proved
by fetching one row past the page and looking at the overflow, never by
comparing the page against the size that was asked for: `len(page) == page_size`
is true both for a corpus with more behind it and for one that ends exactly
there, and the two need different answers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.application.commands import (
    GetEntityContext,
    GetEntityRelationships,
    ListUnresolvedMentions,
    ResolveEntity,
    SearchEntities,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.context_card import CONTEXT_CARD_COLLECTION_LIMIT
from my_pa.domain.relationship.entity import (
    Entity,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import EntityObservation, ObservationKind
from my_pa.domain.relationship.normalization import normalize_name

HUB: Final = "ent_hub00001hub00001"
WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)

#: More edges than any page this suite asks for, and more than the context card
#: can carry. One past a limit proves the limit bit; a comfortable margin past it
#: also proves the *second* page is a real page rather than the remainder.
EDGES: Final = 40


def _entity(entity_id: str, display_name: str, principal_id: str, kind: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=kind,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def hub(scene: Scene) -> Scene:
    """One organization and `EDGES` people who work for it.

    A hub rather than a chain, because a hub is the shape that defeats a depth
    bound: every one of these edges is one hop from `HUB`, so a read bounded
    only by depth returns all forty of them.
    """
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(
            principal_id, _entity(HUB, "Acme Construction", principal_id, EntityType.ORGANIZATION)
        )
        for index in range(EDGES):
            person_id = f"ent_{index:04d}person{index:04d}"
            entities.create(
                principal_id,
                _entity(person_id, f"Person Number {index:04d}", principal_id, EntityType.PERSON),
            )
            entities.record_relationship(
                principal_id,
                EntityRelationship(
                    # Zero-padded so the identifier order the repository sorts
                    # and pages on is the order these were staged in. A cursor
                    # test whose keys sort differently from its staging order
                    # proves nothing about which rows were skipped.
                    relationship_id=f"erel_{index:04d}edge{index:04d}",
                    from_entity_id=person_id,
                    relationship_type=EntityRelationshipType.WORKS_FOR,
                    to_entity_id=HUB,
                    principal_id=principal_id,
                    state="active",
                    version=1,
                ),
            )
    return scene


def _envelope(scene: Scene, capability: Capability, command: object) -> ResponseEnvelope:
    service = build_service(scene.world, scene.providers)
    return service.invoke(
        metadata_for(capability, Purpose.ENTITY_READ, scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )


def _edges(envelope: ResponseEnvelope) -> list[dict[str, object]]:
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    edges = result["relationships"]
    assert isinstance(edges, list)
    return edges


# --- entities.relationships: the bound, and the cursor that survives it ------


def test_relationships_returns_at_most_one_page_of_a_hub(hub: Scene) -> None:
    """Forty edges, all one hop away, and the answer carries five."""
    envelope = _envelope(
        hub,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=HUB, page_size=5),
    )
    assert len(_edges(envelope)) == 5
    assert envelope.disclosure.truncation.is_truncated
    assert envelope.disclosure.truncation.reason == "page_size_reached"


def test_a_truncated_page_hands_back_a_cursor_that_reaches_the_next_rows(hub: Scene) -> None:
    """The continuation is real, not decorative.

    A `next_cursor` nobody can use is worse than none: it tells a caller there
    is more and gives them no way to it, which reads as a bug in their client
    rather than in this handler.
    """
    first = _envelope(
        hub,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=HUB, page_size=5),
    )
    cursor = first.disclosure.truncation.next_cursor
    assert cursor is not None
    page_one = [edge["relationship_id"] for edge in _edges(first)]
    assert cursor == page_one[-1]

    second = _envelope(
        hub,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=HUB, page_size=5, after=cursor),
    )
    page_two = [edge["relationship_id"] for edge in _edges(second)]
    # Strictly after: no overlap, and no gap either. An off-by-one in either
    # direction silently drops a relationship or repeats one, and only comparing
    # against the whole staged order catches the second kind.
    assert set(page_one) & set(page_two) == set()
    assert page_one + page_two == [f"erel_{index:04d}edge{index:04d}" for index in range(10)]


def test_walking_the_cursor_reaches_every_edge_exactly_once(hub: Scene) -> None:
    """The pagination is *complete*: bounding a read must not lose a row.

    A bound that a caller cannot walk past is a disclosure that some of their
    own records are unreachable, which is a different failure from the one being
    fixed and just as bad.
    """
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(EDGES):
        envelope = _envelope(
            hub,
            Capability.ENTITIES_RELATIONSHIPS,
            GetEntityRelationships(entity_id=HUB, page_size=7, after=cursor),
        )
        seen.extend(str(edge["relationship_id"]) for edge in _edges(envelope))
        cursor = envelope.disclosure.truncation.next_cursor
        if cursor is None:
            break
    assert cursor is None, "the walk never terminated"
    assert seen == [f"erel_{index:04d}edge{index:04d}" for index in range(EDGES)]


def test_a_final_page_is_not_reported_as_truncated(hub: Scene) -> None:
    """The overflow row, not the page size, is what decides.

    `len(page) == page_size` is true of the last page of a larger corpus *and*
    of a corpus that ends exactly there. Asking for one more row is what tells
    them apart, and `EDGES` divides evenly by this page size on purpose so the
    final page is exactly full.
    """
    cursor = f"erel_{EDGES - 6:04d}edge{EDGES - 6:04d}"
    envelope = _envelope(
        hub,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=HUB, page_size=5, after=cursor),
    )
    assert len(_edges(envelope)) == 5
    assert envelope.disclosure.truncation.is_truncated is False
    assert envelope.disclosure.truncation.next_cursor is None


def test_a_truncated_page_does_not_also_claim_it_has_no_continuation(hub: Scene) -> None:
    """`LISTING_HAS_NO_CONTINUATION` and `next_cursor` cannot both be right.

    The limitation exists for listings this build issues no cursor for. Emitting
    it beside a working cursor would tell a caller to stop while handing them
    the means to go on, and a caller that believes the limitation stops.
    """
    envelope = _envelope(
        hub,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=HUB, page_size=5),
    )
    assert envelope.disclosure.truncation.next_cursor is not None
    assert "listing_has_no_continuation_cursor" not in list(envelope.disclosure.limitations)


def test_relationships_refuses_a_cursor_that_is_not_a_relationship_identifier() -> None:
    """Refused at the command, not silently ordered into the middle of the key space.

    The cursor is compared against `relationship_id` directly. An arbitrary
    string does not fail — it sorts somewhere, and every edge before that point
    is skipped with no indication that anything was.
    """
    with pytest.raises(InvalidRequestError):
        GetEntityRelationships(entity_id=HUB, after="not-an-identifier")
    with pytest.raises(InvalidRequestError):
        GetEntityRelationships(entity_id=HUB, page_size=0)


# --- entities.search: a full page is not the same as a truncated one ---------


def test_search_does_not_call_an_exactly_full_page_truncated(hub: Scene) -> None:
    """`EDGES` people plus one organization, asked for in a page that fits them.

    The old test — `len(found) == page_size` — reported truncation here, and
    then raised rather than answering, because `Truncation` refuses
    `is_truncated` without a reason. So the single arrangement of rows that made
    the claim true was the arrangement that produced no response at all.
    """
    envelope = _envelope(
        hub, Capability.ENTITIES_SEARCH, SearchEntities(query="Person", page_size=EDGES)
    )
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    found = result["entities"]
    assert isinstance(found, list)
    assert len(found) == EDGES
    assert envelope.disclosure.truncation.is_truncated is False


def test_search_reports_truncation_with_a_cursor_when_a_row_was_left_out(hub: Scene) -> None:
    """Search pages now, so it discloses a continuation rather than the absence of one.

    This test asserted `listing_has_no_continuation_cursor` — correctly, while
    `entities.search` was the last read on the plane that could be truncated and
    not paged. Issuing that limitation beside a real cursor would tell a caller
    to stop while handing them the means to go on.
    """
    envelope = _envelope(
        hub, Capability.ENTITIES_SEARCH, SearchEntities(query="Person", page_size=EDGES - 1)
    )
    assert envelope.disclosure.truncation.is_truncated
    assert envelope.disclosure.truncation.reason == "page_size_reached"
    assert envelope.disclosure.truncation.next_cursor is not None
    assert "listing_has_no_continuation_cursor" not in list(envelope.disclosure.limitations)


def test_walking_the_search_pages_reaches_every_entity_exactly_once(hub: Scene) -> None:
    """The cursor the capability issues is one a caller can actually walk with."""
    walked: list[str] = []
    cursor: str | None = None
    for _ in range(EDGES + 2):
        envelope = _envelope(
            hub,
            Capability.ENTITIES_SEARCH,
            SearchEntities(query="Person", page_size=2, after=cursor),
        )
        page = envelope.to_canonical_dict()["result"]["entities"]  # type: ignore[index,call-overload]
        if not page:
            break
        walked.extend(str(row["entity_id"]) for row in page)  # type: ignore[index]
        cursor = envelope.disclosure.truncation.next_cursor
        if cursor is None:
            break
    assert len(walked) == len(set(walked)), walked
    assert len(walked) >= EDGES


# --- entities.context: the card's collections are bounded at the query -------


def test_a_context_card_bounds_its_relationships_and_says_so(hub: Scene) -> None:
    """The card carries its ceiling, and the limitation is read off the overflow.

    `EDGES` exceeds `CONTEXT_CARD_COLLECTION_LIMIT`, so this asserts both halves
    at once: the list is short and the card admits it. A card that carried forty
    edges would fail `EntityContextCard.__post_init__`; one that carried
    twenty-five in silence would pass every earlier test in this repository.
    """
    envelope = _envelope(hub, Capability.ENTITIES_CONTEXT, GetEntityContext(entity_id=HUB))
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    card = result["context_card"]
    assert isinstance(card, dict)
    edges = card["relationships"]
    assert isinstance(edges, list)
    assert len(edges) == CONTEXT_CARD_COLLECTION_LIMIT
    assert "more_relationships_than_this_card_carries" in card["limitations"]
    assert card["is_complete"] is False
    assert envelope.disclosure.truncation.is_truncated


def test_a_context_card_asks_the_repository_for_only_what_it_can_carry(hub: Scene) -> None:
    """The bound is a query-time limit, not a slice of everything.

    This is the half of `RI-PR135-MAJOR-001` that no payload assertion can
    reach: a card that fetched all forty edges and kept twenty-five looks
    identical on the wire to one that fetched twenty-six. The difference is the
    cost, and the only place it is visible is the argument the port received —
    so the argument is what is asserted.
    """
    principal_id = hub.principal.principal_id
    asked: list[int | None] = []
    with FakeUnitOfWork(hub.world) as unit_of_work:
        entities = unit_of_work.entities
        original = entities.relationships

        def recording(*args: object, **kwargs: object) -> list[EntityRelationship]:
            asked.append(kwargs.get("limit"))  # type: ignore[arg-type]
            return original(*args, **kwargs)  # type: ignore[arg-type]

        entities.relationships = recording  # type: ignore[method-assign]
        from my_pa.application.entity_context import EntityContextService

        EntityContextService(entities).card(principal_id, HUB, assembled_at=WHEN)

    assert asked == [CONTEXT_CARD_COLLECTION_LIMIT + 1]


# --- entities.resolve: a dropped candidate is disclosed, not raised ----------


def test_resolve_answers_rather_than_raising_when_it_drops_a_candidate(hub: Scene) -> None:
    """Every `Person Number …` is a distinct name, so this resolves nothing.

    The assertion is narrow on purpose: it is that the handler *answers*. The
    truncation branch of this handler used to construct a `Truncation` with no
    reason, which raises — so the disclosure that exists to admit a dropped
    candidate was the one path that could not be taken.
    """
    envelope = _envelope(
        hub, Capability.ENTITIES_RESOLVE, ResolveEntity(reference="Person Number 0001")
    )
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    truncation = envelope.disclosure.truncation
    assert truncation.is_truncated is False or truncation.reason == "candidate_limit_reached"


# --- the queue's continuation ----------------------------------------------


QUEUED: Final = 12


@pytest.fixture
def queue(scene: Scene) -> Scene:
    """`QUEUED` mentions nothing has placed, in the order the queue serves them."""
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        for index in range(QUEUED):
            unit_of_work.entities.record_observation(
                principal_id,
                EntityObservation(
                    # Zero-padded for the reason the edge identifiers are: the
                    # queue orders and pages on this column, so staging order
                    # and served order have to be the same or a walk test
                    # proves nothing about which rows were skipped.
                    observation_id=f"eobs_{index:04d}queue{index:04d}",
                    principal_id=principal_id,
                    kind=ObservationKind.MESSAGE_PARTICIPANT,
                    observed_value=f"Unplaced Person {index:04d}",
                    normalized_value=normalize_name(f"Unplaced Person {index:04d}"),
                    source_id=scene.source.source_id,
                    source_object_id=scene.markdown.source_object_id,
                    source_version_id=f"ver_{index:04d}queue{index:04d}",
                    observed_at=WHEN,
                    recorded_at=WHEN,
                ),
            )
    return scene


def _mentions(envelope: ResponseEnvelope) -> list[dict[str, object]]:
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    mentions = result["mentions"]
    assert isinstance(mentions, list)
    return mentions


def test_walking_the_queue_reaches_every_mention_exactly_once(queue: Scene) -> None:
    """The queue shipped with a cursor and no test of it.

    Deleting `after_observation_id=command.after` from the handler left the
    whole suite green: the cursor was accepted, ignored, and every page was page
    one. An operator working a queue longer than one page would have seen the
    same mentions forever and never reached the tail — and the plane would have
    reported that as normal operation.
    """
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(QUEUED):
        envelope = _envelope(
            queue,
            Capability.ENTITIES_UNRESOLVED_MENTIONS,
            ListUnresolvedMentions(page_size=5, after=cursor),
        )
        seen.extend(str(row["observation_id"]) for row in _mentions(envelope))
        cursor = envelope.disclosure.truncation.next_cursor
        if cursor is None:
            break
    assert cursor is None, "the walk never terminated"
    assert seen == [f"eobs_{index:04d}queue{index:04d}" for index in range(QUEUED)]
    assert len(seen) == len(set(seen)), "a mention was served on two pages"


def test_the_queue_discloses_a_continuation_only_while_one_remains(queue: Scene) -> None:
    """`is_truncated` and `next_cursor` are one fact and may not disagree."""
    first = _envelope(
        queue,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
        ListUnresolvedMentions(page_size=5),
    )
    assert first.disclosure.truncation.is_truncated is True
    cursor = first.disclosure.truncation.next_cursor
    assert cursor == f"eobs_{4:04d}queue{4:04d}"

    last = _envelope(
        queue,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
        ListUnresolvedMentions(page_size=50, after=cursor),
    )
    assert last.disclosure.truncation.is_truncated is False
    assert last.disclosure.truncation.next_cursor is None


def test_the_queue_refuses_a_cursor_that_is_not_an_observation_identifier() -> None:
    """Refused at the command, on the same terms `entities.relationships` is.

    The cursor is compared against `observation_id` directly, so an arbitrary
    string does not fail — it sorts somewhere, and every mention before that
    point is skipped with nothing saying so. An entity identifier is the
    plausible mistake and is refused too: it is well-formed, and it is not a
    position in this ordering.
    """
    with pytest.raises(InvalidRequestError):
        ListUnresolvedMentions(after="not-an-identifier")
    with pytest.raises(InvalidRequestError):
        ListUnresolvedMentions(after=HUB)
    with pytest.raises(InvalidRequestError):
        ListUnresolvedMentions(page_size=0)


# --- what an unreadable cursor answers on the wire --------------------------


def test_an_unreadable_cursor_answers_not_found_naming_the_cursor(queue: Scene) -> None:
    """The classifier `_entity_translated` exists for, pinned at the wire.

    Every `UnknownScopeError` used to become `not_found` naming
    `enrollment_id` — a field this plane does not model and the request does not
    carry. The three paged entity reads classify it as `cursor` instead, which
    is the same field the command already names when the cursor is *malformed*.

    **This is a FAST test deliberately.** The rule had coverage only in the
    database tier, and `_entity_translated` itself had none anywhere: replacing
    it with a null context left the whole fast selection green, so the wrong
    field could return without a single test noticing.

    The cursor here is well-formed and names an observation the acting
    Principal does not hold, which is what the repository refuses.
    """
    foreign = "eobs_9999zzzz9999zzzz"
    envelope = _envelope(
        queue,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
        ListUnresolvedMentions(after=foreign),
    )
    body = envelope.to_canonical_dict()
    assert body["result"] is None
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.NOT_FOUND.value
    assert error["safe_details"] == [SafeDetail.CURSOR.value]
    # The refusal names the field and nothing about the record, so it cannot be
    # used to learn that some other Principal holds one.
    assert foreign not in repr(body)


def test_a_relationship_cursor_the_caller_cannot_read_answers_the_same_way(hub: Scene) -> None:
    """The sibling, because a rule proved on one read is proved on one read."""
    foreign = "erel_9999zzzz9999zzzz"
    envelope = _envelope(
        hub,
        Capability.ENTITIES_RELATIONSHIPS,
        GetEntityRelationships(entity_id=HUB, after=foreign),
    )
    body = envelope.to_canonical_dict()
    assert body["result"] is None
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.NOT_FOUND.value
    assert error["safe_details"] == [SafeDetail.CURSOR.value]


def test_a_search_cursor_the_caller_cannot_read_answers_the_same_way(hub: Scene) -> None:
    """The third of three. All the same answer, so a BFF handles one case."""
    envelope = _envelope(
        hub,
        Capability.ENTITIES_SEARCH,
        SearchEntities(query="Person", after="ent_9999zzzz9999zzzz9"),
    )
    body = envelope.to_canonical_dict()
    assert body["result"] is None
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.NOT_FOUND.value
    assert error["safe_details"] == [SafeDetail.CURSOR.value]
