"""BFF-to-gateway attestation of an already-verified browser session.

The browser never supplies Principal. After the Next BFF resolves the HMAC
session, it signs its durable Principal UUID with a server-only secret.
"""

from __future__ import annotations

import base64
import hmac
import json
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Final
from uuid import UUID

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


def issue_webauthn_attestation(secret: str, *, principal_id: UUID, now: datetime) -> str:
    """Return a signed, short-lived durable-Principal assertion."""
    _require_secret(secret)
    payload = _encode({"pid": str(principal_id), "iat": int(now.timestamp())})
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_webauthn_attestation(secret: str, token: str, *, now: datetime) -> UUID:
    """Return the server-attested durable Principal or raise."""
    _require_secret(secret)
    if "." not in token:
        raise AttestationError("malformed attestation")
    payload, presented = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(presented, expected):
        raise AttestationError("malformed attestation")
    try:
        attested = _decode(payload)
        pid_raw = attested["pid"]
        issued_raw = attested["iat"]
        if not isinstance(pid_raw, str) or not isinstance(issued_raw, int):
            raise AttestationError("malformed attestation")
        principal_id = UUID(pid_raw)
        issued_at = issued_raw
    except (KeyError, TypeError, ValueError) as error:
        raise AttestationError("malformed attestation") from error
    if any(key in attested for key in ("principal_id", "principalId", "tid", "oid")):
        raise AttestationError("malformed attestation")
    age = now.timestamp() - issued_at
    if age < 0 or age > ATTESTATION_MAX_AGE.total_seconds():
        raise AttestationError("expired attestation")
    return principal_id


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
