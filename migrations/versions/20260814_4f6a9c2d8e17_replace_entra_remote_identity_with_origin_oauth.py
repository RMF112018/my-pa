"""Replace Entra-bound remote identity with origin OAuth and local operator binding."""

from alembic import op

revision: str = "4f6a9c2d8e17"
down_revision: str | None = "e3b7a1d5c942"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM identity.remote_clients) THEN
            RAISE EXCEPTION
              'migration refused: legacy remote clients require explicit operator resolution';
          END IF;
        END $$;
        ALTER TABLE identity.remote_clients
          DROP CONSTRAINT remote_clients_principal_id_fkey;
        ALTER TABLE identity.remote_clients
          ADD COLUMN client_name varchar(256) NOT NULL DEFAULT 'legacy remote client',
          ADD COLUMN redirect_uris text NOT NULL DEFAULT '[]',
          ADD COLUMN registered_scopes varchar(256) NOT NULL DEFAULT '';
        ALTER TABLE identity.remote_clients
          ALTER COLUMN client_name DROP DEFAULT,
          ALTER COLUMN redirect_uris DROP DEFAULT,
          ALTER COLUMN registered_scopes DROP DEFAULT;
        ALTER TABLE identity.remote_clients
          ADD CONSTRAINT remote_client_is_local_operator
          CHECK (principal_id = '24abf5d2-d0c2-5e1c-82f6-e72425e9ed37'::uuid);

        CREATE TABLE identity.oauth_authorization_codes (
          code_hash varchar(64) PRIMARY KEY,
          remote_client_id uuid NOT NULL
            REFERENCES identity.remote_clients(id) ON DELETE CASCADE,
          redirect_uri varchar(2048) NOT NULL,
          scope varchar(256) NOT NULL,
          resource varchar(512) NOT NULL,
          code_challenge varchar(128) NOT NULL,
          expires_at timestamptz NOT NULL,
          consumed_at timestamptz,
          created_at timestamptz NOT NULL,
          CONSTRAINT oauth_code_expiry_is_after_creation CHECK (expires_at > created_at)
        );
        CREATE INDEX active_oauth_codes_by_client
          ON identity.oauth_authorization_codes (remote_client_id, expires_at);

        CREATE TABLE identity.oauth_access_tokens (
          token_hash varchar(64) PRIMARY KEY,
          remote_client_id uuid NOT NULL
            REFERENCES identity.remote_clients(id) ON DELETE CASCADE,
          scope varchar(256) NOT NULL,
          resource varchar(512) NOT NULL,
          expires_at timestamptz NOT NULL,
          revoked_at timestamptz,
          created_at timestamptz NOT NULL,
          CONSTRAINT oauth_token_expiry_is_after_creation CHECK (expires_at > created_at)
        );
        CREATE INDEX active_oauth_tokens_by_client
          ON identity.oauth_access_tokens (remote_client_id, expires_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM identity.remote_clients rc
            LEFT JOIN identity.user_accounts ua ON ua.principal_id = rc.principal_id
            WHERE ua.principal_id IS NULL
          ) THEN
            RAISE EXCEPTION 'downgrade refused: remote client has no legacy user account';
          END IF;
        END $$;
        DROP INDEX identity.active_oauth_tokens_by_client;
        DROP TABLE identity.oauth_access_tokens;
        DROP INDEX identity.active_oauth_codes_by_client;
        DROP TABLE identity.oauth_authorization_codes;
        ALTER TABLE identity.remote_clients
          DROP CONSTRAINT remote_client_is_local_operator,
          DROP COLUMN registered_scopes,
          DROP COLUMN redirect_uris,
          DROP COLUMN client_name;
        ALTER TABLE identity.remote_clients
          ADD CONSTRAINT remote_clients_principal_id_fkey
          FOREIGN KEY (principal_id) REFERENCES identity.user_accounts(principal_id);
        """
    )
