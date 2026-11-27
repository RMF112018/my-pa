"""Composition of the ingestion consumers (WP3a, Manager ruling M5; WP3b).

The one place each consumer's parser (infrastructure) meets its lifecycle
handler (application): `communications_handler()` injects the
`communications_evidence_v2` parser into `CommunicationsEvidenceHandler`, and
`meeting_sync_handler()` injects the `meeting_sync_v1` parser (v2) into
`MeetingSyncHandler`, which stages and never applies (WP3b, ruling D1).

`ingestion_lifecycle()` and `coverage_reader()` are what the operator CLI
(`apps/cli/communications_ingest.py`) and the cycles-plane poll step
(`apps/worker.py run --plane cycles`) both build, so the two cannot compose
the lifecycle differently:

* **No audit rows (ruling m8).** Admission and runs are operator
  configuration and a background step, not capabilities; their evidence is the
  lifecycle rows. The unit of work's audit sink refuses, so an attempt to audit
  is a defect that fails loudly rather than a row nobody asked for.
* **Applying is the applier's (WP3b-S3).** `meeting_sync_applier()` builds
  `MeetingSyncApplier` over the same refusing-audit transactions; the cycles
  step calls it after `poll_enabled`, the CLI after `run-once` and `backfill`,
  both under `COMMS_INGEST_LOCK_KEY`. It applies nothing until the
  reconciliation latch exists (ruling D4).
* **The rederive (WP4-S3).** `communications_rederiver()` builds
  `CommunicationsRederiver` over the same refusing-audit transactions, the same
  lazily composed workspace stores and the same parser and byte bound as the
  handler, so a rederive reads a file exactly as ingestion read it. The CLI's
  `rederive` runs it under `COMMS_INGEST_LOCK_KEY`.
* **The context measurement (WP5-S6).** `meeting_context_measurement()`
  builds `MeetingContextMeasurement` over the same refusing-audit
  transactions, with the probe-fact reads (`meeting_context_probe_facts`, the
  `identity_kind_mismatch` quarantine count) and a statement counter on the
  engine (`before_cursor_execute`). It reads only; the CLI's
  `measure-context` takes no lock.
* **The workspace stores come from settings, once.** `MY_PA_FILES_WORKSPACES`
  (or the single-root form) composed by `bootstrap.gateway.files_workspace_stores`
  with every overlap root, so a `read_only` workspace is refused unless it is
  mounted read-only (`ST_RDONLY`). The lifecycle calls only `list_directory`,
  `stat` and `open_download` on them (ruling m5, guarded). Composition is lazy:
  a command that reads no file (enable, disable, coverage, aggregate) never
  touches a workspace root.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import Engine, event

from my_pa.application.communications_ingest import (
    CommunicationsCoverageReader,
    CommunicationsEvidenceHandler,
    ParsedPublication,
)
from my_pa.application.communications_rederive import (
    DEFAULT_REDERIVE_LIMIT,
    MAX_REDERIVE_LIMIT,
    CommunicationsRederiver,
)
from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.application.meeting_context_measure import DEFAULT_RUNS as DEFAULT_CONTEXT_RUNS
from my_pa.application.meeting_context_measure import (
    MAX_PROBE_ATTENDEES,
    MIN_PROBE_PARTICIPANTS,
    PROBE_IDENTIFIERS,
    MeetingContextMeasurement,
    ProbeFacts,
)
from my_pa.application.meeting_context_measure import MAX_RUNS as MAX_CONTEXT_RUNS
from my_pa.application.meeting_sync_apply import MeetingSyncApplier
from my_pa.application.meeting_sync_ingest import MeetingSyncHandler, ParsedMeetingSync
from my_pa.bootstrap.gateway import files_workspace_stores
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import AuditSink, FileWorkspaceStore, UnitOfWork
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.common.time import utc_now
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION
from my_pa.domain.meeting.context import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_PER_MEETING_LIMIT,
    MAX_CONTEXT_MEETINGS,
    MAX_LOOKBACK_DAYS,
    MAX_PER_MEETING_LIMIT,
)
from my_pa.infrastructure.communications.evidence_v2 import (
    MAX_PUBLICATION_BYTES,
    PARSER_VERSION,
    parse_publication,
)
from my_pa.infrastructure.meeting_sync import parser as meeting_sync_parser
from my_pa.infrastructure.persistence.communications import (
    meeting_context_probe_facts,
    quarantined_reason_count,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "DEFAULT_CONTEXT_RUNS",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_PER_MEETING_LIMIT",
    "DEFAULT_REDERIVE_LIMIT",
    "IDENTIFIER_VERSION",
    "MAX_CONTEXT_MEETINGS",
    "MAX_CONTEXT_RUNS",
    "MAX_LOOKBACK_DAYS",
    "MAX_PER_MEETING_LIMIT",
    "MAX_REDERIVE_LIMIT",
    "communications_handler",
    "communications_rederiver",
    "coverage_reader",
    "ingest_unit_of_work",
    "ingest_workspace_stores",
    "ingestion_lifecycle",
    "meeting_context_measurement",
    "meeting_sync_applier",
    "meeting_sync_handler",
    "parse_for_ingestion",
    "parse_meeting_sync_for_ingestion",
]


def parse_for_ingestion(data: bytes) -> ParsedPublication:
    """`parse_publication`, as the handler's injected parser answer."""
    parsed = parse_publication(data)
    return ParsedPublication(
        publication=parsed.publication,
        rejection=parsed.rejection,
        diagnostic_counts=parsed.diagnostics.code_counts,
    )


def communications_handler() -> CommunicationsEvidenceHandler:
    """The `communications_evidence_v2` handler with the WP1 parser wired in."""
    return CommunicationsEvidenceHandler(
        parse=parse_for_ingestion,
        parser_version=PARSER_VERSION,
        max_bytes=MAX_PUBLICATION_BYTES,
    )


def parse_meeting_sync_for_ingestion(data: bytes) -> ParsedMeetingSync:
    """The `meeting_sync_v1` `parse_publication`, as the handler's injected parser answer."""
    parsed = meeting_sync_parser.parse_publication(data)
    return ParsedMeetingSync(
        publication=parsed.publication,
        rejection=parsed.rejection,
        diagnostic_counts=parsed.diagnostics.code_counts,
    )


def meeting_sync_handler(*, clock: Callable[[], datetime] = utc_now) -> MeetingSyncHandler:
    """The `meeting_sync_v1` staging handler with the parser v2 wired in."""
    return MeetingSyncHandler(
        parse=parse_meeting_sync_for_ingestion,
        parser_version=meeting_sync_parser.PARSER_VERSION,
        max_bytes=meeting_sync_parser.MAX_PUBLICATION_BYTES,
        clock=clock,
    )


class _IngestionWritesNoAudit(AuditSink):
    """The audit sink of an ingestion transaction: it refuses (module docstring)."""

    def record(self, event: AuditEvent) -> None:
        raise RuntimeError("an ingestion transaction writes no audit event")


def ingest_unit_of_work(engine: Engine) -> Callable[[], UnitOfWork]:
    """One plain transaction per call, with the refusing audit sink."""
    audit = _IngestionWritesNoAudit()
    return lambda: SqlAlchemyUnitOfWork(engine, audit=audit)


def ingest_workspace_stores(
    settings: Settings, engine: Engine, *, eager: bool = False
) -> Callable[[str], FileWorkspaceStore]:
    """`workspace_id -> store`, composed from settings on first use (module docstring).

    `eager` composes at once, so a long-lived process refuses a misconfigured
    root at start rather than at its first poll. An unknown workspace id is a
    `LookupError`, which the lifecycle answers `workspace_unavailable`. A
    misconfigured root raises the store's `FileWorkspaceRootError` at
    composition, which callers report as a code.
    """
    composed: dict[str, FileWorkspaceStore] | None = None
    if eager:
        composed = files_workspace_stores(settings, engine)

    def store(workspace_id: str) -> FileWorkspaceStore:
        nonlocal composed
        if composed is None:
            composed = files_workspace_stores(settings, engine)
        return composed[workspace_id]

    return store


def ingestion_lifecycle(
    settings: Settings,
    engine: Engine,
    *,
    clock: Callable[[], datetime] = utc_now,
    stability: StabilityMemory | None = None,
    eager: bool = False,
) -> IngestionLifecycle:
    """The lifecycle with the communications and meeting sync handlers, the stores, no audit."""
    return IngestionLifecycle(
        unit_of_work=ingest_unit_of_work(engine),
        stores=ingest_workspace_stores(settings, engine, eager=eager),
        handlers=[communications_handler(), meeting_sync_handler(clock=clock)],
        clock=clock,
        stability=stability,
    )


def coverage_reader(
    engine: Engine, *, clock: Callable[[], datetime] = utc_now
) -> CommunicationsCoverageReader:
    """The coverage read over the same transactions."""
    return CommunicationsCoverageReader(unit_of_work=ingest_unit_of_work(engine), clock=clock)


def meeting_sync_applier(
    engine: Engine, *, clock: Callable[[], datetime] = utc_now
) -> MeetingSyncApplier:
    """The staged-publication applier over the ingestion transactions (no audit, D9)."""
    return MeetingSyncApplier(unit_of_work=ingest_unit_of_work(engine), clock=clock)


def communications_rederiver(settings: Settings, engine: Engine) -> CommunicationsRederiver:
    """The WP4 rederive over the ingestion transactions, stores and parser (no audit)."""
    return CommunicationsRederiver(
        unit_of_work=ingest_unit_of_work(engine),
        stores=ingest_workspace_stores(settings, engine),
        parse=parse_for_ingestion,
        max_bytes=MAX_PUBLICATION_BYTES,
    )


def meeting_context_measurement(
    engine: Engine, principal_id: str, *, clock: Callable[[], datetime] = utc_now
) -> MeetingContextMeasurement:
    """`measure-context`'s measurement over `engine`, for `principal_id` (read-only)."""
    issued = 0

    def count(*_args: object) -> None:
        nonlocal issued
        issued += 1

    event.listen(engine, "before_cursor_execute", count)

    def probe_facts(
        anchors: Sequence[datetime], lookback: timedelta, excluded: Sequence[str]
    ) -> Sequence[ProbeFacts]:
        with engine.connect() as connection:
            return meeting_context_probe_facts(
                connection,
                principal_id,
                anchors=anchors,
                lookback=lookback,
                excluded_addresses=excluded,
                identifier_version=IDENTIFIER_VERSION,
                max_attendees=MAX_PROBE_ATTENDEES,
                min_participants=MIN_PROBE_PARTICIPANTS,
                identifiers=PROBE_IDENTIFIERS,
            )

    def quarantined(reason: str) -> int:
        with engine.connect() as connection:
            return quarantined_reason_count(connection, principal_id, reason)

    return MeetingContextMeasurement(
        unit_of_work=ingest_unit_of_work(engine),
        probe_facts=probe_facts,
        quarantined=quarantined,
        statements=lambda: issued,
        identifier_version=IDENTIFIER_VERSION,
        clock=clock,
    )
