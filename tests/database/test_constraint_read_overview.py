"""PC-CM-IMP-WP03 §L T14 and T9: the overview agrees with the Register, or it is wrong.

Every count on the overview names a list filter that must select exactly the rows
it counted. That is not a convention here: each test below runs the aggregate
statement and the matching list query against the same rows, the same fixed
instant and the same Project settings, and asserts the two numbers are equal.
The two are computed by different SQL from the same definitions, so a divergence
would mean one of the two definitions had drifted — which is the failure this
file exists to catch.

The Project's own calendar is the second subject. `project_today` is the backend
instant read in the Project's IANA zone and nothing else: the same instant read
in two zones can be two different Project dates, and the Overdue count moves with
it. No service method takes a timezone parameter, so a caller cannot supply a
more convenient one; and a Project with no settings row fails closed with an
unavailable answer rather than reporting zero overdue Constraints it could not
compute.

Every identifier, code and date here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.application.errors import SafeDetail, UnavailableError
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintOverview,
    ConstraintRecentFilter,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import project_constraints, projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_ovwaaaa01"
PRINCIPAL_B: Final = "prn_ovwbbbb02"
PROJECT_A: Final = "prj_ovwaaaa01"
PROJECT_B: Final = "prj_ovwbbbb02"
CATEGORY_A: Final = "ccat_ovwaaaa01"
CATEGORY_B: Final = "ccat_ovwbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_ovw{ordinal:06d}"


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


OVERDUE: Final = _id("cst", 1)
DUE_SOON: Final = _id("cst", 2)
HELD: Final = _id("cst", 3)
TOUCHED: Final = _id("cst", 4)
CLOSED: Final = _id("cst", 5)
DRAFT: Final = _id("cst", 6)
LEGACY: Final = _id("cst", 7)
PROJECT_UNSET: Final = "prj_ovwaaaa03"
PROJECT_WEST: Final = "prj_ovwaaaa04"
CATEGORY_WEST: Final = "ccat_ovwaaaa04"

#: `NOW` read in `ZONE_EAST` is Monday 14 September 2026; Due Soon runs through
#: Wednesday 23 September, seven working days later.
PROJECT_TODAY: Final = date(2026, 9, 14)

#: Late enough in UTC that New York has already turned the page and Los Angeles
#: has not: one instant, two Project dates.
MIDNIGHT_BOUNDARY: Final = datetime(2026, 9, 15, 5, 30, tzinfo=UTC)


def _counted(connection: Connection, *, zone: str = ZONE_EAST) -> SqlConstraintManagementRepository:
    """Seven Constraints, chosen so that every overview count is non-trivial."""
    repository = _world(connection, zone=zone)
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(constraint_id=OVERDUE, constraint_code="1.01", due_date=date(2026, 9, 10)),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=DUE_SOON,
            constraint_code="1.02",
            due_date=date(2026, 9, 16),
            lifecycle_state=ConstraintLifecycleState.IN_PROGRESS,
            bic=(PartyRef(kind=PartyKind.UNRESOLVED, label="the owner"),),
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=HELD,
            constraint_code="1.03",
            lifecycle_state=ConstraintLifecycleState.ON_HOLD,
            due_date=date(2026, 11, 2),
            bic=(PartyRef(kind=PartyKind.UNRESOLVED, label="the architect"),),
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=TOUCHED,
            constraint_code="1.04",
            due_date=date(2026, 10, 1),
            updated_at=datetime(2026, 9, 10, 9, 0, tzinfo=UTC),
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=CLOSED,
            constraint_code="1.05",
            lifecycle_state=ConstraintLifecycleState.CLOSED,
            completion_date=date(2026, 9, 11),
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
            published_at=None,
            bic=(),
        ),
    )
    connection.execute(
        insert(project_constraints).values(
            constraint_id=LEGACY,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            constraint_code="7.03",
            lifecycle_state=ConstraintLifecycleState.CLOSED.value,
            origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT.value,
            record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE.value,
            version=1,
            created_at=T0,
            updated_at=T0,
        )
    )
    return repository


def _overview(
    repository: SqlConstraintManagementRepository, *, now: datetime = NOW
) -> ConstraintOverview:
    return SERVICE.read_overview(
        repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=now
    )


def _rows(
    repository: SqlConstraintManagementRepository, *, now: datetime = NOW, **fields: object
) -> int:
    page = SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(**fields),
        now=now,
    )
    assert page.is_truncated is False
    return len(page.entries)


def test_every_overview_count_equals_its_matching_list_query(
    migrated_engine: Engine,
) -> None:
    """Nine counts, nine list queries, one fixed instant and one set of rows."""
    with migrated_engine.begin() as connection:
        repository = _counted(connection)
        overview = _overview(repository)
        assert overview.total_open == _rows(repository, scope=ConstraintListScope.OPEN)
        assert overview.overdue == _rows(repository, scope=ConstraintListScope.ALL, overdue=True)
        assert overview.due_soon == _rows(repository, scope=ConstraintListScope.ALL, due_soon=True)
        assert overview.in_my_court == _rows(
            repository, scope=ConstraintListScope.ALL, my_court=True
        )
        assert overview.on_hold == _rows(
            repository,
            scope=ConstraintListScope.ALL,
            statuses=frozenset({ConstraintLifecycleState.ON_HOLD}),
        )
        assert overview.recently_changed == _rows(
            repository,
            scope=ConstraintListScope.ALL,
            recent=ConstraintRecentFilter.RECENTLY_CHANGED,
        )
        assert overview.recently_closed == _rows(
            repository,
            scope=ConstraintListScope.ALL,
            recent=ConstraintRecentFilter.RECENTLY_CLOSED,
        )
        assert overview.draft == _rows(repository, scope=ConstraintListScope.DRAFT)
        assert overview.needs_attention == _rows(
            repository, scope=ConstraintListScope.ALL, needs_attention=True
        )


def test_each_of_those_counts_is_non_trivial_on_this_data(migrated_engine: Engine) -> None:
    """A coherence test between two zeroes would prove nothing, so none of them is zero."""
    with migrated_engine.begin() as connection:
        overview = _overview(_counted(connection))
        assert overview.total_open == 4
        assert overview.overdue == 1
        assert overview.due_soon == 1
        assert overview.in_my_court == 2
        assert overview.on_hold == 1
        assert overview.recently_changed == 1
        assert overview.recently_closed == 1
        assert overview.draft == 1
        assert overview.needs_attention == 1


def test_the_overview_reports_the_calendar_it_counted_on(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        overview = _overview(_counted(connection))
        assert overview.project_today == PROJECT_TODAY
        assert overview.project_timezone == ZONE_EAST
        assert overview.due_soon_through == date(2026, 9, 23)
        assert overview.as_of == NOW
        assert overview.project_id == PROJECT_A


def test_overdue_and_due_soon_never_count_the_same_constraint(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _counted(connection)
        overview = _overview(repository)
        both = _rows(repository, scope=ConstraintListScope.ALL, overdue=True, due_soon=True)
        assert both == 0
        assert overview.overdue + overview.due_soon <= overview.total_open


def test_the_average_open_age_is_the_mean_of_the_rows_that_have_a_date(
    migrated_engine: Engine,
) -> None:
    """Four active rows, all identified on 1 September: ten weekdays through today."""
    with migrated_engine.begin() as connection:
        repository = _counted(connection)
        overview = _overview(repository)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(scope=ConstraintListScope.OPEN),
            now=NOW,
        )
        elapsed = [entry.days_elapsed for entry in page.entries]
        assert all(value == 10 for value in elapsed)
        assert overview.average_open_age_business_days == 10.0


def test_the_same_instant_in_two_zones_is_two_project_dates(
    migrated_engine: Engine,
) -> None:
    """One backend instant, two IANA zones, two calendars — and two Overdue counts.

    Both Projects hold one Constraint due on 14 September. Read at an instant
    that is already the 15th in New York and still the 14th in Los Angeles, the
    eastern Project's row is overdue and the western Project's is due today.
    """
    with migrated_engine.begin() as connection:
        repository = _counted(connection)
        _seed_project(connection, PRINCIPAL_A, PROJECT_WEST)
        repository.insert_project_settings(
            PRINCIPAL_A, _settings(PRINCIPAL_A, PROJECT_WEST, ZONE_WEST)
        )
        repository.insert_category(
            PRINCIPAL_A, _category(CATEGORY_WEST, PRINCIPAL_A, PROJECT_WEST, "WST", 1)
        )
        for project, category, identifier in (
            (PROJECT_A, CATEGORY_A, _id("cst", 8)),
            (PROJECT_WEST, CATEGORY_WEST, _id("cst", 9)),
        ):
            repository.insert_constraint(
                PRINCIPAL_A,
                _constraint(
                    constraint_id=identifier,
                    project_id=project,
                    category_id=category,
                    constraint_code="4.01",
                    due_date=date(2026, 9, 14),
                ),
            )
        eastern = SERVICE.read_overview(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            now=MIDNIGHT_BOUNDARY,
        )
        western = SERVICE.read_overview(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_WEST,
            now=MIDNIGHT_BOUNDARY,
        )
        assert eastern.project_today == date(2026, 9, 15)
        assert western.project_today == date(2026, 9, 14)
        assert western.project_timezone == ZONE_WEST
        assert western.total_open == 1
        assert western.overdue == 0
        assert western.due_soon == 1
        assert eastern.overdue == 2


def test_a_project_with_no_configured_timezone_fails_closed(
    migrated_engine: Engine,
) -> None:
    """Not zero overdue Constraints: no answer at all, because none can be computed."""
    with migrated_engine.begin() as connection:
        repository = _counted(connection)
        _seed_project(connection, PRINCIPAL_A, PROJECT_UNSET)
        with pytest.raises(UnavailableError) as error:
            SERVICE.read_overview(
                repository, principal_id=PRINCIPAL_A, project_id=PROJECT_UNSET, now=NOW
            )
        assert error.value.safe_details == (SafeDetail.PROJECT_ID,)
        with pytest.raises(UnavailableError):
            SERVICE.list_constraints(
                repository,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_UNSET,
                query=ConstraintListQuery(),
                now=NOW,
            )


def test_an_unknown_zone_name_fails_closed_the_same_way(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _counted(connection)
        _seed_project(connection, PRINCIPAL_A, PROJECT_UNSET)
        repository.insert_project_settings(
            PRINCIPAL_A, _settings(PRINCIPAL_A, PROJECT_UNSET, "Mars/Olympus_Mons")
        )
        with pytest.raises(UnavailableError) as error:
            SERVICE.read_overview(
                repository, principal_id=PRINCIPAL_A, project_id=PROJECT_UNSET, now=NOW
            )
        assert error.value.safe_details == (SafeDetail.PROJECT_ID,)


def test_no_read_accepts_a_timezone_the_caller_chose(migrated_engine: Engine) -> None:
    """There is no parameter to pass one through, so a fallback cannot be smuggled in."""
    with migrated_engine.begin() as connection:
        repository = _counted(connection)
        with pytest.raises(TypeError):
            SERVICE.read_overview(  # type: ignore[call-arg]
                repository,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                now=NOW,
                timezone_name=ZONE_WEST,
            )
        assert "timezone" not in set(ConstraintListQuery.__slots__)
