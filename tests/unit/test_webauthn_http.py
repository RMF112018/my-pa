"""HTTP protocol for WebAuthn ceremony routes. No database."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from my_pa.adapters.http.webauthn import (
    AUTHENTICATED_WEBAUTHN_ACTIONS,
    PUBLIC_WEBAUTHN_ACTIONS,
    webauthn_http_handler,
)
from my_pa.domain.identity.webauthn_relying_party import (
    WebAuthnCeremonyError,
    WebAuthnRelyingParty,
)

ORIGIN = "http://localhost:3100"
RP = WebAuthnRelyingParty(rp_id="localhost", rp_name="my-pa", allowed_origins=(ORIGIN,))


def _request(path: str, *, headers: dict[str, str] | None = None) -> Request:
    packed = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": packed,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
        }
    )


def _load(response: Response) -> dict[str, Any]:
    assert response.headers["cache-control"] == "no-store"
    return json.loads(response.body)


def test_auth_state_is_public_and_returns_payload() -> None:
    captured: dict[str, Any] = {}

    def execute(
        action: str,
        origin: str,
        document: Mapping[str, Any],
        attestation: str | None,
        sid: str | None = None,
    ) -> Mapping[str, Any]:
        captured["action"] = action
        captured["attestation"] = attestation
        captured["sid"] = sid
        captured["origin"] = origin
        captured["document"] = dict(document)
        return {"state": "uninitialized"}

    handler = webauthn_http_handler(relying_party=RP, execute=execute)
    response = handler(_request("/webauthn/v1/auth-state", headers={"origin": ORIGIN}), {})
    assert response.status_code == 200
    assert _load(response) == {"state": "uninitialized"}
    assert captured["action"] == "auth-state"
    assert captured["attestation"] is None
    assert captured["sid"] is None


def test_bootstrap_options_are_public() -> None:
    def execute(
        action: str,
        origin: str,
        document: Mapping[str, Any],
        attestation: str | None,
        sid: str | None = None,
    ) -> Mapping[str, Any]:
        assert action == "bootstrap/registration/options"
        assert attestation is None
        assert document["grant"] == "raw-grant"
        return {"challenge": "abc"}

    handler = webauthn_http_handler(relying_party=RP, execute=execute)
    response = handler(
        _request("/webauthn/v1/bootstrap/registration/options", headers={"origin": ORIGIN}),
        {"grant": "raw-grant"},
    )
    assert response.status_code == 200
    assert _load(response) == {"challenge": "abc"}


def test_registration_options_require_attestation() -> None:
    handler = webauthn_http_handler(
        relying_party=RP, execute=lambda *_args, **_kwargs: {"ok": True}
    )
    response = handler(
        _request("/webauthn/v1/registration/options", headers={"origin": ORIGIN}),
        {"grant": "raw-grant"},
    )
    assert response.status_code == 401
    assert _load(response) == {"error": {"code": "unauthenticated"}}


def test_sid_in_json_body_is_refused() -> None:
    handler = webauthn_http_handler(
        relying_party=RP, execute=lambda *_args, **_kwargs: {"ok": True}
    )
    response = handler(
        _request("/webauthn/v1/auth-state", headers={"origin": ORIGIN}),
        {"sid": "ab" * 32},
    )
    assert response.status_code == 400
    assert _load(response) == {"error": {"code": "invalid_request"}}


def test_authorizing_sid_comes_from_header() -> None:
    seen: dict[str, str | None] = {}

    def execute(
        action: str,
        origin: str,
        document: Mapping[str, Any],
        attestation: str | None,
        sid: str | None = None,
    ) -> Mapping[str, Any]:
        seen["sid"] = sid
        seen["attestation"] = attestation
        return {"ok": True}

    handler = webauthn_http_handler(relying_party=RP, execute=execute)
    response = handler(
        _request(
            "/webauthn/v1/registration/options",
            headers={
                "origin": ORIGIN,
                "x-my-pa-webauthn-attestation": "token",
                "x-my-pa-auth-sid": "header-sid",
            },
        ),
        {"grant": "raw-grant"},
    )
    assert response.status_code == 200
    assert seen["sid"] == "header-sid"
    assert seen["attestation"] == "token"


def test_wrong_origin_is_forbidden() -> None:
    handler = webauthn_http_handler(
        relying_party=RP, execute=lambda *_args, **_kwargs: {"ok": True}
    )
    response = handler(
        _request("/webauthn/v1/auth-state", headers={"origin": "https://evil.example"}),
        {},
    )
    assert response.status_code == 403
    assert _load(response) == {"error": {"code": "wrong_origin"}}


def test_error_status_mapping() -> None:
    def execute(
        action: str,
        origin: str,
        document: Mapping[str, Any],
        attestation: str | None,
        sid: str | None = None,
    ) -> Mapping[str, Any]:
        raise WebAuthnCeremonyError(str(document["code"]))

    handler = webauthn_http_handler(relying_party=RP, execute=execute)
    cases = {
        "bootstrap_required": 401,
        "bootstrap_grant_invalid": 400,
        "operator_recovery_grant_invalid": 400,
        "auth_state_inconsistent": 409,
        "bootstrap_unavailable": 409,
        "operator_recovery_unavailable": 409,
        "step_up_required": 401,
    }
    for code, status in cases.items():
        response = handler(
            _request("/webauthn/v1/auth-state", headers={"origin": ORIGIN}),
            {"code": code},
        )
        assert response.status_code == status, code
        assert _load(response) == {"error": {"code": code}}


def test_public_and_authenticated_actions_are_closed() -> None:
    assert "auth-state" in PUBLIC_WEBAUTHN_ACTIONS
    assert "bootstrap/registration/options" in PUBLIC_WEBAUTHN_ACTIONS
    assert "operator-recovery/registration/complete" in PUBLIC_WEBAUTHN_ACTIONS
    assert "registration/options" in AUTHENTICATED_WEBAUTHN_ACTIONS
    assert "step-up/complete" in AUTHENTICATED_WEBAUTHN_ACTIONS
    assert not (PUBLIC_WEBAUTHN_ACTIONS & AUTHENTICATED_WEBAUTHN_ACTIONS)
