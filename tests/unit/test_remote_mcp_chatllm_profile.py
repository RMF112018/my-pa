"""ChatLLM profile CLI emits the chatllm-profile-cli-v1 JSON contract."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.cli import remote_mcp as command
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from my_pa.application.chatllm_data_profile import (
    chatllm_grant_purpose,
    desired_effective_capabilities,
)
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.gateway import application_composition_state
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.operation import (
    REMOTE_CAPABILITY_VERSION,
    Capability,
    is_write_capability,
)
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_clients,
    remote_security_controls,
)

WHEN = datetime(2026, 9, 23, 12, tzinfo=UTC)
EXPIRED_AT = datetime(2026, 9, 13, 19, 48, 5, tzinfo=UTC)
CLIENT_ID = "synthetic-chatllm-client"
CLIENT_UUID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
RESOURCE = "https://my-pa.example/mcp"
SCOPE = "my-pa.read"
PROFILE_VERSION = "chatllm-data-v2"

GOLDEN_KEYS = [
    "schema_version",
    "command",
    "profile_version",
    "target",
    "eligibility",
    "gates",
    "pre",
    "post",
    "applied",
    "committed",
    "converged",
    "rolled_back",
    "failure",
]


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://localhost/my_pa",
        oauth_audience=RESOURCE,
        oauth_scopes=SCOPE,
        mcp_chatllm_gateway_enabled=True,
        mcp_chatllm_gateway_oauth_client_ids=CLIENT_ID,
    )


def _seed_converged(connection: Connection) -> None:
    repository = RemoteIdentityRepository(connection)
    settings = _settings()
    state = application_composition_state(settings)
    desired = desired_effective_capabilities(frozenset(_HANDLERS), state)
    for capability in sorted(desired, key=lambda item: item.value):
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


@contextmanager
def _cli(monkeypatch: pytest.MonkeyPatch, *, converged: bool = False) -> Iterator[Engine]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
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
        connection.execute(
            remote_security_controls.insert().values(
                singleton=True,
                remote_enabled=True,
                writes_enabled=True,
                updated_at=WHEN,
            )
        )
        if converged:
            _seed_converged(connection)
    monkeypatch.setattr(command, "load_settings", _settings)
    monkeypatch.setattr(command, "create_database_engine", lambda *args, **kwargs: engine)
    try:
        yield engine
    finally:
        engine.dispose()


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


def _renew(
    repository: RemoteIdentityRepository,
    *,
    grant_id: UUID,
    capability: Capability,
    is_write: bool,
) -> bool:
    return repository.renew_canonical_grant(
        grant_id=grant_id,
        remote_client_id=CLIENT_UUID,
        external_scope=SCOPE,
        capability=capability,
        capability_version=REMOTE_CAPABILITY_VERSION,
        purpose=chatllm_grant_purpose(capability),
        resource=RESOURCE,
        is_write=is_write,
    )


def _profile_args(command_name: str) -> list[str]:
    return [
        command_name,
        "--oauth-client-id",
        CLIENT_ID,
        "--scope",
        SCOPE,
        "--resource",
        RESOURCE,
        "--profile-version",
        PROFILE_VERSION,
    ]


def test_golden_schema_key_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch):
        assert command.main(_profile_args("profile-diff")) == 1
        payload = json.loads(capsys.readouterr().out)
        assert list(payload) == GOLDEN_KEYS
        assert payload["schema_version"] == "chatllm-profile-cli-v1"
        assert payload["command"] == "profile-diff"
        assert payload["profile_version"] == PROFILE_VERSION
        assert payload["post"] is None
        assert payload["applied"] is False
        assert payload["committed"] is False
        assert payload["converged"] is False
        assert payload["rolled_back"] is False
        assert payload["failure"] is None
        assert list(payload["target"]) == [
            "client_fingerprint",
            "resource_fingerprint",
            "scope",
            "capability_version",
        ]
        assert payload["target"]["capability_version"] == REMOTE_CAPABILITY_VERSION
        assert list(payload["eligibility"]) == ["inspectable", "apply_eligible", "blockers"]
        assert list(payload["gates"]) == [
            "process_remote_writes_enabled",
            "client_writes_enabled",
            "global_remote_writes_enabled",
            "remote_enabled",
            "runtime_writes_effective",
        ]
        assert list(payload["pre"]) == [
            "healthy",
            "desired_effective_count",
            "desired_effective",
            "conditions",
            "actions",
            "counts",
        ]
        assert list(payload["pre"]["counts"]) == ["add", "renew", "revoke", "noop", "blocking"]
        assert payload["pre"]["conditions"]
        assert list(payload["pre"]["conditions"][0]) == [
            "capability",
            "code",
            "severity",
            "count",
            "grant_refs",
        ]
        assert payload["pre"]["actions"]
        assert list(payload["pre"]["actions"][0]) == [
            "kind",
            "capability",
            "purpose",
            "is_write",
            "grant_ref",
        ]
        assert payload["pre"]["actions"][0]["grant_ref"] is None


def test_json_never_emits_raw_identifiers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch):
        command.main(_profile_args("profile-diff"))
        text = capsys.readouterr().out
        assert CLIENT_ID not in text
        assert RESOURCE not in text
        assert str(CLIENT_UUID) not in text
        assert "sha256:" in text
        payload = json.loads(text)
        assert payload["target"]["client_fingerprint"].startswith("sha256:")
        assert payload["target"]["resource_fingerprint"].startswith("sha256:")


def test_converged_profile_diff_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch, converged=True):
        assert command.main(_profile_args("profile-diff")) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["converged"] is True
        assert payload["pre"]["healthy"] is True
        assert payload["eligibility"]["apply_eligible"] is True


def test_divergent_profile_diff_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch):
        assert command.main(_profile_args("profile-diff")) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["converged"] is False
        assert payload["pre"]["healthy"] is False
        assert payload["pre"]["counts"]["add"] > 0


def test_unknown_client_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch):
        with pytest.raises(SystemExit) as raised:
            command.main(
                [
                    "profile-diff",
                    "--oauth-client-id",
                    "missing-client",
                    "--scope",
                    SCOPE,
                    "--resource",
                    RESOURCE,
                    "--profile-version",
                    PROFILE_VERSION,
                ]
            )
        assert raised.value.code == 2


def test_unsupported_profile_version_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch):
        with pytest.raises(SystemExit) as raised:
            command.main(
                [
                    "profile-diff",
                    "--oauth-client-id",
                    CLIENT_ID,
                    "--scope",
                    SCOPE,
                    "--resource",
                    RESOURCE,
                    "--profile-version",
                    "chatllm-data-v9",
                ]
            )
        assert raised.value.code == 2


def test_profile_apply_without_apply_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch):
        with pytest.raises(SystemExit) as raised:
            command.main(_profile_args("profile-apply"))
        assert raised.value.code == 2


def test_profile_apply_success_implies_committed_and_converged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch):
        assert command.main([*_profile_args("profile-apply"), "--apply"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["applied"] is True
        assert payload["committed"] is True
        assert payload["converged"] is True
        assert payload["rolled_back"] is False
        assert payload["post"] is not None
        assert payload["post"]["healthy"] is True
        assert payload["post"]["counts"]["add"] == 0
        assert payload["post"]["counts"]["renew"] == 0
        assert payload["post"]["counts"]["revoke"] == 0


def test_profile_apply_already_converged_is_zero_mutation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch, converged=True):
        assert command.main([*_profile_args("profile-apply"), "--apply"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["applied"] is True
        assert payload["committed"] is True
        assert payload["converged"] is True
        assert payload["pre"]["counts"]["add"] == 0
        assert payload["pre"]["counts"]["renew"] == 0
        assert payload["pre"]["counts"]["revoke"] == 0


def test_profile_apply_ineligible_exits_one_without_mutation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _cli(monkeypatch) as engine:
        with engine.begin() as connection:
            connection.execute(
                remote_clients.update()
                .where(remote_clients.c.oauth_client_id == CLIENT_ID)
                .values(enabled=False)
            )
        assert command.main([*_profile_args("profile-apply"), "--apply"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["eligibility"]["apply_eligible"] is False
        assert "CLIENT_DISABLED" in payload["eligibility"]["blockers"]
        assert payload["applied"] is False
        assert payload["committed"] is False
        assert payload["converged"] is False
        assert payload["rolled_back"] is False


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
        assert _renew(
            repository, grant_id=expired_id, capability=Capability.CONTEXT_PREPARE, is_write=False
        )
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


def test_renew_canonical_grant_on_active_finite_sets_null() -> None:
    """Renewing a finite-expiry active grant sets expires_at to NULL."""
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
        assert _renew(
            repository, grant_id=finite_id, capability=Capability.TASKS_LIST, is_write=False
        )
        rows_after = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_after) == 1
        assert rows_after[0].id == finite_id
        assert rows_after[0].expires_at is None


def test_profile_apply_renew_idempotence_after_renew() -> None:
    """Renewing twice is idempotent; the second renew succeeds without error."""
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
        assert _renew(
            repository, grant_id=finite_id, capability=Capability.ENTITIES_SEARCH, is_write=False
        )
        rows_first = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_first) == 1
        assert rows_first[0].expires_at is None
        assert _renew(
            repository, grant_id=finite_id, capability=Capability.ENTITIES_SEARCH, is_write=False
        )
        rows_second = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_second) == 1
        assert rows_second[0].id == finite_id
        assert rows_second[0].expires_at is None


def test_transaction_rollback_on_apply_failure() -> None:
    """Transaction rollback reverts prior renew/add operations on failure."""
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
            assert _renew(
                repository, grant_id=finite_id, capability=Capability.TASKS_LIST, is_write=False
            )
            rows_mid = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
            assert rows_mid[0].expires_at is None
            raise IntegrityError("simulated failure", None, None)
        rows_after = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_after) == 1
        assert rows_after[0].id == finite_id
        assert rows_after[0].expires_at is not None
