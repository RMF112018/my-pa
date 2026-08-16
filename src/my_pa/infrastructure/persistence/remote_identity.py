"""Durable OAuth client-to-Principal bindings and capability grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
    update,
)

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA

__all__ = [
    "REFRESH_REVOKE_REASONS",
    "REMOTE_IDENTITY_METADATA",
    "RemoteGrantResolution",
    "RemoteIdentityRepository",
    "oauth_access_tokens",
    "oauth_authorization_codes",
    "oauth_refresh_token_families",
    "oauth_refresh_tokens",
    "remote_capability_grants",
    "remote_clients",
    "remote_security_controls",
]

REMOTE_IDENTITY_METADATA = IDENTITY_METADATA

REFRESH_REVOKE_REASONS: frozenset[str] = frozenset(
    {"replay_detected", "client_revoked", "operator_revoked", "refresh_disabled"}
)

remote_clients = Table(
    "remote_clients",
    REMOTE_IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("principal_id", Uuid(as_uuid=True), nullable=False),
    Column("oauth_client_id", String(256), nullable=False, unique=True),
    Column("client_name", String(256), nullable=False),
    Column("redirect_uris", Text, nullable=False),
    Column("registered_scopes", String(256), nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("writes_enabled", Boolean, nullable=False),
    Column("refresh_enabled", Boolean, nullable=False, default=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"principal_id = '{LOCAL_OPERATOR_UUID.hex}'",
        name="remote_client_is_local_operator",
    ),
)

oauth_authorization_codes = Table(
    "oauth_authorization_codes",
    REMOTE_IDENTITY_METADATA,
    Column("code_hash", String(64), primary_key=True),
    Column(
        "remote_client_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.remote_clients.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("redirect_uri", String(2048), nullable=False),
    Column("scope", String(256), nullable=False),
    Column("resource", String(512), nullable=False),
    Column("code_challenge", String(128), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

oauth_refresh_token_families = Table(
    "oauth_refresh_token_families",
    REMOTE_IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "remote_client_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.remote_clients.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("scope", String(256), nullable=False),
    Column("resource", String(512), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("absolute_expires_at", DateTime(timezone=True), nullable=False),
    Column("last_rotated_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("revoke_reason", String(64)),
    Column("replay_detected_at", DateTime(timezone=True)),
    Index("oauth_refresh_families_by_client_expiry", "remote_client_id", "absolute_expires_at"),
)

oauth_refresh_tokens = Table(
    "oauth_refresh_tokens",
    REMOTE_IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "family_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.oauth_refresh_token_families.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("generation", Integer, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("idle_expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    UniqueConstraint("family_id", "generation", name="oauth_refresh_family_generation_unique"),
    Index("oauth_refresh_tokens_by_family_idle", "family_id", "idle_expires_at"),
)

oauth_access_tokens = Table(
    "oauth_access_tokens",
    REMOTE_IDENTITY_METADATA,
    Column("token_hash", String(64), primary_key=True),
    Column(
        "remote_client_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.remote_clients.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("scope", String(256), nullable=False),
    Column("resource", String(512), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column(
        "refresh_family_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.oauth_refresh_token_families.id", ondelete="SET NULL"),
    ),
    Index("oauth_access_tokens_by_refresh_family", "refresh_family_id"),
)

remote_capability_grants = Table(
    "remote_capability_grants",
    REMOTE_IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "remote_client_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.remote_clients.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("external_scope", String(256), nullable=False),
    Column("capability", String(128), nullable=False),
    Column("capability_version", String(32), nullable=False),
    Column("purpose", String(64)),
    Column("resource", String(512), nullable=False),
    Column("is_write", Boolean, nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

remote_security_controls = Table(
    "remote_security_controls",
    REMOTE_IDENTITY_METADATA,
    Column("singleton", Boolean, primary_key=True),
    Column("remote_enabled", Boolean, nullable=False),
    Column("writes_enabled", Boolean, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True, slots=True)
class RemoteGrantResolution:
    principal_id: UUID
    scopes: frozenset[str]
    capabilities: frozenset[Capability]
    capability_purposes: frozenset[tuple[Capability, Purpose | None]]
    write_allowed: bool


class RemoteIdentityRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def authenticate(
        self,
        *,
        oauth_client_id: str,
        token_scopes: frozenset[str],
        resource: str,
        now: datetime,
    ) -> RemoteGrantResolution | None:
        """Resolve active grants; token scopes intersect and never elevate them."""
        row = self._connection.execute(
            select(
                remote_clients.c.id,
                remote_clients.c.principal_id,
                remote_clients.c.writes_enabled,
                remote_security_controls.c.remote_enabled,
                remote_security_controls.c.writes_enabled.label("global_writes_enabled"),
            )
            .select_from(
                remote_clients.join(
                    remote_security_controls, remote_security_controls.c.singleton.is_(True)
                )
            )
            .where(
                remote_clients.c.oauth_client_id == oauth_client_id,
                remote_clients.c.enabled.is_(True),
                remote_clients.c.revoked_at.is_(None),
                (remote_clients.c.expires_at.is_(None) | (remote_clients.c.expires_at > now)),
                remote_clients.c.principal_id == LOCAL_OPERATOR_UUID,
            )
        ).one_or_none()
        if row is None or not row.remote_enabled:
            return None
        grants = self._connection.execute(
            select(
                remote_capability_grants.c.external_scope,
                remote_capability_grants.c.capability,
                remote_capability_grants.c.purpose,
                remote_capability_grants.c.is_write,
            ).where(
                remote_capability_grants.c.remote_client_id == row.id,
                remote_capability_grants.c.capability_version == "v1",
                remote_capability_grants.c.external_scope.in_(token_scopes),
                remote_capability_grants.c.resource == resource,
                remote_capability_grants.c.revoked_at.is_(None),
                (
                    remote_capability_grants.c.expires_at.is_(None)
                    | (remote_capability_grants.c.expires_at > now)
                ),
            )
        ).all()
        capabilities: set[Capability] = set()
        capability_purposes: set[tuple[Capability, Purpose | None]] = set()
        scopes: set[str] = set()
        writes_allowed = bool(row.writes_enabled and row.global_writes_enabled)
        for grant in grants:
            if grant.is_write and not writes_allowed:
                continue
            try:
                capability = Capability(grant.capability)
            except ValueError:
                continue
            capabilities.add(capability)
            try:
                purpose = None if grant.purpose is None else Purpose(grant.purpose)
            except ValueError:
                continue
            capability_purposes.add((capability, purpose))
            scopes.add(grant.external_scope)
        return RemoteGrantResolution(
            principal_id=row.principal_id,
            scopes=frozenset(scopes),
            capabilities=frozenset(capabilities),
            capability_purposes=frozenset(capability_purposes),
            write_allowed=writes_allowed,
        )

    def register_client(
        self,
        *,
        oauth_client_id: str,
        client_name: str,
        redirect_uris: str,
        registered_scopes: str,
        now: datetime,
        expires_at: datetime | None = None,
        writes_enabled: bool = False,
        refresh_enabled: bool = False,
    ) -> UUID:
        """Operator-side registration; the request path never calls this."""
        identifier = uuid4()
        self._connection.execute(
            remote_clients.insert().values(
                id=identifier,
                principal_id=LOCAL_OPERATOR_UUID,
                oauth_client_id=oauth_client_id,
                client_name=client_name,
                redirect_uris=redirect_uris,
                registered_scopes=registered_scopes,
                enabled=True,
                writes_enabled=writes_enabled,
                refresh_enabled=refresh_enabled,
                expires_at=expires_at,
                revoked_at=None,
                created_at=now,
            )
        )
        return identifier

    def set_client_writes(self, *, oauth_client_id: str, writes_enabled: bool) -> bool:
        """Toggle writes on one unrevoked client. Does not change client identity."""
        result = self._connection.execute(
            update(remote_clients)
            .where(
                remote_clients.c.oauth_client_id == oauth_client_id,
                remote_clients.c.revoked_at.is_(None),
            )
            .values(writes_enabled=writes_enabled)
        )
        return result.rowcount == 1

    def set_client_refresh(self, *, oauth_client_id: str, refresh_enabled: bool) -> bool:
        """Toggle refresh on one unrevoked client. Does not change client identity."""
        result = self._connection.execute(
            update(remote_clients)
            .where(
                remote_clients.c.oauth_client_id == oauth_client_id,
                remote_clients.c.revoked_at.is_(None),
            )
            .values(refresh_enabled=refresh_enabled)
        )
        return result.rowcount == 1

    def revoke_client(self, *, oauth_client_id: str, now: datetime) -> bool:
        """Disable a client, writes, and refresh, and revoke active families."""
        row = self._connection.execute(
            select(remote_clients.c.id).where(remote_clients.c.oauth_client_id == oauth_client_id)
        ).one_or_none()
        if row is None:
            return False
        self._connection.execute(
            update(remote_clients)
            .where(remote_clients.c.id == row.id)
            .values(
                enabled=False,
                writes_enabled=False,
                refresh_enabled=False,
                revoked_at=now,
            )
        )
        families = self._connection.execute(
            select(oauth_refresh_token_families.c.id).where(
                oauth_refresh_token_families.c.remote_client_id == row.id,
                oauth_refresh_token_families.c.revoked_at.is_(None),
            )
        ).scalars()
        for family_id in families:
            self.revoke_refresh_family(family_id=family_id, now=now, reason="client_revoked")
        return True

    def revoke_refresh_family(
        self,
        *,
        family_id: UUID,
        now: datetime,
        reason: str,
        replay: bool = False,
    ) -> None:
        if reason not in REFRESH_REVOKE_REASONS:
            raise ValueError("refresh revoke reason is not recognized")
        values: dict[str, object] = {"revoked_at": now, "revoke_reason": reason}
        if replay:
            values["replay_detected_at"] = now
        self._connection.execute(
            update(oauth_refresh_token_families)
            .where(oauth_refresh_token_families.c.id == family_id)
            .values(**values)
        )
        self._connection.execute(
            update(oauth_refresh_tokens)
            .where(
                oauth_refresh_tokens.c.family_id == family_id,
                oauth_refresh_tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        self._connection.execute(
            update(oauth_access_tokens)
            .where(
                oauth_access_tokens.c.refresh_family_id == family_id,
                oauth_access_tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    def remote_access_enabled(self) -> bool:
        row = self._connection.execute(
            select(remote_security_controls.c.remote_enabled).where(
                remote_security_controls.c.singleton.is_(True)
            )
        ).one_or_none()
        return bool(row is not None and row.remote_enabled)

    def has_active_capability_grant(
        self,
        *,
        remote_client_id: UUID,
        token_scopes: frozenset[str],
        resource: str,
        now: datetime,
    ) -> bool:
        if not token_scopes:
            return False
        count = self._connection.execute(
            select(func.count())
            .select_from(remote_capability_grants)
            .where(
                remote_capability_grants.c.remote_client_id == remote_client_id,
                remote_capability_grants.c.capability_version == "v1",
                remote_capability_grants.c.external_scope.in_(token_scopes),
                remote_capability_grants.c.resource == resource,
                remote_capability_grants.c.revoked_at.is_(None),
                (
                    remote_capability_grants.c.expires_at.is_(None)
                    | (remote_capability_grants.c.expires_at > now)
                ),
            )
        ).scalar_one()
        return int(count) > 0

    def grant(
        self,
        *,
        remote_client_id: UUID,
        external_scope: str,
        capability: Capability,
        now: datetime,
        is_write: bool,
        resource: str,
        expires_at: datetime | None = None,
        purpose: Purpose | None = None,
    ) -> UUID:
        identifier = uuid4()
        self._connection.execute(
            remote_capability_grants.insert().values(
                id=identifier,
                remote_client_id=remote_client_id,
                external_scope=external_scope,
                capability=capability.value,
                capability_version="v1",
                purpose=None if purpose is None else purpose.value,
                resource=resource,
                is_write=is_write,
                expires_at=expires_at,
                revoked_at=None,
                created_at=now,
            )
        )
        return identifier
