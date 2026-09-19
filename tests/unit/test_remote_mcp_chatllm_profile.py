"""ChatLLM profile-apply renews expired grants without creating an expiry."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from my_pa.application.chatllm_data_profile import chatllm_grant_purpose
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_clients,
)

WHEN = datetime(2026, 9, 14, 12, tzinfo=UTC)
EXPIRED_AT = datetime(2026, 9, 13, 19, 48, 5, tzinfo=UTC)
CLIENT_ID = "synthetic-chatllm-client"
CLIENT_UUID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
RESOURCE = "https://my-pa.example/mcp"
SCOPE = "my-pa.read"


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
                client_name="synthetic ChatLLM",
                redirect_uris='["https://client.example/callback"]',
                registered_scopes=SCOPE,
                enabled=True,
                writes_enabled=True,
                created_at=WHEN,
            )
        )
        yield connection, RemoteIdentityRepository(connection)


def test_expired_grant_becomes_non_expiring_and_missing_grant_is_added() -> None:
    with _repository() as (_, repository):
        expired_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.CONTEXT_PREPARE,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=EXPIRED_AT,
            purpose=chatllm_grant_purpose(Capability.CONTEXT_PREPARE),
        )
        assert repository.clear_grant_expiry(grant_id=expired_id)
        added = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.CAPTURE_CREATE,
            now=WHEN,
            is_write=is_write_capability(Capability.CAPTURE_CREATE),
            resource=RESOURCE,
            expires_at=None,
            purpose=chatllm_grant_purpose(Capability.CAPTURE_CREATE),
        )
        rows = {
            row.capability: row
            for row in repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        }
        assert set(rows) == {Capability.CONTEXT_PREPARE.value, Capability.CAPTURE_CREATE.value}
        assert rows[Capability.CONTEXT_PREPARE.value].id == expired_id
        assert rows[Capability.CONTEXT_PREPARE.value].expires_at is None
        assert rows[Capability.CAPTURE_CREATE.value].id == added
        assert rows[Capability.CAPTURE_CREATE.value].expires_at is None
        assert repository.client_id_for_oauth_id(CLIENT_ID) == CLIENT_UUID


def test_clear_grant_expiry_on_active_finite_sets_null() -> None:
    """Clearing expiry on a finite-expiry active grant sets expires_at to NULL."""
    from datetime import timedelta

    future_expiry = WHEN + timedelta(days=30)
    with _repository() as (_, repository):
        finite_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=future_expiry,
            purpose=chatllm_grant_purpose(Capability.TASKS_LIST),
        )
        rows_before = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_before) == 1
        assert rows_before[0].id == finite_id
        assert rows_before[0].expires_at is not None
        assert repository.clear_grant_expiry(grant_id=finite_id)
        rows_after = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_after) == 1
        assert rows_after[0].id == finite_id
        assert rows_after[0].expires_at is None


def test_profile_apply_idempotence_after_renew() -> None:
    """Applying renew action twice is idempotent; second clear succeeds without error."""
    from datetime import timedelta

    future_expiry = WHEN + timedelta(days=30)
    with _repository() as (_, repository):
        finite_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.ENTITIES_SEARCH,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=future_expiry,
            purpose=chatllm_grant_purpose(Capability.ENTITIES_SEARCH),
        )
        assert repository.clear_grant_expiry(grant_id=finite_id)
        rows_first = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_first) == 1
        assert rows_first[0].expires_at is None
        assert repository.clear_grant_expiry(grant_id=finite_id)
        rows_second = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_second) == 1
        assert rows_second[0].id == finite_id
        assert rows_second[0].expires_at is None


def test_transaction_rollback_on_apply_failure() -> None:
    """Transaction rollback reverts prior renew/add operations on failure."""
    from datetime import timedelta

    import pytest
    from sqlalchemy.exc import IntegrityError

    future_expiry = WHEN + timedelta(days=30)
    with _repository() as (connection, repository):
        finite_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=future_expiry,
            purpose=chatllm_grant_purpose(Capability.TASKS_LIST),
        )
        rows_before = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_before) == 1
        assert rows_before[0].expires_at is not None
        with pytest.raises((IntegrityError, Exception)), connection.begin_nested():
            assert repository.clear_grant_expiry(grant_id=finite_id)
            rows_mid = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
            assert rows_mid[0].expires_at is None
            raise IntegrityError("simulated failure", None, None)
        rows_after = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_after) == 1
        assert rows_after[0].id == finite_id
        assert rows_after[0].expires_at is not None
