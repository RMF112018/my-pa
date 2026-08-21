"""Add generalized entity, external identifier, assignment, and relationship tables.

Revision ID: 9def3c2e63bb
Revises: f4c1a8e6b205
Create Date: 2026-08-17

WP-RI-01: domain model and additive database migration.  Creates four tables
(`entities`, `entity_external_identifiers`, `entity_assignments`,
`entity_relationships`) that generalize beyond the person-and-organization-only
WP-9 substrate.  These tables are additive: they do not modify or drop
`relationship_people` or `relationship_organizations`.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`), and
the closed-set literals below are frozen at this revision.

**Every constraint is named, and the names match `tables.py`.**  An inline
`CHECK` inside a column definition is auto-named by PostgreSQL
(`entities_entity_id_check`), which is not the name the declaration states —
and `tests/schema` asserts that every name a declaration gives appears on the
migrated server.  So each one is written as a table-level `CONSTRAINT` clause
here, spelled exactly as `_is_identifier` and `_one_of` spell it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "9def3c2e63bb"
down_revision: str | None = "f4c1a8e6b205"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_ENTITY_TYPE_VALUES: Final = (
    "'location', 'organization', 'person', 'program', 'project', 'team_or_group', 'work_package'"
)

_ENTITY_STATUS_VALUES: Final = "'active', 'archived', 'historical', 'inactive', 'merged_redirect'"

_NAMESPACE_VALUES: Final = (
    "'apple_contact_id', 'email', 'entra_object_id', 'outlook_contact_id', "
    "'source_participant_id', 'teams_user_id', 'vendor_system_id'"
)

_ASSIGNMENT_TYPE_VALUES: Final = (
    "'employment', 'membership', 'project_assignment', 'team_membership', 'work_package_assignment'"
)

_RELATIONSHIP_TYPE_VALUES: Final = (
    "'affiliated_with', 'approver_for', 'consultant_to', 'contractor_on', "
    "'decision_maker_for', 'leads', 'manages', 'member_of', "
    "'primary_contact_for', 'reports_to', 'represents', 'responsible_for', "
    "'subcontractor_to', 'vendor_for', 'works_for'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entities (
          entity_id text PRIMARY KEY,
          principal_id text NOT NULL,
          entity_type text NOT NULL,
          canonical_name text NOT NULL,
          display_name text NOT NULL,
          status text NOT NULL DEFAULT 'active',
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          version integer NOT NULL DEFAULT 1,
          superseded_by_entity_id text
            REFERENCES {SCHEMA}.entities(entity_id),
          CONSTRAINT entity_id_is_an_opaque_identifier
            CHECK (entity_id ~ '^ent_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_entity_type_is_known
            CHECK (entity_type IN ({_ENTITY_TYPE_VALUES})),
          CONSTRAINT an_entity_status_is_known
            CHECK (status IN ({_ENTITY_STATUS_VALUES})),
          CONSTRAINT an_entity_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT an_entity_canonical_name_is_not_blank
            CHECK (length(trim(canonical_name)) > 0),
          CONSTRAINT an_entity_display_name_is_not_blank
            CHECK (length(trim(display_name)) > 0),
          CONSTRAINT an_entity_redirects_exactly_when_it_is_merged_away
            CHECK ((status = 'merged_redirect') = (superseded_by_entity_id IS NOT NULL)),
          CONSTRAINT an_entity_does_not_supersede_itself
            CHECK (superseded_by_entity_id IS NULL OR superseded_by_entity_id <> entity_id)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entities_by_principal ON {SCHEMA}.entities (principal_id);
        CREATE INDEX entities_by_entity_type ON {SCHEMA}.entities (entity_type);
        CREATE INDEX entities_by_status ON {SCHEMA}.entities (status);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_external_identifiers (
          identifier_id text PRIMARY KEY,
          entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          namespace text NOT NULL,
          normalized_value text NOT NULL,
          display_value text NOT NULL,
          verified boolean NOT NULL DEFAULT false,
          effective_from timestamptz,
          effective_to timestamptz,
          principal_id text NOT NULL,
          CONSTRAINT identifier_id_is_an_opaque_identifier
            CHECK (identifier_id ~ '^xid_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_external_identifier_namespace_is_known
            CHECK (namespace IN ({_NAMESPACE_VALUES})),
          CONSTRAINT an_external_identifier_normalized_value_is_not_blank
            CHECK (length(trim(normalized_value)) > 0),
          CONSTRAINT an_external_identifier_display_value_is_not_blank
            CHECK (length(trim(display_value)) > 0),
          CONSTRAINT an_external_identifier_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          CONSTRAINT an_external_identifier_is_recorded_once_per_namespace
            UNIQUE (entity_id, namespace, normalized_value)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_external_identifiers_by_principal
          ON {SCHEMA}.entity_external_identifiers (principal_id);
        CREATE INDEX entity_external_identifiers_by_namespace_value
          ON {SCHEMA}.entity_external_identifiers (namespace, normalized_value);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_assignments (
          assignment_id text PRIMARY KEY,
          entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          scope_entity_id text
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE SET NULL,
          assignment_type text NOT NULL,
          role text,
          discipline text,
          responsibility_class text,
          effective_from timestamptz,
          effective_to timestamptz,
          status text NOT NULL DEFAULT 'active',
          principal_id text NOT NULL,
          CONSTRAINT assignment_id_is_an_opaque_identifier
            CHECK (assignment_id ~ '^asn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_assignment_type_is_known
            CHECK (assignment_type IN ({_ASSIGNMENT_TYPE_VALUES})),
          CONSTRAINT an_assignment_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            )
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_assignments_by_principal
          ON {SCHEMA}.entity_assignments (principal_id);
        CREATE INDEX entity_assignments_by_entity_id
          ON {SCHEMA}.entity_assignments (entity_id);
        CREATE INDEX entity_assignments_by_scope_entity_id
          ON {SCHEMA}.entity_assignments (scope_entity_id);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_relationships (
          relationship_id text PRIMARY KEY,
          from_entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          to_entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          relationship_type text NOT NULL,
          scope_entity_id text
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE SET NULL,
          effective_from timestamptz,
          effective_to timestamptz,
          state text NOT NULL DEFAULT 'active',
          version integer NOT NULL DEFAULT 1,
          principal_id text NOT NULL,
          CONSTRAINT relationship_id_is_an_opaque_identifier
            CHECK (relationship_id ~ '^erel_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_entity_relationship_type_is_known
            CHECK (relationship_type IN ({_RELATIONSHIP_TYPE_VALUES})),
          CONSTRAINT an_entity_relationship_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT an_entity_relationship_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          CONSTRAINT an_entity_relationship_connects_two_distinct_entities
            CHECK (from_entity_id <> to_entity_id)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_relationships_by_principal
          ON {SCHEMA}.entity_relationships (principal_id);
        CREATE INDEX entity_relationships_by_from_entity
          ON {SCHEMA}.entity_relationships (from_entity_id);
        CREATE INDEX entity_relationships_by_to_entity
          ON {SCHEMA}.entity_relationships (to_entity_id);
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TABLE IF EXISTS {SCHEMA}.entity_relationships;
        DROP TABLE IF EXISTS {SCHEMA}.entity_assignments;
        DROP TABLE IF EXISTS {SCHEMA}.entity_external_identifiers;
        DROP TABLE IF EXISTS {SCHEMA}.entities;
        """
    )
