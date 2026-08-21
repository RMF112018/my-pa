"""Add the entity alias table.

Revision ID: b7f4d1a92c36
Revises: 9def3c2e63bb
Create Date: 2026-08-18

WP-RI-03: exact resolution matches on aliases as well as on canonical names
(specification section 15.1, "aliases and initials"), so an entity needs a
place to record the name forms it is actually referred to by.

**The unique constraint is per entity, not global**, and that is the whole
safety argument of this table: two real people do share a name, and a schema
that made a shared alias a conflict would force one of them to be merged into
the other. `an_alias_is_recorded_once_per_entity_and_type` says an entity does
not record the same name twice under the same type; it says nothing about two
entities, which is why `entity_aliases_by_normalized_value` is a plain index
rather than a unique one.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`), the
closed-set literal is frozen at this revision, and every constraint is named to
match the declaration.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "b7f4d1a92c36"
down_revision: str | None = "9def3c2e63bb"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_ALIAS_TYPE_VALUES: Final = (
    "'abbreviation', 'document_reference', 'former_name', 'full_name', "
    "'initials', 'nickname', 'preferred_name'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_aliases (
          alias_id text PRIMARY KEY,
          entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          alias_type text NOT NULL,
          normalized_value text NOT NULL,
          display_value text NOT NULL,
          effective_from timestamptz,
          effective_to timestamptz,
          principal_id text NOT NULL,
          CONSTRAINT alias_id_is_an_opaque_identifier
            CHECK (alias_id ~ '^eals_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_alias_type_is_known
            CHECK (alias_type IN ({_ALIAS_TYPE_VALUES})),
          CONSTRAINT an_alias_normalized_value_is_not_blank
            CHECK (length(trim(normalized_value)) > 0),
          CONSTRAINT an_alias_display_value_is_not_blank
            CHECK (length(trim(display_value)) > 0),
          CONSTRAINT an_alias_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          CONSTRAINT an_alias_is_recorded_once_per_entity_and_type
            UNIQUE (entity_id, alias_type, normalized_value)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_aliases_by_principal
          ON {SCHEMA}.entity_aliases (principal_id);
        CREATE INDEX entity_aliases_by_normalized_value
          ON {SCHEMA}.entity_aliases (normalized_value);
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_aliases;")
