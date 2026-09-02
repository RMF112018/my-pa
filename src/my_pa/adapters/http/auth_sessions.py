"""Loopback BFF session-service routes. Not public MCP capabilities.

The handler is protocol only: origin, service HMAC, body shape, and status.
Store execution is injected by the composition root so this module never
imports SQLAlchemy or AuthSessionStore.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import Response

from my_pa.adapters.http.webauthn import WEBAUTHN_PATH_PREFIX
from my_pa.application.session_service_auth import (
    SYNTHETIC_CATALOGUE,
    SessionServiceAuthError,
    SessionServiceError,
    verify_session_service_token,
)
from my_pa.domain.identity.secret_digests import AuthSecretError, parse_opaque_token
from my_pa.domain.identity.user_account import reject_caller_supplied_principal
from my_pa.domain.identity.webauthn_relying_party import WebAuthnRelyingParty

__all__ = [
    "SESSION_SERVICE_ACTIONS",
    "SESSION_SERVICE_HEADER",
    "dispatch_webauthn_http",
    "session_service_http_handler",
]

SESSION_SERVICE_HEADER: Final = "x-my-pa-session-service"
_ATTESTATION_HEADER: Final = "x-my-pa-webauthn-attestation"
_JSON: Final = "application/json"
_SID_ACTIONS: Final = frozenset(
    {
        "sessions/resolve",
        "sessions/touch",
        "sessions/rotate",
        "sessions/revoke",
    }
)
SESSION_SERVICE_ACTIONS: Final = _SID_ACTIONS | {"sessions/issue-synthetic"}

SessionServiceExecute = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def dispatch_webauthn_http(
    *,
    session_service: Callable[[Request, Mapping[str, Any]], Response],
    ceremony: Callable[[Request, Mapping[str, Any]], Response],
) -> Callable[[Request, Mapping[str, Any]], Response]:
    """Route session-service actions away from WP03 ceremony attestation."""

    def handle(request: Request, document: Mapping[str, Any]) -> Response:
        action = request.url.path.removeprefix(WEBAUTHN_PATH_PREFIX)
        if action in SESSION_SERVICE_ACTIONS:
            return session_service(request, document)
        return ceremony(request, document)

    return handle


def session_service_http_handler(
    *,
    relying_party: WebAuthnRelyingParty | None,
    service_secret: str,
    execute: SessionServiceExecute,
    clock: Callable[[], datetime],
) -> Callable[[Request, Mapping[str, Any]], Response]:
    """Starlette handler for `/webauthn/v1/sessions/` service actions."""

    def handle(request: Request, document: Mapping[str, Any]) -> Response:
        action = request.url.path.removeprefix(WEBAUTHN_PATH_PREFIX)
        if action not in SESSION_SERVICE_ACTIONS:
            return _error("invalid_request", 404)
        if relying_party is None:
            return _error("backend_unavailable", 503)
        origin = request.headers.get("origin")
        if origin is None or not relying_party.accepts_origin(origin):
            return _error("wrong_origin", 403)
        if request.headers.get(_ATTESTATION_HEADER) is not None:
            return _error("attestation_refused", 403)
        if len(service_secret.strip()) < 32:
            return _error("authority_unavailable", 503)
        if not isinstance(document, dict):
            return _error("invalid_request", 400)
        if _caller_supplied_principal(document):
            return _error("caller_supplied_principal", 400)
        token = request.headers.get(SESSION_SERVICE_HEADER)
        if not token:
            return _error("unauthenticated", 401)
        try:
            verify_session_service_token(service_secret, token, now=clock())
        except SessionServiceAuthError:
            return _error("unauthenticated", 401)
        if action in _SID_ACTIONS:
            sid = document.get("sid")
            if not isinstance(sid, str):
                return _error("unauthenticated", 401)
            try:
                parse_opaque_token(sid)
            except AuthSecretError:
                return _error("unauthenticated", 401)
        else:
            key = document.get("key")
            if key not in SYNTHETIC_CATALOGUE:
                return _error("invalid_request", 400)
            if "sid" in document:
                return _error("invalid_request", 400)
        try:
            payload = execute(action, document)
        except SessionServiceError as error:
            return _error(error.code, _status_for(error.code))
        return Response(
            json.dumps(dict(payload), separators=(",", ":"), sort_keys=True),
            status_code=200,
            media_type=_JSON,
            headers={"Cache-Control": "no-store"},
        )

    return handle


def _caller_supplied_principal(document: Mapping[str, Any]) -> bool:
    try:
        reject_caller_supplied_principal(document)
    except Exception:
        return True
    stack: list[Mapping[str, Any]] = [document]
    while stack:
        mapping = stack.pop()
        if "principalId" in mapping:
            return True
        for value in mapping.values():
            if isinstance(value, Mapping):
                stack.append(value)
    return False


def _error(code: str, status: int) -> Response:
    return Response(
        json.dumps({"error": {"code": code}}, separators=(",", ":"), sort_keys=True),
        status_code=status,
        media_type=_JSON,
        headers={"Cache-Control": "no-store"},
    )


def _status_for(code: str) -> int:
    if code == "unauthenticated":
        return 401
    if code in {"authority_unavailable", "backend_unavailable"}:
        return 503
    if code in {"wrong_origin", "attestation_refused"}:
        return 403
    if code == "caller_supplied_principal":
        return 400
    return 400
