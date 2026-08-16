"""Rotating refresh-token lifecycle, binding, replay, and redaction."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, create_engine, select, update
from sqlalchemy.engine import Engine

from my_pa.contracts.oauth import OAuthError
from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    oauth_access_tokens,
    oauth_refresh_token_families,
    oauth_refresh_tokens,
    remote_capability_grants,
    remote_clients,
    remote_security_controls,
)
from my_pa.infrastructure.security.origin_authorization import (
    TOKEN_LIFETIME,
    OriginOAuthServer,
)
from my_pa.infrastructure.security.remote_oauth import RemoteAuthenticator, redact_security_value

WHEN = datetime(2026, 8, 16, 12, tzinfo=UTC)
ISSUER = "https://mcp.example.invalid"
RESOURCE = f"{ISSUER}/mcp"
REDIRECT = "https://client.example/callback"
VERIFIER = "a" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    built = create_engine("sqlite://")
    with built.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
        connection.execute(
            remote_security_controls.insert().values(
                singleton=True,
                remote_enabled=True,
                writes_enabled=True,
                updated_at=WHEN,
            )
        )
    yield built
    built.dispose()


class Clock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def __call__(self) -> datetime:
        return self.instant


def server(
    engine: Engine,
    clock: Clock,
    *,
    events: list[dict[str, object]] | None = None,
    access_token_lifetime: timedelta = TOKEN_LIFETIME,
) -> OriginOAuthServer:
    @contextmanager
    def connections() -> Iterator[Connection]:
        with engine.begin() as connection:
            yield connection

    return OriginOAuthServer(
        connections=connections,
        issuer=ISSUER,
        resource=RESOURCE,
        supported_scopes=frozenset({"my-pa.read", "my-pa.write"}),
        now=clock,
        access_token_lifetime=access_token_lifetime,
        on_security_event=None if events is None else events.append,
    )


def register(service: OriginOAuthServer, *, grant_types: list[str] | None = None) -> str:
    payload: dict[str, object] = {
        "client_name": "Synthetic ChatLLM",
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
        "scope": "my-pa.read",
    }
    if grant_types is not None:
        payload["grant_types"] = grant_types
    return str(service.register_client(payload)["client_id"])


def enable_refresh(engine: Engine, client_id: str) -> None:
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        assert repository.set_client_refresh(oauth_client_id=client_id, refresh_enabled=True)
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


def authorization_values(client_id: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "scope": "my-pa.read",
        "state": "state",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
    }


def code_exchange(service: OriginOAuthServer, client_id: str, raw_code: str) -> dict[str, object]:
    return service.issue_token(
        {
            "grant_type": "authorization_code",
            "code": raw_code,
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER,
            "resource": RESOURCE,
        }
    )


def issue_refresh_enabled(
    engine: Engine,
    clock: Clock,
    *,
    events: list[dict[str, object]] | None = None,
    access_token_lifetime: timedelta = TOKEN_LIFETIME,
) -> tuple[OriginOAuthServer, str, dict[str, object]]:
    service = server(engine, clock, events=events, access_token_lifetime=access_token_lifetime)
    client_id = register(service)
    enable_refresh(engine, client_id)
    raw_code = service.issue_authorization_code(
        service.validate_authorization(authorization_values(client_id))
    )
    return service, client_id, code_exchange(service, client_id, raw_code)


def test_production_access_token_lifetime_remains_one_hour() -> None:
    assert timedelta(hours=1) == TOKEN_LIFETIME
    assert int(TOKEN_LIFETIME.total_seconds()) == 3600


def test_refresh_disabled_code_exchange_omits_refresh_token(engine: Engine) -> None:
    clock = Clock(WHEN)
    service = server(engine, clock)
    client_id = register(service)
    raw_code = service.issue_authorization_code(
        service.validate_authorization(authorization_values(client_id))
    )
    issued = code_exchange(service, client_id, raw_code)
    assert issued["expires_in"] == 3600
    assert "refresh_token" not in issued
    with engine.connect() as connection:
        assert connection.execute(select(oauth_refresh_tokens.c.token_hash)).first() is None
        family = connection.execute(select(oauth_access_tokens.c.refresh_family_id)).scalar_one()
        assert family is None


def test_refresh_enabled_code_exchange_returns_digest_only_refresh(engine: Engine) -> None:
    clock = Clock(WHEN)
    events: list[dict[str, object]] = []
    _service, client_id, issued = issue_refresh_enabled(engine, clock, events=events)
    refresh = str(issued["refresh_token"])
    access = str(issued["access_token"])
    assert issued["expires_in"] == 3600
    assert len(refresh) >= 43
    with engine.connect() as connection:
        stored = connection.execute(select(oauth_refresh_tokens.c.token_hash)).scalar_one()
        assert stored == hashlib.sha256(refresh.encode()).hexdigest()
        assert refresh not in stored
        assert access not in stored
        assert connection.execute(select(oauth_refresh_tokens.c.generation)).scalar_one() == 0
    for event in events:
        rendered = repr(event)
        assert refresh not in rendered
        assert access not in rendered
        assert client_id in str(event.get("client_id", client_id))
    assert any(event["event"] == "oauth.refresh_token.family_created" for event in events)


def test_dcr_accepts_optional_refresh_and_rejects_unsupported_grants(engine: Engine) -> None:
    service = server(engine, Clock(WHEN))
    accepted = service.register_client(
        {
            "client_name": "Optional refresh",
            "redirect_uris": [REDIRECT],
            "grant_types": ["refresh_token", "authorization_code"],
        }
    )
    assert accepted["grant_types"] == ["authorization_code", "refresh_token"]
    with engine.connect() as connection:
        enabled = connection.execute(
            select(remote_clients.c.refresh_enabled).where(
                remote_clients.c.oauth_client_id == accepted["client_id"]
            )
        ).scalar_one()
        assert enabled is False
    with pytest.raises(OAuthError, match="unsupported grant_types"):
        service.register_client(
            {
                "client_name": "Client credentials",
                "redirect_uris": [REDIRECT],
                "grant_types": ["client_credentials"],
            }
        )
    with pytest.raises(OAuthError, match="authorization_code is required"):
        service.register_client(
            {
                "client_name": "Refresh only",
                "redirect_uris": [REDIRECT],
                "grant_types": ["refresh_token"],
            }
        )


def test_metadata_advertises_refresh_without_offline_access(engine: Engine) -> None:
    metadata = server(engine, Clock(WHEN)).authorization_server_metadata()
    assert metadata["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert "offline_access" not in metadata["scopes_supported"]
    assert "offline_access" not in repr(metadata)


def test_two_renewals_rotate_without_interactive_authorization(engine: Engine) -> None:
    clock = Clock(WHEN)
    service, client_id, first = issue_refresh_enabled(
        engine, clock, access_token_lifetime=timedelta(minutes=5)
    )
    first_refresh = str(first["refresh_token"])
    clock.instant = WHEN + timedelta(minutes=6)
    assert service.introspect(str(first["access_token"])) is None
    second = service.issue_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": first_refresh,
            "client_id": client_id,
            "resource": RESOURCE,
        }
    )
    second_refresh = str(second["refresh_token"])
    assert second_refresh != first_refresh
    assert service.introspect(str(second["access_token"])) is not None
    clock.instant = WHEN + timedelta(minutes=12)
    assert service.introspect(str(second["access_token"])) is None
    third = service.issue_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": second_refresh,
            "client_id": client_id,
            "resource": RESOURCE,
        }
    )
    assert service.introspect(str(third["access_token"])) is not None
    assert str(third["refresh_token"]) != second_refresh
    with engine.connect() as connection:
        generations = {
            row.generation: row.consumed_at
            for row in connection.execute(
                select(oauth_refresh_tokens.c.generation, oauth_refresh_tokens.c.consumed_at)
            )
        }
        assert generations[0] is not None
        assert generations[1] is not None
        assert generations[2] is None


def test_consumed_refresh_replay_revokes_family_and_access(engine: Engine) -> None:
    clock = Clock(WHEN)
    events: list[dict[str, object]] = []
    service, client_id, first = issue_refresh_enabled(engine, clock, events=events)
    first_refresh = str(first["refresh_token"])
    rotated = service.issue_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": first_refresh,
            "client_id": client_id,
            "resource": RESOURCE,
        }
    )
    replacement_access = str(rotated["access_token"])
    with pytest.raises(OAuthError, match="refresh token is invalid") as raised:
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": first_refresh,
                "client_id": client_id,
                "resource": RESOURCE,
            }
        )
    assert raised.value.error == "invalid_grant"
    assert first_refresh not in str(raised.value)
    assert service.introspect(replacement_access) is None
    with engine.connect() as connection:
        family = connection.execute(select(oauth_refresh_token_families)).one()
        assert family.replay_detected_at is not None
        assert family.revoked_at is not None
        assert family.revoke_reason == "replay_detected"
    assert any(event["event"] == "oauth.refresh.replay_detected" for event in events)
    for event in events:
        assert first_refresh not in repr(event)
        assert redact_security_value(first_refresh) == "[REDACTED]"


def test_refresh_bindings_and_controls_fail_closed(engine: Engine) -> None:
    clock = Clock(WHEN)
    service, client_id, issued = issue_refresh_enabled(engine, clock)
    refresh = str(issued["refresh_token"])
    other = register(service)
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": other,
                "resource": RESOURCE,
            }
        )
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "resource": f"{ISSUER}/other",
            }
        )
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "resource": RESOURCE,
                "scope": "my-pa.write",
            }
        )
    with engine.begin() as connection:
        RemoteIdentityRepository(connection).set_client_refresh(
            oauth_client_id=client_id, refresh_enabled=False
        )
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "resource": RESOURCE,
            }
        )


def test_global_remote_disable_and_missing_grants_block_refresh(engine: Engine) -> None:
    clock = Clock(WHEN)
    service, client_id, issued = issue_refresh_enabled(engine, clock)
    refresh = str(issued["refresh_token"])
    with engine.begin() as connection:
        connection.execute(
            update(remote_security_controls)
            .where(remote_security_controls.c.singleton.is_(True))
            .values(remote_enabled=False, updated_at=WHEN)
        )
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "resource": RESOURCE,
            }
        )
    with engine.begin() as connection:
        connection.execute(
            update(remote_security_controls)
            .where(remote_security_controls.c.singleton.is_(True))
            .values(remote_enabled=True, updated_at=WHEN)
        )
        connection.execute(update(remote_capability_grants).values(revoked_at=WHEN))
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "resource": RESOURCE,
            }
        )


def test_write_kill_switch_does_not_block_refresh(engine: Engine) -> None:
    clock = Clock(WHEN)
    service, client_id, issued = issue_refresh_enabled(engine, clock)
    refresh = str(issued["refresh_token"])
    with engine.begin() as connection:
        RemoteIdentityRepository(connection).set_client_writes(
            oauth_client_id=client_id, writes_enabled=False
        )
        connection.execute(
            update(remote_security_controls)
            .where(remote_security_controls.c.singleton.is_(True))
            .values(writes_enabled=False, updated_at=WHEN)
        )
    rotated = service.issue_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "resource": RESOURCE,
        }
    )
    context = service.introspect(str(rotated["access_token"]))
    assert context is not None

    @contextmanager
    def connections() -> Iterator[Connection]:
        with engine.begin() as connection:
            yield connection

    authenticator = RemoteAuthenticator(
        token_context=service.introspect,
        connections=connections,
        required_resource=RESOURCE,
        now=clock,
    )
    auth = authenticator.authenticate(f"Bearer {rotated['access_token']}")
    assert auth.write_allowed is False
    assert Capability.CAPABILITIES_GET in auth.capabilities


def test_client_revocation_disables_refresh_and_access(engine: Engine) -> None:
    clock = Clock(WHEN)
    service, client_id, issued = issue_refresh_enabled(engine, clock)
    access = str(issued["access_token"])
    refresh = str(issued["refresh_token"])
    with engine.begin() as connection:
        assert RemoteIdentityRepository(connection).revoke_client(
            oauth_client_id=client_id, now=WHEN
        )
    assert service.introspect(access) is None
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "resource": RESOURCE,
            }
        )


def test_refresh_revoke_is_non_oracular(engine: Engine) -> None:
    clock = Clock(WHEN)
    service, client_id, issued = issue_refresh_enabled(engine, clock)
    refresh = str(issued["refresh_token"])
    access = str(issued["access_token"])
    service.revoke("not-a-real-token-value-and-unknown-----------")
    service.revoke(refresh)
    assert service.introspect(access) is None
    with pytest.raises(OAuthError):
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "resource": RESOURCE,
            }
        )


def test_refresh_disabled_client_cannot_use_refresh_grant(engine: Engine) -> None:
    clock = Clock(WHEN)
    service = server(engine, clock)
    client_id = register(service, grant_types=["authorization_code", "refresh_token"])
    with pytest.raises(OAuthError) as raised:
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": "b" * 43,
                "client_id": client_id,
                "resource": RESOURCE,
            }
        )
    assert raised.value.error == "invalid_grant"


def test_unsupported_grant_type_is_rejected(engine: Engine) -> None:
    service = server(engine, Clock(WHEN))
    with pytest.raises(OAuthError) as raised:
        service.issue_token({"grant_type": "client_credentials"})
    assert raised.value.error == "unsupported_grant_type"
    assert "offline_access" not in str(raised.value)
