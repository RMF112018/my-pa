"""Admit Project.version and the durable Project↔Entity bridge.

Revision ID: 9f2c8a1d4e70
Revises: de5ec1c65857
Create Date: 2026-09-13

WP-MCP-PROJ-01 adds `knowledge.projects.version` and the Continuity
Project↔Entity bridge `knowledge.project_entity_links`. Existing Project rows
receive version 1 and one `unresolved_missing` bridge row with a null entity
id. Nothing here mints an Entity and nothing joins on a name.

Literals are frozen here rather than derived from domain enums (`D-48` /
architecture freeze). Downgrade refuses when any bound bridge row exists so a
binding cannot be dropped silently.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "9f2c8a1d4e70"
down_revision: str | None = "de5ec1c65857"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"
_PRINCIPAL_IDENTIFIER: Final = f"principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'"
_PROJECT_IDENTIFIER: Final = f"project_id ~ '^prj_{_IDENTIFIER_SUFFIX}$'"
_ENTITY_IDENTIFIER_WHEN_PRESENT: Final = (
    f"project_entity_id IS NULL OR project_entity_id ~ '^ent_{_IDENTIFIER_SUFFIX}$'"
)
_LINKAGE_STATE_KNOWN: Final = (
    "linkage_state IN ('bound', 'unresolved_missing', 'unresolved_ambiguous')"
)
_BOUND_NAMES_ITS_ENTITY: Final = "(linkage_state = 'bound') = (project_entity_id IS NOT NULL)"
_VERSION_POSITIVE: Final = "version >= 1"


def _refuse(*, name: str, offending_sql: str, message: str) -> None:
    """Fail closed when `offending_sql` yields any row.

    Emitting the guard as server SQL keeps offline `--sql` mode honest and
    keeps the refusal message free of row payloads beyond a count.
    """
    escaped_name = name.replace("'", "''")
    escaped_message = message.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
          offending_count integer;
        BEGIN
          WITH offending AS (
            {offending_sql}
          )
          SELECT count(*) INTO offending_count FROM offending;
          IF offending_count > 0 THEN
            RAISE EXCEPTION
              'WP-MCP-PROJ-01 refused ({escaped_name}): % row(s). {escaped_message}',
              offending_count;
          END IF;
        END $$
        """  # noqa: S608
    )


def upgrade() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN version integer NOT NULL DEFAULT 1")
    op.execute(
        f"UPDATE {SCHEMA}.projects SET version = 1 "  # noqa: S608
        "WHERE version IS DISTINCT FROM 1"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects "
        f"ADD CONSTRAINT a_project_version_is_positive CHECK ({_VERSION_POSITIVE})"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects "
        "ADD CONSTRAINT a_project_is_identified_within_its_principal "
        "UNIQUE (project_id, principal_id)"
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_entity_links (
          principal_id text NOT NULL,
          project_id text NOT NULL,
          project_entity_id text,
          linkage_state text NOT NULL,
          created_at timestamp with time zone NOT NULL,
          updated_at timestamp with time zone NOT NULL,
          PRIMARY KEY (principal_id, project_id),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK ({_PRINCIPAL_IDENTIFIER}),
          CONSTRAINT project_id_is_an_opaque_identifier
            CHECK ({_PROJECT_IDENTIFIER}),
          CONSTRAINT a_project_entity_id_is_an_entity_identifier_when_present
            CHECK ({_ENTITY_IDENTIFIER_WHEN_PRESENT}),
          CONSTRAINT a_project_entity_link_state_is_known
            CHECK ({_LINKAGE_STATE_KNOWN}),
          CONSTRAINT a_bound_project_entity_link_names_its_entity
            CHECK ({_BOUND_NAMES_ITS_ENTITY}),
          CONSTRAINT a_project_entity_link_names_a_project_in_its_principal
            FOREIGN KEY (project_id, principal_id)
            REFERENCES {SCHEMA}.projects (project_id, principal_id),
          CONSTRAINT a_project_entity_link_names_an_entity_in_its_principal
            FOREIGN KEY (project_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
        )
        """
    )
    op.execute(
        f"CREATE INDEX project_entity_links_by_principal "
        f"ON {SCHEMA}.project_entity_links (principal_id)"
    )
    op.execute(
        f"CREATE UNIQUE INDEX a_project_entity_is_linked_once_per_principal "
        f"ON {SCHEMA}.project_entity_links (principal_id, project_entity_id) "
        "WHERE project_entity_id IS NOT NULL"
    )
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.project_entity_links (
          principal_id, project_id, project_entity_id, linkage_state,
          created_at, updated_at
        )
        SELECT
          principal_id,
          project_id,
          NULL,
          'unresolved_missing',
          created_at,
          updated_at
        FROM {SCHEMA}.projects
        """  # noqa: S608
    )


def downgrade() -> None:
    _refuse(
        name="bound project-entity links",
        offending_sql=(
            f"SELECT project_id FROM {SCHEMA}.project_entity_links "  # noqa: S608
            "WHERE linkage_state = 'bound'"
        ),
        message=(
            "Dropping project_entity_links would destroy bound Project Entity "
            "identities; unbind or remove those rows before downgrade."
        ),
    )
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.project_entity_links")
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects "
        "DROP CONSTRAINT IF EXISTS a_project_is_identified_within_its_principal"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects DROP CONSTRAINT IF EXISTS a_project_version_is_positive"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.projects DROP COLUMN IF EXISTS version")
