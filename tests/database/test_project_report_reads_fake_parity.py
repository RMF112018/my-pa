"""WP4P-S2: the FAST reads fake answers what PostgreSQL answers (the WP3P-S4 lesson).

The same synthetic world is built through the same WP3P path, in the same
order under the same clock, over the fakes (`tests.conftest._ProjectReportReads`)
and over a head-migrated clone (`SqlProjectReportReadsRepository`). Every read
method is then called with the same arguments on both, and the answers must be
equal once the identifiers each side issued at random (sources, snapshots,
derivations, binding revisions, records, series) are replaced by what they
name. Answers are compared in order, except those ordered by an identifier
each side issued at random (`lines_of_records` by record, the stated totals,
cross-checks and RFI candidates by derivation), compared as sets.

The world is `build_world` plus the service cases' `extend_world` (Decimal
money in the buyout and reconciliation exports, a current cross-check and,
after the buyout alone is re-derived, a stale one beside it, ruling A4), and a
second Principal's world that must never be answered to the first (ruling
R1-05). Every answer but the ones meant to be empty must be non-empty, so a
read the fake answers wrongly cannot pass by answering nothing on both sides.
Every value is synthetic.
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
    RFI_LATER,
    RFI_PROJECT,
    RFI_ROWS_LATER,
    ReadsScene,
    build_world,
    database_scene,
    fast_scene,
    rfi_export,
    unknown_adapter_registry,
)
from tests.unit.project_reports_reads_service_cases import (
    PAIR_PROJECT,
    extend_world,
    rederive_the_buyout_alone,
)

pytestmark = pytest.mark.database

OTHER_PRINCIPAL: Final = "prn_synotherreads01"
#: The second Principal's Project: its own id, the first Principal's number.
OTHER_PROJECT: Final = ("rfis", "prj_synreadsother1x", RFI_PROJECT[2])
#: Answers meant to be empty: no Project named, a text across two fields,
#: every read of the first Principal over the second Principal's identifiers,
#: and every child read over a derivation the step superseded (R2-04).
_SUPERSEDED: Final = ("totals", "checks", "rfi_candidates", "lines")
_EMPTY: Final = frozenset(
    {"no_projects", "lines:boundary", "foreign", *(f"superseded:{k}" for k in _SUPERSEDED)}
)
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


def _answers(scene: ReadsScene, principal: str) -> dict[str, Any]:
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
            # Ruling R1-08: one engine folds both sides, so `İ` matches itself on both.
            "text_non_ascii": ProjectReportLineQuery(
                derivation_ids=rfis, limit=1000, text="délta İOTA", text_fields=fields
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
        # A record names the derivation that created it, which may since be superseded.
        answers["find_records"] = tuple(
            name(
                tuple(
                    dataclasses.replace(
                        entry,
                        created_by_derivation_id=name.names.get(
                            entry.created_by_derivation_id, "derivation:superseded"
                        ),
                    )
                    for entry in reads.find_records(principal, project, family, key)
                )
            )
            for project, family, key in (
                (RFI_PROJECT[1], RecordFamily.RFIS, "rfi:GMP-174"),
                (RFI_PROJECT[1], RecordFamily.RFIS, "rfi:GMP-170"),
                (OTHER_PROJECT[1], RecordFamily.RFIS, "rfi:GMP-174"),
            )
            if reads.find_records(principal, project, family, key)
        )
    return answers


def _foreign(scene: ReadsScene) -> tuple[object, ...]:
    """The first Principal's reads over every identifier the second Principal holds."""
    with scene.unit() as unit:
        reads = unit.project_report_reads
        theirs = reads.list_report_versions(OTHER_PRINCIPAL)
        derivations = tuple(v.derivation_id for v in theirs)
        assert derivations, "the second Principal's world was seeded"
        lines = reads.query_lines(
            OTHER_PRINCIPAL, ProjectReportLineQuery(derivation_ids=derivations, limit=1000)
        )
        records = [line.record_id for line in lines if line.record_id]
        assert records
        mine = scene.principal
        return tuple(
            answer
            for answer in (
                reads.list_report_versions(mine, project_ids=[OTHER_PROJECT[1]]),
                reads.query_lines(
                    mine, ProjectReportLineQuery(derivation_ids=derivations, limit=1000)
                ),
                reads.lines_of_records(mine, records),
                reads.stated_totals_of(mine, derivations),
                reads.cross_checks_of(mine, derivations),
                reads.rfi_candidates(mine, derivations, [174]),
                reads.find_records(mine, OTHER_PROJECT[1], RecordFamily.RFIS, "rfi:GMP-174"),
            )
            if answer
        )


def _child_reads(scene: ReadsScene, derivations: tuple[str, ...]) -> dict[str, tuple[object, ...]]:
    """The child reads over named derivations, raw (identifiers as each side issued them)."""
    with scene.unit() as unit:
        reads = unit.project_report_reads
        mine = scene.principal
        return {
            "totals": tuple(reads.stated_totals_of(mine, derivations)),
            "checks": tuple(reads.cross_checks_of(mine, derivations)),
            "rfi_candidates": tuple(reads.rfi_candidates(mine, derivations, [174, 17, 9])),
            "lines": tuple(
                reads.query_lines(
                    mine, ProjectReportLineQuery(derivation_ids=derivations, limit=1000)
                )
            ),
        }


def _derivation_ids(scene: ReadsScene) -> tuple[str, ...]:
    with scene.unit() as unit:
        versions = unit.project_report_reads.list_report_versions(scene.principal)
        return tuple(v.derivation_id for v in versions)


def _other_world(scene: ReadsScene) -> ReadsScene:
    """A second Principal's RFI world over the same unit of work and clock."""
    other = ReadsScene(
        unit=scene.unit,
        add_project=scene.add_project,
        clock=scene.clock,
        principal_id=OTHER_PRINCIPAL,
    )
    other.bind(*OTHER_PROJECT)
    other.ingest("rfis", RFI_LATER, rfi_export(RFI_ROWS_LATER))
    return other


def _both(
    engine: Engine, step: Callable[[ReadsScene], None] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    fast, _ingest, _world = fast_scene()
    database = database_scene(engine)
    answered: list[dict[str, Any]] = []
    for scene in (fast, database):
        build_world(scene)
        extend_world(scene)
        other = _other_world(scene)
        before = _derivation_ids(scene)
        held = _child_reads(scene, before)
        if step is not None:
            step(scene)
        current = set(_derivation_ids(scene))
        # Ruling R2-04: the child reads are also called with the derivation ids the
        # step superseded, so a fake that ignores "current" answers them and differs.
        superseded = tuple(d for d in before if d not in current)
        answers = _answers(scene, scene.principal)
        if superseded:
            stale = set(superseded)
            for key, answer in _child_reads(scene, superseded).items():
                answers[f"superseded:{key}"] = answer
                # What those derivations held before the step (a count, so both sides compare).
                answers[f"superseded_held:{key}"] = sum(
                    1 for entry in held[key] if stale & set(map(str, _strings(entry)))
                )
        answers["foreign"] = _foreign(scene)
        answers["other"] = _answers(other, OTHER_PRINCIPAL)
        answered.append(answers)
    return answered[0], answered[1]


def _strings(entry: object) -> tuple[str, ...]:
    """Every string field of a dataclass answer, one level deep."""
    assert dataclasses.is_dataclass(entry) and not isinstance(entry, type)
    found: list[str] = []
    for f in dataclasses.fields(entry):
        value = getattr(entry, f.name)
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, tuple):
            found.extend(item for item in value if isinstance(item, str))
    return tuple(found)


def _assert_equal(fast: dict[str, Any], database: dict[str, Any]) -> None:
    assert fast.keys() == database.keys()
    for key in fast:
        assert fast[key] == database[key], key
    for key, answer in fast.items():
        if key.startswith("superseded_held:"):
            continue
        assert (not answer) is (key in _EMPTY), key
    other = fast["other"]
    assert other["versions"] and other["lines:all"] and other["records"]
    assert other["find_records"]
    # Real Decimal money crosses the comparison, and both checks are stored (A4).
    assert any("buyout" in repr(entry) for entry in fast["lines:all"])
    assert "Decimal(" in repr(fast["lines:all"])


def _rederive_the_buyout(scene: ReadsScene) -> None:
    """Ruling A4: the first cross-check now names a superseded buyout, so it is stale."""
    rederive_the_buyout_alone(scene)
    with scene.unit() as unit:
        checks = unit.project_reports.list_cross_checks(scene.principal, PAIR_PROJECT[1])
    assert sorted(c.outcome.value for c in checks) == ["match", "mismatch"]


def test_the_fake_reads_what_the_database_reads(migrated_engine: Engine) -> None:
    fast, database = _both(migrated_engine, _rederive_the_buyout)
    _assert_equal(fast, database)
    # Only the current check is answered: the stale one names a superseded side.
    assert len(fast["checks"]) == 1


def test_the_fake_reads_what_the_database_reads_after_rederivation(
    migrated_engine: Engine,
) -> None:
    def rederive(scene: ReadsScene) -> None:
        scene.correct("rfis")
        scene.correct("observations")
        scene.rederive()
        scene.rederive(unknown_adapter_registry())

    fast, database = _both(migrated_engine, rederive)
    _assert_equal(fast, database)
    # R2-04: the superseded derivations held lines, stated totals and RFI
    # candidates before the step, so their empty answers are not vacuous.
    for key in ("totals", "rfi_candidates", "lines"):
        assert fast[f"superseded_held:{key}"] > 0, key
