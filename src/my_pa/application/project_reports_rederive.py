"""Bounded re-derivation of stored project-report snapshots (WP3P-S5; rulings D9, D10, D11).

`ProjectReportsRederiver.sweep` re-derives a snapshot **from its stored Layer
A rows**, never from the file, and appends a derivation superseding the
current one (nothing is updated; the current derivation is the one nothing
supersedes). A snapshot is due when its current derivation:

* (a) is quarantined `unknown_header_signature` and the reader now registers
  the signature: trigger `rederive_adapter`;
* (b) names a binding revision that is no longer its source's current one (a
  correction or a rebind; ruling D11 re-derives a project-number quarantine
  this way): trigger `rederive_binding`;
* (c) was written under an adapter, identity or status-map version other than
  the reader's: trigger `rederive_version`;
* or, only when the operator asks (`rebuild=True`), any other current
  derivation: trigger `operator_rebuild`.

A source with no active binding is never re-derived (`derivations_skipped_unbound`).
Each snapshot is re-derived in its own transaction through the handler's own
`write_derivation`, so a failure rolls back that snapshot alone and is counted
`derivations_failed`. At most `limit` snapshots are attempted per sweep; the
rest wait for the next (`derivations_deferred`). A dry run decides and counts
(`derivations_due_<trigger>`) and writes nothing.

Counts are the closed `REDERIVE_COUNT_KEYS`, never content. Nothing here logs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.application.project_reports_ingest import ExportReader, write_derivation
from my_pa.contracts.ports import ProjectReportDerivationRecord, UnitOfWork
from my_pa.domain.common.time import utc_now
from my_pa.domain.project_reports.model import (
    BindingState,
    DerivationState,
    DerivationTrigger,
    QuarantineReason,
)

__all__ = [
    "DEFAULT_SWEEP_LIMIT",
    "REDERIVE_COUNT_KEYS",
    "ProjectReportsRederiver",
    "RederiveReport",
]

DEFAULT_SWEEP_LIMIT: Final = 100
_REDERIVE_TRIGGERS: Final = tuple(t for t in DerivationTrigger if t is not DerivationTrigger.INGEST)
_BASE_KEYS: Final = (
    "derivations_checked",
    "derivations_current",
    "derivations_skipped_unbound",
    "derivations_deferred",
    "derivations_failed",
)
#: Every key a sweep's counts may carry.
REDERIVE_COUNT_KEYS: Final = frozenset(
    {
        *_BASE_KEYS,
        *(f"derivations_due_{t.value}" for t in _REDERIVE_TRIGGERS),
        *(f"derivations_written_{t.value}" for t in _REDERIVE_TRIGGERS),
    }
)


@dataclass(frozen=True, slots=True)
class RederiveReport:
    dry_run: bool
    counts: Mapping[str, int]


class ProjectReportsRederiver:
    """The re-derivation sweep (module docstring)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        reader: ExportReader,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._reader = reader
        self._clock = clock

    def _due(
        self,
        unit: UnitOfWork,
        principal_id: str,
        current: ProjectReportDerivationRecord,
        *,
        rebuild: bool,
    ) -> DerivationTrigger | str | None:
        """The trigger a current derivation is due under, `"unbound"`, or `None`."""
        repository = unit.project_reports
        binding = repository.get_binding(principal_id, current.ingest_source_id)
        if binding is None or binding.state is not BindingState.ACTIVE:
            return "unbound"
        reader = self._reader
        if (
            current.state is DerivationState.QUARANTINED
            and current.quarantine_reason is QuarantineReason.UNKNOWN_HEADER_SIGNATURE
        ):
            head = repository.get_snapshot(principal_id, current.snapshot_id)
            if head is not None and reader.adapter_version(head.header_signature) is not None:
                return DerivationTrigger.REDERIVE_ADAPTER
        if current.binding_revision_id != binding.binding_revision_id:
            return DerivationTrigger.REDERIVE_BINDING
        stale = (
            current.identity_version != reader.identity_version
            or current.status_map_version != reader.status_map_version
        )
        if not stale and current.adapter_version is not None:
            head = repository.get_snapshot(principal_id, current.snapshot_id)
            registered = None if head is None else reader.adapter_version(head.header_signature)
            stale = registered is not None and registered != current.adapter_version
        if stale:
            return DerivationTrigger.REDERIVE_VERSION
        return DerivationTrigger.OPERATOR_REBUILD if rebuild else None

    def sweep(
        self,
        principal_id: str,
        *,
        limit: int = DEFAULT_SWEEP_LIMIT,
        ingest_source_id: str | None = None,
        dry_run: bool = False,
        rebuild: bool = False,
    ) -> RederiveReport:
        if type(limit) is not int or limit < 1:
            raise ValueError("a sweep limit is a positive integer")
        counts: Counter[str] = Counter(dict.fromkeys(_BASE_KEYS, 0))
        with self._unit_of_work() as unit:
            currents = unit.project_reports.list_current_derivations(
                principal_id, ingest_source_id=ingest_source_id
            )
            due: list[tuple[ProjectReportDerivationRecord, DerivationTrigger]] = []
            for current in currents:
                counts["derivations_checked"] += 1
                trigger = self._due(unit, principal_id, current, rebuild=rebuild)
                if trigger == "unbound":
                    counts["derivations_skipped_unbound"] += 1
                elif isinstance(trigger, DerivationTrigger):
                    due.append((current, trigger))
                else:
                    counts["derivations_current"] += 1
        for index, (current, trigger) in enumerate(due):
            if index >= limit:
                counts["derivations_deferred"] += 1
                continue
            if dry_run:
                counts[f"derivations_due_{trigger.value}"] += 1
                continue
            try:
                written = self._rederive(principal_id, current, rebuild=rebuild)
            except Exception:  # this snapshot rolls back; the sweep continues
                counts["derivations_failed"] += 1
                continue
            if written is None:
                counts["derivations_current"] += 1
            else:
                counts[f"derivations_written_{written.value}"] += 1
        return RederiveReport(dry_run=dry_run, counts=dict(sorted(counts.items())))

    def _rederive(
        self, principal_id: str, seen: ProjectReportDerivationRecord, *, rebuild: bool
    ) -> DerivationTrigger | None:
        """One snapshot, in its own transaction, re-checked under it."""
        with self._unit_of_work() as unit:
            repository = unit.project_reports
            current = repository.current_derivation(principal_id, seen.snapshot_id)
            if current is None or current.derivation_id != seen.derivation_id:
                return None  # another writer re-derived it first
            trigger = self._due(unit, principal_id, current, rebuild=rebuild)
            if not isinstance(trigger, DerivationTrigger):
                return None
            binding = repository.get_binding(principal_id, current.ingest_source_id)
            assert binding is not None  # noqa: S101 - `_due` answered a trigger
            revision = repository.get_binding_revision(principal_id, binding.binding_revision_id)
            if revision is None:
                raise LookupError("a binding names its revision")
            write_derivation(
                unit,
                principal_id,
                reader=self._reader,
                snapshot_id=current.snapshot_id,
                ingest_source_id=current.ingest_source_id,
                revision=revision,
                trigger=trigger,
                supersedes_derivation_id=current.derivation_id,
                derived_at=self._clock(),
            )
        return trigger
