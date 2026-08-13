"""Add the dedicated Principal-bound Apple bridge credential plane.

Revision ID: a9e4c7b2d610
Revises: d7a4c9e2f165
Created: 2026-08-12 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a9e4c7b2d610"
down_revision: str | None = "d7a4c9e2f165"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge.native_apple_bridge_credentials (
          credential_id text PRIMARY KEY,
          principal_id text NOT NULL,
          bridge_id text NOT NULL,
          secret_sha256 text NOT NULL,
          state text NOT NULL,
          created_at timestamptz NOT NULL,
          revoked_at timestamptz,
          CONSTRAINT apple_bridge_credential_stays_in_principal
            FOREIGN KEY (principal_id, bridge_id)
            REFERENCES knowledge.native_bridges (principal_id, bridge_id),
          CONSTRAINT apple_bridge_secret_is_a_sha256_digest
            CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'),
          CONSTRAINT apple_bridge_credential_state_is_known
            CHECK (state IN ('active', 'revoked')),
          CONSTRAINT an_apple_bridge_credential_records_revocation
            CHECK ((state = 'revoked') = (revoked_at IS NOT NULL)),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT bridge_id_is_an_opaque_identifier
            CHECK (bridge_id ~ '^nbrg_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT apple_credential_id_is_an_opaque_identifier
            CHECK (credential_id ~ '^abcred_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT an_apple_credential_identity_is_principal_bound
            UNIQUE (principal_id, credential_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE knowledge.native_apple_read_grants (
          authority_id text PRIMARY KEY,
          principal_id text NOT NULL,
          bridge_id text NOT NULL,
          page_limit integer NOT NULL,
          range_start_unix_milliseconds bigint NOT NULL,
          range_end_unix_milliseconds bigint NOT NULL,
          cursor_private text,
          staged_at timestamptz NOT NULL,
          delivered_at timestamptz,
          delivery_lease_expires_at timestamptz,
          delivered_to_credential_id text,
          CONSTRAINT apple_read_grant_authority_stays_in_principal
            FOREIGN KEY (principal_id, authority_id) REFERENCES
            knowledge.native_admission_authorities (principal_id, authority_id),
          CONSTRAINT apple_read_grant_bridge_stays_in_principal
            FOREIGN KEY (principal_id, bridge_id) REFERENCES
            knowledge.native_bridges (principal_id, bridge_id),
          CONSTRAINT apple_grant_delivery_credential_stays_in_principal
            FOREIGN KEY (principal_id, delivered_to_credential_id) REFERENCES
            knowledge.native_apple_bridge_credentials (principal_id, credential_id),
          CONSTRAINT apple_grant_delivery_lease_is_complete CHECK
            ((delivered_at IS NULL) = (delivery_lease_expires_at IS NULL) AND
             (delivered_at IS NULL) = (delivered_to_credential_id IS NULL)),
          CONSTRAINT apple_read_grant_page_limit_is_bounded CHECK (page_limit BETWEEN 1 AND 100),
          CONSTRAINT apple_read_grant_range_is_ordered CHECK
            (range_start_unix_milliseconds <= range_end_unix_milliseconds),
          CONSTRAINT apple_read_grant_cursor_is_bounded CHECK
            (cursor_private IS NULL OR octet_length(cursor_private) <= 512),
          CONSTRAINT authority_id_is_an_opaque_identifier CHECK
            (authority_id ~ '^nauth_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK
            (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT bridge_id_is_an_opaque_identifier CHECK
            (bridge_id ~ '^nbrg_[A-Za-z0-9]{8,64}$')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE knowledge.native_apple_read_grants")
    op.execute("DROP TABLE knowledge.native_apple_bridge_credentials")
