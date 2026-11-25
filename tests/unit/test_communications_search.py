"""WP4-S4: `application.communications_search` and its pure parts, FAST tier.

The search statement is the database tier's (`tests/database/test_communications_search.py`);
here the fakes can its answers, so what is proved is the service around it:
request normalization and every section 16 bound; one identifier per
`identifiers[]` item (R11) and the identifiers merged from the non-negated
query (R6); the quoted-phrase parse; the D4-final trigger (fallback exactly
when `english` keeps fewer nodes than `simple`) and `no_searchable_terms`; the
cursor codec (malformed, binding, scope) for search and the thread view; a
withheld body's snippet and text never returned; the read's id rules and text
bounds; the coverage read's bounds. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.communications_search import (
    MAX_ANSWER_TEXT_CHARACTERS,
    MAX_MESSAGE_TEXT_CHARACTERS,
    CommunicationsReads,
    CoverageRequest,
    ReadRequest,
    SearchRequest,
)
from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import (
    CommunicationMessageRecord,
    CommunicationSearchQueryShape,
    CommunicationSearchRow,
)
from my_pa.domain.communications.cursor import (
    MAX_CURSOR_CHARACTERS,
    CommunicationsCursor,
    CursorMalformedError,
    SearchPosition,
    ThreadPosition,
    decode_cursor,
    encode_cursor,
    grant_digest,
    scope_digest,
    search_position,
    thread_position,
)
from my_pa.domain.communications.search_query import (
    negated_text,
    quoted_phrases,
    unnegated_text,
)
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.communications_ingest_fakes import IngestWorld, unit_of_work_factory
from tests.unit.test_communications_ingest import P, Scene, at, pub

NOW: Final = datetime(2026, 11, 21, 12, tzinfo=UTC)
WHEN: Final = datetime(2026, 11, 17, 12, tzinfo=UTC)
GRANTS: Final = (("communications.search", "communications_read"),)


def service(world: IngestWorld, **kwargs: str) -> CommunicationsReads:
    return CommunicationsReads(
        unit_of_work=unit_of_work_factory(world), clock=lambda: NOW, **kwargs
    )


def row(n: int, **overrides: object) -> CommunicationSearchRow:
    values: dict[str, object] = {
        "message_id": f"cmsg_fast{n:06d}",
        "conversation_id": None,
        "message_time": WHEN - timedelta(minutes=n),
        "subject": f"Synthetic {n}",
        "sender_address": "alpha@example.invalid",
        "has_attachments": False,
        "body_state": "present",
        "search_text_version": "comms_search_text_v2",
        "search_text_flags": (),
        "identity_conflict": False,
        "participants_reconciled": False,
        "participants_disagreed": False,
        "source_unavailable": False,
        "tier": 3,
        "rank": 0,
        "overlap": 0,
        "matched_identifier_kinds": (),
        "conversation_hits": 1,
        "snippet": f"text {n}",
    }
    values.update(overrides)
    return CommunicationSearchRow(**values)  # type: ignore[arg-type]


@pytest.fixture
def world() -> IngestWorld:
    return IngestWorld()


def _refused(call: Callable[[], object]) -> tuple[type[Exception], tuple[SafeDetail, ...]]:
    with pytest.raises((InvalidRequestError, ConflictError, NotFoundError)) as raised:
        call()
    return type(raised.value), raised.value.safe_details  # type: ignore[union-attr]


# ---- normalization and bounds ------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"query": "x" * 513}, SafeDetail.QUERY),
        ({"query": 5}, SafeDetail.QUERY),
        ({"identifiers": [f"RFI {n}" for n in range(21)]}, SafeDetail.IDENTIFIERS),
        ({"identifiers": "RFI 5"}, SafeDetail.IDENTIFIERS),
        ({"identifiers": ["174"]}, SafeDetail.IDENTIFIERS),  # R11: zero
        ({"identifiers": ["RFI 1 and RFI 2"]}, SafeDetail.IDENTIFIERS),  # R11: several
        ({"identifiers": ["pco:12x"]}, SafeDetail.IDENTIFIERS),
        (
            {
                "identifiers": [f"RFI {n}" for n in range(15)],
                "query": " ".join(f"CB {n}" for n in range(6)),
            },
            SafeDetail.IDENTIFIERS,
        ),  # 15 requested + 6 found in the query > 20
        ({"participants": [f"p{n}@example.invalid" for n in range(21)]}, SafeDetail.PARTICIPANTS),
        ({"participants": ["not an address"]}, SafeDetail.PARTICIPANTS),
        ({"participant_mode": "some"}, SafeDetail.PARTICIPANT_MODE),
        ({"from_utc": datetime(2026, 11, 17)}, SafeDetail.FROM_UTC),  # naive
        ({"to_utc": WHEN.replace(microsecond=5)}, SafeDetail.TO_UTC),  # not whole seconds
        ({"from_utc": WHEN, "to_utc": WHEN - timedelta(seconds=1)}, SafeDetail.TO_UTC),
        ({"folder_role": "archive"}, SafeDetail.FOLDER_ROLE),
        ({"conversation_id": ""}, SafeDetail.CONVERSATION_ID),
        ({"conversation_id": "c" * 2049}, SafeDetail.CONVERSATION_ID),
        ({"collapse": "thread"}, SafeDetail.COLLAPSE),
        ({"limit": 0}, SafeDetail.LIMIT),
        ({"limit": 51}, SafeDetail.LIMIT),
        ({"limit": True}, SafeDetail.LIMIT),
        ({"cursor": "not a cursor!"}, SafeDetail.CURSOR),
    ],
)
def test_a_request_outside_its_bounds_is_refused_with_its_field(
    world: IngestWorld, fields: dict[str, object], detail: SafeDetail
) -> None:
    request = SearchRequest(**fields)  # type: ignore[arg-type]
    assert _refused(lambda: service(world).search(P, request)) == (InvalidRequestError, (detail,))
    assert world.search_calls == []


def test_the_bounds_themselves_are_admitted(world: IngestWorld) -> None:
    request = SearchRequest(
        query="x" * 512,
        identifiers=[f"RFI {n}" for n in range(20)],
        participants=[f"P{n}@Example.invalid " for n in range(20)],
        participant_mode="all",
        from_utc=WHEN,
        to_utc=WHEN,
        folder_role="sent",
        limit=50,
    )
    service(world).search(P, request)
    (query,) = world.search_calls
    assert len(query.identifiers) == 20
    assert query.participants[0] == "p0@example.invalid"  # lower-cased and trimmed
    assert query.participants_all is True
    assert query.limit == 51  # one more, to know whether a next page exists


def test_identifiers_from_the_query_are_merged_deduplicated_and_negation_excluded(
    world: IngestWorld,
) -> None:
    answer = service(world).search(
        P,
        SearchRequest(
            query='RFI 174 and "Change Order 5" -PCO-3 -"COR 9"', identifiers=["rfi:174"]
        ),
    )
    assert answer.identifiers == ("co:5", "rfi:174")
    (query,) = world.search_calls
    assert query.identifiers == (("co", "5"), ("rfi", "174"))


def test_a_conversation_filter_turns_collapse_off(world: IngestWorld) -> None:
    service(world).search(P, SearchRequest(conversation_id="conv-1"))
    service(world).search(P, SearchRequest())
    assert [q.collapse for q in world.search_calls] == [False, True]


# ---- the quoted-phrase parse -------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "phrases", "unnegated"),
    [
        ('"change orders" deck', ("change orders",), "change orders deck"),
        ('a -"b c" "d  e', ("d e",), "a d  e"),
        ('"x" "" y "x"', ("x",), "x y x"),
        ("-word kept", (), "kept"),
        ('pre-cast "slab"', ("slab",), "pre-cast slab"),
        ('a-"b c"', ("b c",), "a- b c"),
    ],
)
def test_the_quoted_phrase_parse(query: str, phrases: tuple[str, ...], unnegated: str) -> None:
    assert quoted_phrases(query) == phrases
    assert unnegated_text(query) == unnegated


@pytest.mark.parametrize(
    ("query", "negated"),
    [
        ("RFI 5 -pricing", "-pricing"),
        ('a -"b c" -d "e"', '-"b c" -d'),
        ('-"open phrase', '-"open phrase"'),
        ('pre-cast a-"b c" -""', ""),
        ("nothing negated", ""),
    ],
)
def test_the_negated_terms_are_kept_negated(query: str, negated: str) -> None:
    """WP4-R2 G4: the exclusion every candidate must satisfy, in websearch syntax."""
    assert negated_text(query) == negated


def test_the_negated_terms_reach_the_statement(world: IngestWorld) -> None:
    service(world).search(P, SearchRequest(query='RFI 5 -pricing -"change order"'))
    service(world).search(P, SearchRequest(query="RFI 5"))
    service(world).search(P, SearchRequest())
    assert [q.excluded for q in world.search_calls] == ['-pricing -"change order"', None, None]


# ---- the stop-word fallback trigger (D4-final) and query states --------------------------


@pytest.mark.parametrize(
    ("english", "simple", "fallback", "state"),
    [
        (1, 1, None, None),
        (3, 3, None, None),
        (0, 1, "simple_stopwords", None),  # a stop-word name alone
        (1, 3, "simple_stopwords", None),  # "Will Smith"
        (0, 0, None, "no_searchable_terms"),
    ],
)
def test_the_fallback_is_flagged_exactly_when_english_drops_a_lexeme(
    world: IngestWorld, english: int, simple: int, fallback: str | None, state: str | None
) -> None:
    world.query_shape = CommunicationSearchQueryShape(english_nodes=english, simple_nodes=simple)
    answer = service(world).search(P, SearchRequest(query="synthetic"))
    assert (answer.text_fallback, answer.query_state) == (fallback, state)
    (query,) = world.search_calls
    assert query.text_fallback is (fallback is not None)
    assert query.english_terms is (english > 0)
    assert (query.query is None) is (state is not None)


def test_no_query_asks_no_shape_and_browses(world: IngestWorld) -> None:
    answer = service(world).search(P, SearchRequest())
    assert world.search_queries == []
    assert (answer.query_state, answer.text_fallback) == (None, None)
    assert world.search_calls[0].query is None


# ---- the cursor codec ---------------------------------------------------------------------


def test_the_cursor_round_trips_and_is_bounded() -> None:
    position = SearchPosition(2, 123, 1, WHEN, "cmsg_fast000001")
    cursor = CommunicationsCursor("a" * 64, "b" * 64, position)
    token = encode_cursor(cursor)
    assert len(token) <= MAX_CURSOR_CHARACTERS
    assert decode_cursor(token, search_position) == cursor
    thread = CommunicationsCursor("a" * 64, "b" * 64, ThreadPosition(WHEN, "cmsg_fast000001"))
    assert decode_cursor(encode_cursor(thread), thread_position) == thread
    with pytest.raises(CursorMalformedError):  # a thread token is not a search position
        decode_cursor(encode_cursor(thread), search_position)


@pytest.mark.parametrize(
    "token",
    ["", "!!", "e30", "x" * (MAX_CURSOR_CHARACTERS + 1), 5, None],
)
def test_a_malformed_token_is_refused(token: object) -> None:
    with pytest.raises(CursorMalformedError):
        decode_cursor(token, search_position)


def test_the_scope_digest_covers_only_the_communications_grants() -> None:
    base = grant_digest(GRANTS)
    assert grant_digest([*GRANTS, ("records.lineage", None)]) == base
    assert grant_digest([*GRANTS, ("communications.read", None)]) != base
    assert grant_digest(None) is None
    assert scope_digest(base) != scope_digest(None)


def test_search_pages_bind_to_the_request_principal_and_grants(world: IngestWorld) -> None:
    world.search_rows = [row(n) for n in range(5)]
    reads = service(world)
    first = reads.search(P, SearchRequest(limit=2), grants=GRANTS)
    assert [r.message_id for r in first.results] == ["cmsg_fast000000", "cmsg_fast000001"]
    assert first.next_cursor is not None
    reads.search(P, SearchRequest(limit=2, cursor=first.next_cursor), grants=GRANTS)
    assert world.search_calls[-1].after == (3, 0, 0, WHEN - timedelta(minutes=1), "cmsg_fast000001")
    for other in (
        lambda: reads.search(P, SearchRequest(limit=2, query="x", cursor=first.next_cursor)),
        lambda: reads.search(P, SearchRequest(limit=2, collapse="none", cursor=first.next_cursor)),
        lambda: reads.search(
            "prn_someoneelse0001", SearchRequest(limit=2, cursor=first.next_cursor)
        ),
    ):
        assert _refused(other) == (ConflictError, (SafeDetail.CURSOR,))
    calls = len(world.search_calls)
    changed = reads.search(P, SearchRequest(limit=2, cursor=first.next_cursor), grants=())
    assert (changed.cursor_state, changed.results, changed.next_cursor) == (
        "scope_changed_restart_required",
        (),
        None,
    )
    assert len(world.search_calls) == calls  # nothing beyond the restart
    # A different limit continues the same request.
    reads.search(P, SearchRequest(limit=3, cursor=first.next_cursor), grants=GRANTS)


def test_the_identifier_read_version_is_bound_into_the_cursor(world: IngestWorld) -> None:
    world.search_rows = [row(n) for n in range(3)]
    token = service(world).search(P, SearchRequest(limit=1)).next_cursor
    v1 = service(world, identifier_version="comms_identifiers_v1")
    assert _refused(lambda: v1.search(P, SearchRequest(limit=1, cursor=token))) == (
        ConflictError,
        (SafeDetail.CURSOR,),
    )


def test_the_last_page_has_no_cursor(world: IngestWorld) -> None:
    world.search_rows = [row(n) for n in range(2)]
    assert service(world).search(P, SearchRequest(limit=2)).next_cursor is None


# ---- withheld bodies ----------------------------------------------------------------------


@pytest.mark.parametrize("state", ["withheld", "truncated"])
def test_a_withheld_or_truncated_body_never_yields_a_snippet(
    world: IngestWorld, state: str
) -> None:
    """Even a row that (impossibly) carried text for such a body returns none."""
    world.search_rows = [row(1, body_state=state, snippet="leaked words")]
    (result,) = service(world).search(P, SearchRequest()).results
    assert result.snippet is None


def test_a_snippet_is_at_most_300_characters(world: IngestWorld) -> None:
    world.search_rows = [row(1, snippet="y" * 400)]
    (result,) = service(world).search(P, SearchRequest()).results
    assert result.snippet == "y" * 300


# ---- read ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_", "detail"),
    [
        (ReadRequest(), SafeDetail.MESSAGE_IDS),
        (
            ReadRequest(message_ids=["cmsg_fast000001"], conversation_id="c"),
            SafeDetail.CONVERSATION_ID,
        ),
        (ReadRequest(message_ids=[f"cmsg_fast{n:06d}" for n in range(26)]), SafeDetail.MESSAGE_IDS),
        (ReadRequest(message_ids=["not-an-id"]), SafeDetail.MESSAGE_IDS),
        (ReadRequest(message_ids=["isrc_fast00000001"]), SafeDetail.MESSAGE_IDS),
        (ReadRequest(message_ids="cmsg_fast000001"), SafeDetail.MESSAGE_IDS),
        (ReadRequest(message_ids=["cmsg_fast000001"], cursor="x"), SafeDetail.CURSOR),
        (ReadRequest(message_ids=["cmsg_fast000001"], include_text=1), SafeDetail.INCLUDE_TEXT),  # type: ignore[arg-type]
        (ReadRequest(conversation_id="c", cursor="!!"), SafeDetail.CURSOR),
    ],
)
def test_a_read_outside_its_bounds_is_refused(
    world: IngestWorld, request_: ReadRequest, detail: SafeDetail
) -> None:
    assert _refused(lambda: service(world).read(P, request_)) == (InvalidRequestError, (detail,))


def _ingested(texts: list[str], *, conversation: str | None = None) -> tuple[Scene, list[str]]:
    scene = Scene()
    messages = [
        s.message(
            n + 1, selected=at(17, 8 + n % 10), subject=f"Synthetic {n}", content=f"<p>{t}</p>"
        )
        for n, t in enumerate(texts)
    ]
    scene.ingest("20261117-comms.json", pub(17, messages))
    if conversation is not None:
        for key, message in list(scene.world.messages.items()):
            scene.world.messages[key] = replace(message, conversation_id=conversation)
    ordered = sorted(scene.world.messages.values(), key=lambda m: m.subject or "")
    return scene, [m.message_id for m in ordered]


def test_a_read_keeps_request_order_and_reports_not_found(world: IngestWorld) -> None:
    scene, ids = _ingested(["first RFI 12", "second"])
    answer = service(scene.world).read(
        P, ReadRequest(message_ids=[ids[1], "cmsg_notthere0001", ids[0], ids[1]])
    )
    assert [m.message_id for m in answer.messages] == [ids[1], ids[0]]
    assert answer.not_found == ("cmsg_notthere0001",)
    first = answer.messages[1]
    assert first.search_text == "first RFI 12"
    assert first.identifiers == ("rfi:12",)
    assert first.coverage.coverage_state == "complete"
    assert answer.identifier_version == "comms_identifiers_v2"


def _with_text(scene: Scene, message_id: str, text: str, **projection: object) -> None:
    key = (P, message_id)
    message: CommunicationMessageRecord = scene.world.messages[key]
    scene.world.messages[key] = replace(
        message, projection=replace(message.projection, search_text=text, **projection)
    )


def test_read_text_is_cut_per_message_and_capped_per_answer() -> None:
    scene, ids = _ingested([f"m{n}" for n in range(12)])
    for message_id in ids:
        _with_text(scene, message_id, "z" * (MAX_MESSAGE_TEXT_CHARACTERS + 5))
    answer = service(scene.world).read(P, ReadRequest(message_ids=ids))
    full = MAX_ANSWER_TEXT_CHARACTERS // MAX_MESSAGE_TEXT_CHARACTERS
    for index, message in enumerate(answer.messages):
        if index < full:
            assert message.search_text is not None
            assert len(message.search_text) == MAX_MESSAGE_TEXT_CHARACTERS
            assert (message.truncated, message.text_omitted) == (True, None)
        else:
            assert (message.search_text, message.text_omitted) == (None, "answer_cap")
    assert sum(len(m.search_text or "") for m in answer.messages) == MAX_ANSWER_TEXT_CHARACTERS
    quiet = service(scene.world).read(P, ReadRequest(message_ids=ids[:1], include_text=False))
    assert (quiet.messages[0].search_text, quiet.messages[0].text_omitted) == (
        None,
        "not_requested",
    )


@pytest.mark.parametrize("state", ["withheld", "truncated"])
def test_a_read_never_returns_text_for_a_withheld_or_truncated_body(state: str) -> None:
    """Even a record that (impossibly) carried text for such a body returns none."""
    scene, ids = _ingested(["secret words"])
    _with_text(scene, ids[0], "secret words", body_state=state)
    (message,) = service(scene.world).read(P, ReadRequest(message_ids=ids)).messages
    assert (message.search_text, message.text_omitted, message.body_state) == (
        None,
        "no_text",
        state,
    )


def test_the_thread_view_pages_and_binds_its_cursor() -> None:
    scene, _ = _ingested([f"note {n}" for n in range(27)], conversation="conv-t")
    reads = service(scene.world)
    first = reads.read(P, ReadRequest(conversation_id="conv-t"), grants=GRANTS)
    assert len(first.messages) == 25
    times = [(m.message_time, m.message_id) for m in first.messages]
    assert times == sorted(times)
    second = reads.read(
        P, ReadRequest(conversation_id="conv-t", cursor=first.next_cursor), grants=GRANTS
    )
    assert len(second.messages) == 2 and second.next_cursor is None
    assert _refused(
        lambda: reads.read(P, ReadRequest(conversation_id="conv-u", cursor=first.next_cursor))
    ) == (ConflictError, (SafeDetail.CURSOR,))
    changed = reads.read(
        P, ReadRequest(conversation_id="conv-t", cursor=first.next_cursor), grants=()
    )
    assert (changed.cursor_state, changed.messages) == ("scope_changed_restart_required", ())


# ---- coverage -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_", "detail"),
    [
        (CoverageRequest(from_utc=WHEN, to_utc=WHEN - timedelta(seconds=1)), SafeDetail.TO_UTC),
        (
            CoverageRequest(from_utc=WHEN, to_utc=WHEN + timedelta(days=366, seconds=1)),
            SafeDetail.TO_UTC,
        ),
        (CoverageRequest(from_utc=datetime(2026, 11, 1), to_utc=WHEN), SafeDetail.FROM_UTC),
        (CoverageRequest(from_utc=WHEN, to_utc=WHEN, source="cmsg_fast000001"), SafeDetail.SOURCE),
    ],
)
def test_a_coverage_request_outside_its_bounds_is_refused(
    world: IngestWorld, request_: CoverageRequest, detail: SafeDetail
) -> None:
    assert _refused(lambda: service(world).coverage(P, request_)) == (
        InvalidRequestError,
        (detail,),
    )


def test_coverage_of_an_unknown_source_is_not_found_and_366_days_is_admitted() -> None:
    scene, _ = _ingested(["x"])
    reads = service(scene.world)
    assert _refused(
        lambda: reads.coverage(P, CoverageRequest(WHEN, WHEN, source="isrc_notthere0001"))
    ) == (NotFoundError, (SafeDetail.SOURCE,))
    answer = reads.coverage(
        P, CoverageRequest(WHEN - timedelta(days=366), WHEN, source=scene.source_id)
    )
    assert answer.coverage.state == "partial"
    assert answer.coverage.snapshot_count == 1
