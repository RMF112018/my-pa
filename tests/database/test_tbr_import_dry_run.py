"""PC-CM-IMP-WP13 T13-01, T13-04: the dry run writes nothing, and infers no calendar.

The `database` tier, on a disposable head-migrated clone. Two claims live here
and neither can be established without a real server.

*The dry run is side-effect free.* Not "performs no insert" — that is a claim
about the code, and the code is what is under test. What is measured is the
database: every table the import writes is counted before and after a full dry
run over the synthetic register, and every count is unchanged. The dry run
leaves its transaction by exception on purpose, so a future edit that added a
write to that path would still write nothing, and this test would still be the
thing that noticed if that stopped being true.

*The project calendar comes from the stored settings row and from nowhere else.*
The environment's own timezone is set to a zone twelve hours from UTC for the
duration of one test, and the import is required to be unaffected by it — and,
separately, a stored zone that is not an IANA name is required to stop the run
rather than to fall back to anything. Between them those two are the whole "no
system-timezone fallback" claim.

Every identifier, prefix, label, code and date here is synthetic.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, func, insert, select, update
from sqlalchemy.sql import FromClause

from my_pa.application.constraint_legacy_import import (
    ConstraintLegacyImportService,
    ImportDisposition,
    LegacyImportProjectUnavailableError,
)
from my_pa.domain.project_controls.business_time import ProjectTimezoneError
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.ooxml_worksheet_reader import OoxmlWorkbookSource
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    constraint_project_settings,
    constraint_sync_baselines,
    project_constraint_history,
    project_constraint_parties,
    project_constraint_revisions,
    project_constraints,
    projects,
)
from tests.fixtures.tbr_workbook import SHEET_NAME, write_register

pytestmark = [pytest.mark.database, pytest.mark.database_clone]

PRINCIPAL_A: Final = "prn_impaaaa0001aaaa0001aa"
PRINCIPAL_B: Final = "prn_impbbbb0002bbbb0002bb"
PROJECT_A: Final = "prj_impaaaa0001aaaa"
PROJECT_B: Final = "prj_impbbbb0002bbbb"
REGISTER: Final = "synthetic-register-01"
ZONE: Final = "America/Chicago"

#: 15:00 UTC on Wednesday 2 September 2026 — still 2 September in Chicago.
T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

#: Every table one import writes. The dry run must leave all of them alone.
WRITTEN_TABLES: Final = (
    project_constraints,
    project_constraint_revisions,
    project_constraint_history,
    project_constraint_parties,
    constraint_categories,
    constraint_sync_baselines,
)


def seed(engine: Engine) -> None:
    """Two Principals, two Projects, and a calendar for each."""
    with engine.begin() as connection:
        for principal, project in ((PRINCIPAL_A, PROJECT_A), (PRINCIPAL_B, PROJECT_B)):
            connection.execute(
                insert(projects).values(
                    project_id=project,
                    principal_id=principal,
                    name="A Synthetic Project",
                    state="active",
                    participants=[],
                    opened_at=T0,
                    created_at=T0,
                    updated_at=T0,
                )
            )
    with SqlAlchemyConstraintManagementUnitOfWork(engine) as uow:
        for principal, project in ((PRINCIPAL_A, PROJECT_A), (PRINCIPAL_B, PROJECT_B)):
            uow.constraints.insert_project_settings(
                principal,
                ConstraintProjectSettings(
                    principal_id=principal,
                    project_id=project,
                    timezone_name=ZONE,
                    version=1,
                    created_at=T0,
                    updated_at=T0,
                ),
            )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return migrated_engine


def _service(engine: Engine) -> ConstraintLegacyImportService:
    return ConstraintLegacyImportService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
        clock=lambda: T0,
    )


def _reader(tmp_path: Path) -> OoxmlWorkbookSource:
    path = write_register(tmp_path / "register.xlsm", with_vba=True)
    return OoxmlWorkbookSource(path, sheet_name=SHEET_NAME)


def _count(engine: Engine, table: FromClause) -> int:
    with engine.begin() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _census(engine: Engine) -> dict[str, int]:
    return {table.name: _count(engine, table) for table in WRITTEN_TABLES}


def test_a_full_dry_run_leaves_every_table_exactly_as_it_found_it(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-01. Zero constraints, revisions, receipts, parties, categories, baselines."""
    before = _census(staged)
    outcome = _service(staged).dry_run(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        register_id=REGISTER,
        reader=_reader(tmp_path),
    )
    assert outcome.report.planned_inserts > 0
    assert outcome.report.applied == 0
    assert outcome.report.replayed == 0
    assert outcome.report.disposition is ImportDisposition.READY
    assert _census(staged) == before
    assert all(count == 0 for count in before.values())


def test_a_dry_run_is_repeatable_and_produces_the_same_answer_twice(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-01. A side-effect-free run is one that a second run cannot notice."""
    service = _service(staged)
    reader = _reader(tmp_path)
    first = service.dry_run(
        principal_id=PRINCIPAL_A, project_id=PROJECT_A, register_id=REGISTER, reader=reader
    )
    second = service.dry_run(
        principal_id=PRINCIPAL_A, project_id=PROJECT_A, register_id=REGISTER, reader=reader
    )
    assert first.report.class_counts == second.report.class_counts
    assert first.report.category_plans == second.report.category_plans
    assert first.report.source_digest == second.report.source_digest


def test_a_project_with_no_constraint_settings_is_refused(staged: Engine, tmp_path: Path) -> None:
    """T13-04. The settings row is the gate, exactly as the product plane has it."""
    with staged.begin() as connection:
        connection.execute(
            constraint_project_settings.delete().where(
                constraint_project_settings.c.project_id == PROJECT_A
            )
        )
    with pytest.raises(LegacyImportProjectUnavailableError):
        _service(staged).dry_run(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            register_id=REGISTER,
            reader=_reader(tmp_path),
        )


def test_another_principals_project_fails_the_same_way_as_a_missing_one(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-04, CM-BE-AC-132. Foreign and unconfigured are deliberately the same answer."""
    with pytest.raises(LegacyImportProjectUnavailableError) as foreign:
        _service(staged).dry_run(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_B,
            register_id=REGISTER,
            reader=_reader(tmp_path),
        )
    with pytest.raises(LegacyImportProjectUnavailableError) as absent:
        _service(staged).dry_run(
            principal_id=PRINCIPAL_A,
            project_id="prj_impcccc0003cccc",
            register_id=REGISTER,
            reader=_reader(tmp_path),
        )
    assert foreign.value.code == absent.value.code
    assert str(foreign.value) == str(absent.value)


def test_a_stored_timezone_that_is_not_an_iana_zone_stops_the_run(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-04. There is no fallback: an unusable calendar is a stop, not a default."""
    with staged.begin() as connection:
        connection.execute(
            update(constraint_project_settings)
            .where(constraint_project_settings.c.project_id == PROJECT_A)
            .values(timezone_name="Not/AZone")
        )
    with pytest.raises(ProjectTimezoneError) as error:
        _service(staged).dry_run(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            register_id=REGISTER,
            reader=_reader(tmp_path),
        )
    assert error.value.code == "project_timezone_invalid"


def test_the_workstation_timezone_changes_nothing(
    staged: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T13-04. Run under a zone twelve hours from UTC; the answer does not move."""
    baseline = _service(staged).dry_run(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        register_id=REGISTER,
        reader=_reader(tmp_path),
    )
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        shifted = _service(staged).dry_run(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            register_id=REGISTER,
            reader=_reader(tmp_path),
        )
    finally:
        monkeypatch.delenv("TZ", raising=False)
        if hasattr(time, "tzset"):
            time.tzset()
    assert shifted.report.class_counts == baseline.report.class_counts
    assert shifted.report.lifecycle_counts == baseline.report.lifecycle_counts
    assert shifted.report.category_plans == baseline.report.category_plans
    assert os.environ.get("TZ") is None
