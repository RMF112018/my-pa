"""Durable single-operator OAuth 2.1 authorization server primitives.

Clients, authorization codes, and opaque access tokens live in PostgreSQL. Raw
codes and tokens are returned once and only SHA-256 digests are persisted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import Connection, func, select

from my_pa.contracts.oauth import AuthorizationRequest, OAuthError
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    oauth_access_tokens,
    oauth_authorization_codes,
    remote_clients,
)
from my_pa.infrastructure.security.remote_oauth import OriginTokenContext

__all__ = ["OriginOAuthServer"]

CODE_LIFETIME: Final = timedelta(minutes=5)
TOKEN_LIFETIME: Final = timedelta(hours=1)
_PKCE_VALUE: Final = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")
_CLIENT_NAME_LIMIT: Final = 128
_REDIRECT_LIMIT: Final = 8
_ACTIVE_CLIENT_LIMIT: Final = 32
ConnectionProvider = Callable[[], AbstractContextManager[Connection]]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class OriginOAuthServer:
    """Origin-owned DCR, PKCE code exchange, revocation, and introspection."""

    def __init__(
        self,
        *,
        connections: ConnectionProvider,
        issuer: str,
        resource: str,
        supported_scopes: frozenset[str],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.connections = connections
        self.issuer = self._https_origin(issuer)
        self.resource = resource.strip()
        self.supported_scopes = frozenset(scope.strip() for scope in supported_scopes if scope)
        self.now = now
        if not self.resource or not self.supported_scopes:
            raise ValueError("resource and supported scopes are required")

    @staticmethod
    def _https_origin(value: str) -> str:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("OAuth issuer must be an HTTPS origin")
        return value.strip().rstrip("/")

    @staticmethod
    def _redirect_uri(value: object) -> str:
        if not isinstance(value, str) or len(value) > 2048:
            raise OAuthError("invalid_redirect_uri", "an HTTPS redirect URI is required")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise OAuthError("invalid_redirect_uri", "an HTTPS redirect URI is required")
        return value

    def register_client(self, payload: Mapping[str, object]) -> dict[str, object]:
        redirects = payload.get("redirect_uris")
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= _REDIRECT_LIMIT:
            raise OAuthError("invalid_client_metadata", "redirect_uris must be a bounded list")
        redirect_uris = tuple(self._redirect_uri(value) for value in redirects)
        if len(set(redirect_uris)) != len(redirect_uris):
            raise OAuthError("invalid_client_metadata", "redirect_uris must be unique")
        if payload.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthError("invalid_client_metadata", "only public PKCE clients are supported")
        if payload.get("grant_types", ["authorization_code"]) != ["authorization_code"]:
            raise OAuthError("invalid_client_metadata", "only authorization_code is supported")
        if payload.get("response_types", ["code"]) != ["code"]:
            raise OAuthError("invalid_client_metadata", "only the code response type is supported")
        name = payload.get("client_name", "OAuth client")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > _CLIENT_NAME_LIMIT:
            raise OAuthError("invalid_client_metadata", "client_name is invalid")
        scopes = self._scopes(str(payload.get("scope", "my-pa.read")))
        client_id = secrets.token_urlsafe(24)
        registered = _aware(self.now())
        with self.connections() as connection:
            active_clients = connection.execute(
                select(func.count())
                .select_from(remote_clients)
                .where(
                    remote_clients.c.enabled.is_(True),
                    remote_clients.c.revoked_at.is_(None),
                )
            ).scalar_one()
            if active_clients >= _ACTIVE_CLIENT_LIMIT:
                raise OAuthError("invalid_client_metadata", "active client limit reached")
            RemoteIdentityRepository(connection).register_client(
                oauth_client_id=client_id,
                client_name=name.strip(),
                redirect_uris=json.dumps(redirect_uris, separators=(",", ":")),
                registered_scopes=" ".join(sorted(scopes)),
                now=registered,
                writes_enabled=False,
            )
        return {
            "client_id": client_id,
            "client_id_issued_at": int(registered.timestamp()),
            "client_name": name.strip(),
            "redirect_uris": list(redirect_uris),
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": " ".join(sorted(scopes)),
        }

    def validate_authorization(self, values: Mapping[str, str]) -> AuthorizationRequest:
        if values.get("response_type") != "code":
            raise OAuthError("unsupported_response_type", "response_type must be code")
        client_id = values.get("client_id", "")
        state = values.get("state", "")
        if len(client_id) > 256 or len(state) > 1024:
            raise OAuthError("invalid_request", "authorization request is too large")
        redirect_uri = self._redirect_uri(values.get("redirect_uri"))
        challenge = values.get("code_challenge", "")
        if (
            values.get("code_challenge_method") != "S256"
            or len(challenge) != 43
            or not _PKCE_VALUE.fullmatch(challenge)
        ):
            raise OAuthError("invalid_request", "PKCE S256 is required")
        if values.get("resource", self.resource) != self.resource:
            raise OAuthError("invalid_target", "resource is not served here")
        scopes = self._scopes(values.get("scope", "my-pa.read"))
        with self.connections() as connection:
            row = connection.execute(
                select(
                    remote_clients.c.client_name,
                    remote_clients.c.redirect_uris,
                    remote_clients.c.registered_scopes,
                ).where(
                    remote_clients.c.oauth_client_id == client_id,
                    remote_clients.c.enabled.is_(True),
                    remote_clients.c.revoked_at.is_(None),
                )
            ).one_or_none()
        if row is None or redirect_uri not in json.loads(row.redirect_uris):
            raise OAuthError("invalid_request", "client or redirect URI is not registered")
        if not scopes <= frozenset(row.registered_scopes.split()):
            raise OAuthError("invalid_scope", "requested scope was not registered")
        return AuthorizationRequest(
            client_id=client_id,
            client_name=row.client_name,
            redirect_uri=redirect_uri,
            scope=" ".join(sorted(scopes)),
            state=state,
            code_challenge=challenge,
            resource=self.resource,
        )

    def issue_authorization_code(self, request: AuthorizationRequest) -> str:
        raw = secrets.token_urlsafe(32)
        created = _aware(self.now())
        with self.connections() as connection:
            client_id = connection.execute(
                select(remote_clients.c.id).where(
                    remote_clients.c.oauth_client_id == request.client_id,
                    remote_clients.c.enabled.is_(True),
                    remote_clients.c.revoked_at.is_(None),
                )
            ).scalar_one_or_none()
            if client_id is None:
                raise OAuthError("invalid_request", "client is no longer active")
            connection.execute(
                oauth_authorization_codes.insert().values(
                    code_hash=_digest(raw),
                    remote_client_id=client_id,
                    redirect_uri=request.redirect_uri,
                    scope=request.scope,
                    resource=request.resource,
                    code_challenge=request.code_challenge,
                    expires_at=created + CODE_LIFETIME,
                    consumed_at=None,
                    created_at=created,
                )
            )
        return raw

    def exchange_code(self, values: Mapping[str, str]) -> dict[str, object]:
        if values.get("grant_type") != "authorization_code":
            raise OAuthError("unsupported_grant_type", "grant_type must be authorization_code")
        raw_code = values.get("code", "")
        verifier = values.get("code_verifier", "")
        if not raw_code or not _PKCE_VALUE.fullmatch(verifier):
            raise OAuthError("invalid_grant", "authorization code or verifier is invalid")
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        now = _aware(self.now())
        with self.connections() as connection:
            row = connection.execute(
                select(
                    oauth_authorization_codes.c.remote_client_id,
                    oauth_authorization_codes.c.redirect_uri,
                    oauth_authorization_codes.c.scope,
                    oauth_authorization_codes.c.resource,
                    oauth_authorization_codes.c.code_challenge,
                    oauth_authorization_codes.c.expires_at,
                    oauth_authorization_codes.c.consumed_at,
                    remote_clients.c.oauth_client_id,
                )
                .select_from(
                    oauth_authorization_codes.join(
                        remote_clients,
                        oauth_authorization_codes.c.remote_client_id == remote_clients.c.id,
                    )
                )
                .where(
                    oauth_authorization_codes.c.code_hash == _digest(raw_code),
                    remote_clients.c.enabled.is_(True),
                    remote_clients.c.revoked_at.is_(None),
                )
            ).one_or_none()
            if row is None:
                raise OAuthError("invalid_grant", "authorization code is invalid")
            invalid = (
                row.oauth_client_id != values.get("client_id")
                or row.redirect_uri != values.get("redirect_uri")
                or row.resource != values.get("resource", self.resource)
                or row.consumed_at is not None
                or _aware(row.expires_at) <= now
                or not secrets.compare_digest(row.code_challenge, challenge)
            )
            if invalid:
                raise OAuthError("invalid_grant", "authorization code is invalid")
            consumed = connection.execute(
                oauth_authorization_codes.update()
                .where(
                    oauth_authorization_codes.c.code_hash == _digest(raw_code),
                    oauth_authorization_codes.c.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            )
            if consumed.rowcount != 1:
                raise OAuthError("invalid_grant", "authorization code is invalid")
            raw_token = secrets.token_urlsafe(32)
            connection.execute(
                oauth_access_tokens.insert().values(
                    token_hash=_digest(raw_token),
                    remote_client_id=row.remote_client_id,
                    scope=row.scope,
                    resource=row.resource,
                    expires_at=now + TOKEN_LIFETIME,
                    revoked_at=None,
                    created_at=now,
                )
            )
        return {
            "access_token": raw_token,
            "token_type": "Bearer",
            "expires_in": int(TOKEN_LIFETIME.total_seconds()),
            "scope": row.scope,
        }

    def introspect(self, raw_token: str) -> OriginTokenContext | None:
        if not raw_token:
            return None
        with self.connections() as connection:
            row = connection.execute(
                select(
                    remote_clients.c.oauth_client_id,
                    oauth_access_tokens.c.scope,
                    oauth_access_tokens.c.resource,
                    oauth_access_tokens.c.expires_at,
                )
                .select_from(
                    oauth_access_tokens.join(
                        remote_clients,
                        oauth_access_tokens.c.remote_client_id == remote_clients.c.id,
                    )
                )
                .where(
                    oauth_access_tokens.c.token_hash == _digest(raw_token),
                    oauth_access_tokens.c.revoked_at.is_(None),
                    remote_clients.c.enabled.is_(True),
                    remote_clients.c.revoked_at.is_(None),
                )
            ).one_or_none()
        if row is None or _aware(row.expires_at) <= _aware(self.now()):
            return None
        return OriginTokenContext(
            client_id=row.oauth_client_id,
            scopes=frozenset(row.scope.split()),
            resource=row.resource,
        )

    def revoke(self, raw_token: str) -> None:
        if not raw_token:
            return
        with self.connections() as connection:
            connection.execute(
                oauth_access_tokens.update()
                .where(oauth_access_tokens.c.token_hash == _digest(raw_token))
                .values(revoked_at=_aware(self.now()))
            )

    def authorization_server_metadata(self) -> dict[str, object]:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/oauth/authorize",
            "token_endpoint": f"{self.issuer}/oauth/token",
            "registration_endpoint": f"{self.issuer}/oauth/register",
            "revocation_endpoint": f"{self.issuer}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": sorted(self.supported_scopes),
        }

    def _scopes(self, raw: str) -> frozenset[str]:
        scopes = frozenset(raw.split())
        if not scopes or not scopes <= self.supported_scopes:
            raise OAuthError("invalid_scope", "requested scope is not supported")
        return scopes
