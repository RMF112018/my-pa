"""WP4P-S2: the project-report reads on PostgreSQL (`SqlProjectReportReadsRepository`).

The `database` tier, on a disposable head-migrated clone. The synthetic world
is built through the WP3P path (the lifecycle, the handler, the re-derivation
sweep) over an in-memory file store (`tests.unit.project_report_reads_scene`),
then read through `UnitOfWork.project_report_reads` alone
(`tests.unit.project_report_reads_cases`, the cases the fake runs too):

* a superseded derivation (a binding correction and an adapter
  re-derivation) is never answered or counted;
* a quarantined latest version answers no rows and `snapshot_quarantined`;
* versions follow the label order (D10), not arrival, with per-version
  filter semantics;
* another Principal's identifiers answer nothing;
* RFI `174` never matches `1740` or `17`; the prefix is exact;
  `ambiguous_prefix` (PULSE-AC-14 through the read);
* text never crosses a field; date ranges are inclusive;
* the two-level export answers its 99 detail lines, never a header (AC-06);
* keyset pages are disjoint and complete.

Every identifier, folder, number and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine, text

from tests.unit.project_report_reads_cases import (
    CASES,
    case_a_superseded_derivation_is_never_answered_or_counted,
)
from tests.unit.project_report_reads_scene import ReadsScene, build_world, database_scene

pytestmark = pytest.mark.database


@pytest.fixture
def scene(migrated_engine: Engine) -> ReadsScene:
    built = database_scene(migrated_engine)
    build_world(built)
    return built


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_a_read_case_on_postgresql(scene: ReadsScene, case: Callable[[ReadsScene], None]) -> None:
    case(scene)


def test_a_superseded_derivation_on_postgresql(scene: ReadsScene, migrated_engine: Engine) -> None:
    def derivation_rows() -> int:
        with migrated_engine.connect() as connection:
            return int(
                connection.execute(
                    text("SELECT count(*) FROM knowledge.project_report_derivations")
                ).scalar_one()
            )

    case_a_superseded_derivation_is_never_answered_or_counted(scene, derivation_rows)


def test_the_unit_of_work_exposes_the_reads(migrated_engine: Engine) -> None:
    from my_pa.infrastructure.persistence.project_report_reads import (
        SqlProjectReportReadsRepository,
    )

    scene = database_scene(migrated_engine)
    with scene.unit() as unit:
        assert isinstance(unit.project_report_reads, SqlProjectReportReadsRepository)
        assert unit.project_report_reads.list_report_versions(scene.principal) == ()
