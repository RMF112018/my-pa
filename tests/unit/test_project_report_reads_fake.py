"""WP4P-S2 FAST: the read cases over the in-memory fake (`tests.conftest._ProjectReportReads`).

The same cases run on PostgreSQL in `tests/database/test_project_report_reads.py`;
`tests/database/test_project_report_reads_fake_parity.py` compares the two
answers read for read. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from my_pa.contracts.ports import ProjectReportLineQuery
from my_pa.domain.project_reports.catalogue import searchable_text_fields
from my_pa.domain.project_reports.model import RecordFamily
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


def test_the_fake_folds_only_ascii_letters_and_emulates_a_c_locale_cluster() -> None:
    """Ruling R1-08: the fake emulates a C-locale cluster and folds ASCII letters only.

    `É` against `é` is left out of the shared case on purpose: a UTF-8 cluster
    folds it and a C-locale one does not, so only the ASCII fold is a contract.
    """
    scene, _ingest, _world = fast_scene()
    build_world(scene)
    with scene.unit() as unit:
        reads = unit.project_report_reads
        (latest,) = [
            v.derivation_id
            for v in reads.list_report_versions(scene.principal)
            if v.slug_label == "qxrfis" and v.date_label == "20261120"
        ]

        def numbers(needle: str) -> list[str]:
            query = ProjectReportLineQuery(
                derivation_ids=(latest,),
                limit=100,
                text=needle,
                text_fields=searchable_text_fields(RecordFamily.RFIS),
            )
            return [
                next(v.raw_text for v in line.values if v.field_key == "rfi.number")
                for line in reads.query_lines(scene.principal, query)
            ]

        assert numbers("İota") == ["1740"]
        assert numbers("DéLTA") == ["1740"]
        assert numbers("DÉLTA") == []
        assert numbers("i̇ota") == []  # Python's `"İ".lower()`: never the needle
