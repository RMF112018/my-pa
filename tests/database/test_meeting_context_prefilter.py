"""WP5-R2 R2-1: the Project-number pre-filter is a superset of the exact match
under any server lowering, ICU included.

The `database` tier, run on the C and the en_US.UTF-8 clusters alike.

- A `simple` lexeme is its token lowered one character at a time by the C
  library. The pre-filter looks for the number's lexeme in the text's `lower()`.
  On a libc database the two lowerings are one; ICU's `lower()` is
  context-sensitive (Greek final sigma), multi-character (`İ` is `i` and a
  combining dot) and tailored (`tr`, `lt`). Without the identification the
  pre-filter would drop a true match there.
- The first test lowers the text and the lexeme under each ICU collation the
  server has, which is what `lower()` does in a database of that provider, and
  requires every lexeme of every exactly matching number to pass the
  production pre-filter predicate (`number_prefilter`, which translates only a
  text holding a changed character) and the full identification alike. It
  also requires the bare form to miss somewhere, so the hazard is really
  exercised.
- The second test needs no ICU: it feeds the ICU-lowered forms themselves, as
  literals, to the same expressions.

Every value is synthetic.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from sqlalchemy import Boolean, Engine, Text, column, func, literal, select, table, true, values
from sqlalchemy.dialects.postgresql import REGCONFIG, TSQUERY

from my_pa.infrastructure.persistence.communications import (
    number_prefilter,
    number_prefilter_haystack,
    number_prefilter_needle,
)

pytestmark = pytest.mark.database

#: Project numbers carrying every character a server lowering treats apart.
NUMBERS: Final = (
    "ΟΔΟΣ-4",
    "ΣΑΣ",
    "\u039b\u039f\u0393\u039f\u03a312",
    "ΟΔΟΣΑ-7",
    "İX-1",
    "KİT-9",
    "IX-5",
    "ÌX-2",
    "JÍ-5",
    "ĨA-3",
    "ǅX-3",
    "ǈ-6",
    "ΎΑ-1",
    "ΏΒ-2",
    "SYN-4417",
)
#: How a number appears in a message: as written, re-cased, glued, wrapped.
WRAPPINGS: Final = (
    "{n}",
    "Job {n} invoice",
    "{lower}",
    "x{n}",
    "{n}s",
    "({n})",
    "{n}, {n}",
    "RE: {n} / {lower}",
    "<b>{n}</b>",
    "{n}-{n}",
)
ICU_COLLATIONS: Final = ("und-x-icu", "tr-x-icu", "lt-x-icu")
_COLLATIONS: Final = table("pg_collation", column("collname", Text), schema="pg_catalog")


def _simple(name: str) -> Any:  # noqa: ANN401 - a SQL expression
    return literal(name).cast(REGCONFIG)


def _pairs() -> list[tuple[str, str]]:
    return [
        (number, wrapping.format(n=number, lower=number.lower()))
        for number in NUMBERS
        for wrapping in WRAPPINGS
    ]


@pytest.mark.parametrize("collation", ICU_COLLATIONS)
def test_every_exact_number_match_passes_the_prefilter_under_icu_lowering(
    migrated_engine: Engine, collation: str
) -> None:
    with migrated_engine.connect() as connection:
        present = connection.scalar(
            select(func.count()).select_from(_COLLATIONS).where(_COLLATIONS.c.collname == collation)
        )
        if not present:
            pytest.skip(f"the server has no {collation} collation")
        pairs = values(column("number", Text), column("body", Text), name="pairs").data(_pairs())
        lexeme = column("lexeme", Text)
        lexemes = (
            func.unnest(func.tsvector_to_array(func.to_tsvector(_simple("simple"), pairs.c.number)))
            .table_valued(lexeme)
            .render_derived()
        )
        exact = func.to_tsvector(_simple("simple"), pairs.c.body).bool_op("@@")(
            func.plainto_tsquery(_simple("simple"), pairs.c.number, type_=TSQUERY)
        )
        body = pairs.c.body.collate(collation)
        needle = number_prefilter_needle(lexeme.collate(collation))
        # The production predicate, and the identification it short-cuts.
        passes = number_prefilter(body, needle)
        folded = func.strpos(number_prefilter_haystack(body), needle) > 0
        bare = func.strpos(func.lower(pairs.c.body.collate(collation)), lexeme) > 0
        rows = connection.execute(
            select(
                pairs.c.number,
                pairs.c.body,
                lexeme,
                passes.label("passes"),
                folded.label("folded"),
                bare.label("bare"),
            )
            .select_from(pairs.join(lexemes, true()))
            .where(exact.cast(Boolean))
        ).all()
    assert len({(row.number, row.body) for row in rows}) >= len(NUMBERS) * 6
    misses = [(row.number, row.body, row.lexeme) for row in rows if not row.passes]
    assert misses == []
    assert all(row.folded for row in rows)
    # The hazard is real under this collation: the bare form drops a true match.
    assert any(not row.bare for row in rows)


#: (what an ICU `lower()` makes of a text, the `simple` lexeme of its number on
#: a libc database). Each is a true match the bare `strpos` would drop. (A
#: title-case digraph such as `ǅ` needs ICU to lower the lexeme too, so only the
#: collation test above can show it.)
ICU_FORMS: Final = (
    ("οδος-4", "οδοσ"),  # final sigma, by context
    ("job οδος", "οδοσ"),
    ("i̇x-1", "ix"),  # `İ`: `i` and a combining dot
    ("ki̇t-9", "kit"),
    ("\u0131x-5", "ix"),  # `tr`: `I` is dotless
    ("i̇̀x-2", "ìx"),  # `lt`: `Ì` keeps its dot
    ("ji̇́-5", "jí"),
    ("i̇̃a-3", "ĩa"),
    ("ύα-1", "ώα"),  # macOS maps `Ύ` to `ώ`
    ("ώβ-2", "Ϗβ"),  # and `Ώ` to `Ϗ`
)


def test_the_identification_holds_the_icu_forms_directly(migrated_engine: Engine) -> None:
    forms = values(column("lowered", Text), column("lexeme", Text), name="forms").data(
        list(ICU_FORMS)
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            select(
                forms.c.lowered,
                number_prefilter(forms.c.lowered, number_prefilter_needle(forms.c.lexeme)).label(
                    "passes"
                ),
                (func.strpos(forms.c.lowered, forms.c.lexeme) > 0).label("bare"),
            )
        ).all()
    assert len(rows) == len(ICU_FORMS)
    assert [row.lowered for row in rows if not row.passes] == []
    assert [row.lowered for row in rows if row.bare] == []
