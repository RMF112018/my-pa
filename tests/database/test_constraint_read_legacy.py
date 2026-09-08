"""PC-CM-IMP-WP03 §L T12: a legally persisted legacy import is readable, and stays honest.

The DDL admits a shape the write aggregate cannot build. Four CHECK constraints
relax conjunctively for `origin = 'legacy_workbook_import'` **and**
`record_quality = 'legacy_incomplete'`, so such a row may be CLOSED with no
completion date, may carry no `published_at`, and may be missing its Category,
description, Date Identified and Due Date. No write path in this repository
produces one, which is why the rows here are inserted with SQLAlchemy Core: the
point is to read what an importer will one day write, not to invent a writer.

The asymmetry being proved is the whole legacy decision. `read_constraint` and
`list_constraints` return the row intact; `get` still raises
`ConstraintInvariantError` for the very same row, because the aggregate was not
weakened to make the read work. And nothing is filled in on the way out: an
absent date stays `None`, an absent description stays `None`, an absent BIC stays
empty, and a CLOSED record with no completion datum reports exactly that rather
than a substituted date. The row is surfaced through `record_quality`,
`needs_attention` and `missing_fields` instead — which is the point of having
them.

**One boundary of the DDL, recorded because it contradicts a looser reading:**
`a_draft_constraint_carries_no_code` is *not* legacy-gated, so a non-DRAFT row —
legacy or not — always has a `constraint_code`. A closed import with a null code
cannot be persisted at all. A null code is proved here on the row shape that can
hold one, a legacy DRAFT.

Every identifier, code, date and label is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintAttentionReason,
    ConstraintFieldKey,
    ConstraintInvariantError,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import ConstraintListQuery, ConstraintListScope
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import project_constraints, projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_lgcaaaa01"
PRINCIPAL_B: Final = "prn_lgcbbbb02"
PROJECT_A: Final = "prj_lgcaaaa01"
PROJECT_B: Final = "prj_lgcbbbb02"
CATEGORY_A: Final = "ccat_lgcaaaa01"
CATEGORY_B: Final = "ccat_lgcbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_lgc{ordinal:06d}"


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


NORMAL: Final = _id("cst", 1)
LEGACY_CLOSED: Final = _id("cst", 2)
LEGACY_ACTIVE: Final = _id("cst", 3)
LEGACY_DRAFT: Final = _id("cst", 4)

#: `NOW` read in `ZONE_EAST` is Monday 14 September 2026. The one dated row was
#: identified on Tuesday 1 September, which is ten weekdays inclusive.
PROJECT_TODAY: Final = date(2026, 9, 14)
DATED_AGE_BUSINESS_DAYS: Final = 10


def _insert_legacy(connection: Connection, **columns: object) -> None:
    """One legacy row, written past the write path because no write path makes one."""
    values: dict[str, Any] = {
        "principal_id": PRINCIPAL_A,
        "project_id": PROJECT_A,
        "category_id": None,
        "constraint_code": None,
        "description": None,
        "date_identified": None,
        "due_date": None,
        "reference": None,
        "current_update": None,
        "completion_date": None,
        "closure_commentary": None,
        "voided_date": None,
        "void_reason": None,
        "published_at": None,
        "origin": ConstraintOrigin.LEGACY_WORKBOOK_IMPORT.value,
        "record_quality": ConstraintRecordQuality.LEGACY_INCOMPLETE.value,
        "version": 1,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(columns)
    connection.execute(insert(project_constraints).values(**values))


def _legacy_world(connection: Connection) -> SqlConstraintManagementRepository:
    repository = _world(connection)
    repository.insert_constraint(
        PRINCIPAL_A, _constraint(constraint_id=NORMAL, date_identified=date(2026, 9, 1))
    )
    _insert_legacy(
        connection,
        constraint_id=LEGACY_CLOSED,
        lifecycle_state=ConstraintLifecycleState.CLOSED.value,
        constraint_code="7.03",
    )
    _insert_legacy(
        connection,
        constraint_id=LEGACY_ACTIVE,
        lifecycle_state=ConstraintLifecycleState.IDENTIFIED.value,
        constraint_code="7.04",
    )
    _insert_legacy(
        connection,
        constraint_id=LEGACY_DRAFT,
        lifecycle_state=ConstraintLifecycleState.DRAFT.value,
    )
    return repository


def test_the_write_aggregate_still_refuses_the_row_the_read_plane_returns(
    migrated_engine: Engine,
) -> None:
    """The asymmetry, stated as one test: `get` raises, `read_constraint` does not."""
    with migrated_engine.begin() as connection:
        repository = _legacy_world(connection)
        with pytest.raises(ConstraintInvariantError):
            repository.get(PRINCIPAL_A, LEGACY_CLOSED)
        record = repository.read_constraint(PRINCIPAL_A, LEGACY_CLOSED)
        assert record is not None
        assert record.constraint_id == LEGACY_CLOSED
        assert record.lifecycle_state is ConstraintLifecycleState.CLOSED
        assert record.completion_date is None


def test_a_legacy_row_appears_in_the_register_alongside_normal_rows(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _legacy_world(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL),
            now=NOW,
        )
        assert sorted(entry.constraint_id for entry in page.entries) == sorted(
            [NORMAL, LEGACY_CLOSED, LEGACY_ACTIVE, LEGACY_DRAFT]
        )


def test_a_legacy_rows_missing_values_stay_missing_in_both_reads(
    migrated_engine: Engine,
) -> None:
    """No default date, description, BIC, closure datum or lifecycle is substituted."""
    with migrated_engine.begin() as connection:
        repository = _legacy_world(connection)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=LEGACY_CLOSED, now=NOW
        )
        assert view.description is None
        assert view.date_identified is None
        assert view.due_date is None
        assert view.category is None
        assert view.bic == ()
        assert view.responsible == ()
        assert view.days_elapsed is None
        assert view.is_overdue is False
        assert view.is_due_soon is False
        assert view.in_my_court is False
        # A closed import counts as published because its lifecycle says so,
        # and yet carries no `published_at`: the read plane reports both rather
        # than reconciling them into a date nobody recorded.
        assert view.is_published is True
        assert view.published_at is None
        assert view.completion is not None
        assert view.completion.completion_date is None
        assert view.completion.closure_commentary is None
        assert view.void is None
        assert view.status is ConstraintLifecycleState.CLOSED
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL),
            now=NOW,
        )
        entry = next(row for row in page.entries if row.constraint_id == LEGACY_CLOSED)
        assert (entry.description, entry.date_identified, entry.due_date) == (None, None, None)
        assert entry.days_elapsed is None
        assert entry.is_overdue is False
        assert entry.is_due_soon is False


def test_a_legacy_draft_reads_back_with_no_constraint_code(migrated_engine: Engine) -> None:
    """A null code is a real stored shape; it is simply the DRAFT one."""
    with migrated_engine.begin() as connection:
        repository = _legacy_world(connection)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=LEGACY_DRAFT, now=NOW
        )
        assert view.constraint_code is None
        assert view.status is ConstraintLifecycleState.DRAFT


def test_the_attention_diagnostics_are_exact_rather_than_indicative(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _legacy_world(connection)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=LEGACY_CLOSED, now=NOW
        )
        assert view.needs_attention is True
        assert view.needs_attention_reasons == (ConstraintAttentionReason.LEGACY_INCOMPLETE,)
        assert view.missing_fields == (
            ConstraintFieldKey.CATEGORY_ID,
            ConstraintFieldKey.DESCRIPTION,
            ConstraintFieldKey.DATE_IDENTIFIED,
            ConstraintFieldKey.DUE_DATE,
            ConstraintFieldKey.BIC,
        )
        normal = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=NORMAL, now=NOW
        )
        assert normal.needs_attention is False
        assert normal.needs_attention_reasons == ()
        assert normal.missing_fields == ()


def test_the_undated_legacy_row_is_outside_the_average_open_age_denominator(
    migrated_engine: Engine,
) -> None:
    """Excluded from numerator and denominator both, rather than counted as zero."""
    with migrated_engine.begin() as connection:
        repository = _legacy_world(connection)
        overview = SERVICE.read_overview(
            repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
        )
        assert overview.project_today == PROJECT_TODAY
        assert overview.total_open == 2
        assert overview.average_open_age_business_days == float(DATED_AGE_BUSINESS_DAYS)
        assert overview.needs_attention == 3
        assert overview.draft == 1


def test_an_overview_with_only_undated_rows_reports_no_average_rather_than_zero(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _world(connection)
        _insert_legacy(
            connection,
            constraint_id=LEGACY_ACTIVE,
            lifecycle_state=ConstraintLifecycleState.IDENTIFIED.value,
            constraint_code="7.04",
        )
        overview = SERVICE.read_overview(
            repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
        )
        assert overview.total_open == 1
        assert overview.average_open_age_business_days is None


def test_a_legacy_row_is_reachable_through_the_record_quality_filter(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _legacy_world(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL,
                record_qualities=frozenset({ConstraintRecordQuality.LEGACY_INCOMPLETE}),
            ),
            now=NOW,
        )
        assert sorted(entry.constraint_id for entry in page.entries) == sorted(
            [LEGACY_CLOSED, LEGACY_ACTIVE, LEGACY_DRAFT]
        )
        attention = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL, needs_attention=True),
            now=NOW,
        )
        assert len(attention.entries) == 3
