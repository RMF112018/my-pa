"""Normalize account identity and add one-time auth grants.

Revision ID: 4e9a1c7b2d60
Revises: c5b71e0a8d43
Create Date: 2026-09-07

The local account is the fixed LOCAL_OPERATOR_UUID. Existing account and
foreign-key identities are never rewritten. Closed vocabularies and the fixed
UUID are frozen here rather than imported from runtime modules.

`(identity_provider, identity_subject)` replaces `(tid, oid)` as the sole
account uniqueness arbiter: the local account carries no `tid`/`oid` at all,
and two overlapping uniques would let a concurrent first sign-in raise on the
one its `ON CONFLICT` did not name instead of collapsing onto the existing
row. The downgrade restores `(tid, oid)` first, which its own guard has
already proven representable.
"""

from __future__ import annotations

from alembic import op

revision: str = "4e9a1c7b2d60"
down_revision: str | None = "c5b71e0a8d43"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE identity.user_accounts
          ADD COLUMN identity_provider varchar(32),
          ADD COLUMN identity_subject varchar(192);

        UPDATE identity.user_accounts
           SET identity_provider = CASE
                 WHEN tid = '11111111-2222-3333-4444-555555555555'
                   THEN 'synthetic'
                 ELSE 'entra'
               END,
               identity_subject = tid || ':' || oid;

        ALTER TABLE identity.user_accounts
          ALTER COLUMN identity_provider SET NOT NULL,
          ALTER COLUMN identity_subject SET NOT NULL,
          ALTER COLUMN tid DROP NOT NULL,
          ALTER COLUMN oid DROP NOT NULL,
          ADD CONSTRAINT user_account_identity_provider_is_known
            CHECK (identity_provider IN ('entra', 'synthetic', 'local')),
          ADD CONSTRAINT user_account_identity_subject_is_present
            CHECK (length(trim(identity_subject)) > 0),
          ADD CONSTRAINT user_account_provider_claim_shape CHECK (
            (identity_provider IN ('entra', 'synthetic')
              AND tid IS NOT NULL AND length(trim(tid)) > 0
              AND oid IS NOT NULL AND length(trim(oid)) > 0)
            OR
            (identity_provider = 'local' AND tid IS NULL AND oid IS NULL)
          ),
          ADD CONSTRAINT user_account_local_binding_is_fixed CHECK (
            identity_provider <> 'local'
            OR (
              identity_subject = 'local-operator'
              AND principal_id = '24abf5d2-d0c2-5e1c-82f6-e72425e9ed37'::uuid
            )
          ),
          ADD CONSTRAINT one_user_account_per_provider_subject
            UNIQUE (identity_provider, identity_subject);

        ALTER TABLE identity.user_accounts
          DROP CONSTRAINT one_user_account_per_entra_identity;

        CREATE TABLE identity.auth_grants (
          id uuid PRIMARY KEY,
          grant_digest varchar(64) NOT NULL UNIQUE,
          purpose varchar(48) NOT NULL,
          target_principal_id uuid NOT NULL,
          authorizing_session_id uuid REFERENCES identity.auth_sessions(id),
          created_at timestamptz NOT NULL,
          expires_at timestamptz NOT NULL,
          exchanged_at timestamptz,
          consumed_at timestamptz,
          revoked_at timestamptz,
          revoke_reason varchar(64),
          CONSTRAINT auth_grant_digest_is_sha256_hex
            CHECK (grant_digest ~ '^[0-9a-f]{64}$'),
          CONSTRAINT auth_grant_purpose_is_known
            CHECK (purpose IN ('bootstrap', 'operator_recovery', 'credential_administration')),
          CONSTRAINT auth_grant_target_is_local_operator
            CHECK (
              target_principal_id =
                '24abf5d2-d0c2-5e1c-82f6-e72425e9ed37'::uuid
            ),
          CONSTRAINT auth_grant_expiry_is_bounded
            CHECK (expires_at > created_at AND expires_at <= created_at + interval '15 minutes'),
          CONSTRAINT auth_grant_terminal_state_is_exclusive
            CHECK (consumed_at IS NULL OR revoked_at IS NULL),
          CONSTRAINT auth_grant_session_matches_purpose CHECK (
            (purpose = 'credential_administration' AND authorizing_session_id IS NOT NULL)
            OR
            (purpose IN ('bootstrap', 'operator_recovery') AND authorizing_session_id IS NULL)
          ),
          CONSTRAINT auth_grant_exchanged_at_is_ordered CHECK (
            exchanged_at IS NULL
            OR (exchanged_at >= created_at AND exchanged_at < expires_at)
          ),
          CONSTRAINT auth_grant_consumed_at_is_ordered CHECK (
            consumed_at IS NULL
            OR (
              consumed_at >= created_at
              AND (exchanged_at IS NULL OR consumed_at >= exchanged_at)
            )
          ),
          CONSTRAINT auth_grant_revoke_reason_matches_revocation CHECK (
            (revoked_at IS NULL AND revoke_reason IS NULL)
            OR (
              revoked_at IS NOT NULL
              AND revoke_reason IS NOT NULL
              AND length(trim(revoke_reason)) > 0
              AND revoked_at >= created_at
              AND (exchanged_at IS NULL OR revoked_at >= exchanged_at)
            )
          )
        );
        CREATE UNIQUE INDEX auth_grants_one_live_per_purpose
          ON identity.auth_grants (purpose)
          WHERE consumed_at IS NULL AND revoked_at IS NULL;

        ALTER TABLE identity.webauthn_challenges
          DROP CONSTRAINT webauthn_challenge_purpose_is_known,
          ADD COLUMN auth_grant_id uuid UNIQUE REFERENCES identity.auth_grants(id),
          ADD CONSTRAINT webauthn_challenge_purpose_is_known CHECK (purpose IN (
            'registration', 'authentication', 'credential_administration',
            'recovery', 'step_up', 'bootstrap_registration',
            'credential_registration', 'operator_recovery_registration'
          ));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        LOCK TABLE identity.user_accounts, identity.auth_grants,
          identity.webauthn_challenges IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM identity.auth_grants)
          OR EXISTS (
            SELECT 1 FROM identity.webauthn_challenges
             WHERE auth_grant_id IS NOT NULL
                OR purpose IN (
                  'bootstrap_registration', 'credential_registration',
                  'operator_recovery_registration'
                )
          )
          OR EXISTS (
            SELECT 1 FROM identity.user_accounts
             WHERE identity_provider = 'local'
                OR tid IS NULL OR oid IS NULL
                OR length(trim(tid)) = 0
                OR length(trim(oid)) = 0
          )
          THEN
            RAISE EXCEPTION
              'auth remediation history cannot be represented by the previous schema';
          END IF;
        END $$;

        ALTER TABLE identity.webauthn_challenges
          DROP CONSTRAINT webauthn_challenge_purpose_is_known,
          DROP COLUMN auth_grant_id,
          ADD CONSTRAINT webauthn_challenge_purpose_is_known CHECK (purpose IN (
            'registration', 'authentication', 'credential_administration',
            'recovery', 'step_up'
          ));
        DROP INDEX identity.auth_grants_one_live_per_purpose;
        DROP TABLE identity.auth_grants;

        ALTER TABLE identity.user_accounts
          ADD CONSTRAINT one_user_account_per_entra_identity UNIQUE (tid, oid);

        ALTER TABLE identity.user_accounts
          DROP CONSTRAINT one_user_account_per_provider_subject,
          DROP CONSTRAINT user_account_local_binding_is_fixed,
          DROP CONSTRAINT user_account_provider_claim_shape,
          DROP CONSTRAINT user_account_identity_subject_is_present,
          DROP CONSTRAINT user_account_identity_provider_is_known,
          ALTER COLUMN tid SET NOT NULL,
          ALTER COLUMN oid SET NOT NULL,
          DROP COLUMN identity_subject,
          DROP COLUMN identity_provider;
        """
    )
