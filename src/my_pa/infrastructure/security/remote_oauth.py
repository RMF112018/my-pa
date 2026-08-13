"""Origin-side OAuth authentication and durable remote-client authorization.

The edge may authenticate a request, but this module independently verifies the
bearer token and resolves all authority from server-side records.  In
particular, neither a tool payload nor a token scope can name a Principal or
create a capability grant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Connection

from my_pa.domain.identity.binding import capture_principal_id
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.identity.user_account import TokenClaimsError, validate_token_claims
from my_pa.infrastructure.persistence.remote_identity import RemoteIdentityRepository

__all__ = [
    "RemoteAuthContext",
    "RemoteAuthenticationError",
    "RemoteAuthenticator",
    "protected_resource_metadata",
    "redact_security_value",
]

_SAFE_FAILURE: Final = "the presented bearer credential is not authorized"
TokenClaims = Callable[[str], Mapping[str, Any]]
ConnectionProvider = Callable[[], AbstractContextManager[Connection]]


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
        token_claims: TokenClaims,
        connections: ConnectionProvider,
        tenant_id: str,
        required_resource: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not tenant_id.strip() or not required_resource.strip():
            raise ValueError("tenant_id and required_resource are required")
        self._token_claims = token_claims
        self._connections = connections
        self._tenant_id = tenant_id.strip()
        self._required_resource = required_resource.strip()
        self._now = now

    def authenticate(self, authorization_header: str | None) -> RemoteAuthContext:
        """Authenticate from the Authorization header and no request payload."""
        failed = False
        context: RemoteAuthContext | None = None
        try:
            token = self._bearer(authorization_header)
            claims = self._token_claims(token)
            identity = validate_token_claims(claims, home_tenant_id=self._tenant_id)
            client_id = self._required_claim(claims, "azp", fallback="appid")
            token_scopes = self._scopes(claims)
            # An explicit resource claim, when an AS emits one, must agree with
            # the audience already verified cryptographically by token_claims.
            resource = claims.get("resource")
            if resource is not None and resource != self._required_resource:
                raise ValueError
            with self._connections() as connection:
                resolved = RemoteIdentityRepository(connection).authenticate(
                    tenant_id=identity.tid,
                    object_id=identity.oid,
                    oauth_client_id=client_id,
                    token_scopes=token_scopes,
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
                client_id=client_id,
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

    @staticmethod
    def _required_claim(
        claims: Mapping[str, object], name: str, *, fallback: str | None = None
    ) -> str:
        value = claims.get(name)
        if value is None and fallback is not None:
            value = claims.get(fallback)
        if not isinstance(value, str) or not value.strip():
            raise ValueError
        return value.strip()

    @staticmethod
    def _scopes(claims: Mapping[str, object]) -> frozenset[str]:
        raw = claims.get("scp", claims.get("scope"))
        if not isinstance(raw, str):
            return frozenset()
        return frozenset(part for part in raw.split() if part)
