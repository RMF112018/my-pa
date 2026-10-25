"""The pure Program reporting rules (record lineage S4 contract sections 3.1 to 3.3, 5.1).

FAST: no database. The membership rows (worker M2, WP-04A) pin the section 3.1
rule as tables over fetched rows -- the window rule in both modes, the
redirect walk's bound and cycle refusal, the bridge's exactly-one rule and the
completeness precedence -- so the database tests of
`tests/integration/test_program_member_resolver.py` prove the reads feed it
and these prove the rule itself. The overview rows (worker M4, WP-04B) pin
the section 3.3 Constraint source-state table, the reportability reasons of
every metric at Project and total grain, the acceptance proof (never proven
in S4, and the one place that would change the accepted totals) and the
section 5.1 digest's golden vectors.

Every identifier here is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.domain.program.digest import overview_digest
from my_pa.domain.program.membership import (
    BridgeLink,
    EntityNode,
    MemberEdge,
    RedirectFailure,
    RequestedProgram,
    WindowVerdict,
    assemble_membership,
    bridge_outcome,
    completeness,
    walk_redirect,
    window_verdict,
)
from my_pa.domain.program.reportability import (
    ACCEPTANCE_PROVING,
    COMMITMENT_METRICS,
    CONSTRAINT_METRICS,
    METRIC_CATALOGUE,
    MetricId,
    ProjectFacts,
    SyncTarget,
    commitment_acceptance_proof,
    constraint_source_state,
    project_metric,
    scope_total,
    target_state,
)
from my_pa.domain.program.vocabulary import (
    MAX_REDIRECT_HOPS,
    AcceptanceVerification,
    ConstraintSourceState,
    MembershipMode,
    MemberUnresolvedReason,
    MetricValueState,
    NotReportableReason,
    ProgramCompleteness,
    ProgramFamily,
)

T: Final = datetime(2026, 10, 24, 12, tzinfo=UTC)
BEFORE: Final = T - timedelta(days=30)
AFTER: Final = T + timedelta(days=30)
CURRENT: Final = MembershipMode.CURRENT
HISTORICAL: Final = MembershipMode.HISTORICAL
MEMBER: Final = WindowVerdict.MEMBER
OUTSIDE: Final = WindowVerdict.OUTSIDE
NO_START: Final = WindowVerdict.START_NOT_RECORDED
NO_END: Final = WindowVerdict.END_NOT_RECORDED


def _edge(
    starts: datetime | None,
    ends: datetime | None,
    state: str = "active",
    *,
    relationship_id: str = "erel_programdomain0001",
    program: str = "ent_programdomaing001",
    member: str = "ent_programdomainb001",
) -> MemberEdge:
    return MemberEdge(
        relationship_id=relationship_id,
        program_entity_id=program,
        member_entity_id=member,
        effective_from=starts,
        effective_to=ends,
        state=state,
    )


def _node(
    entity_id: str,
    entity_type: str = "project",
    *,
    status: str = "active",
    into: str | None = None,
) -> EntityNode:
    return EntityNode(
        entity_id=entity_id,
        entity_type=entity_type,
        status="merged_redirect" if into is not None else status,
        superseded_by_entity_id=into,
    )


#: `(effective_from, effective_to, state) -> (current verdict, historical verdict)`
#: at the instant `T`. Both modes apply the same window; historical mode only
#: separates what the recorded dates can prove.
WINDOW_TABLE: Final = [
    # A dated, open, active edge is a member in both modes.
    ((BEFORE, None, "active"), (MEMBER, MEMBER)),
    # A null start is no obstacle now, and unprovable at an instant.
    ((None, None, "active"), (MEMBER, NO_START)),
    ((None, AFTER, "active"), (MEMBER, NO_START)),
    ((None, AFTER, "ended"), (MEMBER, NO_START)),
    # A start after `T` is outside the window (both non-null comparisons).
    ((AFTER, None, "active"), (OUTSIDE, OUTSIDE)),
    # An end at or before `T` is outside it.
    ((BEFORE, T, "ended"), (OUTSIDE, OUTSIDE)),
    ((BEFORE, T - timedelta(microseconds=1), "active"), (OUTSIDE, OUTSIDE)),
    ((None, BEFORE, "ended"), (OUTSIDE, OUTSIDE)),
    # An `ended` edge whose recorded end is still in the future is a member
    # until that end (R4-F09), and a verified one: both dates are recorded.
    ((BEFORE, AFTER, "ended"), (MEMBER, MEMBER)),
    ((BEFORE, T + timedelta(microseconds=1), "ended"), (MEMBER, MEMBER)),
    # An `ended` edge with no recorded end is not a current member, and
    # historically its end is unprovable.
    ((BEFORE, None, "ended"), (OUTSIDE, NO_END)),
    # A dated closed window around `T`.
    ((BEFORE, AFTER, "active"), (MEMBER, MEMBER)),
    # The start instant itself is inside.
    ((T, None, "active"), (MEMBER, MEMBER)),
]


@pytest.mark.parametrize(("window", "expected"), WINDOW_TABLE)
def test_window_rule_table(
    window: tuple[datetime | None, datetime | None, str],
    expected: tuple[WindowVerdict, WindowVerdict],
) -> None:
    starts, ends, state = window
    edge = _edge(starts, ends, state)
    current, historical = expected
    assert window_verdict(edge, T, CURRENT) is current
    assert window_verdict(edge, T, HISTORICAL) is historical
    # Same window over the recorded dates: outside historically is outside
    # now; the one difference is an `ended` edge with no recorded end, which is
    # not a current member and is historically `end_not_recorded`.
    if historical is OUTSIDE:
        assert current is OUTSIDE
    if current is OUTSIDE and historical is not OUTSIDE:
        assert (ends, state, historical) == (None, "ended", NO_END)
    # A verified historical member is a current member at the same instant.
    if historical is MEMBER:
        assert current is MEMBER


def test_redirect_walk_bounds_and_cycles() -> None:
    # No redirect: the Entity is its own terminal, 0 hops.
    nodes = {"ent_programdomainp001": _node("ent_programdomainp001", "program")}
    walked = walk_redirect("ent_programdomainp001", nodes)
    assert walked.terminal == nodes["ent_programdomainp001"]
    assert walked.hops == 0
    # A chain of exactly MAX_REDIRECT_HOPS hops resolves; one more is too long.
    chain = [f"ent_programdomainc{index:03d}" for index in range(MAX_REDIRECT_HOPS + 2)]
    for limit in (MAX_REDIRECT_HOPS, MAX_REDIRECT_HOPS + 1):
        built = {
            entity: _node(entity, "program", into=chain[index + 1])
            for index, entity in enumerate(chain[:limit])
        }
        built[chain[limit]] = _node(chain[limit], "program")
        walked = walk_redirect(chain[0], built)
        if limit == MAX_REDIRECT_HOPS:
            assert walked.terminal is not None
            assert walked.terminal.entity_id == chain[limit]
            assert walked.hops == MAX_REDIRECT_HOPS
        else:
            assert walked.terminal is None
            assert walked.failure is RedirectFailure.TOO_LONG
    # A revisit is a cycle, never a terminal.
    looped = {
        "ent_programdomaina001": _node("ent_programdomaina001", into="ent_programdomaina002"),
        "ent_programdomaina002": _node("ent_programdomaina002", into="ent_programdomaina003"),
        "ent_programdomaina003": _node("ent_programdomaina003", into="ent_programdomaina001"),
    }
    walked = walk_redirect("ent_programdomaina001", looped)
    assert walked.terminal is None
    assert walked.failure is RedirectFailure.CYCLE
    # An Entity that is not the caller's (not fetched) has no terminal.
    walked = walk_redirect("ent_programdomainz001", looped)
    assert walked.failure is RedirectFailure.MISSING
    # The status of a terminal is whatever it is: only `merged_redirect` is followed.
    archived = {"ent_programdomainr001": _node("ent_programdomainr001", status="archived")}
    walked = walk_redirect("ent_programdomainr001", archived)
    assert walked.terminal is not None
    assert walked.terminal.status == "archived"


@pytest.mark.parametrize(
    ("projects", "expected"),
    [
        ((), MemberUnresolvedReason.BRIDGE_MISSING),
        (("prj_programdomain0001",), "prj_programdomain0001"),
        (("prj_programdomain0001", "prj_programdomain0001"), "prj_programdomain0001"),
        (
            ("prj_programdomain0001", "prj_programdomain0002"),
            MemberUnresolvedReason.BRIDGE_AMBIGUOUS,
        ),
        (
            ("prj_programdomain0002", "prj_programdomain0001", "prj_programdomain0003"),
            MemberUnresolvedReason.BRIDGE_AMBIGUOUS,
        ),
    ],
)
def test_bridge_resolution_counts(
    projects: tuple[str, ...], expected: str | MemberUnresolvedReason
) -> None:
    # Exactly one bound Project, else why there is none; never a choice.
    assert bridge_outcome(projects) == expected
    # The assembled answer names the same outcome for one in-window edge.
    resolution = assemble_membership(
        (RequestedProgram("ent_programdomaing001", "ent_programdomaing001", "active"),),
        (_edge(BEFORE, None),),
        mode=CURRENT,
        at=T,
        source_cutoff_at=T,
        nodes={"ent_programdomainb001": _node("ent_programdomainb001")},
        bridges=[
            BridgeLink("ent_programdomainb001", project, "ent_programdomainb001")
            for project in projects
        ],
        project_states=dict.fromkeys(projects, "active"),
        edge_overflow_program=None,
    )
    (program,) = resolution.programs
    if isinstance(expected, MemberUnresolvedReason):
        assert program.members == ()
        assert [member.reason for member in program.unresolved_members] == [expected]
        assert program.complete_state is ProgramCompleteness.MEMBERSHIP_UNRESOLVED
    else:
        assert program.project_ids == (expected,)
        assert program.unresolved_members == ()
        assert program.qualifiers == (ProgramCompleteness.COMPLETE,)


def test_completeness_precedence() -> None:
    assert completeness([]) == (ProgramCompleteness.COMPLETE, (ProgramCompleteness.COMPLETE,))
    assert completeness([ProgramCompleteness.COMPLETE]) == (
        ProgramCompleteness.COMPLETE,
        (ProgramCompleteness.COMPLETE,),
    )
    every = [
        ProgramCompleteness.RESTRICTED_EVIDENCE,
        ProgramCompleteness.COMPLETE,
        ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        ProgramCompleteness.MEMBERSHIP_UNRESOLVED,
        ProgramCompleteness.TRUNCATED_BUDGET,
    ]
    state, qualifiers = completeness(every)
    assert state is ProgramCompleteness.TRUNCATED_BUDGET
    # `complete` never combines; qualifiers[0] is the state; precedence order.
    assert qualifiers == (
        ProgramCompleteness.TRUNCATED_BUDGET,
        ProgramCompleteness.MEMBERSHIP_UNRESOLVED,
        ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        ProgramCompleteness.RESTRICTED_EVIDENCE,
    )
    assert completeness(
        [
            ProgramCompleteness.RESTRICTED_EVIDENCE,
            ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        ]
    ) == (
        ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        (
            ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
            ProgramCompleteness.RESTRICTED_EVIDENCE,
        ),
    )


# --- the overview rules (worker M4, sections 3.2, 3.3 and 5.1) -------------------

_VERIFIED: Final = datetime(2026, 9, 1, tzinfo=UTC)


def _target(
    *, verified: bool = True, run: bool = True, state: str | None = "in_sync"
) -> SyncTarget:
    return SyncTarget(
        last_verified_at=_VERIFIED if verified else None,
        last_run_id="csyr_goldenrun0001" if run else None,
        last_run_sync_state=state if run else None,
    )


@pytest.mark.parametrize(
    ("calendar", "targets", "conflicts", "expected"),
    [
        (False, [_target()], 0, ConstraintSourceState.CALENDAR_UNCONFIGURED),
        (False, [], 3, ConstraintSourceState.CALENDAR_UNCONFIGURED),
        (True, [], 0, ConstraintSourceState.NEVER_SYNCED),
        (True, [_target()], 0, ConstraintSourceState.IN_SYNC),
        (True, [_target(verified=False)], 0, ConstraintSourceState.UNVERIFIED),
        (True, [_target(run=False)], 0, ConstraintSourceState.UNVERIFIED),
        (True, [_target(state="verification_failed")], 0, ConstraintSourceState.SYNC_DEGRADED),
        (True, [_target(state="partial")], 0, ConstraintSourceState.SYNC_DEGRADED),
        (True, [_target(state="never_synced")], 0, ConstraintSourceState.SYNC_DEGRADED),
        (True, [_target()], 1, ConstraintSourceState.CONFLICT),
        (True, [_target(verified=False)], 1, ConstraintSourceState.CONFLICT),
        # The worst target wins: in sync only when every target is.
        (True, [_target(), _target(state="partial")], 0, ConstraintSourceState.SYNC_DEGRADED),
        (True, [_target(state="partial"), _target()], 0, ConstraintSourceState.SYNC_DEGRADED),
        (True, [_target(), _target(verified=False)], 0, ConstraintSourceState.UNVERIFIED),
        (
            True,
            [_target(verified=False), _target(state="conflict")],
            0,
            ConstraintSourceState.SYNC_DEGRADED,
        ),
        (True, [_target(), _target()], 0, ConstraintSourceState.IN_SYNC),
    ],
)
def test_constraint_source_state_table(
    calendar: bool,
    targets: list[SyncTarget],
    conflicts: int,
    expected: ConstraintSourceState,
) -> None:
    assert (
        constraint_source_state(
            calendar_configured=calendar, targets=targets, open_conflicts=conflicts
        )
        is expected
    )
    # Each target's own state, in its checked order (R4-F01).
    assert target_state(_target(), project_has_open_conflict=True) is ConstraintSourceState.CONFLICT
    assert (
        target_state(_target(verified=False, state="partial"), project_has_open_conflict=False)
        is ConstraintSourceState.UNVERIFIED
    )


_ALL: Final = frozenset(ProgramFamily)


def _facts(
    project_id: str,
    *,
    commitments: dict[MetricId, int] | None = None,
    issues: frozenset[str] = frozenset(),
    legacy: int = 0,
    legacy_closed: int = 0,
    source: ConstraintSourceState = ConstraintSourceState.IN_SYNC,
    constraints: dict[MetricId, int] | None = None,
) -> ProjectFacts:
    calendar = source is not ConstraintSourceState.CALENDAR_UNCONFIGURED
    return ProjectFacts(
        project_id=project_id,
        commitment_counts=commitments or {},
        issue_ids=issues,
        legacy_issue_links=legacy,
        legacy_issue_links_closed=legacy_closed,
        constraint_source_state=source,
        constraint_counts=(constraints or {}) if calendar else None,
    )


_SOURCE_REASONS: Final = {
    ConstraintSourceState.IN_SYNC: (),
    ConstraintSourceState.NEVER_SYNCED: (NotReportableReason.NEVER_SYNCED,),
    ConstraintSourceState.UNVERIFIED: (NotReportableReason.SYNC_UNVERIFIED,),
    ConstraintSourceState.SYNC_DEGRADED: (NotReportableReason.SYNC_DEGRADED,),
    ConstraintSourceState.CONFLICT: (NotReportableReason.SYNC_CONFLICT,),
    ConstraintSourceState.CALENDAR_UNCONFIGURED: (NotReportableReason.CALENDAR_UNCONFIGURED,),
}


def _expected_reasons(
    metric: MetricId,
    *,
    unresolved: bool,
    truncated: bool,
    legacy: bool,
    source: ConstraintSourceState,
) -> tuple[NotReportableReason, ...]:
    reasons: set[NotReportableReason] = set()
    if unresolved:
        reasons.add(NotReportableReason.MEMBERSHIP_UNRESOLVED)
    if truncated:
        reasons.add(NotReportableReason.MEMBERSHIP_TRUNCATED)
    if metric in {
        MetricId.COMMITMENT_OPEN_ACCEPTED,
        MetricId.COMMITMENT_OVERDUE_ACCEPTED,
        MetricId.COMMITMENT_UNSCHEDULED_ACCEPTED,
    }:
        reasons.add(NotReportableReason.ACCEPTANCE_UNVERIFIED)
    if metric is MetricId.ISSUE_OUTSTANDING and legacy:
        reasons.add(NotReportableReason.ISSUE_LINK_UNVERIFIED)
    if metric in CONSTRAINT_METRICS:
        reasons.update(_SOURCE_REASONS[source])
    return tuple(sorted(reasons))


@pytest.mark.parametrize("unresolved", [False, True])
@pytest.mark.parametrize("truncated", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("source", list(ConstraintSourceState))
def test_reportability_reasons_table(
    unresolved: bool, truncated: bool, legacy: bool, source: ConstraintSourceState
) -> None:
    clean = _facts("prj_goldenclean001", issues=frozenset({"sit_goldenshared01"}))
    gapped = _facts(
        "prj_goldengapped01",
        issues=frozenset({"sit_goldenshared01", "sit_goldenown00001"}),
        legacy=1 if legacy else 0,
        legacy_closed=2,
        source=source,
    )
    for row in METRIC_CATALOGUE:
        total = scope_total(
            row.metric_id,
            [clean, gapped],
            visible=_ALL,
            membership_unresolved=unresolved,
            membership_truncated=truncated,
        )
        expected = _expected_reasons(
            row.metric_id, unresolved=unresolved, truncated=truncated, legacy=legacy, source=source
        )
        assert total.reasons == expected, row.metric_id
        # No zero is ever substituted: a gap is a `null`, a clean total a count.
        if expected:
            assert (total.value, total.value_state) == (None, MetricValueState.NOT_REPORTABLE)
        else:
            assert total.value_state is MetricValueState.REPORTED
            assert total.value is not None
        assert total.nonadditive_across_projects is (row.metric_id is MetricId.ISSUE_OUTSTANDING)
        # Per Project: only the calendar and the legacy link gate a value.
        own = project_metric(row.metric_id, gapped, visible=_ALL)
        project_reasons: tuple[NotReportableReason, ...] = ()
        if row.metric_id is MetricId.ISSUE_OUTSTANDING and legacy:
            project_reasons = (NotReportableReason.ISSUE_LINK_UNVERIFIED,)
        if (
            row.metric_id in CONSTRAINT_METRICS
            and source is ConstraintSourceState.CALENDAR_UNCONFIGURED
        ):
            project_reasons = (NotReportableReason.CALENDAR_UNCONFIGURED,)
        assert own.reasons == project_reasons, row.metric_id
        # An invisible family is restricted, never a count and never a reason.
        hidden = scope_total(
            row.metric_id,
            [clean, gapped],
            visible=_ALL - {row.family},
            membership_unresolved=unresolved,
            membership_truncated=truncated,
        )
        assert (hidden.value, hidden.value_state, hidden.reasons) == (
            None,
            MetricValueState.RESTRICTED,
            (),
        )
    # The Issue grain is distinct over the scope: the shared Issue counts once.
    issues = scope_total(
        MetricId.ISSUE_OUTSTANDING,
        [clean, gapped],
        visible=_ALL,
        membership_unresolved=False,
        membership_truncated=False,
    )
    if not legacy:
        assert issues.value == 2


def test_commitment_acceptance_proof_is_unverified_for_native_acceptance() -> None:
    assert (
        commitment_acceptance_proof("accepted")
        is AcceptanceVerification.UNVERIFIED_REVIEW_REFERENCE
    )
    assert commitment_acceptance_proof("proposed") is AcceptanceVerification.NOT_ACCEPTED
    # No verification state proves acceptance in S4.
    assert frozenset() == ACCEPTANCE_PROVING
    facts = _facts("prj_goldenaccept01", commitments=dict.fromkeys(COMMITMENT_METRICS, 2))
    for metric in COMMITMENT_METRICS:
        total = scope_total(
            metric,
            [facts],
            visible=_ALL,
            membership_unresolved=False,
            membership_truncated=False,
        )
        accepted = metric in {
            MetricId.COMMITMENT_OPEN_ACCEPTED,
            MetricId.COMMITMENT_OVERDUE_ACCEPTED,
            MetricId.COMMITMENT_UNSCHEDULED_ACCEPTED,
        }
        if accepted:
            assert (total.value, total.reasons) == (
                None,
                (NotReportableReason.ACCEPTANCE_UNVERIFIED,),
            )
            assert total.acceptance is AcceptanceVerification.UNVERIFIED_REVIEW_REFERENCE
            # Per Project the figure is shown, marked unverified.
            shown = project_metric(metric, facts, visible=_ALL)
            assert (shown.value, shown.value_state) == (2, MetricValueState.REPORTED)
            assert shown.acceptance is AcceptanceVerification.UNVERIFIED_REVIEW_REFERENCE
        else:
            assert (total.value, total.reasons, total.acceptance) == (2, (), None)


def test_a_proven_acceptance_would_report_the_distinct_total() -> None:
    projects = [
        _facts("prj_goldenproven01", commitments={MetricId.COMMITMENT_OPEN_ACCEPTED: 3}),
        _facts("prj_goldenproven02", commitments={MetricId.COMMITMENT_OPEN_ACCEPTED: 4}),
    ]
    proven = scope_total(
        MetricId.COMMITMENT_OPEN_ACCEPTED,
        projects,
        visible=_ALL,
        membership_unresolved=False,
        membership_truncated=False,
        acceptance_proven=True,
    )
    assert (proven.value, proven.value_state, proven.reasons) == (
        7,
        MetricValueState.REPORTED,
        (),
    )
    # The other gates still apply to a proven acceptance.
    gapped = scope_total(
        MetricId.COMMITMENT_OPEN_ACCEPTED,
        projects,
        visible=_ALL,
        membership_unresolved=True,
        membership_truncated=False,
        acceptance_proven=True,
    )
    assert gapped.reasons == (NotReportableReason.MEMBERSHIP_UNRESOLVED,)


#: Section 5.1: `D` with its 3 read-time stamps removed, exactly as canonical text.
#: Regenerated in lockstep for record lineage S3.1 (S3.1 contract sections 7.8
#: and 8): the calculation version is `program-overview-v2`.
_GOLDEN_D: Final = {
    "calculation_version": "program-overview-v2",
    "complete_state": "complete",
    "metric_schema_version": 1,
    "per_project": [],
    "portfolio": {"overlaps": [], "project_ids": []},
    "programs": [],
    "qualifiers": ["complete"],
}
_GOLDEN_TEXT: Final = (
    b'program-overview-v2\n{"calculation_version":"program-overview-v2",'
    b'"complete_state":"complete","metric_schema_version":1,"per_project":[],'
    b'"portfolio":{"overlaps":[],"project_ids":[]},"programs":[],"qualifiers":["complete"]}'
)


def test_overview_digest_golden_vectors() -> None:
    expected = "eb26c48831c2a1f81ccb2ab855bd8f7cc9c2553a3f805a466b16719ca23d6128"
    assert hashlib.sha256(_GOLDEN_TEXT).hexdigest() == expected
    assert overview_digest(_GOLDEN_D) == expected
    # The 3 read-time stamps are not in `D`.
    stamped = {
        **_GOLDEN_D,
        "source_cutoff_at": "2026-10-24T12:00:00.000000Z",
        "lineage_known_at": "2026-10-24T11:59:59.000001Z",
        "overview_sha256": "f" * 64,
    }
    assert overview_digest(stamped) == expected
    # `project_today` and every per-Project field are in it.
    with_project = {
        **_GOLDEN_D,
        "per_project": [
            {
                "calendar": {"project_today": "2026-10-25", "timezone_name": "Pacific/Kiritimati"},
                "metrics": [
                    {
                        "metric_id": "issue_outstanding",
                        "nonadditive_across_projects": True,
                        "reasons": [],
                        "value": 2,
                    }
                ],
                "project_id": "prj_goldenvector01",
            }
        ],
    }
    assert (
        overview_digest(with_project)
        == "f5198014f7749003676b5623ccbb9f4610b92e9e5f262abd6f56c6a81d5df733"
    )
    next_day = json.loads(json.dumps(with_project))
    next_day["per_project"][0]["calendar"]["project_today"] = "2026-10-26"
    assert overview_digest(next_day) != overview_digest(with_project)
    # Key order is not part of it; the digest of `{}` is the bare prefix's.
    assert overview_digest(dict(reversed(list(_GOLDEN_D.items())))) == expected
    assert overview_digest({}) == hashlib.sha256(b"program-overview-v2\n{}").hexdigest()
