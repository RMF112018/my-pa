"""Replace the all-history grant uniqueness with an unrevoked partial index.

Revision ID: 7a5c4e9d2b61
Revises: e6a4c2f91b73
Create Date: 2026-09-23

The legacy `one_remote_capability_grant` UNIQUE constraint spans every grant
row, so a revoked grant permanently occupies the canonical identity and a
replacement cannot be granted. This revision narrows uniqueness to unrevoked
rows and treats `purpose IS NULL` as a value (`NULLS NOT DISTINCT`), so revoked
history and one active replacement coexist while a capability-wide grant still
occupies exactly one slot. Existing rows are never deleted, revoked, or
rewritten: duplicate unrevoked identities refuse the upgrade.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "7a5c4e9d2b61"
down_revision: str | None = "e6a4c2f91b73"
branch_labels: str | None = None
depends_on: str | None = None

_IDENTITY_COLUMNS = (
    "remote_client_id, external_scope, capability, capability_version, purpose, resource"
)


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        text(
            "SELECT remote_client_id, external_scope, capability, capability_version, "
            "purpose, resource, count(*) AS n "
            "FROM identity.remote_capability_grants "
            "WHERE revoked_at IS NULL "
            "GROUP BY remote_client_id, external_scope, capability, capability_version, "
            "purpose, resource "
            "HAVING count(*) > 1"
        )
    ).all()
    if duplicates:
        raise RuntimeError(
            "migration refused: duplicate unrevoked remote capability grants require "
            "explicit operator resolution"
        )
    op.execute(
        "ALTER TABLE identity.remote_capability_grants DROP CONSTRAINT one_remote_capability_grant"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_remote_capability_grants_unrevoked_identity "
        "ON identity.remote_capability_grants "
        f"({_IDENTITY_COLUMNS}) NULLS NOT DISTINCT WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        text(
            "SELECT remote_client_id, external_scope, capability, capability_version, "
            "purpose, resource, count(*) AS n "
            "FROM identity.remote_capability_grants "
            "WHERE purpose IS NOT NULL "
            "GROUP BY remote_client_id, external_scope, capability, capability_version, "
            "purpose, resource "
            "HAVING count(*) > 1"
        )
    ).all()
    if duplicates:
        raise RuntimeError(
            "migration refused: duplicate all-history grant identities require "
            "explicit operator resolution"
        )
    op.execute("DROP INDEX identity.uq_remote_capability_grants_unrevoked_identity")
    op.execute(
        "ALTER TABLE identity.remote_capability_grants "
        "ADD CONSTRAINT one_remote_capability_grant "
        f"UNIQUE ({_IDENTITY_COLUMNS})"
    )
