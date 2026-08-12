"""Merge the frozen-native and managed-document lineages without DDL.

The remediation candidate starts from the published ``main`` head
``a7c3e8d1f642`` and selectively carries the reviewed recovery/WP-28 lineage
through ``6b3d9a2f8c14``.  Both histories are immutable evidence.  This merge
revision records that the candidate contains both; it does not replay, rewrite,
or compensate either lineage.

Revision ID: c8f4a2d9e761
Revises: a7c3e8d1f642, 6b3d9a2f8c14
Created: 2026-08-12 05:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "c8f4a2d9e761"
down_revision: tuple[str, str] = ("a7c3e8d1f642", "6b3d9a2f8c14")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the two published histories; their revisions own all schema DDL."""


def downgrade() -> None:
    """Split the history marker without changing either branch's schema."""
