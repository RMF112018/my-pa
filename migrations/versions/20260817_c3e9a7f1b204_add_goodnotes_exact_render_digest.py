"""Add exact visual render digest on GoodNotes page versions.

Revision ID: c3e9a7f1b204
Revises: e8c1b5a7d204
Create Date: 2026-08-17

RWP-01. Additive knowledge-schema DDL. Persists `exact_render_sha256` so page
identity can be the pinned visual raster rather than admitted raw bytes.
Nullable for legacy rows; this revision does not backfill invented hashes.
DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3e9a7f1b204"
down_revision: str | tuple[str, ...] | None = "e8c1b5a7d204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.goodnotes_page_versions
          ADD COLUMN exact_render_sha256 varchar(64);

        ALTER TABLE knowledge.goodnotes_page_versions
          ADD CONSTRAINT goodnotes_version_exact_render_sha256_shape
            CHECK (
              exact_render_sha256 IS NULL
              OR exact_render_sha256 ~ '^[a-f0-9]{64}$'
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.goodnotes_page_versions
          DROP CONSTRAINT IF EXISTS goodnotes_version_exact_render_sha256_shape;
        ALTER TABLE knowledge.goodnotes_page_versions
          DROP COLUMN IF EXISTS exact_render_sha256;
        """
    )
