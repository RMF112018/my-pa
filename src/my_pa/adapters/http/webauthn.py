"""Loopback WebAuthn ceremony routes. Not public MCP capabilities."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Engine
from starlette.requests import Request
from starlette.responses import Response
from webauthn.helpers import base64url_to_bytes

from my_pa.application.webauthn_bff_attestation import (
    AttestationError,
    verify_webauthn_attestation,
)
from my_pa.application.webauthn_ceremony import (
    CeremonyResult,
    WebAuthnCeremonyError,
    WebAuthnCeremonyService,
)
from my_pa.domain.common.time import utc_now
from my_pa.domain.identity.user_account import reject_caller_supplied_principal
from my_pa.domain.identity.webauthn_relying_party import (
    WebAuthnRelyingParty,
    WebAuthnRelyingPartyError,
)

__all__ = [
    "WEBAUTHN_PATH_PREFIX",
    "WebAuthnHttpConfig",
    "webauthn_http_handler",
]

WEBAUTHN_PATH_PREFIX: Final = "/webauthn/v1/"
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


class WebAuthnHttpConfig:
    """Composition-root WebAuthn HTTP settings."""

    def __init__(
        self,
        *,
        engine: Engine,
        relying_party: WebAuthnRelyingParty | None,
        bff_secret: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.engine = engine
        self.relying_party = relying_party
        self.bff_secret = bff_secret
        self.clock = clock


def webauthn_http_handler(
    config: WebAuthnHttpConfig,
) -> Callable[[Request, Mapping[str, Any]], Response]:
    """Starlette handler for `/webauthn/v1/{action}`."""

    def handle(request: Request, document: Mapping[str, Any]) -> Response:
        action = request.url.path.removeprefix(WEBAUTHN_PATH_PREFIX)
        if action not in _AUTHENTICATED_ACTIONS and action not in _PUBLIC_ACTIONS:
            return _error("invalid_request", 404)
        if config.relying_party is None:
            return _error("backend_unavailable", 503)
        origin = request.headers.get("origin")
        if origin is None or not config.relying_party.accepts_origin(origin):
            return _error("wrong_origin", 403)
        if not isinstance(document, dict):
            return _error("invalid_request", 400)
        try:
            reject_caller_supplied_principal(document)
        except Exception:
            return _error("caller_supplied_principal", 400)
        try:
            with config.engine.begin() as connection:
                service = WebAuthnCeremonyService(
                    connection, config.relying_party, clock=config.clock
                )
                principal_id = None
                if action in _AUTHENTICATED_ACTIONS:
                    token = request.headers.get(_ATTESTATION_HEADER)
                    if not token:
                        return _error("unauthenticated", 401)
                    tid, oid = verify_webauthn_attestation(
                        config.bff_secret, token, now=config.clock()
                    )
                    principal_id = service.ensure_account(
                        tid=tid,
                        oid=oid,
                        upn=None,
                        display_name=None,
                    )
                result = _dispatch(service, action, origin, document, principal_id)
        except AttestationError:
            return _error("unauthenticated", 401)
        except WebAuthnCeremonyError as error:
            return _error(error.code, _status_for(error.code))
        except WebAuthnRelyingPartyError:
            return _error("backend_unavailable", 503)
        return _success(result)

    return handle


def _require_principal(principal_id: UUID | None) -> UUID:
    if principal_id is None:
        raise WebAuthnCeremonyError("unauthenticated")
    return principal_id


def _dispatch(
    service: WebAuthnCeremonyService,
    action: str,
    origin: str,
    document: Mapping[str, Any],
    principal_id: UUID | None,
) -> CeremonyResult:
    if action == "registration/options":
        return service.registration_options(_require_principal(principal_id), origin=origin)
    if action == "registration/complete":
        bound = _require_principal(principal_id)
        credential = document.get("credential")
        if not isinstance(credential, dict):
            raise WebAuthnCeremonyError("invalid_registration")
        label = document.get("label")
        return service.registration_complete(
            bound,
            origin=origin,
            credential=credential,
            label=label if isinstance(label, str) else None,
        )
    if action == "authentication/options":
        return service.authentication_options(origin=origin)
    if action == "authentication/complete":
        credential = document.get("credential")
        if not isinstance(credential, dict):
            raise WebAuthnCeremonyError("invalid_assertion")
        return service.authentication_complete(origin=origin, credential=credential)
    if action == "credentials/list":
        return service.list_credentials(_require_principal(principal_id))
    if action == "credentials/revoke":
        return service.revoke_credential(
            _require_principal(principal_id),
            origin=origin,
            credential_id=_bytes_field(document, "credentialId"),
            administration_grant=_bytes_field(document, "administrationGrant"),
        )
    if action == "recovery/issue":
        return service.issue_recovery(
            _require_principal(principal_id),
            origin=origin,
            administration_grant=_bytes_field(document, "administrationGrant"),
        )
    if action == "recovery/consume":
        presented = document.get("code")
        if not isinstance(presented, str):
            raise WebAuthnCeremonyError("invalid_recovery_code")
        return service.consume_recovery(presented, origin=origin)
    if action == "step-up/options":
        return service.step_up_options(_require_principal(principal_id), origin=origin)
    if action == "step-up/complete":
        credential = document.get("credential")
        if not isinstance(credential, dict):
            raise WebAuthnCeremonyError("invalid_assertion")
        return service.step_up_complete(
            _require_principal(principal_id), origin=origin, credential=credential
        )
    if action == "sessions/revoke-all":
        return service.revoke_all_sessions(
            _require_principal(principal_id),
            origin=origin,
            administration_grant=_bytes_field(document, "administrationGrant"),
        )
    raise WebAuthnCeremonyError("invalid_request")


def _bytes_field(document: Mapping[str, Any], name: str) -> bytes:
    value = document.get(name)
    if not isinstance(value, str) or not value:
        raise WebAuthnCeremonyError("invalid_request")
    try:
        return base64url_to_bytes(value)
    except Exception as error:
        raise WebAuthnCeremonyError("invalid_request") from error


def _success(result: CeremonyResult) -> Response:
    body: dict[str, Any] = dict(result.payload)
    if result.recovery_codes is not None:
        body["codes"] = list(result.recovery_codes)
    if result.issued_session is not None:
        body["sessionCreated"] = True
    return Response(
        json.dumps(body, separators=(",", ":"), sort_keys=True),
        status_code=200,
        media_type=_JSON,
        headers={"Cache-Control": "no-store"},
    )


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
