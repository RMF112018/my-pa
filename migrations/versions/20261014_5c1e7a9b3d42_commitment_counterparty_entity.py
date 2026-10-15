"""Name a Commitment's counterparty by Entity instead of by Person.

Revision ID: 5c1e7a9b3d42
Revises: c8f7ae406d47
Create Date: 2026-10-14

Written against `a591b81f10a2` and re-parented onto `c8f7ae406d47` (the MCP
interaction log, #331) when that revision landed on `a591b81f10a2` first, so the
chain keeps one head; `c8f7ae406d47` creates only the `observability` schema and
touches neither `knowledge.commitments` nor `knowledge.entities`, so nothing below
changes.

`knowledge.commitments.counterparty_person_id` (created by `8f2b6c4d1a37`) held
an `IdKind.PERSON` identifier with no foreign key. A Person is minted only by
the Graph-sourced identity-resolution pipeline into
`knowledge.relationship_people`, which this deployment never populates, so no
Commitment could ever pass the application's current-counterparty check. This
revision is a clean cutover to an `IdKind.ENTITY` counterparty naming a
locally-creatable `knowledge.entities` row (the application admits `person` and
`organization` Entities that are `active`). It:

1. drops `counterparty_person_id` and its inline CHECK
   `counterparty_person_id_is_an_opaque_identifier` (no index names it);
2. adds `counterparty_entity_id text NOT NULL` with the CHECK
   `counterparty_entity_id_is_an_opaque_identifier` (`^ent_[A-Za-z0-9]{8,64}$`,
   the shape every other Entity identifier column carries);
3. adds the composite foreign key
   `a_commitment_counterparty_is_an_entity_of_its_principal`
   `(counterparty_entity_id, principal_id)` onto
   `entities (entity_id, principal_id)`, the target
   `an_entity_is_identified_within_its_principal` exists for: a plain
   `entity_id` key would be satisfiable across the Principal partition. No
   `ON DELETE` action: an Entity row is never deleted by the application, and
   a Commitment must never be cascaded away;
4. adds the lookup index `commitments_by_counterparty_entity`, as every other
   Entity-referencing column on this plane has one.

There is no backfill, no dual-write and no alias: a `per_` identifier has no
Entity it could be mapped to. **`upgrade` therefore refuses** with
`restrict_violation`, changing nothing, while `knowledge.commitments` holds any
row: adding a `NOT NULL` column with no default to a populated table would
otherwise fail opaquely, and inventing an Entity per Person would be an identity
assertion this revision has no evidence for. **`downgrade` refuses in the same
way** while any row exists, because an `ent_` identifier cannot be mapped back
to a Person. On an empty table `downgrade` drops the index, the foreign key, the
CHECK and the column, and restores `counterparty_person_id text NOT NULL` with
its original CHECK exactly (the column moves to the end of the table; nothing
reads columns by position).

All DDL is frozen text: no package import, no live declaration, no enum
(`D-48`, `D-69`). It grants nothing and emits no Record Event.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "5c1e7a9b3d42"
down_revision: str | tuple[str, ...] | None = "c8f7ae406d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"
TABLE: Final = "commitments"
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_PERSON_COLUMN: Final = "counterparty_person_id"
_PERSON_CHECK: Final = "counterparty_person_id_is_an_opaque_identifier"
_PERSON_CHECK_SQL: Final = f"counterparty_person_id ~ '^per_{_IDENTIFIER_SUFFIX}$'"

_ENTITY_COLUMN: Final = "counterparty_entity_id"
_ENTITY_CHECK: Final = "counterparty_entity_id_is_an_opaque_identifier"
_ENTITY_CHECK_SQL: Final = f"counterparty_entity_id ~ '^ent_{_IDENTIFIER_SUFFIX}$'"
_ENTITY_FOREIGN_KEY: Final = "a_commitment_counterparty_is_an_entity_of_its_principal"
_ENTITY_INDEX: Final = "commitments_by_counterparty_entity"


def _refuse_while_any_commitment_exists(direction: str, reason: str) -> None:
    """Fail closed, changing nothing, while `knowledge.commitments` holds a row.

    Emitted as server SQL so offline `--sql` mode stays honest; the message
    carries a count and never a row payload.
    """
    escaped = reason.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
          offending_count bigint;
        BEGIN
          SELECT count(*) INTO offending_count FROM {SCHEMA}.{TABLE};
          IF offending_count > 0 THEN
            RAISE EXCEPTION
              '5c1e7a9b3d42 {direction} refused: % commitment row(s). {escaped}',
              offending_count
              USING ERRCODE = 'restrict_violation';
          END IF;
        END $$
        """  # noqa: S608 -- every interpolated value is a frozen literal of this revision
    )


def upgrade() -> None:
    _refuse_while_any_commitment_exists(
        "upgrade",
        "A per_ counterparty has no Entity to map to and the new column is NOT NULL "
        "with no default; empty knowledge.commitments before applying this revision.",
    )
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT {_PERSON_CHECK}")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP COLUMN {_PERSON_COLUMN}")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ADD COLUMN {_ENTITY_COLUMN} text NOT NULL")
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT {_ENTITY_CHECK} CHECK ({_ENTITY_CHECK_SQL})"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} "
        f"ADD CONSTRAINT {_ENTITY_FOREIGN_KEY} "
        f"FOREIGN KEY ({_ENTITY_COLUMN}, principal_id) "
        f"REFERENCES {SCHEMA}.entities (entity_id, principal_id)"
    )
    op.execute(f"CREATE INDEX {_ENTITY_INDEX} ON {SCHEMA}.{TABLE} ({_ENTITY_COLUMN})")


def downgrade() -> None:
    _refuse_while_any_commitment_exists(
        "downgrade",
        "An ent_ counterparty cannot be mapped back to a per_ Person; "
        "empty knowledge.commitments before downgrading.",
    )
    op.execute(f"DROP INDEX {SCHEMA}.{_ENTITY_INDEX}")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT {_ENTITY_FOREIGN_KEY}")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT {_ENTITY_CHECK}")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP COLUMN {_ENTITY_COLUMN}")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ADD COLUMN {_PERSON_COLUMN} text NOT NULL")
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT {_PERSON_CHECK} CHECK ({_PERSON_CHECK_SQL})"
    )
