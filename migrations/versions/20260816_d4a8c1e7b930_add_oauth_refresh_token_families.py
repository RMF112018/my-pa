"""Add OAuth refresh-token families and per-client refresh control.

Revision ID: d4a8c1e7b930
Revises: b7c4e9a2d518
Create Date: 2026-08-16

Additive identity-plane DDL. Existing remote clients, grants, authorization
codes, and access tokens are preserved. `refresh_enabled` defaults false so
pre-existing clients stay on the authorization-code path. Closed-set CHECK
constraints are not added for `revoke_reason` (`D-69`). DDL is written out
rather than imported from persistence modules (`D-48`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d4a8c1e7b930"
down_revision: str | tuple[str, ...] | None = "b7c4e9a2d518"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE identity.remote_clients
          ADD COLUMN refresh_enabled boolean NOT NULL DEFAULT false;

        CREATE TABLE identity.oauth_refresh_token_families (
          id uuid PRIMARY KEY,
          remote_client_id uuid NOT NULL
            REFERENCES identity.remote_clients(id) ON DELETE CASCADE,
          scope varchar(256) NOT NULL,
          resource varchar(512) NOT NULL,
          created_at timestamptz NOT NULL,
          absolute_expires_at timestamptz NOT NULL,
          last_rotated_at timestamptz NOT NULL,
          revoked_at timestamptz,
          revoke_reason varchar(64),
          replay_detected_at timestamptz,
          CONSTRAINT oauth_refresh_family_absolute_after_creation
            CHECK (absolute_expires_at > created_at)
        );
        CREATE INDEX oauth_refresh_families_by_client_expiry
          ON identity.oauth_refresh_token_families (remote_client_id, absolute_expires_at);

        CREATE TABLE identity.oauth_refresh_tokens (
          id uuid PRIMARY KEY,
          family_id uuid NOT NULL
            REFERENCES identity.oauth_refresh_token_families(id) ON DELETE CASCADE,
          token_hash varchar(64) NOT NULL UNIQUE,
          generation integer NOT NULL,
          issued_at timestamptz NOT NULL,
          idle_expires_at timestamptz NOT NULL,
          consumed_at timestamptz,
          revoked_at timestamptz,
          CONSTRAINT oauth_refresh_generation_non_negative CHECK (generation >= 0),
          CONSTRAINT oauth_refresh_idle_after_issue CHECK (idle_expires_at > issued_at),
          CONSTRAINT oauth_refresh_family_generation_unique UNIQUE (family_id, generation)
        );
        CREATE INDEX oauth_refresh_tokens_by_family_idle
          ON identity.oauth_refresh_tokens (family_id, idle_expires_at);

        ALTER TABLE identity.oauth_access_tokens
          ADD COLUMN refresh_family_id uuid
            REFERENCES identity.oauth_refresh_token_families(id) ON DELETE SET NULL;
        CREATE INDEX oauth_access_tokens_by_refresh_family
          ON identity.oauth_access_tokens (refresh_family_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS identity.oauth_access_tokens_by_refresh_family;
        ALTER TABLE identity.oauth_access_tokens
          DROP COLUMN IF EXISTS refresh_family_id;
        DROP INDEX IF EXISTS identity.oauth_refresh_tokens_by_family_idle;
        DROP TABLE IF EXISTS identity.oauth_refresh_tokens;
        DROP INDEX IF EXISTS identity.oauth_refresh_families_by_client_expiry;
        DROP TABLE IF EXISTS identity.oauth_refresh_token_families;
        ALTER TABLE identity.remote_clients
          DROP COLUMN IF EXISTS refresh_enabled;
        """
    )
