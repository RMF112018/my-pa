"""The operator CLI can toggle an existing client's refresh_enabled flag."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from apps.cli.remote_mcp import main
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Connection

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_clients,
)

WHEN = datetime(2026, 8, 16, 12, tzinfo=UTC)
CLIENT_ID = "synthetic-oauth-client"
CLIENT_UUID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def test_the_help_text_names_the_command() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["set-client-refresh", "--help"])
    assert raised.value.code == 0


@contextmanager
def _repository() -> Iterator[tuple[Connection, RemoteIdentityRepository]]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
        connection.execute(
            remote_clients.insert().values(
                id=CLIENT_UUID,
                principal_id=LOCAL_OPERATOR_UUID,
                oauth_client_id=CLIENT_ID,
                client_name="synthetic client",
                redirect_uris='["https://client.example/callback"]',
                registered_scopes="my-pa.read",
                enabled=True,
                writes_enabled=False,
                refresh_enabled=False,
                created_at=WHEN,
            )
        )
        yield connection, RemoteIdentityRepository(connection)


def test_an_enabled_client_toggles_only_refresh_enabled() -> None:
    with _repository() as (connection, repository):
        before = connection.execute(select(*remote_clients.c)).one()
        assert repository.set_client_refresh(oauth_client_id=CLIENT_ID, refresh_enabled=True)
        after = connection.execute(select(*remote_clients.c)).one()
        assert after.refresh_enabled is True
        assert after.oauth_client_id == before.oauth_client_id == CLIENT_ID
        assert after.id == before.id
        assert after.writes_enabled is False
        assert after.enabled is True
        assert after.revoked_at is None


def test_a_revoked_client_is_refused_and_unchanged() -> None:
    with _repository() as (connection, repository):
        connection.execute(
            remote_clients.update()
            .where(remote_clients.c.oauth_client_id == CLIENT_ID)
            .values(revoked_at=WHEN, enabled=False, writes_enabled=False)
        )
        assert not repository.set_client_refresh(oauth_client_id=CLIENT_ID, refresh_enabled=True)
        row = connection.execute(select(*remote_clients.c)).one()
        assert row.refresh_enabled is False
        assert row.revoked_at is not None


def test_an_unknown_client_is_refused() -> None:
    with _repository() as (_, repository):
        assert not repository.set_client_refresh(
            oauth_client_id="missing-client", refresh_enabled=True
        )
