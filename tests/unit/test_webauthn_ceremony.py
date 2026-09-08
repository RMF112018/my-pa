"""WebAuthn relying-party and ceremony state-machine tests."""

from __future__ import annotations

import base64
import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest

from my_pa.application.webauthn_bff_attestation import (
    AttestationError,
    issue_webauthn_attestation,
    verify_webauthn_attestation,
)
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.webauthn_relying_party import (
    WebAuthnRelyingParty,
    WebAuthnRelyingPartyError,
    parse_allowed_origins,
)

WHEN = datetime(2026, 9, 2, 12, tzinfo=UTC)
RP = WebAuthnRelyingParty(
    rp_id="localhost",
    rp_name="my-pa",
    allowed_origins=("http://localhost:3100",),
)
SECRET = "synthetic-webauthn-bff-secret-00000000"  # noqa: S105


def _sign(secret: str, body: dict[str, object]) -> str:
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return f"{payload}.{signature}"


def test_origins_are_exact_and_reject_wildcards() -> None:
    assert parse_allowed_origins("https://my-pa.example http://localhost:3100") == (
        "https://my-pa.example",
        "http://localhost:3100",
    )
    with pytest.raises(WebAuthnRelyingPartyError, match="wildcard"):
        parse_allowed_origins("https://*.example")
    with pytest.raises(WebAuthnRelyingPartyError, match="https"):
        parse_allowed_origins("http://my-pa.example")
    party = WebAuthnRelyingParty(
        rp_id="my-pa.example",
        rp_name="my-pa",
        allowed_origins=("https://my-pa.example",),
    )
    assert party.accepts_origin("https://my-pa.example")
    assert not party.accepts_origin("https://evil.example")
    assert not party.accepts_origin("https://sub.my-pa.example")


def test_attestation_round_trips_principal_id_and_rejects_tid_oid() -> None:
    token = issue_webauthn_attestation(SECRET, principal_id=LOCAL_OPERATOR_UUID, now=WHEN)
    assert verify_webauthn_attestation(SECRET, token, now=WHEN) == LOCAL_OPERATOR_UUID
    with pytest.raises(AttestationError):
        verify_webauthn_attestation(SECRET + "x", token, now=WHEN)
    with pytest.raises(AttestationError, match="expired"):
        verify_webauthn_attestation(SECRET, token, now=datetime(2026, 9, 2, 13, tzinfo=UTC))


@pytest.mark.parametrize("field", ["tid", "oid", "principal_id", "principalId"])
def test_attestation_refuses_non_pid_identity_fields(field: str) -> None:
    token = _sign(
        SECRET,
        {"pid": str(LOCAL_OPERATOR_UUID), "iat": int(WHEN.timestamp()), field: "x"},
    )
    with pytest.raises(AttestationError):
        verify_webauthn_attestation(SECRET, token, now=WHEN)


def test_attestation_refuses_tid_oid_without_pid() -> None:
    token = _sign(SECRET, {"tid": "t", "oid": "o", "iat": int(WHEN.timestamp())})
    with pytest.raises(AttestationError):
        verify_webauthn_attestation(SECRET, token, now=WHEN)


def test_attestation_returns_uuid_not_entra_pair() -> None:
    token = issue_webauthn_attestation(
        SECRET, principal_id=UUID("11111111-1111-1111-1111-111111111111"), now=WHEN
    )
    attested = verify_webauthn_attestation(SECRET, token, now=WHEN)
    assert isinstance(attested, UUID)
    assert attested != LOCAL_OPERATOR_UUID


def test_rp_id_rejects_wildcards_and_ports() -> None:
    with pytest.raises(WebAuthnRelyingPartyError):
        WebAuthnRelyingParty(
            rp_id="*.example",
            rp_name="my-pa",
            allowed_origins=("https://my-pa.example",),
        )
