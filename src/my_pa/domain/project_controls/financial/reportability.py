"""Financial controlled source F-1: admission, resolution and the evaluator (sections 3.7-3.10, 5).

`admit_source_run` turns a parser outcome into an admitted or refused run.
`resolve_source_version` is section 3.7 for 1 designated system and 1 scope
key; `resolve_project_mapping` is section 3.8; `evaluate_financial_overview`
is the section 5.3 algorithm. Every gap is material: there is no threshold,
tolerance or materiality parameter (OD-08). Without a designation covering the
request perspective the answer is `source_not_integrated`, never a fabricated
zero. Input order never matters: every input is sorted canonically first.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from my_pa.domain.project_controls.financial.canonical import source_content_sha256
from my_pa.domain.project_controls.financial.equations import (
    FinancialInvariantError,
    compute_project,
    consolidate_metric,
    external_transfer_amounts,
    internal_transfers,
    not_reportable,
    project_has_rows,
    repeats_a_ref_across_versions,
)
from my_pa.domain.project_controls.financial.model import (
    CALCULATION_VERSION,
    METRICS_BY_PERSPECTIVE,
    SOURCE_STATE_PRECEDENCE,
    AdmissionRefusalCode,
    CostBasis,
    FinanceParseOutcome,
    FinanceParseRefusalCode,
    FinancialDenominator,
    FinancialMetric,
    FinancialMetricValue,
    FinancialNotReportableReason,
    FinancialOverview,
    FinancialPerspective,
    FinancialReportability,
    FinancialScopeRequest,
    FinancialSourceState,
    MappingState,
    ProjectFinancialFigures,
    ProjectMappingRevision,
    RunOutcome,
    SourceDesignation,
    SourceRun,
    SourceVersion,
    SourceVersionStatus,
    TransferElimination,
)

__all__ = [
    "MappingResolution",
    "VersionResolution",
    "admit_source_run",
    "current_mapping_revisions",
    "evaluate_financial_overview",
    "resolve_project_mapping",
    "resolve_source_version",
    "source_state_of",
]

_R = FinancialNotReportableReason


def _version(run: SourceRun) -> SourceVersion:
    if run.version is None:
        raise FinancialInvariantError("an admitted run carries its version")
    return run.version


def _content(run: SourceRun) -> str:
    if run.content_sha256 is None:
        raise FinancialInvariantError("an admitted run carries its content digest")
    return run.content_sha256


# --- run admission (section 3.10) ---------------------------------------------------


def admit_source_run(
    run_ref: str,
    run_sequence: int,
    designation: SourceDesignation,
    file_sha256: str,
    outcome: FinanceParseOutcome,
) -> SourceRun:
    """A parser refusal is a refused run; a parsed version is checked against the designation."""
    if outcome.file_sha256 != file_sha256:
        raise ValueError("the parse outcome belongs to another file")
    system = designation.source_system

    def refused(
        code: FinanceParseRefusalCode | AdmissionRefusalCode, line: int | None
    ) -> SourceRun:
        return SourceRun(
            run_ref, run_sequence, system, file_sha256, RunOutcome.REFUSED, code, line, None, None
        )

    version = outcome.admitted
    if version is None:
        if outcome.refusal_code is None:
            raise ValueError("a parse outcome without a version carries its refusal")
        return refused(outcome.refusal_code, outcome.refusal_line)
    if version.source_system != system:
        return refused(AdmissionRefusalCode.SOURCE_SYSTEM_MISMATCH, None)
    if version.perspective not in designation.perspectives:
        return refused(AdmissionRefusalCode.PERSPECTIVE_NOT_DESIGNATED, None)
    return SourceRun(
        run_ref,
        run_sequence,
        system,
        file_sha256,
        RunOutcome.ADMITTED,
        None,
        None,
        version,
        source_content_sha256(version),
    )


# --- version resolution (section 3.7) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionResolution:
    """The section 3.7 outcome of 1 system for 1 scope key.

    `reasons` are the project-level reasons every Project mapped from the
    system receives; `effective` is `None` unless exactly 1 approved head stands.
    """

    effective: SourceVersion | None
    effective_content_sha256: str | None
    reasons: frozenset[FinancialNotReportableReason]
    pending_source_versions: tuple[str, ...]


def _refusal_reason(run: SourceRun) -> FinancialNotReportableReason:
    if run.refusal_code is FinanceParseRefusalCode.PARTIAL_EXPORT:
        return _R.PARTIAL_EXPORT
    if run.refusal_code is FinanceParseRefusalCode.HASH_MISMATCH:
        return _R.HASH_MISMATCH
    return _R.SOURCE_REFUSED


def _classify_missing_scope(
    versions: Iterable[SourceVersion],
    period: str,
    perspective: FinancialPerspective,
    cost_basis: CostBasis,
) -> frozenset[FinancialNotReportableReason]:
    """Section 5.3 step 6: the nearest existing versions of the system."""
    existing = list(versions)
    if any(
        v.period == period and v.perspective is perspective and v.cost_basis is cost_basis
        for v in existing
    ):
        return frozenset({_R.CURRENCY_MISMATCH, _R.FX_MISSING})
    if any(v.period == period and v.perspective is perspective for v in existing):
        return frozenset({_R.BASIS_MISMATCH})
    if any(v.period == period for v in existing):
        return frozenset({_R.PERSPECTIVE_MISMATCH})
    if existing:
        return frozenset({_R.PERIOD_MISMATCH})
    return frozenset({_R.SOURCE_VERSION_MISSING})


def _has_cycle(successor: Mapping[str, str | None]) -> bool:
    for start in successor:
        seen: set[str] = set()
        node: str | None = start
        while node is not None:
            if node in seen:
                return True
            seen.add(node)
            node = successor[node]
    return False


def resolve_source_version(
    designation: SourceDesignation,
    runs: Sequence[SourceRun],
    request: FinancialScopeRequest,
) -> VersionResolution:
    """Section 3.7 for the designated system over its non-quarantined runs."""
    system = designation.source_system
    own = sorted(
        (run for run in runs if run.designated_source_system == system),
        key=lambda run: run.run_sequence,
    )
    admitted = [run for run in own if run.outcome is RunOutcome.ADMITTED]
    refused = [run for run in own if run.outcome is RunOutcome.REFUSED]

    # Step 1: a ref carrying 2 contents anywhere in the system is terminal.
    contents_by_ref: dict[str, set[str]] = {}
    for run in admitted:
        contents_by_ref.setdefault(_version(run).source_version_ref, set()).add(_content(run))
    if any(len(contents) > 1 for contents in contents_by_ref.values()):
        return VersionResolution(None, None, frozenset({_R.SOURCE_VERSION_CONFLICT}), ())

    # Step 1a: the as-of filter on the export's self-asserted data cutoff.
    if request.source_cutoff is not None:
        cutoff = request.source_cutoff
        admitted = [run for run in admitted if _version(run).cutoff_at <= cutoff]

    runs_by_content: dict[str, list[SourceRun]] = {}
    for run in admitted:
        runs_by_content.setdefault(_content(run), []).append(run)
    # The admitting run of a version is the latest run carrying its content.
    admitting = {content: group[-1] for content, group in runs_by_content.items()}
    versions = {content: _version(run) for content, run in admitting.items()}

    scope = (system, request.period, request.perspective, request.currency, request.cost_basis)
    in_scope = {c: v for c, v in versions.items() if v.scope_key == scope}
    pending = tuple(
        sorted(c for c, v in in_scope.items() if v.status is SourceVersionStatus.PROPOSED)
    )
    reasons: set[FinancialNotReportableReason] = set()
    effective: str | None = None

    if not in_scope:
        reasons |= _classify_missing_scope(
            versions.values(), request.period, request.perspective, request.cost_basis
        )
    else:
        # Steps 2-3: supersession graph and heads (proposed never supersedes).
        content_by_ref = {v.source_version_ref: c for c, v in in_scope.items()}
        successor: dict[str, str | None] = {}
        for content, version in in_scope.items():
            target = None
            if version.status is not SourceVersionStatus.PROPOSED and version.supersedes_ref:
                target = content_by_ref.get(version.supersedes_ref)
            successor[content] = target
        superseded = {target for target in successor.values() if target is not None}
        heads = [c for c in in_scope if c not in superseded]
        approved = [c for c in heads if in_scope[c].status is SourceVersionStatus.APPROVED]
        withdrawn = [c for c in heads if in_scope[c].status is SourceVersionStatus.WITHDRAWN]
        if _has_cycle(successor) or len(approved) >= 2 or (len(approved) == 1 and withdrawn):
            reasons.add(_R.SOURCE_VERSION_AMBIGUOUS)
        elif len(approved) == 1:
            effective = approved[0]
        elif withdrawn:
            reasons.add(_R.WITHDRAWN_SOURCE)
        else:
            reasons.add(_R.APPROVAL_MISSING)

    effective_version = None if effective is None else in_scope[effective]
    if effective_version is not None:
        # Step 5: approval consistency (self-asserted content vs the designation).
        if effective_version.approved_by not in designation.approvers:
            reasons.add(_R.APPROVAL_ACTOR_UNRECOGNIZED)
        approved_at = effective_version.approved_at
        if approved_at is not None and approved_at < effective_version.cutoff_at:
            reasons.add(_R.APPROVAL_STALE)

    # Step 6: refused runs newer than the admitting run (any, without an effective version).
    admitting_sequence = None if effective is None else admitting[effective].run_sequence
    for run in refused:
        if admitting_sequence is None or run.run_sequence > admitting_sequence:
            reasons.add(_refusal_reason(run))

    # Step 7: hash parity of every run carrying the effective version.
    if effective is not None:
        for run in runs_by_content[effective]:
            if source_content_sha256(_version(run)) != run.content_sha256:
                reasons.add(_R.HASH_MISMATCH)

    return VersionResolution(effective_version, effective, frozenset(reasons), pending)


# --- mapping resolution (section 3.8) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class MappingResolution:
    """The system and external id a Project is mapped from, or its mapping reasons."""

    source_system: str | None
    external_project_id: str | None
    reasons: frozenset[FinancialNotReportableReason]


def current_mapping_revisions(
    mappings: Sequence[ProjectMappingRevision],
) -> dict[tuple[str, str], ProjectMappingRevision]:
    """The highest revision per key; a gap or a duplicate revision raises `ValueError`."""
    by_key: dict[tuple[str, str], list[ProjectMappingRevision]] = {}
    for mapping in mappings:
        by_key.setdefault(mapping.key, []).append(mapping)
    current = {}
    for key, revisions in sorted(by_key.items()):
        numbers = sorted(revision.revision for revision in revisions)
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("mapping revisions are numbered 1..n without gap or duplicate")
        current[key] = max(revisions, key=lambda revision: revision.revision)
    return current


def resolve_project_mapping(
    project_id: str,
    systems: Iterable[str],
    current: Mapping[tuple[str, str], ProjectMappingRevision],
) -> MappingResolution:
    """Section 3.8 across the designated systems covering the request perspective."""
    names = sorted(set(systems))
    accepted: dict[str, list[str]] = {}
    for (system, external_id), revision in sorted(current.items()):
        if (
            system in names
            and revision.project_id == project_id
            and revision.state is MappingState.ACCEPTED
        ):
            accepted.setdefault(system, []).append(external_id)
    if len(accepted) >= 2:
        reasons = {_R.DOUBLE_COUNT_DETECTED}
        if any(len(ids) > 1 for ids in accepted.values()):
            reasons.add(_R.MAPPING_AMBIGUOUS)
        return MappingResolution(None, None, frozenset(reasons))
    if len(accepted) == 1:
        ((system, ids),) = accepted.items()
        if len(ids) > 1:
            return MappingResolution(system, None, frozenset({_R.MAPPING_AMBIGUOUS}))
        return MappingResolution(system, ids[0], frozenset())
    states = {
        revision.state
        for (system, _), revision in current.items()
        if system in names and revision.project_id == project_id
    }
    if MappingState.QUARANTINED in states:
        return MappingResolution(None, None, frozenset({_R.MAPPING_QUARANTINED}))
    if MappingState.PROPOSED in states:
        return MappingResolution(None, None, frozenset({_R.MAPPING_UNREVIEWED}))
    return MappingResolution(None, None, frozenset({_R.MAPPING_MISSING}))


# --- the evaluator (section 5.3) -------------------------------------------------------------


def source_state_of(reasons: Iterable[FinancialNotReportableReason]) -> FinancialSourceState:
    """Section 5.2: `effective` without a project reason, else the first matching state."""
    present = set(reasons)
    if not present:
        return FinancialSourceState.EFFECTIVE
    for state, members in SOURCE_STATE_PRECEDENCE:
        if present & members:
            return state
    raise ValueError("a project reason has no source state")


def _validate_inputs(
    designations: Sequence[SourceDesignation],
    runs: Sequence[SourceRun],
    quarantined_run_refs: frozenset[str],
) -> None:
    if type(quarantined_run_refs) is not frozenset:
        raise TypeError("quarantined_run_refs must be a frozenset")
    systems = Counter(designation.source_system for designation in designations)
    if any(count > 1 for count in systems.values()):
        raise ValueError("at most 1 active designation per source system")
    if any(count > 1 for count in Counter(run.run_ref for run in runs).values()):
        raise ValueError("run refs are unique")
    sequences = Counter((run.designated_source_system, run.run_sequence) for run in runs)
    if any(count > 1 for count in sequences.values()):
        raise ValueError("run_sequence is unique per source system")
    if not quarantined_run_refs <= {run.run_ref for run in runs}:
        raise ValueError("a quarantined run ref names no supplied run")


def _denominator(
    request: FinancialScopeRequest,
    projects: Sequence[ProjectFinancialFigures],
    refused_runs: int,
    quarantined_runs: int,
) -> FinancialDenominator:
    states = Counter(project.source_state for project in projects)
    effective = states[FinancialSourceState.EFFECTIVE]
    return FinancialDenominator(
        member_projects=len(request.project_ids),
        unresolved_members=request.unresolved_members,
        projects_reportable=effective,
        missing_source_count=len(projects) - effective,
        refused_runs=refused_runs,
        quarantined_runs=quarantined_runs,
        projects_by_source_state=tuple((state, states[state]) for state in FinancialSourceState),
    )


def _membership_reasons(request: FinancialScopeRequest) -> set[FinancialNotReportableReason]:
    reasons = set()
    if request.unresolved_members > 0:
        reasons.add(_R.MEMBERSHIP_UNRESOLVED)
    if request.membership_truncated:
        reasons.add(_R.MEMBERSHIP_TRUNCATED)
    return reasons


def _nulled(
    metrics: Sequence[FinancialMetric], reasons: Iterable[FinancialNotReportableReason]
) -> tuple[FinancialMetricValue, ...]:
    listed = tuple(reasons)
    return tuple(not_reportable(metric, listed) for metric in metrics)


def _not_integrated(request: FinancialScopeRequest) -> FinancialOverview:
    """Section 5.3 step 2: no designation covers the request perspective."""
    metrics = METRICS_BY_PERSPECTIVE[request.perspective]
    project_reasons = (_R.SOURCE_NOT_INTEGRATED,)
    projects = tuple(
        ProjectFinancialFigures(
            project_id=project_id,
            source_state=FinancialSourceState.NOT_INTEGRATED,
            reasons=project_reasons,
            source_content_sha256=None,
            external_project_id=None,
            eac_basis=None,
            metrics=_nulled(metrics, project_reasons),
        )
        for project_id in request.project_ids
    )
    program_reasons = tuple(sorted({_R.SOURCE_NOT_INTEGRATED} | _membership_reasons(request)))
    return FinancialOverview(
        calculation_version=CALCULATION_VERSION,
        request=request,
        reportability=FinancialReportability.SOURCE_NOT_INTEGRATED,
        reasons=program_reasons,
        program_reasons=program_reasons,
        quarantined_runs=(),
        program_metrics=_nulled(metrics, program_reasons),
        projects=projects,
        transfer_eliminations=(),
        source_versions=(),
        pending_source_versions=(),
        source_cutoff_at=None,
        denominator=_denominator(request, projects, 0, 0),
    )


def evaluate_financial_overview(
    request: FinancialScopeRequest,
    designations: Sequence[SourceDesignation],
    runs: Sequence[SourceRun],
    mappings: Sequence[ProjectMappingRevision],
    quarantined_run_refs: frozenset[str],
) -> FinancialOverview:
    """Section 5.3. No threshold, tolerance or materiality parameter exists (OD-08)."""
    # Step 1: canonical order, input contract, quarantine set aside.
    _validate_inputs(designations, runs, quarantined_run_refs)
    ordered_designations = sorted(designations, key=lambda d: d.source_system)
    ordered_runs = sorted(runs, key=lambda r: (r.designated_source_system, r.run_sequence))
    current = current_mapping_revisions(
        sorted(mappings, key=lambda m: (m.source_system, m.external_project_id, m.revision))
    )
    in_scope = [d for d in ordered_designations if request.perspective in d.perspectives]
    systems = [d.source_system for d in in_scope]
    scoped_runs = [run for run in ordered_runs if run.designated_source_system in systems]
    quarantined = tuple(sorted(r.run_ref for r in scoped_runs if r.run_ref in quarantined_run_refs))
    live_runs = [run for run in scoped_runs if run.run_ref not in quarantined_run_refs]
    refused_runs = sum(1 for run in live_runs if run.outcome is RunOutcome.REFUSED)

    # Step 2: no designation covers the perspective.
    if not in_scope:
        return _not_integrated(request)

    # Step 3: version resolution per system.
    resolutions = {d.source_system: resolve_source_version(d, live_runs, request) for d in in_scope}

    # Steps 4-9: per Project.
    metrics = METRICS_BY_PERSPECTIVE[request.perspective]
    mapped: dict[str, MappingResolution] = {}
    projects: list[ProjectFinancialFigures] = []
    for project_id in request.project_ids:
        mapping = resolve_project_mapping(project_id, systems, current)
        mapped[project_id] = mapping
        reasons = set(mapping.reasons)
        content: str | None = None
        computation = None
        if mapping.source_system is not None and mapping.external_project_id is not None:
            resolution = resolutions[mapping.source_system]
            reasons |= resolution.reasons
            version = resolution.effective
            content = resolution.effective_content_sha256
            if version is not None:
                if not project_has_rows(version, mapping.external_project_id):
                    reasons.add(_R.MISSING_PROJECT)
                else:
                    computation = compute_project(version, mapping.external_project_id)
                    if computation.reconciliation_failed:
                        reasons.add(_R.SOURCE_RECONCILIATION_FAILED)
        project_reasons = tuple(sorted(reasons))
        if project_reasons or computation is None:
            figures = _nulled(metrics, project_reasons)
            eac_basis = None
        else:
            figures = computation.metrics
            eac_basis = computation.eac_basis
        projects.append(
            ProjectFinancialFigures(
                project_id=project_id,
                source_state=source_state_of(project_reasons),
                reasons=project_reasons,
                source_content_sha256=content,
                external_project_id=mapping.external_project_id,
                eac_basis=eac_basis,
                metrics=figures,
            )
        )

    # Section 4.7: the versions entering the answer (before step 9 nulling).
    members = set(request.project_ids)
    sources = sorted(
        {
            system
            for (system, _), revision in current.items()
            if system in systems
            and revision.state is MappingState.ACCEPTED
            and revision.project_id in members
        }
    )
    entering: dict[str, SourceVersion] = {}
    entering_contents: dict[str, str] = {}
    pending: set[str] = set()
    for system in sources:
        resolution = resolutions[system]
        pending.update(resolution.pending_source_versions)
        if resolution.effective is not None and resolution.effective_content_sha256 is not None:
            entering[system] = resolution.effective
            entering_contents[system] = resolution.effective_content_sha256
    program_reasons = _membership_reasons(request)
    if repeats_a_ref_across_versions([entering[s] for s in sorted(entering)]):
        program_reasons.add(_R.DOUBLE_COUNT_DETECTED)

    # Section 4.6: internal transfers, eliminated once per system.
    eliminations: list[TransferElimination] = []
    internal_refs: dict[str, frozenset[str]] = {}
    for system, version in sorted(entering.items()):
        member_by_external = {
            m.external_project_id: project_id
            for project_id, m in mapped.items()
            if m.source_system == system and m.external_project_id is not None
        }
        found = internal_transfers(version, member_by_external, entering_contents[system])
        eliminations.extend(found)
        internal_refs[system] = frozenset(e.transfer_ref for e in found)

    # Step 10: Program metrics.
    program_metrics = []
    for index, metric in enumerate(metrics):
        member_values = [project.metrics[index] for project in projects]
        contributions = None
        if metric in (FinancialMetric.TRANSFERS_IN, FinancialMetric.TRANSFERS_OUT) and all(
            not project.reasons for project in projects
        ):
            contributions = []
            for project_id in request.project_ids:
                m = mapped[project_id]
                if m.source_system is None or m.external_project_id is None:
                    raise FinancialInvariantError("a Project without reasons is mapped")
                amounts = external_transfer_amounts(
                    entering[m.source_system],
                    m.external_project_id,
                    internal_refs[m.source_system],
                )
                contributions.append(amounts[0 if metric is FinancialMetric.TRANSFERS_IN else 1])
        program_metrics.append(
            consolidate_metric(metric, member_values, program_reasons, contributions)
        )

    # Step 11: reportability.
    all_reasons = set(program_reasons)
    for project in projects:
        all_reasons.update(project.reasons)
    used = sorted(entering.items())
    return FinancialOverview(
        calculation_version=CALCULATION_VERSION,
        request=request,
        reportability=(
            FinancialReportability.NOT_REPORTABLE
            if all_reasons
            else FinancialReportability.REPORTABLE
        ),
        reasons=tuple(sorted(all_reasons)),
        program_reasons=tuple(sorted(program_reasons)),
        quarantined_runs=quarantined,
        program_metrics=tuple(program_metrics),
        projects=tuple(projects),
        transfer_eliminations=tuple(sorted(eliminations, key=lambda e: e.transfer_ref)),
        source_versions=tuple(sorted(entering_contents.values())),
        pending_source_versions=tuple(sorted(pending)),
        source_cutoff_at=min((v.cutoff_at for _, v in used), default=None),
        denominator=_denominator(request, projects, refused_runs, len(quarantined)),
    )
