from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pytest import MonkeyPatch
from sqlalchemy import create_engine

from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_capability_grants,
    remote_clients,
    remote_security_controls,
)
from my_pa.infrastructure.persistence.user_accounts import user_accounts
from my_pa.infrastructure.security.remote_oauth import (
    RemoteAuthenticationError,
    RemoteAuthenticator,
    protected_resource_metadata,
    redact_security_value,
)

WHEN = datetime(2026, 8, 13, tzinfo=UTC)


class RepositoryAnswer:
    principal_id = UUID("12345678-1234-5678-1234-567812345678")
    scopes = frozenset({"my-pa.read"})
    capabilities = frozenset({Capability.KNOWLEDGE_SEARCH})
    capability_purposes = frozenset({(Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH)})
    write_allowed = False


class FakeConnection:
    pass


@contextmanager
def connections() -> Iterator[FakeConnection]:
    yield FakeConnection()


def claims(_: str) -> dict[str, object]:
    return {
        "tid": "tenant",
        "oid": "person",
        "azp": "client",
        "scp": "my-pa.read ungranted.scope",
        "resource": "https://mcp.example.invalid",
    }


def test_header_only_authentication_returns_server_resolved_context(
    monkeypatch: MonkeyPatch,
) -> None:
    def authenticate(_self: object, **kwargs: object) -> RepositoryAnswer:
        assert kwargs["oauth_client_id"] == "client"
        assert kwargs["token_scopes"] == frozenset({"my-pa.read", "ungranted.scope"})
        return RepositoryAnswer()

    monkeypatch.setattr(
        "my_pa.infrastructure.security.remote_oauth.RemoteIdentityRepository.authenticate",
        authenticate,
    )
    auth = RemoteAuthenticator(
        token_claims=claims,
        connections=connections,
        tenant_id="tenant",
        required_resource="https://mcp.example.invalid",
        now=lambda: WHEN,
    )
    context = auth.authenticate("Bearer synthetic-token")
    assert context.principal.authenticated
    assert context.principal_id == "prn_12345678123456781234567812345678"
    assert context.client_id == "client"
    assert context.scopes == frozenset({"my-pa.read"})
    assert context.capabilities == frozenset({Capability.KNOWLEDGE_SEARCH})
    assert context.write_allowed is False
    assert context.allows(Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH)
    assert not context.allows(Capability.KNOWLEDGE_SEARCH, Purpose.CAPTURE_AUTHORING)


@pytest.mark.parametrize("header", [None, "", "Basic value", "Bearer", "Bearer a b"])
def test_malformed_headers_have_one_safe_failure(header: str | None) -> None:
    auth = RemoteAuthenticator(
        token_claims=claims,
        connections=connections,
        tenant_id="tenant",
        required_resource="https://mcp.example.invalid",
        now=lambda: WHEN,
    )
    with pytest.raises(RemoteAuthenticationError) as error:
        auth.authenticate(header)
    assert str(error.value) == "the presented bearer credential is not authorized"
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "changed",
    [
        {"tid": "foreign"},
        {"oid": ""},
        {"azp": ""},
        {"resource": "https://other.invalid"},
    ],
)
def test_tenant_identity_client_and_resource_fail_closed(changed: dict[str, str]) -> None:
    def invalid(_: str) -> dict[str, object]:
        return {**claims("token"), **changed}

    auth = RemoteAuthenticator(
        token_claims=invalid,
        connections=connections,
        tenant_id="tenant",
        required_resource="https://mcp.example.invalid",
        now=lambda: WHEN,
    )
    with pytest.raises(RemoteAuthenticationError):
        auth.authenticate("Bearer token")


def test_metadata_and_redaction_are_deterministic() -> None:
    assert protected_resource_metadata(
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"write", "read"}),
    ) == {
        "resource": "https://mcp.example.invalid",
        "authorization_servers": ["https://issuer.example.invalid"],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["read", "write"],
    }
    assert redact_security_value("secret") == "[REDACTED]"


def test_repository_enforces_binding_grants_and_kill_switches() -> None:
    """A real SQL query intersects scope and denies cross-Principal bindings."""
    engine = create_engine("sqlite://")
    principal_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    principal_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    client = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
        for principal, oid in ((principal_a, "person-a"), (principal_b, "person-b")):
            connection.execute(
                user_accounts.insert().values(
                    id=principal,
                    principal_id=principal,
                    tid="tenant",
                    oid=oid,
                    first_seen_at=WHEN,
                    consent_state="granted",
                    lifecycle_state="active",
                    home_tenant_verified=True,
                )
            )
        connection.execute(
            remote_clients.insert().values(
                id=client,
                principal_id=principal_a,
                oauth_client_id="client-a",
                enabled=True,
                writes_enabled=True,
                created_at=WHEN,
            )
        )
        connection.execute(
            remote_security_controls.insert().values(
                singleton=True,
                remote_enabled=True,
                writes_enabled=False,
                updated_at=WHEN,
            )
        )
        connection.execute(
            remote_capability_grants.insert(),
            [
                {
                    "id": UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
                    "remote_client_id": client,
                    "external_scope": "my-pa.read",
                    "capability": Capability.KNOWLEDGE_SEARCH.value,
                    "capability_version": "v1",
                    "purpose": Purpose.KNOWLEDGE_SEARCH.value,
                    "resource": "https://mcp.example.invalid",
                    "is_write": False,
                    "created_at": WHEN,
                },
                {
                    "id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
                    "remote_client_id": client,
                    "external_scope": "my-pa.write",
                    "capability": Capability.CAPTURE_CREATE.value,
                    "capability_version": "v1",
                    "purpose": Purpose.CAPTURE_AUTHORING.value,
                    "resource": "https://mcp.example.invalid",
                    "is_write": True,
                    "created_at": WHEN,
                },
            ],
        )
        repository = RemoteIdentityRepository(connection)
        resolved = repository.authenticate(
            tenant_id="tenant",
            object_id="person-a",
            oauth_client_id="client-a",
            token_scopes=frozenset({"my-pa.read", "my-pa.write", "token-only"}),
            resource="https://mcp.example.invalid",
            now=WHEN,
        )
        assert resolved is not None
        assert resolved.principal_id == principal_a
        assert resolved.scopes == frozenset({"my-pa.read"})
        assert resolved.capabilities == frozenset({Capability.KNOWLEDGE_SEARCH})
        assert not resolved.write_allowed

        # The client is bound to A: B's otherwise valid identity cannot use it.
        assert (
            repository.authenticate(
                tenant_id="tenant",
                object_id="person-b",
                oauth_client_id="client-a",
                token_scopes=frozenset({"my-pa.read"}),
                resource="https://mcp.example.invalid",
                now=WHEN,
            )
            is None
        )

        connection.execute(
            remote_security_controls.update().values(remote_enabled=False, updated_at=WHEN)
        )
        assert (
            repository.authenticate(
                tenant_id="tenant",
                object_id="person-a",
                oauth_client_id="client-a",
                token_scopes=frozenset({"my-pa.read"}),
                resource="https://mcp.example.invalid",
                now=WHEN,
            )
            is None
        )
        connection.execute(
            remote_security_controls.update().values(remote_enabled=True, updated_at=WHEN)
        )

        connection.execute(remote_clients.update().values(revoked_at=WHEN, enabled=False))
        assert (
            repository.authenticate(
                tenant_id="tenant",
                object_id="person-a",
                oauth_client_id="client-a",
                token_scopes=frozenset({"my-pa.read"}),
                resource="https://mcp.example.invalid",
                now=WHEN,
            )
            is None
        )
    engine.dispose()
