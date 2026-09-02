"""BFF-to-gateway attestation of an already-verified browser session.

The browser never supplies Principal. After the Next BFF resolves the HMAC
session, it signs `(tid, oid, iat)` with a server-only secret. WebAuthn routes
verify that signature and map claims through `UserAccountRepository`.
"""

from __future__ import annotations

import base64
import hmac
import json
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Final

from my_pa.domain.identity.secret_digests import AuthSecretError

__all__ = [
    "ATTESTATION_MAX_AGE",
    "AttestationError",
    "issue_webauthn_attestation",
    "verify_webauthn_attestation",
]

ATTESTATION_MAX_AGE: Final = timedelta(seconds=30)


class AttestationError(AuthSecretError):
    """The BFF attestation is missing, expired, or forged."""


def issue_webauthn_attestation(secret: str, *, tid: str, oid: str, now: datetime) -> str:
    """Return `base64url(json).hexsig` for a verified session's tid/oid."""
    _require_secret(secret)
    payload = _encode({"tid": tid, "oid": oid, "iat": int(now.timestamp())})
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_webauthn_attestation(secret: str, token: str, *, now: datetime) -> tuple[str, str]:
    """Return `(tid, oid)` or raise. Does not accept caller-supplied principal_id."""
    _require_secret(secret)
    if "." not in token:
        raise AttestationError("malformed attestation")
    payload, presented = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(presented, expected):
        raise AttestationError("malformed attestation")
    try:
        attested = _decode(payload)
        tid = attested["tid"]
        oid = attested["oid"]
        issued_raw = attested["iat"]
        if not isinstance(issued_raw, int):
            raise AttestationError("malformed attestation")
        issued_at = issued_raw
    except (KeyError, TypeError, ValueError) as error:
        raise AttestationError("malformed attestation") from error
    if not isinstance(tid, str) or not isinstance(oid, str) or not tid or not oid:
        raise AttestationError("malformed attestation")
    if "principal_id" in attested or "principalId" in attested:
        raise AttestationError("malformed attestation")
    age = now.timestamp() - issued_at
    if age < 0 or age > ATTESTATION_MAX_AGE.total_seconds():
        raise AttestationError("expired attestation")
    return tid, oid


def _require_secret(secret: str) -> None:
    if len(secret.strip()) < 32:
        raise AttestationError("webauthn BFF secret is not configured")


def _encode(body: dict[str, object]) -> str:
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(payload: str) -> dict[str, object]:
    padding = "=" * (-len(payload) % 4)
    parsed = json.loads(base64.urlsafe_b64decode(payload + padding).decode("utf-8"))
    if not isinstance(parsed, dict):
        raise AttestationError("malformed attestation")
    return parsed
