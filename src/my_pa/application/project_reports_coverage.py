"""Coverage of the project-report sources, from stored rows (WP3P-S5; rulings D4, D8, D10).

`project_reports_coverage` reads, per source, its lifecycle snapshots and its
**report series**: the ingested snapshots grouped by `(slug label, header
signature)` (`domain.project_reports.labels.series_key`; ruling D4: derived at
read time from the earliest-first-seen path of each snapshot, never stored).
Per series it answers the number of versions, the earliest and latest date
labels (as ISO dates), the first and last first-seen instants, the freshness
in seconds of the latest version (by the total order of ruling D10:
`version_order_key`), the completeness classes and quarantine reasons of the
current derivations, and the filter semantics: `operator_declared` when the
source's current revision declares a filter for the series' slug at or before
the latest version was first seen (ruling D8 (i)), else `unknown`.

Nothing here writes. The answer holds identifiers, closed codes, counts,
dates and instants only: never a path, a file or slug name, a signature or a
cell (the series is an index).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from my_pa.application.project_reports_ingest import snapshot_labels
from my_pa.contracts.ports import (
    IngestConsumer,
    IngestSnapshotStatus,
    UnitOfWork,
)
from my_pa.domain.project_reports.model import BindingState, DerivationState, FilterSemantics
from my_pa.domain.project_reports.versions import VersionRef, latest_version

__all__ = ["SeriesCoverage", "SourceCoverage", "project_reports_coverage"]


@dataclass(frozen=True, slots=True)
class SeriesCoverage:
    family_view: str | None
    versions: int
    earliest_date_label: str | None
    latest_date_label: str | None
    first_seen: datetime
    last_seen: datetime
    freshness_seconds: int
    filter_semantics: FilterSemantics
    completeness: dict[str, int] = field(default_factory=dict)
    quarantined: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    ingest_source_id: str
    enabled: bool
    binding_state: str | None
    project_number: str | None
    snapshots: int
    ingested: int
    rejected: int
    quarantined: int
    series: tuple[SeriesCoverage, ...]


def _iso_date(label: str | None) -> str | None:
    return None if label is None else f"{label[:4]}-{label[4:6]}-{label[6:]}"


def project_reports_coverage(
    unit: UnitOfWork,
    principal_id: str,
    ingest_source_ids: Sequence[str] | None,
    *,
    now: datetime,
) -> tuple[SourceCoverage, ...]:
    """Coverage of the given sources (or every project-report source), in source order."""
    ingestion, repository = unit.ingestion, unit.project_reports
    sources = [
        source
        for source in ingestion.list_sources(principal_id)
        if source.consumer is IngestConsumer.PULSE_CSV_EXPORT
        and (ingest_source_ids is None or source.ingest_source_id in ingest_source_ids)
    ]
    answer: list[SourceCoverage] = []
    for source in sources:
        source_id = source.ingest_source_id
        binding = repository.get_binding(principal_id, source_id)
        revision = (
            None
            if binding is None
            else repository.get_binding_revision(principal_id, binding.binding_revision_id)
        )
        declarations = (
            {}
            if revision is None or revision.state is not BindingState.ACTIVE
            else {
                d.slug_label: d.declared_at
                for d in repository.list_filter_declarations(
                    principal_id, revision.binding_revision_id
                )
            }
        )
        snapshots = ingestion.list_snapshots(principal_id, source_id)
        groups: dict[
            tuple[str | None, str], list[tuple[VersionRef, str | None, str | None, str | None]]
        ] = {}
        quarantined = 0
        for snapshot in snapshots:
            if snapshot.status is not IngestSnapshotStatus.INGESTED:
                continue
            head = repository.get_snapshot(principal_id, snapshot.snapshot_id)
            derivation = repository.current_derivation(principal_id, snapshot.snapshot_id)
            if head is None or derivation is None:
                continue
            labels = snapshot_labels(unit, principal_id, snapshot.snapshot_id)
            version = VersionRef(snapshot.snapshot_id, labels.date_label, snapshot.first_seen_at)
            view = None if derivation.family_view is None else derivation.family_view.value
            if derivation.state is DerivationState.QUARANTINED:
                quarantined += 1
                state = (
                    None
                    if derivation.quarantine_reason is None
                    else derivation.quarantine_reason.value
                )
                completeness = None
            else:
                state = None
                completeness = (
                    None
                    if derivation.completeness_class is None
                    else derivation.completeness_class.value
                )
            groups.setdefault((labels.slug_label, head.header_signature), []).append(
                (version, view, completeness, state)
            )
        series: list[SeriesCoverage] = []
        for (slug, _signature), versions in sorted(
            groups.items(), key=lambda item: min(v[0].first_seen_at for v in item[1])
        ):
            refs = [v[0] for v in versions]
            latest = latest_version(refs)
            assert latest is not None  # noqa: S101 - a series has a version
            labelled = sorted(ref.date_label for ref in refs if ref.date_label is not None)
            declared = declarations.get(slug) if slug is not None else None
            series.append(
                SeriesCoverage(
                    family_view=next((v[1] for v in versions if v[1] is not None), None),
                    versions=len(versions),
                    earliest_date_label=_iso_date(labelled[0]) if labelled else None,
                    latest_date_label=_iso_date(labelled[-1]) if labelled else None,
                    first_seen=min(ref.first_seen_at for ref in refs),
                    last_seen=max(ref.first_seen_at for ref in refs),
                    freshness_seconds=max(0, int((now - latest.first_seen_at).total_seconds())),
                    filter_semantics=FilterSemantics.OPERATOR_DECLARED
                    if declared is not None and declared <= latest.first_seen_at
                    else FilterSemantics.UNKNOWN,
                    completeness=dict(sorted(Counter(v[2] for v in versions if v[2]).items())),
                    quarantined=dict(sorted(Counter(v[3] for v in versions if v[3]).items())),
                )
            )
        answer.append(
            SourceCoverage(
                ingest_source_id=source_id,
                enabled=source.enabled,
                binding_state=None if binding is None else binding.state.value,
                project_number=None if revision is None else revision.declared_project_number,
                snapshots=len(snapshots),
                ingested=sum(1 for s in snapshots if s.status is IngestSnapshotStatus.INGESTED),
                rejected=sum(1 for s in snapshots if s.status is IngestSnapshotStatus.REJECTED),
                quarantined=quarantined,
                series=tuple(series),
            )
        )
    return tuple(answer)
