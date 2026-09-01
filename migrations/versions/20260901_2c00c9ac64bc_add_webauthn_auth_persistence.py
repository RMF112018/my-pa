"""Add WebAuthn credential, challenge, recovery, and session persistence.

Revision ID: 2c00c9ac64bc
Revises: 1cda4d536268
Create Date: 2026-09-01

UI-IMP-WP02 durable identity-plane substrate for ADR-011. Additive tables only.
Closed-set purpose CHECK is a frozen literal list (`D-69`). DDL is written out
rather than imported from persistence modules (`D-48`). This revision does not
activate WebAuthn ceremonies or replace the production browser session cookie.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2c00c9ac64bc"
down_revision: str | tuple[str, ...] | None = "1cda4d536268"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE identity.webauthn_credentials (
          id uuid PRIMARY KEY,
          principal_id uuid NOT NULL
            REFERENCES identity.user_accounts(principal_id),
          credential_id bytea NOT NULL UNIQUE,
          public_key bytea NOT NULL,
          sign_count bigint NOT NULL DEFAULT 0,
          user_handle bytea,
          label varchar(128),
          transports varchar(128),
          created_at timestamptz NOT NULL,
          last_used_at timestamptz,
          revoked_at timestamptz,
          revoke_reason varchar(64),
          CONSTRAINT webauthn_credential_sign_count_non_negative CHECK (sign_count >= 0)
        );
        CREATE INDEX webauthn_credentials_by_principal
          ON identity.webauthn_credentials (principal_id);

        CREATE TABLE identity.webauthn_challenges (
          id uuid PRIMARY KEY,
          challenge_digest varchar(64) NOT NULL UNIQUE,
          challenge_bytes bytea NOT NULL,
          purpose varchar(64) NOT NULL,
          principal_id uuid
            REFERENCES identity.user_accounts(principal_id),
          credential_record_id uuid
            REFERENCES identity.webauthn_credentials(id),
          rp_id varchar(253) NOT NULL,
          origin varchar(512) NOT NULL,
          created_at timestamptz NOT NULL,
          expires_at timestamptz NOT NULL,
          consumed_at timestamptz,
          CONSTRAINT webauthn_challenge_expires_after_creation
            CHECK (expires_at > created_at),
          CONSTRAINT webauthn_challenge_purpose_is_known
            CHECK (purpose IN (
              'registration',
              'authentication',
              'credential_administration',
              'recovery',
              'step_up'
            ))
        );
        CREATE INDEX webauthn_challenges_by_principal
          ON identity.webauthn_challenges (principal_id);

        CREATE TABLE identity.recovery_code_sets (
          id uuid PRIMARY KEY,
          principal_id uuid NOT NULL
            REFERENCES identity.user_accounts(principal_id),
          generation integer NOT NULL,
          created_at timestamptz NOT NULL,
          revoked_at timestamptz,
          CONSTRAINT recovery_code_set_generation_positive CHECK (generation >= 1),
          CONSTRAINT recovery_code_sets_principal_generation
            UNIQUE (principal_id, generation)
        );

        CREATE TABLE identity.recovery_codes (
          id uuid PRIMARY KEY,
          set_id uuid NOT NULL
            REFERENCES identity.recovery_code_sets(id),
          code_hash varchar(64) NOT NULL UNIQUE,
          created_at timestamptz NOT NULL,
          consumed_at timestamptz,
          revoked_at timestamptz
        );
        CREATE INDEX recovery_codes_by_set
          ON identity.recovery_codes (set_id);

        CREATE TABLE identity.auth_sessions (
          id uuid PRIMARY KEY,
          token_hash varchar(64) NOT NULL UNIQUE,
          principal_id uuid NOT NULL
            REFERENCES identity.user_accounts(principal_id),
          created_at timestamptz NOT NULL,
          last_seen_at timestamptz NOT NULL,
          idle_expires_at timestamptz NOT NULL,
          absolute_expires_at timestamptz NOT NULL,
          revoked_at timestamptz,
          revoke_reason varchar(64),
          rotated_from_id uuid REFERENCES identity.auth_sessions(id),
          superseded_by_id uuid REFERENCES identity.auth_sessions(id),
          CONSTRAINT auth_session_absolute_after_creation
            CHECK (absolute_expires_at > created_at),
          CONSTRAINT auth_session_idle_after_creation
            CHECK (idle_expires_at > created_at)
        );
        CREATE INDEX auth_sessions_by_principal
          ON identity.auth_sessions (principal_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS identity.auth_sessions_by_principal;
        DROP TABLE IF EXISTS identity.auth_sessions;
        DROP INDEX IF EXISTS identity.recovery_codes_by_set;
        DROP TABLE IF EXISTS identity.recovery_codes;
        DROP TABLE IF EXISTS identity.recovery_code_sets;
        DROP INDEX IF EXISTS identity.webauthn_challenges_by_principal;
        DROP TABLE IF EXISTS identity.webauthn_challenges;
        DROP INDEX IF EXISTS identity.webauthn_credentials_by_principal;
        DROP TABLE IF EXISTS identity.webauthn_credentials;
        """
    )
