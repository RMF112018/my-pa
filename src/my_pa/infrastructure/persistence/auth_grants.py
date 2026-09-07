"""Digest-only, one-time authorization grants for auth ceremonies."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    Index,
    Row,
    String,
    Table,
    Uuid,
    func,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.auth_grants import (
    AUTH_GRANT_MAX_TTL,
    AUTH_GRANT_TTL,
    AuthGrant,
    AuthGrantPurpose,
    IssuedAuthGrant,
)
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.secret_digests import (
    AuthSecretError,
    digest_bytes,
    encode_opaque_token,
    issue_opaque_token,
    parse_opaque_token,
)
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA

auth_grants = Table(
    "auth_grants",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("grant_digest", String(64), nullable=False, unique=True),
    Column("purpose", String(48), nullable=False),
    Column("target_principal_id", Uuid(as_uuid=True), nullable=False),
    Column("authorizing_session_id", Uuid(as_uuid=True), ForeignKey("identity.auth_sessions.id")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("exchanged_at", DateTime(timezone=True)),
    Column("consumed_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("revoke_reason", String(64)),
    CheckConstraint("grant_digest ~ '^[0-9a-f]{64}$'", name="auth_grant_digest_is_sha256_hex"),
    CheckConstraint(
        "purpose IN ('bootstrap', 'operator_recovery', 'credential_administration')",
        name="auth_grant_purpose_is_known",
    ),
    CheckConstraint(
        "target_principal_id = '24abf5d2-d0c2-5e1c-82f6-e72425e9ed37'::uuid",
        name="auth_grant_target_is_local_operator",
    ),
    CheckConstraint(
        "expires_at > created_at AND expires_at <= created_at + interval '15 minutes'",
        name="auth_grant_expiry_is_bounded",
    ),
    CheckConstraint(
        "consumed_at IS NULL OR revoked_at IS NULL",
        name="auth_grant_terminal_state_is_exclusive",
    ),
    CheckConstraint(
        "(purpose = 'credential_administration' AND authorizing_session_id IS NOT NULL) OR "
        "(purpose IN ('bootstrap', 'operator_recovery') AND authorizing_session_id IS NULL)",
        name="auth_grant_session_matches_purpose",
    ),
    CheckConstraint(
        "exchanged_at IS NULL OR (exchanged_at >= created_at AND exchanged_at < expires_at)",
        name="auth_grant_exchanged_at_is_ordered",
    ),
    CheckConstraint(
        "consumed_at IS NULL OR (consumed_at >= created_at AND "
        "(exchanged_at IS NULL OR consumed_at >= exchanged_at))",
        name="auth_grant_consumed_at_is_ordered",
    ),
    CheckConstraint(
        "(revoked_at IS NULL AND revoke_reason IS NULL) OR "
        "(revoked_at IS NOT NULL AND revoke_reason IS NOT NULL AND "
        "length(trim(revoke_reason)) > 0 AND revoked_at >= created_at AND "
        "(exchanged_at IS NULL OR revoked_at >= exchanged_at))",
        name="auth_grant_revoke_reason_matches_revocation",
    ),
    Index(
        "auth_grants_one_live_per_purpose",
        "purpose",
        unique=True,
        postgresql_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
    ),
)


def _grant(row: Row[tuple[object, ...]]) -> AuthGrant:
    value = row._mapping
    return AuthGrant(
        id=value["id"],
        grant_digest=value["grant_digest"],
        purpose=AuthGrantPurpose(value["purpose"]),
        target_principal_id=value["target_principal_id"],
        authorizing_session_id=value["authorizing_session_id"],
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        exchanged_at=value["exchanged_at"],
        consumed_at=value["consumed_at"],
        revoked_at=value["revoked_at"],
        revoke_reason=value["revoke_reason"],
    )


def _digest_of(raw_grant: str) -> str | None:
    try:
        return digest_bytes(parse_opaque_token(raw_grant))
    except AuthSecretError:
        return None


class AuthGrantStore:
    """Issue, inspect, consume, and revoke grants on one caller-owned transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def issue(
        self,
        purpose: AuthGrantPurpose,
        *,
        now: datetime,
        ttl: timedelta = AUTH_GRANT_TTL,
        authorizing_session_id: UUID | None = None,
    ) -> IssuedAuthGrant:
        instant = ensure_utc(now)
        if ttl <= timedelta(0) or ttl > AUTH_GRANT_MAX_TTL:
            raise ValueError("auth grant TTL is positive and at most 15 minutes")
        needs_session = purpose is AuthGrantPurpose.CREDENTIAL_ADMINISTRATION
        if needs_session != (authorizing_session_id is not None):
            raise ValueError("only credential-administration grants bind a session")
        self._connection.execute(
            update(auth_grants)
            .where(
                auth_grants.c.purpose == purpose.value,
                auth_grants.c.consumed_at.is_(None),
                auth_grants.c.revoked_at.is_(None),
                auth_grants.c.expires_at <= instant,
            )
            .values(revoked_at=instant, revoke_reason="expired")
        )
        raw, digest = issue_opaque_token()
        try:
            with self._connection.begin_nested():
                row = self._connection.execute(
                    auth_grants.insert()
                    .values(
                        id=uuid4(),
                        grant_digest=digest,
                        purpose=purpose.value,
                        target_principal_id=LOCAL_OPERATOR_UUID,
                        authorizing_session_id=authorizing_session_id,
                        created_at=instant,
                        expires_at=instant + ttl,
                    )
                    .returning(*auth_grants.c)
                ).one()
        except IntegrityError as error:
            raise ValueError("an unconsumed grant already exists for this purpose") from error
        return IssuedAuthGrant(record=_grant(row), raw_grant=encode_opaque_token(raw))

    def active(self, purpose: AuthGrantPurpose, *, now: datetime) -> AuthGrant | None:
        instant = ensure_utc(now)
        row = self._connection.execute(
            select(*auth_grants.c).where(
                auth_grants.c.purpose == purpose.value,
                auth_grants.c.consumed_at.is_(None),
                auth_grants.c.revoked_at.is_(None),
                auth_grants.c.expires_at > instant,
            )
        ).one_or_none()
        return None if row is None else _grant(row)

    def get_by_raw(
        self, raw_grant: str, purpose: AuthGrantPurpose, *, now: datetime
    ) -> AuthGrant | None:
        _ = ensure_utc(now)
        digest = _digest_of(raw_grant)
        if digest is None:
            return None
        row = self._connection.execute(
            select(*auth_grants.c).where(
                auth_grants.c.grant_digest == digest,
                auth_grants.c.purpose == purpose.value,
            )
        ).one_or_none()
        return None if row is None else _grant(row)

    def exchange(
        self, raw_grant: str, purpose: AuthGrantPurpose, *, now: datetime
    ) -> AuthGrant | None:
        if purpose is AuthGrantPurpose.CREDENTIAL_ADMINISTRATION:
            return None
        instant = ensure_utc(now)
        digest = _digest_of(raw_grant)
        if digest is None:
            return None
        row = self._connection.execute(
            update(auth_grants)
            .where(
                auth_grants.c.grant_digest == digest,
                auth_grants.c.purpose == purpose.value,
                auth_grants.c.target_principal_id == LOCAL_OPERATOR_UUID,
                auth_grants.c.exchanged_at.is_(None),
                auth_grants.c.consumed_at.is_(None),
                auth_grants.c.revoked_at.is_(None),
                auth_grants.c.expires_at > instant,
            )
            .values(exchanged_at=instant)
            .returning(*auth_grants.c)
        ).one_or_none()
        return None if row is None else _grant(row)

    def consume(
        self,
        raw_grant: str,
        purpose: AuthGrantPurpose,
        *,
        now: datetime,
        authorizing_session_id: UUID | None = None,
    ) -> AuthGrant | None:
        instant = ensure_utc(now)
        digest = _digest_of(raw_grant)
        if digest is None:
            return None
        statement = update(auth_grants).where(
            auth_grants.c.grant_digest == digest,
            auth_grants.c.purpose == purpose.value,
            auth_grants.c.target_principal_id == LOCAL_OPERATOR_UUID,
            auth_grants.c.authorizing_session_id.is_not_distinct_from(authorizing_session_id),
            auth_grants.c.consumed_at.is_(None),
            auth_grants.c.revoked_at.is_(None),
            auth_grants.c.expires_at > instant,
        )
        if purpose is AuthGrantPurpose.CREDENTIAL_ADMINISTRATION:
            statement = statement.values(
                exchanged_at=func.coalesce(auth_grants.c.exchanged_at, instant),
                consumed_at=instant,
            )
        else:
            statement = statement.where(auth_grants.c.exchanged_at.is_not(None)).values(
                consumed_at=instant
            )
        row = self._connection.execute(statement.returning(*auth_grants.c)).one_or_none()
        return None if row is None else _grant(row)

    def revoke_active(
        self,
        purpose: AuthGrantPurpose,
        *,
        now: datetime,
        reason: str = "operator_revoked",
    ) -> bool:
        instant = ensure_utc(now)
        if not reason.strip():
            raise ValueError("revoke_reason is present exactly when revoked")
        result = self._connection.execute(
            update(auth_grants)
            .where(
                auth_grants.c.purpose == purpose.value,
                auth_grants.c.consumed_at.is_(None),
                auth_grants.c.revoked_at.is_(None),
            )
            .values(revoked_at=instant, revoke_reason=reason)
        )
        return result.rowcount == 1
