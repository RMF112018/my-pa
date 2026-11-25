"""WP4P-S2: the FAST reads fake answers what PostgreSQL answers (the WP3P-S4 lesson).

The same synthetic world is built through the same WP3P path, in the same
order under the same clock, over the fakes (`tests.conftest._ProjectReportReads`)
and over a head-migrated clone (`SqlProjectReportReadsRepository`). Every read
method is then called with the same arguments on both, and the answers must be
equal once the identifiers each side issued at random (sources, snapshots,
derivations, binding revisions, records, series) are replaced by what they
name. Answers are compared in order, except those ordered by an identifier
each side issued at random (`lines_of_records` by record, the stated totals,
cross-checks and RFI candidates by derivation), compared as sets. Every value is synthetic.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from datetime import date
from typing import Any, Final

import pytest
from sqlalchemy import Engine

from my_pa.contracts.ports import (
    ProjectReportIdentifierTerm,
    ProjectReportLineQuery,
    ProjectReportReadsRepository,
    ProjectReportRfiTerm,
)
from my_pa.domain.project_reports.catalogue import searchable_text_fields
from my_pa.domain.project_reports.model import RecordFamily, StatusClass
from tests.unit.project_report_reads_scene import (
    OBS_PROJECT,
    RFI_PROJECT,
    ReadsScene,
    build_world,
    database_scene,
    fast_scene,
    unknown_adapter_registry,
)

pytestmark = pytest.mark.database

_ISSUED: Final = re.compile(r"\A(isrc|isnp|prdrv|prbnd|prrec|prser)_[A-Za-z0-9]+\Z")


class _Names:
    """Replaces each issued identifier by a stable name for what it identifies."""

    def __init__(self, reads: ProjectReportReadsRepository, principal: str) -> None:
        self.names: dict[str, str] = {}
        for version in reads.list_report_versions(principal):
            where = f"{version.project_id}/{version.slug_label}/{version.date_label}"
            self.names[version.snapshot_id] = f"snapshot:{where}"
            self.names[version.derivation_id] = f"derivation:{where}"
            self.names[version.ingest_source_id] = f"source:{version.project_id}"
            self.names[version.binding_revision_id] = f"revision:{version.project_id}"
            self.names[version.series_id] = (
                f"series:{version.project_id}/{version.slug_label}/{version.header_signature}"
            )
            query = ProjectReportLineQuery(derivation_ids=(version.derivation_id,), limit=1000)
            for line in reads.query_lines(principal, query):
                if line.record_id is not None:
                    self.names[line.record_id] = f"record:{line.identity_key}"

    def __call__(self, value: object) -> object:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return tuple((f.name, self(getattr(value, f.name))) for f in dataclasses.fields(value))
        if isinstance(value, tuple | list):
            return tuple(self(item) for item in value)
        if isinstance(value, dict):
            return tuple(sorted((str(k), self(v)) for k, v in value.items()))
        if isinstance(value, str) and _ISSUED.fullmatch(value):
            assert value in self.names, value
            return self.names[value]
        return value


def _sorted(named: object) -> tuple[object, ...]:
    assert isinstance(named, tuple)
    return tuple(sorted(named, key=repr))


def _answers(scene: ReadsScene) -> dict[str, Any]:
    principal = scene.principal
    with scene.unit() as unit:
        reads = unit.project_report_reads
        name = _Names(reads, principal)
        versions = reads.list_report_versions(principal)
        derivations = tuple(v.derivation_id for v in versions)
        rfis = tuple(v.derivation_id for v in versions if v.project_id == RFI_PROJECT[1])
        fields = searchable_text_fields(RecordFamily.RFIS)
        queries: dict[str, ProjectReportLineQuery] = {
            "all": ProjectReportLineQuery(derivation_ids=derivations, limit=1000),
            "page": ProjectReportLineQuery(derivation_ids=derivations, limit=7, after=(1, 2)),
            "reversed": ProjectReportLineQuery(derivation_ids=derivations[::-1], limit=50),
            "status": ProjectReportLineQuery(
                derivation_ids=derivations, limit=1000, status_classes=(StatusClass.CLOSED,)
            ),
            "statuses": ProjectReportLineQuery(
                derivation_ids=derivations, limit=1000, statuses=("Open",)
            ),
            "dates": ProjectReportLineQuery(
                derivation_ids=rfis,
                limit=1000,
                date_field="rfi.date_initiated",
                date_from=date(2026, 11, 1),
                date_to=date(2026, 11, 5),
            ),
            "rfi": ProjectReportLineQuery(
                derivation_ids=rfis,
                limit=1000,
                rfi_terms=(ProjectReportRfiTerm(None, 174), ProjectReportRfiTerm("GMP-", 175)),
            ),
            "identifier": ProjectReportLineQuery(
                derivation_ids=rfis,
                limit=1000,
                identifiers=(ProjectReportIdentifierTerm("rfi.number", "GMP-174"),),
            ),
            "group": ProjectReportLineQuery(
                derivation_ids=derivations, limit=1000, group_keys=("Open", "Closed")
            ),
            "text": ProjectReportLineQuery(
                derivation_ids=rfis, limit=1000, text="kilo", text_fields=fields
            ),
            "boundary": ProjectReportLineQuery(
                derivation_ids=rfis, limit=1000, text="okil", text_fields=fields
            ),
        }
        answers: dict[str, Any] = {
            "versions": name(versions),
            "rfi_versions": name(
                reads.list_report_versions(principal, record_family=RecordFamily.RFIS)
            ),
            "obs_versions": name(
                reads.list_report_versions(principal, project_ids=[OBS_PROJECT[1]])
            ),
            "no_projects": name(reads.list_report_versions(principal, project_ids=[])),
        }
        for key, query in queries.items():
            answers[f"lines:{key}"] = name(reads.query_lines(principal, query))
        records = sorted(
            {line.record_id for line in reads.query_lines(principal, queries["all"])} - {None}
        )
        answers["records"] = _sorted(
            name(reads.lines_of_records(principal, [r for r in records if r]))
        )
        # Ordered by derivation id, which each side issues at random: compared as sets.
        answers["totals"] = _sorted(name(reads.stated_totals_of(principal, derivations)))
        answers["checks"] = _sorted(name(reads.cross_checks_of(principal, derivations)))
        answers["rfi_candidates"] = _sorted(
            name(reads.rfi_candidates(principal, rfis, [174, 17, 9]))
        )
    return answers


def _both(
    engine: Engine, step: Callable[[ReadsScene], None] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    fast, _ingest, _world = fast_scene()
    database = database_scene(engine)
    for scene in (fast, database):
        build_world(scene)
        if step is not None:
            step(scene)
    return _answers(fast), _answers(database)


def _assert_equal(fast: dict[str, Any], database: dict[str, Any]) -> None:
    assert fast.keys() == database.keys()
    for key in fast:
        assert fast[key] == database[key], key
    assert fast["lines:all"] and fast["records"] and fast["totals"]


def test_the_fake_reads_what_the_database_reads(migrated_engine: Engine) -> None:
    _assert_equal(*_both(migrated_engine))


def test_the_fake_reads_what_the_database_reads_after_rederivation(
    migrated_engine: Engine,
) -> None:
    def rederive(scene: ReadsScene) -> None:
        scene.correct("rfis")
        scene.rederive()
        scene.rederive(unknown_adapter_registry())

    _assert_equal(*_both(migrated_engine, rederive))
