"""Loopback WebAuthn ceremony routes. Not public MCP capabilities.

The handler is protocol only: origin, attestation, body shape, and status.
Ceremony execution is injected by the composition root so this module never
imports SQLAlchemy, the WebAuthn library, or persistence.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import Response

from my_pa.application.webauthn_bff_attestation import AttestationError
from my_pa.domain.identity.user_account import reject_caller_supplied_principal
from my_pa.domain.identity.webauthn_relying_party import (
    WebAuthnCeremonyError,
    WebAuthnRelyingParty,
    WebAuthnRelyingPartyError,
)

__all__ = [
    "WEBAUTHN_PATH",
    "WEBAUTHN_PATH_PREFIX",
    "webauthn_http_handler",
]

WEBAUTHN_PATH_PREFIX: Final = "/webauthn/v1/"
WEBAUTHN_PATH: Final = "/webauthn/v1/{action}"
_JSON: Final = "application/json"
_ATTESTATION_HEADER: Final = "x-my-pa-webauthn-attestation"
_AUTHENTICATED_ACTIONS: Final = frozenset(
    {
        "registration/options",
        "registration/complete",
        "credentials/list",
        "credentials/revoke",
        "recovery/issue",
        "step-up/options",
        "step-up/complete",
        "sessions/revoke-all",
    }
)
_PUBLIC_ACTIONS: Final = frozenset(
    {"authentication/options", "authentication/complete", "recovery/consume"}
)

WebAuthnExecute = Callable[[str, str, Mapping[str, Any], str | None], Mapping[str, Any]]


def webauthn_http_handler(
    *,
    relying_party: WebAuthnRelyingParty | None,
    execute: WebAuthnExecute,
) -> Callable[[Request, Mapping[str, Any]], Response]:
    """Starlette handler for `/webauthn/v1/{action}`."""

    def handle(request: Request, document: Mapping[str, Any]) -> Response:
        action = request.url.path.removeprefix(WEBAUTHN_PATH_PREFIX)
        if action not in _AUTHENTICATED_ACTIONS and action not in _PUBLIC_ACTIONS:
            return _error("invalid_request", 404)
        if relying_party is None:
            return _error("backend_unavailable", 503)
        origin = request.headers.get("origin")
        if origin is None or not relying_party.accepts_origin(origin):
            return _error("wrong_origin", 403)
        if not isinstance(document, dict):
            return _error("invalid_request", 400)
        try:
            reject_caller_supplied_principal(document)
        except Exception:
            return _error("caller_supplied_principal", 400)
        attestation = request.headers.get(_ATTESTATION_HEADER)
        if action in _AUTHENTICATED_ACTIONS and not attestation:
            return _error("unauthenticated", 401)
        try:
            payload = execute(action, origin, document, attestation)
        except AttestationError:
            return _error("unauthenticated", 401)
        except WebAuthnCeremonyError as error:
            return _error(error.code, _status_for(error.code))
        except WebAuthnRelyingPartyError:
            return _error("backend_unavailable", 503)
        return Response(
            json.dumps(dict(payload), separators=(",", ":"), sort_keys=True),
            status_code=200,
            media_type=_JSON,
            headers={"Cache-Control": "no-store"},
        )

    return handle


def _error(code: str, status: int) -> Response:
    return Response(
        json.dumps({"error": {"code": code}}, separators=(",", ":"), sort_keys=True),
        status_code=status,
        media_type=_JSON,
        headers={"Cache-Control": "no-store"},
    )


def _status_for(code: str) -> int:
    if code in {"unauthenticated", "step_up_required", "step_up_expired"}:
        return 401
    if code in {"wrong_origin", "caller_supplied_principal", "principal_mismatch"}:
        return 403
    if code == "duplicate_credential":
        return 409
    if code == "backend_unavailable":
        return 503
    if code == "rate_limited":
        return 429
    return 400
