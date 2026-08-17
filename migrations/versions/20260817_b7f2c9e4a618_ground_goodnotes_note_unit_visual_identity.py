"""Ground GoodNotes NOTE_UNIT identity in server-cropped page rasters.

Revision ID: b7f2c9e4a618
Revises: a4d9c2e7b815
Create Date: 2026-08-17

RWP-03. Additive knowledge-schema DDL. Canonical crop identity is the server
digest of cropped grayscale pixels; Agent crop/geometry is a locator.
Current-only AMBIGUOUS ledger rows may omit note/occurrence FKs. New revisions
carry page-version and snapshot provenance without backfilling legacy rows.
DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`).
Closed-set literals are frozen at this revision.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7f2c9e4a618"
down_revision: str | tuple[str, ...] | None = "a4d9c2e7b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.goodnotes_note_occurrences
          ADD CONSTRAINT one_goodnotes_occurrence_note_pair
            UNIQUE (principal_id, occurrence_id, note_id);

        ALTER TABLE knowledge.goodnotes_note_occurrences
          ADD CONSTRAINT goodnotes_note_occurrences_page_version_fk
            FOREIGN KEY (principal_id, page_version_id)
            REFERENCES knowledge.goodnotes_page_versions (
              principal_id, page_version_id
            )
            ON DELETE RESTRICT;

        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD COLUMN page_version_id varchar(30);
        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD COLUMN snapshot_id varchar(36);

        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD CONSTRAINT goodnotes_revision_page_version_id_shape
            CHECK (
              page_version_id IS NULL
              OR page_version_id ~ '^gnver_[a-f0-9]{24}$'
            );
        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD CONSTRAINT goodnotes_revision_snapshot_id_shape
            CHECK (
              snapshot_id IS NULL
              OR snapshot_id ~ '^gnsnap_[a-f0-9]{24}$'
            );

        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP CONSTRAINT goodnotes_note_revisions_occurrence_fk;
        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD CONSTRAINT goodnotes_note_revisions_occurrence_note_fk
            FOREIGN KEY (principal_id, occurrence_id, note_id)
            REFERENCES knowledge.goodnotes_note_occurrences (
              principal_id, occurrence_id, note_id
            )
            ON DELETE RESTRICT;
        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD CONSTRAINT goodnotes_note_revisions_page_version_fk
            FOREIGN KEY (principal_id, page_version_id)
            REFERENCES knowledge.goodnotes_page_versions (
              principal_id, page_version_id
            )
            ON DELETE RESTRICT;
        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD CONSTRAINT goodnotes_note_revisions_snapshot_fk
            FOREIGN KEY (principal_id, snapshot_id)
            REFERENCES knowledge.goodnotes_source_snapshots (
              principal_id, snapshot_id
            )
            ON DELETE RESTRICT;

        ALTER TABLE knowledge.goodnotes_run_note_changes
          ALTER COLUMN note_id DROP NOT NULL;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ALTER COLUMN occurrence_id DROP NOT NULL;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD COLUMN page_version_id varchar(30);
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD COLUMN geometry_key varchar(96);
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD COLUMN reason varchar(64);
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD COLUMN revision_id varchar(36);

        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT one_goodnotes_run_occurrence_change;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT goodnotes_run_note_changes_occurrence_fk;

        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_change_identity_matches_state
            CHECK (
              (
                change_state IN (
                  'NEW',
                  'UNCHANGED',
                  'REVISED',
                  'REMOVED_OR_NO_LONGER_PRESENT'
                )
                AND note_id IS NOT NULL
                AND occurrence_id IS NOT NULL
              )
              OR (
                change_state = 'AMBIGUOUS'
                AND (
                  (note_id IS NOT NULL AND occurrence_id IS NOT NULL)
                  OR (
                    note_id IS NULL
                    AND occurrence_id IS NULL
                    AND page_version_id IS NOT NULL
                    AND geometry_key IS NOT NULL
                  )
                )
              )
            );
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_change_page_version_id_shape
            CHECK (
              page_version_id IS NULL
              OR page_version_id ~ '^gnver_[a-f0-9]{24}$'
            );
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_change_geometry_key_shape
            CHECK (
              geometry_key IS NULL
              OR (
                char_length(geometry_key) BETWEEN 1 AND 96
                AND geometry_key ~ (
                  '^[0-9]\\.[0-9]{4},[0-9]\\.[0-9]{4},[0-9]\\.[0-9]{4},'
                  '[0-9]\\.[0-9]{4}:(none|[a-f0-9]{64})$'
                )
              )
            );
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_change_reason_is_bounded
            CHECK (reason IS NULL OR char_length(reason) BETWEEN 1 AND 64);
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_change_revision_id_shape
            CHECK (
              revision_id IS NULL
              OR revision_id ~ '^gnrev_[a-f0-9]{24}$'
            );

        CREATE UNIQUE INDEX one_goodnotes_run_occurrence_change
          ON knowledge.goodnotes_run_note_changes (
            principal_id, run_id, occurrence_id
          )
          WHERE occurrence_id IS NOT NULL;
        CREATE UNIQUE INDEX one_goodnotes_run_current_ambiguous_change
          ON knowledge.goodnotes_run_note_changes (
            principal_id, run_id, page_version_id, geometry_key
          )
          WHERE occurrence_id IS NULL;

        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_run_note_changes_occurrence_note_fk
            FOREIGN KEY (principal_id, occurrence_id, note_id)
            REFERENCES knowledge.goodnotes_note_occurrences (
              principal_id, occurrence_id, note_id
            )
            ON DELETE RESTRICT;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_run_note_changes_revision_fk
            FOREIGN KEY (principal_id, revision_id)
            REFERENCES knowledge.goodnotes_note_revisions (
              principal_id, revision_id
            )
            ON DELETE RESTRICT;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_run_note_changes_page_version_fk
            FOREIGN KEY (principal_id, page_version_id)
            REFERENCES knowledge.goodnotes_page_versions (
              principal_id, page_version_id
            )
            ON DELETE RESTRICT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_run_note_changes_page_version_fk;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_run_note_changes_revision_fk;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_run_note_changes_occurrence_note_fk;
        DROP INDEX IF EXISTS knowledge.one_goodnotes_run_current_ambiguous_change;
        DROP INDEX IF EXISTS knowledge.one_goodnotes_run_occurrence_change;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_change_revision_id_shape;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_change_reason_is_bounded;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_change_geometry_key_shape;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_change_page_version_id_shape;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP CONSTRAINT IF EXISTS goodnotes_change_identity_matches_state;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP COLUMN IF EXISTS revision_id;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP COLUMN IF EXISTS reason;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP COLUMN IF EXISTS geometry_key;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          DROP COLUMN IF EXISTS page_version_id;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ALTER COLUMN occurrence_id SET NOT NULL;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ALTER COLUMN note_id SET NOT NULL;
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT one_goodnotes_run_occurrence_change
            UNIQUE (principal_id, run_id, occurrence_id);
        ALTER TABLE knowledge.goodnotes_run_note_changes
          ADD CONSTRAINT goodnotes_run_note_changes_occurrence_fk
            FOREIGN KEY (principal_id, occurrence_id)
            REFERENCES knowledge.goodnotes_note_occurrences (
              principal_id, occurrence_id
            )
            ON DELETE RESTRICT;

        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP CONSTRAINT IF EXISTS goodnotes_note_revisions_snapshot_fk;
        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP CONSTRAINT IF EXISTS goodnotes_note_revisions_page_version_fk;
        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP CONSTRAINT IF EXISTS goodnotes_note_revisions_occurrence_note_fk;
        ALTER TABLE knowledge.goodnotes_note_revisions
          ADD CONSTRAINT goodnotes_note_revisions_occurrence_fk
            FOREIGN KEY (principal_id, occurrence_id)
            REFERENCES knowledge.goodnotes_note_occurrences (
              principal_id, occurrence_id
            )
            ON DELETE RESTRICT;
        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP CONSTRAINT IF EXISTS goodnotes_revision_snapshot_id_shape;
        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP CONSTRAINT IF EXISTS goodnotes_revision_page_version_id_shape;
        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP COLUMN IF EXISTS snapshot_id;
        ALTER TABLE knowledge.goodnotes_note_revisions
          DROP COLUMN IF EXISTS page_version_id;

        ALTER TABLE knowledge.goodnotes_note_occurrences
          DROP CONSTRAINT IF EXISTS goodnotes_note_occurrences_page_version_fk;
        ALTER TABLE knowledge.goodnotes_note_occurrences
          DROP CONSTRAINT IF EXISTS one_goodnotes_occurrence_note_pair;
        """
    )
