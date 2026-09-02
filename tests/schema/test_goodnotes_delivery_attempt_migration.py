"""Additive dormant GoodNotes delivery-attempt ledger."""

from __future__ import annotations

import ast
import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Executable

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "f4c1a8e6b205"
PRIOR: Final = "d9c4e1a7b628"
INTELLIGENCE_REVISION: Final = "e9b2c4d7a150"
#: Where `upgrade head` lands, which the database tier reads back out of
#: `alembic_version`. That is a position in the chain rather than a property of
#: this revision, so it moves whenever a revision is added; the chain test below
#: is written not to depend on it.
ENTITY_REVISION: Final = "9def3c2e63bb"
ALIAS_REVISION: Final = "b7f4d1a92c36"
CAPABILITY_REVISION: Final = "c1a7e4b93d58"
GOVERNANCE_REVISION: Final = "d2b8f5c04e71"
#: The unresolved-mention capability admission, between governance and head.
QUEUE_REVISION: Final = "e4d7b2f9a316"
MENTION_REVISION: Final = "f3a8c1d7e592"
#: The Work task and commitment contracts, which stack on the intelligence
#: plane and carry the head until the Relationship Memory plane stacks on them.
WORK_REVISION: Final = "a4d9e7c2b615"
#: The Relationship Memory plane, which is where `upgrade head` now lands.
#: `WORK_REVISION` above was head until this revision stacked on it;
#: naming both keeps the chain assertion below a statement about the order
#: rather than about whichever revision happens to be last.
MEMORY_REVISION: Final = "f1c6b904a2d7"
#: The entity lifecycle and ledger revision (WP-RI-A-01), which is where
#: `upgrade head` now lands. `MEMORY_REVISION` above was head until this one
#: stacked on it; naming both keeps the chain assertion below a statement about
#: the order rather than about whichever revision happens to be last.
LIFECYCLE_REVISION: Final = "2fe4e13fb449"
#: Phase A's single vocabulary revision, which is where `upgrade head` now
#: lands. `LIFECYCLE_REVISION` above was head until this one stacked on it;
#: naming both keeps the chain assertion below a statement about the order
#: rather than about whichever revision happens to be last.
PHASE_A_REVISION: Final = "823e23b6cc63"
#: Phase B's vocabulary revision, which is where `upgrade head` now lands.
#: `PHASE_A_REVISION` above was head until the Phase B chain stacked on it;
#: naming both keeps the chain assertion below a statement about the order
#: rather than about whichever revision happens to be last.
PHASE_B_REVISION: Final = "b64e29a0f7c1"
PHASE_B_HEAD: Final = "3d07af4dc513"
GSQS_REVISION: Final = "c4b0a1d9e827"
PHASE_B_START: Final = "c7a1f04b9e63"
#: The chain's current head: `c99cd8ed8d1c` (RI-ENT-WP-08's blocker-clearing pass), which
#: renames the seeded `entity_relationship_types` row `design_coordinates_with` to
#: `design_coordination_with`. It stacked on `1cda4d536268` (RI-ENT-WP-07), which was head
#: before it. Written out rather than derived so chain drift fails here rather than passing.
HEAD_REVISION: Final = "b8e4d1a6c073"
GROUNDING_REVISION: Final = "b7f2c9e4a618"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260817_f4c1a8e6b205_add_goodnotes_delivery_attempt_ledger.py"
)
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_delivery_attempt_migration_test"
NEW_TABLES: Final = frozenset({"goodnotes_delivery_attempts"})
FROZEN_STATES: Final = ("PREPARED", "SENT", "ACKNOWLEDGED", "FAILED")


def _administer(maintenance: Engine, *statements: Executable) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _tables(engine: Engine, schema: str = "knowledge") -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": schema},
            ).scalars()
        )


def _state_check(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = 'knowledge' "
                "AND t.relname = 'goodnotes_delivery_attempts' "
                "AND c.conname = 'goodnotes_delivery_attempt_state_is_known'"
            )
        ).scalar_one_or_none()


@pytest.fixture
def disposable_database() -> Iterator[str]:
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
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


def test_the_chain_has_one_head_and_this_revision_is_on_it() -> None:
    """One unbranched head, and this revision on the chain below it.

    Asserts a single head and this revision's place on the chain rather than
    which revision happens to be last: the head it named was another revision's,
    so it had to be re-pinned by every work package that added one.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(ENTITY_REVISION).down_revision == REVISION
    assert script.get_revision(ALIAS_REVISION).down_revision == ENTITY_REVISION
    assert script.get_revision(CAPABILITY_REVISION).down_revision == ALIAS_REVISION
    assert script.get_revision(GOVERNANCE_REVISION).down_revision == CAPABILITY_REVISION
    assert script.get_revision(QUEUE_REVISION).down_revision == GOVERNANCE_REVISION
    assert script.get_revision(MENTION_REVISION).down_revision == QUEUE_REVISION
    assert script.get_revision(INTELLIGENCE_REVISION).down_revision == MENTION_REVISION
    assert script.get_revision(WORK_REVISION).down_revision == INTELLIGENCE_REVISION
    assert script.get_revision(MEMORY_REVISION).down_revision == WORK_REVISION
    assert script.get_revision(PHASE_A_REVISION).down_revision == LIFECYCLE_REVISION
    assert script.get_revision(GSQS_REVISION).down_revision == PHASE_A_REVISION
    assert script.get_revision(PHASE_B_START).down_revision == GSQS_REVISION
    assert script.get_revision(PHASE_B_REVISION).down_revision == "a1f7d3c85e40"
    assert script.get_revision(PHASE_B_HEAD).down_revision == PHASE_B_REVISION
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(REVISION).down_revision == PRIOR
    assert script.get_revision(PRIOR).down_revision == GROUNDING_REVISION
    # 86 migration files: 85 through `1cda4d536268` (RI-ENT-WP-07), plus
    # `c99cd8ed8d1c` (commit `37ead78`, RI-ENT-WP-08's blocker-clearing pass),
    # which renames the seeded entity_relationship_types row
    # `design_coordinates_with` to `design_coordination_with`.
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 87


def test_the_revision_imports_neither_tables_nor_domain_enums() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "my_pa.infrastructure.persistence.tables" not in imported
    assert not any(module.startswith("my_pa.domain") for module in imported)
    assert "from my_pa" not in source
    assert "GoodNotesDeliveryAttemptState" not in source
    assert "capability_is_known" not in source


def test_the_frozen_sql_names_attempt_windows_and_immutability() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE knowledge.goodnotes_delivery_attempts" in source
    assert "ON DELETE CASCADE" not in source
    assert "ON DELETE RESTRICT" in source
    assert "goodnotes_delivery_attempts_are_immutable" in source
    assert "one_goodnotes_delivery_attempt_window" in source
    assert "gndla_" in source
    assert "one_goodnotes_delivery_summary" not in source
    for state in FROZEN_STATES:
        assert f"'{state}'" in source
    assert "ALTER TABLE knowledge.goodnotes_run_note_changes" not in source


@pytest.mark.database
def test_empty_database_reaches_the_new_head(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == HEAD_REVISION
        assert _tables(engine) >= NEW_TABLES
        definition = _state_check(engine)
        assert definition is not None
        for state in FROZEN_STATES:
            assert state in definition
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_removes_attempt_table_and_leaves_receipts(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        command.downgrade(_config(), PRIOR)
        remaining = _tables(engine)
        assert NEW_TABLES.isdisjoint(remaining)
        assert "goodnotes_delivery_receipts" in remaining
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == PRIOR
    finally:
        engine.dispose()


@pytest.mark.database
def test_attempt_windows_are_immutable_and_refuse_unknown_states(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_notebooks "
                    "(principal_id, notebook_id, source_root_id, identity_status, "
                    " created_at, last_observed_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'icloud-goodnotes', 'ACTIVE',"
                    " '2026-08-17T12:00:00+00', '2026-08-17T12:00:00+00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_ingestion_runs "
                    "(principal_id, run_id, source_root_id, trigger_type, request_id, "
                    " idempotency_key, request_fingerprint, started_at, status) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'icloud-goodnotes', 'MANUAL', 'req-attempt',"
                    " 'req-attempt',"
                    " 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',"
                    " '2026-08-17T12:00:00+00', 'RUNNING')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_delivery_attempts "
                    "(principal_id, attempt_id, run_id, destination, idempotency_token, "
                    " state, created_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gndla_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'operator-local',"
                    " 'token-prepared',"
                    " 'PREPARED', '2026-08-17T12:00:00+00')"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError, match="append only"):
            connection.execute(
                text(
                    "UPDATE knowledge.goodnotes_delivery_attempts "
                    "SET state = 'SENT' "
                    "WHERE attempt_id = 'gndla_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError, match="append only"):
            connection.execute(
                text(
                    "DELETE FROM knowledge.goodnotes_delivery_attempts "
                    "WHERE attempt_id = 'gndla_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_delivery_attempts "
                    "(principal_id, attempt_id, run_id, destination, idempotency_token, "
                    " state, created_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gndla_bbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'operator-local',"
                    " 'token-unknown',"
                    " 'DELIVERED', '2026-08-17T12:00:00+00')"
                )
            )
    finally:
        engine.dispose()
