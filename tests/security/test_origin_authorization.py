from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from my_pa.contracts.oauth import AuthorizationRequest, OAuthError
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    oauth_access_tokens,
    oauth_authorization_codes,
    remote_clients,
)
from my_pa.infrastructure.security.origin_authorization import (
    OriginOAuthServer,
)

WHEN = datetime(2026, 8, 14, 12, tzinfo=UTC)
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
    yield built
    built.dispose()


def server(engine: Engine, *, now: datetime = WHEN) -> OriginOAuthServer:
    @contextmanager
    def connections() -> Iterator[Connection]:
        with engine.begin() as connection:
            yield connection

    return OriginOAuthServer(
        connections=connections,
        issuer=ISSUER,
        resource=RESOURCE,
        supported_scopes=frozenset({"my-pa.read"}),
        now=lambda: now,
    )


def register(service: OriginOAuthServer) -> str:
    result = service.register_client(
        {
            "client_name": "Synthetic ChatLLM",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
        }
    )
    return str(result["client_id"])


def request(service: OriginOAuthServer, client_id: str) -> AuthorizationRequest:
    return service.validate_authorization(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "scope": "my-pa.read",
            "state": "opaque-client-state",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        }
    )


def test_dcr_binds_every_client_to_the_local_operator_without_a_secret(engine: Engine) -> None:
    service = server(engine)
    client_id = register(service)
    with engine.connect() as connection:
        row = connection.execute(select(remote_clients)).one()
    assert row.oauth_client_id == client_id
    assert row.principal_id == LOCAL_OPERATOR_UUID
    assert row.writes_enabled is False
    assert row.registered_scopes == "my-pa.read"


def test_dcr_active_client_limit_is_atomic_under_concurrency() -> None:
    built = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with built.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
    service = server(built)
    for _client in range(31):
        register(service)

    def attempt() -> bool:
        try:
            register(service)
        except OAuthError as exc:
            assert exc.error == "invalid_client_metadata"
            assert str(exc) == "active client limit reached"
            return False
        return True

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = tuple(pool.map(lambda _item: attempt(), range(4)))
        assert outcomes.count(True) == 1
        with built.connect() as connection:
            assert len(connection.execute(select(remote_clients)).all()) == 32
    finally:
        built.dispose()


def test_pkce_code_is_single_use_and_only_hashes_are_persisted(engine: Engine) -> None:
    service = server(engine)
    client_id = register(service)
    raw_code = service.issue_authorization_code(request(service, client_id))
    issued = service.exchange_code(
        {
            "grant_type": "authorization_code",
            "code": raw_code,
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER,
            "resource": RESOURCE,
        }
    )
    raw_token = str(issued["access_token"])
    context = service.introspect(raw_token)
    assert context is not None
    assert context.client_id == client_id
    assert context.scopes == frozenset({"my-pa.read"})
    with engine.connect() as connection:
        code_hash = connection.execute(select(oauth_authorization_codes.c.code_hash)).scalar_one()
        token_hash = connection.execute(select(oauth_access_tokens.c.token_hash)).scalar_one()
    assert raw_code not in (code_hash, token_hash)
    assert raw_token not in (code_hash, token_hash)
    with pytest.raises(OAuthError, match="authorization code is invalid"):
        service.exchange_code(
            {
                "grant_type": "authorization_code",
                "code": raw_code,
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "code_verifier": VERIFIER,
                "resource": RESOURCE,
            }
        )


def test_redirect_pkce_scope_expiry_and_revocation_fail_closed(engine: Engine) -> None:
    service = server(engine)
    client_id = register(service)
    with pytest.raises(OAuthError):
        service.validate_authorization(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://attacker.example/callback",
                "scope": "my-pa.write",
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
            }
        )
    raw_code = service.issue_authorization_code(request(service, client_id))
    issued = service.exchange_code(
        {
            "grant_type": "authorization_code",
            "code": raw_code,
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER,
        }
    )
    token = str(issued["access_token"])
    service.revoke(token)
    assert service.introspect(token) is None
    expired = server(engine, now=WHEN + timedelta(hours=2))
    assert expired.introspect(token) is None


def test_discovery_advertises_only_origin_pkce_contract(engine: Engine) -> None:
    metadata = server(engine).authorization_server_metadata()
    assert metadata["issuer"] == ISSUER
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert "jwks_uri" not in metadata
