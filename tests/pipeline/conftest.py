"""One disposable database at head, and the production path that reaches it.

Every fixture here builds its rows the way the product does: `admit_capture`
saves a capture, which is what writes the version, the receipt, the submission,
and the `capture_jobs` row; `run_worker(plane=CAPTURE_JOBS)` claims that row and
runs the nine stages. Nothing inserts a row the product would not have written,
which is why an assertion here about the pipeline is an assertion about the
pipeline and not about a fixture that resembles it.

**The database is disposable and is never the configured one.** These tests
migrate from empty to head and drop the database afterwards, and pointing that at
canonical `my_pa` would destroy the migrated corpus.

**Every fixture is synthetic**, which is `QC-AC-073` (`20_…:239`, "migrations and
tests use isolated synthetic databases; no live personal data") and `AGENTS.md`
section 5 — **not** `QC-AC-042`, whose subject is what captured text may do and
which says nothing about where a corpus comes from.
"""

from __future__ import annotations

import io
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.engine import Connection, make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import CaptureAdmissionRequest
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.capture_pipeline import process_capture_version
from my_pa.infrastructure.jobs.worker import JobHandler, WorkerRun, issue_worker_owner, run_worker
from my_pa.infrastructure.persistence.capture import admit_capture
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.tables import capture_jobs

ROOT = Path(__file__).resolve().parents[2]

#: One synthetic principal for the whole suite, minted once rather than per
#: save: the store partitions captures and idempotency keys by principal
#: (`PKL-MYPA-D-WP03-001`), so a per-save principal would make a key retry an
#: independent admission and would hide every saved capture from the search a
#: test runs afterwards.
PRINCIPAL_ID = issue_identifier(IdKind.PRINCIPAL)

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's, because the database tier runs serially and
#: these names are server-global.
DISPOSABLE_DATABASE = "my_pa_capture_pipeline_test"

WHEN = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)

#: Text that exercises every deterministic matcher at once, so a test that
#: asserts a non-empty result has something real to find. Synthetic throughout:
#: the identifier, the amount, and the host are invented.
RICH_NOTE = (
    "Buyout review 2026-09-14.\n"
    "I will send the RFI-0421 response and the $12,500.00 revision.\n"
    "See https://example.invalid/rfi/0421 for the attachment.\n"
)


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database migrated to head, dropped when the module finishes."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    """An engine over the disposable database, emptied before each test."""
    built = create_database_engine(disposable_database)
    try:
        with built.begin() as connection:
            connection.execute(text("TRUNCATE knowledge.captures CASCADE"))
            connection.execute(text("TRUNCATE knowledge.capture_submissions CASCADE"))
        yield built
    finally:
        built.dispose()


@dataclass(frozen=True, slots=True)
class Saved:
    """One capture as the save left it, before any worker ran."""

    capture_id: str
    version_id: str
    operation_id: str
    text: str


def save(
    connection: Connection,
    note: str,
    *,
    key: str | None = None,
    capture_kind: CaptureKind = CaptureKind.QUICK_NOTE,
    context_source_object_id: str | None = None,
    context_source_version_id: str | None = None,
) -> Saved:
    """Store one capture through the production admit path.

    The `capture_jobs` row is written by `admit_capture` itself and is read back
    here rather than constructed, so the operation this returns is the one the
    save queued — a test that minted its own would be testing a job the product
    never enqueued.
    """
    request = CaptureAdmissionRequest(
        capture_id=None,
        content=CaptureContent(note),
        idempotency_key=key or f"pipeline-{issue_identifier(IdKind.CORRELATION)}",
        request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
        correlation_id=issue_identifier(IdKind.CORRELATION),
        principal_id=PRINCIPAL_ID,
        audit_id=issue_identifier(IdKind.AUDIT),
        classification=Classification.PRIVATE_LOCAL,
        processing_policy=ProcessingPolicy.LOCAL_ONLY,
        server_received_at=WHEN,
        accepted_at=WHEN,
        client_created_at=None,
        occurred_at=None,
        capture_kind=capture_kind,
        context_source_object_id=context_source_object_id,
        context_source_version_id=context_source_version_id,
    )
    admission = admit_capture(connection, request, context=capture_context(PRINCIPAL_ID))
    receipt = admission.receipt
    operation_id = connection.execute(
        select(capture_jobs.c.operation_id).where(capture_jobs.c.version_id == receipt.version_id)
    ).scalar_one()
    return Saved(
        capture_id=receipt.capture_id,
        version_id=receipt.version_id,
        operation_id=str(operation_id),
        text=note,
    )


def drain(
    engine: Engine, *, handler: JobHandler = process_capture_version, jobs: int = 1
) -> WorkerRun:
    """Run the capture-plane worker for a bounded number of iterations.

    The real `run_worker`, on the real plane, with the real handler by default —
    a test that called the handler directly would prove nothing about the claim,
    the lease, or the completion, which is where three of this package's
    properties live. `handler` is an argument only so that a test can substitute
    one that fails at a chosen instant.
    """
    return run_worker(
        engine,
        owner=issue_worker_owner(),
        handler=handler,
        stop=threading.Event(),
        plane=CAPTURE_JOBS,
        max_iterations=jobs,
        poll_seconds=0.01,
    )
