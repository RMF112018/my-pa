"""WP4-S4: `communications.search`, `.read` and `.coverage` services on PostgreSQL.

The `database` tier, on a disposable head-migrated clone, through
`CommunicationsReads` over the real unit of work and the real search statement
(contract sections 9, 13, 14 and 16; WP4 rulings D4-final, D8, D9, R6-R13).
Proved here: FTS correctness; identifier exactness end to end (`RFI 17` is not
`RFI 174`); the tiers; the total order (equal rank and time differ by id);
cursor exactness for every limit; collapse (the representative is the best
ranked, `conversation_hits`, stable pages); the quoted-phrase `strpos`
confirmation; participants `any` and `all`; the folder-role lane claim with
per-result lanes; a withheld body never returned; foreign ids `not_found`
exactly as unknown ones; the stop-word fallback (only it finds a stop-word
name, and a normal query does not trigger it); `no_searchable_terms`; the
identifiers merged from the query; coverage `complete`, `partial` and `none`;
the versions and `identifier_version_pending`; the thread view 25 per page.
Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.communications_search import (
    CoverageRequest,
    ReadRequest,
    SearchAnswer,
    SearchRequest,
)
from my_pa.application.errors import ConflictError, NotFoundError
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION_V1
from my_pa.domain.communications.search_query import quoted_phrases
from tests.database.communications_search_world import OTHER, P, World, at, reads

pytestmark = pytest.mark.database

A: Final = "alpha@example.invalid"
B: Final = "bravo@example.invalid"
C: Final = "charlie@example.invalid"
GRANTS: Final = (("communications.search", "communications_read"),)


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[dict[str, str]]:
    """The standard synthetic world (days 17, 18 and 20 covered; 19 a gap)."""
    w = World(migrated_engine)
    ids = {
        "slab": w.message(
            1,
            subject="Slab pour schedule",
            text="The slab pour moves to Friday per RFI 174.",
            when=at(17, 10),
            conversation="conv-slab",
            participants=(("from", A), ("to", B)),
        ),
        "slab_reply": w.message(
            2,
            subject="Re: Slab pour schedule",
            text="Confirmed. Slab pour slab pour; see RFI 17 as well.",
            when=at(20, 13),  # the conversation spans the whole browse
            conversation="conv-slab",
            participants=(("from", B), ("to", A)),
            lanes=(("sent", "unverified_lane_claim"),),
        ),
        "pricing": w.message(
            3,
            subject="Pricing",
            text="PCO 3 and RFI 5 pricing attached.",
            when=at(18, 9),
            conversation="conv-pricing",
            participants=(("from", C), ("to", A), ("cc", B)),
            lanes=(("inbox", "unverified_lane_claim"), ("sent", "verified")),
        ),
        "answered": w.message(
            4,
            subject="Pricing follow up",
            text="RFI 5 answered.",
            when=at(18, 10),
            conversation="conv-answered",
            participants=(("from", A), ("to", C)),
        ),
        "orders": w.message(
            5,
            subject="Deck",
            text="We reviewed the change orders for the deck.",
            when=at(18, 11),
            conversation="conv-orders",
        ),
        "ordering": w.message(
            6,
            subject="Deliveries",
            text="The supplier changed ordering of the deliveries.",
            when=at(18, 12),
            conversation="conv-ordering",
        ),
        "will": w.message(
            7,
            subject="Plans",
            text="Will sent the revised plans.",
            when=at(20, 9),
            conversation="conv-will",
        ),
        "withheld": w.message(
            8,
            subject="RFI 5 privileged",
            text=None,
            when=at(20, 10),
            conversation="conv-withheld",
            body_state="withheld",
        ),
        "tie_a": w.message(9, subject="Tie case", text="tie breaker text", when=at(20, 11)),
        "tie_b": w.message(10, subject="Tie case", text="tie breaker text", when=at(20, 11)),
    }
    other = World(migrated_engine, principal_id=OTHER, tag="z")
    ids["foreign"] = other.message(
        1, subject="Slab pour schedule", text="The slab pour per RFI 174.", when=at(17, 10)
    )
    yield ids


def _ids(answer: SearchAnswer) -> list[str]:
    return [result.message_id for result in answer.results]


def search(engine: Engine, **fields: object) -> SearchAnswer:
    return reads(engine).search(P, SearchRequest(**fields), grants=GRANTS)  # type: ignore[arg-type]


# ---- FTS and identifiers ----------------------------------------------------------------


def test_fts_finds_the_text_and_never_another_principals_row(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    answer = search(migrated_engine, query="slab", collapse="none")
    assert set(_ids(answer)) == {world["slab"], world["slab_reply"]}
    assert world["foreign"] not in _ids(answer)
    assert answer.text_fallback is None  # a normal query does not trigger the fallback
    assert answer.query_state is None
    assert all(result.tier == 3 and result.rank > 0 for result in answer.results)
    # The reply says "slab pour" three times: it ranks first.
    assert _ids(answer)[0] == world["slab_reply"]


def test_identifier_exactness_end_to_end(migrated_engine: Engine, world: dict[str, str]) -> None:
    exact = search(migrated_engine, identifiers=["RFI 17"], collapse="none")
    assert _ids(exact) == [world["slab_reply"]]
    assert exact.identifiers == ("rfi:17",)
    other = search(migrated_engine, identifiers=["rfi:174"], collapse="none")
    assert _ids(other) == [world["slab"]]
    assert other.results[0].matched_identifier_kinds == ("rfi",)


def test_the_tiers(migrated_engine: Engine, world: dict[str, str]) -> None:
    answer = search(
        migrated_engine, query="pricing", identifiers=["RFI 5", "PCO 3"], collapse="none"
    )
    tiers = {result.message_id: result.tier for result in answer.results}
    assert tiers[world["pricing"]] == 1  # both
    assert tiers[world["answered"]] == 2  # RFI 5 only
    assert tiers[world["withheld"]] == 2  # RFI 5 in its subject
    assert [r.tier for r in answer.results] == sorted(r.tier for r in answer.results)
    pricing = next(r for r in answer.results if r.message_id == world["pricing"])
    assert pricing.matched_identifier_kinds == ("pco", "rfi")


def test_identifiers_in_the_query_are_merged_and_tiered(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    answer = search(migrated_engine, query="RFI 174 schedule", collapse="none")
    assert answer.identifiers == ("rfi:174",)
    assert answer.results[0].message_id == world["slab"]
    assert answer.results[0].tier == 1
    # A negated identifier excludes; it is not asked for.
    negated = search(migrated_engine, query='slab -"RFI 174"', collapse="none")
    assert negated.identifiers == ()
    assert _ids(negated) == [world["slab_reply"]]


def test_a_negated_term_excludes_an_identifier_match_too(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """WP4-R2 G4: `-word` excludes in every tier, not only among the text matches."""
    asked = search(migrated_engine, query="RFI 5", collapse="none")
    assert set(_ids(asked)) == {world["pricing"], world["answered"], world["withheld"]}
    # "PCO 3 and RFI 5 pricing attached." is an RFI 5 identifier match; it is excluded.
    word = search(migrated_engine, query="RFI 5 -attached", collapse="none")
    assert word.identifiers == ("rfi:5",)
    assert set(_ids(word)) == {world["answered"], world["withheld"]}
    phrase = search(migrated_engine, query='RFI 5 -"pricing attached"', collapse="none")
    assert set(_ids(phrase)) == {world["answered"], world["withheld"]}
    # The exclusion reads the stored document: "Pricing" in a subject excludes too.
    stemmed = search(migrated_engine, query="RFI 5 -pricing", collapse="none")
    assert _ids(stemmed) == [world["withheld"]]
    by_field = search(
        migrated_engine, query="pricing -attached", identifiers=["RFI 5"], collapse="none"
    )
    assert set(_ids(by_field)) == {world["answered"], world["withheld"]}
    # A negated `english` stop word has no lexeme there: it excludes nothing.
    stop_word = search(migrated_engine, query="RFI 5 -the", collapse="none")
    assert set(_ids(stop_word)) == set(_ids(asked))


def test_the_total_order_breaks_equal_rank_and_time_by_id(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    answer = search(migrated_engine, query="tie breaker", collapse="none")
    first, second = answer.results
    assert (first.rank, first.message_time) == (second.rank, second.message_time)
    assert [first.message_id, second.message_id] == sorted(
        [world["tie_a"], world["tie_b"]], reverse=True
    )


# ---- cursor exactness and collapse -------------------------------------------------------


def _all_pages(engine: Engine, limit: int, **fields: object) -> list[str]:
    seen: list[str] = []
    cursor = None
    for _ in range(100):
        answer = search(engine, limit=limit, cursor=cursor, **fields)
        seen.extend(_ids(answer))
        cursor = answer.next_cursor
        if cursor is None:
            return seen
    raise AssertionError("the pages never ended")


@pytest.mark.parametrize("collapse", ["conversation", "none"])
def test_concatenated_pages_equal_the_unpaged_order_for_every_limit(
    migrated_engine: Engine, world: dict[str, str], collapse: str
) -> None:
    whole = _ids(search(migrated_engine, limit=50, collapse=collapse))
    assert len(whole) == (9 if collapse == "conversation" else 10)
    for limit in range(1, len(whole) + 1):
        assert _all_pages(migrated_engine, limit, collapse=collapse) == whole, limit
    ranked = _ids(search(migrated_engine, query="slab pour", limit=50, collapse=collapse))
    for limit in range(1, len(ranked) + 1):
        assert _all_pages(migrated_engine, limit, query="slab pour", collapse=collapse) == ranked


def test_collapse_keeps_the_best_ranked_message_of_a_conversation(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    collapsed = search(migrated_engine, query="slab pour")
    assert _ids(collapsed) == [world["slab_reply"]]  # ranks above the first message
    assert collapsed.results[0].conversation_hits == 2
    one_conversation = search(
        migrated_engine, query="slab pour", conversation_id="conv-slab", collapse="conversation"
    )
    assert set(_ids(one_conversation)) == {world["slab"], world["slab_reply"]}


def test_a_page_continues_after_the_collapsed_representative(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """The keyset is applied after the collapse (D9).

    The slab conversation's representative (its latest message) heads the
    browse and its first message is the oldest row of the world. Keyed before
    the collapse, every page after the first would elect that older message as
    the conversation's representative and show the conversation again.
    """
    first = search(migrated_engine, limit=1)
    assert _ids(first) == [world["slab_reply"]]
    for limit in (1, 2, 3):
        rest = _all_pages(migrated_engine, limit)
        assert len(rest) == len(set(rest)) == 9
        assert world["slab_reply"] in rest and world["slab"] not in rest


def test_a_cursor_for_another_request_or_principal_conflicts(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    cursor = search(migrated_engine, limit=1).next_cursor
    assert cursor is not None
    with pytest.raises(ConflictError):
        search(migrated_engine, limit=1, query="slab", cursor=cursor)
    with pytest.raises(ConflictError):
        reads(migrated_engine).search(OTHER, SearchRequest(limit=1, cursor=cursor), grants=GRANTS)
    changed = reads(migrated_engine).search(P, SearchRequest(limit=1, cursor=cursor), grants=())
    assert (changed.cursor_state, changed.results) == ("scope_changed_restart_required", ())


# ---- phrases, participants, lanes ------------------------------------------------------


def test_a_quoted_phrase_is_confirmed_exactly(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    # Both stem to `chang <-> order`; only the exact phrase is kept.
    stemmed = search(migrated_engine, query="change orders", collapse="none")
    assert {world["orders"], world["ordering"]} <= set(_ids(stemmed))
    exact = search(migrated_engine, query='"change orders"', collapse="none")
    assert _ids(exact) == [world["orders"]]


def test_a_quoted_phrase_never_spans_the_subject_and_the_text(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """WP4-R2 G5: "Slab pour schedule" then "The slab pour ..." is not "schedule the slab"."""
    spanning = search(migrated_engine, query='"schedule the slab"', collapse="none")
    assert _ids(spanning) == []
    in_subject = search(migrated_engine, query='"pour schedule"', collapse="none")
    assert set(_ids(in_subject)) == {world["slab"], world["slab_reply"]}
    # WP4-R3 R3-2: the subject is case-folded too ("Slab pour schedule").
    folded = search(migrated_engine, query='"slab pour schedule"', collapse="none")
    assert set(_ids(folded)) == {world["slab"], world["slab_reply"]}
    in_text = search(migrated_engine, query='"moves to friday"', collapse="none")
    assert _ids(in_text) == [world["slab"]]


def test_the_phrase_parse_matches_the_server(migrated_engine: Engine) -> None:
    queries = ['"change orders" deck', 'a -"b c" "d  e', '"x" "" y', 'q "slab, pour"']
    with migrated_engine.connect() as connection:
        for query in queries:
            server = connection.execute(
                text("SELECT websearch_to_tsquery('simple', :q)::text"), {"q": query}
            ).scalar_one()
            for phrase in quoted_phrases(query):
                alone = connection.execute(
                    text("SELECT websearch_to_tsquery('simple', :q)::text"),
                    {"q": f'"{phrase}"'},
                ).scalar_one()
                assert alone in server, (query, phrase)
            negated = connection.execute(
                text("SELECT websearch_to_tsquery('simple', :q)::text"), {"q": '"b c"'}
            ).scalar_one()
            if "-" in query:
                assert f"!( {negated} )" in server or f"!{negated}" in server


def test_participants_any_and_all(migrated_engine: Engine, world: dict[str, str]) -> None:
    any_of = search(migrated_engine, participants=[C, "NOBODY@example.invalid"], collapse="none")
    assert set(_ids(any_of)) == {world["pricing"], world["answered"]}
    all_of = search(migrated_engine, participants=[A, B, C], participant_mode="all")
    assert _ids(all_of) == [world["pricing"]]
    assert all_of.results[0].participant_overlap == 3
    both = search(migrated_engine, participants=[A, B], participant_mode="all", collapse="none")
    assert set(_ids(both)) == {world["slab"], world["slab_reply"], world["pricing"]}


def test_the_folder_role_is_a_lane_claim_with_per_result_lanes(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    sent = search(migrated_engine, folder_role="sent", collapse="none")
    assert set(_ids(sent)) == {world["slab_reply"], world["pricing"]}
    lanes = {
        r.message_id: {(lane.folder_role, lane.lane_verification) for lane in r.lanes}
        for r in sent.results
    }
    assert lanes[world["slab_reply"]] == {("sent", "unverified_lane_claim")}
    assert lanes[world["pricing"]] == {("inbox", "unverified_lane_claim"), ("sent", "verified")}


# ---- withheld bodies and not_found -------------------------------------------------------


def test_a_withheld_body_is_never_returned(migrated_engine: Engine, world: dict[str, str]) -> None:
    found = search(migrated_engine, identifiers=["RFI 5"], collapse="none")
    withheld = next(r for r in found.results if r.message_id == world["withheld"])
    assert (withheld.body_state, withheld.snippet) == ("withheld", None)
    read = reads(migrated_engine).read(P, ReadRequest(message_ids=[world["withheld"]]))
    (message,) = read.messages
    assert (message.search_text, message.text_omitted) == (None, "no_text")


def test_foreign_and_unknown_ids_are_not_found_alike(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    unknown = "cmsg_srchnotthere1"
    answer = reads(migrated_engine).read(
        P, ReadRequest(message_ids=[world["foreign"], world["slab"], unknown])
    )
    assert [m.message_id for m in answer.messages] == [world["slab"]]
    assert answer.not_found == (world["foreign"], unknown)
    alone_foreign = reads(migrated_engine).read(P, ReadRequest(message_ids=[world["foreign"]]))
    alone_unknown = reads(migrated_engine).read(P, ReadRequest(message_ids=[unknown]))
    assert replace(alone_foreign, not_found=()) == replace(alone_unknown, not_found=())


def test_a_read_carries_participants_provenance_coverage_and_identifiers(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    (message,) = (
        reads(migrated_engine).read(P, ReadRequest(message_ids=[world["pricing"]])).messages
    )
    assert message.search_text == "PCO 3 and RFI 5 pricing attached."
    assert message.identifiers == ("pco:3", "rfi:5")
    assert message.coverage.coverage_state == "complete"
    assert message.coverage.start == at(18, 0)
    assert message.observations.count == 2
    assert dict(message.observations.by_folder_role) == {"inbox": 1, "sent": 1}
    cc = next(p for p in message.participants if p.field == "cc")
    assert (cc.address, len(cc.sources)) == (B, 2)
    assert message.search_text_version == "comms_search_text_v2"


# ---- the stop-word fallback (ruling D4-final) and query states ---------------------------


def test_a_stop_word_name_is_found_only_through_the_flagged_fallback(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    with migrated_engine.connect() as connection:
        english = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.communication_messages"
                " WHERE search_document @@ websearch_to_tsquery('english', 'Will')"
            )
        ).scalar_one()
    assert english == 0  # `english` drops the stop word: no stored-document match
    answer = search(migrated_engine, query="Will", collapse="none")
    assert _ids(answer) == [world["will"]]
    assert answer.text_fallback == "simple_stopwords"
    assert answer.results[0].rank > 0
    assert answer.results[0].snippet is not None


def test_the_fallback_ranks_by_the_greater_of_the_two_ranks(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """WP4-R2 G2 (D4-final): the rank is the greater of the `english` and `simple` ranks.

    `the or slab` keeps `slab` under `english` and `the | slab` under `simple`.
    A message with "the" and no "slab" has no `english` rank at all; its rank
    is its `simple` one.
    """
    query = "the or slab"
    answer = search(migrated_engine, query=query, collapse="none", limit=50)
    assert answer.text_fallback == "simple_stopwords"
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT message_id,"
                " floor(ts_rank_cd(search_document,"
                "   websearch_to_tsquery('english', :q)) * 1000000)::bigint,"
                " floor(ts_rank_cd(to_tsvector('simple',"
                "   coalesce(subject, '') || ' ' || coalesce(search_text, '')),"
                "   websearch_to_tsquery('simple', :q)) * 1000000)::bigint"
                " FROM knowledge.communication_messages WHERE message_id = ANY(:ids)"
            ),
            {"q": query, "ids": _ids(answer)},
        ).all()
    expected = {str(row[0]): (int(row[1]), int(row[2])) for row in rows}
    ranks = {r.message_id: r.rank for r in answer.results}
    assert ranks == {mid: max(pair) for mid, pair in expected.items()}
    english, simple = expected[world["will"]]  # "Will sent the revised plans."
    assert english == 0 < simple == ranks[world["will"]]


def test_a_query_with_no_searchable_term_is_a_flagged_browse(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    answer = search(migrated_engine, query="!!! &&", collapse="none", limit=50)
    assert answer.query_state == "no_searchable_terms"
    assert len(answer.results) == 10
    assert all(r.rank == 0 and r.tier == 3 for r in answer.results)


# ---- versions and coverage (D8, R13) ----------------------------------------------------


def test_versions_and_pending_identifier_version(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    answer = search(migrated_engine, query="slab")
    assert answer.versions.search_text_versions == ("comms_search_text_v2",)
    assert answer.versions.identifier_version == "comms_identifiers_v2"
    assert answer.versions.identifier_version_pending == 0
    v1 = reads(migrated_engine, identifier_version=IDENTIFIER_VERSION_V1).search(
        P, SearchRequest(query="slab")
    )
    assert v1.versions.identifier_version_pending == 10


def test_identifiers_are_searched_and_read_at_the_reader_version_only(
    migrated_engine: Engine,
) -> None:
    """WP4-R2 G1: v1 rows stay beside v2 rows (R4); a reader sees its version's only.

    `RFI 10:30` is a meeting time: v1 stored `rfi:10`, v2 extracts nothing. A
    v2 reader neither finds the message by `RFI 10` nor lists the v1 row; a
    v1 reader does both.
    """
    w = World(migrated_engine)
    meeting = w.message(
        1,
        subject="Site walk",
        text="Meet at RFI 10:30 on site.",
        when=at(17, 9),
        extra_identifiers=(("rfi", "10", IDENTIFIER_VERSION_V1),),
    )
    v2 = reads(migrated_engine)
    v1 = reads(migrated_engine, identifier_version=IDENTIFIER_VERSION_V1)
    found_v2 = v2.search(P, SearchRequest(identifiers=["RFI 10"]), grants=GRANTS)
    assert (found_v2.identifiers, _ids(found_v2)) == (("rfi:10",), [])
    found_v1 = v1.search(P, SearchRequest(identifiers=["RFI 10"]), grants=GRANTS)
    assert _ids(found_v1) == [meeting]
    assert found_v1.results[0].tier == 1
    (read_v2,) = v2.read(P, ReadRequest(message_ids=[meeting])).messages
    assert read_v2.identifiers == ()
    (read_v1,) = v1.read(P, ReadRequest(message_ids=[meeting])).messages
    assert read_v1.identifiers == ("rfi:10",)


def test_search_coverage_of_the_queried_range(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    whole = search(migrated_engine).coverage
    assert (whole.state, whole.start, whole.end) == ("partial", at(17, 0), whole.latest_covered)
    assert whole.gaps_total == 1  # day 19
    assert whole.freshness_seconds is not None
    covered = search(migrated_engine, from_utc=at(17, 0), to_utc=at(18, 23)).coverage
    assert (covered.state, covered.gaps) == ("complete", ())
    later = search(migrated_engine, from_utc=at(22, 0), to_utc=at(23, 0)).coverage
    assert later.state == "none"


def test_the_coverage_read(migrated_engine: Engine, world: dict[str, str]) -> None:
    service = reads(migrated_engine)
    partial = service.coverage(P, CoverageRequest(from_utc=at(17, 0), to_utc=at(20, 12)))
    assert partial.coverage.state == "partial"
    assert len(partial.coverage.intervals) == 2
    assert partial.coverage.snapshot_count == 3
    complete = service.coverage(P, CoverageRequest(from_utc=at(20, 0), to_utc=at(20, 12)))
    assert complete.coverage.state == "complete"
    none = service.coverage(P, CoverageRequest(from_utc=at(25, 0), to_utc=at(26, 0)))
    assert none.coverage.state == "none"
    source = "isrc_srchasource"
    one = service.coverage(P, CoverageRequest(from_utc=at(17, 0), to_utc=at(17, 12), source=source))
    assert one.coverage.state == "complete"
    with pytest.raises(NotFoundError):
        service.coverage(P, CoverageRequest(at(17, 0), at(17, 12), source="isrc_srchzsource"))
    with pytest.raises(NotFoundError):
        service.coverage(P, CoverageRequest(at(17, 0), at(17, 12), source="isrc_srchnotthere"))


# ---- thread view -------------------------------------------------------------------------


def test_the_thread_view_pages_25_with_a_cursor(migrated_engine: Engine) -> None:
    w = World(migrated_engine)
    made = [
        w.message(100 + n, subject="Thread", text=f"note {n}", when=at(17, 8, n), conversation="t")
        for n in range(30)
    ]
    service = reads(migrated_engine)
    first = service.read(P, ReadRequest(conversation_id="t"), grants=GRANTS)
    assert [m.message_id for m in first.messages] == made[:25]
    assert first.next_cursor is not None
    second = service.read(
        P, ReadRequest(conversation_id="t", cursor=first.next_cursor), grants=GRANTS
    )
    assert [m.message_id for m in second.messages] == made[25:]
    assert second.next_cursor is None
    missing = service.read(P, ReadRequest(conversation_id="nope"))
    assert (missing.messages, missing.not_found) == ((), ("nope",))


# ---- WP4-S5: the wired capabilities over the real unit of work ---------------------------


def test_the_wired_reads_answer_through_the_service_in_its_own_unit_of_work(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """The 3 `communications.*` reads, invoked through `ApplicationService` with the switch on.

    The reads run inside the invocation's own transaction (the handler never
    opens a second one); the answers carry the versions and coverage; another
    Principal's ids are `not_found`; with the switch off the same request is the
    standard `unsupported`.
    """
    from my_pa.adapters.normalization import normalize
    from my_pa.application.service import ApplicationService
    from my_pa.domain.identity.principal import Principal, PrincipalKind
    from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
    from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
    from tests.conftest import DEFAULT_LIMITS
    from tests.contract.test_transport_parity import document

    def service(enabled: bool) -> ApplicationService:
        return ApplicationService(
            unit_of_work=lambda: SqlAlchemyUnitOfWork(
                migrated_engine, audit=SqlAlchemyAuditSink(migrated_engine)
            ),
            limits=DEFAULT_LIMITS,
            communications_enabled=enabled,
        )

    def invoke(
        target: ApplicationService, principal_id: str, name: str, payload: dict[str, object]
    ) -> object:
        principal = Principal(principal_id, PrincipalKind.OPERATOR, authenticated=True)
        metadata, command = normalize(name, document(Capability(name), principal_id, payload))
        return target.invoke(metadata, command, principal=principal)

    from my_pa.domain.identity.operation import Capability

    on = service(True)
    searched = invoke(on, P, "communications.search", {"query": "slab pour", "collapse": "none"})
    assert searched.error is None, searched.error  # type: ignore[attr-defined]
    payload = searched.result  # type: ignore[attr-defined]
    assert world["slab"] in {r["message_id"] for r in payload["results"]}
    assert payload["versions"]["identifier_version"] == "comms_identifiers_v2"
    assert payload["coverage"]["snapshot_count"] >= 1
    read = invoke(on, P, "communications.read", {"message_ids": [world["slab"]]})
    assert read.error is None  # type: ignore[attr-defined]
    (message,) = read.result["messages"]  # type: ignore[attr-defined]
    assert message["search_text"].startswith("The slab pour")
    assert message["coverage"]["coverage_state"] == "complete"
    foreign = invoke(on, OTHER, "communications.read", {"message_ids": [world["slab"]]})
    assert foreign.result["not_found"] == [world["slab"]]  # type: ignore[attr-defined]
    covered = invoke(
        on,
        P,
        "communications.coverage",
        {"from_utc": "2026-11-17T00:00:00Z", "to_utc": "2026-11-20T23:59:59Z"},
    )
    assert covered.error is None  # type: ignore[attr-defined]
    assert covered.result["coverage"]["state"] == "partial"  # type: ignore[attr-defined]
    off = invoke(service(False), P, "communications.search", {"query": "slab pour"})
    assert off.error.code.value == "unsupported"  # type: ignore[attr-defined]


def test_a_restricted_profile_composition_serves_no_communications_read(
    cloned_database_url: str, migrated_engine: Engine
) -> None:
    """WP4-R2 G3, on the Schedule T2-25 model: a restricted MCP database role
    holds no privilege on the communications tables.

    The gateway composes the read switch only without an injected
    `data_engine`, so a profile service serves none of the 3 names even with
    the switch on; the full-role control service serves all 3.
    """
    from my_pa.bootstrap.gateway import build_gateway_runtime
    from my_pa.bootstrap.settings import Settings

    names = {"communications.search", "communications.read", "communications.coverage"}
    settings = Settings(database_url=cloned_database_url, communications_enabled=True)
    control = build_gateway_runtime(settings)
    profile = build_gateway_runtime(
        settings,
        data_engine=migrated_engine,
        independent_audit_engine=control.audit_engine,
        controls_engine=control.work_engine,
        permit_reenrichment=False,
        permit_managed_documents=False,
    )
    try:
        assert {c.value for c in control.service.available_capabilities} >= names
        assert not {c.value for c in profile.service.available_capabilities} & names
    finally:
        for engine in {control.work_engine, control.audit_engine}:
            engine.dispose()
