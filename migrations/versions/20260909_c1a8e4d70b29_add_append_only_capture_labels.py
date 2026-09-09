"""Add append-only capture display labels.

Revision ID: c1a8e4d70b29
Revises: b8e4d6f20a11
Create Date: 2026-09-09

One additive table: `knowledge.capture_labels` holds caller-supplied list-safe
titles for product-owned captures. The current label is the latest row for a
capture, or absent when none exists. Nothing here updates `captures` and
nothing copies `capture_versions.content`. Search matching on a label is out
of this revision; the closed audit vocabularies are unchanged.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c1a8e4d70b29"
down_revision: str | None = "b8e4d6f20a11"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"
_IMMUTABILITY_FUNCTION: Final = "capture_labels_stay_as_written"
_IMMUTABILITY_TRIGGER: Final = "capture_labels_are_append_only"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.capture_labels (
          label_id text NOT NULL,
          capture_id text NOT NULL,
          owner_principal_id text NOT NULL,
          display_label text NOT NULL,
          recorded_at timestamp with time zone NOT NULL DEFAULT now(),
          PRIMARY KEY (label_id),
          CONSTRAINT capture_labels_capture_id_fkey
            FOREIGN KEY (capture_id) REFERENCES {SCHEMA}.captures (capture_id)
            ON DELETE CASCADE,
          CONSTRAINT label_id_is_an_opaque_identifier
            CHECK (label_id ~ '^clbl_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT owner_principal_id_is_an_opaque_identifier
            CHECK (owner_principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT capture_display_label_is_bounded
            CHECK (char_length(display_label) BETWEEN 1 AND 120)
        )
        """
    )
    op.execute(
        f"CREATE INDEX capture_labels_by_capture ON {SCHEMA}.capture_labels "
        "(capture_id, recorded_at, label_id)"
    )
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'knowledge.capture_labels is append only; % is refused', TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    op.execute(
        f"CREATE TRIGGER {_IMMUTABILITY_TRIGGER} "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.capture_labels "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_IMMUTABILITY_TRIGGER} ON {SCHEMA}.capture_labels")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.capture_labels")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")
