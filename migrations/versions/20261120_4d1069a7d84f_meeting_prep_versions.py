"""Meeting prep briefs: the one `meeting_prep_versions` table (ADR-020 C1).

Revision ID: 4d1069a7d84f
Revises: 640aaacc78e8
Create Date: 2026-11-20

The one additive revision of ADR-020 (`docs/decisions/ADR-020-meeting-prep-briefs.md`,
which controls), on the sole head `640aaacc78e8`. In order it:

1. sets `lock_timeout` to 10 s for this revision's transaction only
   (`SET LOCAL`), so a lock that cannot be taken aborts the whole revision with
   `55P03` and leaves the database at `640aaacc78e8`;
2. creates `knowledge.meeting_prep_versions` as frozen DDL text (never the live
   `Table` object), a copy of the `meeting_note_versions` design (`7d9a450dfd07`):
   an immutable chain of full-body versions, each naming the `meeting_history`
   receipt that wrote it, partitioned by `principal_id` through composite
   foreign keys onto `meetings`, itself and `meeting_history`, all
   `ON DELETE RESTRICT`. Unlike notes there is no digest-bearing unique: no
   lineage evidence anchor references a prep version;
3. creates its two indexes: `(principal_id, meeting_id, version_number DESC)`
   and the GIN index on `to_tsvector('simple', content_markdown)` that
   `meetings.search` uses for the current prep;
4. creates the append-only guard, the notes precedent: one function
   (`meeting_prep_versions_stay_append_only`) and one `BEFORE UPDATE OR DELETE`
   row trigger (`meeting_prep_versions_are_append_only`).

Every bound is a frozen literal: the `mprep_` prefix (ADR-020 C1), the body
bound 400000 (`MAX_MEETING_PREP_CHARACTERS`, ADR-020 C3) and the SHA-256 shape.
This revision imports nothing from the live domain.

No existing row, column, constraint or vocabulary changes: no audit
vocabulary restatement (no capability or purpose is added), no `GRANT`, no
`REVOKE`; the table is owned by the role that runs the migration. No backfill.

`downgrade` locks the table `ACCESS EXCLUSIVE`, refuses with
`restrict_violation`, deleting nothing, while any prep version exists, and
otherwise drops exactly what `upgrade` created, in reverse order.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "4d1069a7d84f"
down_revision: str | None = "640aaacc78e8"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_LOCK_TIMEOUT: Final = "SET LOCAL lock_timeout = '10s'"

_TABLE: Final = "meeting_prep_versions"

_DDL: Final = """
    CREATE TABLE knowledge.meeting_prep_versions (
      prep_version_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      meeting_id TEXT NOT NULL,
      version_number INTEGER NOT NULL,
      supersedes_prep_version_id TEXT,
      content_markdown TEXT NOT NULL,
      content_sha256 TEXT NOT NULL,
      meeting_history_id TEXT NOT NULL,
      recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
      PRIMARY KEY (prep_version_id),
      CONSTRAINT prep_version_id_is_an_opaque_identifier CHECK (prep_version_id ~
          '^mprep_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT meeting_id_is_an_opaque_identifier CHECK (meeting_id ~
          '^mtg_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT supersedes_prep_version_id_is_an_opaque_identifier CHECK
          (supersedes_prep_version_id ~ '^mprep_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT meeting_history_id_is_an_opaque_identifier CHECK (meeting_history_id ~
          '^mhst_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_meeting_prep_version_number_is_positive CHECK (version_number >= 1),
      CONSTRAINT only_the_first_meeting_prep_supersedes_nothing CHECK ((version_number = 1) =
          (supersedes_prep_version_id IS NULL)),
      CONSTRAINT a_meeting_prep_body_is_bounded CHECK (length(content_markdown) BETWEEN 1 AND
          400000),
      CONSTRAINT a_meeting_prep_digest_is_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT a_meeting_prep_is_identified_within_its_meeting UNIQUE (prep_version_id,
          meeting_id, principal_id),
      CONSTRAINT one_meeting_prep_version_number_per_meeting UNIQUE (meeting_id,
          version_number),
      CONSTRAINT a_meeting_prep_version_is_superseded_once UNIQUE (supersedes_prep_version_id),
      CONSTRAINT a_meeting_prep_belongs_to_a_meeting_of_its_principal FOREIGN KEY(meeting_id,
          principal_id) REFERENCES knowledge.meetings (meeting_id, principal_id) ON DELETE
          RESTRICT,
      CONSTRAINT a_meeting_prep_supersedes_a_prep_of_its_meeting FOREIGN
          KEY(supersedes_prep_version_id, meeting_id, principal_id) REFERENCES
          knowledge.meeting_prep_versions (prep_version_id, meeting_id, principal_id) ON DELETE
          RESTRICT,
      CONSTRAINT a_meeting_prep_names_a_receipt_of_its_meeting FOREIGN KEY(meeting_history_id,
          meeting_id, principal_id) REFERENCES knowledge.meeting_history (history_id,
          meeting_id, principal_id) ON DELETE RESTRICT
    )
    """

_INDEXES: Final = (
    (
        "meeting_prep_versions_by_principal_meeting",
        """
        CREATE INDEX meeting_prep_versions_by_principal_meeting ON knowledge.meeting_prep_versions
          (principal_id, meeting_id, version_number DESC)
        """,
    ),
    (
        "meeting_prep_versions_text",
        """
        CREATE INDEX meeting_prep_versions_text ON knowledge.meeting_prep_versions USING gin
          (to_tsvector('simple', content_markdown))
        """,
    ),
)

_APPEND_ONLY_FUNCTION: Final = "meeting_prep_versions_stay_append_only"
_APPEND_ONLY_TRIGGER: Final = "meeting_prep_versions_are_append_only"

_APPEND_ONLY: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '{_TABLE} is append-only'
        USING ERRCODE = 'restrict_violation';
    END; $$;
    CREATE TRIGGER {_APPEND_ONLY_TRIGGER}
      BEFORE UPDATE OR DELETE ON {SCHEMA}.{_TABLE}
      FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}()
    """

#: `downgrade` locks the table before it checks it, so no prep version can
#: commit between the refusal check and the drop.
_LOCK_TABLE: Final = "LOCK TABLE knowledge.meeting_prep_versions IN ACCESS EXCLUSIVE MODE"

#: `downgrade` refuses while any prep version exists, rather than deleting user
#: data to make the downgrade pass (the `7d9a450dfd07` precedent).
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM knowledge.meeting_prep_versions) THEN
        RAISE EXCEPTION 'meeting prep versions exist; refusing to downgrade 4d1069a7d84f'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_DDL)
    for _name, ddl in _INDEXES:
        op.execute(ddl)
    op.execute(_APPEND_ONLY)


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLE)
    op.execute(_REFUSE_DOWNGRADE)
    op.execute(f"DROP TRIGGER {_APPEND_ONLY_TRIGGER} ON {SCHEMA}.{_TABLE}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}()")
    for name, _ddl in reversed(_INDEXES):
        op.execute(f"DROP INDEX {SCHEMA}.{name}")
    op.execute(f"DROP TABLE {SCHEMA}.{_TABLE} RESTRICT")
