"""Static and offline checks for the durable GoodNotes pull revision."""

from __future__ import annotations

import ast
import io
import re
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from my_pa.bootstrap.gateway import local_principal

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "6a2f9d1c4b80"
PREVIOUS: Final = "b8e4d1a6c073"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260904_6a2f9d1c4b80_add_goodnotes_pull_and_review_ledgers.py"
)
TABLES: Final = (
    "goodnotes_pull_sessions",
    "goodnotes_pull_claims",
    "goodnotes_pull_assignments",
    "goodnotes_pull_completions",
    "goodnotes_semantic_review_decisions",
)


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def test_revision_is_the_only_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_revision_is_frozen_and_does_not_import_live_schema_or_enums() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "my_pa.infrastructure.persistence.tables" not in imported
    assert not any(module.startswith("my_pa.domain") for module in imported)
    for value in (
        "goodnotes.complete",
        "goodnotes.pull",
        "goodnotes.status",
        "goodnotes_pull",
        "goodnotes_pull_observation",
    ):
        assert value in source


def test_offline_upgrade_emits_all_ledgers_constraints_and_immutability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    output = io.StringIO()
    command.upgrade(_config(output), "head", sql=True)
    sql = output.getvalue()
    for table in TABLES:
        assert f"CREATE TABLE knowledge.{table}" in sql
        assert f"CREATE TRIGGER {table}_are_immutable" in sql
    for fragment in (
        "one_goodnotes_pull_session_per_client",
        "one_goodnotes_pull_work_attempt",
        "one_goodnotes_pull_completion_per_assignment",
        "one_goodnotes_semantic_review_per_sequence",
        "one_goodnotes_semantic_review_request",
        "goodnotes_semantic_review_proposal_fk",
        "goodnotes_semantic_review_correction_matches_action",
        "goodnotes_semantic_review_corrected_digest_shape",
    ):
        assert fragment in sql


def test_every_ledger_accepts_the_canonical_local_principal_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    output = io.StringIO()
    command.upgrade(_config(output), "head", sql=True)
    sql = output.getvalue()
    goodnotes_pull_sql = sql[sql.index("CREATE TABLE knowledge.goodnotes_pull_sessions") :]
    canonical_pattern = r"prn_[A-Za-z0-9]{8,64}"

    assert re.fullmatch(canonical_pattern, local_principal().principal_id)
    assert goodnotes_pull_sql.count("principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'") == len(TABLES)
    assert "principal_id ~ '^prn_[a-f0-9]{24}$'" not in goodnotes_pull_sql


def test_offline_downgrade_is_reversible_to_the_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    output = io.StringIO()
    command.downgrade(_config(output), f"{REVISION}:{PREVIOUS}", sql=True)
    sql = output.getvalue()
    for table in TABLES:
        assert f"DROP TABLE knowledge.{table}" in sql
