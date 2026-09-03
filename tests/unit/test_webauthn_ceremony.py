"""WebAuthn relying-party and ceremony state-machine tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.webauthn_bff_attestation import (
    AttestationError,
    issue_webauthn_attestation,
    verify_webauthn_attestation,
)
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


def test_attestation_round_trips_tid_oid_and_rejects_principal_id() -> None:
    token = issue_webauthn_attestation(SECRET, tid="t", oid="o", now=WHEN)
    assert verify_webauthn_attestation(SECRET, token, now=WHEN) == ("t", "o")
    with pytest.raises(AttestationError):
        verify_webauthn_attestation(SECRET + "x", token, now=WHEN)
    with pytest.raises(AttestationError, match="expired"):
        verify_webauthn_attestation(SECRET, token, now=datetime(2026, 9, 2, 13, tzinfo=UTC))


def test_rp_id_rejects_wildcards_and_ports() -> None:
    with pytest.raises(WebAuthnRelyingPartyError):
        WebAuthnRelyingParty(
            rp_id="*.example",
            rp_name="my-pa",
            allowed_origins=("https://my-pa.example",),
        )
