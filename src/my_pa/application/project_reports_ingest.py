"""The project-report consumer's lifecycle handler (WP3P; ruling D5). S4: admission only.

The project-reports lifecycle is a separate `IngestionLifecycle` instance whose
handler registry holds exactly one handler, for `pulse_csv_export`, composed in
`bootstrap/project_reports.py` and nowhere else. The communications lifecycle
never holds it, so the generic `apps/cli/communications_ingest.py admit`
refuses the consumer (`consumer_not_registered`): a project-report source is
admitted only by `bindings apply`, in the same transaction as its binding
(ruling D7).

**S4 registers the consumer for admission only.** The lifecycle admits a
consumer only when it holds a handler for it, and the reading handler (Layer A,
derivations) is slice S5. Until then `AdmissionOnlyHandler` stands in: it
declares the consumer, the reader version and the 16 MiB bound (ruling D17),
and refuses to read. `prepare` raises, so a run that reached it (none is wired
in S4: no worker step, no `run-once` or `backfill` command) would count each
file `snapshots_failed` and write no snapshot row -- never a rejection, which
would mark the bytes as seen forever. S5 replaces this class with the reading
handler in this module.
"""

from __future__ import annotations

from typing import Final

from my_pa.contracts.ports import (
    IngestApplied,
    IngestConsumer,
    IngestConsumerHandler,
    IngestPrepared,
    IngestSnapshotRecord,
    UnitOfWork,
)

__all__ = [
    "MAX_EXPORT_BYTES",
    "READER_VERSION",
    "AdmissionOnlyHandler",
    "ProjectReportsNotReadableError",
]

#: Ruling D17: the reader version and the largest export read.
READER_VERSION: Final = "pulse_csv_reader_v1"
MAX_EXPORT_BYTES: Final = 16 * 1024 * 1024


class ProjectReportsNotReadableError(RuntimeError):
    """The admission-only handler was asked to read (S5 provides the reader)."""


class AdmissionOnlyHandler(IngestConsumerHandler):
    """The `pulse_csv_export` registration that admits sources and reads nothing."""

    @property
    def consumer(self) -> IngestConsumer:
        return IngestConsumer.PULSE_CSV_EXPORT

    @property
    def parser_version(self) -> str:
        return READER_VERSION

    @property
    def max_bytes(self) -> int:
        return MAX_EXPORT_BYTES

    def prepare(self, data: bytes) -> IngestPrepared:
        raise ProjectReportsNotReadableError("the project-report reader is slice S5")

    def apply(
        self,
        unit: UnitOfWork,
        principal_id: str,
        snapshot: IngestSnapshotRecord,
        prepared: IngestPrepared,
    ) -> IngestApplied:
        raise ProjectReportsNotReadableError("the project-report reader is slice S5")
