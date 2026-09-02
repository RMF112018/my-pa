"""Persisting the Principal registry: resolve-or-create and scope grants.

The registry's one non-negotiable behavior is that `(tid, oid)` maps to
exactly one `principal_id`, forever, under concurrency and retry. That is a
database fact, not an application check: the insert is attempted first with
`ON CONFLICT (tid, oid) DO UPDATE`, so two concurrent first sign-ins of the
same person cannot both read "absent" and both mint a Principal — the second
insert collapses onto the first row and both callers observe the same
`principal_id`. Check-then-insert would reintroduce exactly the window the
constraint exists to close (the same argument `enrollment.py` records for
idempotency keys).

What the conflict arm may touch is deliberately narrow: `upn`,
`display_name`, `last_authenticated_at`, and lifecycle re-activation. It may
never touch `principal_id`, `tid`, `oid`, or `first_seen_at` — identity and
first sight are written once.

Reads of per-Principal records (`scope_grants`) go through
`principal_scoped`, so this module is also the first consumer of the
fail-closed guard: no context, no rows, no exception to that.

The tables are declared here on their own `MetaData` rather than in
`tables.py`: the `identity` plane has a different writer (the authentication
boundary) and a different lifetime than the `knowledge` schema, and the
frozen migration `c4a7e2d81b53` names these two tables explicitly for the
same reason every other revision names its own.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    MetaData,
    Row,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.identity.user_account import (
    ConsentState,
    EntraTokenClaims,
    PrincipalScopeGrant,
    UserAccount,
    UserLifecycleState,
)
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    principal_scoped,
    require_principal_context,
)

__all__ = ["IDENTITY_METADATA", "UserAccountRepository", "principal_scope_grants", "user_accounts"]

IDENTITY_METADATA = MetaData(schema="identity")

user_accounts = Table(
    "user_accounts",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("principal_id", Uuid(as_uuid=True), nullable=False, unique=True),
    Column("tid", String(64), nullable=False),
    Column("oid", String(64), nullable=False),
    Column("upn", String(320)),
    Column("display_name", String(256)),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_authenticated_at", DateTime(timezone=True)),
    Column("consent_state", String(32), nullable=False, default=ConsentState.PENDING.value),
    Column("lifecycle_state", String(32), nullable=False, default=UserLifecycleState.INVITED.value),
    Column("home_tenant_verified", Boolean, nullable=False, default=False),
    UniqueConstraint("tid", "oid", name="one_user_account_per_entra_identity"),
)

principal_scope_grants = Table(
    "principal_scope_grants",
    IDENTITY_METADATA,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "principal_id",
        Uuid(as_uuid=True),
        ForeignKey("identity.user_accounts.principal_id"),
        nullable=False,
    ),
    Column("scope", String(256), nullable=False),
    Column("consent_type", String(16)),
    Column("consented_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)


def _account(row: Row[tuple]) -> UserAccount:  # type: ignore[type-arg]
    return UserAccount(
        id=row.id,
        principal_id=row.principal_id,
        tid=row.tid,
        oid=row.oid,
        upn=row.upn,
        display_name=row.display_name,
        first_seen_at=row.first_seen_at,
        last_authenticated_at=row.last_authenticated_at,
        consent_state=ConsentState(row.consent_state),
        lifecycle_state=UserLifecycleState(row.lifecycle_state),
        home_tenant_verified=row.home_tenant_verified,
    )


def _grant(row: Row[tuple]) -> PrincipalScopeGrant:  # type: ignore[type-arg]
    return PrincipalScopeGrant(
        id=row.id,
        principal_id=row.principal_id,
        scope=row.scope,
        consent_type=row.consent_type,
        consented_at=row.consented_at,
        revoked_at=row.revoked_at,
    )


class UserAccountRepository:
    """The Principal registry over one connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def resolve_or_create(self, claims: EntraTokenClaims, *, now: datetime) -> UserAccount:
        """Return the one account for `(tid, oid)`, creating it on first sight.

        Idempotent: a retry or a concurrent duplicate lands on the same row
        and the same `principal_id`. The conflict arm refreshes the mutable
        observations and the authentication timestamp only.
        """
        insert = pg_insert(user_accounts).values(
            id=uuid4(),
            principal_id=uuid4(),
            tid=claims.tid,
            oid=claims.oid,
            upn=claims.upn,
            display_name=claims.display_name,
            first_seen_at=now,
            last_authenticated_at=now,
            consent_state=ConsentState.PENDING.value,
            lifecycle_state=UserLifecycleState.ACTIVE.value,
            home_tenant_verified=True,
        )
        resolved = insert.on_conflict_do_update(
            constraint="one_user_account_per_entra_identity",
            set_={
                "upn": insert.excluded.upn,
                "display_name": insert.excluded.display_name,
                "last_authenticated_at": insert.excluded.last_authenticated_at,
                "lifecycle_state": UserLifecycleState.ACTIVE.value,
            },
        ).returning(*user_accounts.c)
        row = self._connection.execute(resolved).one()
        return _account(row)

    def get(self, principal_id: UUID) -> UserAccount | None:
        """The account for this durable UUID, or `None`."""
        row = self._connection.execute(
            select(*user_accounts.c).where(user_accounts.c.principal_id == principal_id)
        ).one_or_none()
        return None if row is None else _account(row)

    def account_for(self, context: PrincipalContext | None) -> UserAccount | None:
        """The context's own account, or `None`. Fails closed without context."""
        statement = principal_scoped(select(*user_accounts.c), user_accounts, context)
        row = self._connection.execute(statement).one_or_none()
        return None if row is None else _account(row)

    def record_scope_grant(
        self,
        context: PrincipalContext | None,
        *,
        scope: str,
        consent_type: str | None,
        now: datetime,
    ) -> PrincipalScopeGrant:
        """Record one consented delegated scope for the context's Principal."""
        resolved = require_principal_context(context)
        row = self._connection.execute(
            pg_insert(principal_scope_grants)
            .values(
                id=uuid4(),
                principal_id=resolved.principal_id,
                scope=scope,
                consent_type=consent_type,
                consented_at=now,
                revoked_at=None,
            )
            .returning(*principal_scope_grants.c)
        ).one()
        return _grant(row)

    def scope_grants(self, context: PrincipalContext | None) -> tuple[PrincipalScopeGrant, ...]:
        """The context's own grants, and never anyone else's."""
        statement = principal_scoped(
            select(*principal_scope_grants.c).order_by(principal_scope_grants.c.scope),
            principal_scope_grants,
            context,
        )
        return tuple(_grant(row) for row in self._connection.execute(statement))
