"""Additive OAuth refresh-token family migration and PostgreSQL concurrency."""

from __future__ import annotations

import base64
import hashlib
import io
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, func, select, text
from sqlalchemy.engine import Engine, make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.oauth import OAuthError
from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    oauth_refresh_token_families,
    oauth_refresh_tokens,
    remote_clients,
    remote_security_controls,
)
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA
from my_pa.infrastructure.security.origin_authorization import OriginOAuthServer

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20260816_d4a8c1e7b930_add_oauth_refresh_token_families.py"
DISPOSABLE_DATABASE = "my_pa_oauth_refresh_migration_test"
PRIOR_REVISION = "a8a1272aaa0a"
OAUTH_REVISION = "d4a8c1e7b930"
LINEAGE_REVISION = "f8c3a1e6b247"
NOTE_REVISION = "c9e2b6a4d813"
PROPOSAL_REVISION = "d7e1a4c8b926"
DELIVERY_REVISION = "e8c1b5a7d204"
EXACT_RENDER_REVISION = "c3e9a7f1b204"
CONTENT_REVISION = "a4d9c2e7b815"
GROUNDING_REVISION = "b7f2c9e4a618"
ENTITY_KIND_REVISION = "d9c4e1a7b628"
ATTEMPT_REVISION = "f4c1a8e6b205"
ENTITY_REVISION = "9def3c2e63bb"
#: Where `upgrade head` lands, which the database tier reads back out of
#: `alembic_version`. That is a position in the chain rather than a property of
#: this revision, so it moves whenever a revision is added; the chain test below
#: is written not to depend on it.
HEAD_REVISION = "b7f4d1a92c36"
WHEN = datetime(2026, 8, 16, 12, tzinfo=UTC)
ISSUER = "https://mcp.example.invalid"
RESOURCE = f"{ISSUER}/mcp"
REDIRECT = "https://client.example/callback"
VERIFIER = "a" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


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


def test_runtime_refresh_tables_match_the_frozen_migration() -> None:
    source = MIGRATION.read_text()
    assert "ADD COLUMN refresh_enabled boolean NOT NULL DEFAULT false" in source
    assert "CREATE TABLE identity.oauth_refresh_token_families" in source
    assert "CREATE TABLE identity.oauth_refresh_tokens" in source
    assert "ADD COLUMN refresh_family_id uuid" in source
    assert "my_pa.domain" not in source
    assert "infrastructure.persistence.tables" not in source
    for table in (oauth_refresh_token_families, oauth_refresh_tokens):
        assert f"CREATE TABLE identity.{table.name}" in source
        for column in table.c:
            assert column.name in source


def test_refresh_tables_share_the_canonical_identity_metadata() -> None:
    assert {
        "oauth_refresh_token_families",
        "oauth_refresh_tokens",
        "oauth_access_tokens",
        "remote_clients",
    }.issubset({table.name for table in IDENTITY_METADATA.tables.values()})


def test_the_chain_has_one_head_and_this_revision_is_on_it() -> None:
    """Renamed from "is the head", because that was never the claim needed here.

    This revision stopped being the head six revisions ago; the pin survived
    because each of those revisions edited this line, and it rotted again at
    `9def3c2e63bb`. A single unbranched chain that reaches this revision, and
    the ordered links written against it, are what the tests below depend on.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert OAUTH_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(OAUTH_REVISION).down_revision == PRIOR_REVISION
    assert script.get_revision(LINEAGE_REVISION).down_revision == OAUTH_REVISION
    assert script.get_revision(NOTE_REVISION).down_revision == LINEAGE_REVISION
    assert script.get_revision(PROPOSAL_REVISION).down_revision == NOTE_REVISION
    assert script.get_revision(DELIVERY_REVISION).down_revision == PROPOSAL_REVISION
    assert script.get_revision(EXACT_RENDER_REVISION).down_revision == DELIVERY_REVISION
    assert script.get_revision(CONTENT_REVISION).down_revision == EXACT_RENDER_REVISION
    assert script.get_revision(GROUNDING_REVISION).down_revision == CONTENT_REVISION
    assert script.get_revision(ENTITY_KIND_REVISION).down_revision == GROUNDING_REVISION
    assert script.get_revision(ATTEMPT_REVISION).down_revision == ENTITY_KIND_REVISION
    assert script.get_revision(ENTITY_REVISION).down_revision == ATTEMPT_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == ENTITY_REVISION
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 60


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
            assert "oauth_refresh_token_families" in set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'identity' AND table_name = 'remote_clients'"
                    )
                ).scalars()
            )
            assert "refresh_enabled" in columns
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
            assert "oauth_refresh_token_families" in tables
            assert "oauth_refresh_tokens" in tables
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_oauth_revision_is_still_reachable(disposable_database: str) -> None:
    command.upgrade(_config(), OAUTH_REVISION)
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == OAUTH_REVISION
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
            assert "oauth_refresh_token_families" in tables
            assert "oauth_refresh_tokens" in tables
            knowledge = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'knowledge' AND table_name = 'goodnotes_notebooks'"
                    )
                ).scalars()
            )
            assert knowledge == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_prior_head_to_new_head_preserves_clients_and_disables_refresh(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), PRIOR_REVISION)
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE identity.remote_security_controls "
                    "SET remote_enabled = true, writes_enabled = false, updated_at = now() "
                    "WHERE singleton = true"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO identity.remote_clients "
                    "(id, principal_id, oauth_client_id, client_name, redirect_uris, "
                    " registered_scopes, enabled, writes_enabled, created_at) "
                    "VALUES ("
                    " 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',"
                    " '24abf5d2-d0c2-5e1c-82f6-e72425e9ed37',"
                    " 'pre-existing-client', 'legacy', '[]', 'my-pa.read',"
                    " true, false, now())"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO identity.oauth_access_tokens "
                    "(token_hash, remote_client_id, scope, resource, expires_at, created_at) "
                    "VALUES ("
                    " 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',"
                    " 'my-pa.read', 'https://mcp.example.invalid/mcp', now() + interval '1 hour',"
                    " now())"
                )
            )
        command.upgrade(_config(), OAUTH_REVISION)
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT oauth_client_id, refresh_enabled, enabled FROM identity.remote_clients"
                )
            ).one()
            assert row.oauth_client_id == "pre-existing-client"
            assert row.refresh_enabled is False
            assert row.enabled is True
            tokens = connection.execute(text("SELECT count(*) FROM identity.oauth_access_tokens"))
            assert tokens.scalar_one() == 1
            family_id = connection.execute(
                text("SELECT refresh_family_id FROM identity.oauth_access_tokens")
            ).scalar_one()
            assert family_id is None
    finally:
        engine.dispose()


@pytest.mark.database
def test_concurrent_refresh_serializes_to_one_active_generation(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)

    @contextmanager
    def connections() -> Iterator[Connection]:
        with engine.begin() as connection:
            yield connection

    service = OriginOAuthServer(
        connections=connections,
        issuer=ISSUER,
        resource=RESOURCE,
        supported_scopes=frozenset({"my-pa.read"}),
        now=lambda: WHEN,
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                remote_security_controls.update()
                .where(remote_security_controls.c.singleton.is_(True))
                .values(remote_enabled=True, writes_enabled=False, updated_at=WHEN)
            )
        client_id = str(
            service.register_client(
                {
                    "client_name": "Concurrent",
                    "redirect_uris": [REDIRECT],
                    "scope": "my-pa.read",
                }
            )["client_id"]
        )
        with engine.begin() as connection:
            repository = RemoteIdentityRepository(connection)
            repository.set_client_refresh(oauth_client_id=client_id, refresh_enabled=True)
            remote_id = connection.execute(
                select(remote_clients.c.id).where(remote_clients.c.oauth_client_id == client_id)
            ).scalar_one()
            repository.grant(
                remote_client_id=remote_id,
                external_scope="my-pa.read",
                capability=Capability.CAPABILITIES_GET,
                now=WHEN,
                is_write=False,
                resource=RESOURCE,
            )
        raw_code = service.issue_authorization_code(
            service.validate_authorization(
                {
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": REDIRECT,
                    "scope": "my-pa.read",
                    "state": "state",
                    "code_challenge": CHALLENGE,
                    "code_challenge_method": "S256",
                    "resource": RESOURCE,
                }
            )
        )
        issued = service.issue_token(
            {
                "grant_type": "authorization_code",
                "code": raw_code,
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "code_verifier": VERIFIER,
                "resource": RESOURCE,
            }
        )
        refresh = str(issued["refresh_token"])

        def attempt() -> bool:
            try:
                service.issue_token(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                        "client_id": client_id,
                        "resource": RESOURCE,
                    }
                )
            except OAuthError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(lambda _item: attempt(), range(2)))
        assert outcomes.count(True) <= 1
        with engine.connect() as connection:
            active = connection.execute(
                select(func.count())
                .select_from(oauth_refresh_tokens)
                .where(
                    oauth_refresh_tokens.c.consumed_at.is_(None),
                    oauth_refresh_tokens.c.revoked_at.is_(None),
                )
            ).scalar_one()
            assert int(active) <= 1
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
            assert "oauth_refresh_tokens" not in tables
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'identity' AND table_name = 'remote_clients'"
                    )
                ).scalars()
            )
            assert "refresh_enabled" not in columns
        command.upgrade(_config(), "head")
    finally:
        engine.dispose()
