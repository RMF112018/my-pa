"""Additive WebAuthn auth-persistence migration against disposable PostgreSQL."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
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
HEAD_REVISION: Final = "2c00c9ac64bc"
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


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(maintenance, drop)
        maintenance.dispose()


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


def test_the_chain_has_one_head_and_this_revision_is_it() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(HEAD_REVISION).down_revision == PRIOR_REVISION
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 87


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
        command.upgrade(_config(), HEAD_REVISION)
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
