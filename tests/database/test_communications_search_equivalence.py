"""WP5-R4 R4-1 (the operator's direction on WP5-R1 F-1): `ded76e225` is result-equivalent.

`ded76e225` stopped re-evaluating the text criterion where it cannot change the
answer. The `database` tier, run on the C and the en_US.UTF-8 clusters alike,
proves the rewrite against the verbatim statement it replaced
(`tests/database/communications_search_reference.py`):

* every request -- 33 queries (phrases, negations, stop words, identifiers in
  the query) crossed with 7 field sets, 3 limits and both collapse modes, so
  ids plus text, text only, ids only and browse are all exercised -- answers
  the same `SearchAnswer` through `CommunicationsReads.search`, page by page to
  the end of its cursor;
* both statements return the same raw rows, `text_hit` included.

The world is the WP4 search world plus planted cases: an identifier-only match
whose text the query does not match; an identifier match whose `english`
phrase matches across the subject/text boundary but fails the per-field
`strpos` confirmation (the one case the moved rank guard decides); exact ties;
a stop-word-only message; a second conversation member; and long texts whose
headline differs from their plain prefix.

Direct assertions pin each line `ded76e225` changed: a text-only hit gets its
`ts_headline` snippet; an identifier-only row with text present gets the plain
prefix under ids plus text; and the cross-field phrase row gets rank 0.
Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import pytest
from sqlalchemy import Engine

import my_pa.infrastructure.persistence.communications as communications
from my_pa.application.communications_search import SearchAnswer, SearchResult
from my_pa.contracts.ports import CommunicationSearchQuery
from tests.database.communications_search_reference import reference_search_statement
from tests.database.communications_search_world import P, World, at
from tests.database.test_communications_search import A, B, C, search, world

pytestmark = pytest.mark.database

__all__ = ["world"]  # the WP4 search world fixture, re-used here

#: A word that appears only past the first 300 characters of `LONG_HIT`.
NEEDLE: Final = "zephyrine"
_FILLER: Final = " ".join(f"concrete{n:02d} formwork{n:02d} rebar{n:02d}" for n in range(24))
LONG_HIT: Final = f"{_FILLER} the {NEEDLE} batch arrives Thursday {_FILLER}"
LONG_ID_ONLY: Final = f"RFI 5 noted. {_FILLER}"

QUERIES: Final = (
    "slab pour",
    "RFI 5",
    "RFI 174",
    "RFI 17",
    "rfi 5 pricing",
    "pricing",
    "RFI 5 -attached",
    'RFI 5 -"pricing attached"',
    "RFI 5 -pricing",
    "RFI 5 -the",
    "tie breaker",
    "the",
    "will",
    '"slab pour"',
    '"pour schedule"',
    "PCO 3",
    "PCO 3 RFI 5",
    "orders",
    "ordering",
    "change orders",
    "-slab",
    "slab -RFI",
    "deck -orders",
    "privileged",
    "RFI 5 privileged",
    "nomatch",
    '"slab pour" RFI 5',
    '"big slab pour"',
    "RFI 999",
    "RFI 999 slab",
    "Tie case",
    "RFI 17 slab",
    NEEDLE,
)
FIELD_SETS: Final[tuple[dict[str, object], ...]] = (
    {},
    {"identifiers": ["RFI 5"]},
    {"identifiers": ["RFI 174", "RFI 17"]},
    {"identifiers": ["PCO 3", "RFI 5"]},
    {"participants": [A, B], "participant_mode": "all"},
    {"participants": [C]},
    {"folder_role": "sent"},
)


class _SameSource(World):
    """More messages under the standard world's source (no second source row)."""

    def __post_init__(self) -> None:
        self.source_id = "isrc_srchasource"


def _plant(engine: Engine) -> dict[str, str]:
    w = _SameSource(engine, tag="q")
    return {
        # An identifier-only match whose text the query does not match.
        "id_only": w.message(
            1,
            subject="Unrelated",
            text="Concrete curing RFI 5 noted.",
            when=at(18, 14),
            conversation="conv-q1",
        ),
        "slab_member": w.message(
            2,
            subject="Slab",
            text="slab slab slab RFI 5",
            when=at(18, 15),
            conversation="conv-slab",
        ),
        "tie_c": w.message(
            3, subject="Tie case", text="tie breaker text", when=at(20, 11), conversation="conv-q3"
        ),
        "tie_d": w.message(4, subject="Tie case", text="tie breaker text RFI 5", when=at(20, 11)),
        "stop_words": w.message(5, subject="the", text="the the the", when=at(17, 11)),
        "pricing_member": w.message(
            6,
            subject="Pricing",
            text="pricing pricing RFI 174 attached",
            when=at(18, 9),
            conversation="conv-pricing",
        ),
        # The `english` phrase "slab pour" spans subject|text in the stored
        # document (FTS matches), but neither field holds it alone (strpos fails).
        "cross_field": w.message(
            7,
            subject="Big slab",
            text="pour on Monday RFI 5",
            when=at(18, 16),
            conversation="conv-q7",
        ),
        "cross_field_no_id": w.message(
            8, subject="Big slab", text="pour on Monday", when=at(18, 17), conversation="conv-q8"
        ),
        "long_hit": w.message(9, subject="Batch", text=LONG_HIT, when=at(17, 14)),
        "long_id_only": w.message(10, subject="Curing", text=LONG_ID_ONLY, when=at(17, 15)),
    }


def _shape(query: CommunicationSearchQuery) -> str:
    if query.identifiers and query.query is not None:
        return "ids+text"
    if query.identifiers:
        return "ids"
    if query.query is not None:
        return "text"
    return "browse"


def _with_statement(
    monkeypatch: pytest.MonkeyPatch,
    statement: Callable[[str, CommunicationSearchQuery], Any],
    engine: Engine,
    **fields: object,
) -> SearchAnswer:
    monkeypatch.setattr(communications, "_search_statement", statement)
    return search(engine, **fields)


@pytest.mark.parametrize("collapse", ["none", "conversation"])
def test_the_search_statement_answers_exactly_what_the_reference_answers(
    migrated_engine: Engine,
    world: dict[str, str],
    collapse: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant(migrated_engine)
    current = communications._search_statement
    queries: list[CommunicationSearchQuery] = []

    def capturing(principal_id: str, query: CommunicationSearchQuery) -> Any:  # noqa: ANN401
        queries.append(query)
        return current(principal_id, query)

    shapes = dict.fromkeys(("ids+text", "ids", "text", "browse"), 0)
    rows_compared = 0
    pages_walked = 0
    for text in (None, *QUERIES):
        for fields in FIELD_SETS:
            for limit in (1, 3, 50):
                asked: dict[str, object] = dict(fields, collapse=collapse, limit=limit)
                if text is not None:
                    asked["query"] = text
                queries.clear()
                new = _with_statement(monkeypatch, capturing, migrated_engine, **asked)
                old = _with_statement(
                    monkeypatch, reference_search_statement, migrated_engine, **asked
                )
                assert repr(new) == repr(old), (text, fields, limit)
                (query,) = queries
                shapes[_shape(query)] += 1
                # The raw rows, `text_hit` included, statement against statement.
                with migrated_engine.connect() as connection:
                    current_rows = [tuple(r) for r in connection.execute(current(P, query))]
                    reference_rows = [
                        tuple(r) for r in connection.execute(reference_search_statement(P, query))
                    ]
                assert current_rows == reference_rows, (text, fields, limit)
                rows_compared += len(current_rows)
                # Every later page, to the end of the cursor.
                cursor = new.next_cursor
                while cursor is not None:
                    paged = dict(asked, cursor=cursor)
                    new_page = _with_statement(monkeypatch, current, migrated_engine, **paged)
                    old_page = _with_statement(
                        monkeypatch, reference_search_statement, migrated_engine, **paged
                    )
                    assert repr(new_page) == repr(old_page), (text, fields, limit, cursor)
                    cursor = new_page.next_cursor
                    pages_walked += 1
    assert all(count > 0 for count in shapes.values()), shapes
    assert rows_compared > 0
    assert pages_walked > 0


def _result(answer: SearchAnswer, message_id: str) -> SearchResult:
    (result,) = (r for r in answer.results if r.message_id == message_id)
    return result


def test_a_text_only_hit_gets_its_headline_snippet(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """`ded76e225`: text only marks every retained row `text_hit` (kills M2)."""
    planted = _plant(migrated_engine)
    answer = search(migrated_engine, query=NEEDLE, collapse="none")
    hit = _result(answer, planted["long_hit"])
    assert hit.tier == 3
    assert hit.rank > 0
    assert NEEDLE not in LONG_HIT[:300]
    assert hit.snippet is not None
    assert NEEDLE in hit.snippet
    assert hit.snippet != LONG_HIT[:300]


def test_an_identifier_only_row_gets_the_plain_prefix_under_ids_plus_text(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """`ded76e225`: ids plus text keeps the evaluated `text_hit` (kills M3)."""
    planted = _plant(migrated_engine)
    answer = search(migrated_engine, query=NEEDLE, identifiers=["RFI 5"], collapse="none")
    id_only = _result(answer, planted["long_id_only"])
    assert id_only.tier == 1
    assert id_only.rank == 0
    assert id_only.snippet == LONG_ID_ONLY[:300]
    # The text hit in the same answer still gets its headline.
    hit = _result(answer, planted["long_hit"])
    assert hit.tier == 3
    assert hit.snippet is not None
    assert NEEDLE in hit.snippet


def test_a_phrase_spanning_subject_and_text_ranks_zero_with_ids_plus_text(
    migrated_engine: Engine, world: dict[str, str]
) -> None:
    """`ded76e225`: the moved rank guard holds for ids plus text (kills M1).

    The stored document matches the `english` phrase across the subject/text
    boundary, so its raw rank is positive; the per-field confirmation fails,
    so the row is an identifier match only and its rank is 0.
    """
    planted = _plant(migrated_engine)
    answer = search(migrated_engine, query='"slab pour"', identifiers=["RFI 5"], collapse="none")
    cross = _result(answer, planted["cross_field"])
    assert cross.tier == 1
    assert cross.rank == 0
    assert cross.snippet == "pour on Monday RFI 5"
    assert planted["cross_field_no_id"] not in {r.message_id for r in answer.results}
    text_only = search(migrated_engine, query='"slab pour"', collapse="none")
    assert planted["cross_field"] not in {r.message_id for r in text_only.results}
    assert all(r.rank > 0 for r in text_only.results)
