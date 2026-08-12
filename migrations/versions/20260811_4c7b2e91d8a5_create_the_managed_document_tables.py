"""Create the managed-document plane: documents, versions, submissions, receipts, lifecycle.

WP-27. The product's own write plane — the first one in this schema whose rows
name bytes on a filesystem this product wrote. Five tables and two triggers.

**The two triggers are the structural half of immutability, and they are the
reason this revision is not just five `CREATE TABLE`s.** `AGENTS.md` section 4
and the operating brief both require a managed version to be immutable, and no
`CHECK` can express "no `UPDATE`". A rule enforced only by the writer is a rule
the next writer does not inherit, so `managed_document_versions` and
`managed_document_lifecycle_events` each carry a `BEFORE UPDATE OR DELETE`
trigger that raises — the same mechanism `1a4c9e77b2d5` installed on
`capture_versions`, and for the same reason. The lifecycle table carries one too
because archive is a state transition recorded as an event: a rewritable event is
a status field with extra steps, and restoring by editing the archive row would
leave no trace that anything was ever archived.

**The two closed sets below are frozen**, per the standing rule `9c6b4a18ed72`
states and every revision since has repeated: no Alembic revision may derive a
closed-set constraint from a domain enum. The managed media types and the two
lifecycle transitions are written out here, so a database migrated to this
revision holds the vocabulary this revision describes rather than whatever the
domain says on the day it runs. `tests/architecture/
test_no_revision_derives_a_closed_set_from_an_enum.py` holds both texts.

**Nothing about the capability vocabulary changes.** This package adds no member
to `Capability` and no member to `Purpose`, because it wires no transport: the
managed-document use cases are reached through
`application.managed_documents.ManagedDocumentService`, which a composition root
calls directly with a resolved Principal, exactly as `SituationService` is
reached. `audit_events.capability_is_known` is therefore untouched, and admitting
a managed capability seat is WP-28's `ALTER` to write when it wires the adapter.

**No path column anywhere.** A version's bytes live at a location the byte store
derives from the version identifier, so there is nothing here for a row to point
at — which is also what makes a migrated database and a managed root reconcilable
against each other with no second index.

Revision ID: 4c7b2e91d8a5
Revises: 2d9f4a7c1e58
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Final

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    managed_document_lifecycle_events,
    managed_document_receipts,
    managed_document_submissions,
    managed_document_versions,
    managed_documents,
)

revision: str = "4c7b2e91d8a5"
down_revision: str | None = "2d9f4a7c1e58"
branch_labels: str | None = None
depends_on: str | None = None

#: The five tables this revision creates, in dependency order. `create_all`
#: sorts by foreign key itself; the order here is for a reader.
_TABLES: Final[list[Table]] = [
    managed_documents,
    managed_document_versions,
    managed_document_receipts,
    managed_document_submissions,
    managed_document_lifecycle_events,
]

#: The closed sets as this revision emits them, written out rather than derived.
#: A member added to `MANAGED_MEDIA_TYPES` or to
#: `domain.documents.managed.LifecycleTransition` must leave these two texts
#: exactly where they are, which is what "the revision goes on denoting one
#: schema" means.
_FROZEN: Final[dict[str, dict[str, str]]] = {
    "managed_document_versions": {
        "a_managed_media_type_is_known": (
            "media_type IN ('application/json', 'application/octet-stream', "
            "'application/pdf', 'text/markdown', 'text/plain')"
        ),
    },
    "managed_document_lifecycle_events": {
        "a_managed_document_transition_is_known": "transition IN ('archived', 'restored')",
    },
}

#: The function and the triggers that make the two append-only tables append only.
_IMMUTABILITY_FUNCTION: Final = "managed_document_rows_stay_as_written"
_IMMUTABLE_TABLES: Final = (
    ("managed_document_versions", "managed_document_versions_are_append_only"),
    ("managed_document_lifecycle_events", "managed_document_lifecycle_is_append_only"),
)


def _historical_wp27_tables() -> list[Table]:
    """The five tables as this revision emits them, with the two sets frozen.

    Copies into a throwaway `MetaData` rather than restating the declarations,
    which is the pattern `9c6b4a18ed72` establishes and for the reason it gives:
    a duplicated column list here would be a second statement of each table and
    would drift from the first in a way nothing checks. All five are copied into
    the *same* throwaway metadata, so the foreign keys among them — including
    `managed_document_versions.supersedes_version_id`, which points at its own
    table — resolve inside the copy rather than back at the shared declaration.
    """
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
    frozen = _historical_wp27_tables()
    frozen[0].metadata.create_all(op.get_bind(), tables=frozen)
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION '%.% is append only; % is refused', "
        "TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
        )


def downgrade() -> None:
    # The triggers go with their tables; the function does not, and
    # `7e5a1fb93d62` drops the schema with RESTRICT, so leaving it behind would
    # fail the downgrade at a revision that has no idea this one existed.
    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {SCHEMA}.{table}")
    frozen = _historical_wp27_tables()
    frozen[0].metadata.drop_all(op.get_bind(), tables=frozen)
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")
