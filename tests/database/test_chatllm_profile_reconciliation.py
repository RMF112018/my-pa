"""Isolated PostgreSQL proofs for ChatLLM profile grant reconciliation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.operation import REMOTE_CAPABILITY_VERSION, Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_clients,
)

pytestmark = pytest.mark.database

WHEN = datetime(2026, 9, 23, 12, tzinfo=UTC)
CLIENT_ID = "synthetic-chatllm-client"
CLIENT_UUID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
RESOURCE = "https://my-pa.example/mcp"
SCOPE = "my-pa.read"


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_client(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            remote_clients.insert().values(
                id=CLIENT_UUID,
                principal_id=LOCAL_OPERATOR_UUID,
                oauth_client_id=CLIENT_ID,
                client_name="synthetic ChatLLM",
                redirect_uris='["https://client.example/callback"]',
                registered_scopes=SCOPE,
                enabled=True,
                writes_enabled=True,
                created_at=WHEN,
            )
        )


def _grant_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM identity.remote_capability_grants")
            ).scalar_one()
        )


def test_db01_insert_canonical_durable_active(engine: Engine) -> None:
    _seed_client(engine)
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        grant_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=None,
            purpose=Purpose.TASK_READ,
        )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT capability, capability_version, purpose, resource, is_write, "
                "expires_at, revoked_at FROM identity.remote_capability_grants "
                "WHERE id = :id"
            ),
            {"id": grant_id},
        ).one()
    assert tuple(row) == (
        "tasks.list",
        REMOTE_CAPABILITY_VERSION,
        "task_read",
        RESOURCE,
        False,
        None,
        None,
    )


def test_db03_revoked_replacement_coexists(engine: Engine) -> None:
    _seed_client(engine)
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        first = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            purpose=Purpose.TASK_READ,
        )
        assert repository.revoke_capability_grant(
            grant_id=first, remote_client_id=CLIENT_UUID, now=WHEN
        )
        replacement = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            purpose=Purpose.TASK_READ,
        )
        assert replacement != first
    assert _grant_count(engine) == 2
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id::text, revoked_at FROM identity.remote_capability_grants "
                "ORDER BY id::text"
            )
        ).all()
        assert {tuple(row) for row in rows} == {
            (str(first), WHEN),
            (str(replacement), None),
        }


def test_db06_duplicate_unrevoked_identity_is_refused(engine: Engine) -> None:
    _seed_client(engine)
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            purpose=Purpose.TASK_READ,
        )
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        with pytest.raises(IntegrityError):
            repository.grant(
                remote_client_id=CLIENT_UUID,
                external_scope=SCOPE,
                capability=Capability.TASKS_LIST,
                now=WHEN,
                is_write=False,
                resource=RESOURCE,
                purpose=Purpose.TASK_READ,
            )
    assert _grant_count(engine) == 1


def test_db06b_duplicate_unrevoked_purpose_null_identity_is_refused(engine: Engine) -> None:
    _seed_client(engine)
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            purpose=None,
        )
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        with pytest.raises(IntegrityError):
            repository.grant(
                remote_client_id=CLIENT_UUID,
                external_scope=SCOPE,
                capability=Capability.TASKS_LIST,
                now=WHEN,
                is_write=False,
                resource=RESOURCE,
                purpose=None,
            )
    assert _grant_count(engine) == 1
