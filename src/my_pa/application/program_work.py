"""`programs.overview` (record lineage S4 contract sections 3.2-3.4, 5.1, 6.2 and 7.2, WP-04B).

The operational position of 1..10 Programs' resolved Projects -- Commitments,
Issues and Constraints -- per Project, per Program and per portfolio, from
**one** `REPEATABLE READ, READ ONLY` snapshot on the Program read pool
(section 6.3): the membership resolution (`resolve_membership_in`, current
mode), then the Commitment aggregates, the outstanding Issue pairs, the legacy
Issue links, and the Constraint facts (`program_constraints`), each one
statement for the whole Project set. So every figure and the membership are
equal at the one cutoff `source_cutoff_at` by construction (section 3.4).

Totals are distinct counts, reported only when complete enough (OD-08,
`domain.program.reportability`); `overview_sha256` is section 5.1's digest of
the answer as served.

**Visibility (section 6.2).** A local caller sees every family. A remote
caller needs `entity` and `project` to see any Program (`not_found`
otherwise, before any read); a family it does not see is not read at all,
its metrics are `restricted` at every scope and every field derived from it
is `null` (`lineage_known_at` and the legacy-link fields with `issue`, the
calendar, source state, sync and source-state denominator with
`constraint`), and the answer carries `restricted_evidence`.

Nothing here writes: the snapshot transaction is read-only and rolled back.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence

from my_pa.application.errors import NotFoundError, SafeDetail
from my_pa.application.program_constraints import ProjectConstraintFacts, read_constraint_facts
from my_pa.application.program_membership import PROGRAM_ROOT_FAMILIES, resolve_membership_in
from my_pa.contracts.ports import ProgramReadUnitOfWork
from my_pa.contracts.v1.programs import (
    ConstraintSyncView,
    MetricView,
    OverviewPortfolioView,
    OverviewProgramView,
    OverviewProjectView,
    ProgramOverviewView,
    ProjectCalendarView,
    program_instant,
)
from my_pa.domain.program.digest import overview_digest
from my_pa.domain.program.membership import ProgramResolution, completeness
from my_pa.domain.program.reportability import (
    METRIC_CATALOGUE,
    MetricValue,
    ProjectFacts,
    project_metric,
    scope_denominator,
    scope_total,
)
from my_pa.domain.program.vocabulary import (
    PROGRAM_CALCULATION_VERSION,
    PROGRAM_METRIC_SCHEMA_VERSION,
    ProgramCompleteness,
    ProgramFamily,
)
from my_pa.domain.situation.situation import ProjectState

__all__ = ["program_overview_in", "read_program_overview"]

#: The 3 families the overview's metrics derive from; any one invisible makes
#: the answer `restricted_evidence`.
_METRIC_FAMILIES: frozenset[ProgramFamily] = frozenset(
    {ProgramFamily.COMMITMENT, ProgramFamily.ISSUE, ProgramFamily.CONSTRAINT}
)
#: A placeholder digest, replaced once the answer it digests is complete.
_UNDIGESTED = "0" * 64


def _totals(
    projects: Sequence[ProjectFacts],
    *,
    visible: Collection[ProgramFamily],
    unresolved: bool,
    truncated: bool,
) -> tuple[MetricValue, ...]:
    return tuple(
        scope_total(
            row.metric_id,
            projects,
            visible=visible,
            membership_unresolved=unresolved,
            membership_truncated=truncated,
        )
        for row in METRIC_CATALOGUE
    )


def _project_view(
    facts: ProjectFacts,
    *,
    project_state: str,
    constraint: ProjectConstraintFacts | None,
    visible: Collection[ProgramFamily],
) -> OverviewProjectView:
    return OverviewProjectView(
        project_id=facts.project_id,
        project_state=ProjectState(project_state),
        calendar=(
            None
            if constraint is None
            else ProjectCalendarView.of(constraint.timezone_name, constraint.project_today)
        ),
        constraint_source_state=None if constraint is None else constraint.source_state,
        constraint_last_run_sync_states=(
            None if constraint is None else constraint.last_run_sync_states
        ),
        constraint_sync=(
            None if constraint is None else ConstraintSyncView.of(constraint.sync_health)
        ),
        legacy_issue_links=facts.legacy_issue_links,
        legacy_issue_links_closed=facts.legacy_issue_links_closed,
        metrics=tuple(
            MetricView.of(project_metric(row.metric_id, facts, visible=visible))
            for row in METRIC_CATALOGUE
        ),
    )


def program_overview_in(
    unit_of_work: ProgramReadUnitOfWork,
    principal_id: str,
    program_entity_ids: Sequence[str],
    *,
    families: frozenset[ProgramFamily],
) -> ProgramOverviewView:
    """Sections 3.2-3.4 and 7.2 inside an open Program read unit of work.

    The caller has already applied the section 6.2 root-family rule. Takes the
    snapshot (its first query) if it is not taken yet; every later statement
    reads that snapshot.
    """
    snapshot, resolution = resolve_membership_in(unit_of_work, principal_id, program_entity_ids)
    cutoff = snapshot.source_cutoff_at
    project_ids = resolution.portfolio.project_ids
    project_states = {
        member.project_id: member.project_state
        for program in resolution.programs
        for member in program.members
    }
    metrics = unit_of_work.program_metrics
    commitments = (
        metrics.commitment_counts(principal_id, project_ids, cutoff=cutoff)
        if ProgramFamily.COMMITMENT in families
        else None
    )
    issue_ids: dict[str, set[str]] | None = None
    legacy: Mapping[str, tuple[int, int]] | None = None
    if ProgramFamily.ISSUE in families:
        issue_ids = {project_id: set() for project_id in project_ids}
        for project_id, issue_id in metrics.outstanding_issue_links(principal_id, project_ids):
            issue_ids[project_id].add(issue_id)
        legacy = metrics.legacy_issue_links(principal_id, project_ids)
    constraints = (
        read_constraint_facts(unit_of_work, principal_id, project_ids, cutoff=cutoff)
        if ProgramFamily.CONSTRAINT in families
        else None
    )

    facts: dict[str, ProjectFacts] = {}
    for project_id in project_ids:
        constraint = None if constraints is None else constraints[project_id]
        links = None if legacy is None else legacy.get(project_id, (0, 0))
        facts[project_id] = ProjectFacts(
            project_id=project_id,
            commitment_counts=None if commitments is None else commitments.get(project_id, {}),
            issue_ids=None if issue_ids is None else frozenset(issue_ids[project_id]),
            legacy_issue_links=None if links is None else links[0],
            legacy_issue_links_closed=None if links is None else links[1],
            constraint_source_state=None if constraint is None else constraint.source_state,
            constraint_counts=None if constraint is None else constraint.counts,
        )

    def scope(program: ProgramResolution) -> OverviewProgramView:
        members = [facts[member.project_id] for member in program.members]
        return OverviewProgramView.of(
            program,
            denominator=scope_denominator(
                members, unresolved_members=len(program.unresolved_members), visible=families
            ),
            totals=_totals(
                members,
                visible=families,
                unresolved=bool(program.unresolved_members),
                truncated=ProgramCompleteness.TRUNCATED_BUDGET in program.qualifiers,
            ),
        )

    # The portfolio counts each resolved Program's unresolved edges once, even
    # when 2 requested ids name the one Program.
    unresolved_edges = {
        (program.resolved_program_entity_id, member.relationship_id)
        for program in resolution.programs
        for member in program.unresolved_members
    }
    portfolio_facts = [facts[project_id] for project_id in project_ids]
    portfolio = OverviewPortfolioView.of(
        resolution,
        denominator=scope_denominator(
            portfolio_facts, unresolved_members=len(unresolved_edges), visible=families
        ),
        totals=_totals(
            portfolio_facts,
            visible=families,
            unresolved=bool(unresolved_edges),
            truncated=ProgramCompleteness.TRUNCATED_BUDGET in resolution.qualifiers,
        ),
    )
    codes = set(resolution.qualifiers)
    if not families >= _METRIC_FAMILIES:
        codes.add(ProgramCompleteness.RESTRICTED_EVIDENCE)
    complete_state, qualifiers = completeness(codes)
    horizon = snapshot.lineage_known_at if ProgramFamily.ISSUE in families else None
    view = ProgramOverviewView(
        source_cutoff_at=program_instant(cutoff),
        lineage_known_at=None if horizon is None else program_instant(horizon),
        metric_schema_version=PROGRAM_METRIC_SCHEMA_VERSION,
        calculation_version=PROGRAM_CALCULATION_VERSION,
        programs=tuple(scope(program) for program in resolution.programs),
        portfolio=portfolio,
        per_project=tuple(
            _project_view(
                facts[project_id],
                project_state=project_states[project_id],
                constraint=None if constraints is None else constraints[project_id],
                visible=families,
            )
            for project_id in project_ids
        ),
        complete_state=complete_state,
        qualifiers=qualifiers,
        overview_sha256=_UNDIGESTED,
    )
    return view.model_copy(update={"overview_sha256": overview_digest(view.to_canonical_dict())})


def read_program_overview(
    unit_of_work_factory: Callable[[], ProgramReadUnitOfWork],
    principal_id: str,
    program_entity_ids: Sequence[str],
    *,
    families: frozenset[ProgramFamily],
) -> ProgramOverviewView:
    """`programs.overview` (section 7.2), on its own Program read snapshot.

    A caller that does not see both the `entity` and the `project` family sees
    no Program: `not_found` / `program_entity_ids`, before any read.
    """
    if not families >= PROGRAM_ROOT_FAMILIES:
        raise NotFoundError(SafeDetail.PROGRAM_ENTITY_IDS)
    with unit_of_work_factory() as unit_of_work:
        return program_overview_in(
            unit_of_work, principal_id, program_entity_ids, families=families
        )
