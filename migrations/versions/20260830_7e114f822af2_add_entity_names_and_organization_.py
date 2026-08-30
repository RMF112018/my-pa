"""Add entity_names and entity_organization_profiles (RI-ENT-WP-02).

Revision ID: 7e114f822af2
Revises: b727e870d45e
Create Date: 2026-08-30

RI-ENT-WP-02 (typed names and organization profile). Closes ENTITY-SCHEMA-001
("no typed legal/brand/DBA/operating-name semantics") and unblocks
ENTITY-RESOLUTION-001. Authorized per `AUTH-RI-ENT-20260830-OPERATOR-001`
(untracked, repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record, finding IDs, and disposition rulings.

Two brand-new, purely additive tables. Nothing existing is altered, no legacy
data is backfilled, and there is nothing here for a migration to guess about:
both tables are empty at every environment this revision reaches.

**`entity_names`** is the typed-name successor to `entity_aliases`
(`b7f4d1a92c36`/`2fe4e13fb449`), whose shape it mirrors column-for-column plus
one addition (`is_preferred`). `entity_aliases` is preserved exactly as-is —
this revision does not touch it, consolidate it, or deprecate it (RULING 3 /
audit decision R.1 remains open for a later work package). See
`my_pa.domain.relationship.entity.EntityName` for the full design rationale,
including why a historical juristic entity is its own `entities` row rather
than a row here, and the merge/split deferral to RI-ENT-WP-06.

**`entity_organization_profiles`** is a one-row-per-entity classification
(`entity_id` is both primary key and the foreign key to `entities`), not a
temporal record family — an organization has one current
`organization_kind_code`/`legal_identity_status_code`, not a history of them,
so there is no `state`/`effective_from`/`superseded_by_*` here to guess a
value for. See `my_pa.domain.relationship.entity.EntityOrganizationProfile`.

`legal_identity_status_code` is a closed vocabulary
(verified/best_supported/unresolved/awaiting_confirmation), not a numeric
confidence: `tests/architecture/test_relationship_scoring_surface_is_denied`
denies `confidence|certainty|probability|likelihood|propensity` on every table
of the generalized entity plane, and this revision does not seek or need an
exemption from that guard.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`); the
closed-set literals are frozen at this revision.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "7e114f822af2"
down_revision: str | None = "b727e870d45e"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_NAME_TYPE_VALUES: Final = (
    "'acronym', 'alias', 'brand', 'dba', 'display', 'document_reference', "
    "'historical_name', 'legal', 'operating'"
)

_ORGANIZATION_KIND_VALUES: Final = (
    "'brand_or_operating_unit', 'company', 'government_authority', "
    "'llc_or_spv', 'nonprofit', 'other_or_unresolved', 'professional_practice', "
    "'public_agency', 'utility'"
)

_LEGAL_IDENTITY_STATUS_VALUES: Final = (
    "'awaiting_confirmation', 'best_supported', 'unresolved', 'verified'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_names (
          entity_name_id text PRIMARY KEY,
          entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          name_type_code text NOT NULL,
          normalized_value text NOT NULL,
          display_value text NOT NULL,
          is_preferred boolean NOT NULL DEFAULT false,
          effective_from timestamptz,
          effective_to timestamptz,
          principal_id text NOT NULL,
          state text NOT NULL DEFAULT 'active',
          version integer NOT NULL DEFAULT 1,
          updated_at timestamptz,
          retired_at timestamptz,
          superseded_by_entity_name_id text
            REFERENCES {SCHEMA}.entity_names(entity_name_id),
          CONSTRAINT entity_name_id_is_an_opaque_identifier
            CHECK (entity_name_id ~ '^enam_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_entity_name_type_is_known
            CHECK (name_type_code IN ({_NAME_TYPE_VALUES})),
          CONSTRAINT an_entity_name_state_is_known
            CHECK (state IN ('active', 'retired', 'superseded')),
          CONSTRAINT an_entity_name_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT an_entity_name_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          CONSTRAINT an_entity_name_names_a_successor_only_when_superseded
            CHECK (superseded_by_entity_name_id IS NULL OR state = 'superseded'),
          CONSTRAINT an_entity_name_does_not_supersede_itself
            CHECK (
              superseded_by_entity_name_id IS NULL
              OR superseded_by_entity_name_id <> entity_name_id
            ),
          CONSTRAINT an_entity_name_normalized_value_is_not_blank
            CHECK (length(trim(normalized_value)) > 0),
          CONSTRAINT an_entity_name_display_value_is_not_blank
            CHECK (length(trim(display_value)) > 0),
          CONSTRAINT an_entity_name_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          CONSTRAINT an_entity_name_is_identified_within_its_principal
            UNIQUE (entity_name_id, principal_id)
        );
        """
    )
    # Composite foreign keys, added after the table exists so both sides of
    # each reference are present: entity_names(entity_id, principal_id) ->
    # entities(entity_id, principal_id), and the self-referencing
    # (superseded_by_entity_name_id, principal_id) -> entity_names(...).
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_names
          ADD CONSTRAINT an_entity_name_names_an_entity_of_its_principal
          FOREIGN KEY (entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_names
          ADD CONSTRAINT an_entity_name_is_superseded_within_its_principal
          FOREIGN KEY (superseded_by_entity_name_id, principal_id)
          REFERENCES {SCHEMA}.entity_names (entity_name_id, principal_id);
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_names_by_principal
          ON {SCHEMA}.entity_names (principal_id);
        CREATE INDEX entity_names_by_normalized_value
          ON {SCHEMA}.entity_names (normalized_value);
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX an_active_entity_name_is_unique_per_entity_and_type
          ON {SCHEMA}.entity_names (principal_id, entity_id, name_type_code, normalized_value)
          WHERE state = 'active';
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX an_active_entity_name_has_one_preferred_per_type
          ON {SCHEMA}.entity_names (principal_id, entity_id, name_type_code)
          WHERE state = 'active' AND is_preferred = true;
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_organization_profiles (
          entity_id text PRIMARY KEY
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          principal_id text NOT NULL,
          organization_kind_code text NOT NULL,
          legal_identity_status_code text NOT NULL DEFAULT 'unresolved',
          jurisdiction_code text,
          registration_identifier text,
          version integer NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT entity_id_is_an_opaque_identifier
            CHECK (entity_id ~ '^ent_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_organization_kind_is_known
            CHECK (organization_kind_code IN ({_ORGANIZATION_KIND_VALUES})),
          CONSTRAINT a_legal_identity_status_is_known
            CHECK (legal_identity_status_code IN ({_LEGAL_IDENTITY_STATUS_VALUES})),
          CONSTRAINT an_organization_profile_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT an_org_profile_jurisdiction_code_is_not_blank
            CHECK (jurisdiction_code IS NULL OR length(trim(jurisdiction_code)) > 0),
          CONSTRAINT an_org_profile_registration_id_is_not_blank
            CHECK (
              registration_identifier IS NULL
              OR length(trim(registration_identifier)) > 0
            )
        );
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_organization_profiles
          ADD CONSTRAINT an_organization_profile_extends_an_entity_of_its_principal
          FOREIGN KEY (entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_organization_profiles_by_principal
          ON {SCHEMA}.entity_organization_profiles (principal_id);
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_organization_profiles;")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_names;")
