"""Add entity_addresses and entity_communication_methods (RI-ENT-WP-03).

Revision ID: 441b071bf37b
Revises: 7e114f822af2
Create Date: 2026-08-30

RI-ENT-WP-03 (address and communication record families). Closes
`ENTITY-SCHEMA-002` ("no normalized entity-address family") and
`ENTITY-SCHEMA-003` ("no typed phones/domains/websites"). Authorized per
`AUTH-RI-ENT-20260830-OPERATOR-001` (untracked, repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record, finding IDs, and disposition rulings.

Two brand-new, purely additive tables. Nothing existing is altered, no legacy
data is backfilled, and there is nothing here for a migration to guess about:
both tables are empty at every environment this revision reaches.

**`entity_addresses`** mirrors `entity_names`'s shape column-for-column
(composite FK to `entities`, principal-scoped self-referencing supersession,
three-state lifecycle) plus the address-specific structured/optional fields
(`line1`/`line2`/`city`/`region`/`postal_code`/`country`) and the
`raw_value`/`normalized_address_value` pair. Its active uniqueness is keyed on
`(principal_id, entity_id, address_type_code, normalized_address_value)` --
deliberately including `address_type_code` so the *same* street address may
recur for one entity under a *different* address role (a legal-principal
address and a project address are often literally the same building) without
that being treated as a duplicate; only the same (entity, type) pair recorded
twice actively is refused. The full reasoning, including the RULING 3 "known
structure only, never inferred from `raw_value`" boundary, lives in
`my_pa.domain.relationship.entity.EntityAddress`'s docstring, not repeated
here.

**`entity_communication_methods`** mirrors the same `entity_names` shape for
a contact channel (email/phone/domain/website), with an independent
`usage_context_code` axis and its own `CommunicationVerificationStatusCode`
vocabulary -- a deliberately separate enum from `LegalIdentityStatusCode` even
though the four members read the same, because the two describe unrelated
dimensions (a contact channel's verification versus an organization's legal
identity) and sharing one vocabulary would couple two unrelated migrations'
widenings. `linked_external_identifier_id` optionally cross-references
`entity_external_identifiers` -- the table that remains the sole authority for
identity resolution -- without merging the two concepts; a `CHECK`
(`linked_external_identifier_id IS NULL OR method_type_code = 'email'`)
confines that cross-reference to email rows only, which is what stops
phone/domain/website values from ever being written into the
external-identifier namespace through this column. Full reasoning, including
why the type is stated rather than inferred (RULING 3), lives in
`my_pa.domain.relationship.entity.EntityCommunicationMethod`'s docstring.

`legal_identity_status_code`'s sibling vocabulary here,
`verification_status_code`, is likewise a closed vocabulary, not a numeric
confidence: `tests/architecture/test_relationship_scoring_surface_is_denied`
denies `confidence|certainty|probability|likelihood|propensity` on every
table of the generalized entity plane, and this revision does not seek or
need an exemption from that guard.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`); the
closed-set literals are frozen at this revision.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "441b071bf37b"
down_revision: str | None = "7e114f822af2"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_ADDRESS_TYPE_VALUES: Final = (
    "'business', 'city_hall', 'headquarters', 'known_other', 'legal_principal', "
    "'mailing', 'office', 'project', 'regional_office'"
)

_COMMUNICATION_METHOD_TYPE_VALUES: Final = "'domain', 'email', 'phone', 'website'"

_COMMUNICATION_USAGE_CONTEXT_VALUES: Final = (
    "'corporate', 'generic', 'office', 'other', 'personal', 'project', 'project_sales'"
)

_COMMUNICATION_VERIFICATION_STATUS_VALUES: Final = (
    "'awaiting_confirmation', 'best_supported', 'unresolved', 'verified'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_addresses (
          entity_address_id text PRIMARY KEY,
          entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          principal_id text NOT NULL,
          address_type_code text NOT NULL,
          line1 text,
          line2 text,
          city text,
          region text,
          postal_code text,
          country text,
          raw_value text NOT NULL,
          normalized_address_value text NOT NULL,
          label text,
          is_preferred boolean NOT NULL DEFAULT false,
          effective_from timestamptz,
          effective_to timestamptz,
          state text NOT NULL DEFAULT 'active',
          version integer NOT NULL DEFAULT 1,
          updated_at timestamptz,
          retired_at timestamptz,
          superseded_by_entity_address_id text
            REFERENCES {SCHEMA}.entity_addresses(entity_address_id),
          CONSTRAINT entity_address_id_is_an_opaque_identifier
            CHECK (entity_address_id ~ '^eadr_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_entity_address_type_is_known
            CHECK (address_type_code IN ({_ADDRESS_TYPE_VALUES})),
          CONSTRAINT an_entity_address_state_is_known
            CHECK (state IN ('active', 'retired', 'superseded')),
          CONSTRAINT an_entity_address_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT an_entity_address_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          CONSTRAINT an_entity_address_names_a_successor_only_when_superseded
            CHECK (superseded_by_entity_address_id IS NULL OR state = 'superseded'),
          CONSTRAINT an_entity_address_does_not_supersede_itself
            CHECK (
              superseded_by_entity_address_id IS NULL
              OR superseded_by_entity_address_id <> entity_address_id
            ),
          CONSTRAINT an_entity_address_raw_value_is_not_blank
            CHECK (length(trim(raw_value)) > 0),
          CONSTRAINT an_entity_address_normalized_value_is_not_blank
            CHECK (length(trim(normalized_address_value)) > 0),
          CONSTRAINT an_entity_address_line1_is_not_blank
            CHECK (line1 IS NULL OR length(trim(line1)) > 0),
          CONSTRAINT an_entity_address_line2_is_not_blank
            CHECK (line2 IS NULL OR length(trim(line2)) > 0),
          CONSTRAINT an_entity_address_city_is_not_blank
            CHECK (city IS NULL OR length(trim(city)) > 0),
          CONSTRAINT an_entity_address_region_is_not_blank
            CHECK (region IS NULL OR length(trim(region)) > 0),
          CONSTRAINT an_entity_address_postal_code_is_not_blank
            CHECK (postal_code IS NULL OR length(trim(postal_code)) > 0),
          CONSTRAINT an_entity_address_country_is_not_blank
            CHECK (country IS NULL OR length(trim(country)) > 0),
          CONSTRAINT an_entity_address_label_is_not_blank
            CHECK (label IS NULL OR length(trim(label)) > 0),
          CONSTRAINT an_entity_address_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          CONSTRAINT an_entity_address_is_identified_within_its_principal
            UNIQUE (entity_address_id, principal_id)
        );
        """
    )
    # Composite foreign keys, added after the table exists so both sides of
    # each reference are present: entity_addresses(entity_id, principal_id)
    # -> entities(entity_id, principal_id), and the self-referencing
    # (superseded_by_entity_address_id, principal_id) -> entity_addresses(...).
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_addresses
          ADD CONSTRAINT an_entity_address_names_an_entity_of_its_principal
          FOREIGN KEY (entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_addresses
          ADD CONSTRAINT an_entity_address_is_superseded_within_its_principal
          FOREIGN KEY (superseded_by_entity_address_id, principal_id)
          REFERENCES {SCHEMA}.entity_addresses (entity_address_id, principal_id);
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_addresses_by_principal
          ON {SCHEMA}.entity_addresses (principal_id);
        -- The "normalized geography" index: every reader that matches
        -- addresses by value, across entities and types, scans this rather
        -- than the table.
        CREATE INDEX entity_addresses_by_normalized_address_value
          ON {SCHEMA}.entity_addresses (normalized_address_value);
        -- The (entity, type, current state) index: the shape almost every
        -- read of this table takes ("this entity's active project
        -- addresses" and similar).
        CREATE INDEX entity_addresses_by_entity_type_state
          ON {SCHEMA}.entity_addresses (entity_id, address_type_code, state);
        """
    )
    op.execute(
        f"""
        -- Per *entity and address type*, deliberately NOT per entity alone:
        -- the same normalized address may legitimately recur for one entity
        -- under a DIFFERENT address_type_code (a legal-principal address and
        -- a project address are often the identical street address), and
        -- address_type_code being part of this key is what permits that
        -- rather than a coincidence a future reader should "fix" by dropping
        -- it -- do not drop it.
        CREATE UNIQUE INDEX an_active_entity_address_is_unique_per_entity_and_type
          ON {SCHEMA}.entity_addresses (
            principal_id, entity_id, address_type_code, normalized_address_value
          )
          WHERE state = 'active';
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX an_active_entity_address_has_one_preferred_per_type
          ON {SCHEMA}.entity_addresses (principal_id, entity_id, address_type_code)
          WHERE state = 'active' AND is_preferred = true;
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_communication_methods (
          communication_method_id text PRIMARY KEY,
          entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          principal_id text NOT NULL,
          method_type_code text NOT NULL,
          usage_context_code text NOT NULL,
          normalized_value text NOT NULL,
          display_value text NOT NULL,
          verification_status_code text NOT NULL DEFAULT 'unresolved',
          is_preferred boolean NOT NULL DEFAULT false,
          effective_from timestamptz,
          effective_to timestamptz,
          state text NOT NULL DEFAULT 'active',
          version integer NOT NULL DEFAULT 1,
          updated_at timestamptz,
          retired_at timestamptz,
          superseded_by_communication_method_id text
            REFERENCES {SCHEMA}.entity_communication_methods(communication_method_id),
          linked_external_identifier_id text
            REFERENCES {SCHEMA}.entity_external_identifiers(identifier_id),
          CONSTRAINT communication_method_id_is_an_opaque_identifier
            CHECK (communication_method_id ~ '^ecmm_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_communication_method_type_is_known
            CHECK (method_type_code IN ({_COMMUNICATION_METHOD_TYPE_VALUES})),
          CONSTRAINT a_communication_usage_context_is_known
            CHECK (usage_context_code IN ({_COMMUNICATION_USAGE_CONTEXT_VALUES})),
          CONSTRAINT a_communication_verification_status_is_known
            CHECK (
              verification_status_code IN ({_COMMUNICATION_VERIFICATION_STATUS_VALUES})
            ),
          CONSTRAINT an_entity_communication_method_state_is_known
            CHECK (state IN ('active', 'retired', 'superseded')),
          CONSTRAINT a_communication_method_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT a_communication_method_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          CONSTRAINT a_communication_method_names_a_successor_only_when_superseded
            CHECK (
              superseded_by_communication_method_id IS NULL OR state = 'superseded'
            ),
          CONSTRAINT a_communication_method_does_not_supersede_itself
            CHECK (
              superseded_by_communication_method_id IS NULL
              OR superseded_by_communication_method_id <> communication_method_id
            ),
          CONSTRAINT a_communication_method_normalized_value_is_not_blank
            CHECK (length(trim(normalized_value)) > 0),
          CONSTRAINT a_communication_method_display_value_is_not_blank
            CHECK (length(trim(display_value)) > 0),
          CONSTRAINT a_communication_method_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          -- The identity/channel boundary: only an EMAIL row may ever
          -- cross-reference entity_external_identifiers, which remains the
          -- sole authority for identity resolution. This is what stops
          -- phone/domain/website rows from overloading the
          -- external-identifier namespace through this column.
          CONSTRAINT a_communication_method_links_an_identifier_only_for_email
            CHECK (
              linked_external_identifier_id IS NULL OR method_type_code = 'email'
            ),
          CONSTRAINT a_communication_method_is_identified_within_its_principal
            UNIQUE (communication_method_id, principal_id)
        );
        """
    )
    # Composite foreign keys, added after the table exists: entity_id/
    # principal_id -> entities, the self-referencing supersession, and the
    # optional cross-reference to entity_external_identifiers -- three
    # references, each scoped to the same principal on both sides.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_communication_methods
          ADD CONSTRAINT a_communication_method_names_an_entity_of_its_principal
          FOREIGN KEY (entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_communication_methods
          ADD CONSTRAINT a_communication_method_is_superseded_within_its_principal
          FOREIGN KEY (superseded_by_communication_method_id, principal_id)
          REFERENCES {SCHEMA}.entity_communication_methods (
            communication_method_id, principal_id
          );
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_communication_methods
          ADD CONSTRAINT a_communication_method_links_an_identifier_of_its_principal
          FOREIGN KEY (linked_external_identifier_id, principal_id)
          REFERENCES {SCHEMA}.entity_external_identifiers (identifier_id, principal_id);
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_communication_methods_by_principal
          ON {SCHEMA}.entity_communication_methods (principal_id);
        CREATE INDEX entity_communication_methods_by_normalized_value
          ON {SCHEMA}.entity_communication_methods (normalized_value);
        CREATE INDEX entity_communication_methods_by_entity_type_state
          ON {SCHEMA}.entity_communication_methods (entity_id, method_type_code, state);
        """
    )
    op.execute(
        f"""
        -- Per *entity and method type*, across usage contexts: the same
        -- value tagged with two different usage_context_codes is one
        -- channel double-counted, not two channels, so usage_context_code is
        -- deliberately NOT part of this key. Two genuinely different
        -- channels (a corporate number and a project's own number) already
        -- differ in normalized_value.
        CREATE UNIQUE INDEX an_active_communication_method_is_unique_per_entity_and_type
          ON {SCHEMA}.entity_communication_methods (
            principal_id, entity_id, method_type_code, normalized_value
          )
          WHERE state = 'active';
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX an_active_communication_method_has_one_preferred_per_type
          ON {SCHEMA}.entity_communication_methods (
            principal_id, entity_id, method_type_code
          )
          WHERE state = 'active' AND is_preferred = true;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_communication_methods;")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_addresses;")
