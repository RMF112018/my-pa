from __future__ import annotations

import io
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, func, select, text
from sqlalchemy.engine import Engine, make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.oauth import OAuthError
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    oauth_access_tokens,
    oauth_authorization_codes,
    remote_capability_grants,
    remote_clients,
    remote_security_controls,
)
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA
from my_pa.infrastructure.security.origin_authorization import OriginOAuthServer

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT / "migrations/versions/20260813_e3b7a1d5c942_add_remote_oauth_identity_and_grants.py"
)
ORIGIN_MIGRATION = (
    ROOT
    / "migrations/versions/20260814_4f6a9c2d8e17_replace_entra_remote_identity_with_origin_oauth.py"
)
REFRESH_MIGRATION = (
    ROOT / "migrations/versions/20260816_d4a8c1e7b930_add_oauth_refresh_token_families.py"
)
DISPOSABLE_DATABASE = "my_pa_origin_oauth_migration_test"
PRIOR_REVISION = "e3b7a1d5c942"


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


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


def test_runtime_remote_identity_tables_match_the_frozen_migration() -> None:
    text = MIGRATION.read_text() + ORIGIN_MIGRATION.read_text() + REFRESH_MIGRATION.read_text()
    assert {
        table.name for table in (remote_clients, remote_capability_grants, remote_security_controls)
    } == {"remote_clients", "remote_capability_grants", "remote_security_controls"}
    for table in (remote_clients, remote_capability_grants, remote_security_controls):
        assert f"CREATE TABLE identity.{table.name}" in text
        for column in table.c:
            assert column.name in text


def test_remote_controls_are_created_fail_closed() -> None:
    text = MIGRATION.read_text()
    assert "remote_enabled, writes_enabled" in text
    assert "VALUES (true, false, false, now())" in text
    assert "capability_version" in text
    assert "external_scope" in text
    assert "revoked_at" in text
    assert "expires_at" in text


def test_remote_tables_share_the_canonical_identity_metadata() -> None:
    assert REMOTE_IDENTITY_METADATA is IDENTITY_METADATA
    assert {
        "user_accounts",
        "principal_scope_grants",
        "remote_clients",
        "remote_capability_grants",
        "remote_security_controls",
        "oauth_authorization_codes",
        "oauth_access_tokens",
        "oauth_refresh_token_families",
        "oauth_refresh_tokens",
    }.issubset({table.name for table in IDENTITY_METADATA.tables.values()})


def test_origin_oauth_migration_removes_entra_identity_and_hashes_credentials() -> None:
    text = ORIGIN_MIGRATION.read_text()
    assert "DROP CONSTRAINT remote_clients_principal_id_fkey" in text
    assert "migration refused: legacy remote clients require explicit operator resolution" in text
    assert "remote_client_is_local_operator" in text
    assert str(LOCAL_OPERATOR_UUID) in text
    assert "code_hash varchar(64) PRIMARY KEY" in text
    assert "token_hash varchar(64) PRIMARY KEY" in text
    for table in (oauth_authorization_codes, oauth_access_tokens):
        assert f"CREATE TABLE identity.{table.name}" in text


@pytest.mark.database
def test_origin_oauth_migration_refuses_legacy_rows_without_schema_or_data_change(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), PRIOR_REVISION)
    engine = create_database_engine(disposable_database)
    principal_id = "10000000-0000-4000-8000-000000000001"
    client_id = "20000000-0000-4000-8000-000000000001"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO identity.user_accounts "
                    "(id, principal_id, tid, oid, first_seen_at) "
                    "VALUES (:id, :principal_id, 'legacy-tenant', 'legacy-object', now())"
                ),
                {"id": principal_id, "principal_id": principal_id},
            )
            connection.execute(
                text(
                    "INSERT INTO identity.remote_clients "
                    "(id, principal_id, oauth_client_id, enabled, created_at) "
                    "VALUES (:id, :principal_id, 'legacy-client', true, now())"
                ),
                {"id": client_id, "principal_id": principal_id},
            )

        with pytest.raises(
            Exception,
            match="migration refused: legacy remote clients require explicit operator resolution",
        ):
            command.upgrade(_config(), "head")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == (PRIOR_REVISION)
            row = connection.execute(
                text(
                    "SELECT id::text, principal_id::text, oauth_client_id, enabled "
                    "FROM identity.remote_clients"
                )
            ).one()
            assert tuple(row) == (client_id, principal_id, "legacy-client", True)
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'identity' AND table_name = 'remote_clients'"
                    )
                ).scalars()
            )
            assert {"client_name", "redirect_uris", "registered_scopes"}.isdisjoint(columns)
            oauth_tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity' "
                        "AND table_name IN ('oauth_authorization_codes', 'oauth_access_tokens')"
                    )
                ).scalars()
            )
            assert oauth_tables == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_postgresql_serializes_independent_dcr_servers_at_the_client_limit(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)

    @contextmanager
    def connections() -> Iterator[Connection]:
        with engine.begin() as connection:
            yield connection

    def service() -> OriginOAuthServer:
        return OriginOAuthServer(
            connections=connections,
            issuer="https://mcp.example.invalid",
            resource="https://mcp.example.invalid/mcp",
            supported_scopes=frozenset({"my-pa.read"}),
            now=lambda: datetime(2026, 8, 14, 12, tzinfo=UTC),
        )

    servers = (service(), service())
    payload = {
        "client_name": "Synthetic concurrent client",
        "redirect_uris": ["https://client.example.invalid/callback"],
        "token_endpoint_auth_method": "none",
    }
    try:
        for _client in range(31):
            servers[0].register_client(payload)

        def attempt(server: OriginOAuthServer) -> bool:
            try:
                server.register_client(payload)
            except OAuthError as exc:
                assert exc.error == "invalid_client_metadata"
                assert str(exc) == "active client limit reached"
                return False
            return True

        with engine.connect() as guard:
            transaction = guard.begin()
            guard.exec_driver_sql("SELECT pg_advisory_xact_lock(7420196)")
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = tuple(pool.submit(attempt, server) for server in servers)
                reached_lock = False
                for _attempt in range(200):
                    with engine.connect() as observer:
                        waiting = observer.execute(
                            text(
                                "SELECT count(*) FROM pg_locks "
                                "WHERE locktype = 'advisory' AND NOT granted"
                            )
                        ).scalar_one()
                    if waiting == 2:
                        reached_lock = True
                        break
                    time.sleep(0.01)
                transaction.commit()
                if not reached_lock:
                    for future in futures:
                        future.result(timeout=10)
                    pytest.fail("independent registrations did not reach the advisory lock")
                outcomes = tuple(future.result(timeout=10) for future in futures)

        assert outcomes.count(True) == 1
        with engine.connect() as connection:
            assert (
                connection.execute(select(func.count()).select_from(remote_clients)).scalar_one()
                == 32
            )
    finally:
        engine.dispose()
