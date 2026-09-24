"""PC-CM-RUN01-WP06: what a cross-Project Constraint read costs, and what it answers.

The defining technical risk of the portfolio reads is that they quietly become a
loop over Projects. A ceiling on the statement count would not catch that — a
per-Project read passes any ceiling until somebody adds a Project. What catches
it is **invariance**: the same arrangement read across one Project, five
Projects and twelve Projects must issue *exactly* the same statements, and so
must the same Project count read over a handful of rows and over hundreds. The
tests below assert both halves, and the equality under Project count is the one
that would fail first if a per-Project read were ever introduced. It is the most
important assertion in this module.

The counts are what the composed read service issues end to end, and they are
deliberately identical to the exact-Project figures
(`test_constraint_read_query_counts.py`), because a portfolio read asks the same
questions in bulk rather than more questions:

* Portfolio Register page — **six**: the bulk settings read, the rows, the
  page's parties in bulk, the sync targets with their baselines, the open
  conflicts, the bulk Category list. The Entity label read is a seventh only
  when the page holds an ENTITY party with no stored label of its own.
* Portfolio overview — **four**: the bulk settings read, the one grouped
  aggregate, and the two sync statements.

Those are the *read service's* figures, and they are not what a caller pays.
`ApplicationService._portfolio_projects` issues one statement more —
`work.projects.list_projects`, the canonical Project enumeration that decides
which Projects a portfolio spans — so the **composed** cost of one invocation is
seven statements and five rather than six and four. Pinning only the layer below
would let a regression that added a per-Project read *at handler level* pass
every test in this package, so the composed figures are pinned here too, as
exact equalities across the same Projects-by-rows arrangements: an eighth
statement is a failure whether it was written above the read service or inside
it.

**What seven and five do and do not count.** They are the statements the
*Constraint plane's own transaction* issues on the counted engine: the portfolio
read service's work plus the one Project enumeration. They are **not** the total
a database serves for one invocation. `_composed` deliberately gives the gateway
unit of work and the audit sink a **second** engine over the same catalog, so
their statements — the envelope's own transaction, the audit insert — are
outside every figure here by construction. That separation is the claim: the
bound this package exists to hold is a property of the portfolio read path and
must not move when an unrelated envelope or audit change does. Read seven and
five as "what the portfolio read costs", never as "what one invocation costs the
database".

Beyond cost, this module proves against real SQL the three things the fakes
cannot: that each Project's own IANA calendar is applied to that Project's own
rows inside the single grouped statement, that a second Principal's Projects and
rows are unreachable through every portfolio method, and that paging, sorting
and searching stay correct when the result set spans Projects.

Every identifier, code and description here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, insert
from sqlalchemy.engine import Connection

from my_pa.application.commands import (
    Command,
    ListConstraints,
    ListPortfolioConstraints,
    ReadConstraintOverview,
    ReadPortfolioConstraintOverview,
    SearchPortfolioConstraints,
)
from my_pa.application.constraints import ConstraintReadService
from my_pa.application.disclosure import Limitation
from my_pa.application.service import MAX_PORTFOLIO_PROJECTS, ApplicationService
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
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
    ConstraintPortfolioOverview,
    ConstraintPortfolioPage,
    ConstraintSort,
    SortDirection,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
    SqlConstraintManagementRepository,
)
from my_pa.infrastructure.persistence.tables import entities, projects
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS

pytestmark = pytest.mark.database

SERVICE: Final = ConstraintReadService()

#: Two Principals throughout, so "one Principal's portfolio cannot reach the
#: other's Projects" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_pfaaaaaa01"
PRINCIPAL_B: Final = "prn_pfbbbbbb02"

#: One fixed UTC instant, read in two IANA zones whose local dates differ across
#: it: 03:30 UTC on the 15th is still the 14th in New York and already the 15th
#: in Tokyo. No test here reads a wall clock.
NOW: Final = datetime(2026, 9, 15, 3, 30, tzinfo=UTC)
EAST_TODAY: Final = date(2026, 9, 14)
TOKYO_TODAY: Final = date(2026, 9, 15)
ZONE_EAST: Final = "America/New_York"
ZONE_TOKYO: Final = "Asia/Tokyo"

T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

#: The exact costs, stated rather than bounded, and identical to the
#: exact-Project figures for the same reads.
PORTFOLIO_LIST_STATEMENTS: Final = 6
PORTFOLIO_LIST_STATEMENTS_WITH_ENTITY_LABELS: Final = 7
PORTFOLIO_OVERVIEW_STATEMENTS: Final = 4

#: What a caller pays *on the Constraint plane's own transaction*: the figures
#: above plus the one canonical `projects.list_projects` statement
#: `ApplicationService._portfolio_projects` issues to decide which Projects the
#: portfolio spans. Stated as separate constants rather than as
#: `PORTFOLIO_LIST_STATEMENTS + 1` on purpose — an arithmetic definition would
#: move silently with the figure it is derived from, and the claim here is that
#: *both* numbers are what was measured.
#:
#: They exclude the gateway unit-of-work and audit-sink statements, which
#: `_composed` routes to a second engine on purpose. Neither figure is the total
#: number of statements one invocation sends to a database.
COMPOSED_PORTFOLIO_LIST_STATEMENTS: Final = 7
COMPOSED_PORTFOLIO_OVERVIEW_STATEMENTS: Final = 5

ACTING: Final = Principal(principal_id=PRINCIPAL_A, kind=PrincipalKind.GATEWAY, authenticated=True)

ENTITY_BARE: Final = "ent_pf00000001"


def _project_id(principal_tag: str, ordinal: int) -> str:
    return f"prj_pf{principal_tag}{ordinal:06d}"


def _category_id(principal_tag: str, ordinal: int) -> str:
    return f"ccat_pf{principal_tag}{ordinal:06d}"


def _constraint_id(ordinal: int) -> str:
    return f"cst_pf{ordinal:08d}"


def _seed_project(
    connection: Connection,
    principal: str,
    project: str,
    *,
    state: str = "active",
    name: str = "Sample Project",
) -> None:
    connection.execute(
        insert(projects).values(
            project_id=project,
            principal_id=principal,
            name=name,
            state=state,
            participants=[],
            opened_at=T0,
            created_at=T0,
            updated_at=T0,
            closed_at=T0 if state == "closed" else None,
        )
    )


def _settings(principal: str, project: str, zone: str) -> ConstraintProjectSettings:
    return ConstraintProjectSettings(
        principal_id=principal,
        project_id=project,
        timezone_name=zone,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _category(category_id: str, principal: str, project: str, prefix: str) -> ConstraintCategory:
    return ConstraintCategory(
        category_id=category_id,
        principal_id=principal,
        project_id=project,
        prefix=prefix,
        title=f"Category {prefix}",
        state=ConstraintCategoryState.ACTIVE,
        created_at=T0,
        updated_at=T0,
        display_order=1,
    )


def _constraint(**overrides: object) -> ProjectConstraint:
    """One published, active Constraint. Every value in it is synthetic."""
    values: dict[str, Any] = {
        "constraint_id": _constraint_id(1),
        "principal_id": PRINCIPAL_A,
        "lifecycle_state": ConstraintLifecycleState.IDENTIFIED,
        "origin": ConstraintOrigin.PRODUCT,
        "record_quality": ConstraintRecordQuality.NORMAL,
        "created_at": T0,
        "updated_at": T0,
        "version": 2,
        "constraint_code": "1.01",
        "description": "Switchgear submittal outstanding",
        "date_identified": date(2026, 9, 1),
        "due_date": date(2026, 9, 30),
        "bic": (PartyRef(kind=PartyKind.PRINCIPAL),),
        "published_at": T0,
    }
    values.update(overrides)
    return ProjectConstraint(**values)


class _Portfolio:
    """One Principal's owned Projects, and the identifiers a test refers to them by."""

    def __init__(self, project_ids: Sequence[str]) -> None:
        self.project_ids = tuple(project_ids)


def _seed_portfolio(
    connection: Connection,
    repository: SqlConstraintManagementRepository,
    *,
    principal: str,
    tag: str,
    projects_wanted: int,
    rows_per_project: int,
    zones: Sequence[str] = (ZONE_EAST,),
    first_constraint: int = 1,
    bare_entity_party: bool = False,
) -> _Portfolio:
    """`projects_wanted` configured Projects, each holding `rows_per_project` rows.

    The zones cycle, so any arrangement with more than one Project is also an
    arrangement with more than one calendar — a portfolio read that collapsed to
    a single date would be measured on a fixture that could expose it.
    """
    project_ids: list[str] = []
    ordinal = first_constraint
    for index in range(projects_wanted):
        project = _project_id(tag, index + 1)
        project_ids.append(project)
        _seed_project(connection, principal, project)
        repository.insert_project_settings(
            principal, _settings(principal, project, zones[index % len(zones)])
        )
        category = _category_id(tag, index + 1)
        repository.insert_category(
            principal, _category(category, principal, project, f"P{index + 1:02d}")
        )
        party = (
            PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_BARE)
            if bare_entity_party
            else PartyRef(kind=PartyKind.PRINCIPAL)
        )
        for row in range(rows_per_project):
            repository.insert_constraint(
                principal,
                _constraint(
                    constraint_id=_constraint_id(ordinal),
                    principal_id=principal,
                    project_id=project,
                    category_id=category,
                    constraint_code=f"{index + 1}.{row + 1:03d}",
                    bic=(party,),
                ),
            )
            ordinal += 1
    return _Portfolio(project_ids)


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


def _portfolio_page(
    repository: SqlConstraintManagementRepository,
    portfolio: _Portfolio,
    *,
    query: ConstraintListQuery | None = None,
    principal: str = PRINCIPAL_A,
) -> ConstraintPortfolioPage:
    """The whole portfolio answer: the page, and how many Projects were left out."""
    return SERVICE.list_portfolio_constraints(
        repository,  # type: ignore[arg-type]
        principal_id=principal,
        project_ids=portfolio.project_ids,
        query=query or ConstraintListQuery(scope=ConstraintListScope.ALL, limit=50),
        now=NOW,
    )


def _page(
    repository: SqlConstraintManagementRepository,
    portfolio: _Portfolio,
    *,
    query: ConstraintListQuery | None = None,
    principal: str = PRINCIPAL_A,
) -> ConstraintListPage:
    """Just the Register page, for the assertions that are about rows."""
    return _portfolio_page(repository, portfolio, query=query, principal=principal).page


def _overview(
    repository: SqlConstraintManagementRepository,
    portfolio: _Portfolio,
    *,
    principal: str = PRINCIPAL_A,
) -> ConstraintPortfolioOverview:
    return SERVICE.read_portfolio_overview(
        repository,  # type: ignore[arg-type]
        principal_id=principal,
        project_ids=portfolio.project_ids,
        now=NOW,
    )


@contextmanager
def _composed(engine: Engine, url: str) -> Iterator[ApplicationService]:
    """The real entry point, with its Constraint transaction on the counted engine.

    The gateway unit of work and the audit sink are given a **second** engine
    over the same catalog, so `_counted(engine)` measures the Constraint plane's
    own statements and nothing else. That is deliberate and it is the claim being
    made: the bound this package exists to hold is on the portfolio read path,
    and an audit insert is neither on it nor a function of how many Projects the
    Principal owns. Mixing the two onto one engine would let an unrelated
    envelope change move a number that is supposed to be a property of the read.
    """
    side = create_database_engine(url)
    try:
        audit = SqlAlchemyAuditSink(side)
        yield ApplicationService(
            unit_of_work=lambda: SqlAlchemyUnitOfWork(side, audit=audit),
            clock=lambda: NOW,
            limits=DEFAULT_LIMITS,
            constraint_management_unit_of_work=(
                lambda: SqlAlchemyConstraintManagementUnitOfWork(engine)
            ),
        )
    finally:
        side.dispose()


def _invoke(service: ApplicationService, command: Command) -> ResponseEnvelope:
    metadata = RequestMetadata(
        request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
        capability=command.capability,
        purpose=Purpose.CONSTRAINT_READ,
        principal_id=ACTING.principal_id,
        requested_at=NOW,
    )
    return service.invoke(metadata, command, principal=ACTING)


def _seed_committed(
    engine: Engine, *, tag: str, projects_wanted: int, rows_per_project: int, first: int = 1
) -> None:
    """Seed one Principal's portfolio and commit it, so the service can read it.

    A composed invocation opens its own transaction, so it cannot see rows still
    held in an uncommitted one. Every composed measurement below therefore seeds
    through this helper rather than inside the block it measures.
    """
    with engine.begin() as connection:
        _seed_portfolio(
            connection,
            SqlConstraintManagementRepository(connection),
            principal=PRINCIPAL_A,
            tag=tag,
            projects_wanted=projects_wanted,
            rows_per_project=rows_per_project,
            zones=(ZONE_EAST, ZONE_TOKYO),
            first_constraint=first,
        )


# --- The statement-count bound, and its invariance ----------------------------


@pytest.mark.parametrize(
    ("projects_wanted", "rows_per_project"),
    [(1, 1), (1, 60), (5, 1), (5, 12), (12, 1), (12, 8)],
)
def test_a_portfolio_page_costs_exactly_six_statements_however_many_projects_it_spans(
    migrated_engine: Engine, projects_wanted: int, rows_per_project: int
) -> None:
    """The N+1 proof: the cost is a function of the read, not of the portfolio.

    Six statements for one Project and six for twelve. A read that resolved a
    calendar, fetched Categories or counted sync facts per Project would scale
    with `projects_wanted` and fail here at the first arrangement past one.
    """
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="a",
            projects_wanted=projects_wanted,
            rows_per_project=rows_per_project,
            zones=(ZONE_EAST, ZONE_TOKYO),
        )
        with _counted(migrated_engine) as statements:
            page = _page(repository, portfolio)
        assert page.entries
        assert len(statements) == PORTFOLIO_LIST_STATEMENTS


def test_the_portfolio_page_cost_is_identical_across_every_project_count(
    migrated_engine: Engine,
) -> None:
    """Stated as an equality as well as a number, because the equality is the guard."""
    measured: list[int] = []
    for index, projects_wanted in enumerate((1, 5, 12)):
        with migrated_engine.begin() as connection:
            repository = SqlConstraintManagementRepository(connection)
            portfolio = _seed_portfolio(
                connection,
                repository,
                principal=PRINCIPAL_A,
                tag=f"c{index}",
                projects_wanted=projects_wanted,
                rows_per_project=4,
                zones=(ZONE_EAST, ZONE_TOKYO),
                first_constraint=1 + index * 1000,
            )
            with _counted(migrated_engine) as statements:
                _page(repository, portfolio)
            measured.append(len(statements))
            connection.rollback()
    assert measured == [PORTFOLIO_LIST_STATEMENTS] * 3
    assert len(set(measured)) == 1


def test_the_portfolio_page_cost_does_not_move_when_the_register_grows(
    migrated_engine: Engine,
) -> None:
    """Five Projects of three rows and five Projects of eighty cost the same."""
    measured: list[int] = []
    for index, rows_per_project in enumerate((3, 80)):
        with migrated_engine.begin() as connection:
            repository = SqlConstraintManagementRepository(connection)
            portfolio = _seed_portfolio(
                connection,
                repository,
                principal=PRINCIPAL_A,
                tag=f"g{index}",
                projects_wanted=5,
                rows_per_project=rows_per_project,
                zones=(ZONE_EAST, ZONE_TOKYO),
                first_constraint=1 + index * 5000,
            )
            with _counted(migrated_engine) as statements:
                _page(repository, portfolio)
            measured.append(len(statements))
            connection.rollback()
    assert measured == [PORTFOLIO_LIST_STATEMENTS, PORTFOLIO_LIST_STATEMENTS]


def test_the_entity_label_read_is_one_more_statement_for_the_whole_portfolio(
    migrated_engine: Engine,
) -> None:
    """A bare ENTITY party costs one statement for the page, not one per Project."""
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        connection.execute(
            insert(entities).values(
                entity_id=ENTITY_BARE,
                principal_id=PRINCIPAL_A,
                entity_type="organization",
                canonical_name="sample glazing",
                display_name="Sample Glazing",
                status="active",
                created_at=T0,
                updated_at=T0,
                version=1,
            )
        )
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="e",
            projects_wanted=7,
            rows_per_project=3,
            zones=(ZONE_EAST, ZONE_TOKYO),
            bare_entity_party=True,
        )
        with _counted(migrated_engine) as statements:
            page = _page(repository, portfolio)
        assert len(statements) == PORTFOLIO_LIST_STATEMENTS_WITH_ENTITY_LABELS
        assert all(entry.bic[0].display_label == "Sample Glazing" for entry in page.entries)


@pytest.mark.parametrize(
    ("projects_wanted", "rows_per_project"),
    [(1, 1), (1, 60), (5, 4), (12, 1), (12, 8)],
)
def test_the_portfolio_overview_costs_exactly_four_statements_however_many_projects(
    migrated_engine: Engine, projects_wanted: int, rows_per_project: int
) -> None:
    """One grouped aggregate, whatever the portfolio spans. Never one per Project."""
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="o",
            projects_wanted=projects_wanted,
            rows_per_project=rows_per_project,
            zones=(ZONE_EAST, ZONE_TOKYO),
        )
        with _counted(migrated_engine) as statements:
            overview = _overview(repository, portfolio)
        assert len(overview.projects) == projects_wanted
        assert len(statements) == PORTFOLIO_OVERVIEW_STATEMENTS


def test_the_portfolio_overview_cost_is_identical_across_every_project_count(
    migrated_engine: Engine,
) -> None:
    measured: list[int] = []
    for index, projects_wanted in enumerate((1, 5, 12)):
        with migrated_engine.begin() as connection:
            repository = SqlConstraintManagementRepository(connection)
            portfolio = _seed_portfolio(
                connection,
                repository,
                principal=PRINCIPAL_A,
                tag=f"v{index}",
                projects_wanted=projects_wanted,
                rows_per_project=5,
                zones=(ZONE_EAST, ZONE_TOKYO),
                first_constraint=1 + index * 900,
            )
            with _counted(migrated_engine) as statements:
                _overview(repository, portfolio)
            measured.append(len(statements))
            connection.rollback()
    assert measured == [PORTFOLIO_OVERVIEW_STATEMENTS] * 3
    assert len(set(measured)) == 1


# --- The composed cost, which is the one a caller pays ------------------------


@pytest.mark.parametrize(
    ("projects_wanted", "rows_per_project"),
    [(1, 1), (1, 60), (5, 1), (5, 12), (12, 1), (12, 8)],
)
def test_a_composed_portfolio_page_costs_exactly_seven_statements(
    migrated_engine: Engine, cloned_database_url: str, projects_wanted: int, rows_per_project: int
) -> None:
    """Seven, not six, and not seven-plus-one-per-Project.

    The read service's six plus the single canonical `list_projects` the handler
    issues to decide the Project set. A handler that asked the Project
    repository one question per Project — `get_project` in a loop, an ownership
    re-check, a per-Project settings probe — would measure
    ``7 + projects_wanted`` and fail here at every arrangement, including the
    one-Project one.

    Seven counts the Constraint plane's own transaction only. The gateway unit
    of work and the audit sink run on `_composed`'s second engine and are not in
    this figure — it is what the portfolio read costs, not what the invocation
    costs the database.
    """
    _seed_committed(
        migrated_engine,
        tag="ca",
        projects_wanted=projects_wanted,
        rows_per_project=rows_per_project,
    )
    with (
        _composed(migrated_engine, cloned_database_url) as service,
        _counted(migrated_engine) as statements,
    ):
        envelope = _invoke(service, ListPortfolioConstraints())
    assert envelope.error is None, envelope.error
    assert len(statements) == COMPOSED_PORTFOLIO_LIST_STATEMENTS


def test_the_composed_portfolio_page_cost_is_identical_across_every_project_count(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The invariance, stated at the layer that is actually paid for.

    A ceiling would not catch a per-Project read at handler level; an equality
    across one, five and twelve Projects does, and it is the assertion that
    would fail first.
    """
    measured: list[int] = []
    with _composed(migrated_engine, cloned_database_url) as service:
        for index, projects_wanted in enumerate((1, 5, 12)):
            _seed_committed(
                migrated_engine,
                tag=f"cb{index}",
                projects_wanted=projects_wanted,
                rows_per_project=4,
                first=1 + index * 2000,
            )
            with _counted(migrated_engine) as statements:
                envelope = _invoke(service, ListPortfolioConstraints())
            assert envelope.error is None, envelope.error
            measured.append(len(statements))
    assert measured == [COMPOSED_PORTFOLIO_LIST_STATEMENTS] * 3
    assert len(set(measured)) == 1


@pytest.mark.parametrize(
    ("projects_wanted", "rows_per_project"),
    [(1, 1), (1, 60), (5, 1), (5, 12), (12, 1), (12, 8)],
)
def test_a_composed_portfolio_overview_costs_exactly_five_statements(
    migrated_engine: Engine, cloned_database_url: str, projects_wanted: int, rows_per_project: int
) -> None:
    """The overview's four plus the same one Project enumeration.

    Five on the Constraint plane's own transaction, excluding the gateway unit
    of work and the audit sink exactly as the page's seven does.
    """
    _seed_committed(
        migrated_engine,
        tag="cc",
        projects_wanted=projects_wanted,
        rows_per_project=rows_per_project,
    )
    with (
        _composed(migrated_engine, cloned_database_url) as service,
        _counted(migrated_engine) as statements,
    ):
        envelope = _invoke(service, ReadPortfolioConstraintOverview())
    assert envelope.error is None, envelope.error
    assert len(statements) == COMPOSED_PORTFOLIO_OVERVIEW_STATEMENTS


def test_the_composed_portfolio_overview_cost_is_identical_across_every_project_count(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    measured: list[int] = []
    with _composed(migrated_engine, cloned_database_url) as service:
        for index, projects_wanted in enumerate((1, 5, 12)):
            _seed_committed(
                migrated_engine,
                tag=f"cd{index}",
                projects_wanted=projects_wanted,
                rows_per_project=5,
                first=1 + index * 2000,
            )
            with _counted(migrated_engine) as statements:
                envelope = _invoke(service, ReadPortfolioConstraintOverview())
            assert envelope.error is None, envelope.error
            measured.append(len(statements))
    assert measured == [COMPOSED_PORTFOLIO_OVERVIEW_STATEMENTS] * 3
    assert len(set(measured)) == 1


def test_the_composed_cost_is_the_read_services_cost_plus_the_project_enumeration(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The two layers measured side by side, so the gap is stated rather than assumed.

    Both sides are the Constraint plane's own transaction; neither includes the
    gateway unit of work or the audit sink, so the difference is the Project
    enumeration and nothing else.

    This is what makes the composed figures more than a second copy of the read
    service's: the difference between them is required to be exactly one
    statement, and that statement is required to be the canonical Project
    enumeration. A handler that enumerated Projects twice, or once per Project,
    changes the difference and fails here even if somebody also updated the
    composed constants.
    """
    _seed_committed(migrated_engine, tag="ce", projects_wanted=6, rows_per_project=3)
    with _composed(migrated_engine, cloned_database_url) as service:
        with _counted(migrated_engine) as composed_list:
            _invoke(service, ListPortfolioConstraints())
        with _counted(migrated_engine) as composed_overview:
            _invoke(service, ReadPortfolioConstraintOverview())
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _Portfolio(tuple(_project_id("ce", index + 1) for index in range(6)))
        with _counted(migrated_engine) as bare_list:
            _page(repository, portfolio)
        with _counted(migrated_engine) as bare_overview:
            _overview(repository, portfolio)
    assert len(composed_list) - len(bare_list) == 1
    assert len(composed_overview) - len(bare_overview) == 1
    # And the extra statement is the Project enumeration itself, asked once.
    # Counted by what it reads rather than by differencing the two lists: the
    # composed call and the bare one build their Register statement from
    # different defaults, so the texts differ for a reason that is not the gap
    # being measured.
    for composed in (composed_list, composed_overview):
        assert sum("FROM knowledge.projects" in text for text in composed) == 1
    for bare in (bare_list, bare_overview):
        assert not any("FROM knowledge.projects" in text for text in bare)


def test_no_portfolio_read_statement_takes_a_row_lock(migrated_engine: Engine) -> None:
    """A read is a read. Nothing here composes `FOR UPDATE`."""
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="l",
            projects_wanted=4,
            rows_per_project=3,
        )
        with _counted(migrated_engine) as statements:
            _page(repository, portfolio)
            _overview(repository, portfolio)
        assert statements
        assert not any("FOR UPDATE" in statement.upper() for statement in statements)


# --- Per-Project calendars, against real SQL ---------------------------------


def _two_zone_world(
    connection: Connection,
) -> tuple[SqlConstraintManagementRepository, _Portfolio]:
    """Two Projects, two zones, one Due Date that falls either side of the turn."""
    repository = SqlConstraintManagementRepository(connection)
    portfolio = _seed_portfolio(
        connection,
        repository,
        principal=PRINCIPAL_A,
        tag="z",
        projects_wanted=2,
        rows_per_project=0,
        zones=(ZONE_EAST, ZONE_TOKYO),
    )
    east, tokyo = portfolio.project_ids
    for ordinal, (project, category) in enumerate(
        ((east, _category_id("z", 1)), (tokyo, _category_id("z", 2))), start=1
    ):
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=_constraint_id(500 + ordinal),
                project_id=project,
                category_id=category,
                constraint_code=f"{ordinal}.001",
                due_date=date(2026, 9, 14),
                date_identified=date(2026, 9, 10),
            ),
        )
    return repository, portfolio


def test_one_instant_is_two_project_dates_and_the_same_due_date_classifies_apart(
    migrated_engine: Engine,
) -> None:
    """The per-Project calendar, proved through the real statement.

    New York is still on the Due Date at this instant, so its row is Due Soon;
    Tokyo has turned over, so the identical row is Overdue. A single shared
    calendar would give both rows the same answer.
    """
    with migrated_engine.begin() as connection:
        repository, portfolio = _two_zone_world(connection)
        east, tokyo = portfolio.project_ids
        page = _page(repository, portfolio)
        by_project = {entry.project_id: entry for entry in page.entries}
        assert (by_project[east].is_overdue, by_project[east].is_due_soon) == (False, True)
        assert (by_project[tokyo].is_overdue, by_project[tokyo].is_due_soon) == (True, False)


def test_the_grouped_aggregate_counts_each_project_against_its_own_date(
    migrated_engine: Engine,
) -> None:
    """The same claim for the overview, so counts and rows cannot disagree."""
    with migrated_engine.begin() as connection:
        repository, portfolio = _two_zone_world(connection)
        east, tokyo = portfolio.project_ids
        overview = _overview(repository, portfolio)
        counted = {entry.project_id: entry for entry in overview.projects}
        assert counted[east].project_today == EAST_TODAY
        assert counted[tokyo].project_today == TOKYO_TODAY
        assert counted[east].project_timezone == ZONE_EAST
        assert counted[tokyo].project_timezone == ZONE_TOKYO
        assert (counted[east].overdue, counted[east].due_soon) == (0, 1)
        assert (counted[tokyo].overdue, counted[tokyo].due_soon) == (1, 0)


def test_the_overdue_quick_filter_is_applied_on_each_rows_own_project_calendar(
    migrated_engine: Engine,
) -> None:
    """A date-dependent predicate in the WHERE clause, not just in the projection."""
    with migrated_engine.begin() as connection:
        repository, portfolio = _two_zone_world(connection)
        _, tokyo = portfolio.project_ids
        page = _page(
            repository,
            portfolio,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL, overdue=True, limit=50),
        )
        assert [entry.project_id for entry in page.entries] == [tokyo]


def test_a_project_with_no_constraint_calendar_contributes_nothing_to_either_read(
    migrated_engine: Engine,
) -> None:
    """An owned but unenrolled Project is omitted, and both reads say how many.

    PC-CM-RUN01-WP06, as the operator's ruling settled it: omitted, not fatal,
    and disclosed by a count.
    """
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="u",
            projects_wanted=2,
            rows_per_project=2,
        )
        unconfigured = _project_id("u", 99)
        _seed_project(connection, PRINCIPAL_A, unconfigured)
        widened = _Portfolio((*portfolio.project_ids, unconfigured))
        answer = _portfolio_page(repository, widened)
        overview = _overview(repository, widened)
        assert unconfigured not in {entry.project_id for entry in answer.page.entries}
        assert [entry.project_id for entry in overview.projects] == list(portfolio.project_ids)
        assert len(answer.page.entries) == 4
        assert answer.omitted_projects == 1
        assert overview.omitted_projects == 1


def test_a_stored_zone_that_will_not_load_is_omitted_and_counted_not_fatal(
    migrated_engine: Engine,
) -> None:
    """The ruling's second member, proved against a row PostgreSQL actually holds.

    `Mars/Olympus_Mons` satisfies every stored CHECK on `timezone_name` — it is
    non-blank, inside the length bound and carries no whitespace — and
    `zoneinfo` still cannot load it. That is the reachable shape of a broken
    calendar, and an earlier build failed the entire portfolio on it: an
    anonymous refusal that took the healthy Projects down with it and named no
    Project to fix. Both healthy Projects answer, and the count says one was
    left out.
    """
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="z",
            projects_wanted=2,
            rows_per_project=2,
        )
        broken = _project_id("z", 98)
        _seed_project(connection, PRINCIPAL_A, broken)
        repository.insert_project_settings(
            PRINCIPAL_A, _settings(PRINCIPAL_A, broken, "Mars/Olympus_Mons")
        )
        widened = _Portfolio((*portfolio.project_ids, broken))
        answer = _portfolio_page(repository, widened)
        overview = _overview(repository, widened)
        assert broken not in {entry.project_id for entry in answer.page.entries}
        assert len(answer.page.entries) == 4
        assert answer.omitted_projects == 1
        assert [entry.project_id for entry in overview.projects] == list(portfolio.project_ids)
        assert overview.omitted_projects == 1


def test_both_members_of_cannot_contribute_are_counted_in_one_figure(
    migrated_engine: Engine,
) -> None:
    """One class, one count. A build that counted only one member understates it."""
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="b",
            projects_wanted=1,
            rows_per_project=1,
        )
        unconfigured = _project_id("b", 97)
        broken = _project_id("b", 98)
        for project in (unconfigured, broken):
            _seed_project(connection, PRINCIPAL_A, project)
        repository.insert_project_settings(
            PRINCIPAL_A, _settings(PRINCIPAL_A, broken, "Mars/Olympus_Mons")
        )
        widened = _Portfolio((*portfolio.project_ids, unconfigured, broken))
        assert _portfolio_page(repository, widened).omitted_projects == 2
        assert _overview(repository, widened).omitted_projects == 2


def test_a_project_in_scope_with_no_constraints_is_counted_as_zero_not_dropped(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="n",
            projects_wanted=3,
            rows_per_project=0,
        )
        overview = _overview(repository, portfolio)
        assert [entry.project_id for entry in overview.projects] == list(portfolio.project_ids)
        assert all(entry.total_open == 0 for entry in overview.projects)


# --- Cross-Principal isolation ------------------------------------------------


def _two_principal_world(
    connection: Connection,
) -> tuple[SqlConstraintManagementRepository, _Portfolio, _Portfolio]:
    repository = SqlConstraintManagementRepository(connection)
    mine = _seed_portfolio(
        connection,
        repository,
        principal=PRINCIPAL_A,
        tag="m",
        projects_wanted=3,
        rows_per_project=2,
        zones=(ZONE_EAST, ZONE_TOKYO),
        first_constraint=1,
    )
    theirs = _seed_portfolio(
        connection,
        repository,
        principal=PRINCIPAL_B,
        tag="t",
        projects_wanted=3,
        rows_per_project=2,
        zones=(ZONE_EAST, ZONE_TOKYO),
        first_constraint=2001,
    )
    return repository, mine, theirs


def test_a_portfolio_page_never_returns_another_principals_rows(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository, mine, _ = _two_principal_world(connection)
        page = _page(repository, mine)
        assert len(page.entries) == 6
        assert {entry.project_id for entry in page.entries} == set(mine.project_ids)


def test_naming_another_principals_projects_yields_nothing_rather_than_their_rows(
    migrated_engine: Engine,
) -> None:
    """A foreign Project has no calendar in this partition, so it is simply absent.

    The answer is identical to an owned Project that was never enrolled, which
    is the nondisclosure posture the plane requires: nothing in the result tells
    a caller whether the Project they named exists, is theirs, or is merely
    unconfigured (decision PC-CM-D02).
    """
    with migrated_engine.begin() as connection:
        repository, _, theirs = _two_principal_world(connection)
        page = _page(repository, theirs)
        overview = _overview(repository, theirs)
        assert page.entries == ()
        assert page.next_cursor is None
        assert overview.projects == ()


def test_a_mixed_project_set_returns_only_the_callers_own_projects(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository, mine, theirs = _two_principal_world(connection)
        mixed = _Portfolio((*mine.project_ids, *theirs.project_ids))
        page = _page(repository, mixed)
        overview = _overview(repository, mixed)
        assert {entry.project_id for entry in page.entries} == set(mine.project_ids)
        assert [entry.project_id for entry in overview.projects] == sorted(mine.project_ids)


def test_each_principal_sees_only_their_own_portfolio_counts(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository, mine, theirs = _two_principal_world(connection)
        ours = _overview(repository, mine)
        yours = SERVICE.read_portfolio_overview(
            repository,  # type: ignore[arg-type]
            principal_id=PRINCIPAL_B,
            project_ids=theirs.project_ids,
            now=NOW,
        )
        assert sum(entry.total_open for entry in ours.projects) == 6
        assert sum(entry.total_open for entry in yours.projects) == 6
        assert {entry.project_id for entry in ours.projects}.isdisjoint(
            {entry.project_id for entry in yours.projects}
        )


# --- The omitted-Project count is a pure function of the caller's own set -----
#
# The count is itself a section-14 surface: a figure that moved with another
# Principal's data would rebuild the existence oracle by a different route. What
# the tests below prove against real SQL is that it does not, and that it *does*
# move when the caller's own Projects change in exactly the same way — a control
# without which "unchanged" would be consistent with the count being frozen.


def _unreachable_projects(
    connection: Connection,
    repository: SqlConstraintManagementRepository,
    *,
    principal: str,
    tag: str,
    unconfigured: int,
    broken: int,
) -> tuple[str, ...]:
    """Projects that cannot contribute.

    `unconfigured` of them have no settings row; `broken` of them have one whose
    stored zone `zoneinfo` cannot load.
    """
    created: list[str] = []
    for index in range(unconfigured):
        project = _project_id(tag, 900 + index)
        _seed_project(connection, principal, project)
        created.append(project)
    for index in range(broken):
        project = _project_id(tag, 950 + index)
        _seed_project(connection, principal, project)
        repository.insert_project_settings(
            principal, _settings(principal, project, "Mars/Olympus_Mons")
        )
        created.append(project)
    return tuple(created)


def test_another_principals_unusable_projects_do_not_move_the_callers_count(
    migrated_engine: Engine,
) -> None:
    """The oracle proof. Seeded, not argued.

    Principal B is given six Projects that cannot contribute — three never
    enrolled, three enrolled against a zone that will not load — which is the
    exact shape that produces a count for their owner. Principal A's count is
    measured before and after those rows exist and is required to be identical.

    The settings statement is Principal-scoped in the adapter and the count is
    accumulated from the owned set the read was handed, never by subtracting one
    result from another, so there is no path for B's rows to reach it. This test
    is what makes that a measured fact rather than a reading of the code.
    """
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        mine = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="o",
            projects_wanted=2,
            rows_per_project=2,
        )
        my_unusable = _unreachable_projects(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="o",
            unconfigured=1,
            broken=1,
        )
        scope = _Portfolio((*mine.project_ids, *my_unusable))
        before = _portfolio_page(repository, scope).omitted_projects
        before_overview = _overview(repository, scope).omitted_projects
        assert before == 2

        _unreachable_projects(
            connection,
            repository,
            principal=PRINCIPAL_B,
            tag="q",
            unconfigured=3,
            broken=3,
        )
        assert _portfolio_page(repository, scope).omitted_projects == before
        assert _overview(repository, scope).omitted_projects == before_overview

        # The control: the caller's *own* set moving the same way does move it.
        more_of_mine = _unreachable_projects(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="r",
            unconfigured=1,
            broken=1,
        )
        widened = _Portfolio((*scope.project_ids, *more_of_mine))
        assert _portfolio_page(repository, widened).omitted_projects == before + 2
        assert _overview(repository, widened).omitted_projects == before_overview + 2


def test_a_portfolio_command_admits_no_project_so_the_count_cannot_be_probed(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The structural half: nothing a caller sends can reach the Project set.

    A count a caller could move by *naming* something outside their partition
    would be an oracle whatever the figure is called. The three portfolio
    commands carry no Project field at all — they are frozen dataclasses and an
    unknown keyword is a refusal — so the set is always whatever
    `ApplicationService._portfolio_projects` read from the canonical
    Principal-scoped repository, and a caller has no input to the count beyond
    owning Projects. Asserted here rather than at the read service, because the
    read service takes a Project set as an argument and only the composed path
    decides where that argument comes from.
    """
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="pa",
            projects_wanted=1,
            rows_per_project=1,
        )
        _unreachable_projects(
            connection, repository, principal=PRINCIPAL_A, tag="pa", unconfigured=2, broken=0
        )
        theirs = _unreachable_projects(
            connection, repository, principal=PRINCIPAL_B, tag="pb", unconfigured=4, broken=2
        )
    for command_type in (
        ListPortfolioConstraints,
        ReadPortfolioConstraintOverview,
    ):
        with pytest.raises(TypeError):
            command_type(project_id=theirs[0])  # type: ignore[call-arg]
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, ListPortfolioConstraints())
    assert _result(envelope)["omitted_projects"] == 2
    rendered = envelope.model_dump_json()
    for project in theirs:
        assert project not in rendered


# --- Walking a partial portfolio to exhaustion --------------------------------
#
# Nothing used to pin the end-to-end multi-page walk: "the disclosure stays
# correct on every page" held by construction only. The ruling makes it
# load-bearing, because a partiality that no cursor can repair must survive to
# the terminal page or a caller who pages to the end is told they have seen the
# whole portfolio.
#
# These run against **real SQL through the composed `ApplicationService`**, and
# that is the tier rather than a preference. The unit fake models no keyset
# cursor at all — it filters by the spec's Project set and slices at
# `fetch_limit` — so a "walk" driven through it would return page one forever
# and every assertion about page two would be vacuous. Here the cursor is one
# the read service issued over stored rows and the next statement genuinely
# continues from it.


def _walk(service: ApplicationService, *, limit: int, pages: int = 50) -> list[ResponseEnvelope]:
    """Every page of a portfolio listing, in order, to the terminal one."""
    walked: list[ResponseEnvelope] = []
    cursor: str | None = None
    for _ in range(pages):
        envelope = _invoke(service, ListPortfolioConstraints(limit=limit, cursor=cursor))
        assert envelope.error is None, envelope.error
        walked.append(envelope)
        assert envelope.disclosure is not None
        truncation = envelope.disclosure.truncation
        cursor = None if truncation is None else truncation.next_cursor
        if cursor is None:
            return walked
    raise AssertionError("the portfolio walk did not terminate")


def _result(envelope: ResponseEnvelope) -> dict[str, Any]:
    """The success payload as the wire carries it."""
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    rendered = envelope.model_dump(mode="json")["result"]
    assert isinstance(rendered, dict)
    return rendered


def _rows_of(envelope: ResponseEnvelope) -> list[str]:
    rows = _result(envelope)["constraints"]
    assert isinstance(rows, list)
    return [str(row["constraint_id"]) for row in rows]


def test_a_capped_portfolio_stays_disclosed_on_every_page_including_the_last(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The exhaustion walk. Three pages, and the cap is still stated on the third.

    `MAX_PORTFOLIO_PROJECTS + 1` owned Projects, so the cap is reached and rows
    beyond it are unreachable from any page. The walk is non-vacuous: each page
    holds different rows, the union has no gap and no repeat, and the last page
    is the one where the rows run out rather than where a loop bound did.

    On every page the truncation is stated and names the Project cap. On the
    pages that fill, a usable cursor is issued and
    `LISTING_HAS_NO_CONTINUATION` is absent, because it would be false. On the
    terminal page there is no cursor, the truncation *remains*, and the
    limitation is emitted — which is the invariant the previous cycle
    established: it holds exactly when the emitted truncation carries no
    continuation.
    """
    _seed_committed(
        migrated_engine,
        tag="wa",
        projects_wanted=MAX_PORTFOLIO_PROJECTS + 1,
        rows_per_project=1,
    )
    with _composed(migrated_engine, cloned_database_url) as service:
        walked = _walk(service, limit=40)
    assert len(walked) == 3
    seen: list[str] = []
    for index, envelope in enumerate(walked):
        assert envelope.disclosure is not None
        truncation = envelope.disclosure.truncation
        assert truncation is not None and truncation.is_truncated is True
        assert truncation.reason == "portfolio_project_limit_reached"
        assert _result(envelope)["omitted_projects"] == 0
        limitations = envelope.disclosure.limitations
        terminal = index == len(walked) - 1
        assert (truncation.next_cursor is None) is terminal
        assert (Limitation.LISTING_HAS_NO_CONTINUATION.value in limitations) is terminal
        seen.extend(_rows_of(envelope))
    # Exactly the rows inside the cap, once each. The Project past the cap
    # contributed none, which is what the standing truncation is about.
    assert len(seen) == MAX_PORTFOLIO_PROJECTS
    assert len(set(seen)) == MAX_PORTFOLIO_PROJECTS


def test_an_omitting_portfolio_reports_the_same_count_on_every_page_of_the_walk(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The omission does not depend on the page, so it does not fade across a walk.

    Seven Projects that contribute and three that cannot — one never enrolled,
    two enrolled against a zone that will not load. The count is three on the
    first page, on the middle page and on the terminal page, and the reason
    names the omission throughout because the cap is not reached here.

    The middle page is what makes this more than a restatement of the
    single-page test: a build that derived the count from the rows in hand, or
    reset it once a cursor was taken, passes page one and fails here.
    """
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="wb",
            projects_wanted=7,
            rows_per_project=6,
            zones=(ZONE_EAST, ZONE_TOKYO),
        )
        _unreachable_projects(
            connection, repository, principal=PRINCIPAL_A, tag="wb", unconfigured=1, broken=2
        )
    with _composed(migrated_engine, cloned_database_url) as service:
        walked = _walk(service, limit=20)
    assert len(walked) == 3
    seen: list[str] = []
    for index, envelope in enumerate(walked):
        assert envelope.disclosure is not None
        truncation = envelope.disclosure.truncation
        assert truncation is not None and truncation.is_truncated is True
        assert truncation.reason == "portfolio_projects_omitted"
        assert _result(envelope)["omitted_projects"] == 3
        terminal = index == len(walked) - 1
        assert (truncation.next_cursor is None) is terminal
        assert (
            Limitation.LISTING_HAS_NO_CONTINUATION.value in envelope.disclosure.limitations
        ) is terminal
        seen.extend(_rows_of(envelope))
    assert len(seen) == 42
    assert len(set(seen)) == 42


def test_an_unpartial_portfolio_walk_ends_untruncated_rather_than_standing_open(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The control the two walks above need.

    Without it, "truncated on the last page" would be consistent with this
    surface never reporting a complete answer at all. Nothing is capped and
    nothing is omitted here, so the terminal page is plainly untruncated, issues
    no cursor, emits no limitation, and still publishes the count as zero.
    """
    _seed_committed(migrated_engine, tag="wc", projects_wanted=4, rows_per_project=5)
    with _composed(migrated_engine, cloned_database_url) as service:
        walked = _walk(service, limit=8)
    assert len(walked) == 3
    for index, envelope in enumerate(walked):
        assert envelope.disclosure is not None
        truncation = envelope.disclosure.truncation
        assert _result(envelope)["omitted_projects"] == 0
        if index < len(walked) - 1:
            assert truncation is not None and truncation.is_truncated is True
            assert truncation.reason == "page_size_reached"
            assert truncation.next_cursor is not None
        else:
            assert truncation is None or truncation.is_truncated is False
            assert (
                Limitation.LISTING_HAS_NO_CONTINUATION.value not in envelope.disclosure.limitations
            )


# --- Paging, sorting and searching across Projects ---------------------------


def test_keyset_paging_walks_a_cross_project_result_set_without_a_gap_or_a_repeat(
    migrated_engine: Engine,
) -> None:
    """`constraint_id` is a global primary key, so the keyset stays total across Projects."""
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="p",
            projects_wanted=4,
            rows_per_project=5,
            zones=(ZONE_EAST, ZONE_TOKYO),
        )
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(20):
            page = _page(
                repository,
                portfolio,
                query=ConstraintListQuery(
                    scope=ConstraintListScope.ALL,
                    sort=ConstraintSort.CODE,
                    limit=3,
                    cursor=cursor,
                ),
            )
            seen.extend(entry.constraint_id for entry in page.entries)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == 20
        assert len(set(seen)) == 20


def test_a_descending_sort_across_projects_reverses_the_ascending_order_exactly(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="s",
            projects_wanted=3,
            rows_per_project=4,
            zones=(ZONE_EAST, ZONE_TOKYO),
        )
        ascending = _page(
            repository,
            portfolio,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL, sort=ConstraintSort.CODE, limit=50
            ),
        )
        descending = _page(
            repository,
            portfolio,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL,
                sort=ConstraintSort.CODE,
                direction=SortDirection.DESC,
                limit=50,
            ),
        )
        forward = [entry.constraint_id for entry in ascending.entries]
        backward = [entry.constraint_id for entry in descending.entries]
        assert len(forward) == 12
        assert backward == list(reversed(forward))


def test_a_search_term_narrows_the_whole_portfolio_and_never_one_project_of_it(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="q",
            projects_wanted=3,
            rows_per_project=0,
            zones=(ZONE_EAST, ZONE_TOKYO),
        )
        for ordinal, project in enumerate(portfolio.project_ids, start=1):
            repository.insert_constraint(
                PRINCIPAL_A,
                _constraint(
                    constraint_id=_constraint_id(700 + ordinal),
                    project_id=project,
                    category_id=_category_id("q", ordinal),
                    constraint_code=f"{ordinal}.001",
                    description=(
                        "Louvre schedule pending" if ordinal < 3 else "Switchgear submittal"
                    ),
                ),
            )
        page = _page(
            repository,
            portfolio,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL, search_text="louvre", limit=50
            ),
        )
        assert len(page.entries) == 2
        assert {entry.project_id for entry in page.entries} == set(portfolio.project_ids[:2])


def test_a_search_over_a_portfolio_costs_the_same_six_statements(
    migrated_engine: Engine,
) -> None:
    """`portfolio_search` is `portfolio_list` with a term, including in its cost."""
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        portfolio = _seed_portfolio(
            connection,
            repository,
            principal=PRINCIPAL_A,
            tag="h",
            projects_wanted=9,
            rows_per_project=3,
            zones=(ZONE_EAST, ZONE_TOKYO),
        )
        with _counted(migrated_engine) as statements:
            _page(
                repository,
                portfolio,
                query=ConstraintListQuery(
                    scope=ConstraintListScope.ALL, search_text="switchgear", limit=50
                ),
            )
        assert len(statements) == PORTFOLIO_LIST_STATEMENTS


# --- Phase 0: ACTIVE-only Project scope and `project_name` (IMPL-1-PHASE0) ---
#
# `_portfolio_projects` is what decides which Projects one portfolio read
# spans and, from the same statement, the name each of them carries onto its
# own rows. Both are proved here through the composed `ApplicationService`
# against real SQL, because neither is visible to the read service the rest of
# this module exercises directly: the read service takes a Project set and a
# name mapping as given, and never asks the Project repository anything.


def _seed_state_project(
    connection: Connection,
    repository: SqlConstraintManagementRepository,
    *,
    principal: str,
    project: str,
    name: str,
    state: str,
    category: str,
    prefix: str,
    constraint_id: str,
) -> None:
    """One Project in the given lifecycle state, configured and holding one row."""
    _seed_project(connection, principal, project, state=state, name=name)
    repository.insert_project_settings(principal, _settings(principal, project, ZONE_EAST))
    repository.insert_category(principal, _category(category, principal, project, prefix))
    repository.insert_constraint(
        principal,
        _constraint(
            constraint_id=constraint_id,
            principal_id=principal,
            project_id=project,
            category_id=category,
            constraint_code="1.001",
        ),
    )


def _seed_active_on_hold_and_closed_committed(engine: Engine, *, tag: str) -> dict[str, str]:
    """One ACTIVE, one ON_HOLD and one CLOSED Project, each holding one row.

    Committed, for the reason `_seed_committed` states: a composed invocation
    opens its own transaction and cannot see rows a still-open one is holding.
    """
    active = _project_id(tag, 1)
    on_hold = _project_id(tag, 2)
    closed = _project_id(tag, 3)
    with engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        _seed_state_project(
            connection,
            repository,
            principal=PRINCIPAL_A,
            project=active,
            name="Active Tower",
            state="active",
            category=_category_id(tag, 1),
            prefix="ACT",
            constraint_id=_constraint_id(9001),
        )
        _seed_state_project(
            connection,
            repository,
            principal=PRINCIPAL_A,
            project=on_hold,
            name="Paused Annex",
            state="on_hold",
            category=_category_id(tag, 2),
            prefix="ONH",
            constraint_id=_constraint_id(9002),
        )
        _seed_state_project(
            connection,
            repository,
            principal=PRINCIPAL_A,
            project=closed,
            name="Finished Wing",
            state="closed",
            category=_category_id(tag, 3),
            prefix="CLD",
            constraint_id=_constraint_id(9003),
        )
    return {"active": active, "on_hold": on_hold, "closed": closed}


def test_an_on_hold_project_contributes_nothing_to_a_composed_portfolio_list(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The behaviour change, proved through the real transport.

    Today every owned Project contributes to a portfolio read regardless of
    state; after Phase 0, an on-hold Project's row is absent from the page.
    """
    ids = _seed_active_on_hold_and_closed_committed(migrated_engine, tag="sa")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, ListPortfolioConstraints())
    project_ids = {row["project_id"] for row in _result(envelope)["constraints"]}
    assert ids["active"] in project_ids
    assert ids["on_hold"] not in project_ids
    assert ids["closed"] not in project_ids


def test_a_closed_project_contributes_nothing_to_a_composed_portfolio_search(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    ids = _seed_active_on_hold_and_closed_committed(migrated_engine, tag="sb")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, SearchPortfolioConstraints(query="switchgear"))
    project_ids = {row["project_id"] for row in _result(envelope)["constraints"]}
    assert ids["active"] in project_ids
    assert ids["on_hold"] not in project_ids
    assert ids["closed"] not in project_ids


def test_an_on_hold_or_closed_project_is_excluded_from_the_composed_portfolio_overview(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    ids = _seed_active_on_hold_and_closed_committed(migrated_engine, tag="sc")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, ReadPortfolioConstraintOverview())
    project_ids = {row["project_id"] for row in _result(envelope)["overview"]["projects"]}
    assert project_ids == {ids["active"]}


def test_an_on_hold_project_remains_reachable_by_its_own_exact_project_read(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """Excluded from the portfolio, and still reachable named directly (§1).

    The Phase-0 narrowing is `_portfolio_projects`'s own; `_require_constraint_
    project` -- the exact-Project seam -- asks only whether the Project is this
    Principal's, never its lifecycle state.
    """
    ids = _seed_active_on_hold_and_closed_committed(migrated_engine, tag="sd")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, ListConstraints(project_id=ids["on_hold"]))
    assert envelope.error is None, envelope.error
    rows = _result(envelope)["constraints"]
    assert [row["project_id"] for row in rows] == [ids["on_hold"]]


def test_a_closed_project_remains_reachable_by_its_own_exact_project_read(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    ids = _seed_active_on_hold_and_closed_committed(migrated_engine, tag="se")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, ListConstraints(project_id=ids["closed"]))
    assert envelope.error is None, envelope.error
    rows = _result(envelope)["constraints"]
    assert [row["project_id"] for row in rows] == [ids["closed"]]


def _seed_named_active_portfolio_committed(engine: Engine, *, tag: str) -> dict[str, str]:
    """Two ACTIVE Projects with distinct names, each holding one row.

    Distinct names, rather than the shared `"Sample Project"` `_seed_project`
    otherwise defaults to, so a decoration bug that mixed rows up across
    Projects -- or that named every row from one Project -- is representable
    and not merely "some name is present".
    """
    first = _project_id(tag, 1)
    second = _project_id(tag, 2)
    with engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        _seed_state_project(
            connection,
            repository,
            principal=PRINCIPAL_A,
            project=first,
            name="Riverside Build-Out",
            state="active",
            category=_category_id(tag, 1),
            prefix="PF1",
            constraint_id=_constraint_id(9101),
        )
        _seed_state_project(
            connection,
            repository,
            principal=PRINCIPAL_A,
            project=second,
            name="Harbor Fit-Out",
            state="active",
            category=_category_id(tag, 2),
            prefix="PF2",
            constraint_id=_constraint_id(9102),
        )
    return {"first": first, "second": second}


def test_every_portfolio_list_row_carries_the_owning_projects_name(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    ids = _seed_named_active_portfolio_committed(migrated_engine, tag="pn")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, ListPortfolioConstraints())
    by_project = {row["project_id"]: row for row in _result(envelope)["constraints"]}
    assert by_project[ids["first"]]["project_name"] == "Riverside Build-Out"
    assert by_project[ids["second"]]["project_name"] == "Harbor Fit-Out"


def test_every_portfolio_search_row_carries_the_owning_projects_name(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    ids = _seed_named_active_portfolio_committed(migrated_engine, tag="ps")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, SearchPortfolioConstraints(query="switchgear"))
    by_project = {row["project_id"]: row for row in _result(envelope)["constraints"]}
    assert by_project[ids["first"]]["project_name"] == "Riverside Build-Out"
    assert by_project[ids["second"]]["project_name"] == "Harbor Fit-Out"


def test_every_portfolio_overview_entry_carries_the_owning_projects_name(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    ids = _seed_named_active_portfolio_committed(migrated_engine, tag="po")
    with _composed(migrated_engine, cloned_database_url) as service:
        envelope = _invoke(service, ReadPortfolioConstraintOverview())
    by_project = {row["project_id"]: row for row in _result(envelope)["overview"]["projects"]}
    assert by_project[ids["first"]]["project_name"] == "Riverside Build-Out"
    assert by_project[ids["second"]]["project_name"] == "Harbor Fit-Out"


def test_an_exact_project_response_never_carries_project_name_anywhere(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    """The negative half of the Phase-0 gate: the wire shape stays byte-identical.

    `constraints.list` and `constraints.overview` are exercised for a Project
    that *is* named on a portfolio read (`ids["first"]`), so an absence here
    is not merely because nothing ever set the field for this Project -- the
    same Project's row carries `project_name` on the portfolio path and must
    not on this one.
    """
    ids = _seed_named_active_portfolio_committed(migrated_engine, tag="ep")
    with _composed(migrated_engine, cloned_database_url) as service:
        list_envelope = _invoke(service, ListConstraints(project_id=ids["first"]))
        overview_envelope = _invoke(service, ReadConstraintOverview(project_id=ids["first"]))
    for envelope in (list_envelope, overview_envelope):
        assert envelope.error is None, envelope.error
        rendered = envelope.model_dump_json()
        assert "project_name" not in rendered
        assert "projectName" not in rendered
