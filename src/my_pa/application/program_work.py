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

**The commit-time recompute (section 7.4, R4-F14).** `recompute_program_reference`
runs this same path for a committed artifact's Program reference block, with
the committing caller's families, on its own Program-pool snapshot under a hard
total budget of 5000 ms (the clock starts before the checkout), and returns the
manifest's `ProgramManifestSection`: the server's state beside the claim, or
the failure it met. A failure is recorded, never raised: a slow Program plane
cannot fail an Intelligence commit.

Nothing here writes: the snapshot transaction is read-only and rolled back.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Final

from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.program_constraints import ProjectConstraintFacts, read_constraint_facts
from my_pa.application.program_membership import PROGRAM_ROOT_FAMILIES, resolve_membership_in
from my_pa.contracts.ports import ProgramReadUnavailableError, ProgramReadUnitOfWork
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
from my_pa.domain.intelligence.source_manifest import (
    ProgramReferenceBlock,
    program_section,
    server_state,
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
    RecomputeFailure,
)
from my_pa.domain.situation.situation import ProjectState

__all__ = [
    "RECOMPUTE_BUDGET_SECONDS",
    "program_overview_in",
    "read_program_overview",
    "recompute_program_reference",
]

#: Section 7.4 (R4-F22): the hard total budget of one commit-time recompute.
RECOMPUTE_BUDGET_SECONDS: Final = 5.0

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
        unreviewed_issue_links=(
            None if facts.legacy_issue_links is None else facts.unreviewed_issue_links
        ),
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
    legacy: Mapping[str, tuple[int, int, int]] | None = None
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
        links = None if legacy is None else legacy.get(project_id, (0, 0, 0))
        facts[project_id] = ProjectFacts(
            project_id=project_id,
            commitment_counts=None if commitments is None else commitments.get(project_id, {}),
            issue_ids=None if issue_ids is None else frozenset(issue_ids[project_id]),
            legacy_issue_links=None if links is None else links[0],
            legacy_issue_links_closed=None if links is None else links[1],
            constraint_source_state=None if constraint is None else constraint.source_state,
            constraint_counts=None if constraint is None else constraint.counts,
            unreviewed_issue_links=None if links is None else links[2],
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


def _program_failure(error: ApplicationError) -> RecomputeFailure | None:
    """A Program the block names that is now absent (or invisible), or no longer a Program."""
    if SafeDetail.PROGRAM_ENTITY_IDS not in error.safe_details:
        return None
    if isinstance(error, NotFoundError):
        return RecomputeFailure.PROGRAM_NOT_FOUND
    if isinstance(error, (InvalidRequestError, ConflictError)):
        # Not program-typed, or a redirect chain that no longer resolves.
        return RecomputeFailure.PROGRAM_INVALID
    return None


def recompute_program_reference(
    unit_of_work_factory: Callable[[], ProgramReadUnitOfWork] | None,
    principal_id: str,
    block: ProgramReferenceBlock,
    *,
    families: frozenset[ProgramFamily],
) -> dict[str, object]:
    """Section 7.4 step 2-3: the manifest's Program section for one reference block.

    `unit_of_work_factory` is `None` when `programs.overview` is not served by
    this build or does not admit the committing caller (its remote grant
    re-check and the `entity` and `project` families): the section records
    `not_attempted` and nothing is read. Otherwise the `programs.overview`
    path runs with the caller's `families` under the 5000 ms total budget; the
    clock starts before the checkout (which waits at most the Program engine's
    1 s), and every statement runs under `min(2000, remaining)` ms. The
    server's `overview_sha256` equal to the claim is `verified_at_commit`, else
    `changed_since_read`; a spent budget, a statement timeout, no Program-pool
    connection, or a Program now absent or not program-typed is
    `recompute_failed` with its token. Any other fault propagates.
    """
    if unit_of_work_factory is None:
        return program_section(block)
    deadline = time.monotonic() + RECOMPUTE_BUDGET_SECONDS
    failure: RecomputeFailure | None = None
    try:
        with unit_of_work_factory() as unit_of_work:
            unit_of_work.limit_to_deadline(deadline)
            view = program_overview_in(
                unit_of_work, principal_id, block.program_entity_ids, families=families
            )
    except ProgramReadUnavailableError as error:
        if error.reason == "pool_unavailable":
            failure = RecomputeFailure.POOL_UNAVAILABLE
        elif error.reason == "budget_exceeded" or time.monotonic() >= deadline:
            # A statement cancelled at the remaining budget spent the budget.
            failure = RecomputeFailure.BUDGET_EXCEEDED
        else:
            failure = RecomputeFailure.STATEMENT_TIMEOUT
    except ApplicationError as error:
        failure = _program_failure(error)
        if failure is None:
            raise
    if failure is not None:
        return program_section(block, failure=failure)
    return program_section(
        block, server=server_state(view.to_canonical_dict()), families_seen=families
    )
