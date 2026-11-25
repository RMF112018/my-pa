"""WP4P-S2 FAST: the read cases over the in-memory fake (`tests.conftest._ProjectReportReads`).

The same cases run on PostgreSQL in `tests/database/test_project_report_reads.py`;
`tests/database/test_project_report_reads_fake_parity.py` compares the two
answers read for read. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.unit.project_report_reads_cases import (
    CASES,
    case_a_superseded_derivation_is_never_answered_or_counted,
)
from tests.unit.project_report_reads_scene import ReadsScene, build_world, fast_scene


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_a_read_case_on_the_fake(case: Callable[[ReadsScene], None]) -> None:
    scene, _ingest, _world = fast_scene()
    build_world(scene)
    case(scene)


def test_a_superseded_derivation_on_the_fake() -> None:
    scene, _ingest, world = fast_scene()
    build_world(scene)
    case_a_superseded_derivation_is_never_answered_or_counted(
        scene, lambda: len(world.project_reports.derivations)
    )
