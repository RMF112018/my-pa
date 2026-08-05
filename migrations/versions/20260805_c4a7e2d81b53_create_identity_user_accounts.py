"""Create the WP-01 (R0A) identity plane: user accounts and scope grants.

Revision ID: c4a7e2d81b53
Revises: 9d5e2f7b4c61
Create Date: 2026-08-05

The SQL is frozen in this revision rather than derived from live domain enums,
for the reason `7f2a9d6c4e18` states: an old revision must not change meaning
when the runtime declarations evolve.

**Why a new `identity` schema.** The `knowledge` schema is the application's
domain plane; the legacy schemas are read-only history; `migration_control` is
a one-run ledger. The Principal registry is a fourth authority: it decides who
a request *is* before any domain table is legible, and every user-scoped table
from this revision onward will carry a `principal_id` that resolves here. A
plane with a different writer (the authentication boundary), a different
lifetime (accounts outlive any single domain record), and a different threat
model (it is what cross-Principal isolation isolates *by*) does not share a
schema with what it guards.

**`principal_id` is minted, not derived.** `(tid, oid)` is the Entra identity
and is unique; `principal_id` is an opaque UUID issued at first sight so that
nothing downstream ever needs to parse, log, or reconstruct an Entra claim to
name a partition. `upn` and `display_name` are mutable observations and carry
no uniqueness — a rename must never fork an account (v4.0 package, document 09
section on `UserAccount`).

**Scope grants reference `principal_id`, not `id`.** Every other table in the
product partitions on `principal_id`, so the grant table exercises the same
foreign key every future partition will use, and the `UNIQUE` on
`user_accounts.principal_id` is what makes that reference legal.
"""

from __future__ import annotations

from alembic import op

revision: str = "c4a7e2d81b53"
down_revision: str | None = "9d5e2f7b4c61"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS "identity";
        CREATE TABLE identity.user_accounts (
          id uuid PRIMARY KEY,
          principal_id uuid NOT NULL,
          tid varchar(64) NOT NULL CHECK (length(trim(tid)) > 0),
          oid varchar(64) NOT NULL CHECK (length(trim(oid)) > 0),
          upn varchar(320),
          display_name varchar(256),
          first_seen_at timestamptz NOT NULL,
          last_authenticated_at timestamptz,
          consent_state varchar(32) NOT NULL DEFAULT 'pending'
            CHECK (consent_state IN ('pending', 'granted', 'revoked')),
          lifecycle_state varchar(32) NOT NULL DEFAULT 'invited'
            CHECK (lifecycle_state IN (
              'invited', 'active', 'consent_required',
              'scope_insufficient', 'suspended', 'deprovisioned'
            )),
          home_tenant_verified boolean NOT NULL DEFAULT false,
          CONSTRAINT one_principal_id_per_user_account UNIQUE (principal_id),
          CONSTRAINT one_user_account_per_entra_identity UNIQUE (tid, oid)
        );
        CREATE TABLE identity.principal_scope_grants (
          id uuid PRIMARY KEY,
          principal_id uuid NOT NULL
            REFERENCES identity.user_accounts(principal_id),
          scope varchar(256) NOT NULL CHECK (length(trim(scope)) > 0),
          consent_type varchar(16)
            CHECK (consent_type IN ('admin', 'user')),
          consented_at timestamptz,
          revoked_at timestamptz
        );
        CREATE INDEX principal_scope_grants_by_principal
          ON identity.principal_scope_grants (principal_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE identity.principal_scope_grants;
        DROP TABLE identity.user_accounts;
        DROP SCHEMA "identity" RESTRICT;
        """
    )
