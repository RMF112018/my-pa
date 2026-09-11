"""WP-TUX-01: origin_kind, direct closure, and append-only task_comments.

Revision `de5ec1c65857` revises `c1a8e4d70b29`. Empty-to-head, prior-to-head
backfill, CHECK behaviour, comment partition/idempotency, and fail-closed
downgrade are asserted here. Capture-label table-set claims stay with
`tests/schema/test_capture_labels_migration.py` and
`KNOWLEDGE_TABLES_BY_REVISION['c1a8e4d70b29']` — this module does not touch them.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import task_comments, tasks

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "de5ec1c65857"
PREVIOUS_REVISION: Final = "c1a8e4d70b29"
TRIGGER: Final = "task_comments_are_append_only"
FUNCTION: Final = "task_comments_stay_as_written"

PRINCIPAL: Final = "prn_aaaaaaaa11111111"
TASK_EVIDENCE: Final = "tsk_aaaaaaaa11111111"
TASK_DIRECT: Final = "tsk_bbbbbbbb22222222"
ORIGIN: Final = "cap_aaaaaaaa11111111"
WHEN: Final = "2026-09-11 12:00:00+00"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; this module drives Alembic itself."""
    return empty_database_url


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


def _columns(engine: Engine, table: str) -> dict[str, tuple[Any, ...]]:
    with engine.connect() as connection:
        return {
            str(row[0]): (row[1], row[2])
            for row in connection.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table},
            )
        }


def _constraint_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = :schema AND t.relname = :table"
                ),
                {"schema": SCHEMA, "table": table},
            ).scalars()
        )


def _seed_legacy_task(connection: Connection, *, task_id: str, closed: bool = False) -> None:
    """Insert a pre-WP-TUX-01 task row at the capture_labels head shape."""
    connection.execute(
        text(
            """
            INSERT INTO knowledge.tasks (
              task_id, principal_id, title, state, evidence_state,
              origin_evidence_ref, opened_at, closed_at, closure_evidence_ref,
              acceptance_kind, created_at, updated_at, lifecycle_state, version
            ) VALUES (
              :task_id, :principal_id, 'Seeded task',
              :state, 'accepted', :origin,
              :when, :closed_at, :closure,
              'direct_principal', :when, :when, :lifecycle, 1
            )
            """
        ),
        {
            "task_id": task_id,
            "principal_id": PRINCIPAL,
            "origin": ORIGIN,
            "when": WHEN,
            "state": "closed" if closed else "open",
            "lifecycle": "completed" if closed else "open",
            "closed_at": WHEN if closed else None,
            "closure": ORIGIN if closed else None,
        },
    )


def test_the_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION
    assert FUNCTION  # rename must touch this module


@pytest.mark.database
def test_empty_to_head_installs_origin_and_comments(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert "task_comments" in _tables(engine)
        columns = _columns(engine, "tasks")
        assert columns["origin_kind"][1] == "NO"
        assert columns["origin_evidence_ref"][1] == "YES"
        names = _constraint_names(engine, "tasks")
        assert "a_task_origin_matches_its_provenance" in names
        assert "a_task_closure_evidence_matches_its_state" in names
        assert "a_task_cites_its_origin_evidence" not in names
        assert "a_closed_task_carries_closure_evidence" not in names
        assert "tasks_principal_task_is_unique" in names
        comment_cols = set(_columns(engine, "task_comments"))
        assert comment_cols == {
            "comment_id",
            "principal_id",
            "task_id",
            "body",
            "author_kind",
            "author_id",
            "created_at",
            "idempotency_key",
            "request_digest",
        }
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
        assert TRIGGER in triggers
        # Live declaration correspondence for the new table.
        assert {column.name for column in task_comments.columns} == comment_cols
        assert "origin_kind" in {column.name for column in tasks.columns}
        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_backfill_preserves_evidence_refs_from_prior_head(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        with engine.begin() as connection:
            _seed_legacy_task(connection, task_id=TASK_EVIDENCE)
            _seed_legacy_task(connection, task_id=TASK_DIRECT, closed=True)
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT task_id, origin_kind, origin_evidence_ref, "
                        "closure_evidence_ref FROM knowledge.tasks "
                        "ORDER BY task_id"
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        for row in rows:
            assert row["origin_kind"] == "evidence"
            assert row["origin_evidence_ref"] == ORIGIN
        closed = next(row for row in rows if row["task_id"] == TASK_DIRECT)
        assert closed["closure_evidence_ref"] == ORIGIN
    finally:
        engine.dispose()


@pytest.mark.database
def test_provenance_and_closure_checks(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.tasks (
                      task_id, principal_id, title, state, evidence_state,
                      origin_kind, origin_evidence_ref, opened_at, closed_at,
                      closure_evidence_ref, acceptance_kind, created_at,
                      updated_at, lifecycle_state, version
                    ) VALUES (
                      :task_id, :principal_id, 'Direct create', 'open', 'accepted',
                      'direct_principal', NULL, :when, NULL, NULL,
                      'direct_principal', :when, :when, 'open', 1
                    )
                    """
                ),
                {"task_id": TASK_DIRECT, "principal_id": PRINCIPAL, "when": WHEN},
            )
        # Evidence origin without a reference is refused.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                        INSERT INTO knowledge.tasks (
                          task_id, principal_id, title, state, evidence_state,
                          origin_kind, origin_evidence_ref, opened_at,
                          acceptance_kind, created_at, updated_at,
                          lifecycle_state, version
                        ) VALUES (
                          'tsk_cccccccc33333333', :principal_id, 'Broken',
                          'open', 'proposed', 'evidence', NULL, :when,
                          'none', :when, :when, 'open', 1
                        )
                        """
                ),
                {"principal_id": PRINCIPAL, "when": WHEN},
            )
        # Terminal may omit closure evidence.
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE knowledge.tasks
                       SET state = 'closed', lifecycle_state = 'completed',
                           closed_at = :when, closure_evidence_ref = NULL
                     WHERE task_id = :task_id
                    """
                ),
                {"task_id": TASK_DIRECT, "when": WHEN},
            )
        # Nonterminal may not carry closure evidence.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                        INSERT INTO knowledge.tasks (
                          task_id, principal_id, title, state, evidence_state,
                          origin_kind, origin_evidence_ref, opened_at,
                          closure_evidence_ref, acceptance_kind, created_at,
                          updated_at, lifecycle_state, version
                        ) VALUES (
                          'tsk_dddddddd44444444', :principal_id, 'Open with closure',
                          'open', 'accepted', 'direct_principal', NULL, :when,
                          :origin, 'direct_principal', :when, :when, 'open', 1
                        )
                        """
                ),
                {"principal_id": PRINCIPAL, "when": WHEN, "origin": ORIGIN},
            )
    finally:
        engine.dispose()


@pytest.mark.database
def test_comment_fk_partition_idempotency_and_append_only(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        digest = "a" * 64
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.tasks (
                      task_id, principal_id, title, state, evidence_state,
                      origin_kind, origin_evidence_ref, opened_at,
                      acceptance_kind, created_at, updated_at,
                      lifecycle_state, version
                    ) VALUES (
                      :task_id, :principal_id, 'Commented', 'open', 'accepted',
                      'direct_principal', NULL, :when, 'direct_principal',
                      :when, :when, 'open', 1
                    )
                    """
                ),
                {"task_id": TASK_DIRECT, "principal_id": PRINCIPAL, "when": WHEN},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.task_comments (
                      comment_id, principal_id, task_id, body, author_kind,
                      author_id, created_at, idempotency_key, request_digest
                    ) VALUES (
                      'tcm_aaaaaaaa11111111', :principal_id, :task_id,
                      'First note', 'principal', :principal_id, :when,
                      'idem-key-0001', :digest
                    )
                    """
                ),
                {"principal_id": PRINCIPAL, "task_id": TASK_DIRECT, "when": WHEN, "digest": digest},
            )
        # Cross-Principal partition is refused by the composite FK.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                        INSERT INTO knowledge.task_comments (
                          comment_id, principal_id, task_id, body, author_kind,
                          author_id, created_at, idempotency_key, request_digest
                        ) VALUES (
                          'tcm_bbbbbbbb22222222', 'prn_bbbbbbbb22222222',
                          :task_id, 'Forged', 'principal', 'prn_bbbbbbbb22222222',
                          :when, 'idem-key-0002', :digest
                        )
                        """
                ),
                {"task_id": TASK_DIRECT, "when": WHEN, "digest": digest},
            )
        # Idempotency unique per Principal.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                        INSERT INTO knowledge.task_comments (
                          comment_id, principal_id, task_id, body, author_kind,
                          author_id, created_at, idempotency_key, request_digest
                        ) VALUES (
                          'tcm_cccccccc33333333', :principal_id, :task_id,
                          'Replay', 'principal', :principal_id, :when,
                          'idem-key-0001', :digest
                        )
                        """
                ),
                {
                    "principal_id": PRINCIPAL,
                    "task_id": TASK_DIRECT,
                    "when": WHEN,
                    "digest": digest,
                },
            )
        for statement in (
            "UPDATE knowledge.task_comments SET body = 'Rewritten' "
            "WHERE comment_id = 'tcm_aaaaaaaa11111111'",
            "DELETE FROM knowledge.task_comments WHERE comment_id = 'tcm_aaaaaaaa11111111'",
        ):
            refused: BaseException | None = None
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement))
            except DBAPIError as error:
                refused = error
            assert refused is not None, statement
            assert "append only" in str(refused)
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_refuses_incompatible_rows_and_allows_compatible(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.tasks (
                      task_id, principal_id, title, state, evidence_state,
                      origin_kind, origin_evidence_ref, opened_at,
                      acceptance_kind, created_at, updated_at,
                      lifecycle_state, version
                    ) VALUES (
                      :task_id, :principal_id, 'Direct', 'open', 'accepted',
                      'direct_principal', NULL, :when, 'direct_principal',
                      :when, :when, 'open', 1
                    )
                    """
                ),
                {"task_id": TASK_DIRECT, "principal_id": PRINCIPAL, "when": WHEN},
            )
        refused: BaseException | None = None
        try:
            command.downgrade(_config(), PREVIOUS_REVISION)
        except Exception as error:
            refused = error
        assert refused is not None
        assert "direct_principal" in str(refused)

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM knowledge.tasks"))
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.tasks (
                      task_id, principal_id, title, state, evidence_state,
                      origin_kind, origin_evidence_ref, opened_at, closed_at,
                      closure_evidence_ref, acceptance_kind, created_at,
                      updated_at, lifecycle_state, version
                    ) VALUES (
                      :task_id, :principal_id, 'Evidence', 'closed', 'accepted',
                      'evidence', :origin, :when, :when, :origin,
                      'direct_principal', :when, :when, 'completed', 1
                    )
                    """
                ),
                {
                    "task_id": TASK_EVIDENCE,
                    "principal_id": PRINCIPAL,
                    "when": WHEN,
                    "origin": ORIGIN,
                },
            )
        command.downgrade(_config(), PREVIOUS_REVISION)
        assert "task_comments" not in _tables(engine)
        columns = _columns(engine, "tasks")
        assert "origin_kind" not in columns
        assert columns["origin_evidence_ref"][1] == "NO"
        command.upgrade(_config(), "head")
    finally:
        engine.dispose()
