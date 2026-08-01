"""create the migration control plane

Creates the eight ledger tables in `migration_control` and seeds the ninth,
`identifier_map`, from `migrations/data/identifier_map.json`.

The tables are declared once, in
`my_pa.infrastructure.migration.control_plane`, and created from that
declaration here. The loader writes to the same declaration, so the schema this
revision applies and the schema the loader assumes cannot drift apart.

`identifier_map` is reference data rather than run data: it records the 473
identifiers the 63-byte budget or the neutral-naming rule forced the DDL
generator to rename (OD-013, OD-024), so a reader who queries for a legacy name
finds the mapping instead of concluding the column was lost. It is regenerated
by `scripts/migration/generate_target_schema.py` alongside the DDL.

It sits immediately after the tables and before the indexes and foreign keys,
because that is where the load runs. The load needs `migration_control` to
exist, and needs the indexes and the foreign keys *not* to: SQLite never
enforced its declared constraints, so the corpus may hold orphans that have to
be reported rather than allowed to abort a load (OD-017), and building indexes
after a bulk load is cheaper (OD-019). So the sequence is
`upgrade 4b9f0d27ac31`, load, `upgrade head`.

Revision ID: 4b9f0d27ac31
Revises: 1e6c0a94f3b7
Created: 2026-08-01 11:05:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

from my_pa.infrastructure.migration.control_plane import METADATA
from my_pa.infrastructure.migration.runs import seed_identifier_map

revision: str = "4b9f0d27ac31"
down_revision: str | None = "1e6c0a94f3b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IDENTIFIER_MAP = Path(__file__).resolve().parents[1] / "data" / "identifier_map.json"


def _renames() -> list[dict[str, str]]:
    document: dict[str, Any] = json.loads(IDENTIFIER_MAP.read_text(encoding="utf-8"))
    return [
        {str(key): str(value) for key, value in rename.items()} for rename in document["renames"]
    ]


def upgrade() -> None:
    bind = op.get_bind()
    METADATA.create_all(bind)
    seed_identifier_map(bind, _renames())


def downgrade() -> None:
    METADATA.drop_all(op.get_bind())
