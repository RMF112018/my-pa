"""Merge continuity-authoring and task-management migration heads.

Both `7c2e9b4a1d80` (user-directed continuity writes) and `a1c9e6f2b834`
(WP-TM-05 Commitment/Task/Follow-Up integration) were authored in parallel
from the same ancestor. Neither touches a table, column, index, or constraint
name the other defines, so this is a pure merge point with no schema changes
of its own.

Revision ID: 7504585e3ca5
Revises: 7c2e9b4a1d80, a1c9e6f2b834
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "7504585e3ca5"
down_revision: str | tuple[str, ...] | None = ("7c2e9b4a1d80", "a1c9e6f2b834")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
