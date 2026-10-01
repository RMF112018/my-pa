"""ChatLLM profile-apply renews expired grants without creating an expiry."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from apps.cli.remote_mcp import _run_profile_command
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
)
from my_pa.application.service import _HANDLERS
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.chatllm_capability_policy import CHATLLM_DATA_PROFILE_VERSION
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.domain.identity.purpose import Purpose
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


#: Meeting Records WP-MTG-05: the six grants profile-apply must add, with the
#: single purpose each is stamped with.
_MEETING_PURPOSES = {
    Capability.MEETINGS_READ: Purpose.MEETING_READ,
    Capability.MEETINGS_LIST: Purpose.MEETING_READ,
    Capability.MEETINGS_SEARCH: Purpose.MEETING_READ,
    Capability.MEETINGS_CREATE: Purpose.MEETING_AUTHORING,
    Capability.MEETINGS_UPDATE: Purpose.MEETING_AUTHORING,
    Capability.MEETINGS_SERIES_UPDATE: Purpose.MEETING_AUTHORING,
}
_MEETING_WRITES = frozenset(
    {
        Capability.MEETINGS_CREATE,
        Capability.MEETINGS_UPDATE,
        Capability.MEETINGS_SERIES_UPDATE,
    }
)
#: A synthetic, fully composed deployment. Stands in for `Settings` so the
#: profile command never loads configuration or opens a database of its own.
_FULL_PLANE_SETTINGS = SimpleNamespace(
    managed_documents_are_composed=lambda: True,
    relationship_intelligence_enabled=True,
    relationship_intelligence_writes_enabled=True,
    relationship_memory_enabled=True,
)


def _profile(
    repository: RemoteIdentityRepository,
    command: str,
    capsys: pytest.CaptureFixture[str],
    *,
    profile_version: str = CHATLLM_DATA_PROFILE_VERSION,
) -> tuple[int, dict[str, object]]:
    """Run the operator profile command against the in-test store only."""
    args = argparse.Namespace(
        command=command,
        oauth_client_id=CLIENT_ID,
        scope=SCOPE,
        resource=RESOURCE,
        profile_version=profile_version,
        apply=command == "profile-apply",
    )
    code = _run_profile_command(
        argparse.ArgumentParser(prog="remote_mcp"),
        args,
        repository,
        _FULL_PLANE_SETTINGS,  # type: ignore[arg-type]
        WHEN,
    )
    return code, json.loads(capsys.readouterr().out)


def _grant_v2_catalog(repository: RemoteIdentityRepository) -> frozenset[Capability]:
    """Converge the client on everything the profile wants except the Meetings."""
    desired = desired_effective_capabilities(
        composed_capabilities(
            frozenset(_HANDLERS),
            ChatLLMCompositionPlanes(
                managed_documents=True,
                relationship_intelligence=True,
                relationship_intelligence_writes=True,
                relationship_memory=True,
                constraints=True,
            ),
        )
    )
    assert frozenset(_MEETING_PURPOSES) <= desired
    for capability in sorted(desired - frozenset(_MEETING_PURPOSES), key=lambda c: c.value):
        repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=capability,
            now=WHEN,
            is_write=is_write_capability(capability),
            resource=RESOURCE,
            expires_at=None,
            purpose=chatllm_grant_purpose(capability),
        )
    return desired


def test_profile_apply_adds_the_meeting_grants_once_and_then_converges(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _repository() as (_, repository):
        desired = _grant_v2_catalog(repository)
        code, plan = _profile(repository, "profile-plan", capsys)
        assert code == 1
        assert plan["profile_version"] == "chatllm-data-v5"
        assert plan["healthy"] is False
        assert plan["actions"] == [
            {
                "kind": "add",
                "capability": capability.value,
                "purpose": purpose.value,
                "write": capability in _MEETING_WRITES,
                "grant_id": None,
            }
            for capability, purpose in sorted(_MEETING_PURPOSES.items(), key=lambda i: i[0].value)
        ]

        code, applied = _profile(repository, "profile-apply", capsys)
        assert code == 0
        assert applied["applied"] is True
        rows = repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        assert len(rows) == len(desired)
        meeting_rows = {
            row.capability: row for row in rows if row.capability.startswith("meetings.")
        }
        assert set(meeting_rows) == {capability.value for capability in _MEETING_PURPOSES}
        for capability, purpose in _MEETING_PURPOSES.items():
            row = meeting_rows[capability.value]
            assert row.purpose == purpose.value
            assert row.is_write is (capability in _MEETING_WRITES)
            assert row.capability_version == "v1"
            assert row.resource == RESOURCE
            assert row.external_scope == SCOPE
            assert row.expires_at is None
            assert row.revoked_at is None

        code, again = _profile(repository, "profile-apply", capsys)
        assert code == 0
        assert again["actions"] == []
        assert again["healthy"] is True
        assert len(repository.list_capability_grants(remote_client_id=CLIENT_UUID)) == len(desired)
        code, diff = _profile(repository, "profile-diff", capsys)
        assert code == 0
        assert diff["healthy"] is True
        assert diff["add"] == []
        assert diff["failing"] == []


def test_profile_commands_refuse_the_previous_profile_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _repository() as (_, repository):
        _grant_v2_catalog(repository)
        with pytest.raises(SystemExit) as raised:
            _profile(repository, "profile-apply", capsys, profile_version="chatllm-data-v3")
        assert raised.value.code == 2
        assert "profile version must be chatllm-data-v5" in capsys.readouterr().err
        rows = repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        assert not any(row.capability.startswith("meetings.") for row in rows)
