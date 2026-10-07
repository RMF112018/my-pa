"""Admit three Morning Intelligence focus areas on the Intelligence Artifact plane.

Revision ID: 93f3aa113f58
Revises: 6734f039f7a6
Create Date: 2026-10-07

Restates the three server-named focus-area CHECKs that `e9b2c4d7a150` created
inline so they admit `captures`, `notes` and `field_intelligence` beside the
original six:

- `intelligence_producer_runs_focus_area_id_check` on
  `knowledge.intelligence_producer_runs`;
- `intelligence_artifacts_focus_area_id_check` on
  `knowledge.intelligence_artifacts`;
- `intelligence_pipeline_dependencies_expected_focus_area_id_check` on
  `knowledge.intelligence_pipeline_dependencies`.

The three new areas are admitted, not expected: cycle membership and the
morning-brief dependency count are catalog policy and are unchanged. Each CHECK
keeps its `IS NULL OR ... IN (...)` shape and keeps its server-generated name.

The vocabularies are frozen literals at this revision; nothing is imported from
the package (`D-48`, `D-69`). This revision creates no table, role, grant or row.

``downgrade`` restores the six-value CHECKs. It deletes nothing: while any row
still holds one of the three new values, re-adding the narrower CHECK fails with
`check_violation` and the downgrade stops. Removing those rows is an explicit
operator decision, never an implicit side effect of downgrading.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "93f3aa113f58"
down_revision: str | tuple[str, ...] | None = "6734f039f7a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"

#: (table, column, constraint name) for each focus-area CHECK.
_CHECKS: Final = (
    (
        "intelligence_producer_runs",
        "focus_area_id",
        "intelligence_producer_runs_focus_area_id_check",
    ),
    (
        "intelligence_artifacts",
        "focus_area_id",
        "intelligence_artifacts_focus_area_id_check",
    ),
    (
        "intelligence_pipeline_dependencies",
        "expected_focus_area_id",
        "intelligence_pipeline_dependencies_expected_focus_area_id_check",
    ),
)

_FOCUS_AREAS_BEFORE: Final = (
    "risk_deadline_exception",
    "decision_approval",
    "communications",
    "project_program_pulse",
    "watchlist_dependency",
    "action_commitment",
)

_FOCUS_AREAS_AFTER: Final = (
    "risk_deadline_exception",
    "decision_approval",
    "communications",
    "project_program_pulse",
    "watchlist_dependency",
    "action_commitment",
    "captures",
    "notes",
    "field_intelligence",
)


def _restate(vocabulary: tuple[str, ...]) -> None:
    literals = ", ".join(f"'{value}'" for value in vocabulary)
    for table, column, name in _CHECKS:
        op.execute(f'ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT "{name}"')
        op.execute(
            f'ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT "{name}" '
            f"CHECK ({column} IS NULL OR {column} IN ({literals}))"
        )


def upgrade() -> None:
    _restate(_FOCUS_AREAS_AFTER)


def downgrade() -> None:
    _restate(_FOCUS_AREAS_BEFORE)
