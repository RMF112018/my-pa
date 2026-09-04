"""Additive WebAuthn auth-persistence migration against disposable PostgreSQL."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA
from my_pa.infrastructure.persistence.webauthn_auth import (
    auth_sessions,
    recovery_code_sets,
    recovery_codes,
    webauthn_challenges,
    webauthn_credentials,
)

ROOT: Final = Path(__file__).resolve().parents[2]
MIGRATION: Final = ROOT / (
    "migrations/versions/20260901_2c00c9ac64bc_add_webauthn_auth_persistence.py"
)
PRIOR_REVISION: Final = "c99cd8ed8d1c"
#: This module's subject revision: UI-IMP-WP02's auth-persistence revision.
REVISION: Final = "2c00c9ac64bc"
#: The link directly above `REVISION`. `2c00c9ac64bc` was head on `origin/main`;
#: merging RI-ENT-WP-10/11 into it re-parented `16f05c46b8c3` -- which had also
#: been written against `c99cd8ed8d1c` -- onto `REVISION` (RULING-M11).
NEXT_REVISION: Final = "16f05c46b8c3"
#: The RI successor above `NEXT_REVISION`: `b8e4d1a6c073` (RI-ENT-WP-12,
#: backfilling one
#: `display`-typed `entity_names` row per active `entities` row), likewise
#: written against `c99cd8ed8d1c` and re-parented onto `NEXT_REVISION` once
#: RI-ENT-WP-10/11 merged, so the head this suite must see is that one and
#: `REVISION` is two links beneath it. Written out rather than derived so chain
#: drift fails here rather than passing.
HEAD_REVISION: Final = "b8e4d1a6c073"
#: PR192's graph-vocabulary migration directly above `HEAD_REVISION`.
GRAPH_REVISION: Final = "c3f8a1d07e94"
#: The additive GoodNotes migration directly above `GRAPH_REVISION`, and the
#: sole current chain head.
CURRENT_HEAD_REVISION: Final = "6a2f9d1c4b80"
NEW_TABLES: Final = frozenset(
    {
        "webauthn_credentials",
        "webauthn_challenges",
        "recovery_code_sets",
        "recovery_codes",
        "auth_sessions",
    }
)
DISPOSABLE_DATABASE: Final = "my_pa_webauthn_auth_persistence_schema_test"


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def test_runtime_tables_match_the_frozen_migration() -> None:
    source = MIGRATION.read_text()
    assert "CREATE TABLE identity.webauthn_credentials" in source
    assert "CREATE TABLE identity.webauthn_challenges" in source
    assert "CREATE TABLE identity.recovery_code_sets" in source
    assert "CREATE TABLE identity.recovery_codes" in source
    assert "CREATE TABLE identity.auth_sessions" in source
    assert "my_pa.domain" not in source
    assert "infrastructure.persistence" not in source
    assert "WebAuthnChallengePurpose" not in source
    assert "'registration'" in source
    assert "'credential_administration'" in source
    for table in (
        webauthn_credentials,
        webauthn_challenges,
        recovery_code_sets,
        recovery_codes,
        auth_sessions,
    ):
        assert f"CREATE TABLE identity.{table.name}" in source
        for column in table.c:
            assert column.name in source


def test_tables_share_the_canonical_identity_metadata() -> None:
    assert NEW_TABLES.issubset({table.name for table in IDENTITY_METADATA.tables.values()})


def test_the_chain_has_one_head_and_this_revision_is_four_links_beneath_it() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [CURRENT_HEAD_REVISION]
    assert script.get_revision(CURRENT_HEAD_REVISION).down_revision == GRAPH_REVISION
    assert script.get_revision(GRAPH_REVISION).down_revision == HEAD_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == NEXT_REVISION
    assert script.get_revision(NEXT_REVISION).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PRIOR_REVISION
    # 91 on the merged tree: 88 at `16f05c46b8c3`, plus `b8e4d1a6c073`, the
    # graph vocabulary admission, and additive GoodNotes successor.
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 91


@pytest.mark.database
def test_empty_database_reaches_the_new_head(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == CURRENT_HEAD_REVISION
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
            assert tables >= NEW_TABLES
            assert "user_accounts" in tables
    finally:
        engine.dispose()


@pytest.mark.database
def test_prior_head_to_new_head_adds_only_these_tables(disposable_database: str) -> None:
    command.upgrade(_config(), PRIOR_REVISION)
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            before = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            after = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
            assert after - before == NEW_TABLES
            names = set(
                connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = 'identity' AND t.relname = 'webauthn_challenges'"
                    )
                ).scalars()
            )
            assert "webauthn_challenge_purpose_is_known" in names
            assert "webauthn_challenge_expires_after_creation" in names
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_round_trip_from_new_head(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    command.downgrade(_config(), PRIOR_REVISION)
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
            assert NEW_TABLES.isdisjoint(tables)
            assert "user_accounts" in tables
        command.upgrade(_config(), "head")
        command.downgrade(_config(), "base")
        with engine.connect() as connection:
            leftover = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema IN ('identity', 'knowledge')"
                    )
                ).scalars()
            )
            assert leftover == set()
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
