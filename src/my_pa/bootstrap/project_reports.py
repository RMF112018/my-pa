"""Composition of the project-reports consumer (WP3P; rulings D5, D6, D7).

The one place the project-reports lifecycle and its bindings service are
built, so the operator CLI (`apps/cli/project_reports.py`) and the cycles-plane
step (slice S5) cannot compose them differently:

* **A separate lifecycle instance (ruling D5).** `project_reports_lifecycle()`
  is an `IngestionLifecycle` whose handler registry holds only the
  `pulse_csv_export` handler (S4: the admission-only stand-in of
  `application.project_reports_ingest`). The communications lifecycle
  (`bootstrap.communications_ingest`) never holds it, so the generic `admit`
  refuses the consumer and a project-report source is admitted only by
  `bindings apply`.
* **Its own lock.** `PROJECT_REPORTS_POLL_LOCK_KEY`, taken without waiting
  (`single_flight`); the bindings apply holds it for its one transaction.
* **No audit rows (ruling D6).** The unit of work's audit sink refuses, as the
  communications ingestion's does: the append-only binding revisions are the
  audit, so an attempt to audit is a defect that fails loudly. It is restated
  here rather than imported, because no project-reports module imports a
  communications one (`tests/architecture/test_project_reports_scope.py`).
* **The workspace stores come from settings, once.** `MY_PA_FILES_WORKSPACES`
  composed by `bootstrap.gateway.files_workspace_stores`, so a `read_only`
  workspace is refused unless it is mounted read-only. The bindings service
  calls only `stat` and `list_directory` on them. Composition is lazy.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Final

from sqlalchemy import Engine

from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.application.project_reports_bindings import ProjectReportBindings
from my_pa.application.project_reports_ingest import AdmissionOnlyHandler
from my_pa.bootstrap.gateway import files_workspace_stores
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import AuditSink, FileWorkspaceStore, UnitOfWork
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.common.time import utc_now
from my_pa.infrastructure.jobs.cycle_scheduler import PROJECT_REPORTS_POLL_LOCK_KEY, single_flight
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "PROJECT_REPORTS_WORKSPACE_ID",
    "bindings_service",
    "poll_lock",
    "project_reports_lifecycle",
    "project_reports_unit_of_work",
    "project_reports_workspace_stores",
]

#: The one file workspace the PULSE exports live in (design section 3.1).
PROJECT_REPORTS_WORKSPACE_ID: Final = "mcp"


class _ProjectReportsWriteNoAudit(AuditSink):
    """The audit sink of a project-reports transaction: it refuses (module docstring)."""

    def record(self, event: AuditEvent) -> None:
        raise RuntimeError("a project-reports transaction writes no audit event")


def project_reports_unit_of_work(engine: Engine) -> Callable[[], UnitOfWork]:
    """One plain transaction per call, with the refusing audit sink."""
    audit = _ProjectReportsWriteNoAudit()
    return lambda: SqlAlchemyUnitOfWork(engine, audit=audit)


def project_reports_workspace_stores(
    settings: Settings, engine: Engine
) -> Callable[[str], FileWorkspaceStore]:
    """`workspace_id -> store`, composed from settings on first use.

    An unknown workspace id is a `LookupError`; a misconfigured root raises the
    store's `FileWorkspaceRootError` at composition, which callers report as a
    code.
    """
    composed: dict[str, FileWorkspaceStore] | None = None

    def store(workspace_id: str) -> FileWorkspaceStore:
        nonlocal composed
        if composed is None:
            composed = files_workspace_stores(settings, engine)
        return composed[workspace_id]

    return store


def project_reports_lifecycle(
    settings: Settings,
    engine: Engine,
    *,
    clock: Callable[[], datetime] = utc_now,
    stability: StabilityMemory | None = None,
) -> IngestionLifecycle:
    """The project-reports lifecycle: only the `pulse_csv_export` handler (ruling D5)."""
    return IngestionLifecycle(
        unit_of_work=project_reports_unit_of_work(engine),
        stores=project_reports_workspace_stores(settings, engine),
        handlers=[AdmissionOnlyHandler()],
        clock=clock,
        stability=stability,
    )


def poll_lock(engine: Engine) -> Callable[[], AbstractContextManager[bool]]:
    """The project-reports poll lock, taken without waiting; yields whether it is held."""
    return lambda: single_flight(engine, key=PROJECT_REPORTS_POLL_LOCK_KEY)


def bindings_service(
    settings: Settings, engine: Engine, *, clock: Callable[[], datetime] = utc_now
) -> ProjectReportBindings:
    """`bindings check` and `bindings apply` over the project-reports lifecycle."""
    stores = project_reports_workspace_stores(settings, engine)
    return ProjectReportBindings(
        unit_of_work=project_reports_unit_of_work(engine),
        lifecycle=project_reports_lifecycle(settings, engine, clock=clock),
        stores=stores,
        workspace_id=PROJECT_REPORTS_WORKSPACE_ID,
        lock=poll_lock(engine),
        clock=clock,
    )
