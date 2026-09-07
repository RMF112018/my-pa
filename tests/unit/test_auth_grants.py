"""One-time auth-grant contracts. Fast tier; no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from my_pa.domain.identity.auth_grants import (
    AUTH_GRANT_MAX_TTL,
    AUTH_GRANT_TTL,
    AuthGrant,
    AuthGrantPurpose,
    IssuedAuthGrant,
)
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID

WHEN = datetime(2026, 9, 7, 12, tzinfo=UTC)
DIGEST = "ab" * 32
RAW_GRANT = "cd" * 32


def _grant(**overrides: object) -> AuthGrant:
    values: dict[str, object] = {
        "id": uuid4(),
        "grant_digest": DIGEST,
        "purpose": AuthGrantPurpose.BOOTSTRAP,
        "target_principal_id": LOCAL_OPERATOR_UUID,
        "authorizing_session_id": None,
        "created_at": WHEN,
        "expires_at": WHEN + AUTH_GRANT_TTL,
    }
    values.update(overrides)
    return AuthGrant(**values)  # type: ignore[arg-type]


def test_bootstrap_grant_exchanges_then_consumes() -> None:
    grant = _grant()
    assert grant.can_exchange(WHEN)
    assert not grant.can_consume(WHEN)
    exchanged = grant.exchanged(WHEN + timedelta(minutes=1))
    assert exchanged.exchanged_at == WHEN + timedelta(minutes=1)
    assert exchanged.can_consume(WHEN + timedelta(minutes=2))
    consumed = exchanged.consumed(WHEN + timedelta(minutes=2))
    assert consumed.consumed_at == WHEN + timedelta(minutes=2)
    assert not consumed.usable_at(WHEN + timedelta(minutes=2))
    assert grant.exchanged_at is None


def test_credential_administration_consumes_without_prior_exchange() -> None:
    session_id = uuid4()
    grant = _grant(
        purpose=AuthGrantPurpose.CREDENTIAL_ADMINISTRATION,
        authorizing_session_id=session_id,
    )
    assert not grant.can_exchange(WHEN)
    assert grant.can_consume(WHEN)
    consumed = grant.consumed(WHEN)
    assert consumed.consumed_at == WHEN
    assert consumed.exchanged_at is None


def test_credential_administration_may_set_exchanged_and_consumed_together() -> None:
    grant = _grant(
        purpose=AuthGrantPurpose.CREDENTIAL_ADMINISTRATION,
        authorizing_session_id=uuid4(),
        exchanged_at=WHEN,
        consumed_at=WHEN,
    )
    assert grant.exchanged_at == WHEN
    assert grant.consumed_at == WHEN
    assert not grant.can_consume(WHEN)


def test_operator_recovery_requires_exchange_before_consume() -> None:
    grant = _grant(purpose=AuthGrantPurpose.OPERATOR_RECOVERY)
    with pytest.raises(ValueError, match="cannot be consumed"):
        grant.consumed(WHEN)
    exchanged = grant.exchanged(WHEN)
    assert exchanged.consumed(WHEN).consumed_at == WHEN


def test_revoked_grant_is_unusable_and_cannot_be_consumed() -> None:
    grant = _grant().revoked(WHEN, "operator_revoked")
    assert grant.revoke_reason == "operator_revoked"
    assert not grant.usable_at(WHEN)
    assert not grant.can_exchange(WHEN)
    with pytest.raises(ValueError, match="cannot be consumed"):
        grant.consumed(WHEN)


def test_grant_cannot_be_consumed_and_revoked() -> None:
    with pytest.raises(ValueError, match="consumed and revoked"):
        _grant(consumed_at=WHEN, revoked_at=WHEN, revoke_reason="x")


def test_digest_must_be_lowercase_sha256_hex() -> None:
    with pytest.raises(ValueError, match="digest"):
        _grant(grant_digest="AB" * 32)
    with pytest.raises(ValueError, match="digest"):
        _grant(grant_digest="ab" * 16)


def test_target_principal_is_the_fixed_local_operator() -> None:
    with pytest.raises(ValueError, match="LOCAL_OPERATOR_UUID"):
        _grant(target_principal_id=uuid4())


def test_expiry_is_positive_and_bounded_to_fifteen_minutes() -> None:
    with pytest.raises(ValueError, match="expiry"):
        _grant(expires_at=WHEN)
    with pytest.raises(ValueError, match="expiry"):
        _grant(expires_at=WHEN + AUTH_GRANT_MAX_TTL + timedelta(seconds=1))
    bounded = _grant(expires_at=WHEN + AUTH_GRANT_MAX_TTL)
    assert bounded.expires_at == WHEN + AUTH_GRANT_MAX_TTL


def test_exchanged_at_is_at_or_after_creation_and_before_expiry() -> None:
    with pytest.raises(ValueError, match="exchanged_at"):
        _grant(exchanged_at=WHEN - timedelta(seconds=1))
    with pytest.raises(ValueError, match="exchanged_at"):
        _grant(exchanged_at=WHEN + AUTH_GRANT_TTL)
    assert _grant(exchanged_at=WHEN).exchanged_at == WHEN


def test_consumed_at_cannot_precede_exchanged_at() -> None:
    with pytest.raises(ValueError, match="consumed_at"):
        _grant(
            exchanged_at=WHEN + timedelta(minutes=2),
            consumed_at=WHEN + timedelta(minutes=1),
        )


def test_bootstrap_forbids_authorizing_session() -> None:
    with pytest.raises(ValueError, match="session"):
        _grant(authorizing_session_id=uuid4())


def test_credential_administration_requires_authorizing_session() -> None:
    with pytest.raises(ValueError, match="session"):
        _grant(purpose=AuthGrantPurpose.CREDENTIAL_ADMINISTRATION)


def test_expired_grant_cannot_exchange_or_consume() -> None:
    grant = _grant()
    later = WHEN + AUTH_GRANT_TTL
    assert not grant.can_exchange(later)
    assert not grant.can_consume(later)
    assert not grant.usable_at(later)


def test_issued_grant_hides_raw_material_from_repr() -> None:
    issued = IssuedAuthGrant(record=_grant(), raw_grant=RAW_GRANT)
    rendered = repr(issued)
    assert RAW_GRANT not in rendered
    assert DIGEST not in repr(issued.record)
    assert issued.raw_grant == RAW_GRANT


def test_default_ttl_is_ten_minutes() -> None:
    assert timedelta(minutes=10) == AUTH_GRANT_TTL
    assert timedelta(minutes=15) == AUTH_GRANT_MAX_TTL
