"""Durable single-operator OAuth 2.1 authorization server primitives.

Clients, authorization codes, opaque access tokens, and rotating refresh tokens
live in PostgreSQL. Raw codes and tokens are returned once and only SHA-256
digests are persisted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, select

from my_pa.contracts.oauth import AuthorizationRequest, OAuthError
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    oauth_access_tokens,
    oauth_authorization_codes,
    oauth_refresh_token_families,
    oauth_refresh_tokens,
    remote_clients,
)
from my_pa.infrastructure.security.remote_oauth import OriginTokenContext

__all__ = ["TOKEN_LIFETIME", "OriginOAuthServer"]

CODE_LIFETIME: Final = timedelta(minutes=5)
TOKEN_LIFETIME: Final = timedelta(hours=1)
REFRESH_IDLE_LIFETIME: Final = timedelta(days=30)
REFRESH_ABSOLUTE_LIFETIME: Final = timedelta(days=90)
_PKCE_VALUE: Final = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")
_TOKEN_VALUE: Final = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_CLIENT_NAME_LIMIT: Final = 128
_REDIRECT_LIMIT: Final = 8
_ACTIVE_CLIENT_LIMIT: Final = 32
_DCR_GRANTS: Final = frozenset({"authorization_code", "refresh_token"})
ConnectionProvider = Callable[[], AbstractContextManager[Connection]]
SecurityEvent = Callable[[Mapping[str, object]], None]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class OriginOAuthServer:
    """Origin-owned DCR, PKCE code exchange, refresh, revocation, and introspection."""

    def __init__(
        self,
        *,
        connections: ConnectionProvider,
        issuer: str,
        resource: str,
        supported_scopes: frozenset[str],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        access_token_lifetime: timedelta = TOKEN_LIFETIME,
        refresh_idle_lifetime: timedelta = REFRESH_IDLE_LIFETIME,
        refresh_absolute_lifetime: timedelta = REFRESH_ABSOLUTE_LIFETIME,
        on_security_event: SecurityEvent | None = None,
    ) -> None:
        self.connections = connections
        self.issuer = self._https_origin(issuer)
        self.resource = resource.strip()
        self.supported_scopes = frozenset(scope.strip() for scope in supported_scopes if scope)
        self.now = now
        self.access_token_lifetime = access_token_lifetime
        self.refresh_idle_lifetime = refresh_idle_lifetime
        self.refresh_absolute_lifetime = refresh_absolute_lifetime
        self.on_security_event = on_security_event
        self._registration_lock = threading.Lock()
        if not self.resource or not self.supported_scopes:
            raise ValueError("resource and supported scopes are required")
        if access_token_lifetime <= timedelta(0):
            raise ValueError("access token lifetime must be positive")

    def _emit(self, event: str, **fields: object) -> None:
        if self.on_security_event is None:
            return
        self.on_security_event({"event": event, **fields})

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

    def _registered_grants(self, payload: Mapping[str, object]) -> list[str]:
        raw = payload.get("grant_types", ["authorization_code"])
        if not isinstance(raw, list) or not raw:
            raise OAuthError("invalid_client_metadata", "grant_types is invalid")
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str) or item in seen or item not in _DCR_GRANTS:
                raise OAuthError("invalid_client_metadata", "unsupported grant_types")
            seen.add(item)
        if "authorization_code" not in seen:
            raise OAuthError("invalid_client_metadata", "authorization_code is required")
        grants = ["authorization_code"]
        if "refresh_token" in seen:
            grants.append("refresh_token")
        return grants

    def register_client(self, payload: Mapping[str, object]) -> dict[str, object]:
        redirects = payload.get("redirect_uris")
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= _REDIRECT_LIMIT:
            raise OAuthError("invalid_client_metadata", "redirect_uris must be a bounded list")
        redirect_uris = tuple(self._redirect_uri(value) for value in redirects)
        if len(set(redirect_uris)) != len(redirect_uris):
            raise OAuthError("invalid_client_metadata", "redirect_uris must be unique")
        if payload.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthError("invalid_client_metadata", "only public PKCE clients are supported")
        grants = self._registered_grants(payload)
        if payload.get("response_types", ["code"]) != ["code"]:
            raise OAuthError("invalid_client_metadata", "only the code response type is supported")
        name = payload.get("client_name", "OAuth client")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > _CLIENT_NAME_LIMIT:
            raise OAuthError("invalid_client_metadata", "client_name is invalid")
        scopes = self._scopes(str(payload.get("scope", "my-pa.read")))
        client_id = secrets.token_urlsafe(24)
        registered = _aware(self.now())
        with self._registration_lock, self.connections() as connection:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(7420196)")
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
                refresh_enabled=False,
            )
        return {
            "client_id": client_id,
            "client_id_issued_at": int(registered.timestamp()),
            "client_name": name.strip(),
            "redirect_uris": list(redirect_uris),
            "grant_types": grants,
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

    def issue_token(self, values: Mapping[str, str]) -> dict[str, object]:
        grant = values.get("grant_type")
        if grant == "authorization_code":
            return self.exchange_code(values)
        if grant == "refresh_token":
            return self.refresh_access(values)
        raise OAuthError("unsupported_grant_type", "grant_type is not supported")

    def exchange_code(self, values: Mapping[str, str]) -> dict[str, object]:
        if values.get("grant_type") != "authorization_code":
            raise OAuthError("unsupported_grant_type", "grant_type is not supported")
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
                    remote_clients.c.refresh_enabled,
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
            family_id = None
            raw_refresh = None
            if row.refresh_enabled:
                family_id, raw_refresh = self._mint_refresh_family(
                    connection,
                    remote_client_id=row.remote_client_id,
                    scope=row.scope,
                    resource=row.resource,
                    now=now,
                )
                self._emit(
                    "oauth.refresh_token.family_created",
                    client_id=row.oauth_client_id,
                    family_id=str(family_id),
                    generation=0,
                    resource=row.resource,
                    scope=row.scope,
                )
            raw_token = self._mint_access_token(
                connection,
                remote_client_id=row.remote_client_id,
                scope=row.scope,
                resource=row.resource,
                now=now,
                family_id=family_id,
            )
        issued: dict[str, object] = {
            "access_token": raw_token,
            "token_type": "Bearer",
            "expires_in": int(self.access_token_lifetime.total_seconds()),
            "scope": row.scope,
        }
        if raw_refresh is not None:
            issued["refresh_token"] = raw_refresh
        self._emit(
            "oauth.access_token.issued",
            client_id=row.oauth_client_id,
            resource=row.resource,
            scope=row.scope,
            refresh_issued=raw_refresh is not None,
        )
        return issued

    def refresh_access(self, values: Mapping[str, str]) -> dict[str, object]:
        raw = values.get("refresh_token", "")
        if not _TOKEN_VALUE.fullmatch(raw):
            raise OAuthError("invalid_grant", "refresh token is invalid")
        now = _aware(self.now())
        digest = _digest(raw)
        requested_scope = values.get("scope")
        replay: dict[str, object] | None = None
        denial: dict[str, object] | None = None
        issued: dict[str, object] | None = None
        succeeded: dict[str, object] | None = None
        with self.connections() as connection:
            repository = RemoteIdentityRepository(connection)
            query = (
                select(
                    oauth_refresh_tokens.c.id,
                    oauth_refresh_tokens.c.family_id,
                    oauth_refresh_tokens.c.generation,
                    oauth_refresh_tokens.c.idle_expires_at,
                    oauth_refresh_tokens.c.consumed_at,
                    oauth_refresh_tokens.c.revoked_at,
                    oauth_refresh_token_families.c.remote_client_id,
                    oauth_refresh_token_families.c.scope,
                    oauth_refresh_token_families.c.resource,
                    oauth_refresh_token_families.c.absolute_expires_at,
                    oauth_refresh_token_families.c.revoked_at.label("family_revoked_at"),
                    remote_clients.c.oauth_client_id,
                    remote_clients.c.principal_id,
                    remote_clients.c.enabled,
                    remote_clients.c.refresh_enabled,
                    remote_clients.c.expires_at.label("client_expires_at"),
                    remote_clients.c.revoked_at.label("client_revoked_at"),
                )
                .select_from(
                    oauth_refresh_tokens.join(
                        oauth_refresh_token_families,
                        oauth_refresh_tokens.c.family_id == oauth_refresh_token_families.c.id,
                    ).join(
                        remote_clients,
                        oauth_refresh_token_families.c.remote_client_id == remote_clients.c.id,
                    )
                )
                .where(oauth_refresh_tokens.c.token_hash == digest)
            )
            if connection.dialect.name == "postgresql":
                query = query.with_for_update()
            row = connection.execute(query).one_or_none()
            if row is None:
                denial = {"reason": "invalid"}
            elif row.consumed_at is not None:
                repository.revoke_refresh_family(
                    family_id=row.family_id,
                    now=now,
                    reason="replay_detected",
                    replay=True,
                )
                replay = {
                    "client_id": row.oauth_client_id,
                    "family_id": str(row.family_id),
                    "generation": row.generation,
                    "reason": "replay_detected",
                }
            elif (
                row.family_revoked_at is not None
                or row.revoked_at is not None
                or _aware(row.idle_expires_at) <= now
                or _aware(row.absolute_expires_at) <= now
                or row.oauth_client_id != values.get("client_id")
                or not row.enabled
                or row.client_revoked_at is not None
                or (row.client_expires_at is not None and _aware(row.client_expires_at) <= now)
                or not row.refresh_enabled
                or row.principal_id != LOCAL_OPERATOR_UUID
                or row.resource != values.get("resource", self.resource)
                or not repository.remote_access_enabled()
            ):
                denial = {
                    "client_id": row.oauth_client_id,
                    "family_id": str(row.family_id),
                    "generation": row.generation,
                    "reason": "invalid",
                }
            else:
                scope = row.scope
                if requested_scope:
                    try:
                        requested = self._scopes(requested_scope)
                    except OAuthError:
                        denial = {
                            "client_id": row.oauth_client_id,
                            "family_id": str(row.family_id),
                            "reason": "invalid",
                        }
                    else:
                        if not requested <= frozenset(row.scope.split()):
                            denial = {
                                "client_id": row.oauth_client_id,
                                "family_id": str(row.family_id),
                                "reason": "invalid",
                            }
                        else:
                            scope = " ".join(sorted(requested))
                if denial is None and not repository.has_active_capability_grant(
                    remote_client_id=row.remote_client_id,
                    token_scopes=frozenset(scope.split()),
                    resource=row.resource,
                    now=now,
                ):
                    denial = {
                        "client_id": row.oauth_client_id,
                        "family_id": str(row.family_id),
                        "generation": row.generation,
                        "reason": "invalid",
                    }
                if denial is None:
                    consumed = connection.execute(
                        oauth_refresh_tokens.update()
                        .where(
                            oauth_refresh_tokens.c.id == row.id,
                            oauth_refresh_tokens.c.consumed_at.is_(None),
                            oauth_refresh_tokens.c.revoked_at.is_(None),
                        )
                        .values(consumed_at=now)
                    )
                    if consumed.rowcount != 1:
                        repository.revoke_refresh_family(
                            family_id=row.family_id,
                            now=now,
                            reason="replay_detected",
                            replay=True,
                        )
                        replay = {
                            "client_id": row.oauth_client_id,
                            "family_id": str(row.family_id),
                            "generation": row.generation,
                            "reason": "replay_detected",
                        }
                    else:
                        next_generation = int(row.generation) + 1
                        raw_refresh = secrets.token_urlsafe(32)
                        connection.execute(
                            oauth_refresh_tokens.insert().values(
                                id=uuid4(),
                                family_id=row.family_id,
                                token_hash=_digest(raw_refresh),
                                generation=next_generation,
                                issued_at=now,
                                idle_expires_at=now + self.refresh_idle_lifetime,
                                consumed_at=None,
                                revoked_at=None,
                            )
                        )
                        connection.execute(
                            oauth_refresh_token_families.update()
                            .where(oauth_refresh_token_families.c.id == row.family_id)
                            .values(last_rotated_at=now)
                        )
                        raw_token = self._mint_access_token(
                            connection,
                            remote_client_id=row.remote_client_id,
                            scope=scope,
                            resource=row.resource,
                            now=now,
                            family_id=row.family_id,
                        )
                        issued = {
                            "access_token": raw_token,
                            "token_type": "Bearer",
                            "expires_in": int(self.access_token_lifetime.total_seconds()),
                            "scope": scope,
                            "refresh_token": raw_refresh,
                        }
                        succeeded = {
                            "client_id": row.oauth_client_id,
                            "family_id": str(row.family_id),
                            "generation": next_generation,
                            "resource": row.resource,
                            "scope": scope,
                        }
        # Replay revocation must commit before invalid_grant is raised.
        # `engine.begin()` rolls back on exception, which would otherwise leave
        # the reused generation and its linked access tokens active.
        if replay is not None:
            self._emit("oauth.refresh.replay_detected", **replay)
            raise OAuthError("invalid_grant", "refresh token is invalid")
        if denial is not None or issued is None or succeeded is None:
            if denial is not None:
                self._emit("oauth.refresh.denied", **denial)
            else:
                self._emit("oauth.refresh.denied", reason="invalid")
            raise OAuthError("invalid_grant", "refresh token is invalid")
        self._emit("oauth.refresh.succeeded", **succeeded)
        return issued

    def _mint_refresh_family(
        self,
        connection: Connection,
        *,
        remote_client_id: UUID,
        scope: str,
        resource: str,
        now: datetime,
    ) -> tuple[UUID, str]:
        family_id = uuid4()
        raw_refresh = secrets.token_urlsafe(32)
        connection.execute(
            oauth_refresh_token_families.insert().values(
                id=family_id,
                remote_client_id=remote_client_id,
                scope=scope,
                resource=resource,
                created_at=now,
                absolute_expires_at=now + self.refresh_absolute_lifetime,
                last_rotated_at=now,
                revoked_at=None,
                revoke_reason=None,
                replay_detected_at=None,
            )
        )
        connection.execute(
            oauth_refresh_tokens.insert().values(
                id=uuid4(),
                family_id=family_id,
                token_hash=_digest(raw_refresh),
                generation=0,
                issued_at=now,
                idle_expires_at=now + self.refresh_idle_lifetime,
                consumed_at=None,
                revoked_at=None,
            )
        )
        return family_id, raw_refresh

    def _mint_access_token(
        self,
        connection: Connection,
        *,
        remote_client_id: UUID,
        scope: str,
        resource: str,
        now: datetime,
        family_id: UUID | None,
    ) -> str:
        raw_token = secrets.token_urlsafe(32)
        connection.execute(
            oauth_access_tokens.insert().values(
                token_hash=_digest(raw_token),
                remote_client_id=remote_client_id,
                scope=scope,
                resource=resource,
                expires_at=now + self.access_token_lifetime,
                revoked_at=None,
                created_at=now,
                refresh_family_id=family_id,
            )
        )
        return raw_token

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
        now = _aware(self.now())
        digest = _digest(raw_token)
        with self.connections() as connection:
            updated = connection.execute(
                oauth_access_tokens.update()
                .where(oauth_access_tokens.c.token_hash == digest)
                .values(revoked_at=now)
            )
            if updated.rowcount:
                return
            family_id = connection.execute(
                select(oauth_refresh_tokens.c.family_id).where(
                    oauth_refresh_tokens.c.token_hash == digest
                )
            ).scalar_one_or_none()
            if family_id is not None:
                RemoteIdentityRepository(connection).revoke_refresh_family(
                    family_id=family_id,
                    now=now,
                    reason="operator_revoked",
                )

    def authorization_server_metadata(self) -> dict[str, object]:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/oauth/authorize",
            "token_endpoint": f"{self.issuer}/oauth/token",
            "registration_endpoint": f"{self.issuer}/oauth/register",
            "revocation_endpoint": f"{self.issuer}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": sorted(self.supported_scopes),
        }

    def _scopes(self, raw: str) -> frozenset[str]:
        scopes = frozenset(raw.split())
        if not scopes or not scopes <= self.supported_scopes:
            raise OAuthError("invalid_scope", "requested scope is not supported")
        return scopes
