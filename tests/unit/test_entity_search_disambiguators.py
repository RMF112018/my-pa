"""`SqlEntityRepository.search` fetches its disambiguators batched, never per row.

`RI-AC-038` asked for disambiguators on the `entities.search` row.
`tests/contract/test_entity_search_disambiguators.py` proves the response
carries them and that the five original keys survive. This file proves the
*cost*, which is the half a contract test cannot see: a browse page of fifty
must issue three statements, not fifty-one.

That is the defect this feature acquires by default. The obvious implementation
-- ask each summary for its own affiliations as it is built -- is correct,
passes every behavioural assertion, and turns one round trip into `page_size + 1`
against an unindexed plane. Nothing else in the suite would notice, because
nothing else counts statements.

**How it is measured.** The repository takes its connection rather than opening
one, so a recording stub is a complete substitute for the driver here: the
statements are built, counted and compiled, and none is executed. Nothing in
this module opens a connection or reaches PostgreSQL. That the compiled SQL is
also *accepted* by PostgreSQL is `tests/database`'s claim, not this one.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Final

from sqlalchemy.dialects import postgresql

from my_pa.contracts.ports import EntitySummary
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"


class _Recorder:
    """A connection that records every statement and executes none.

    `SqlEntityRepository` is constructed around a connection it does not own,
    which is what makes this substitution honest rather than a mock of the class
    under test: the statements counted here are the statements the repository
    would have sent.
    """

    def __init__(self, page: list[SimpleNamespace]) -> None:
        self.statements: list[Any] = []
        self._page = page

    def execute(self, statement: Any) -> Any:  # noqa: ANN401 - mirrors `Connection.execute`
        self.statements.append(statement)
        rows = self._page if len(self.statements) == 1 else []
        return SimpleNamespace(all=lambda: rows, first=lambda: None)


def _row(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=f"ent_aaaa{index:04d}aaaa{index:04d}",
        entity_type="person",
        canonical_name=f"synthetic person {index}",
        display_name=f"Synthetic Person {index}",
        status="active",
    )


def _compiled(statement: Any) -> str:  # noqa: ANN401 - any SQLAlchemy statement
    return str(statement.compile(dialect=postgresql.dialect()))


def test_a_page_of_one_and_a_page_of_fifty_cost_the_same_three_statements() -> None:
    """The anti-N+1 claim, and both halves are needed.

    One statement would prove nothing (a per-row read of an empty page issues
    none), and fifty rows alone would not distinguish "batched" from "capped at
    fifty". The two together do: the count does not move with the page.
    """
    counted = []
    for size in (1, 50):
        recorder = _Recorder([_row(index) for index in range(1, size + 1)])
        page = SqlEntityRepository(recorder).search(PRINCIPAL, "synthetic", limit=size)  # type: ignore[arg-type]
        assert len(page) == size
        counted.append(len(recorder.statements))
    assert counted == [3, 3], counted


def test_an_empty_page_asks_no_further_question() -> None:
    """No page, no disambiguators: two statements a caller pays for and gets nothing from."""
    recorder = _Recorder([])
    assert SqlEntityRepository(recorder).search(PRINCIPAL, "nobody whatsoever") == []  # type: ignore[arg-type]
    assert len(recorder.statements) == 1


def test_both_disambiguator_reads_are_bounded_twice_over() -> None:
    """A window cut per entity, and a `LIMIT` over the whole read.

    The window is what stops one entity with forty affiliations from starving
    the rest of the page -- a plain `LIMIT` over rows ordered by subject would
    let the first subject consume the budget. The `LIMIT` is the second bound,
    so the read stays finite even if the window is ever changed out from under
    that claim. Both are asserted because losing either is silent.
    """
    recorder = _Recorder([_row(1), _row(2)])
    SqlEntityRepository(recorder).search(PRINCIPAL, "synthetic", limit=2)  # type: ignore[arg-type]
    for statement in recorder.statements[1:]:
        rendered = _compiled(statement)
        assert "row_number() OVER (PARTITION BY" in rendered, rendered
        assert "LIMIT" in rendered, rendered


def test_both_disambiguator_reads_carry_their_own_partition_predicate() -> None:
    """Scoped as well as keyed by the page's identifiers.

    The `IN (…)` list names entities this Principal was already shown, so a
    missing partition predicate would not leak through *these* rows -- it would
    leak through the joined organization, whose display name is a second
    `entities` row nobody asked about. Asserted on both statements rather than
    on the one that joins, because the claim is about the rule and not about
    today's SQL.
    """
    recorder = _Recorder([_row(1)])
    SqlEntityRepository(recorder).search(PRINCIPAL, "synthetic", limit=1)  # type: ignore[arg-type]
    for statement in recorder.statements[1:]:
        assert "principal_id = " in _compiled(statement)


def test_a_summary_without_context_carries_two_empty_collections() -> None:
    """The default the whole backwards-compatible widening rests on.

    `EntitySummary` gained two fields with defaults so that the three
    construction sites -- this repository's mapper, the in-memory fake and the
    evaluation corpus -- all keep constructing. An entity with no affiliation
    and no participation answers with empty rather than absent.
    """
    recorder = _Recorder([_row(1)])
    (summary,) = SqlEntityRepository(recorder).search(PRINCIPAL, "synthetic", limit=1)  # type: ignore[arg-type]
    assert summary.affiliated_organizations == ()
    assert summary.project_roles == ()


def test_a_project_engagement_without_a_role_is_the_project_alone() -> None:
    """`EntitySummary.project_role`, which all three implementations compose through.

    Held in one place precisely so the fake and the server cannot spell the same
    fact differently; `role_text` is nullable in the schema, so the null branch
    is the ordinary one rather than an edge case.
    """
    assert EntitySummary.project_role("Harbour Tower", None) == "Harbour Tower"
    assert EntitySummary.project_role("Harbour Tower", "") == "Harbour Tower"
    assert (
        EntitySummary.project_role("Harbour Tower", "commissioning lead")
        == "commissioning lead on Harbour Tower"
    )
