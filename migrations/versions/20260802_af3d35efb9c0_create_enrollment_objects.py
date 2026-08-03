"""create enrollment objects

Adds one table to the existing `knowledge` schema — `enrollment_objects`. It
creates no schema and reads nothing from the migrated legacy corpus.

`enrollment_objects` is the enumerated object set an enrollment authorizes. Until
this revision the only record of scope was `enrollments.root_object_id` and
`enrollments.object_ids`, and neither column had a foreign key: `object_ids` is an
`ARRAY(Text)` and PostgreSQL has no element-level reference, so an identifier that
named no row was storable and silently authorized nothing. The new table closes
that for the enumerated set.

The table is named explicitly rather than taken from the shared `MetaData`, for
the reason `8b3f5c17d904` states: `my_pa.infrastructure.persistence.tables`
declares every table in this schema in one module, so an unqualified `create_all`
here would also create the nine that earlier revisions own — and would then start
creating whatever a later revision declares, which would make this file's meaning
depend on code written after it.
`tests/schema/test_extraction_schema_migration.py` asserts that each revision
emits exactly the tables it names.

**Why there is no foreign key on `enrollments.root_object_id`.** It would be the
obvious second half, and it is deliberately absent. `enrollments` is created by
`7e5a1fb93d62` through `METADATA.create_all`, and that `MetaData` is shared at
import time, so declaring the reference in `tables.py` would retroactively change
the DDL that already-merged revision emits — a base-to-head replay would produce a
constraint the revision never described, and at head the same reference would
exist twice. Adding it here instead, with `op.create_foreign_key`, does not avoid
that: the declaration is what the earlier revision reads. A chain whose earlier
revisions change meaning when a later one is written is not a chain, and the
constraint is redundant with a control this package already builds: enumeration
runs inside the enroll transaction, a root naming no observed object enumerates
to nothing, and `record_scope` refuses both an unobserved object and an empty
set — so an enrollment naming a root that does not exist is never accepted.

This revision is therefore purely declaration-driven, which is exactly the
pattern `tables.py`'s module docstring states, under "The tables are declared
once here" — cited by heading rather than by line, because WP-6 moved that
paragraph and the line numbers that stood here went with it.

The downgrade drops the table. It leaves the `knowledge` schema and the nine
tables below it in place, because this revision created none of them.

Revision ID: af3d35efb9c0
Revises: 9c6b4a18ed72
Created: 2026-08-02 17:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Table

from my_pa.infrastructure.persistence.tables import METADATA, enrollment_objects

revision: str = "af3d35efb9c0"
down_revision: str | None = "9c6b4a18ed72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the one table this revision's docstring documents.
_TABLES: list[Table] = [enrollment_objects]


def upgrade() -> None:
    METADATA.create_all(op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    METADATA.drop_all(op.get_bind(), tables=_TABLES)
