"""create the knowledge schema

Creates the application's own schema, `knowledge`, and the five tables in it:
configured sources, observed objects, observed versions, enrollments, and jobs.

It is a new schema on purpose. The eight domain schemas hold the migrated legacy
corpus, which this revision does not read, write, or depend on; `public` holds
`alembic_version` and nothing else; and `migration_control` is a ledger scoped to
one migration run, so putting application state there would make an enrollment
retry indistinguishable from a migration retry and would give application code a
write path into migration governance. This revision therefore adds and removes
only objects that did not exist before it, and its downgrade cannot touch the
migrated corpus even if it is run against a loaded database.

The tables are declared once, in `my_pa.infrastructure.persistence.tables`, and
copied into revision-local metadata here. Closed-set checks are replaced with
the literals this revision originally emitted, so later vocabulary expansion
cannot rewrite migration history.

The five are named explicitly rather than taken as "whatever is in the shared
`MetaData`". `METADATA` is shared with every later revision that declares a table
in this schema, so an unqualified `create_all` would create the tables of those
revisions too: this landed revision would silently start doing more than its own
docstring says the moment someone declared a sixth table, and it would stop being
a record of what was applied. The pin makes the code match the docstring, and
`tests/schema/test_extraction_schema_migration.py` asserts the equality per
revision so removing it fails rather than passing quietly.

Revision ID: 7e5a1fb93d62
Revises: 6c4d3ea82f10
Created: 2026-08-01 15:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    enrollments,
    jobs,
    source_object_versions,
    source_objects,
    sources,
)

revision: str = "7e5a1fb93d62"
down_revision: str | None = "6c4d3ea82f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the five tables this revision's docstring documents. Order is not
#: significant — SQLAlchemy sorts by foreign-key dependency on create and
#: reverses that on drop — but membership is.
_TABLES: list[Table] = [sources, source_objects, source_object_versions, enrollments, jobs]

_FROZEN: dict[str, dict[str, str]] = {
    "sources": {
        "provider_kind_is_known": "provider_kind IN ('fixture')",
        "classification_is_known": (
            "classification IN ('private_local', 'restricted_local', 'synthetic_test')"
        ),
    },
    "source_objects": {"kind_is_known": "kind IN ('container', 'file')"},
    "jobs": {
        "state_is_known": "state IN ('failed', 'queued', 'running', 'succeeded')",
        "last_error_code_is_a_public_error_code": (
            "last_error_code IS NULL OR last_error_code IN ('invalid_request', "
            "'ambiguous_request', 'denied', 'unavailable', 'unsupported', 'not_found', "
            "'conflict', 'rate_limited', 'quarantined', 'cancelled', 'internal_error')"
        ),
    },
}


def _historical_knowledge_tables() -> list[Table]:
    """Return the five declarations with their original closed sets frozen."""
    frozen = MetaData(schema=SCHEMA)
    copies = [table.to_metadata(frozen) for table in _TABLES]
    for copy in copies:
        replacements = _FROZEN.get(copy.name, {})
        for constraint in [
            candidate for candidate in copy.constraints if candidate.name in replacements
        ]:
            copy.constraints.discard(constraint)
        for name, expression in replacements.items():
            copy.append_constraint(CheckConstraint(expression, name=name))
    return copies


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    frozen = _historical_knowledge_tables()
    frozen[0].metadata.create_all(op.get_bind(), tables=frozen)


def downgrade() -> None:
    frozen = _historical_knowledge_tables()
    frozen[0].metadata.drop_all(op.get_bind(), tables=frozen)
    # RESTRICT, not CASCADE: reaching this point with anything still in the
    # schema means a later revision left an object behind, and failing loudly is
    # better than silently deleting whatever it is.
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" RESTRICT')
