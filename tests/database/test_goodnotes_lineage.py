"""Disposable PostgreSQL proof for GoodNotes lineage isolation and replay."""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql import Executable

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchMethod,
    GoodNotesNotebook,
    GoodNotesNotebookPath,
    GoodNotesPagePosition,
    GoodNotesSourceSnapshot,
    issue_stable_id,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_lineage_test"
WHEN = datetime(2026, 8, 16, 15, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST_ONE = "a" * 64
DIGEST_TWO = "b" * 64
FINGERPRINT_ONE = "c" * 64
FINGERPRINT_TWO = "d" * 64


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        administer(maintenance, drop, text(f'CREATE DATABASE "{DATABASE}"'))
        url = configured.set(database=DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        built = create_database_engine(url)
        yield built
        built.dispose()
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        administer(maintenance, drop)
        maintenance.dispose()


def _notebook(principal_id: str, token: str) -> GoodNotesNotebook:
    return GoodNotesNotebook(
        notebook_id=issue_stable_id("gnnb", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=WHEN,
        label=token,
    )


def _run(principal_id: str, token: str, fingerprint: str) -> GoodNotesIngestionRun:
    request_id = f"req-{principal_id[-4:]}-{token}"
    return GoodNotesIngestionRun(
        run_id=issue_stable_id("gnrun", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id=request_id,
        idempotency_key=request_id,
        request_fingerprint=fingerprint,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.RUNNING,
    )


def test_cross_principal_isolation_and_path_history(engine: Engine) -> None:
    notebook_a = _notebook(A, "shared-name")
    notebook_b = GoodNotesNotebook(
        notebook_id=notebook_a.notebook_id,
        principal_id=B,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=WHEN,
        label="other",
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        stored_a = repository.store_notebook(notebook_a)
        stored_b = repository.store_notebook(notebook_b)
        assert stored_a.notebook_id == stored_b.notebook_id
        fetched_a = repository.notebook(A, notebook_a.notebook_id)
        fetched_b = repository.notebook(B, notebook_a.notebook_id)
        assert fetched_a is not None and fetched_b is not None
        assert fetched_a.label == "shared-name"
        assert fetched_b.label == "other"
        first = repository.record_notebook_path(
            GoodNotesNotebookPath(
                principal_id=A,
                notebook_id=notebook_a.notebook_id,
                path="Inbox/alpha.pdf",
                first_seen_at=WHEN,
                last_seen_at=WHEN,
                is_current=True,
            )
        )
        renamed = repository.record_notebook_path(
            GoodNotesNotebookPath(
                principal_id=A,
                notebook_id=notebook_a.notebook_id,
                path="Archive/alpha.pdf",
                first_seen_at=LATER,
                last_seen_at=LATER,
                is_current=True,
            )
        )
        paths = repository.notebook_paths(A, notebook_a.notebook_id)
        assert {item.path for item in paths} == {first.path, renamed.path}
        assert sum(item.is_current for item in paths) == 1
        current = next(item for item in paths if item.is_current)
        assert current.path == "Archive/alpha.pdf"
        assert repository.notebook_paths(B, notebook_a.notebook_id) == ()


def test_exact_snapshot_replay_and_logical_page_positions(engine: Engine) -> None:
    notebook = _notebook(A, "replay")
    run = _run(A, "replay", FINGERPRINT_ONE)
    snapshot = GoodNotesSourceSnapshot(
        snapshot_id=issue_stable_id("gnsnap", A, "first"),
        principal_id=A,
        notebook_id=notebook.notebook_id,
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        observed_path="Inbox/alpha.pdf",
        raw_sha256=DIGEST_ONE,
        size_bytes=32,
        page_count=2,
        observed_at=WHEN,
        settled_at=WHEN,
        run_id=run.run_id,
    )
    logical = GoodNotesLogicalPage(
        logical_page_id=issue_stable_id("gnlp", A, "cover"),
        principal_id=A,
        notebook_id=notebook.notebook_id,
        created_at=WHEN,
        last_seen_at=WHEN,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        repository.store_notebook(notebook)
        stored_run = repository.create_run(run)
        first = repository.store_snapshot(snapshot)
        replayed = repository.store_snapshot(
            GoodNotesSourceSnapshot(
                snapshot_id=issue_stable_id("gnsnap", A, "second-attempt"),
                principal_id=A,
                notebook_id=notebook.notebook_id,
                source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                observed_path="Archive/alpha.pdf",
                raw_sha256=DIGEST_ONE,
                size_bytes=64,
                page_count=9,
                observed_at=LATER,
                settled_at=LATER,
                run_id=stored_run.run_id,
            )
        )
        assert replayed.snapshot_id == first.snapshot_id
        assert replayed.observed_path == "Inbox/alpha.pdf"
        assert replayed.size_bytes == 32
        later_run = repository.create_run(
            GoodNotesIngestionRun(
                run_id=issue_stable_id("gnrun", A, "later"),
                principal_id=A,
                source_root_id="icloud-goodnotes",
                trigger_type=GoodNotesIngestionTrigger.SCHEDULED,
                request_id="req-later",
                idempotency_key="req-later",
                request_fingerprint=DIGEST_TWO,
                started_at=LATER,
                status=GoodNotesIngestionStatus.RUNNING,
            )
        )
        second = repository.store_snapshot(
            GoodNotesSourceSnapshot(
                snapshot_id=issue_stable_id("gnsnap", A, "changed-bytes"),
                principal_id=A,
                notebook_id=notebook.notebook_id,
                source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                observed_path="Archive/alpha.pdf",
                raw_sha256=DIGEST_TWO,
                size_bytes=40,
                page_count=2,
                observed_at=LATER,
                settled_at=LATER,
                run_id=later_run.run_id,
            )
        )
        assert second.snapshot_id != first.snapshot_id
        repository.store_logical_page(logical)
        first_position = repository.store_page_position(
            GoodNotesPagePosition(
                principal_id=A,
                snapshot_id=first.snapshot_id,
                page_number=2,
                logical_page_id=logical.logical_page_id,
                created_at=WHEN,
                match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
            )
        )
        second_position = repository.store_page_position(
            GoodNotesPagePosition(
                principal_id=A,
                snapshot_id=second.snapshot_id,
                page_number=1,
                logical_page_id=logical.logical_page_id,
                created_at=LATER,
                match_method=GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER,
                match_confidence=1.0,
            )
        )
        assert first_position.logical_page_id == second_position.logical_page_id
        assert first_position.page_number != second_position.page_number
        assert repository.snapshot(B, first.snapshot_id) is None
        assert repository.logical_page(B, logical.logical_page_id) is None


def test_request_id_replay_and_fingerprint_conflict(engine: Engine) -> None:
    first = _run(A, "idempotent", FINGERPRINT_ONE)
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        stored = repository.create_run(first)
        replayed = repository.create_run(
            GoodNotesIngestionRun(
                run_id=issue_stable_id("gnrun", A, "other-id"),
                principal_id=A,
                source_root_id="icloud-goodnotes",
                trigger_type=GoodNotesIngestionTrigger.REPLAY,
                request_id=first.request_id,
                idempotency_key=first.request_id,
                request_fingerprint=FINGERPRINT_ONE,
                started_at=LATER,
                status=GoodNotesIngestionStatus.PENDING,
            )
        )
        assert replayed.run_id == stored.run_id
        assert replayed.status is GoodNotesIngestionStatus.RUNNING
        with pytest.raises(ValueError, match="bound to another ingestion"):
            repository.create_run(
                GoodNotesIngestionRun(
                    run_id=issue_stable_id("gnrun", A, "conflict"),
                    principal_id=A,
                    source_root_id="icloud-goodnotes",
                    trigger_type=GoodNotesIngestionTrigger.MANUAL,
                    request_id=first.request_id,
                    idempotency_key=first.request_id,
                    request_fingerprint=FINGERPRINT_TWO,
                    started_at=LATER,
                    status=GoodNotesIngestionStatus.PENDING,
                )
            )
        other = repository.create_run(_run(B, "idempotent", FINGERPRINT_ONE))
        assert other.run_id != stored.run_id
        finished = repository.update_run(
            GoodNotesIngestionRun(
                run_id=stored.run_id,
                principal_id=A,
                source_root_id=stored.source_root_id,
                trigger_type=stored.trigger_type,
                request_id=stored.request_id,
                idempotency_key=stored.idempotency_key,
                request_fingerprint=stored.request_fingerprint,
                started_at=stored.started_at,
                status=GoodNotesIngestionStatus.SUCCEEDED,
                ended_at=LATER,
                snapshot_count=1,
                page_count=2,
            )
        )
        assert finished.status is GoodNotesIngestionStatus.SUCCEEDED
        assert finished.snapshot_count == 1
        assert repository.run(B, stored.run_id) is None
