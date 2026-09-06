"""Frozen additive Review-promotion receipt schema and predecessor upgrade proof."""

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

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import goodnotes_semantic_promotion_receipts

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a4d8e31b2c90"
PREVIOUS = "6a2f9d1c4b80"
HEAD_REVISION = "2774329487be"
TABLE = "goodnotes_semantic_promotion_receipts"
MIGRATION = ROOT / "migrations/versions/20260905_a4d8e31b2c90_add_goodnotes_promotion_receipts.py"


def _config(output: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output)


def test_promotion_revision_is_frozen_and_only_head(monkeypatch: pytest.MonkeyPatch) -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(HEAD_REVISION).down_revision == "e8f2a6c9d104"
    assert script.get_revision("e8f2a6c9d104").down_revision == "d4e8b1c7a902"
    assert script.get_revision("d4e8b1c7a902").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    imported = {
        node.module
        for node in ast.walk(ast.parse(MIGRATION.read_text()))
        if isinstance(node, ast.ImportFrom)
    }
    assert imported == {"alembic"}
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    output = io.StringIO()
    command.upgrade(_config(output), f"{PREVIOUS}:{REVISION}", sql=True)
    sql = output.getvalue()
    assert f"CREATE TABLE knowledge.{TABLE}" in sql
    assert f"CREATE TRIGGER {TABLE}_are_immutable" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "jsonb_array_length(bindings) <= 10000" in sql


@pytest.mark.database
@pytest.mark.migration_empty_to_head
def test_empty_to_head_receipt_metadata_and_round_trip(empty_database_url: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(empty_database_url)
    try:
        inspector = inspect(engine)
        assert {column["name"] for column in inspector.get_columns(TABLE, schema="knowledge")} == {
            column.name for column in goodnotes_semantic_promotion_receipts.columns
        }
        assert inspector.get_pk_constraint(TABLE, schema="knowledge")["constrained_columns"] == [
            "principal_id",
            "run_id",
        ]
        checks = {c["name"] for c in inspector.get_check_constraints(TABLE, schema="knowledge")}
        expected_checks = {
            c.name
            for c in goodnotes_semantic_promotion_receipts.constraints
            if c.__class__.__name__ == "CheckConstraint"
        }
        assert checks == expected_checks
    finally:
        engine.dispose()
    command.downgrade(_config(), "base")


@pytest.mark.database
@pytest.mark.migration_edge
def test_predecessor_run_preserved_and_receipt_is_immutable(empty_database_url: str) -> None:
    command.upgrade(_config(), PREVIOUS)
    engine = create_database_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO knowledge.goodnotes_ingestion_runs
                (principal_id, run_id, source_root_id, trigger_type, request_id,
                 idempotency_key, request_fingerprint, started_at, status)
                VALUES ('prn_aaaaaaaaaaaaaaaaaaaaaaaa', 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',
                        'synthetic', 'SCHEDULED', 'synthetic', 'synthetic', :digest,
                        '2026-09-05T00:00:00Z', 'SUCCEEDED')
            """),
                {"digest": "a" * 64},
            )
        command.upgrade(_config(), REVISION)
        with engine.begin() as connection:
            assert (
                connection.scalar(text("SELECT count(*) FROM knowledge.goodnotes_ingestion_runs"))
                == 1
            )
            connection.execute(
                text("""
                INSERT INTO knowledge.goodnotes_semantic_promotion_receipts
                VALUES ('prn_aaaaaaaaaaaaaaaaaaaaaaaa', 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',
                        'gnspr_aaaaaaaaaaaaaaaaaaaaaaaa', :digest, '[]', '2026-09-05T00:00:00Z')
            """),
                {"digest": "a" * 64},
            )
        for action in ("UPDATE", "DELETE"):
            with engine.begin() as connection, pytest.raises(DBAPIError):
                if action == "UPDATE":
                    connection.execute(
                        text(
                            "UPDATE knowledge.goodnotes_semantic_promotion_receipts "
                            "SET bindings = '[]'"
                        )
                    )
                else:
                    connection.execute(
                        text("DELETE FROM knowledge.goodnotes_semantic_promotion_receipts")
                    )
        command.downgrade(_config(), PREVIOUS)
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT count(*) FROM knowledge.goodnotes_ingestion_runs"))
                == 1
            )
    finally:
        engine.dispose()
