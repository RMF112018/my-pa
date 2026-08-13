"""Durable OAuth client-to-Principal bindings and capability grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    String,
    Table,
    Uuid,
    select,
)

from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.user_accounts import IDENTITY_METADATA, user_accounts

__all__ = [
    "REMOTE_IDENTITY_METADATA",
    "RemoteGrantResolution",
    "RemoteIdentityRepository",
    "remote_capability_grants",
    "remote_clients",
    "remote_security_controls",
]

# One canonical registry for every table in the durable identity plane.
REMOTE_IDENTITY_METADATA = IDENTITY_METADATA

remote_clients = Table(
    "remote_clients",
    REMOTE_IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "principal_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.user_accounts.principal_id"),
        nullable=False,
    ),
    Column("oauth_client_id", String(256), nullable=False, unique=True),
    Column("enabled", Boolean, nullable=False),
    Column("writes_enabled", Boolean, nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
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
        tenant_id: str,
        object_id: str,
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
                    user_accounts,
                    remote_clients.c.principal_id == user_accounts.c.principal_id,
                ).join(remote_security_controls, remote_security_controls.c.singleton.is_(True))
            )
            .where(
                remote_clients.c.oauth_client_id == oauth_client_id,
                remote_clients.c.enabled.is_(True),
                remote_clients.c.revoked_at.is_(None),
                (remote_clients.c.expires_at.is_(None) | (remote_clients.c.expires_at > now)),
                user_accounts.c.tid == tenant_id,
                user_accounts.c.oid == object_id,
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
        principal_id: UUID,
        oauth_client_id: str,
        now: datetime,
        expires_at: datetime | None = None,
        writes_enabled: bool = False,
    ) -> UUID:
        """Operator-side registration; the request path never calls this."""
        identifier = uuid4()
        self._connection.execute(
            remote_clients.insert().values(
                id=identifier,
                principal_id=principal_id,
                oauth_client_id=oauth_client_id,
                enabled=True,
                writes_enabled=writes_enabled,
                expires_at=expires_at,
                revoked_at=None,
                created_at=now,
            )
        )
        return identifier

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
