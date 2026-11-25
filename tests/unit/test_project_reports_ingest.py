"""The project-report handler, the re-derivation sweep and their counts (WP3P-S5), FAST tier.

Over the synthetic fixtures through the real lifecycle, the real handler and
the real reader (`bootstrap.project_reports.PulseExportReader`), with the
in-memory worlds (`tests/unit/project_reports_scene.py`). Proved here:

* every fixture is ingested, rejected or quarantined with its closed counts,
  and the stored aggregate equals the file-level aggregate key for key;
* a short write (a line the repository drops) raises
  `ProjectReportsTotalsError` and rolls the snapshot back whole;
* a retired source's backfill fails each new snapshot `source_unbound` and
  writes nothing (ruling D12);
* the sweep leaves current derivations alone, re-derives an unknown signature
  once an adapter is registered (trigger a), a rebind (b) and a version bump
  (c), and writes nothing on a dry run;
* the cross-report check is written once, buyout on the left, in either
  arrival order;
* every count key is in the closed vocabulary.

The database tier is `tests/database/test_project_reports_ingest.py`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

import pytest

from my_pa.application.ingestion import RUN_COUNT_KEYS
from my_pa.application.project_reports_ingest import (
    RECORD_COUNT_KEYS,
    ProjectReportsTotalsError,
)
from my_pa.application.project_reports_rederive import REDERIVE_COUNT_KEYS
from my_pa.bootstrap.project_reports import PulseExportReader
from my_pa.contracts.ports import (
    ProjectReportLineRecord,
    ProjectReportRowRoleRecord,
    ProjectReportStatedTotalRecord,
)
from my_pa.domain.project_reports.model import (
    BindingState,
    DerivationState,
    DerivationTrigger,
    FamilyView,
    QuarantineReason,
    ValueKind,
)
from my_pa.infrastructure.project_reports import pulse_csv
from my_pa.infrastructure.project_reports.aggregate_cli import summarize_paths
from my_pa.infrastructure.project_reports.stored_aggregate import stored_counts
from tests import conftest
from tests.unit.project_reports_scene import FIXTURES, Scene, fixture_files


def _scene(*directories: str) -> Scene:
    scene = Scene()
    if directories:
        scene.place(directories)
    else:
        scene.place()
    return scene


def _currents(scene: Scene, directory: str | None = None) -> list[object]:
    with scene.unit() as unit:
        return list(
            unit.project_reports.list_current_derivations(
                scene.principal,
                ingest_source_id=None if directory is None else scene.sources[directory],
            )
        )


def test_every_fixture_is_ingested_and_the_stored_aggregate_is_the_file_aggregate() -> None:
    scene = _scene()
    runs = scene.backfill_all()
    for directory, counts in runs.items():
        assert counts["snapshots_failed"] == 0, directory
        assert set(counts) <= set(RUN_COUNT_KEYS) | RECORD_COUNT_KEYS
        files = len(fixture_files(directory))
        assert counts["snapshots_ingested"] + counts["snapshots_rejected"] == files
    assert runs["rejected"]["snapshots_rejected"] == len(fixture_files("rejected"))
    assert runs["variants"]["records_snapshot_quarantined"] == 3
    reports = scene.world.project_reports
    assert len(reports.snapshots) == sum(r["snapshots_ingested"] for r in runs.values())
    with scene.unit() as unit:
        stored = stored_counts(unit, scene.principal, list(scene.sources.values()))
    document, ok = summarize_paths(list(scene.project_numbers()), scene.project_numbers())
    assert ok
    assert stored == document["counts"]
    assert stored["cross_report.match"] == 1
    assert stored["sources.byte_identical_across_sources"] == 1


def test_a_short_write_raises_the_totals_error_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = _scene("two_level")
    stored = conftest._ProjectReports.insert_derivation_rows

    def short(
        self: object,
        principal_id: str,
        derivation_id: str,
        *,
        row_roles: Sequence[ProjectReportRowRoleRecord] = (),
        lines: Sequence[ProjectReportLineRecord] = (),
        stated_totals: Sequence[ProjectReportStatedTotalRecord] = (),
    ) -> None:
        """The repository, except that the derivation's last line is never stored."""
        stored(  # type: ignore[arg-type]
            self,
            principal_id,
            derivation_id,
            row_roles=row_roles,
            lines=lines[:-1],
            stated_totals=stated_totals,
        )

    monkeypatch.setattr(conftest._ProjectReports, "insert_derivation_rows", short)
    raised: list[BaseException] = []
    handler = scene.lifecycle._handlers[next(iter(scene.lifecycle._handlers))]
    original = handler.apply

    def apply(*args: object, **kwargs: object) -> object:
        try:
            return original(*args, **kwargs)  # type: ignore[arg-type]
        except BaseException as error:
            raised.append(error)
            raise

    monkeypatch.setattr(handler, "apply", apply)
    counts = scene.lifecycle.backfill(scene.principal, scene.sources["two_level"]).counts
    assert (counts["snapshots_failed"], counts["snapshots_ingested"]) == (1, 0)
    assert [type(error) for error in raised] == [ProjectReportsTotalsError]
    reports = scene.world.project_reports
    assert (len(reports.snapshots), len(reports.derivations), len(reports.records)) == (0, 0, 0)
    assert not scene.ingest.snapshots


def test_a_retired_source_is_unbound_and_its_backfill_writes_nothing() -> None:
    scene = _scene("signatures")
    scene.rebind("signatures", state=BindingState.RETIRED)
    counts = scene.lifecycle.backfill(scene.principal, scene.sources["signatures"]).counts
    files = len(fixture_files("signatures"))
    assert (counts["snapshots_failed"], counts["snapshots_ingested"]) == (files, 0)
    assert not scene.world.project_reports.snapshots
    assert not scene.ingest.snapshots


def test_the_sweep_leaves_current_derivations_alone() -> None:
    scene = _scene()
    scene.backfill_all()
    before = len(scene.world.project_reports.derivations)
    report = scene.rederiver().sweep(scene.principal)
    assert set(report.counts) <= REDERIVE_COUNT_KEYS
    assert report.counts["derivations_current"] == before
    assert not any(key.startswith("derivations_written") for key in report.counts)
    assert len(scene.world.project_reports.derivations) == before


def _with_unknown_registered() -> dict[str, pulse_csv.FamilyAdapter]:
    """The registry plus a test adapter for `variants/unknown_family.csv`'s header."""
    data = (FIXTURES / "variants" / "unknown_family.csv").read_bytes()
    header = pulse_csv.prepare_export(data).header.cells
    notes = next(a for a in pulse_csv.REGISTRY.values() if a.view is FamilyView.NOTES)
    fields = tuple(
        pulse_csv.FieldSpec(index, cell, f"note.synthetic_{index}", ValueKind.TEXT)
        for index, cell in enumerate(header)
    )
    adapter = dataclasses.replace(notes, fields=fields)
    return {**pulse_csv.REGISTRY, adapter.signature: adapter}


def test_an_unknown_signature_is_rederived_once_its_adapter_is_registered() -> None:
    scene = _scene("variants")
    scene.backfill_all()
    quarantined = [d for d in _currents(scene) if d.quarantine_reason is not None]  # type: ignore[attr-defined]
    unknown = [
        d
        for d in quarantined
        if d.quarantine_reason is QuarantineReason.UNKNOWN_HEADER_SIGNATURE  # type: ignore[attr-defined]
    ]
    assert len(unknown) == 2
    scene.use_reader(PulseExportReader(_with_unknown_registered()))
    count = len(scene.world.project_reports.derivations)
    dry = scene.rederiver().sweep(scene.principal, dry_run=True)
    assert dry.counts["derivations_due_rederive_adapter"] == 1
    assert len(scene.world.project_reports.derivations) == count  # the dry run wrote nothing
    report = scene.rederiver().sweep(scene.principal)
    assert report.counts["derivations_written_rederive_adapter"] == 1
    assert report.counts["derivations_current"] == 2
    states = sorted(d.state.value for d in _currents(scene))  # type: ignore[attr-defined]
    assert states == ["classified", "quarantined", "quarantined"]
    # Every Layer A row was kept; the new derivation classifies them.
    again = scene.rederiver().sweep(scene.principal)
    assert again.counts["derivations_current"] == 3


def test_a_rebind_and_a_version_bump_are_rederived() -> None:
    scene = _scene("signatures")
    scene.backfill_all()
    files = len(fixture_files("signatures"))
    scene.rebind("signatures", state=BindingState.ACTIVE, number="SYN-0999")
    report = scene.rederiver().sweep(scene.principal)
    assert report.counts["derivations_written_rederive_binding"] == files
    mismatched = [
        d
        for d in _currents(scene)
        if d.quarantine_reason is QuarantineReason.BINDING_PROJECT_NUMBER_MISMATCH  # type: ignore[attr-defined]
    ]
    assert len(mismatched) == 3  # the three financial views carry the bound number
    scene.rebind("signatures", state=BindingState.ACTIVE, number="SYN-0001")
    assert (
        scene.rederiver().sweep(scene.principal).counts["derivations_written_rederive_binding"]
        == files
    )
    assert all(d.state is DerivationState.CLASSIFIED for d in _currents(scene))  # type: ignore[attr-defined]
    bumped = {
        signature: dataclasses.replace(adapter, adapter_version="pulse_adapter_v2")
        if adapter.view is FamilyView.NOTES
        else adapter
        for signature, adapter in pulse_csv.REGISTRY.items()
    }
    scene.use_reader(PulseExportReader(bumped))
    report = scene.rederiver().sweep(scene.principal)
    assert report.counts["derivations_written_rederive_version"] == 1
    assert report.counts["derivations_current"] == files - 1


def test_the_sweep_limit_defers_the_rest() -> None:
    scene = _scene("signatures")
    scene.backfill_all()
    report = scene.rederiver().sweep(scene.principal, limit=2, rebuild=True)
    assert report.counts["derivations_written_operator_rebuild"] == 2
    assert report.counts["derivations_deferred"] == len(fixture_files("signatures")) - 2


def _paths(scene: Scene, *views: str) -> list[str]:
    names = scene.placed["signatures"]
    files = fixture_files("signatures")
    return [names[[f.stem for f in files].index(view)] for view in views]


@pytest.mark.parametrize(
    "order", [("buyout_summary", "reconciliation"), ("reconciliation", "buyout_summary")]
)
def test_the_cross_report_check_is_written_once_in_either_order(order: tuple[str, str]) -> None:
    scene = _scene("signatures")
    source = scene.sources["signatures"]
    counts: list[Mapping[str, int]] = []
    for path in _paths(scene, *order):
        counts.append(scene.lifecycle.backfill(scene.principal, source, paths=[path]).counts)
    assert "records_cross_checks_match" not in counts[0]
    assert counts[1]["records_cross_checks_match"] == 1
    checks = list(scene.world.project_reports.cross_checks.values())
    assert len(checks) == 1
    derivations = scene.world.project_reports.derivations
    left = next(d for (_, i), d in derivations.items() if i == checks[0].left_derivation_id)
    right = next(d for (_, i), d in derivations.items() if i == checks[0].right_derivation_id)
    assert (left.family_view, right.family_view) == (
        FamilyView.BUYOUT_SUMMARY,
        FamilyView.RECONCILIATION,
    )
    # The rest of the folder and a rebuild write no second check for the same pair.
    scene.lifecycle.backfill(scene.principal, source)
    assert len(scene.world.project_reports.cross_checks) == 1


def test_a_rebuild_writes_a_cross_check_for_the_new_pair() -> None:
    scene = _scene("signatures")
    scene.backfill_all()
    scene.rederiver().sweep(scene.principal, rebuild=True)
    checks = scene.world.project_reports.cross_checks
    # The first pair, then the rebuilt buyout with the old reconciliation, then the new pair.
    assert len(checks) >= 2
    with scene.unit() as unit:
        stored = stored_counts(unit, scene.principal, [scene.sources["signatures"]])
    assert stored["cross_report.match"] == 1


def test_the_dry_run_counts_and_writes_nothing() -> None:
    scene = _scene()
    before = (len(scene.ingest.snapshots), len(scene.world.project_reports.snapshots))
    writes = list(scene.ingest.writes)
    for directory, source in scene.sources.items():
        report = scene.lifecycle.backfill(scene.principal, source, dry_run=True)
        assert report.run_id is None, directory
    assert (len(scene.ingest.snapshots), len(scene.world.project_reports.snapshots)) == before
    assert scene.ingest.writes == writes


def test_the_count_vocabularies_are_closed_names() -> None:
    for key in RECORD_COUNT_KEYS:
        assert key.startswith("records_") and key.replace("_", "").isalnum()
    for key in REDERIVE_COUNT_KEYS:
        assert key.startswith("derivations_") and key.replace("_", "").isalnum()
    assert "derivations_written_ingest" not in REDERIVE_COUNT_KEYS
    assert f"derivations_written_{DerivationTrigger.OPERATOR_REBUILD.value}" in REDERIVE_COUNT_KEYS
