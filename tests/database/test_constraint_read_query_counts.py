"""PC-CM-IMP-WP03 §L T23: how many statements a read costs, and what it does not depend on.

A ceiling alone is a weak guard — it passes for as long as nobody adds a row.
The property that actually rules out an N+1 is that the count does not move: a
fifty-row Register page and a five-row one issue **the same** statements, and so
does a page read out of a Register ten times larger. Every test below asserts
both halves, and the equality is the one that would fail first if a per-row read
were ever introduced.

The counts are what the composed read service issues end to end, the Project
settings read included, and they are stated exactly rather than as an upper
bound so that adding a statement has to be a decision someone makes on purpose:

* Register page — **six**: settings, the rows, the page's parties in bulk, the
  sync target with its baselines, the open conflicts, the Category list. The
  Entity label read is a seventh only when a page holds an ENTITY party with no
  stored label of its own, and it is one statement for the whole page then too.
* One detail record — **eight**: the record with its parties joined, settings,
  the parties again for projection, the two sync statements, the Category list,
  the relationships and the evidence links.
* One history page — **one**.
* The overview — **four**: settings, the aggregate, and the two sync statements.

Every identifier and code here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import ConstraintListQuery, ConstraintListScope
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import entities, projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_cntaaaa01"
PRINCIPAL_B: Final = "prn_cntbbbb02"
PROJECT_A: Final = "prj_cntaaaa01"
PROJECT_B: Final = "prj_cntbbbb02"
CATEGORY_A: Final = "ccat_cntaaaa01"
CATEGORY_B: Final = "ccat_cntbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_cnt{ordinal:06d}"


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


ENTITY_LABELLED: Final = _id("ent", 1)
ENTITY_BARE: Final = _id("ent", 2)

#: The exact costs, stated rather than bounded. A change to any of them is a
#: change to the read plane's shape and should have to be written down here.
LIST_STATEMENTS: Final = 6
LIST_STATEMENTS_WITH_ENTITY_LABELS: Final = 7
DETAIL_STATEMENTS: Final = 8
HISTORY_STATEMENTS: Final = 1
OVERVIEW_STATEMENTS: Final = 4


@contextmanager
def _counted(engine: Engine) -> Iterator[list[str]]:
    """Every statement the enclosed block sends to the server, in order."""
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

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _register(
    connection: Connection, rows: int, *, bare_entity_party: bool = False
) -> SqlConstraintManagementRepository:
    """`rows` published Constraints, each waiting on one Entity."""
    repository = _world(connection)
    for entity_id, label in ((ENTITY_LABELLED, "Sample Steel"), (ENTITY_BARE, "Sample Glazing")):
        connection.execute(
            insert(entities).values(
                entity_id=entity_id,
                principal_id=PRINCIPAL_A,
                entity_type="organization",
                canonical_name=label.lower(),
                display_name=label,
                status="active",
                created_at=T0,
                updated_at=T0,
                version=1,
            )
        )
    party = (
        PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_BARE)
        if bare_entity_party
        else PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_LABELLED, label="Sample Steel")
    )
    for ordinal in range(1, rows + 1):
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=_id("cst", ordinal),
                constraint_code=f"1.{ordinal}",
                bic=(party,),
            ),
        )
    return repository


def _extend(repository: SqlConstraintManagementRepository, first: int, last: int) -> None:
    """More rows in the same Register, so a growing Project can be measured twice."""
    for ordinal in range(first, last + 1):
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=_id("cst", ordinal),
                constraint_code=f"1.{ordinal}",
                bic=(
                    PartyRef(
                        kind=PartyKind.ENTITY, entity_id=ENTITY_LABELLED, label="Sample Steel"
                    ),
                ),
            ),
        )


def _list_page(repository: SqlConstraintManagementRepository, limit: int) -> int:
    page = SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(scope=ConstraintListScope.ALL, limit=limit),
        now=NOW,
    )
    return len(page.entries)


def test_a_fifty_row_page_and_a_five_row_page_cost_exactly_the_same(
    migrated_engine: Engine,
) -> None:
    """The real N+1 proof: the count is a function of the query, not of the data."""
    with migrated_engine.begin() as connection:
        repository = _register(connection, 60)
        with _counted(migrated_engine) as small:
            assert _list_page(repository, 5) == 5
        with _counted(migrated_engine) as large:
            assert _list_page(repository, 50) == 50
        assert len(small) == len(large) == LIST_STATEMENTS


def test_the_page_cost_does_not_move_when_the_register_grows(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection, 10)
        with _counted(migrated_engine) as small_register:
            assert _list_page(repository, 5) == 5
        _extend(repository, 11, 200)
        with _counted(migrated_engine) as large_register:
            assert _list_page(repository, 5) == 5
        assert len(small_register) == len(large_register) == LIST_STATEMENTS


def test_the_entity_label_read_is_one_more_statement_for_a_whole_page(
    migrated_engine: Engine,
) -> None:
    """Conditional, and bulk when it happens: never one lookup per party."""
    with migrated_engine.begin() as connection:
        repository = _register(connection, 60, bare_entity_party=True)
        with _counted(migrated_engine) as small:
            assert _list_page(repository, 5) == 5
        with _counted(migrated_engine) as large:
            assert _list_page(repository, 50) == 50
        assert len(small) == len(large) == LIST_STATEMENTS_WITH_ENTITY_LABELS


def test_one_detail_record_costs_a_fixed_number_of_statements(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection, 60)
        with _counted(migrated_engine) as statements:
            SERVICE.read_constraint(
                repository, principal_id=PRINCIPAL_A, constraint_id=_id("cst", 1), now=NOW
            )
        assert len(statements) == DETAIL_STATEMENTS


def test_one_history_page_is_a_single_statement(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection, 10)
        with _counted(migrated_engine) as statements:
            SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=_id("cst", 1))
        assert len(statements) == HISTORY_STATEMENTS


def test_the_overview_costs_the_same_over_any_number_of_rows(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection, 10)
        with _counted(migrated_engine) as small:
            SERVICE.read_overview(
                repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
            )
        _extend(repository, 11, 200)
        with _counted(migrated_engine) as large:
            SERVICE.read_overview(
                repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
            )
        assert len(small) == len(large) == OVERVIEW_STATEMENTS


def test_each_bulk_read_is_one_statement_for_the_whole_collection(
    migrated_engine: Engine,
) -> None:
    """The three reads a page's cost would otherwise grow with, measured directly."""
    with migrated_engine.begin() as connection:
        repository = _register(connection, 60, bare_entity_party=True)
        identifiers = tuple(_id("cst", ordinal) for ordinal in range(1, 51))
        with _counted(migrated_engine) as parties:
            rows = repository.parties_for(PRINCIPAL_A, identifiers)
        assert len(rows) == 50
        assert len(parties) == 1
        with _counted(migrated_engine) as labels:
            repository.entity_labels(PRINCIPAL_A, (ENTITY_LABELLED, ENTITY_BARE))
        assert len(labels) == 1
        with _counted(migrated_engine) as sync:
            repository.sync_summary(PRINCIPAL_A, PROJECT_A, identifiers)
        assert len(sync) == 2
        with _counted(migrated_engine) as facts:
            repository.overview_facts(
                PRINCIPAL_A,
                PROJECT_A,
                as_of=NOW,
                project_today=date(2026, 9, 14),
                due_soon_through=date(2026, 9, 23),
            )
        assert len(facts) == 1


def test_an_empty_collection_asks_the_server_nothing(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection, 1)
        with _counted(migrated_engine) as statements:
            assert repository.parties_for(PRINCIPAL_A, ()) == ()
            assert repository.entity_labels(PRINCIPAL_A, ()) == {}
        assert statements == []


def test_no_read_statement_takes_a_row_lock(migrated_engine: Engine) -> None:
    """`get_for_update` and `get_category_for_update` remain the only two that do."""
    with migrated_engine.begin() as connection:
        repository = _register(connection, 10)
        with _counted(migrated_engine) as statements:
            _list_page(repository, 5)
            SERVICE.read_constraint(
                repository, principal_id=PRINCIPAL_A, constraint_id=_id("cst", 1), now=NOW
            )
            SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=_id("cst", 1))
            SERVICE.read_overview(
                repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
            )
        assert statements
        assert all("FOR UPDATE" not in statement.upper() for statement in statements)
        with _counted(migrated_engine) as locking:
            repository.get_for_update(PRINCIPAL_A, _id("cst", 1))
        assert any("FOR UPDATE" in statement.upper() for statement in locking)
