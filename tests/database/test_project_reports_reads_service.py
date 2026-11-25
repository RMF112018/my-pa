"""WP4P-S3: the project-report read service on PostgreSQL (`ProjectReportReads`).

The `database` tier, on a disposable head-migrated clone: the synthetic world
of `tests.unit.project_report_reads_scene` plus `extend_world`, built through
the WP3P path, then read through the service alone
(`tests.unit.project_reports_reads_service_cases`, the cases the fake runs
too): catalog, keyset pages, a new version between pages
(`scope_changed_restart_required`), cursor conflicts, `source_totals` never in
`measures` (PULSE-AC-08), a cross-check mismatch on both columns and a stale
check ignored after a re-derivation (ruling A4), record history across 3 RFI
views, `not_observed` never closed (AC-11), `not_found` indistinguishable,
the WP5 facade, and per-version coverage.

Every identifier, folder, number and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine

from tests.unit.project_report_reads_scene import ReadsScene, build_world, database_scene
from tests.unit.project_reports_reads_service_cases import CASES, extend_world

pytestmark = pytest.mark.database


@pytest.fixture
def scene(migrated_engine: Engine) -> ReadsScene:
    built = database_scene(migrated_engine)
    build_world(built)
    extend_world(built)
    return built


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_a_service_case_on_postgresql(
    scene: ReadsScene, case: Callable[[ReadsScene], None]
) -> None:
    case(scene)
