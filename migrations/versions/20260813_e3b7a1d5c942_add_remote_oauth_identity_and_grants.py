"""Add durable remote OAuth client bindings, grants, and kill switches."""

from alembic import op

revision: str = "e3b7a1d5c942"
down_revision: str | None = "a9e4c7b2d610"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE identity.remote_clients (
          id uuid PRIMARY KEY,
          principal_id uuid NOT NULL REFERENCES identity.user_accounts(principal_id),
          oauth_client_id varchar(256) NOT NULL UNIQUE,
          enabled boolean NOT NULL DEFAULT false,
          writes_enabled boolean NOT NULL DEFAULT false,
          expires_at timestamptz,
          revoked_at timestamptz,
          created_at timestamptz NOT NULL,
          CONSTRAINT remote_client_expiry_is_after_creation
            CHECK (expires_at IS NULL OR expires_at > created_at),
          CONSTRAINT disabled_or_revoked_remote_client_cannot_write
            CHECK ((enabled AND revoked_at IS NULL) OR NOT writes_enabled)
        );
        CREATE INDEX remote_clients_by_principal
          ON identity.remote_clients (principal_id, created_at, id);

        CREATE TABLE identity.remote_capability_grants (
          id uuid PRIMARY KEY,
          remote_client_id uuid NOT NULL
            REFERENCES identity.remote_clients(id) ON DELETE CASCADE,
          external_scope varchar(256) NOT NULL,
          capability varchar(128) NOT NULL,
          capability_version varchar(32) NOT NULL,
          purpose varchar(64),
          resource varchar(512) NOT NULL,
          is_write boolean NOT NULL DEFAULT false,
          expires_at timestamptz,
          revoked_at timestamptz,
          created_at timestamptz NOT NULL,
          CONSTRAINT remote_grant_expiry_is_after_creation
            CHECK (expires_at IS NULL OR expires_at > created_at),
          CONSTRAINT one_remote_capability_grant
            UNIQUE (remote_client_id, external_scope, capability, capability_version,
                    purpose, resource)
        );
        CREATE INDEX active_remote_grants_by_client
          ON identity.remote_capability_grants
          (remote_client_id, external_scope, capability_version);

        CREATE TABLE identity.remote_security_controls (
          singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
          remote_enabled boolean NOT NULL DEFAULT false,
          writes_enabled boolean NOT NULL DEFAULT false,
          updated_at timestamptz NOT NULL
        );
        INSERT INTO identity.remote_security_controls
          (singleton, remote_enabled, writes_enabled, updated_at)
        VALUES (true, false, false, now());
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE identity.remote_security_controls")
    op.execute("DROP INDEX identity.active_remote_grants_by_client")
    op.execute("DROP TABLE identity.remote_capability_grants")
    op.execute("DROP INDEX identity.remote_clients_by_principal")
    op.execute("DROP TABLE identity.remote_clients")
