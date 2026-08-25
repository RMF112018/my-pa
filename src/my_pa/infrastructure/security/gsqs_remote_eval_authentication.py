"""Header-only authentication for the GSQS ChatLLM remote-evaluation resource.

This is a dedicated evaluation audience, not production MCP.  Production tokens
bound to a different resource fail closed even when their scopes would otherwise
look valid.  The evaluation scope is a string constant; there is no Purpose or
Capability vocabulary change.

RemoteAuthenticator is constructed internally so bearer parsing and required
resource validation stay on the PR #151 primitive.  Its authenticate() path is
not used: that path intersects token scopes with production capability grants
and collapses every refusal into one indistinguishable error.  Evaluation needs
a distinct FORBIDDEN_SCOPE when a token is valid for this resource but lacks
``my-pa.gsqs.evaluate``, without a capability-enum migration.  Principal
resolution is therefore an injected callable so tests (and the evaluation
surface) do not need Postgres or a grant table.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Connection

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.infrastructure.security.remote_oauth import (
    OriginTokenContext,
    RemoteAuthenticator,
    protected_resource_metadata,
    redact_security_value,
)

__all__ = [
    "GSQS_REMOTE_EVAL_PURPOSE",
    "GSQS_REMOTE_EVAL_RESOURCE_DEFAULT",
    "GSQS_REMOTE_EVAL_SCOPE",
    "GsqsRemoteEvalAuthenticationError",
    "GsqsRemoteEvalAuthenticator",
    "GsqsRemoteEvalPrincipal",
    "assert_session_principal_binding",
    "build_evaluation_origin_oauth_settings",
    "evaluation_protected_resource_metadata",
]

GSQS_REMOTE_EVAL_RESOURCE_DEFAULT: Final = "https://my-pa-gsqs.bobby-fetting.me/mcp"
GSQS_REMOTE_EVAL_SCOPE: Final = "my-pa.gsqs.evaluate"
GSQS_REMOTE_EVAL_PURPOSE: Final = "goodnotes.gsqs.b0.measurement"

# Same codes as application.goodnotes_gsqs_remote_eval_contracts.  Duplicated as
# literals so infrastructure does not import application.
_CODE_UNAUTHENTICATED: Final = "UNAUTHENTICATED"
_CODE_FORBIDDEN_SCOPE: Final = "FORBIDDEN_SCOPE"
_SAFE_UNAUTHENTICATED: Final = "the presented bearer credential is not authorized"
_SAFE_FORBIDDEN: Final = "the presented bearer credential lacks the required scope"

ConnectionProvider = Callable[[], AbstractContextManager[Connection]]
TokenContext = Callable[[str], OriginTokenContext | None]
PrincipalResolver = Callable[[str], str | None]


def _local_operator_principal(_client_id: str) -> str:
    return capture_principal_id(LOCAL_OPERATOR_UUID)


@dataclass(frozen=True, slots=True)
class GsqsRemoteEvalPrincipal:
    """Server-resolved evaluation identity.  Never taken from a tool body."""

    principal_id: str
    client_id: str
    scopes: frozenset[str]
    resource: str


class GsqsRemoteEvalAuthenticationError(Exception):
    """Fail-closed evaluation authentication refusal with a stable ``code``."""

    def __init__(self, code: str, message: str = "") -> None:
        if code not in {_CODE_UNAUTHENTICATED, _CODE_FORBIDDEN_SCOPE}:
            raise ValueError("evaluation authentication code is not recognized")
        self.code = code
        if not message:
            message = _SAFE_UNAUTHENTICATED if code == _CODE_UNAUTHENTICATED else _SAFE_FORBIDDEN
        super().__init__(message)


class GsqsRemoteEvalAuthenticator:
    """Bearer-header evaluation authenticator.  Fail closed.  Header only."""

    def __init__(
        self,
        *,
        token_context: TokenContext,
        connections: ConnectionProvider,
        required_resource: str = GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
        required_scope: str = GSQS_REMOTE_EVAL_SCOPE,
        principal_resolver: PrincipalResolver | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not required_scope.strip():
            raise ValueError("required_scope is required")
        # Constructed so resource validation and bearer parsing stay on the
        # production primitive.  authenticate() on this instance is never
        # called: it would require production capability grants.
        self._remote = RemoteAuthenticator(
            token_context=token_context,
            connections=connections,
            required_resource=required_resource,
            now=now,
        )
        self._required_scope = required_scope.strip()
        self._principal_resolver = (
            _local_operator_principal if principal_resolver is None else principal_resolver
        )

    def authenticate(self, authorization_header: str | None) -> GsqsRemoteEvalPrincipal:
        """Authenticate from the Authorization header and no request payload."""
        try:
            token = RemoteAuthenticator._bearer(authorization_header)
        except Exception:
            raise GsqsRemoteEvalAuthenticationError(_CODE_UNAUTHENTICATED) from None
        try:
            token_context = self._remote._token_context(token)
        except Exception:
            raise GsqsRemoteEvalAuthenticationError(_CODE_UNAUTHENTICATED) from None
        if token_context is None or token_context.resource != self._remote._required_resource:
            # Invalid, expired, revoked, and wrong-audience tokens share one
            # safe surface.  A production-shaped context for another resource
            # is rejected here because required_resource differs.
            raise GsqsRemoteEvalAuthenticationError(_CODE_UNAUTHENTICATED) from None
        if self._required_scope not in token_context.scopes:
            raise GsqsRemoteEvalAuthenticationError(_CODE_FORBIDDEN_SCOPE) from None
        try:
            principal_id = self._principal_resolver(token_context.client_id)
        except Exception:
            raise GsqsRemoteEvalAuthenticationError(_CODE_UNAUTHENTICATED) from None
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise GsqsRemoteEvalAuthenticationError(_CODE_UNAUTHENTICATED) from None
        redact_security_value(token)
        return GsqsRemoteEvalPrincipal(
            principal_id=principal_id.strip(),
            client_id=token_context.client_id,
            scopes=token_context.scopes,
            resource=token_context.resource,
        )


def assert_session_principal_binding(
    *, authenticated_principal_id: str, session_principal_id: str
) -> None:
    """Require the authenticated principal to be the session principal."""
    if not authenticated_principal_id.strip():
        raise GsqsRemoteEvalAuthenticationError(_CODE_UNAUTHENTICATED) from None
    if not session_principal_id.strip():
        raise GsqsRemoteEvalAuthenticationError(_CODE_UNAUTHENTICATED) from None
    if authenticated_principal_id.strip() != session_principal_id.strip():
        raise GsqsRemoteEvalAuthenticationError(_CODE_FORBIDDEN_SCOPE) from None


def evaluation_protected_resource_metadata(
    *, resource: str, authorization_servers: tuple[str, ...]
) -> dict[str, object]:
    """RFC 9728 metadata for the evaluation resource only."""
    return protected_resource_metadata(
        resource=resource,
        authorization_servers=authorization_servers,
        scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE}),
    )


def build_evaluation_origin_oauth_settings(
    *,
    connections: ConnectionProvider,
    issuer: str,
    resource: str = GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Constructor kwargs for a dedicated OriginOAuthServer.  No live clients."""
    settings: dict[str, object] = {
        "connections": connections,
        "issuer": issuer,
        "resource": resource.strip(),
        "supported_scopes": frozenset({GSQS_REMOTE_EVAL_SCOPE}),
    }
    if now is not None:
        settings["now"] = now
    return settings
