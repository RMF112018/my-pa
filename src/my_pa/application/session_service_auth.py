"""BFF-to-gateway HMAC for opaque AuthSessionStore SID operations.

The browser never supplies Principal. After the Next BFF reads the cookie SID,
it signs a short-lived `{iat}` with a server-only secret distinct from the
WebAuthn attestation secret. Session-service routes verify that signature and
resolve the SID through `AuthSessionStore`.
"""

from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Final

from my_pa.application.webauthn_bff_attestation import ATTESTATION_MAX_AGE
from my_pa.domain.identity.secret_digests import AuthSecretError
from my_pa.domain.identity.user_account import EntraTokenClaims, UserAccount

__all__ = [
    "SYNTHETIC_CATALOGUE",
    "SYNTHETIC_MOSS_TENANT_ID",
    "SessionServiceAuthError",
    "SessionServiceError",
    "issue_session_service_token",
    "session_principal_payload",
    "verify_session_service_token",
]

SYNTHETIC_MOSS_TENANT_ID: Final = "11111111-2222-3333-4444-555555555555"
_FORBIDDEN_PAYLOAD_KEYS: Final = frozenset({"tid", "oid", "principal_id", "principalId", "sid"})

SYNTHETIC_CATALOGUE: Final[Mapping[str, EntraTokenClaims]] = {
    "synthetic-a": EntraTokenClaims(
        tid=SYNTHETIC_MOSS_TENANT_ID,
        oid="aaaa0001-0000-0000-0000-000000000001",
        upn="synthetic.a@moss.example",
        display_name="Synthetic A",
    ),
    "synthetic-b": EntraTokenClaims(
        tid=SYNTHETIC_MOSS_TENANT_ID,
        oid="bbbb0002-0000-0000-0000-000000000002",
        upn="synthetic.b@moss.example",
        display_name="Synthetic B",
    ),
}


class SessionServiceAuthError(AuthSecretError):
    """The session-service HMAC is missing, expired, or forged."""


class SessionServiceError(Exception):
    """Typed session-service failure. `code` is the public error token."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def issue_session_service_token(secret: str, *, now: datetime) -> str:
    """Return `base64url(json).hexsig` for `{iat}` only."""
    _require_secret(secret)
    payload = _encode({"iat": int(now.timestamp())})
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session_service_token(secret: str, token: str, *, now: datetime) -> None:
    """Accept an `{iat}`-only token or raise. Identity fields are refused."""
    _require_secret(secret)
    if "." not in token:
        raise SessionServiceAuthError("malformed session-service token")
    payload, presented = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(presented, expected):
        raise SessionServiceAuthError("malformed session-service token")
    try:
        attested = _decode(payload)
        issued_raw = attested["iat"]
        if not isinstance(issued_raw, int):
            raise SessionServiceAuthError("malformed session-service token")
        issued_at = issued_raw
    except (KeyError, TypeError, ValueError) as error:
        raise SessionServiceAuthError("malformed session-service token") from error
    if any(key in attested for key in _FORBIDDEN_PAYLOAD_KEYS):
        raise SessionServiceAuthError("malformed session-service token")
    age = now.timestamp() - issued_at
    if age < 0 or age > ATTESTATION_MAX_AGE.total_seconds():
        raise SessionServiceAuthError("expired session-service token")


def session_principal_payload(account: UserAccount) -> dict[str, object]:
    """JSON object the BFF receives for a live session's UserAccount."""
    return {
        "principalId": str(account.principal_id),
        "tid": account.tid,
        "oid": account.oid,
        "upn": account.upn or "",
        "displayName": account.display_name or "",
        "lifecycleState": account.lifecycle_state.value,
        "synthetic": account.tid == SYNTHETIC_MOSS_TENANT_ID,
    }


def _require_secret(secret: str) -> None:
    if len(secret.strip()) < 32:
        raise SessionServiceAuthError("session-service secret is not configured")


def _encode(body: dict[str, object]) -> str:
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(payload: str) -> dict[str, object]:
    padding = "=" * (-len(payload) % 4)
    parsed = json.loads(base64.urlsafe_b64decode(payload + padding).decode("utf-8"))
    if not isinstance(parsed, dict):
        raise SessionServiceAuthError("malformed session-service token")
    return parsed
