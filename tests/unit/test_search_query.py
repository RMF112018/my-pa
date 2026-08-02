"""The search query, its bounds, its redaction, and its cursor.

No database. Everything here is a claim about a value, and the two that matter
most are claims about what a value *refuses* to say.

The first is redaction. Section 13 keeps query text out of default logs and
section 10 keeps it out of every error, and both are one careless f-string away
from being untrue. So the query is rendered through every route Python offers —
`repr`, `str`, `format`, `%s`, and a containing dataclass — and every error this
module can raise is caught and searched for the value that caused it.

The second is the cursor. It has to survive a round trip exactly, refuse a
request it was not issued for, and carry no query text, and the last of those is
easy to lose by putting the query in the token "just for debugging".

The rank thresholds are checked at their boundaries rather than on example
documents, because a document's score depends on the corpus and the dictionary
while the bucketing function does not.
"""

from __future__ import annotations

import base64
import json
import secrets
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, make_identifier
from my_pa.domain.search.query import (
    CURSOR_TTL_SECONDS,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_QUERY_CHARACTERS,
    MAX_SNIPPET_CHARACTERS,
    MAX_SNIPPET_WORDS,
    MIN_SNIPPET_WORDS,
    MODERATE_RANK_THRESHOLD,
    RESULT_ORDER,
    STRONG_RANK_THRESHOLD,
    EmptySearchQueryError,
    RankCategory,
    SearchCursor,
    SearchCursorError,
    SearchMatch,
    SearchQuery,
    SearchQueryError,
    SearchRequest,
    binding_digest,
    bound_snippet,
    label_for_media_type,
    rank_category,
    validate_result_label,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: A string no rule in this module rejects, used wherever a test needs a query
#: that is legal and distinctive enough to find in a rendered object.
PRIVATE_QUERY = "zephyrine ledger reconciliation"


def identifier(kind: IdKind) -> str:
    return make_identifier(kind, secrets.token_hex(16))


def request(**overrides: object) -> SearchRequest:
    values: dict[str, object] = {
        "enrollment_id": identifier(IdKind.ENROLLMENT),
        "query": SearchQuery(PRIVATE_QUERY),
    }
    values.update(overrides)
    return SearchRequest(**values)  # type: ignore[arg-type]


def test_normalization_makes_two_spellings_one_query() -> None:
    """Canonical equivalence, whitespace, and surrounding space are all folded."""
    decomposed = "café accounts"
    composed = "café accounts"
    assert unicodedata.normalize("NFD", composed) == decomposed
    assert decomposed != composed, "the two spellings are the same string; this proves nothing"

    assert SearchQuery(decomposed).text == SearchQuery(composed).text
    assert SearchQuery(decomposed).fingerprint == SearchQuery(composed).fingerprint
    assert SearchQuery("  quarterly\n\treport  ").text == "quarterly report"
    assert SearchQuery("quarterly\u00a0report").text == "quarterly report"


def test_compatibility_equivalence_is_deliberately_not_folded() -> None:
    """NFC, not NFKC, and the difference is a decision rather than an accident.

    Folding `ﬁ` to `fi` is a matching decision that belongs to PostgreSQL's
    dictionary, where it is visible and changeable. Asserting the current
    behaviour means changing it has to be deliberate.
    """
    assert SearchQuery("ﬁnance").text != SearchQuery("finance").text


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "\n\t ",
    ],
)
def test_a_query_with_no_content_is_empty_rather_than_a_search(value: str) -> None:
    with pytest.raises(EmptySearchQueryError):
        SearchQuery(value)


def test_a_query_longer_than_the_bound_is_refused() -> None:
    assert SearchQuery("a" * MAX_QUERY_CHARACTERS).text == "a" * MAX_QUERY_CHARACTERS
    with pytest.raises(SearchQueryError, match=str(MAX_QUERY_CHARACTERS)):
        SearchQuery("a" * (MAX_QUERY_CHARACTERS + 1))


def test_an_enormous_query_is_refused_before_it_is_normalized() -> None:
    """The bound exists to prevent work, so it is checked before the work."""
    with pytest.raises(SearchQueryError):
        SearchQuery("é" * 10_000_000)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("null byte", "quarterly\x00report"),
        ("bell", "quarterly\x07report"),
        ("bidi override", "quarterly‮report"),
        ("zero width joiner", "quarterly‍report"),
        ("soft hyphen", "quarterly­report"),
        ("surrogate", "quarterly\ud800report"),
        ("private use", "quarterlyreport"),
    ],
)
def test_control_and_formatting_characters_are_refused_not_stripped(name: str, value: str) -> None:
    """Refusing answers the question asked; stripping answers a different one.

    The bidi override and the zero-width joiner are the ones worth naming: both
    make two visually identical queries different strings, which is exactly how
    a spoofed query would be built.
    """
    with pytest.raises(SearchQueryError):
        SearchQuery(value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("next line", "quarterly\x85report"),
        ("vertical tab", "quarterly\x0breport"),
        ("form feed", "quarterly\x0creport"),
        ("record separator", "quarterly\x1ereport"),
    ],
)
def test_a_control_character_that_is_whitespace_is_folded_like_a_newline(
    name: str, value: str
) -> None:
    """The other half of the rule above, and the reason it is not a contradiction.

    U+0085 and the separators are `Cc` *and* `str.isspace()`, so the whitespace
    collapse reaches them before the category check does and they become a
    space. That is deliberate: they are line and field separators, and refusing
    a query because it was pasted with one in it would refuse a legitimate
    paste. Stating it here means the boundary is a decision rather than an
    artefact of the order the two steps happen to run in.
    """
    assert value[9].isspace(), "this character is not whitespace; the test claims the wrong thing"
    assert SearchQuery(value).text == "quarterly report"


def test_a_query_that_is_not_a_string_is_a_typed_error() -> None:
    for value in (None, 12, b"quarterly", ["quarterly"]):
        with pytest.raises(SearchQueryError):
            SearchQuery(value)  # type: ignore[arg-type]


def renderings(value: object) -> list[str]:
    """Every route by which a value can reach a string.

    A redaction that covered `repr` but not `%s` would be a redaction that
    survived review and leaked in the first log line.
    """
    return [repr(value), str(value), f"{value}", format(value), "%s" % (value,)]  # noqa: UP031


def test_a_query_redacts_itself_however_it_is_rendered() -> None:
    query = SearchQuery(PRIVATE_QUERY)
    for rendered in renderings(query):
        assert PRIVATE_QUERY not in rendered
        assert "redacted" in rendered
    # The length is disclosed on purpose: it is a count, not the content.
    assert str(len(PRIVATE_QUERY)) in repr(query)


def test_a_request_holding_a_query_redacts_it_too() -> None:
    """The containing dataclass is where a redaction is usually lost.

    `SearchRequest` has a generated `repr` that renders each field with `repr`,
    so it inherits the query's redaction rather than needing its own — which is
    only true while `SearchQuery.__repr__` is the redacting one.
    """
    for rendered in renderings(request()):
        assert PRIVATE_QUERY not in rendered


@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("too long", lambda: SearchQuery(PRIVATE_QUERY + "x" * MAX_QUERY_CHARACTERS)),
        ("null byte", lambda: SearchQuery(PRIVATE_QUERY + "\x00")),
        ("control", lambda: SearchQuery(PRIVATE_QUERY + "\x07")),
        ("not a string", lambda: SearchQuery(PRIVATE_QUERY.encode())),  # type: ignore[arg-type]
    ],
)
def test_no_error_about_a_query_ever_echoes_the_query(
    name: str, build: Callable[[], SearchQuery]
) -> None:
    """Section 10: an error carries no query text, in the message or the chain."""
    with pytest.raises(SearchQueryError) as raised:
        build()
    rendered = f"{raised.value!r} {raised.value.args} {raised.value.__cause__} "
    rendered += f"{raised.value.__context__}"
    assert PRIVATE_QUERY not in rendered, f"{name} echoed the query"
    assert "zephyrine" not in rendered


def test_the_fingerprint_is_stable_and_distinguishes_queries() -> None:
    assert SearchQuery(PRIVATE_QUERY).fingerprint == SearchQuery(PRIVATE_QUERY).fingerprint
    assert SearchQuery(PRIVATE_QUERY).fingerprint != SearchQuery("something else").fingerprint
    assert len(SearchQuery(PRIVATE_QUERY).fingerprint) == 64
    assert PRIVATE_QUERY not in SearchQuery(PRIVATE_QUERY).fingerprint


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, RankCategory.WEAK),
        (MODERATE_RANK_THRESHOLD - 1e-9, RankCategory.WEAK),
        (MODERATE_RANK_THRESHOLD, RankCategory.MODERATE),
        (STRONG_RANK_THRESHOLD - 1e-9, RankCategory.MODERATE),
        (STRONG_RANK_THRESHOLD, RankCategory.STRONG),
        (1.0, RankCategory.STRONG),
    ],
)
def test_the_rank_boundaries_are_where_they_are_documented(
    score: float, expected: RankCategory
) -> None:
    assert rank_category(score) is expected


def test_the_rank_bucketing_is_monotone() -> None:
    """The only property a caller may rely on, asserted rather than assumed."""
    order = {RankCategory.WEAK: 0, RankCategory.MODERATE: 1, RankCategory.STRONG: 2}
    scores = [index / 200 for index in range(201)]
    categories = [order[rank_category(score)] for score in scores]
    assert categories == sorted(categories)


def test_a_rank_that_is_not_a_score_is_refused() -> None:
    for value in (-0.1, float("nan")):
        with pytest.raises(ValueError, match="rank"):
            rank_category(value)
    for value in (True, "0.5", None):
        with pytest.raises(TypeError):
            rank_category(value)  # type: ignore[arg-type]


def test_a_cursor_round_trips_exactly() -> None:
    """The rank has to survive base64 and JSON unchanged, or the keyset drifts.

    A float that came back even one unit in the last place different would make
    the resumption predicate skip or repeat the row it was taken from.
    """
    original = SearchCursor(
        binding="a" * 64,
        rank=0.28571429848670959,
        knowledge_id=identifier(IdKind.KNOWLEDGE),
        issued_at=NOW,
    )
    restored = SearchCursor.decode(original.encode())
    assert restored == original
    assert restored.rank == original.rank


def test_a_cursor_carries_no_query_text() -> None:
    """Not "the token looks opaque" — it is decoded and inspected.

    A cursor is handed back to callers, logged, and pasted into issues. The
    binding is a digest of the query and never the query, and this is where that
    is checked rather than trusted.
    """
    query = SearchQuery(PRIVATE_QUERY)
    cursor = SearchCursor(
        binding=binding_digest(
            query=query, enrollment_id=identifier(IdKind.ENROLLMENT), page_size=20, snippet_words=30
        ),
        rank=0.5,
        knowledge_id=identifier(IdKind.KNOWLEDGE),
        issued_at=NOW,
    )
    token = cursor.encode()
    decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert PRIVATE_QUERY not in token
    assert PRIVATE_QUERY not in json.dumps(decoded)
    assert set(decoded) == {"b", "k", "r", "t"}


@pytest.mark.parametrize(
    "token",
    [
        "",
        "!!!not base64!!!",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(b'{"b":"x"}').decode(),
        base64.urlsafe_b64encode(b'{"b":"' + b"a" * 64 + b'","k":"kn_x","r":1,"t":1}').decode(),
        base64.urlsafe_b64encode(b'{"b":"short","k":"kn_' + b"a" * 16 + b'","r":1,"t":1}').decode(),
        base64.urlsafe_b64encode(
            b'{"b":"' + b"a" * 64 + b'","k":"kn_' + b"a" * 16 + b'","r":-1,"t":1}'
        ).decode(),
        "x" * 600,
    ],
)
def test_an_unreadable_or_malformed_cursor_is_one_typed_error(token: str) -> None:
    """One message for every failure, so a rejected cursor teaches nothing."""
    with pytest.raises(SearchCursorError) as raised:
        SearchCursor.decode(token)
    assert str(raised.value) == "the cursor is not readable"
    assert raised.value.__context__ is None


def test_a_cursor_binding_covers_every_input_that_changes_a_page() -> None:
    query = SearchQuery(PRIVATE_QUERY)
    enrollment = identifier(IdKind.ENROLLMENT)
    base = binding_digest(query=query, enrollment_id=enrollment, page_size=20, snippet_words=30)
    variants = [
        binding_digest(
            query=SearchQuery("different"),
            enrollment_id=enrollment,
            page_size=20,
            snippet_words=30,
        ),
        binding_digest(
            query=query,
            enrollment_id=identifier(IdKind.ENROLLMENT),
            page_size=20,
            snippet_words=30,
        ),
        binding_digest(query=query, enrollment_id=enrollment, page_size=21, snippet_words=30),
        binding_digest(query=query, enrollment_id=enrollment, page_size=20, snippet_words=31),
    ]
    assert len(set(variants)) == len(variants)
    assert base not in variants


def test_the_cursor_binds_exactly_these_inputs() -> None:
    """Pin the binding, because section 8.5 lists more than this layer can bind.

    Principal, purpose, and policy version are on section 8.5's list and are not
    part of a search request here, so they are not bound. Recomputing the digest
    from a literal canonical form means the transport work package that
    introduces them has to change this test deliberately rather than forget the
    binding entirely.
    """
    import hashlib

    query = SearchQuery(PRIVATE_QUERY)
    enrollment = identifier(IdKind.ENROLLMENT)
    canonical = json.dumps(
        {
            "enrollment_id": enrollment,
            "order": RESULT_ORDER,
            "page_size": 20,
            "query": query.fingerprint,
            "snippet_words": 30,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    assert (
        binding_digest(query=query, enrollment_id=enrollment, page_size=20, snippet_words=30)
        == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )


def test_a_cursor_expires() -> None:
    cursor = SearchCursor(
        binding="a" * 64, rank=0.5, knowledge_id=identifier(IdKind.KNOWLEDGE), issued_at=NOW
    )
    assert not cursor.is_expired(NOW)
    assert not cursor.is_expired(NOW + timedelta(seconds=CURSOR_TTL_SECONDS))
    assert cursor.is_expired(NOW + timedelta(seconds=CURSOR_TTL_SECONDS + 1))


def test_a_request_resumes_only_from_its_own_cursor() -> None:
    first = request(page_size=10)
    cursor = SearchCursor(
        binding=first.binding,
        rank=0.5,
        knowledge_id=identifier(IdKind.KNOWLEDGE),
        issued_at=NOW,
    ).encode()

    resumed = request(enrollment_id=first.enrollment_id, page_size=10, cursor=cursor)
    position = resumed.position(NOW)
    assert position is not None
    assert position.rank == 0.5

    # Same cursor, a page size the caller changed underneath it.
    with pytest.raises(SearchCursorError):
        request(enrollment_id=first.enrollment_id, page_size=11, cursor=cursor).position(NOW)
    # Same cursor, a different query.
    with pytest.raises(SearchCursorError):
        request(
            enrollment_id=first.enrollment_id,
            page_size=10,
            cursor=cursor,
            query=SearchQuery("a different question entirely"),
        ).position(NOW)
    # Same cursor, too late.
    with pytest.raises(SearchCursorError):
        resumed.position(NOW + timedelta(seconds=CURSOR_TTL_SECONDS + 1))


def test_a_request_without_a_cursor_starts_at_the_beginning() -> None:
    assert request().position(NOW) is None


@pytest.mark.parametrize("page_size", [0, -1, MAX_PAGE_SIZE + 1, True, 1.5, "20"])
def test_a_page_size_outside_the_bounds_is_refused(page_size: object) -> None:
    with pytest.raises(SearchQueryError, match="page_size"):
        request(page_size=page_size)


@pytest.mark.parametrize("words", [MIN_SNIPPET_WORDS - 1, MAX_SNIPPET_WORDS + 1, 0, -5, True, "30"])
def test_a_snippet_width_outside_the_bounds_is_refused(words: object) -> None:
    with pytest.raises(SearchQueryError, match="snippet_words"):
        request(snippet_words=words)


def test_the_default_page_size_is_inside_its_own_bound() -> None:
    assert 1 <= DEFAULT_PAGE_SIZE <= MAX_PAGE_SIZE
    assert request().page_size == DEFAULT_PAGE_SIZE


def test_a_request_names_an_enrollment() -> None:
    with pytest.raises(InvalidIdentifierError):
        request(enrollment_id=identifier(IdKind.SOURCE))
    with pytest.raises(SearchQueryError):
        request(query=PRIVATE_QUERY)


def test_a_snippet_is_bounded_and_stripped_of_control_characters() -> None:
    short, cut = bound_snippet("a quiet paragraph")
    assert (short, cut) == ("a quiet paragraph", False)

    long_value = "word " * 200
    bounded, cut = bound_snippet(long_value)
    assert cut is True
    assert len(bounded) <= MAX_SNIPPET_CHARACTERS

    cleaned, _ = bound_snippet("before\x1b[31mafter\x00‮ end")
    assert "\x1b" not in cleaned
    assert "\x00" not in cleaned
    assert "‮" not in cleaned
    assert cleaned == "before[31mafter end"


@pytest.mark.parametrize(
    "label",
    ["", "/etc/passwd", "..\\windows", "a@b.com", "host:port", "x" * 129, "\x07bell"],
)
def test_a_label_that_could_be_a_path_or_an_address_is_refused(label: str) -> None:
    with pytest.raises(SearchQueryError):
        validate_result_label(label)


@pytest.mark.parametrize("label", ["Markdown document", "notes.md", "Q3_summary", "a"])
def test_a_safe_label_is_permitted(label: str) -> None:
    """The paired positive: a rule that refused everything would pass the above."""
    assert validate_result_label(label) == label


def test_a_label_is_derived_from_the_media_type_and_nothing_else() -> None:
    assert label_for_media_type("text/markdown") == "Markdown document"
    assert label_for_media_type("text/plain") == "Plain text document"
    assert label_for_media_type(None) == "Extracted document"
    assert label_for_media_type("application/pdf") == "Extracted document"


def match(**overrides: object) -> SearchMatch:
    values: dict[str, object] = {
        "knowledge_id": identifier(IdKind.KNOWLEDGE),
        "label": "Markdown document",
        "snippet": "a bounded window into the document",
        "rank": RankCategory.MODERATE,
        "source_id": identifier(IdKind.SOURCE),
        "source_object_id": identifier(IdKind.SOURCE_OBJECT),
        "version_id": identifier(IdKind.VERSION),
    }
    values.update(overrides)
    return SearchMatch(**values)  # type: ignore[arg-type]


def test_a_match_binds_the_version_it_came_from() -> None:
    built = match()
    assert built.version_id.startswith("ver_")
    assert built.source_object_id.startswith("obj_")
    assert built.knowledge_id.startswith("kn_")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("knowledge_id", "obj_" + "a" * 16),
        ("source_id", "kn_" + "a" * 16),
        ("source_object_id", "src_" + "a" * 16),
        ("version_id", "obj_" + "a" * 16),
    ],
)
def test_a_match_refuses_an_identifier_of_the_wrong_kind(field: str, value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        match(**{field: value})


def test_a_match_refuses_an_oversized_snippet_and_an_unsafe_label() -> None:
    with pytest.raises(SearchQueryError):
        match(snippet="x" * (MAX_SNIPPET_CHARACTERS + 1))
    with pytest.raises(SearchQueryError):
        match(label="/var/personal/notes")
