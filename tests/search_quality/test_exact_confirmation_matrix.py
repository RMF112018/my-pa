"""A generated matrix over the exact confirmation, because two sweeps were not enough.

`QC-AC-050` has now been falsified twice by the same function for the same
reason, and both times the case was fixed and the class was left open. Run 2
found that `_exact_confirmation` compared raw bytes while the predicate compares
lowercased lexemes, closed **case**, and left **syntax** open in the same cycle:
`"buyout"` and `buyout.` still matched the index and were still removed
afterwards, silently. A third hand-written list of cases would close whatever
this round happens to have thought of and leave the next axis open, so this file
does not contain a list of cases.

**What it contains instead is a derivation.** Every query form it exercises is
generated from what *the server* says about the text-search configuration in
force:

* the code points the configuration's own parser reports as `blank` tokens, read
  through `pg_ts_config` -> `pg_ts_parser` -> `ts_token_type`. That is where the
  double quote, the full stop, the parenthesis and the thirty-odd others come
  from. Nobody typed them, so a punctuation character nobody remembered is
  covered on the same footing as the one that was reported;
* the words `websearch_to_tsquery` swallows as operators, found by asking which
  words vanish from the parsed query — a word read as syntax is a word that is
  not in the result. On this server that derivation returns `or`, and it returns
  it without `or` appearing anywhere in this file.

**The property.** The confirmation runs *after* the indexed predicate, so it can
only ever remove rows. A removal is invisible: there is no exception, no
limitation token, and nothing in the answer that distinguishes "no capture says
that" from "a capture says exactly that and this filter dropped it". So for
every generated cell the matrix asserts that a removal happened **only** for the
one reason the confirmation exists — the query's literal content is genuinely
not in the document — and that the needle it tested was a substring of what the
caller actually typed rather than something this module invented.

**What this matrix cannot see, stated rather than implied.**

1. **The code-point universe is finite.** It is ASCII `0x20`-`0x7E` plus the
   named non-ASCII code points in `UNIVERSE`. A parser behaviour that appears
   only in a code point outside that set is not covered.
2. **The decoration shapes are finite**: one character at the start, at the end,
   at both ends, or between two terms. A form needing two *different*
   decorations, or nesting, is not generated.
3. **Operator words are derived over two-letter lower-case ASCII words only.**
   A three-letter operator word would not be found, and the derivation would
   report the same empty-handed silence a typed list would.
4. **The corpus is small and synthetic.** The matrix varies the *query* richly
   and the *document* barely, so a divergence that needs a particular document
   shape rather than a particular query shape is outside it.
5. **It never sees a query `SearchQuery` refuses.** Null bytes, control and
   format characters, and every non-ASCII whitespace are rejected or collapsed
   in `domain.search.query` before this plane exists. Those axes are closed
   upstream, and this matrix does not re-prove them; it counts what it was
   refused so that a change upstream shows here as a count moving.
6. **One server, one configuration.** Everything derived here is derived from
   the PostgreSQL this suite is pointed at, under `SEARCH_CONFIG`.

Synthetic fixtures throughout (`QC-AC-073`, `AGENTS.md` section 5).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, and_, select, text, true
from sqlalchemy.engine import Connection
from tests.pipeline.conftest import save

from my_pa.contracts.ports import CaptureSearchRequest
from my_pa.domain.search.query import SearchQuery, SearchQueryError
from my_pa.infrastructure.persistence import capture_search
from my_pa.infrastructure.persistence.tables import capture_versions

pytestmark = pytest.mark.database

#: The stated code-point universe of blind spot (1). Printable ASCII, plus a
#: handful of non-ASCII code points chosen because they are the ones a note
#: actually carries: a typographic apostrophe, an em dash, a combining accent,
#: and two spaces that are not `U+0020`.
#: Written as code points rather than as characters, because two of them are
#: invisible and one is a combining mark that would attach itself to the
#: quotation mark before it in this file.
UNIVERSE: tuple[str, ...] = (
    *(chr(point) for point in range(0x20, 0x7F)),
    *(chr(point) for point in (0x2019, 0x2014, 0x0301, 0x00A0, 0x3000)),
)

#: Captures the matrix searches. Each carries at least one of `TERMS` verbatim,
#: and the three cases of the same sentence are there so that a confirmation
#: which stopped folding case has somewhere to fail.
CORPUS: tuple[str, ...] = (
    "Buyout review scheduled.",
    "buyout review scheduled.",
    "BUYOUT REVIEW SCHEDULED.",
    "I will send the RFI-0421 response and the $12,500.00 revision.",
)

#: The literals the generated queries are built around. Two are plain words and
#: two are the strings the parser splits into adjacent lexemes, which is the
#: residue the confirmation exists for.
TERMS: tuple[str, ...] = ("buyout", "scheduled", "RFI-0421", "12,500.00")


@dataclass(frozen=True, slots=True)
class Cell:
    """One generated query, and where it came from."""

    axis: str
    query: str


def _blank_code_points(connection: Connection) -> frozenset[str]:
    """Which of `UNIVERSE` the configuration's own parser calls `blank`.

    Read from the catalogue rather than written down, which is the whole
    mechanism: this is the set the confirmation's needle trim is defined over,
    so deriving the test's decorations from it means the test and the code are
    reading the same declaration rather than two lists that agree today.
    """
    parser = connection.execute(
        text(
            "SELECT parser.prsname FROM pg_ts_parser AS parser "
            "JOIN pg_ts_config AS configured ON configured.cfgparser = parser.oid "
            "WHERE configured.oid = CAST(:configuration AS regconfig)"
        ),
        {"configuration": capture_search.SEARCH_CONFIG},
    ).scalar_one()
    blank = connection.execute(
        text("SELECT tokid FROM ts_token_type(CAST(:parser AS text)) WHERE alias = 'blank'"),
        {"parser": parser},
    ).scalar_one()
    found = []
    for character in UNIVERSE:
        kinds = (
            connection.execute(
                text("SELECT tokid FROM ts_parse(CAST(:parser AS text), :probe)"),
                {"parser": parser, "probe": character},
            )
            .scalars()
            .all()
        )
        if kinds and all(kind == blank for kind in kinds):
            found.append(character)
    return frozenset(found)


def _operator_words(connection: Connection) -> frozenset[str]:
    """Words `websearch_to_tsquery` reads as syntax rather than as content.

    Found by the same test the defect class is about: a word that is *meant*
    disappears from the parsed query, because the parser spent it on an operator
    instead of a lexeme. Two-letter lower-case ASCII words, which is blind spot
    (3).
    """
    return frozenset(
        connection.execute(
            text(
                "SELECT word FROM ("
                "  SELECT chr(97 + first) || chr(97 + second) AS word"
                "    FROM generate_series(0, 25) AS first, generate_series(0, 25) AS second"
                ") AS candidate "
                "WHERE position(word in websearch_to_tsquery("
                "  CAST(:configuration AS regconfig), 'alpha ' || word || ' beta')::text) = 0"
            ),
            {"configuration": capture_search.SEARCH_CONFIG},
        ).scalars()
    )


def _cells(blank: frozenset[str], operators: frozenset[str]) -> tuple[Cell, ...]:
    """The generated matrix, as `(axis, query)` pairs.

    Nothing here names a syntax element. The decorations are `UNIVERSE`, the
    axis label is whichever side of the derived `blank` partition the character
    fell on, and the operator forms come from `operators`.
    """
    generated: list[Cell] = []
    for term in TERMS:
        generated.append(Cell("bare", term))
        generated.append(Cell("case/upper", term.upper()))
        generated.append(Cell("case/lower", term.lower()))
        for character in UNIVERSE:
            side = "blank" if character in blank else "token"
            generated.append(Cell(f"prefix/{side}", character + term))
            generated.append(Cell(f"suffix/{side}", term + character))
            generated.append(Cell(f"wrap/{side}", character + term + character))
        for word in sorted(operators):
            generated.append(Cell("operator-word", f"{term} {word} scheduled"))
    for character in UNIVERSE:
        side = "blank" if character in blank else "token"
        generated.append(Cell(f"infix/{side}", f"buyout{character}review"))
    return tuple(generated)


def _probe(connection: Connection, query: str) -> tuple[str | None, tuple[tuple[str, bool], ...]]:
    """The needle, and every row the *indexed* predicate matched with its verdict.

    One statement, built from the module's own expressions rather than from a
    restatement of them: the scope predicate, the indexed match and the
    confirmation are the objects `match_statement` composes, so a divergence
    between what this measures and what the product runs would have to be a
    divergence in the composition alone — which
    `test_the_matrix_measures_the_statement_the_product_runs` is what checks.
    """
    request = CaptureSearchRequest(query=SearchQuery(query), limit=100)
    # `true()` first, so a confirmation that returns *no* condition reads as
    # `confirmed` everywhere rather than raising: a plant that empties the
    # tuple must redden this matrix by dropping a row, not by erroring.
    confirmation = and_(true(), *capture_search._exact_confirmation(request))
    rows = connection.execute(
        select(
            capture_versions.c.content,
            confirmation.label("confirmed"),
            capture_search._confirmation_needle(request).label("needle"),
        ).where(
            *capture_search.capture_text_in_scope(),
            capture_search.document_vector().bool_op("@@")(capture_search._tsquery(request)),
        )
    ).all()
    needle = rows[0].needle if rows else None
    return needle, tuple((row.content, bool(row.confirmed)) for row in rows)


def test_the_exact_confirmation_removes_a_row_only_when_the_literal_is_absent(
    engine: Engine,
) -> None:
    """The class, over generated forms rather than over remembered ones.

    Three things are asserted for every cell the indexed predicate matched:

    * a removed row's content really does not contain the needle, case-folded —
      the one reason the confirmation exists;
    * the needle is a substring of the query the caller typed, so a trim that
      started *inventing* text rather than removing syntax is caught even when
      the invented text happens to match;
    * something was matched at all. A matrix whose predicate matched nothing
      would satisfy the first two by vacuity, which is the failure this
      repository has met more than once, so the count of matching cells and the
      count of *correct* removals are both asserted non-zero.

    **What reddens it.** Restore the raw-text eligibility test — the defect this
    correction cycle closed — and the blank-class prefix, suffix and wrap axes
    all report removals whose literal *is* present. Remove the case folding —
    the defect the previous cycle closed — and the bare and lower-case axes
    report the same against the capitalised capture. A control that only caught
    the newest instance would not have learned the class.
    """
    with engine.begin() as connection:
        for body in CORPUS:
            save(connection, body)

    with engine.connect() as connection:
        blank = _blank_code_points(connection)
        operators = _operator_words(connection)
        assert blank, (
            "the derivation found no `blank` code point in the whole universe, so "
            "every decoration below is the undecorated term and this matrix checks "
            "nothing — the `D-26` failure, where a list that could never fire left "
            "six planted violations green"
        )
        assert operators, (
            "the derivation found no operator word, so the operator axis is empty. "
            "`websearch_to_tsquery` has at least one, and a derivation that returns "
            "none has stopped measuring rather than started agreeing"
        )

        cells = _cells(blank, operators)
        refused = 0
        matched = 0
        correct_removals = 0
        wrong_removals: list[tuple[str, str | None, str]] = []
        invented: list[tuple[str, str]] = []
        for cell in cells:
            try:
                needle, rows = _probe(connection, cell.query)
            except SearchQueryError:
                refused += 1
                continue
            if not rows:
                continue
            matched += 1
            if needle is not None and needle not in cell.query:
                invented.append((cell.query, needle))
            for content, confirmed in rows:
                if confirmed:
                    continue
                if needle is not None and needle.lower() not in content.lower():
                    correct_removals += 1
                else:
                    wrong_removals.append((cell.query, needle, content))

    assert matched > 0, (
        f"the indexed predicate matched nothing across {len(cells)} generated cells, "
        "so every assertion below is vacuous"
    )
    assert not invented, (
        f"the confirmation tested a needle that is not part of the query the caller "
        f"typed: {invented[:5]!r}. Trimming may remove syntax; it may not invent text"
    )
    assert not wrong_removals, (
        f"{len(wrong_removals)} rows, across {matched} cells the indexed predicate "
        f"matched, were removed by the exact confirmation although the document does "
        f"contain the query's literal content. First five (query, needle, document): "
        f"{wrong_removals[:5]!r}. "
        "A removal here is invisible to the caller: `QC-AC-050` is false for those "
        "query forms and nothing raises"
    )
    assert correct_removals > 0, (
        f"across {matched} matching cells the confirmation removed nothing at all, so "
        "the assertion above is agreement by absence — a filter that never filters "
        "cannot be observed to filter correctly"
    )
    assert refused < len(cells), (
        f"`SearchQuery` refused all {len(cells)} generated queries, so the matrix "
        "measured the domain guard rather than the search plane"
    )


def test_the_matrix_measures_the_statement_the_product_runs(engine: Engine) -> None:
    """`_probe` composes the same conditions `match_statement` does.

    The matrix above builds its statement from the module's parts so that it can
    read the needle and the verdict per row in one pass. That is only sound if
    the parts compose the way the product composes them, so this asserts the two
    agree on the forms the correction cycle was opened by — and on one the
    confirmation must reject, otherwise the agreement would be agreement between
    two filters that both pass everything.
    """
    with engine.begin() as connection:
        for body in CORPUS:
            save(connection, body)

    rejecting = 0
    with engine.connect() as connection:
        for query in ('"buyout"', "buyout.", "buyout", "RFI-0421", "RFI 0421", "buyout,review"):
            request = CaptureSearchRequest(query=SearchQuery(query), limit=100)
            through_product = {
                row.version_id
                for row in connection.execute(capture_search.match_statement(request)).all()
            }
            _, rows = _probe(connection, query)
            confirmed = sum(1 for _, verdict in rows if verdict)
            assert len(through_product) == confirmed, (
                f"`match_statement` returned {len(through_product)} rows for {query!r} "
                f"while the matrix's own composition confirmed {confirmed}. The matrix "
                "is measuring something the product does not run"
            )
            if rows and confirmed < len(rows):
                rejecting += 1
    assert rejecting > 0, (
        "none of the probed forms had a row rejected by the confirmation, so the "
        "agreement above holds between two filters that both accept everything"
    )


def test_a_document_that_matches_only_at_lexeme_granularity_is_still_removed(
    engine: Engine,
) -> None:
    """The confirmation's purpose, asserted rather than assumed.

    Measured on this server: `to_tsvector('simple', 'Approve 12,500.00 today.')`
    and `to_tsvector('simple', 'Approve 12 500.00 today.')` are the *same
    vector* — `'12':2 '500.00':3` in both — because the parser spends the comma
    as a separator. So the indexed predicate alone matches a note that does not
    contain the string the caller asked for. That is the residue the
    confirmation exists to remove, and it is why the fix trims the needle rather
    than abandoning the test.

    The control is in the same test: the note that *does* contain the literal is
    returned by the same query, so "removed" is distinguishable from "the plane
    finds nothing".
    """
    with engine.begin() as connection:
        exact = save(connection, "Approve 12,500.00 today.")
        split = save(connection, "Approve 12 500.00 today.")

    request = CaptureSearchRequest(query=SearchQuery("12,500.00"), limit=100)
    with engine.connect() as connection:
        indexed = {
            str(version)
            for version in connection.execute(
                select(capture_versions.c.version_id).where(
                    *capture_search.capture_text_in_scope(),
                    capture_search.document_vector().bool_op("@@")(
                        capture_search._tsquery(request)
                    ),
                )
            ).scalars()
        }
        confirmed = {
            str(row.version_id)
            for row in connection.execute(capture_search.match_statement(request)).all()
        }

    assert indexed == {exact.version_id, split.version_id}, (
        f"the indexed predicate did not match both notes ({indexed}), so the removal "
        "below would say nothing about character granularity"
    )
    assert confirmed == {exact.version_id}, (
        f"the exact confirmation returned {confirmed}. It must keep the note that "
        "contains `12,500.00` and drop the note that only carries its two lexemes — "
        "`QC-AC-050` asks for exact, and the index alone is not"
    )
