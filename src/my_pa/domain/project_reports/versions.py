"""Comparing the versions of one report series (plan section 6.3; ruling D10).

"Latest" is computed, never stored, by a total order: the publication date
label (an unlabelled version first), then the lifecycle's first-seen time, then
the snapshot identifier, so arrival order never decides it.

**Closure is never inferred from disappearance.** A record absent from the
latest version is `not_observed_in_latest`; its status stays as it was last
observed, with the version that observed it. Only a status column of a later
version changes a status.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from my_pa.domain.project_reports.model import StatusClass, VersionPresence

__all__ = [
    "RecordObservation",
    "RecordPresence",
    "VersionRef",
    "compare_versions",
    "latest_version",
    "version_order_key",
]


@dataclass(frozen=True, slots=True)
class VersionRef:
    snapshot_id: str
    date_label: str | None
    first_seen_at: datetime


@dataclass(frozen=True, slots=True)
class RecordObservation:
    """One record as one version observed it (its status as exported, classified)."""

    version: VersionRef
    record_key: str
    status: StatusClass | None = None


@dataclass(frozen=True, slots=True)
class RecordPresence:
    presence: VersionPresence
    last_observed: VersionRef
    last_status: StatusClass | None


def version_order_key(version: VersionRef) -> tuple[bool, str, datetime, str]:
    return (
        version.date_label is not None,
        version.date_label or "",
        version.first_seen_at,
        version.snapshot_id,
    )


def latest_version(versions: Iterable[VersionRef]) -> VersionRef | None:
    ordered = sorted(versions, key=version_order_key)
    return ordered[-1] if ordered else None


def compare_versions(
    versions: Sequence[VersionRef], observations: Iterable[RecordObservation]
) -> Mapping[str, RecordPresence]:
    """Each record's presence in the latest version and its last observation."""
    latest = latest_version(versions)
    known = set(versions)
    last: dict[str, RecordObservation] = {}
    for observation in observations:
        if observation.version not in known:
            raise ValueError("an observation names a version outside the series")
        current = last.get(observation.record_key)
        if current is None or version_order_key(observation.version) > version_order_key(
            current.version
        ):
            last[observation.record_key] = observation
    return MappingProxyType(
        {
            key: RecordPresence(
                VersionPresence.OBSERVED_IN_LATEST
                if observation.version == latest
                else VersionPresence.NOT_OBSERVED_IN_LATEST,
                observation.version,
                observation.status,
            )
            for key, observation in sorted(last.items())
        }
    )
