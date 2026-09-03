"""Session-service HTTP isolation gaps not covered by HMAC protocol tests.

Does not re-test token issuance, expiry, or attestation. Synthetic principals
only. No live personal data.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from my_pa.adapters.http.auth_sessions import (
    SESSION_SERVICE_HEADER,
    session_service_http_handler,
)
from my_pa.application.session_service_auth import (
    SYNTHETIC_MOSS_TENANT_ID,
    SessionServiceError,
    issue_session_service_token,
)
from my_pa.domain.identity.webauthn_relying_party import WebAuthnRelyingParty

WHEN = datetime(2026, 9, 2, 12, tzinfo=UTC)
SECRET = "synthetic-session-service-secret-00000"  # noqa: S105
ORIGIN = "http://localhost:3100"
RP = WebAuthnRelyingParty(rp_id="localhost", rp_name="my-pa", allowed_origins=(ORIGIN,))
SID_A = "aa" * 32
SID_B = "bb" * 32
HMAC_SID = "eyJpYXQiOjE3MjUwMDAwMDB9.0123456789abcdef0123456789abcdef"
PRINCIPAL_A = {
    "principalId": "11111111-1111-1111-1111-111111111111",
    "tid": SYNTHETIC_MOSS_TENANT_ID,
    "oid": "aaaa0001-0000-0000-0000-000000000001",
    "upn": "synthetic.a@moss.example",
    "displayName": "Synthetic A",
    "lifecycleState": "active",
    "synthetic": True,
}
PRINCIPAL_B = {
    **PRINCIPAL_A,
    "principalId": "22222222-2222-2222-2222-222222222222",
    "oid": "bbbb0002-0000-0000-0000-000000000002",
    "upn": "synthetic.b@moss.example",
    "displayName": "Synthetic B",
}


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


def _authed(path: str) -> Request:
    token = issue_session_service_token(SECRET, now=WHEN)
    return _request(
        path,
        headers={"origin": ORIGIN, SESSION_SERVICE_HEADER: token},
    )


def _load(response: Response) -> dict[str, Any]:
    return json.loads(response.body)


def _execute(live: dict[str, dict[str, Any]]) -> Callable[[str, Mapping[str, Any]], dict[str, Any]]:
    def execute(action: str, document: Mapping[str, Any]) -> dict[str, Any]:
        sid = document.get("sid")
        if action in {"sessions/resolve", "sessions/touch"}:
            principal = live.get(sid) if isinstance(sid, str) else None
            if principal is None:
                raise SessionServiceError("unauthenticated")
            return {"principal": dict(principal)}
        if action == "sessions/revoke":
            if not isinstance(sid, str) or sid not in live:
                raise SessionServiceError("unauthenticated")
            del live[sid]
            return {"revoked": True}
        raise SessionServiceError("invalid_request")

    return execute


def _handler(
    live: dict[str, dict[str, Any]],
    *,
    relying_party: WebAuthnRelyingParty | None = RP,
    secret: str = SECRET,
) -> Callable[[Request, Mapping[str, Any]], Response]:
    return session_service_http_handler(
        relying_party=relying_party,
        service_secret=secret,
        execute=_execute(live),
        clock=lambda: WHEN,
    )


def test_two_principals_resolve_only_their_own_sid() -> None:
    live = {SID_A: PRINCIPAL_A, SID_B: PRINCIPAL_B}
    handler = _handler(live)
    body_a = _load(handler(_authed("/webauthn/v1/sessions/resolve"), {"sid": SID_A}))
    body_b = _load(handler(_authed("/webauthn/v1/sessions/resolve"), {"sid": SID_B}))
    assert body_a == {"principal": PRINCIPAL_A}
    assert body_b == {"principal": PRINCIPAL_B}
    assert body_a["principal"]["principalId"] != body_b["principal"]["principalId"]
    assert body_a["principal"]["oid"] != PRINCIPAL_B["oid"]


def test_hmac_shaped_sid_is_unauthenticated_not_authority_unavailable() -> None:
    handler = _handler({SID_A: PRINCIPAL_A})
    response = handler(_authed("/webauthn/v1/sessions/resolve"), {"sid": HMAC_SID})
    assert response.status_code == 401
    assert _load(response) == {"error": {"code": "unauthenticated"}}
    assert b"issuedSid" not in response.body


def test_sign_out_replay_of_the_same_sid_is_unauthenticated() -> None:
    live = {SID_A: PRINCIPAL_A, SID_B: PRINCIPAL_B}
    handler = _handler(live)
    revoked = handler(_authed("/webauthn/v1/sessions/revoke"), {"sid": SID_A})
    assert revoked.status_code == 200
    replay = handler(_authed("/webauthn/v1/sessions/resolve"), {"sid": SID_A})
    assert replay.status_code == 401
    assert _load(replay) == {"error": {"code": "unauthenticated"}}
    still_b = handler(_authed("/webauthn/v1/sessions/resolve"), {"sid": SID_B})
    assert still_b.status_code == 200
    assert _load(still_b)["principal"]["oid"] == PRINCIPAL_B["oid"]


def test_missing_relying_party_is_503_not_401() -> None:
    handler = _handler({SID_A: PRINCIPAL_A}, relying_party=None)
    response = handler(_authed("/webauthn/v1/sessions/resolve"), {"sid": SID_A})
    assert response.status_code == 503
    assert _load(response)["error"]["code"] in {"backend_unavailable", "authority_unavailable"}
