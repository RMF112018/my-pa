"""Origin-side OAuth authentication and durable remote-client authorization.

The edge may authenticate a request, but this module independently verifies the
bearer token and resolves all authority from server-side records.  In
particular, neither a tool payload nor a token scope can name a Principal or
create a capability grant.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Connection

from my_pa.domain.identity.binding import capture_principal_id
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.identity.user_account import TokenClaimsError
from my_pa.infrastructure.persistence.remote_identity import RemoteIdentityRepository

__all__ = [
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
