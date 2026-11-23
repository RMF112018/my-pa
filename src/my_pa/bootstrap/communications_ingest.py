"""Composition of the communications ingestion consumer (WP3a, Manager ruling M5).

The one place the `communications_evidence_v2` parser (infrastructure) meets
its lifecycle handler (application): `communications_handler()` injects
`parse_publication`, `PARSER_VERSION` and `MAX_PUBLICATION_BYTES` into
`CommunicationsEvidenceHandler`.

`ingestion_lifecycle()` and `coverage_reader()` are what the operator CLI
(`apps/cli/communications_ingest.py`) and the cycles-plane poll step
(`apps/worker.py run --plane cycles`) both build, so the two cannot compose
the lifecycle differently:

* **No audit rows (ruling m8).** Admission and runs are operator
  configuration and a background step, not capabilities; their evidence is the
  lifecycle rows. The unit of work's audit sink refuses, so an attempt to audit
  is a defect that fails loudly rather than a row nobody asked for.
* **The workspace stores come from settings, once.** `MY_PA_FILES_WORKSPACES`
  (or the single-root form) composed by `bootstrap.gateway.files_workspace_stores`
  with every overlap root, so a `read_only` workspace is refused unless it is
  mounted read-only (`ST_RDONLY`). The lifecycle calls only `list_directory`,
  `stat` and `open_download` on them (ruling m5, guarded). Composition is lazy:
  a command that reads no file (enable, disable, coverage, aggregate) never
  touches a workspace root.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine

from my_pa.application.communications_ingest import (
    CommunicationsCoverageReader,
    CommunicationsEvidenceHandler,
    ParsedPublication,
)
from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.bootstrap.gateway import files_workspace_stores
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import AuditSink, FileWorkspaceStore, UnitOfWork
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.common.time import utc_now
from my_pa.infrastructure.communications.evidence_v2 import (
    MAX_PUBLICATION_BYTES,
    PARSER_VERSION,
    parse_publication,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "communications_handler",
    "coverage_reader",
    "ingest_unit_of_work",
    "ingest_workspace_stores",
    "ingestion_lifecycle",
    "parse_for_ingestion",
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
    """The lifecycle with the communications handler, the stores and no audit."""
    return IngestionLifecycle(
        unit_of_work=ingest_unit_of_work(engine),
        stores=ingest_workspace_stores(settings, engine, eager=eager),
        handlers=[communications_handler()],
        clock=clock,
        stability=stability,
    )


def coverage_reader(
    engine: Engine, *, clock: Callable[[], datetime] = utc_now
) -> CommunicationsCoverageReader:
    """The coverage read over the same transactions."""
    return CommunicationsCoverageReader(unit_of_work=ingest_unit_of_work(engine), clock=clock)
