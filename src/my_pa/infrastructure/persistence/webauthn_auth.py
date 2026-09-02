"""Durable WebAuthn credential, challenge, recovery, and session stores.

Identity-plane tables on `IDENTITY_METADATA`. Repositories take a Connection.
They are not wired to HTTP; WP03/WP04 own ceremony and cookie cutover.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Row,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.auth_sessions import (
    AUTH_SESSION_ABSOLUTE_TTL,
    AUTH_SESSION_IDLE_TTL,
    AuthSession,
    IssuedAuthSession,
    capped_idle_expiry,
    session_is_authoritative,
)
from my_pa.domain.identity.recovery_codes import (
    IssuedRecoveryCodeSet,
    RecoveryCode,
    RecoveryCodeSet,
    issue_recovery_code,
    normalize_recovery_code,
)
from my_pa.domain.identity.secret_digests import (
    AuthSecretError,
    digest_bytes,
    digest_text,
    encode_opaque_token,
    issue_opaque_token,
    parse_opaque_token,
)
from my_pa.domain.identity.webauthn_credentials import (
    WEBAUTHN_CHALLENGE_TTL,
    IssuedWebAuthnChallenge,
    WebAuthnChallenge,
    WebAuthnChallengePurpose,
    WebAuthnCredential,
)
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA

__all__ = [
    "AuthSessionStore",
    "RecoveryCodeStore",
    "WebAuthnAuthPersistence",
    "WebAuthnChallengeStore",
    "WebAuthnCredentialStore",
    "auth_sessions",
    "recovery_code_sets",
    "recovery_codes",
    "webauthn_challenges",
    "webauthn_credentials",
]

#: Literal CHECK text, not joined from the live enum (`D-69` for the revision;
#: the Table copies the same frozen list so runtime metadata matches DDL).
_CHALLENGE_PURPOSE_CHECK: Final = (
    "purpose IN ('registration', 'authentication', 'credential_administration', "
    "'recovery', 'step_up')"
)

webauthn_credentials = Table(
    "webauthn_credentials",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "principal_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.user_accounts.principal_id"),
        nullable=False,
    ),
    Column("credential_id", LargeBinary, nullable=False, unique=True),
    Column("public_key", LargeBinary, nullable=False),
    Column("sign_count", BigInteger, nullable=False, default=0),
    Column("user_handle", LargeBinary),
    Column("label", String(128)),
    Column("transports", String(128)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_used_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("revoke_reason", String(64)),
    CheckConstraint("sign_count >= 0", name="webauthn_credential_sign_count_non_negative"),
    Index("webauthn_credentials_by_principal", "principal_id"),
)

webauthn_challenges = Table(
    "webauthn_challenges",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("challenge_digest", String(64), nullable=False, unique=True),
    Column("challenge_bytes", LargeBinary, nullable=False),
    Column("purpose", String(64), nullable=False),
    Column(
        "principal_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.user_accounts.principal_id"),
    ),
    Column(
        "credential_record_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.webauthn_credentials.id"),
    ),
    Column("rp_id", String(253), nullable=False),
    Column("origin", String(512), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    CheckConstraint("expires_at > created_at", name="webauthn_challenge_expires_after_creation"),
    CheckConstraint(_CHALLENGE_PURPOSE_CHECK, name="webauthn_challenge_purpose_is_known"),
    Index("webauthn_challenges_by_principal", "principal_id"),
)

recovery_code_sets = Table(
    "recovery_code_sets",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "principal_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.user_accounts.principal_id"),
        nullable=False,
    ),
    Column("generation", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    CheckConstraint("generation >= 1", name="recovery_code_set_generation_positive"),
    UniqueConstraint("principal_id", "generation", name="recovery_code_sets_principal_generation"),
)

recovery_codes = Table(
    "recovery_codes",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "set_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.recovery_code_sets.id"),
        nullable=False,
    ),
    Column("code_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Index("recovery_codes_by_set", "set_id"),
)

auth_sessions = Table(
    "auth_sessions",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column(
        "principal_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.user_accounts.principal_id"),
        nullable=False,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("idle_expires_at", DateTime(timezone=True), nullable=False),
    Column("absolute_expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("revoke_reason", String(64)),
    Column("rotated_from_id", Uuid(as_uuid=True), ForeignKey("identity.auth_sessions.id")),
    Column("superseded_by_id", Uuid(as_uuid=True), ForeignKey("identity.auth_sessions.id")),
    CheckConstraint(
        "absolute_expires_at > created_at", name="auth_session_absolute_after_creation"
    ),
    CheckConstraint("idle_expires_at > created_at", name="auth_session_idle_after_creation"),
    Index("auth_sessions_by_principal", "principal_id"),
)


def _as_bytes(value: object) -> bytes:
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise TypeError("expected bytes")


def _optional_bytes(value: object) -> bytes | None:
    return None if value is None else _as_bytes(value)


def _credential(row: Row[tuple[object, ...]]) -> WebAuthnCredential:
    mapping = row._mapping
    return WebAuthnCredential(
        id=mapping["id"],
        principal_id=mapping["principal_id"],
        credential_id=_as_bytes(mapping["credential_id"]),
        public_key=_as_bytes(mapping["public_key"]),
        sign_count=int(mapping["sign_count"]),
        user_handle=_optional_bytes(mapping["user_handle"]),
        label=mapping["label"],
        transports=mapping["transports"],
        created_at=mapping["created_at"],
        last_used_at=mapping["last_used_at"],
        revoked_at=mapping["revoked_at"],
        revoke_reason=mapping["revoke_reason"],
    )


def _challenge(row: Row[tuple[object, ...]]) -> WebAuthnChallenge:
    mapping = row._mapping
    return WebAuthnChallenge(
        id=mapping["id"],
        challenge_digest=mapping["challenge_digest"],
        challenge_bytes=_as_bytes(mapping["challenge_bytes"]),
        purpose=WebAuthnChallengePurpose(mapping["purpose"]),
        principal_id=mapping["principal_id"],
        credential_record_id=mapping["credential_record_id"],
        rp_id=mapping["rp_id"],
        origin=mapping["origin"],
        created_at=mapping["created_at"],
        expires_at=mapping["expires_at"],
        consumed_at=mapping["consumed_at"],
    )


def _recovery_set(row: Row[tuple[object, ...]]) -> RecoveryCodeSet:
    mapping = row._mapping
    return RecoveryCodeSet(
        id=mapping["id"],
        principal_id=mapping["principal_id"],
        generation=int(mapping["generation"]),
        created_at=mapping["created_at"],
        revoked_at=mapping["revoked_at"],
    )


def _recovery_code(row: Row[tuple[object, ...]]) -> RecoveryCode:
    mapping = row._mapping
    return RecoveryCode(
        id=mapping["id"],
        set_id=mapping["set_id"],
        code_hash=mapping["code_hash"],
        created_at=mapping["created_at"],
        consumed_at=mapping["consumed_at"],
        revoked_at=mapping["revoked_at"],
    )


def _session(row: Row[tuple[object, ...]]) -> AuthSession:
    mapping = row._mapping
    return AuthSession(
        id=mapping["id"],
        token_hash=mapping["token_hash"],
        principal_id=mapping["principal_id"],
        created_at=mapping["created_at"],
        last_seen_at=mapping["last_seen_at"],
        idle_expires_at=mapping["idle_expires_at"],
        absolute_expires_at=mapping["absolute_expires_at"],
        revoked_at=mapping["revoked_at"],
        revoke_reason=mapping["revoke_reason"],
        rotated_from_id=mapping["rotated_from_id"],
        superseded_by_id=mapping["superseded_by_id"],
    )


class WebAuthnCredentialStore:
    """Create, lookup, use, and revoke stored authenticator records."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        principal_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        now: datetime,
        sign_count: int = 0,
        user_handle: bytes | None = None,
        label: str | None = None,
        transports: str | None = None,
    ) -> WebAuthnCredential:
        instant = ensure_utc(now)
        if not credential_id or not public_key:
            raise ValueError("WebAuthn credential_id and public_key are non-empty")
        if sign_count < 0:
            raise ValueError("sign_count is non-negative")
        try:
            with self._connection.begin_nested():
                row = self._connection.execute(
                    webauthn_credentials.insert()
                    .values(
                        id=uuid4(),
                        principal_id=principal_id,
                        credential_id=bytes(credential_id),
                        public_key=bytes(public_key),
                        sign_count=sign_count,
                        user_handle=user_handle,
                        label=label,
                        transports=transports,
                        created_at=instant,
                    )
                    .returning(*webauthn_credentials.c)
                ).one()
        except IntegrityError as error:
            detail = str(getattr(error, "orig", error))
            if "webauthn_credentials_credential_id_key" in detail:
                raise ValueError("WebAuthn credential_id is already registered") from error
            raise
        return _credential(row)

    def get_by_credential_id(
        self, credential_id: bytes, *, include_revoked: bool = False
    ) -> WebAuthnCredential | None:
        if not credential_id:
            return None
        statement = select(*webauthn_credentials.c).where(
            webauthn_credentials.c.credential_id == bytes(credential_id)
        )
        if not include_revoked:
            statement = statement.where(webauthn_credentials.c.revoked_at.is_(None))
        row = self._connection.execute(statement).one_or_none()
        return None if row is None else _credential(row)

    def list_for_principal(
        self, principal_id: UUID, *, include_revoked: bool = False
    ) -> tuple[WebAuthnCredential, ...]:
        statement = (
            select(*webauthn_credentials.c)
            .where(webauthn_credentials.c.principal_id == principal_id)
            .order_by(webauthn_credentials.c.created_at)
        )
        if not include_revoked:
            statement = statement.where(webauthn_credentials.c.revoked_at.is_(None))
        return tuple(_credential(row) for row in self._connection.execute(statement))

    def record_use(
        self, credential_id: bytes, *, sign_count: int, now: datetime
    ) -> WebAuthnCredential | None:
        instant = ensure_utc(now)
        row = self._connection.execute(
            update(webauthn_credentials)
            .where(
                webauthn_credentials.c.credential_id == bytes(credential_id),
                webauthn_credentials.c.revoked_at.is_(None),
            )
            .values(sign_count=sign_count, last_used_at=instant)
            .returning(*webauthn_credentials.c)
        ).one_or_none()
        return None if row is None else _credential(row)

    def revoke(
        self, credential_id: bytes, *, now: datetime, reason: str | None = None
    ) -> WebAuthnCredential | None:
        instant = ensure_utc(now)
        row = self._connection.execute(
            update(webauthn_credentials)
            .where(
                webauthn_credentials.c.credential_id == bytes(credential_id),
                webauthn_credentials.c.revoked_at.is_(None),
            )
            .values(revoked_at=instant, revoke_reason=reason)
            .returning(*webauthn_credentials.c)
        ).one_or_none()
        return None if row is None else _credential(row)


class WebAuthnChallengeStore:
    """Issue and atomically consume purpose-bound challenges."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def issue(
        self,
        *,
        purpose: WebAuthnChallengePurpose,
        rp_id: str,
        origin: str,
        now: datetime,
        principal_id: UUID | None = None,
        credential_record_id: UUID | None = None,
        ttl: timedelta = WEBAUTHN_CHALLENGE_TTL,
        challenge_bytes: bytes | None = None,
    ) -> IssuedWebAuthnChallenge:
        instant = ensure_utc(now)
        expires_at = instant + ttl
        nonce = bytes(challenge_bytes) if challenge_bytes is not None else issue_opaque_token()[0]
        digest = digest_bytes(nonce)
        row = self._connection.execute(
            webauthn_challenges.insert()
            .values(
                id=uuid4(),
                challenge_digest=digest,
                challenge_bytes=nonce,
                purpose=purpose.value,
                principal_id=principal_id,
                credential_record_id=credential_record_id,
                rp_id=rp_id,
                origin=origin,
                created_at=instant,
                expires_at=expires_at,
            )
            .returning(*webauthn_challenges.c)
        ).one()
        record = _challenge(row)
        return IssuedWebAuthnChallenge(record=record, challenge_bytes=nonce)

    def get_valid(
        self,
        challenge_bytes: bytes,
        *,
        purpose: WebAuthnChallengePurpose,
        principal_id: UUID | None,
        now: datetime,
    ) -> WebAuthnChallenge | None:
        instant = ensure_utc(now)
        try:
            digest = digest_bytes(challenge_bytes)
        except AuthSecretError:
            return None
        row = self._connection.execute(
            select(*webauthn_challenges.c).where(
                webauthn_challenges.c.challenge_digest == digest,
                webauthn_challenges.c.consumed_at.is_(None),
                webauthn_challenges.c.expires_at > instant,
                webauthn_challenges.c.purpose == purpose.value,
                webauthn_challenges.c.principal_id.is_not_distinct_from(principal_id),
            )
        ).one_or_none()
        return None if row is None else _challenge(row)

    def consume(
        self,
        challenge_bytes: bytes,
        *,
        purpose: WebAuthnChallengePurpose,
        principal_id: UUID | None,
        now: datetime,
    ) -> WebAuthnChallenge | None:
        instant = ensure_utc(now)
        try:
            digest = digest_bytes(challenge_bytes)
        except AuthSecretError:
            return None
        row = self._connection.execute(
            update(webauthn_challenges)
            .where(
                webauthn_challenges.c.challenge_digest == digest,
                webauthn_challenges.c.consumed_at.is_(None),
                webauthn_challenges.c.expires_at > instant,
                webauthn_challenges.c.purpose == purpose.value,
                webauthn_challenges.c.principal_id.is_not_distinct_from(principal_id),
            )
            .values(consumed_at=instant)
            .returning(*webauthn_challenges.c)
        ).one_or_none()
        return None if row is None else _challenge(row)


class RecoveryCodeStore:
    """Create hashed recovery sets and consume codes once."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_set(
        self,
        *,
        principal_id: UUID,
        now: datetime,
        code_count: int = 10,
        hashed_verifiers: tuple[str, ...] | None = None,
        generation: int | None = None,
    ) -> IssuedRecoveryCodeSet:
        instant = ensure_utc(now)
        if hashed_verifiers is None:
            issued: list[str] = []
            hashes: list[str] = []
            for _ in range(code_count):
                plaintext, digest = issue_recovery_code()
                issued.append(plaintext)
                hashes.append(digest)
        else:
            issued = []
            hashes = list(hashed_verifiers)
            if any(len(item) != 64 for item in hashes):
                raise ValueError("recovery hashes are SHA-256 hex digests")
        if generation is None:
            current = self._connection.execute(
                select(recovery_code_sets.c.generation)
                .where(recovery_code_sets.c.principal_id == principal_id)
                .order_by(recovery_code_sets.c.generation.desc())
                .limit(1)
            ).scalar_one_or_none()
            generation = 1 if current is None else int(current) + 1
        set_row = self._connection.execute(
            recovery_code_sets.insert()
            .values(
                id=uuid4(),
                principal_id=principal_id,
                generation=generation,
                created_at=instant,
            )
            .returning(*recovery_code_sets.c)
        ).one()
        record = _recovery_set(set_row)
        for digest in hashes:
            self._connection.execute(
                recovery_codes.insert().values(
                    id=uuid4(),
                    set_id=record.id,
                    code_hash=digest,
                    created_at=instant,
                )
            )
        return IssuedRecoveryCodeSet(record=record, codes=tuple(issued))

    def consume_code(self, presented: str, *, now: datetime) -> RecoveryCode | None:
        instant = ensure_utc(now)
        try:
            normalized = normalize_recovery_code(presented)
            digest = digest_text(normalized)
        except AuthSecretError:
            return None
        if not normalized:
            return None
        row = self._connection.execute(
            update(recovery_codes)
            .where(
                recovery_codes.c.code_hash == digest,
                recovery_codes.c.consumed_at.is_(None),
                recovery_codes.c.revoked_at.is_(None),
                recovery_codes.c.set_id.in_(
                    select(recovery_code_sets.c.id).where(recovery_code_sets.c.revoked_at.is_(None))
                ),
            )
            .values(consumed_at=instant)
            .returning(*recovery_codes.c)
        ).one_or_none()
        return None if row is None else _recovery_code(row)

    def revoke_set(self, set_id: UUID, *, now: datetime) -> RecoveryCodeSet | None:
        instant = ensure_utc(now)
        row = self._connection.execute(
            update(recovery_code_sets)
            .where(
                recovery_code_sets.c.id == set_id,
                recovery_code_sets.c.revoked_at.is_(None),
            )
            .values(revoked_at=instant)
            .returning(*recovery_code_sets.c)
        ).one_or_none()
        if row is None:
            return None
        self._connection.execute(
            update(recovery_codes)
            .where(
                recovery_codes.c.set_id == set_id,
                recovery_codes.c.revoked_at.is_(None),
            )
            .values(revoked_at=instant)
        )
        return _recovery_set(row)


class AuthSessionStore:
    """Opaque SID lifecycle: create, resolve, touch, rotate, revoke."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        principal_id: UUID,
        now: datetime,
        idle_ttl: timedelta = AUTH_SESSION_IDLE_TTL,
        absolute_ttl: timedelta = AUTH_SESSION_ABSOLUTE_TTL,
        rotated_from_id: UUID | None = None,
    ) -> IssuedAuthSession:
        instant = ensure_utc(now)
        raw, token_hash = issue_opaque_token()
        absolute = instant + absolute_ttl
        idle = capped_idle_expiry(now=instant, idle_ttl=idle_ttl, absolute_expires_at=absolute)
        row = self._connection.execute(
            auth_sessions.insert()
            .values(
                id=uuid4(),
                token_hash=token_hash,
                principal_id=principal_id,
                created_at=instant,
                last_seen_at=instant,
                idle_expires_at=idle,
                absolute_expires_at=absolute,
                rotated_from_id=rotated_from_id,
            )
            .returning(*auth_sessions.c)
        ).one()
        return IssuedAuthSession(record=_session(row), raw_sid=encode_opaque_token(raw))

    def resolve(self, raw_sid: str, *, now: datetime) -> AuthSession | None:
        instant = ensure_utc(now)
        token_hash = self._hash_sid(raw_sid)
        if token_hash is None:
            return None
        row = self._connection.execute(
            select(*auth_sessions.c).where(auth_sessions.c.token_hash == token_hash)
        ).one_or_none()
        if row is None:
            return None
        session = _session(row)
        if not session_is_authoritative(session, now=instant):
            return None
        return session

    def touch(
        self,
        raw_sid: str,
        *,
        now: datetime,
        idle_ttl: timedelta = AUTH_SESSION_IDLE_TTL,
    ) -> AuthSession | None:
        instant = ensure_utc(now)
        current = self.resolve(raw_sid, now=instant)
        if current is None:
            return None
        idle = capped_idle_expiry(
            now=instant, idle_ttl=idle_ttl, absolute_expires_at=current.absolute_expires_at
        )
        row = self._connection.execute(
            update(auth_sessions)
            .where(
                auth_sessions.c.id == current.id,
                auth_sessions.c.revoked_at.is_(None),
                auth_sessions.c.superseded_by_id.is_(None),
                auth_sessions.c.idle_expires_at > instant,
                auth_sessions.c.absolute_expires_at > instant,
            )
            .values(last_seen_at=instant, idle_expires_at=idle)
            .returning(*auth_sessions.c)
        ).one_or_none()
        return None if row is None else _session(row)

    def rotate(
        self,
        raw_sid: str,
        *,
        now: datetime,
        idle_ttl: timedelta = AUTH_SESSION_IDLE_TTL,
        absolute_ttl: timedelta = AUTH_SESSION_ABSOLUTE_TTL,
    ) -> IssuedAuthSession | None:
        """Lock the current row; fail closed if it is already superseded.

        Concurrent rotators of the same SID serialize on `FOR UPDATE`. Exactly
        one successor is created. The loser observes a revoked/superseded row
        and returns `None` — it does not learn the new SID.
        """
        instant = ensure_utc(now)
        token_hash = self._hash_sid(raw_sid)
        if token_hash is None:
            return None
        row = self._connection.execute(
            select(*auth_sessions.c)
            .where(auth_sessions.c.token_hash == token_hash)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        current = _session(row)
        if not session_is_authoritative(current, now=instant):
            return None
        issued = self.create(
            principal_id=current.principal_id,
            now=instant,
            idle_ttl=idle_ttl,
            absolute_ttl=absolute_ttl,
            rotated_from_id=current.id,
        )
        self._connection.execute(
            update(auth_sessions)
            .where(auth_sessions.c.id == current.id)
            .values(
                revoked_at=instant,
                revoke_reason="rotated",
                superseded_by_id=issued.record.id,
            )
        )
        return issued

    def revoke(self, raw_sid: str, *, now: datetime, reason: str | None = "revoked") -> bool:
        instant = ensure_utc(now)
        token_hash = self._hash_sid(raw_sid)
        if token_hash is None:
            return False
        result = self._connection.execute(
            update(auth_sessions)
            .where(
                auth_sessions.c.token_hash == token_hash,
                auth_sessions.c.revoked_at.is_(None),
            )
            .values(revoked_at=instant, revoke_reason=reason)
        )
        return result.rowcount == 1

    def revoke_all_for_principal(
        self, principal_id: UUID, *, now: datetime, reason: str | None = "revoked_all"
    ) -> int:
        instant = ensure_utc(now)
        result = self._connection.execute(
            update(auth_sessions)
            .where(
                auth_sessions.c.principal_id == principal_id,
                auth_sessions.c.revoked_at.is_(None),
            )
            .values(revoked_at=instant, revoke_reason=reason)
        )
        return int(result.rowcount)

    def _hash_sid(self, raw_sid: str) -> str | None:
        try:
            return digest_bytes(parse_opaque_token(raw_sid))
        except AuthSecretError:
            return None


class WebAuthnAuthPersistence:
    """One-connection façade over the four stores for multi-instance tests."""

    def __init__(self, connection: Connection) -> None:
        self.credentials = WebAuthnCredentialStore(connection)
        self.challenges = WebAuthnChallengeStore(connection)
        self.recovery = RecoveryCodeStore(connection)
        self.sessions = AuthSessionStore(connection)
