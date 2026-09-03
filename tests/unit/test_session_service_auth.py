"""Opaque BFF session-service HMAC and HTTP protocol tests. No live database."""

from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

from my_pa.adapters.http.auth_sessions import (
    SESSION_SERVICE_ACTIONS,
    SESSION_SERVICE_HEADER,
    dispatch_webauthn_http,
    session_service_http_handler,
)
from my_pa.application.session_service_auth import (
    SYNTHETIC_CATALOGUE,
    SYNTHETIC_MOSS_TENANT_ID,
    SessionServiceAuthError,
    SessionServiceError,
    issue_session_service_token,
    session_principal_payload,
    verify_session_service_token,
)
from my_pa.bootstrap.gateway import _ceremony_response_body
from my_pa.domain.identity.auth_sessions import AuthSession, IssuedAuthSession
from my_pa.domain.identity.user_account import (
    ConsentState,
    UserAccount,
    UserLifecycleState,
)
from my_pa.domain.identity.webauthn_relying_party import WebAuthnRelyingParty
from my_pa.infrastructure.security.webauthn_ceremony import CeremonyResult

WHEN = datetime(2026, 9, 2, 12, tzinfo=UTC)
SECRET = "synthetic-session-service-secret-00000"  # noqa: S105
ORIGIN = "http://localhost:3100"
RP = WebAuthnRelyingParty(rp_id="localhost", rp_name="my-pa", allowed_origins=(ORIGIN,))
LIVE_SID = "ab" * 32
DEAD_SID = "cd" * 32
LOSER_SID = "ef" * 32
NEW_SID = "11" * 32
ISSUED_SID = "22" * 32
PRINCIPAL = {
    "principalId": "11111111-1111-1111-1111-111111111111",
    "tid": SYNTHETIC_MOSS_TENANT_ID,
    "oid": "aaaa0001-0000-0000-0000-000000000001",
    "upn": "synthetic.a@moss.example",
    "displayName": "Synthetic A",
    "lifecycleState": "active",
    "synthetic": True,
}


def _sign(secret: str, body: dict[str, object]) -> str:
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return f"{payload}.{signature}"


def test_issue_verify_round_trips_iat_only_token() -> None:
    token = issue_session_service_token(SECRET, now=WHEN)
    verify_session_service_token(SECRET, token, now=WHEN)


@pytest.mark.parametrize("field", ["tid", "oid", "principal_id", "principalId", "sid"])
def test_payload_identity_fields_are_refused(field: str) -> None:
    token = _sign(SECRET, {"iat": int(WHEN.timestamp()), field: "x"})
    with pytest.raises(SessionServiceAuthError):
        verify_session_service_token(SECRET, token, now=WHEN)


def test_wrong_secret_is_refused() -> None:
    token = issue_session_service_token(SECRET, now=WHEN)
    with pytest.raises(SessionServiceAuthError):
        verify_session_service_token(SECRET + "x", token, now=WHEN)


def test_expired_token_is_refused() -> None:
    token = issue_session_service_token(SECRET, now=WHEN)
    with pytest.raises(SessionServiceAuthError, match="expired"):
        verify_session_service_token(SECRET, token, now=WHEN + timedelta(seconds=31))


def test_malformed_token_is_refused() -> None:
    with pytest.raises(SessionServiceAuthError):
        verify_session_service_token(SECRET, "not-a-token", now=WHEN)


def test_short_secret_fails_closed() -> None:
    with pytest.raises(SessionServiceAuthError):
        issue_session_service_token("too-short", now=WHEN)
    with pytest.raises(SessionServiceAuthError):
        verify_session_service_token("too-short", "x.y", now=WHEN)


def test_compare_digest_rejects_one_bit_flip() -> None:
    token = issue_session_service_token(SECRET, now=WHEN)
    payload, signature = token.rsplit(".", 1)
    flipped = ("0" if signature[0] != "0" else "1") + signature[1:]
    with pytest.raises(SessionServiceAuthError):
        verify_session_service_token(SECRET, f"{payload}.{flipped}", now=WHEN)
    verify_session_service_token(SECRET, token, now=WHEN)


def test_synthetic_catalogue_maps_keys() -> None:
    assert SYNTHETIC_CATALOGUE["synthetic-a"].oid == "aaaa0001-0000-0000-0000-000000000001"
    assert SYNTHETIC_CATALOGUE["synthetic-b"].oid == "bbbb0002-0000-0000-0000-000000000002"
    assert SYNTHETIC_CATALOGUE["synthetic-a"].tid == SYNTHETIC_MOSS_TENANT_ID
    assert "synthetic-c" not in SYNTHETIC_CATALOGUE


def test_session_principal_payload_marks_synthetic_moss_tenant() -> None:
    account = UserAccount(
        id=uuid4(),
        principal_id=uuid4(),
        tid=SYNTHETIC_MOSS_TENANT_ID,
        oid="aaaa0001-0000-0000-0000-000000000001",
        upn=None,
        display_name=None,
        first_seen_at=WHEN,
        last_authenticated_at=WHEN,
        consent_state=ConsentState.PENDING,
        lifecycle_state=UserLifecycleState.ACTIVE,
        home_tenant_verified=True,
    )
    payload = session_principal_payload(account)
    assert payload["upn"] == ""
    assert payload["displayName"] == ""
    assert payload["synthetic"] is True
    assert payload["lifecycleState"] == "active"


def test_ceremony_response_body_copies_raw_sid() -> None:
    session = AuthSession(
        id=uuid4(),
        token_hash="a" * 64,
        principal_id=uuid4(),
        created_at=WHEN,
        last_seen_at=WHEN,
        idle_expires_at=WHEN + timedelta(minutes=30),
        absolute_expires_at=WHEN + timedelta(hours=8),
    )
    result = CeremonyResult(
        payload={"ok": True},
        issued_session=IssuedAuthSession(record=session, raw_sid=LIVE_SID),
    )
    body = _ceremony_response_body(result)
    assert body["sessionCreated"] is True
    assert body["issuedSid"] == LIVE_SID
    assert "issuedSid" not in _ceremony_response_body(CeremonyResult(payload={"ok": True}))


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


def _execute(action: str, document: dict[str, Any]) -> dict[str, Any]:
    if action in {"sessions/resolve", "sessions/touch"}:
        if document.get("sid") != LIVE_SID:
            raise SessionServiceError("unauthenticated")
        return {"principal": dict(PRINCIPAL)}
    if action == "sessions/rotate":
        if document.get("sid") == LOSER_SID:
            raise SessionServiceError("unauthenticated")
        if document.get("sid") != LIVE_SID:
            raise SessionServiceError("unauthenticated")
        return {"issuedSid": NEW_SID}
    if action == "sessions/revoke":
        if document.get("sid") != LIVE_SID:
            raise SessionServiceError("unauthenticated")
        return {"revoked": True}
    if action == "sessions/issue-synthetic":
        claims = SYNTHETIC_CATALOGUE[document["key"]]
        return {
            "issuedSid": ISSUED_SID,
            "principal": {
                **PRINCIPAL,
                "oid": claims.oid,
                "upn": claims.upn or "",
                "displayName": claims.display_name or "",
            },
        }
    raise SessionServiceError("invalid_request")


def _handler(*, secret: str = SECRET) -> Callable[[Request, Mapping[str, Any]], Response]:
    return session_service_http_handler(
        relying_party=RP,
        service_secret=secret,
        execute=_execute,
        clock=lambda: WHEN,
    )


def _authed(path: str) -> Request:
    token = issue_session_service_token(SECRET, now=WHEN)
    return _request(
        path,
        headers={"origin": ORIGIN, SESSION_SERVICE_HEADER: token},
    )


def _load(response: Response) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    return json.loads(response.body)


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("sessions/resolve", {"sid": LIVE_SID}),
        ("sessions/touch", {"sid": LIVE_SID}),
    ],
)
def test_resolve_and_touch_return_principal(action: str, body: dict[str, str]) -> None:
    response = _handler()(_authed(f"/webauthn/v1/{action}"), body)
    assert response.status_code == 200
    assert _load(response) == {"principal": PRINCIPAL}


def test_rotate_winner_returns_issued_sid() -> None:
    response = _handler()(_authed("/webauthn/v1/sessions/rotate"), {"sid": LIVE_SID})
    assert response.status_code == 200
    assert _load(response) == {"issuedSid": NEW_SID}


def test_revoke_live_sid() -> None:
    response = _handler()(_authed("/webauthn/v1/sessions/revoke"), {"sid": LIVE_SID})
    assert response.status_code == 200
    assert _load(response) == {"revoked": True}


@pytest.mark.parametrize(
    "action",
    ["sessions/resolve", "sessions/touch", "sessions/rotate", "sessions/revoke"],
)
def test_dead_sid_is_unauthenticated(action: str) -> None:
    response = _handler()(_authed(f"/webauthn/v1/{action}"), {"sid": DEAD_SID})
    assert response.status_code == 401
    assert _load(response) == {"error": {"code": "unauthenticated"}}
    assert "issuedSid" not in response.body.decode()


def test_missing_service_secret_is_authority_unavailable() -> None:
    token = issue_session_service_token(SECRET, now=WHEN)
    request = _request(
        "/webauthn/v1/sessions/resolve",
        headers={"origin": ORIGIN, SESSION_SERVICE_HEADER: token},
    )
    response = _handler(secret="")(request, {"sid": LIVE_SID})
    assert response.status_code == 503
    assert _load(response) == {"error": {"code": "authority_unavailable"}}


def test_missing_service_header_is_unauthenticated() -> None:
    request = _request("/webauthn/v1/sessions/resolve", headers={"origin": ORIGIN})
    response = _handler()(request, {"sid": LIVE_SID})
    assert response.status_code == 401
    assert _load(response) == {"error": {"code": "unauthenticated"}}


def test_bad_service_header_is_unauthenticated() -> None:
    request = _request(
        "/webauthn/v1/sessions/resolve",
        headers={"origin": ORIGIN, SESSION_SERVICE_HEADER: "not-valid"},
    )
    response = _handler()(request, {"sid": LIVE_SID})
    assert response.status_code == 401
    assert _load(response) == {"error": {"code": "unauthenticated"}}


def test_webauthn_attestation_header_is_refused() -> None:
    token = issue_session_service_token(SECRET, now=WHEN)
    request = _request(
        "/webauthn/v1/sessions/resolve",
        headers={
            "origin": ORIGIN,
            SESSION_SERVICE_HEADER: token,
            "x-my-pa-webauthn-attestation": token,
        },
    )
    response = _handler()(request, {"sid": LIVE_SID})
    assert response.status_code == 403
    assert _load(response) == {"error": {"code": "attestation_refused"}}


@pytest.mark.parametrize("field", ["tid", "oid", "principal_id", "principalId"])
def test_caller_supplied_principal_is_refused(field: str) -> None:
    response = _handler()(_authed("/webauthn/v1/sessions/resolve"), {"sid": LIVE_SID, field: "x"})
    assert response.status_code == 400
    assert _load(response) == {"error": {"code": "caller_supplied_principal"}}


def test_rotate_loser_has_no_issued_sid() -> None:
    response = _handler()(_authed("/webauthn/v1/sessions/rotate"), {"sid": LOSER_SID})
    assert response.status_code == 401
    body = _load(response)
    assert body == {"error": {"code": "unauthenticated"}}
    assert "issuedSid" not in body


def test_revoke_all_is_not_a_session_service_action() -> None:
    assert "sessions/revoke-all" not in SESSION_SERVICE_ACTIONS
    response = _handler()(_authed("/webauthn/v1/sessions/revoke-all"), {})
    assert response.status_code == 404
    seen: list[str] = []

    def ceremony(request: Request, document: dict[str, Any]) -> Response:
        del document
        seen.append(request.url.path)
        return Response("ceremony", status_code=200)

    dispatch = dispatch_webauthn_http(session_service=_handler(), ceremony=ceremony)
    dispatched = dispatch(_authed("/webauthn/v1/sessions/revoke-all"), {})
    assert dispatched.status_code == 200
    assert seen == ["/webauthn/v1/sessions/revoke-all"]


def test_issue_synthetic_maps_catalogue_and_returns_issued_sid() -> None:
    response = _handler()(_authed("/webauthn/v1/sessions/issue-synthetic"), {"key": "synthetic-b"})
    assert response.status_code == 200
    body = _load(response)
    assert body["issuedSid"] == ISSUED_SID
    assert body["principal"]["oid"] == "bbbb0002-0000-0000-0000-000000000002"
    assert body["principal"]["synthetic"] is True
    assert body["principal"]["upn"] == "synthetic.b@moss.example"


def test_issue_synthetic_refuses_tid_in_body() -> None:
    response = _handler()(
        _authed("/webauthn/v1/sessions/issue-synthetic"),
        {"key": "synthetic-a", "tid": SYNTHETIC_MOSS_TENANT_ID},
    )
    assert response.status_code == 400
    assert _load(response) == {"error": {"code": "caller_supplied_principal"}}


def test_issue_synthetic_unknown_key_is_invalid_request() -> None:
    response = _handler()(_authed("/webauthn/v1/sessions/issue-synthetic"), {"key": "synthetic-c"})
    assert response.status_code == 400
    assert _load(response) == {"error": {"code": "invalid_request"}}


def test_malformed_sid_is_unauthenticated() -> None:
    response = _handler()(_authed("/webauthn/v1/sessions/resolve"), {"sid": "not-hex"})
    assert response.status_code == 401
    assert _load(response) == {"error": {"code": "unauthenticated"}}
