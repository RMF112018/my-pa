"""Frozen client retry schema, preserved history, and fail-closed narrowing."""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from my_pa.bootstrap.gateway import local_principal
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    goodnotes_pull_assignments,
    goodnotes_pull_claims,
    goodnotes_pull_completions,
    goodnotes_pull_sessions,
)

ROOT = Path(__file__).resolve().parents[2]
REVISION = "e8f2a6c9d104"
PREVIOUS = "d4e8b1c7a902"
MIGRATION = ROOT / "migrations/versions/20260905_e8f2a6c9d104_goodnotes_client_resume.py"


def _config(output: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output)


def test_client_resume_revision_is_frozen_additive_and_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["2774329487be"]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    source = MIGRATION.read_text()
    assert {
        node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    } == {"alembic"}
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    output = io.StringIO()
    command.upgrade(_config(output), f"{PREVIOUS}:{REVISION}", sql=True)
    sql = output.getvalue()
    assert "DEFAULT 900" in sql and "BETWEEN 60 AND 86400" in sql
    assert "DROP TABLE" not in sql and "UPDATE knowledge." not in sql
    assert "(principal_id, client_id, idempotency_key)" in sql


@pytest.mark.database
@pytest.mark.migration_empty_to_head
def test_client_resume_empty_head_matches_metadata(empty_database_url: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(empty_database_url)
    try:
        inspector = inspect(engine)
        for table in (
            goodnotes_pull_sessions,
            goodnotes_pull_assignments,
            goodnotes_pull_completions,
        ):
            assert {
                c["name"] for c in inspector.get_columns(table.name, schema="knowledge")
            } == set(table.c.keys())
            expected = {
                c.name: list(c.columns.keys())
                for c in table.constraints
                if c.__class__.__name__ == "UniqueConstraint"
            }
            assert {
                c["name"]: c["column_names"]
                for c in inspector.get_unique_constraints(table.name, schema="knowledge")
            } == expected
        columns = {
            c["name"]: c
            for c in inspector.get_columns("goodnotes_pull_sessions", schema="knowledge")
        }
        assert columns["lease_seconds"]["default"] == "900"
        assert not columns["lease_seconds"]["nullable"]
    finally:
        engine.dispose()
    command.downgrade(_config(), "base")


@pytest.mark.database
@pytest.mark.migration_edge
def test_populated_session_upgrade_preserves_rows_and_immutable_bounded_policy(
    empty_database_url: str,
) -> None:
    command.upgrade(_config(), PREVIOUS)
    engine = create_database_engine(empty_database_url)
    principal = local_principal().principal_id
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_pull_sessions "
                    "(principal_id,context_id,client_id,max_attempts,created_at) "
                    "VALUES (:p,'ctx-a','a',3,'2026-09-05T00:00:00Z')"
                ),
                {"p": principal},
            )
            from tests.database.test_goodnotes_pull import WHEN, _seed_resume_work

            _seed_resume_work(connection)
            connection.execute(
                goodnotes_pull_claims.insert().values(
                    principal_id=principal,
                    claim_id="1" * 64,
                    context_id="ctx-a",
                    client_id="a",
                    request_fingerprint="2" * 64,
                    assignment_count=1,
                    created_at=WHEN,
                )
            )
            connection.execute(
                goodnotes_pull_assignments.insert().values(
                    principal_id=principal,
                    assignment_id="3" * 64,
                    claim_id="1" * 64,
                    context_id="ctx-a",
                    client_id="a",
                    run_id="gnrun_0123456789abcdef01234567",
                    page_version_id="gnver_0123456789abcdef01234567",
                    content_sha256="c" * 64,
                    attempt=1,
                    ordinal=1,
                    created_at=WHEN,
                )
            )
            connection.execute(
                goodnotes_pull_completions.insert().values(
                    principal_id=principal,
                    completion_id="4" * 64,
                    assignment_id="3" * 64,
                    context_id="ctx-a",
                    client_id="a",
                    idempotency_key="original-completion",
                    request_fingerprint="5" * 64,
                    result_sha256="6" * 64,
                    created_at=WHEN,
                )
            )
            history = {
                table: list(connection.execute(table.select()))
                for table in (
                    goodnotes_pull_claims,
                    goodnotes_pull_assignments,
                    goodnotes_pull_completions,
                )
            }
            original = (
                connection.execute(text("SELECT * FROM knowledge.goodnotes_pull_sessions"))
                .one()
                ._asdict()
            )
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            upgraded = (
                connection.execute(text("SELECT * FROM knowledge.goodnotes_pull_sessions"))
                .one()
                ._asdict()
            )
            assert upgraded == {**original, "lease_seconds": 900}
            for table, rows in history.items():
                assert list(connection.execute(table.select())) == rows
        for lease in (59, 86401):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO knowledge.goodnotes_pull_sessions "
                        "(principal_id,context_id,client_id,max_attempts,created_at,lease_seconds) "
                        "VALUES (:p,'ctx-b','b',3,'2026-09-05T00:00:00Z',:lease)"
                    ),
                    {"p": principal, "lease": lease},
                )
        for sql in (
            "UPDATE knowledge.goodnotes_pull_sessions SET lease_seconds=901",
            "DELETE FROM knowledge.goodnotes_pull_sessions",
        ):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(text(sql))
        command.downgrade(_config(), PREVIOUS)
        with engine.connect() as connection:
            for table, rows in history.items():
                assert list(connection.execute(table.select())) == rows
            assert (
                connection.execute(text("SELECT * FROM knowledge.goodnotes_pull_sessions"))
                .one()
                ._asdict()
                == original
            )
    finally:
        engine.dispose()


@pytest.mark.database
@pytest.mark.migration_edge
@pytest.mark.parametrize("collision", ["attempt", "completion", "lease"])
def test_unsafe_downgrade_preserves_client_history(empty_database_url: str, collision: str) -> None:
    command.upgrade(_config(), REVISION)
    engine = create_database_engine(empty_database_url)
    try:
        from tests.database.test_goodnotes_pull import (
            PRINCIPAL,
            WHEN,
            _admission,
            _claim,
            _seed_resume_work,
        )

        from my_pa.infrastructure.persistence.goodnotes_pull import SqlGoodNotesPullRepository

        with engine.begin() as connection:
            _seed_resume_work(connection)
            repository = SqlGoodNotesPullRepository(connection, clock=lambda: WHEN)
            if collision == "lease":
                repository.lock_session(PRINCIPAL, "a", "ctx-a", max_attempts=3, lease_seconds=901)
            else:
                first = _claim(repository, "a")
                if collision == "completion":
                    from dataclasses import replace

                    _seed_resume_work(connection, "fedcba9876543210fedcba98")
                    work = next(
                        state.work
                        for state in repository.work_states(PRINCIPAL, "b")
                        if state.work.run_id.endswith("fedcba9876543210fedcba98")
                    )
                    second = replace(
                        first, assignment_id="f" * 64, client_id="b", context_id="ctx-b", work=work
                    )
                    repository.claim_batch(
                        PRINCIPAL, "b", "ctx-b", (second,), (0,), max_attempts=3, lease_seconds=900
                    )
                else:
                    second = _claim(repository, "b")
                if collision == "completion":
                    for assignment in (first, second):
                        repository.complete_batch(
                            PRINCIPAL,
                            assignment.client_id,
                            assignment.context_id,
                            (_admission(repository, assignment),),
                        )
            before = {
                table: list(connection.execute(table.select().order_by(*table.primary_key)))
                for table in (
                    goodnotes_pull_sessions,
                    goodnotes_pull_assignments,
                    goodnotes_pull_completions,
                )
            }

        with pytest.raises(DBAPIError, match="history cannot fit"):
            command.downgrade(_config(), PREVIOUS)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            for table, rows in before.items():
                assert list(connection.execute(table.select().order_by(*table.primary_key))) == rows

    finally:
        engine.dispose()
