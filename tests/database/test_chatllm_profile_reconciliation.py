"""Isolated PostgreSQL proofs for ChatLLM profile grant reconciliation."""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import UUID

import pytest
from apps.cli import remote_mcp as command
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import Settings
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


PROFILE_VERSION = "chatllm-data-v2"


def _rows(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT id::text, capability, purpose, is_write, expires_at, revoked_at "
                    "FROM identity.remote_capability_grants ORDER BY id::text"
                )
            ).all()
        ]


def _bind_cli(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    def settings() -> Settings:
        return Settings(
            database_url=url,
            oauth_audience=RESOURCE,
            oauth_scopes=SCOPE,
            mcp_chatllm_gateway_enabled=True,
            mcp_chatllm_gateway_oauth_client_ids=CLIENT_ID,
        )

    monkeypatch.setattr(command, "load_settings", settings)
    monkeypatch.setattr(
        command,
        "create_database_engine",
        lambda *args, **kwargs: create_database_engine(url),
    )


def _apply() -> tuple[int, dict[str, object]]:
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = command.main(
            [
                "profile-apply",
                "--oauth-client-id",
                CLIENT_ID,
                "--scope",
                SCOPE,
                "--resource",
                RESOURCE,
                "--profile-version",
                PROFILE_VERSION,
                "--apply",
            ]
        )
    return code, json.loads(stdout.getvalue())


def test_apply_uses_the_locked_reread_not_an_earlier_plan(
    engine: Engine, disposable_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grant inserted after a healthy plan is revoked by apply's own reread."""
    _seed_client(engine)
    with engine.begin() as connection:
        RemoteIdentityRepository(connection).grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            purpose=Purpose.TASK_READ,
        )
    holder_locked = threading.Event()
    release_holder = threading.Event()

    def hold() -> None:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text("SELECT id FROM identity.remote_clients WHERE id = :id FOR UPDATE"),
                {"id": CLIENT_UUID},
            )
            holder_locked.set()
            assert release_holder.wait(timeout=30)
            RemoteIdentityRepository(connection).grant(
                remote_client_id=CLIENT_UUID,
                external_scope=SCOPE,
                capability=Capability.TASKS_LIST,
                now=WHEN,
                is_write=False,
                resource=RESOURCE,
                purpose=Purpose.STATUS_OBSERVATION,
            )
            transaction.commit()

    worker = threading.Thread(target=hold)
    worker.start()
    assert holder_locked.wait(timeout=30)
    _bind_cli(monkeypatch, disposable_database)
    apply_done = threading.Event()
    result: dict[str, object] = {}

    def apply() -> None:
        code, payload = _apply()
        result["code"] = code
        result["payload"] = payload
        apply_done.set()

    applier = threading.Thread(target=apply)
    applier.start()
    for _ in range(50):
        with engine.connect() as connection:
            waiting = connection.execute(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE relation = 'identity.remote_clients'::regclass AND NOT granted"
                )
            ).scalar_one()
        if waiting:
            break
        threading.Event().wait(0.1)
    release_holder.set()
    applier.join(timeout=60)
    worker.join(timeout=30)
    assert apply_done.is_set()
    assert result["code"] == 0
    payload = result["payload"]
    assert isinstance(payload, dict)
    assert payload["converged"] is True
    assert payload["rolled_back"] is False
    active_tasks = [row for row in _rows(engine) if row[1] == "tasks.list" and row[5] is None]
    assert [(row[2], row[3]) for row in active_tasks] == [("task_read", False)]


def test_action_failure_rolls_back_to_the_prestate(
    engine: Engine, disposable_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
            expires_at=WHEN + timedelta(hours=1),
        )
        repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            purpose=Purpose.STATUS_OBSERVATION,
        )
    before = _rows(engine)
    _bind_cli(monkeypatch, disposable_database)

    def fail_renew(self: RemoteIdentityRepository, **kwargs: object) -> bool:
        raise RuntimeError("injected renew failure")

    monkeypatch.setattr(RemoteIdentityRepository, "renew_canonical_grant", fail_renew)
    code, payload = _apply()
    assert code == 3
    assert payload["applied"] is False
    assert payload["committed"] is False
    assert payload["rolled_back"] is True
    assert _rows(engine) == before


def test_repeated_and_concurrent_apply_leave_one_canonical_set(
    engine: Engine, disposable_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_client(engine)
    _bind_cli(monkeypatch, disposable_database)
    first, first_payload = _apply()
    second, second_payload = _apply()
    assert first == 0
    assert first_payload["converged"] is True
    assert second == 0
    assert second_payload["pre"]["counts"]["add"] == 0  # type: ignore[index]
    assert second_payload["converged"] is True
    after_repeat = _grant_count(engine)

    codes: list[int] = []

    def apply_once() -> None:
        codes.append(
            command.main(
                [
                    "profile-apply",
                    "--oauth-client-id",
                    CLIENT_ID,
                    "--scope",
                    SCOPE,
                    "--resource",
                    RESOURCE,
                    "--profile-version",
                    PROFILE_VERSION,
                    "--apply",
                ]
            )
        )

    left = threading.Thread(target=apply_once)
    right = threading.Thread(target=apply_once)
    left.start()
    right.start()
    left.join(timeout=120)
    right.join(timeout=120)
    assert sorted(codes) == [0, 0]
    assert _grant_count(engine) == after_repeat
