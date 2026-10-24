"""The Constraint part of `programs.overview` (record lineage S4 contract sections 3.2, 3.3).

Each resolved Project's 5 Constraint metrics are counted by
`ConstraintReadService.read_portfolio_overview` **unchanged**
(PC-CM-RUN01-WP06), on the Program read snapshot connection and at the
snapshot's own cutoff instant: each Project's dates are classified on its own
calendar (`constraint_project_settings.timezone_name`), and a Project with no
usable calendar is omitted by that read -- here it is disclosed as
`calendar_unconfigured`, never dropped and never given a substitute zone.

The **source state** that decides reportability is read from the stored sync
data (R4-F01), not from the overview's 3-way `sync_health`, which reads a
registered-but-never-verified target or a failed last run as `in_sync`; that
`ConstraintSyncHealthView` is still shown (`constraint_sync`) and decides
nothing. Statements: the portfolio read's 4 (settings, overview facts, the
2 of the sync summary) and 1 for the sync targets with their last run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from my_pa.application.constraints import ConstraintReadService
from my_pa.contracts.ports import ProgramReadUnitOfWork, ProgramSyncFacts
from my_pa.domain.program.reportability import (
    MetricId,
    constraint_source_state,
)
from my_pa.domain.program.vocabulary import ConstraintSourceState
from my_pa.domain.project_controls.read_models import (
    ConstraintOverview,
    ConstraintSyncHealthView,
    ConstraintSyncStateView,
)

__all__ = ["ProjectConstraintFacts", "read_constraint_facts"]

_READS: Final = ConstraintReadService()
_NO_SYNC: Final = ProgramSyncFacts(targets=(), open_conflicts=0, last_verified_at=None)


@dataclass(frozen=True, slots=True)
class ProjectConstraintFacts:
    """One Project's Constraint position in the snapshot (section 7.2 `per_project`)."""

    timezone_name: str | None
    project_today: date | None
    counts: Mapping[MetricId, int] | None
    source_state: ConstraintSourceState
    last_run_sync_states: tuple[str, ...]
    sync_health: ConstraintSyncHealthView


def _counts(overview: ConstraintOverview) -> Mapping[MetricId, int]:
    return {
        MetricId.CONSTRAINT_OPEN: overview.total_open,
        MetricId.CONSTRAINT_OVERDUE: overview.overdue,
        MetricId.CONSTRAINT_DUE_SOON: overview.due_soon,
        MetricId.CONSTRAINT_IN_MY_COURT: overview.in_my_court,
        MetricId.CONSTRAINT_DRAFT: overview.draft,
    }


def _health(sync: ProgramSyncFacts) -> ConstraintSyncHealthView:
    """The overview's 3-way roll-up for a Project the portfolio read omitted (no calendar).

    The same rule `_overview_of` applies, over the same stored facts.
    """
    if sync.open_conflicts > 0:
        state = ConstraintSyncStateView.CONFLICT
    elif not sync.targets:
        state = ConstraintSyncStateView.NEVER_SYNCED
    else:
        state = ConstraintSyncStateView.IN_SYNC
    return ConstraintSyncHealthView(
        state=state, open_conflict_count=sync.open_conflicts, last_verified_at=sync.last_verified_at
    )


def read_constraint_facts(
    unit_of_work: ProgramReadUnitOfWork,
    principal_id: str,
    project_ids: Sequence[str],
    *,
    cutoff: datetime,
) -> Mapping[str, ProjectConstraintFacts]:
    """Every requested Project's Constraint facts, read on the open snapshot at `cutoff`."""
    wanted = tuple(sorted(set(project_ids)))
    if not wanted:
        return {}
    portfolio = unit_of_work.guarded(
        lambda: _READS.read_portfolio_overview(
            unit_of_work.constraints, principal_id=principal_id, project_ids=wanted, now=cutoff
        )
    )
    overviews = {overview.project_id: overview for overview in portfolio.projects}
    sync = unit_of_work.program_metrics.sync_facts(principal_id, wanted)
    facts: dict[str, ProjectConstraintFacts] = {}
    for project_id in wanted:
        stored = sync.get(project_id, _NO_SYNC)
        overview = overviews.get(project_id)
        facts[project_id] = ProjectConstraintFacts(
            timezone_name=None if overview is None else overview.project_timezone,
            project_today=None if overview is None else overview.project_today,
            counts=None if overview is None else _counts(overview),
            source_state=constraint_source_state(
                calendar_configured=overview is not None,
                targets=stored.targets,
                open_conflicts=stored.open_conflicts,
            ),
            last_run_sync_states=tuple(
                sorted(
                    {
                        target.last_run_sync_state
                        for target in stored.targets
                        if target.last_run_sync_state is not None
                    }
                )
            ),
            sync_health=_health(stored) if overview is None else overview.sync_health,
        )
    return facts
