"""PC-CM-IMP-WP03 §L T16-T17: the five orders, and the keyset that continues them.

A Constraint Code is an identity, not a number. Ordering it as text gives
`2.01, 2.10, 2.100, 2.09`, and ordering it as a decimal turns `7.30` into `7.3`
— so the Code sort orders by the Category's display order and prefix and then by
the *length* of the sequence segment before its text. That is what makes
`2.01 < 2.09 < 2.10 < 2.100` come out right with no cast anywhere in the
statement, and the ordering assertion below is the exact accepted example.

The keyset is the same tuple as the `ORDER BY`, which is the property most of
these tests exist for. An anchor narrower than its own ordering does not name a
unique position: two Categories can allocate the same sequence numbers, so a
Code anchor of `(length, sequence)` alone is ambiguous exactly at a Category
boundary, and a continuation from it would skip the rows the next Category
starts with. `test_a_page_that_ends_on_a_category_boundary_skips_nothing` lands a
page on that boundary deliberately.

Null keys sort last in both directions, and they do so because the ordering
leads with an explicit discriminator that the keyset predicate compares too —
not because a convention is remembered in two places.

Every code, date and identifier here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.application.errors import ConflictError, InvalidRequestError, SafeDetail
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    ConstraintListPage,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintListSpec,
    ConstraintSort,
    SortDirection,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_srtaaaa01"
PRINCIPAL_B: Final = "prn_srtbbbb02"
PROJECT_A: Final = "prj_srtaaaa01"
PROJECT_B: Final = "prj_srtbbbb02"
CATEGORY_A: Final = "ccat_srtaaaa01"
CATEGORY_B: Final = "ccat_srtbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_srt{ordinal:06d}"


def _seed_project(connection: Connection, principal: str, project: str) -> None:
    connection.execute(
        insert(projects).values(
            project_id=project,
            principal_id=principal,
            name="Sample Project",
            state="active",
            participants=[],
            opened_at=T0,
            created_at=T0,
            updated_at=T0,
        )
    )


def _category(
    category_id: str, principal: str, project: str, prefix: str, display_order: int
) -> ConstraintCategory:
    return ConstraintCategory(
        category_id=category_id,
        principal_id=principal,
        project_id=project,
        prefix=prefix,
        title=f"Category {prefix}",
        state=ConstraintCategoryState.ACTIVE,
        created_at=T0,
        updated_at=T0,
        display_order=display_order,
    )


def _settings(principal: str, project: str, zone: str = ZONE_EAST) -> ConstraintProjectSettings:
    return ConstraintProjectSettings(
        principal_id=principal,
        project_id=project,
        timezone_name=zone,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _constraint(**overrides: object) -> ProjectConstraint:
    """One published, active Constraint. Every value in it is synthetic."""
    values: dict[str, Any] = {
        "constraint_id": _id("cst", 1),
        "principal_id": PRINCIPAL_A,
        "lifecycle_state": ConstraintLifecycleState.IDENTIFIED,
        "origin": ConstraintOrigin.PRODUCT,
        "record_quality": ConstraintRecordQuality.NORMAL,
        "created_at": T0,
        "updated_at": T0,
        "version": 2,
        "project_id": PROJECT_A,
        "category_id": CATEGORY_A,
        "constraint_code": "1.01",
        "description": "Switchgear submittal outstanding",
        "date_identified": date(2026, 9, 1),
        "due_date": date(2026, 9, 30),
        "bic": (PartyRef(kind=PartyKind.PRINCIPAL),),
        "published_at": T0,
    }
    values.update(overrides)
    return ProjectConstraint(**values)


def _world(connection: Connection, *, zone: str = ZONE_EAST) -> SqlConstraintManagementRepository:
    """Both Principals, both Projects, one Category each. Nothing is shared."""
    _seed_project(connection, PRINCIPAL_A, PROJECT_A)
    _seed_project(connection, PRINCIPAL_B, PROJECT_B)
    repository = SqlConstraintManagementRepository(connection)
    repository.insert_project_settings(PRINCIPAL_A, _settings(PRINCIPAL_A, PROJECT_A, zone))
    repository.insert_project_settings(PRINCIPAL_B, _settings(PRINCIPAL_B, PROJECT_B, zone))
    repository.insert_category(PRINCIPAL_A, _category(CATEGORY_A, PRINCIPAL_A, PROJECT_A, "AAA", 1))
    repository.insert_category(PRINCIPAL_B, _category(CATEGORY_B, PRINCIPAL_B, PROJECT_B, "BBB", 1))
    return repository


CATEGORY_SECOND: Final = "ccat_srtaaaa09"

R1: Final = _id("cst", 1)
R2: Final = _id("cst", 2)
R3: Final = _id("cst", 3)
R4: Final = _id("cst", 4)
R5: Final = _id("cst", 5)
R6: Final = _id("cst", 6)
DRAFT: Final = _id("cst", 7)

#: `2.01 < 2.09 < 2.10 < 2.100` is the accepted example, and it is only true if
#: the sequence segment is compared by length before text.
CODE_ORDER: Final = [R1, R2, R3, R4, R5, R6, DRAFT]


def _ordered(connection: Connection) -> SqlConstraintManagementRepository:
    """Four Constraints in one Category and two in the next, plus one unsorted Draft."""
    repository = _world(connection)
    repository.insert_category(
        PRINCIPAL_A, _category(CATEGORY_SECOND, PRINCIPAL_A, PROJECT_A, "BBX", 2)
    )
    rows = (
        (R1, "2.01", date(2026, 9, 20), date(2026, 9, 1), CATEGORY_A, 1),
        (R2, "2.09", date(2026, 9, 21), date(2026, 9, 2), CATEGORY_A, 2),
        (R3, "2.10", date(2026, 9, 22), date(2026, 9, 3), CATEGORY_A, 3),
        (R4, "2.100", date(2026, 9, 22), date(2026, 9, 4), CATEGORY_A, 4),
        (R5, "5.01", date(2026, 9, 25), date(2026, 9, 7), CATEGORY_SECOND, 5),
        (R6, "5.02", date(2026, 9, 26), date(2026, 9, 8), CATEGORY_SECOND, 6),
    )
    for identifier, code, due, identified, category, day in rows:
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=identifier,
                constraint_code=code,
                category_id=category,
                due_date=due,
                date_identified=identified,
                updated_at=datetime(2026, 9, day, 9, 0, tzinfo=UTC),
            ),
        )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=DRAFT,
            lifecycle_state=ConstraintLifecycleState.DRAFT,
            constraint_code=None,
            category_id=None,
            due_date=None,
            date_identified=None,
            published_at=None,
            # `updated_at` is never null, so the Draft has no "missing key" case
            # under that sort; it is stamped last so the one order it does take
            # part in is still fully stated.
            updated_at=datetime(2026, 9, 9, 9, 0, tzinfo=UTC),
            bic=(),
        ),
    )
    return repository


def _page(repository: SqlConstraintManagementRepository, **fields: object) -> ConstraintListPage:
    return SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(scope=ConstraintListScope.ALL, **fields),
        now=NOW,
    )


def _sequence(repository: SqlConstraintManagementRepository, **fields: object) -> list[str]:
    return [entry.constraint_id for entry in _page(repository, **fields).entries]


def test_constraint_codes_order_by_sequence_length_then_text(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        page = _page(repository, sort=ConstraintSort.CODE)
        assert [entry.constraint_id for entry in page.entries] == CODE_ORDER
        assert [entry.constraint_code for entry in page.entries] == [
            "2.01",
            "2.09",
            "2.10",
            "2.100",
            "5.01",
            "5.02",
            None,
        ]


def test_no_code_is_normalised_into_a_number_on_the_way_out(
    migrated_engine: Engine,
) -> None:
    """`7.30` and `7.3` are two codes. A decimal cast would make them one."""
    with migrated_engine.begin() as connection:
        repository = _world(connection)
        for ordinal, code in ((1, "7.3"), (2, "7.30")):
            repository.insert_constraint(
                PRINCIPAL_A,
                _constraint(constraint_id=_id("cst", ordinal), constraint_code=code),
            )
        page = _page(repository, sort=ConstraintSort.CODE)
        assert [entry.constraint_code for entry in page.entries] == ["7.3", "7.30"]


def test_the_code_order_reverses_completely_when_the_direction_does(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        descending = _sequence(repository, sort=ConstraintSort.CODE, direction=SortDirection.DESC)
        assert descending == [R6, R5, R4, R3, R2, R1, DRAFT]


def test_every_sort_orders_by_the_column_it_names(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        assert _sequence(repository, sort=ConstraintSort.DATE_IDENTIFIED) == [
            R1,
            R2,
            R3,
            R4,
            R5,
            R6,
            DRAFT,
        ]
        assert _sequence(repository, sort=ConstraintSort.UPDATED_AT) == [
            R1,
            R2,
            R3,
            R4,
            R5,
            R6,
            DRAFT,
        ]
        assert _sequence(repository, sort=ConstraintSort.DUE_DATE) == [
            R1,
            R2,
            R3,
            R4,
            R5,
            R6,
            DRAFT,
        ]


def test_days_elapsed_sorts_as_date_identified_inverted(migrated_engine: Engine) -> None:
    """Days Elapsed is a decreasing function of Date Identified, so it is one column."""
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        ascending = _sequence(repository, sort=ConstraintSort.DAYS_ELAPSED)
        assert ascending == [R6, R5, R4, R3, R2, R1, DRAFT]
        page = _page(repository, sort=ConstraintSort.DAYS_ELAPSED)
        elapsed = [entry.days_elapsed for entry in page.entries if entry.days_elapsed is not None]
        assert elapsed == sorted(elapsed)


def test_a_row_missing_the_sort_key_is_last_in_both_directions(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        for sort in (
            ConstraintSort.CODE,
            ConstraintSort.DATE_IDENTIFIED,
            ConstraintSort.DAYS_ELAPSED,
            ConstraintSort.DUE_DATE,
        ):
            for direction in (SortDirection.ASC, SortDirection.DESC):
                assert _sequence(repository, sort=sort, direction=direction)[-1] == DRAFT


def test_rows_that_tie_on_the_sort_key_break_on_the_identifier(
    migrated_engine: Engine,
) -> None:
    """Every sort is a total order, which is what paging needs to be stable."""
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        ascending = _sequence(repository, sort=ConstraintSort.DUE_DATE)
        assert ascending.index(R3) < ascending.index(R4)
        descending = _sequence(
            repository, sort=ConstraintSort.DUE_DATE, direction=SortDirection.DESC
        )
        assert descending.index(R4) < descending.index(R3)


def _walk(
    repository: SqlConstraintManagementRepository, *, limit: int, **fields: object
) -> list[str]:
    """Every row, read one page at a time through the cursors the pages issue."""
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        page = _page(repository, limit=limit, cursor=cursor, **fields)
        seen.extend(entry.constraint_id for entry in page.entries)
        if not page.is_truncated:
            return seen
        cursor = page.next_cursor
        assert cursor is not None
    raise AssertionError("the walk did not terminate")


def test_paging_through_a_sort_returns_every_row_exactly_once(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        for sort in ConstraintSort:
            for direction in (SortDirection.ASC, SortDirection.DESC):
                for limit in (1, 2, 3):
                    walked = _walk(repository, limit=limit, sort=sort, direction=direction)
                    whole = _sequence(repository, sort=sort, direction=direction)
                    assert walked == whole
                    assert len(walked) == len(set(walked))


def test_a_page_that_ends_on_a_category_boundary_skips_nothing(
    migrated_engine: Engine,
) -> None:
    """The case a `(length, sequence)` anchor gets wrong, asked for deliberately.

    Four rows fill the first Category exactly, so the anchor is its last row —
    sequence `100`, length 3. The next Category's first row has sequence `01`,
    length 2, which a narrower anchor would place *before* the position and skip.
    """
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        first = _page(repository, sort=ConstraintSort.CODE, limit=4)
        assert [entry.constraint_id for entry in first.entries] == [R1, R2, R3, R4]
        assert first.is_truncated is True
        assert first.next_cursor is not None
        second = _page(repository, sort=ConstraintSort.CODE, limit=4, cursor=first.next_cursor)
        assert [entry.constraint_id for entry in second.entries] == [R5, R6, DRAFT]
        assert second.is_truncated is False


def test_an_unreadable_cursor_is_an_invalid_request(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        for token in ("not-a-cursor", "!!!!", "eyJ1bmV4cGVjdGVkIjogdHJ1ZX0"):
            with pytest.raises(InvalidRequestError) as error:
                _page(repository, cursor=token)
            assert error.value.safe_details == (SafeDetail.CURSOR,)


def test_a_cursor_reused_under_a_changed_request_is_a_conflict(
    migrated_engine: Engine,
) -> None:
    """The binding covers everything that gives the page meaning, so all four fail."""
    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        first = _page(repository, sort=ConstraintSort.CODE, limit=2)
        assert first.next_cursor is not None
        token = first.next_cursor
        changed: tuple[dict[str, object], ...] = (
            {"sort": ConstraintSort.DUE_DATE, "limit": 2},
            {"sort": ConstraintSort.CODE, "limit": 3},
            {"sort": ConstraintSort.CODE, "limit": 2, "direction": SortDirection.DESC},
            {"sort": ConstraintSort.CODE, "limit": 2, "search_text": "switchgear"},
        )
        for fields in changed:
            with pytest.raises(ConflictError) as error:
                _page(repository, cursor=token, **fields)
            assert error.value.safe_details == (SafeDetail.CURSOR,)
        resumed = _page(repository, sort=ConstraintSort.CODE, limit=2, cursor=token)
        assert [entry.constraint_id for entry in resumed.entries] == [R3, R4]


def test_the_page_limit_is_applied_by_the_database_and_not_by_a_slice(
    migrated_engine: Engine,
) -> None:
    """Two proofs: the statement carries a `LIMIT`, and it fetches only that many."""
    statements: list[str] = []

    def _record(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    with migrated_engine.begin() as connection:
        repository = _ordered(connection)
        query = ConstraintListQuery(scope=ConstraintListScope.ALL, limit=2)
        spec = ConstraintListSpec(
            query=query,
            as_of=NOW,
            project_today=date(2026, 9, 14),
            due_soon_through=date(2026, 9, 23),
            fetch_limit=query.limit + 1,
        )
        event.listen(migrated_engine, "before_cursor_execute", _record)
        try:
            records = repository.list_constraints(PRINCIPAL_A, PROJECT_A, spec=spec)
        finally:
            event.remove(migrated_engine, "before_cursor_execute", _record)
        assert len(records) == spec.fetch_limit
        assert len(statements) == 1
        assert "LIMIT" in statements[0].upper()
        assert "FOR UPDATE" not in statements[0].upper()
