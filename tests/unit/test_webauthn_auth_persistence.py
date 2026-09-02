"""FAST-safe domain contracts for WP02 auth persistence helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from my_pa.domain.identity.auth_sessions import (
    AUTH_SESSION_ABSOLUTE_TTL,
    AUTH_SESSION_IDLE_TTL,
    AuthSession,
    capped_idle_expiry,
    session_is_authoritative,
)
from my_pa.domain.identity.recovery_codes import (
    issue_recovery_code,
    normalize_recovery_code,
)
from my_pa.domain.identity.secret_digests import (
    DIGEST_HEX_LENGTH,
    AuthSecretError,
    digest_bytes,
    digest_text,
    digests_match,
    encode_opaque_token,
    issue_opaque_token,
    parse_opaque_token,
)
from my_pa.domain.identity.webauthn_credentials import (
    WEBAUTHN_CHALLENGE_PURPOSE_VALUES,
    WebAuthnChallengePurpose,
)

WHEN = datetime(2026, 9, 1, 12, tzinfo=UTC)


def test_challenge_purpose_enum_matches_the_frozen_literal_list() -> None:
    assert tuple(member.value for member in WebAuthnChallengePurpose) == (
        WEBAUTHN_CHALLENGE_PURPOSE_VALUES
    )


def test_opaque_token_pairs_raw_bytes_with_sha256_hex() -> None:
    raw, digest = issue_opaque_token()
    again, _ = issue_opaque_token()
    assert raw != again
    assert len(raw) == 32
    assert digest == digest_bytes(raw)
    assert len(digest) == DIGEST_HEX_LENGTH
    assert encode_opaque_token(raw) == raw.hex()
    assert parse_opaque_token(raw.hex()) == raw


def test_malformed_opaque_tokens_are_refused() -> None:
    with pytest.raises(AuthSecretError):
        parse_opaque_token("not-hex")
    with pytest.raises(AuthSecretError):
        parse_opaque_token("ab")
    with pytest.raises(AuthSecretError):
        digest_bytes(b"")


def test_digest_comparison_is_closed_for_absent_and_wrong_values() -> None:
    _raw, digest = issue_opaque_token()
    other, _ = issue_opaque_token()
    assert digests_match(digest, digest)
    assert not digests_match(digest_bytes(other), digest)
    assert not digests_match(digest, None)
    assert not digests_match("0" * 64, digest)


def test_recovery_code_normalizes_grouping_before_hashing() -> None:
    plaintext, digest = issue_recovery_code()
    assert "-" in plaintext
    assert digest == digest_text(normalize_recovery_code(plaintext))
    assert digest == digest_text(normalize_recovery_code(plaintext.upper()))
    assert digest == digest_text(normalize_recovery_code(plaintext.replace("-", "")))
    other, _ = issue_recovery_code()
    assert plaintext != other
    assert not digests_match(digest_text(normalize_recovery_code(other)), digest)


def test_idle_expiry_never_passes_absolute_expiry() -> None:
    created = WHEN
    absolute = created + AUTH_SESSION_ABSOLUTE_TTL
    idle = capped_idle_expiry(
        now=created, idle_ttl=AUTH_SESSION_IDLE_TTL, absolute_expires_at=absolute
    )
    assert idle == created + AUTH_SESSION_IDLE_TTL
    near_end = absolute - timedelta(minutes=5)
    capped = capped_idle_expiry(
        now=near_end, idle_ttl=AUTH_SESSION_IDLE_TTL, absolute_expires_at=absolute
    )
    assert capped == absolute
    assert capped <= absolute


def test_session_authority_fails_closed_on_expiry_revocation_and_supersession() -> None:
    principal = uuid4()
    token_hash = digest_bytes(b"x" * 32)
    base = AuthSession(
        id=uuid4(),
        token_hash=token_hash,
        principal_id=principal,
        created_at=WHEN,
        last_seen_at=WHEN,
        idle_expires_at=WHEN + AUTH_SESSION_IDLE_TTL,
        absolute_expires_at=WHEN + AUTH_SESSION_ABSOLUTE_TTL,
    )
    assert session_is_authoritative(base, now=WHEN + timedelta(minutes=1))
    idle_dead = AuthSession(
        id=base.id,
        token_hash=token_hash,
        principal_id=principal,
        created_at=WHEN,
        last_seen_at=WHEN,
        idle_expires_at=WHEN + timedelta(minutes=1),
        absolute_expires_at=WHEN + AUTH_SESSION_ABSOLUTE_TTL,
    )
    assert not session_is_authoritative(idle_dead, now=WHEN + timedelta(minutes=2))
    revoked = AuthSession(
        id=base.id,
        token_hash=token_hash,
        principal_id=principal,
        created_at=WHEN,
        last_seen_at=WHEN,
        idle_expires_at=WHEN + AUTH_SESSION_IDLE_TTL,
        absolute_expires_at=WHEN + AUTH_SESSION_ABSOLUTE_TTL,
        revoked_at=WHEN + timedelta(minutes=1),
        revoke_reason="revoked",
    )
    assert not session_is_authoritative(revoked, now=WHEN + timedelta(minutes=2))
    superseded = AuthSession(
        id=base.id,
        token_hash=token_hash,
        principal_id=principal,
        created_at=WHEN,
        last_seen_at=WHEN,
        idle_expires_at=WHEN + AUTH_SESSION_IDLE_TTL,
        absolute_expires_at=WHEN + AUTH_SESSION_ABSOLUTE_TTL,
        superseded_by_id=uuid4(),
    )
    assert not session_is_authoritative(superseded, now=WHEN + timedelta(minutes=1))
