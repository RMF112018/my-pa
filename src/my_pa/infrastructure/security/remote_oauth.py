"""Origin-side OAuth authentication and durable remote-client authorization.

The edge may authenticate a request, but this module independently verifies the
bearer token and resolves all authority from server-side records.  In
particular, neither a tool payload nor a token scope can name a Principal or
create a capability grant.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Connection, select

from my_pa.contracts.ports import RemoteClientStanding, RemoteClientStandingReader
from my_pa.domain.identity.binding import capture_principal_id
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.identity.user_account import TokenClaimsError
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.transfer import client_ref_of
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_clients,
)

__all__ = [
    "DurableRemoteClientStanding",
    "OriginTokenContext",
    "RemoteAuthContext",
    "RemoteAuthenticationError",
    "RemoteAuthenticator",
    "protected_resource_metadata",
    "redact_security_value",
]

_SAFE_FAILURE: Final = "the presented bearer credential is not authorized"
ConnectionProvider = Callable[[], AbstractContextManager[Connection]]


@dataclass(frozen=True, slots=True)
class OriginTokenContext:
    """Validated opaque-token authority returned by the origin OAuth store."""

    client_id: str
    scopes: frozenset[str]
    resource: str


TokenContext = Callable[[str], OriginTokenContext | None]


class RemoteAuthenticationError(TokenClaimsError):
    """One deliberately indistinguishable remote-authentication refusal."""

    def __init__(self) -> None:
        super().__init__(_SAFE_FAILURE)


@dataclass(frozen=True, slots=True)
class RemoteAuthContext:
    """The complete, server-resolved authority of one remote request."""

    principal: Principal
    client_id: str
    scopes: frozenset[str]
    capabilities: frozenset[Capability]
    write_allowed: bool
    capability_purposes: frozenset[tuple[Capability, Purpose | None]] = frozenset()

    @property
    def principal_id(self) -> str:
        return self.principal.principal_id

    def allows(self, capability: Capability, purpose: Purpose) -> bool:
        """Whether the external grant admits this capability and purpose.

        This is only the external authorization half; the application must
        still perform its canonical Principal/purpose/scope authorization.
        """
        return capability in self.capabilities and (
            (capability, None) in self.capability_purposes
            or (capability, purpose) in self.capability_purposes
        )


def redact_security_value(value: object) -> str:
    """Fail-closed rendering for security-bearing values.

    Logging code should pass the result, never the source value.  The function
    intentionally does not attempt partial masking: prefixes, JWT headers and
    client identifiers are all useful correlation material to an attacker.
    """
    del value
    return "[REDACTED]"


def protected_resource_metadata(
    *, resource: str, authorization_servers: tuple[str, ...], scopes: frozenset[str]
) -> dict[str, object]:
    """RFC 9728 protected-resource metadata with deterministic scope ordering."""
    if not resource.strip() or not authorization_servers:
        raise ValueError("resource and at least one authorization server are required")
    return {
        "resource": resource.strip(),
        "authorization_servers": list(authorization_servers),
        "bearer_methods_supported": ["header"],
        "scopes_supported": sorted(scopes),
    }


class RemoteAuthenticator:
    """Verify a bearer header, then resolve its Principal and grants durably."""

    def __init__(
        self,
        *,
        token_context: TokenContext,
        connections: ConnectionProvider,
        required_resource: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not required_resource.strip():
            raise ValueError("required_resource is required")
        self._token_context = token_context
        self._connections = connections
        self._required_resource = required_resource.strip()
        self._now = now

    def authenticate(self, authorization_header: str | None) -> RemoteAuthContext:
        """Authenticate from the Authorization header and no request payload."""
        failed = False
        context: RemoteAuthContext | None = None
        try:
            token = self._bearer(authorization_header)
            token_context = self._token_context(token)
            if token_context is None or token_context.resource != self._required_resource:
                raise ValueError
            with self._connections() as connection:
                resolved = RemoteIdentityRepository(connection).authenticate(
                    oauth_client_id=token_context.client_id,
                    token_scopes=token_context.scopes,
                    resource=self._required_resource,
                    now=self._now(),
                )
            if resolved is None:
                raise ValueError
            principal_id = capture_principal_id(resolved.principal_id)
            context = RemoteAuthContext(
                principal=Principal(
                    principal_id=principal_id,
                    kind=PrincipalKind.OPERATOR,
                    authenticated=True,
                ),
                client_id=token_context.client_id,
                scopes=resolved.scopes,
                capabilities=resolved.capabilities,
                write_allowed=resolved.write_allowed,
                capability_purposes=resolved.capability_purposes,
            )
        except Exception:  # Every token/store/claim refusal has one safe surface.
            failed = True
        if failed or context is None:
            raise RemoteAuthenticationError
        return context

    @staticmethod
    def _bearer(header: str | None) -> str:
        if not isinstance(header, str):
            raise ValueError
        scheme, separator, token = header.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or " " in token:
            raise ValueError
        return token


class DurableRemoteClientStanding(RemoteClientStandingReader):
    """The files byte routes' per-request client re-check (files-workspace contract §10).

    The same rows and rules as `RemoteAuthenticator`, by the same
    `RemoteIdentityRepository.authenticate`: client enabled, not revoked, not
    expired and bound to the operator; remote access on; grants unrevoked,
    unexpired, `v1`, for this resource; write grants dropped unless the client
    and the global write switches are both on. A byte route carries a ticket,
    not an OAuth token, so the scope ceiling is the configured scope set rather
    than one token's scopes -- a token's scopes only narrow grants, never add
    one, so this is no wider than any token the client could hold.

    The ticket names its client only by the derived reference
    (`remote_client:<pseudonym>`), so the client is found by deriving each
    registered client's reference and comparing in constant time; the
    registry is a handful of operator-registered rows. Every failure (no
    match, a store error) is the one `None`.
    """

    def __init__(
        self,
        *,
        connections: ConnectionProvider,
        resource: str,
        scopes: frozenset[str],
    ) -> None:
        if not resource.strip():
            raise ValueError("resource is required")
        self._connections = connections
        self._resource = resource.strip()
        self._scopes = frozenset(scopes)

    def standing(self, client_ref: str, *, now: datetime) -> RemoteClientStanding | None:
        if type(client_ref) is not str or not self._scopes:
            return None
        if not client_ref.startswith(f"{CreatorKind.REMOTE_CLIENT.value}:"):
            return None
        resolved = None
        oauth_client_id: str | None = None
        try:
            with self._connections() as connection:
                for candidate in connection.execute(
                    select(remote_clients.c.oauth_client_id)
                ).scalars():
                    derived = client_ref_of(derive_creator(CreatorKind.REMOTE_CLIENT, candidate))
                    if hmac.compare_digest(derived.encode("utf-8"), client_ref.encode("utf-8")):
                        oauth_client_id = candidate
                        break
                if oauth_client_id is not None:
                    resolved = RemoteIdentityRepository(connection).authenticate(
                        oauth_client_id=oauth_client_id,
                        token_scopes=self._scopes,
                        resource=self._resource,
                        now=now,
                    )
        except Exception:  # One safe surface: a store failure is a refusal.
            resolved = None
        if resolved is None or oauth_client_id is None:
            return None
        return RemoteClientStanding(
            oauth_client_id=oauth_client_id,
            principal_id=capture_principal_id(resolved.principal_id),
            capability_purposes=resolved.capability_purposes,
            write_allowed=resolved.write_allowed,
        )
