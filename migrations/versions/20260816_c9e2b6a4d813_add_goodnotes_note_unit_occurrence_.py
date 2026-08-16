"""Add additive GoodNotes NOTE_UNIT occurrence, revision, and run-change persistence.

Revision ID: c9e2b6a4d813
Revises: f8c3a1e6b247
Created: 2026-08-16

Additive knowledge-schema DDL. A PDF is not a note; a page is not a note.
Printed or typed agenda/body is SOURCE_CONTEXT, not operator-authored note text.
Physical occurrence identity is the persisted `geometry_key` (canonical
4-decimal normalized box plus crop digest or `none`); transcription and
semantic similarity are supporting evidence only and are not the unique key.
The same words written separately may be two occurrences. Revisions and
run-change rows are append-only. Closed-set CHECK literals are frozen here
(`D-69`). DDL is written out rather than imported from persistence modules
(`D-48`). Existing ordinal `goodnotes_pages` / OCR `goodnotes_region_proposals`
are unchanged. `gnreg` is not reused for NOTE_UNIT occurrences.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c9e2b6a4d813"
down_revision: str | tuple[str, ...] | None = "f8c3a1e6b247"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge.goodnotes_notes (
          principal_id varchar(72) NOT NULL,
          note_id varchar(36) NOT NULL
            CHECK (note_id ~ '^gnnt_[a-f0-9]{24}$'),
          notebook_id varchar(36) NOT NULL,
          identity_status varchar(16) NOT NULL
            CHECK (identity_status IN ('ACTIVE', 'AMBIGUOUS', 'RETIRED')),
          primary_class varchar(16)
            CHECK (
              primary_class IS NULL
              OR primary_class IN (
                'MEETING', 'PROJECT', 'RELATIONSHIP', 'GENERAL'
              )
            ),
          created_at timestamptz NOT NULL,
          last_seen_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_notes_pkey PRIMARY KEY (principal_id, note_id),
          CONSTRAINT goodnotes_note_seen_after_creation
            CHECK (last_seen_at >= created_at),
          CONSTRAINT goodnotes_notes_notebook_fk
            FOREIGN KEY (principal_id, notebook_id)
            REFERENCES knowledge.goodnotes_notebooks (principal_id, notebook_id)
            ON DELETE RESTRICT
        );

        CREATE TABLE knowledge.goodnotes_note_occurrences (
          principal_id varchar(72) NOT NULL,
          occurrence_id varchar(36) NOT NULL
            CHECK (occurrence_id ~ '^gnocc_[a-f0-9]{24}$'),
          note_id varchar(36) NOT NULL,
          logical_page_id varchar(36) NOT NULL,
          page_version_id varchar(30)
            CHECK (
              page_version_id IS NULL
              OR page_version_id ~ '^gnver_[a-f0-9]{24}$'
            ),
          snapshot_id varchar(36)
            CHECK (
              snapshot_id IS NULL
              OR snapshot_id ~ '^gnsnap_[a-f0-9]{24}$'
            ),
          run_id varchar(36)
            CHECK (
              run_id IS NULL
              OR run_id ~ '^gnrun_[a-f0-9]{24}$'
            ),
          x_min numeric(5, 4) NOT NULL,
          y_min numeric(5, 4) NOT NULL,
          width numeric(5, 4) NOT NULL,
          height numeric(5, 4) NOT NULL,
          geometry_key varchar(96) NOT NULL
            CHECK (
              char_length(geometry_key) BETWEEN 1 AND 96
              AND geometry_key ~ (
                '^[0-9]\\.[0-9]{4},[0-9]\\.[0-9]{4},[0-9]\\.[0-9]{4},'
                '[0-9]\\.[0-9]{4}:(none|[a-f0-9]{64})$'
              )
            ),
          crop_sha256 varchar(64)
            CHECK (
              crop_sha256 IS NULL
              OR crop_sha256 ~ '^[a-f0-9]{64}$'
            ),
          context_anchor_sha256 varchar(64)
            CHECK (
              context_anchor_sha256 IS NULL
              OR context_anchor_sha256 ~ '^[a-f0-9]{64}$'
            ),
          identity_status varchar(16) NOT NULL
            CHECK (identity_status IN ('ACTIVE', 'AMBIGUOUS', 'RETIRED')),
          created_at timestamptz NOT NULL,
          last_seen_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_note_occurrences_pkey
            PRIMARY KEY (principal_id, occurrence_id),
          CONSTRAINT one_goodnotes_occurrence_geometry
            UNIQUE (principal_id, logical_page_id, geometry_key),
          CONSTRAINT goodnotes_occurrence_geometry_is_normalized
            CHECK (
              x_min >= 0 AND x_min <= 1
              AND y_min >= 0 AND y_min <= 1
              AND width > 0 AND width <= 1
              AND height > 0 AND height <= 1
              AND x_min + width <= 1
              AND y_min + height <= 1
            ),
          CONSTRAINT goodnotes_occurrence_seen_after_creation
            CHECK (last_seen_at >= created_at),
          CONSTRAINT goodnotes_note_occurrences_note_fk
            FOREIGN KEY (principal_id, note_id)
            REFERENCES knowledge.goodnotes_notes (principal_id, note_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_occurrences_logical_page_fk
            FOREIGN KEY (principal_id, logical_page_id)
            REFERENCES knowledge.goodnotes_logical_pages (
              principal_id, logical_page_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_occurrences_snapshot_fk
            FOREIGN KEY (principal_id, snapshot_id)
            REFERENCES knowledge.goodnotes_source_snapshots (
              principal_id, snapshot_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_occurrences_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES knowledge.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT
        );

        CREATE TABLE knowledge.goodnotes_note_revisions (
          principal_id varchar(72) NOT NULL,
          revision_id varchar(36) NOT NULL
            CHECK (revision_id ~ '^gnrev_[a-f0-9]{24}$'),
          note_id varchar(36) NOT NULL,
          occurrence_id varchar(36)
            CHECK (
              occurrence_id IS NULL
              OR occurrence_id ~ '^gnocc_[a-f0-9]{24}$'
            ),
          supersedes_revision_id varchar(36)
            CHECK (
              supersedes_revision_id IS NULL
              OR supersedes_revision_id ~ '^gnrev_[a-f0-9]{24}$'
            ),
          schema_version varchar(40) NOT NULL
            CHECK (char_length(schema_version) BETWEEN 1 AND 40),
          analyzer_name varchar(100) NOT NULL
            CHECK (char_length(analyzer_name) BETWEEN 1 AND 100),
          analyzer_version varchar(100) NOT NULL
            CHECK (char_length(analyzer_version) BETWEEN 1 AND 100),
          transcription text NOT NULL
            CHECK (char_length(transcription) BETWEEN 1 AND 20000),
          primary_class varchar(16)
            CHECK (
              primary_class IS NULL
              OR primary_class IN (
                'MEETING', 'PROJECT', 'RELATIONSHIP', 'GENERAL'
              )
            ),
          created_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_note_revisions_pkey
            PRIMARY KEY (principal_id, revision_id),
          CONSTRAINT goodnotes_note_revisions_note_fk
            FOREIGN KEY (principal_id, note_id)
            REFERENCES knowledge.goodnotes_notes (principal_id, note_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_revisions_occurrence_fk
            FOREIGN KEY (principal_id, occurrence_id)
            REFERENCES knowledge.goodnotes_note_occurrences (
              principal_id, occurrence_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_revisions_supersedes_fk
            FOREIGN KEY (principal_id, supersedes_revision_id)
            REFERENCES knowledge.goodnotes_note_revisions (
              principal_id, revision_id
            )
            ON DELETE RESTRICT
        );

        CREATE TABLE knowledge.goodnotes_note_links (
          principal_id varchar(72) NOT NULL,
          link_id varchar(36) NOT NULL
            CHECK (link_id ~ '^gnlink_[a-f0-9]{24}$'),
          note_id varchar(36) NOT NULL,
          link_kind varchar(32) NOT NULL
            CHECK (link_kind IN (
              'NOTE_TO_NOTE',
              'NOTE_TO_LOGICAL_PAGE',
              'NOTE_TO_SOURCE_CONTEXT',
              'OCCURRENCE_TO_OCCURRENCE'
            )),
          target_note_id varchar(36)
            CHECK (
              target_note_id IS NULL
              OR target_note_id ~ '^gnnt_[a-f0-9]{24}$'
            ),
          target_logical_page_id varchar(36)
            CHECK (
              target_logical_page_id IS NULL
              OR target_logical_page_id ~ '^gnlp_[a-f0-9]{24}$'
            ),
          target_occurrence_id varchar(36)
            CHECK (
              target_occurrence_id IS NULL
              OR target_occurrence_id ~ '^gnocc_[a-f0-9]{24}$'
            ),
          target_context_anchor_sha256 varchar(64)
            CHECK (
              target_context_anchor_sha256 IS NULL
              OR target_context_anchor_sha256 ~ '^[a-f0-9]{64}$'
            ),
          target_key varchar(80) NOT NULL
            CHECK (
              char_length(target_key) BETWEEN 1 AND 80
              AND target_key ~ (
                '^(note:gnnt_[a-f0-9]{24}|page:gnlp_[a-f0-9]{24}|'
                'occ:gnocc_[a-f0-9]{24}|ctx:[a-f0-9]{64})$'
              )
            ),
          created_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_note_links_pkey
            PRIMARY KEY (principal_id, link_id),
          CONSTRAINT one_goodnotes_note_link_target
            UNIQUE (principal_id, note_id, link_kind, target_key),
          CONSTRAINT goodnotes_note_link_target_matches_kind
            CHECK (
              (
                link_kind = 'NOTE_TO_NOTE'
                AND target_note_id IS NOT NULL
                AND target_logical_page_id IS NULL
                AND target_occurrence_id IS NULL
                AND target_context_anchor_sha256 IS NULL
              )
              OR (
                link_kind = 'NOTE_TO_LOGICAL_PAGE'
                AND target_note_id IS NULL
                AND target_logical_page_id IS NOT NULL
                AND target_occurrence_id IS NULL
                AND target_context_anchor_sha256 IS NULL
              )
              OR (
                link_kind = 'NOTE_TO_SOURCE_CONTEXT'
                AND target_note_id IS NULL
                AND target_logical_page_id IS NULL
                AND target_occurrence_id IS NULL
                AND target_context_anchor_sha256 IS NOT NULL
              )
              OR (
                link_kind = 'OCCURRENCE_TO_OCCURRENCE'
                AND target_note_id IS NULL
                AND target_logical_page_id IS NULL
                AND target_occurrence_id IS NOT NULL
                AND target_context_anchor_sha256 IS NULL
              )
            ),
          CONSTRAINT goodnotes_note_links_note_fk
            FOREIGN KEY (principal_id, note_id)
            REFERENCES knowledge.goodnotes_notes (principal_id, note_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_links_target_note_fk
            FOREIGN KEY (principal_id, target_note_id)
            REFERENCES knowledge.goodnotes_notes (principal_id, note_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_links_target_logical_page_fk
            FOREIGN KEY (principal_id, target_logical_page_id)
            REFERENCES knowledge.goodnotes_logical_pages (
              principal_id, logical_page_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_note_links_target_occurrence_fk
            FOREIGN KEY (principal_id, target_occurrence_id)
            REFERENCES knowledge.goodnotes_note_occurrences (
              principal_id, occurrence_id
            )
            ON DELETE RESTRICT
        );

        CREATE TABLE knowledge.goodnotes_run_note_changes (
          principal_id varchar(72) NOT NULL,
          change_id varchar(36) NOT NULL
            CHECK (change_id ~ '^gnchg_[a-f0-9]{24}$'),
          run_id varchar(36) NOT NULL,
          note_id varchar(36) NOT NULL,
          occurrence_id varchar(36) NOT NULL,
          change_state varchar(32) NOT NULL
            CHECK (change_state IN (
              'NEW',
              'UNCHANGED',
              'REVISED',
              'REMOVED_OR_NO_LONGER_PRESENT',
              'AMBIGUOUS'
            )),
          created_at timestamptz NOT NULL,
          CONSTRAINT goodnotes_run_note_changes_pkey
            PRIMARY KEY (principal_id, change_id),
          CONSTRAINT one_goodnotes_run_occurrence_change
            UNIQUE (principal_id, run_id, occurrence_id),
          CONSTRAINT goodnotes_run_note_changes_run_fk
            FOREIGN KEY (principal_id, run_id)
            REFERENCES knowledge.goodnotes_ingestion_runs (
              principal_id, run_id
            )
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_run_note_changes_note_fk
            FOREIGN KEY (principal_id, note_id)
            REFERENCES knowledge.goodnotes_notes (principal_id, note_id)
            ON DELETE RESTRICT,
          CONSTRAINT goodnotes_run_note_changes_occurrence_fk
            FOREIGN KEY (principal_id, occurrence_id)
            REFERENCES knowledge.goodnotes_note_occurrences (
              principal_id, occurrence_id
            )
            ON DELETE RESTRICT
        );

        CREATE TRIGGER goodnotes_note_revisions_are_immutable
          BEFORE UPDATE OR DELETE ON knowledge.goodnotes_note_revisions
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();

        CREATE TRIGGER goodnotes_run_note_changes_are_immutable
          BEFORE UPDATE OR DELETE ON knowledge.goodnotes_run_note_changes
          FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS goodnotes_run_note_changes_are_immutable
          ON knowledge.goodnotes_run_note_changes;
        DROP TRIGGER IF EXISTS goodnotes_note_revisions_are_immutable
          ON knowledge.goodnotes_note_revisions;
        DROP TABLE IF EXISTS knowledge.goodnotes_run_note_changes;
        DROP TABLE IF EXISTS knowledge.goodnotes_note_links;
        DROP TABLE IF EXISTS knowledge.goodnotes_note_revisions;
        DROP TABLE IF EXISTS knowledge.goodnotes_note_occurrences;
        DROP TABLE IF EXISTS knowledge.goodnotes_notes;
        """
    )
