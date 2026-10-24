"""AT-019: Program metrics reconcile with their native reads (record lineage S4 sections 3.2-3.4).

Against PostgreSQL, through `ApplicationService.invoke` with the Program read
pool composed as the gateway composes it (worker M4, WP-04B). Every figure of
one `programs.overview` is read from one snapshot: per Project it equals the
native read of that plane, every Program and portfolio total equals a direct
`COUNT(DISTINCT ...)`, an Issue shared by 2 Projects counts once and is
flagged nonadditive, and a total is reported only when nothing material is
missing (OD-08) -- otherwise its value is `null` and every reason is named:
an unresolved member, unverified acceptance, a Project never synced, a target
never verified, a degraded last run (the worst target wins), an open sync
conflict, a legacy Issue link of an outstanding Issue, a Project without a
calendar. A closed Issue's legacy link is disclosed and never gates; a
suspended Issue is outstanding; overdue and due-soon are decided on each
Project's own calendar; a verified zero is a reported `0`; the denominator
names every Project state; the overview digest is stable and sensitive.

The Entity graph and the Constraint, sync and legacy facts are seeded by
direct SQL (`lineage_s4_harness`), Commitments and Issue links natively.
Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from my_pa.application.commands import ListCommitmentsV2, ReadPortfolioConstraintOverview
from my_pa.domain.project_controls.business_time import due_soon_through, project_today
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.situation.continuity import CommitmentState
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_s4_harness import T0, S4Runtime

pytestmark = pytest.mark.database

#: The 13 section 3.2 metrics, in catalogue order.
METRICS: Final = (
    "commitment_open_accepted",
    "commitment_open_proposed",
    "commitment_closed_proposed",
    "commitment_overdue_accepted",
    "commitment_overdue_proposed",
    "commitment_unscheduled_accepted",
    "commitment_unscheduled_proposed",
    "issue_outstanding",
    "constraint_open",
    "constraint_overdue",
    "constraint_due_soon",
    "constraint_in_my_court",
    "constraint_draft",
)
ACCEPTED: Final = (
    "commitment_open_accepted",
    "commitment_overdue_accepted",
    "commitment_unscheduled_accepted",
)
CONSTRAINT_METRICS: Final = METRICS[8:]
COMMITMENT_METRICS: Final = METRICS[:7]
#: 2 zones whose calendar days always differ (UTC+14 and UTC-11).
EAST: Final = "Pacific/Kiritimati"
WEST: Final = "Pacific/Pago_Pago"
#: A published Constraint's due date far from any test's today.
FAR: Final = date(2099, 1, 1)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _now(runtime: S4Runtime) -> datetime:
    with runtime.engine.connect() as connection:
        now = connection.execute(text("SELECT now()")).scalar_one()
    assert isinstance(now, datetime)
    return now


def _today(runtime: S4Runtime, zone: str) -> date:
    return _now(runtime).astimezone(ZoneInfo(zone)).date()


def _metric(rows: list[dict[str, Any]], metric_id: str) -> dict[str, Any]:
    found = [row for row in rows if row["metric_id"] == metric_id]
    assert len(found) == 1, metric_id
    return found[0]


def _value(rows: list[dict[str, Any]], metric_id: str) -> Any:  # noqa: ANN401
    return _metric(rows, metric_id)["value"]


def _project(answer: dict[str, Any], project_id: str) -> dict[str, Any]:
    found = [entry for entry in answer["per_project"] if entry["project_id"] == project_id]
    assert len(found) == 1, project_id
    return found[0]


def _reasons(rows: list[dict[str, Any]], metric_id: str) -> list[str]:
    return list(_metric(rows, metric_id)["reasons"])


@dataclass(frozen=True)
class _Project:
    project_id: str
    entity_id: str
    category_id: str | None
    target: tuple[str, str | None] | None


def _member(
    runtime: S4Runtime,
    name: str,
    *programs: str,
    zone: str | None = "UTC",
    sync: str | None = "in_sync",
    principal_id: str = PRINCIPAL,
) -> _Project:
    """A bound Project, a dated edge into each Program, its calendar and one sync target.

    `zone=None`: no Constraint calendar. `sync=None`: no target (never synced);
    otherwise a verified target whose last run is in that persisted state.
    """
    seeds = runtime.seeds
    project_id, entity_id = seeds.project(name, principal_id=principal_id)
    for program in programs:
        seeds.edge(entity_id, program, effective_from=T0, principal_id=principal_id)
    category = (
        None
        if zone is None
        else seeds.constraint_calendar(project_id, zone, principal_id=principal_id)
    )
    target = (
        None
        if sync is None
        else seeds.sync_target(project_id, last_run_state=sync, principal_id=principal_id)
    )
    return _Project(project_id, entity_id, category, target)


@dataclass(frozen=True)
class _Scene:
    """The section 10 AT-019 fixture (the parts the metrics read)."""

    g: str
    h: str
    b1: _Project
    b2: _Project
    b3: _Project
    u: _Project
    shared_issue: str
    u_issue: str
    suspended_issue: str
    legacy_issue: str
    closed_issue: str


def _commitments(runtime: S4Runtime, key: str, project_id: str, *, now: datetime) -> None:
    """Open/closed x accepted/proposed, with and without `due_at`, on one Project."""
    past = now - timedelta(days=3)
    future = now + timedelta(days=30)
    work = runtime.work_commitment
    work(f"{key}-oa-past", project_id=project_id, due_at=past)
    work(f"{key}-oa-none", project_id=project_id)
    work(f"{key}-oa-future", project_id=project_id, due_at=future)
    work(f"{key}-op-past", project_id=project_id, accepted=False, due_at=past)
    work(f"{key}-op-none", project_id=project_id, accepted=False)
    closed = work(f"{key}-cp", project_id=project_id, accepted=False)
    runtime.close_work_commitment(closed, f"{key}-cp")
    closed_accepted = work(f"{key}-ca", project_id=project_id)
    runtime.close_work_commitment(closed_accepted, f"{key}-ca")


def _scene(runtime: S4Runtime) -> _Scene:
    seeds = runtime.seeds
    now = _now(runtime)
    g = seeds.program("Program G")
    h = seeds.program("Program H")
    b1 = _member(runtime, "Bayfront Tower", g)
    b2 = _member(runtime, "Second Street", g, zone="America/New_York", sync=None)
    b3 = _member(runtime, "Third Avenue", g, h, zone=EAST)
    # B3's second workbook's last run is `partial`: B3 is `sync_degraded`.
    seeds.sync_target(b3.project_id, last_run_state="partial")
    u = _member(runtime, "Bayfront Tower", h, zone=None)
    for project, key in ((b1, "b1"), (b2, "b2"), (b3, "b3"), (u, "u")):
        _commitments(runtime, key, project.project_id, now=now)
    today = _today(runtime, "UTC")
    assert b1.category_id is not None
    for due in (today - timedelta(days=2), today, today + timedelta(days=60), FAR):
        seeds.constraint(b1.project_id, b1.category_id, due_date=due)
    seeds.constraint(
        b1.project_id, b1.category_id, due_date=None, state=ConstraintLifecycleState.DRAFT
    )
    seeds.constraint(b1.project_id, b1.category_id, due_date=today, in_my_court=False)
    assert b2.category_id is not None and b3.category_id is not None
    seeds.constraint(b2.project_id, b2.category_id, due_date=today - timedelta(days=5))
    seeds.constraint(b3.project_id, b3.category_id, due_date=today + timedelta(days=60))
    shared_issue = runtime.linked_issue("shared", b1.project_id, b2.project_id)
    u_issue = runtime.linked_issue("unrelated", u.project_id)
    suspended_issue = runtime.linked_issue("suspended", b3.project_id)
    runtime.suspend_issue(suspended_issue, "suspended")
    legacy_issue = runtime.issue("s4-legacy")
    seeds.legacy_issue_link(b2.project_id, legacy_issue)
    closed_issue = runtime.issue("s4-closed")
    seeds.close_issue(closed_issue)
    seeds.legacy_issue_link(b1.project_id, closed_issue)
    return _Scene(
        g=g,
        h=h,
        b1=b1,
        b2=b2,
        b3=b3,
        u=u,
        shared_issue=shared_issue,
        u_issue=u_issue,
        suspended_issue=suspended_issue,
        legacy_issue=legacy_issue,
        closed_issue=closed_issue,
    )


def _clean_program(runtime: S4Runtime, name: str, members: int) -> tuple[str, list[_Project]]:
    """A Program whose every member is in sync, on UTC, with no legacy link."""
    program = runtime.seeds.program(name)
    return program, [_member(runtime, f"{name} {index}", program) for index in range(members)]


# --- reconciliation ---------------------------------------------------------


def _native_commitment_counts(
    runtime: S4Runtime, project_id: str, cutoff: datetime
) -> dict[str, int]:
    """The 7 Commitment metrics of one Project from `commitments.v2.list` (every state)."""
    found: list[dict[str, Any]] = []
    for state in (CommitmentState.OPEN, CommitmentState.CLOSED):
        page = runtime.ok(ListCommitmentsV2(project_ids=(project_id,), state=state, page_size=200))
        assert len(page["commitments"]) < 200
        found.extend(page["commitments"])

    def due(entry: dict[str, Any]) -> datetime | None:
        value = entry.get("due_date")
        return None if value is None else datetime.fromisoformat(value)

    def count(state: str, evidence: str, when: str | None = None) -> int:
        rows = [
            entry
            for entry in found
            if entry["state"] == state and entry["evidence_state"] == evidence
        ]
        if when == "overdue":
            rows = [entry for entry in rows if (moment := due(entry)) and moment < cutoff]
        elif when == "unscheduled":
            rows = [entry for entry in rows if due(entry) is None]
        return len(rows)

    return {
        "commitment_open_accepted": count("open", "accepted"),
        "commitment_open_proposed": count("open", "proposed"),
        "commitment_closed_proposed": count("closed", "proposed"),
        "commitment_overdue_accepted": count("open", "accepted", "overdue"),
        "commitment_overdue_proposed": count("open", "proposed", "overdue"),
        "commitment_unscheduled_accepted": count("open", "accepted", "unscheduled"),
        "commitment_unscheduled_proposed": count("open", "proposed", "unscheduled"),
    }


def test_per_project_values_equal_their_native_reads_at_one_cutoff(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    answer = runtime.overview(scene.g, scene.h)
    cutoff = datetime.fromisoformat(answer["source_cutoff_at"])
    native = runtime.ok(ReadPortfolioConstraintOverview())["overview"]
    by_project = {entry["project_id"]: entry for entry in native["projects"]}
    for project in (scene.b1, scene.b2, scene.b3, scene.u):
        entry = _project(answer, project.project_id)
        metrics = entry["metrics"]
        # Commitments: the native `commitments.v2.list` of that Project.
        for metric_id, expected in _native_commitment_counts(
            runtime, project.project_id, cutoff
        ).items():
            assert _value(metrics, metric_id) == expected, (project.project_id, metric_id)
            assert _metric(metrics, metric_id)["value_state"] == "reported"
        # Constraints: the native `constraints.portfolio_overview` entry.
        overview = by_project.get(project.project_id)
        if overview is None:
            # U has no calendar: the native read omits it, the overview discloses it.
            assert project is scene.u
            for metric_id in CONSTRAINT_METRICS:
                assert _metric(metrics, metric_id)["value"] is None
                assert _reasons(metrics, metric_id) == ["calendar_unconfigured"]
            continue
        assert entry["calendar"] == {
            "timezone_name": overview["project_timezone"],
            "project_today": overview["project_today"],
        }
        for metric_id, field in (
            ("constraint_open", "total_open"),
            ("constraint_overdue", "overdue"),
            ("constraint_due_soon", "due_soon"),
            ("constraint_in_my_court", "in_my_court"),
            ("constraint_draft", "draft"),
        ):
            assert _value(metrics, metric_id) == overview[field], (project.project_id, metric_id)
        assert entry["constraint_sync"]["state"] == overview["sync_health"]["state"]
    # The seeded B1 position, stated.
    b1 = _project(answer, scene.b1.project_id)["metrics"]
    assert [_value(b1, metric_id) for metric_id in CONSTRAINT_METRICS] == [5, 1, 2, 4, 1]
    assert [_value(b1, metric_id) for metric_id in COMMITMENT_METRICS] == [3, 2, 1, 1, 1, 1, 1]
    # Issues per Project: the shared Issue on B1 and B2, the suspended one on B3,
    # U's own; the legacy link is not a native link.
    issues = {
        project.project_id: _value(
            _project(answer, project.project_id)["metrics"], "issue_outstanding"
        )
        for project in (scene.b1, scene.b3, scene.u)
    }
    assert issues == {scene.b1.project_id: 1, scene.b3.project_id: 1, scene.u.project_id: 1}


def _direct(runtime: S4Runtime, statement: str, **parameters: object) -> int:
    with runtime.engine.connect() as connection:
        return int(connection.execute(text(statement), parameters).scalar_one())


_DIRECT_COMMITMENTS: Final = {
    "commitment_open_proposed": "state = 'open' AND evidence_state = 'proposed'",
    "commitment_closed_proposed": "state = 'closed' AND evidence_state = 'proposed'",
    "commitment_overdue_proposed": (
        "state = 'open' AND evidence_state = 'proposed' AND due_at < :cutoff"
    ),
    "commitment_unscheduled_proposed": (
        "state = 'open' AND evidence_state = 'proposed' AND due_at IS NULL"
    ),
    "commitment_open_accepted": "state = 'open' AND evidence_state = 'accepted'",
    "commitment_overdue_accepted": (
        "state = 'open' AND evidence_state = 'accepted' AND due_at < :cutoff"
    ),
    "commitment_unscheduled_accepted": (
        "state = 'open' AND evidence_state = 'accepted' AND due_at IS NULL"
    ),
}
_DIRECT_CONSTRAINTS: Final = {
    "constraint_open": "lifecycle_state IN ('identified', 'pending', 'in_progress', 'on_hold')",
    "constraint_draft": "lifecycle_state = 'draft'",
    "constraint_overdue": (
        "lifecycle_state IN ('identified', 'pending', 'in_progress', 'on_hold') "
        "AND due_date < :today"
    ),
    "constraint_due_soon": (
        "lifecycle_state IN ('identified', 'pending', 'in_progress', 'on_hold') "
        "AND due_date BETWEEN :today AND :through"
    ),
}


def test_every_total_equals_a_direct_distinct_count(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Direct", 3)
    other, other_members = _clean_program(runtime, "Direct other", 1)
    # A Project of both Programs, so the portfolio is not the sum of its Programs.
    runtime.seeds.edge(members[0].entity_id, other, effective_from=T0)
    now = _now(runtime)
    today = _today(runtime, "UTC")
    for index, project in enumerate([*members, *other_members]):
        _commitments(runtime, f"direct-{index}", project.project_id, now=now)
        assert project.category_id is not None
        for due in (today - timedelta(days=1), today, FAR):
            runtime.seeds.constraint(project.project_id, project.category_id, due_date=due)
        runtime.seeds.constraint(
            project.project_id,
            project.category_id,
            due_date=None,
            state=ConstraintLifecycleState.DRAFT,
            in_my_court=False,
        )
    runtime.linked_issue("direct-shared", members[0].project_id, members[1].project_id)
    runtime.linked_issue("direct-own", members[2].project_id)
    runtime.linked_issue("direct-other", other_members[0].project_id, members[0].project_id)
    answer = runtime.overview(program, other)
    cutoff = datetime.fromisoformat(answer["source_cutoff_at"])
    # The direct counts classify on the day of the overview's own instant, so a
    # midnight crossing after seeding cannot flake them.
    today = project_today(cutoff, "UTC")
    scopes = [(scope["project_ids"], scope["totals"]) for scope in answer["programs"]]
    scopes.append((answer["portfolio"]["project_ids"], answer["portfolio"]["totals"]))
    assert len(answer["portfolio"]["project_ids"]) == 4
    for project_ids, totals in scopes:
        ids = list(project_ids)
        for metric_id, predicate in _DIRECT_COMMITMENTS.items():
            expected = _direct(
                runtime,
                "SELECT count(DISTINCT commitment_id) FROM knowledge.commitments "  # noqa: S608
                f"WHERE principal_id = :principal AND project_id = ANY(:ids) AND {predicate}",
                principal=PRINCIPAL,
                ids=ids,
                cutoff=cutoff,
            )
            row = _metric(totals, metric_id)
            if metric_id in ACCEPTED:
                # Never reported in S4; the per-Project figures sum to the count.
                assert row["value"] is None and row["reasons"] == ["acceptance_unverified"]
                summed = sum(
                    _value(_project(answer, project_id)["metrics"], metric_id) for project_id in ids
                )
                assert summed == expected, metric_id
            else:
                assert (row["value_state"], row["value"]) == ("reported", expected), metric_id
        expected_issues = _direct(
            runtime,
            "SELECT count(DISTINCT m.issue_id) FROM knowledge.issue_project_membership_events m "
            "JOIN knowledge.situations s ON s.situation_id = m.issue_id "
            "WHERE m.principal_id = :principal AND m.project_id = ANY(:ids) "
            "AND m.state = 'active' AND s.state IN ('open', 'active', 'suspended')",
            principal=PRINCIPAL,
            ids=ids,
        )
        assert _value(totals, "issue_outstanding") == expected_issues
        for metric_id, predicate in _DIRECT_CONSTRAINTS.items():
            expected = _direct(
                runtime,
                "SELECT count(DISTINCT constraint_id) FROM knowledge.project_constraints "  # noqa: S608
                f"WHERE principal_id = :principal AND project_id = ANY(:ids) AND {predicate}",
                principal=PRINCIPAL,
                ids=ids,
                today=today,
                through=due_soon_through(today),
            )
            assert (_metric(totals, metric_id)["value_state"], _value(totals, metric_id)) == (
                "reported",
                expected,
            ), metric_id
        expected_court = _direct(
            runtime,
            "SELECT count(DISTINCT c.constraint_id) FROM knowledge.project_constraints c "
            "JOIN knowledge.project_constraint_parties p ON p.constraint_id = c.constraint_id "
            "WHERE c.principal_id = :principal AND c.project_id = ANY(:ids) "
            "AND c.lifecycle_state IN ('identified', 'pending', 'in_progress', 'on_hold') "
            "AND p.role = 'bic' AND p.party_kind = 'principal'",
            principal=PRINCIPAL,
            ids=ids,
        )
        assert _value(totals, "constraint_in_my_court") == expected_court


def test_a_shared_issue_is_counted_once_in_program_totals(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Shared", 2)
    runtime.linked_issue("shared-once", members[0].project_id, members[1].project_id)
    answer = runtime.overview(program)
    for project in members:
        assert _value(_project(answer, project.project_id)["metrics"], "issue_outstanding") == 1
    for totals in (answer["programs"][0]["totals"], answer["portfolio"]["totals"]):
        row = _metric(totals, "issue_outstanding")
        assert (row["value_state"], row["value"]) == ("reported", 1)


def test_per_project_issue_impact_is_flagged_nonadditive(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Nonadditive", 2)
    runtime.linked_issue("nonadditive", members[0].project_id, members[1].project_id)
    answer = runtime.overview(program)
    rows = [
        *answer["programs"][0]["totals"],
        *answer["portfolio"]["totals"],
        *(row for entry in answer["per_project"] for row in entry["metrics"]),
    ]
    assert rows
    for row in rows:
        assert row["nonadditive_across_projects"] is (row["metric_id"] == "issue_outstanding")
    # The per-Project impacts sum to 2; the total says 1.
    per_project = sum(
        _value(entry["metrics"], "issue_outstanding") for entry in answer["per_project"]
    )
    assert per_project == 2
    assert _value(answer["programs"][0]["totals"], "issue_outstanding") == 1


def test_unverified_acceptance_makes_the_accepted_total_not_reportable(
    runtime: S4Runtime,
) -> None:
    program, members = _clean_program(runtime, "Acceptance", 1)
    runtime.work_commitment("acceptance-open", project_id=members[0].project_id)
    answer = runtime.overview(program)
    per_project = _project(answer, members[0].project_id)["metrics"]
    for metric_id in ACCEPTED:
        for totals in (answer["programs"][0]["totals"], answer["portfolio"]["totals"]):
            row = _metric(totals, metric_id)
            assert row["value"] is None
            assert row["value_state"] == "not_reportable"
            assert row["reasons"] == ["acceptance_unverified"]
            assert row["acceptance"] == "unverified_review_reference"
        # Per Project the figure is shown, marked unverified.
        shown = _metric(per_project, metric_id)
        assert shown["value_state"] == "reported"
        assert shown["acceptance"] == "unverified_review_reference"
    assert _value(per_project, "commitment_open_accepted") == 1
    # The proposed totals are reported, with no acceptance marking.
    proposed = _metric(answer["programs"][0]["totals"], "commitment_open_proposed")
    assert (proposed["value_state"], proposed["value"], proposed["acceptance"]) == (
        "reported",
        0,
        None,
    )


def test_an_unresolved_member_makes_every_total_not_reportable(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Unresolved", 1)
    clean, _clean_members = _clean_program(runtime, "Resolved", 1)
    unbound = runtime.seeds.entity("project", "Unbound member")
    runtime.seeds.edge(unbound, program, effective_from=T0)
    answer = runtime.overview(program, clean)
    scope = answer["programs"][0]
    assert scope["membership_state"] == "membership_unresolved"
    assert [member["member_entity_id"] for member in scope["unresolved_members"]] == [unbound]
    assert scope["denominator"]["unresolved_members"] == 1
    for totals in (scope["totals"], answer["portfolio"]["totals"]):
        for metric_id in METRICS:
            row = _metric(totals, metric_id)
            assert row["value"] is None, metric_id
            assert "membership_unresolved" in row["reasons"], metric_id
    # The resolved Program's own totals are untouched by the other's gap.
    resolved = answer["programs"][1]
    assert resolved["membership_state"] == "complete"
    assert _metric(resolved["totals"], "constraint_open")["value_state"] == "reported"
    # Per Project, the resolved member's figures stay visible.
    assert _metric(_project(answer, members[0].project_id)["metrics"], "constraint_open")[
        "value_state"
    ] == ("reported")
    assert answer["complete_state"] == "membership_unresolved"


# --- Constraint source state (section 3.3, R4-F01) ----------------------------


def _constraint_totals(answer: dict[str, Any], index: int = 0) -> list[dict[str, Any]]:
    return [
        _metric(answer["programs"][index]["totals"], metric_id) for metric_id in CONSTRAINT_METRICS
    ]


def test_a_never_synced_project_makes_constraint_totals_not_reportable(
    runtime: S4Runtime,
) -> None:
    program, members = _clean_program(runtime, "Never synced", 1)
    never = _member(runtime, "Never synced member", program, sync=None)
    assert never.category_id is not None
    runtime.seeds.constraint(never.project_id, never.category_id, due_date=FAR)
    answer = runtime.overview(program)
    entry = _project(answer, never.project_id)
    assert entry["constraint_source_state"] == "never_synced"
    assert entry["constraint_sync"]["state"] == "never_synced"
    # Per Project the count is shown with its source state; the total is not.
    assert _value(entry["metrics"], "constraint_open") == 1
    for row in _constraint_totals(answer):
        assert (row["value"], row["value_state"], row["reasons"]) == (
            None,
            "not_reportable",
            ["never_synced"],
        )
    assert _project(answer, members[0].project_id)["constraint_source_state"] == "in_sync"


def test_a_never_verified_target_is_unverified_not_in_sync(runtime: S4Runtime) -> None:
    program = runtime.seeds.program("Unverified")
    unverified = _member(runtime, "Unverified member", program, sync=None)
    runtime.seeds.sync_target(unverified.project_id, verified=False, last_run_state="in_sync")
    no_run = _member(runtime, "No run member", program, sync=None)
    runtime.seeds.sync_target(no_run.project_id, verified=True, last_run_state=None)
    answer = runtime.overview(program)
    for project in (unverified, no_run):
        entry = _project(answer, project.project_id)
        assert entry["constraint_source_state"] == "unverified"
        # The portfolio read model's 3-way health reads it `in_sync`, deciding nothing.
        assert entry["constraint_sync"]["state"] == "in_sync"
    for row in _constraint_totals(answer):
        assert row["value"] is None
        assert row["reasons"] == ["sync_unverified"]


@pytest.mark.parametrize("run_state", ["verification_failed", "partial", "db_export_pending"])
def test_a_failed_or_partial_last_run_is_sync_degraded_not_in_sync(
    runtime: S4Runtime, run_state: str
) -> None:
    program = runtime.seeds.program(f"Degraded {run_state}")
    degraded = _member(runtime, "Degraded member", program, sync=run_state)
    answer = runtime.overview(program)
    entry = _project(answer, degraded.project_id)
    assert entry["constraint_source_state"] == "sync_degraded"
    assert entry["constraint_last_run_sync_states"] == [run_state]
    assert entry["constraint_sync"]["state"] == "in_sync"
    for row in _constraint_totals(answer):
        assert (row["value"], row["reasons"]) == (None, ["sync_degraded"])


def test_a_project_is_in_sync_only_when_every_target_is(runtime: S4Runtime) -> None:
    program = runtime.seeds.program("Two workbooks")
    mixed = _member(runtime, "Mixed member", program, sync="in_sync")
    runtime.seeds.sync_target(mixed.project_id, last_run_state="partial")
    both = _member(runtime, "Both in sync", program, sync="in_sync")
    runtime.seeds.sync_target(both.project_id, last_run_state="in_sync")
    answer = runtime.overview(program)
    mixed_entry = _project(answer, mixed.project_id)
    assert mixed_entry["constraint_source_state"] == "sync_degraded"
    assert mixed_entry["constraint_last_run_sync_states"] == ["in_sync", "partial"]
    assert _project(answer, both.project_id)["constraint_source_state"] == "in_sync"
    denominator = answer["programs"][0]["denominator"]
    assert denominator["projects_by_constraint_source_state"]["sync_degraded"] == 1
    assert denominator["projects_by_constraint_source_state"]["in_sync"] == 1
    for row in _constraint_totals(answer):
        assert row["reasons"] == ["sync_degraded"]


def test_a_sync_conflict_makes_constraint_totals_not_reportable(runtime: S4Runtime) -> None:
    program = runtime.seeds.program("Conflict")
    conflicted = _member(runtime, "Conflicted member", program, sync="in_sync")
    assert conflicted.category_id is not None and conflicted.target is not None
    target, run = conflicted.target
    assert run is not None
    constraint = runtime.seeds.constraint(
        conflicted.project_id, conflicted.category_id, due_date=FAR
    )
    runtime.seeds.sync_conflict(conflicted.project_id, target, run, constraint)
    answer = runtime.overview(program)
    entry = _project(answer, conflicted.project_id)
    assert entry["constraint_source_state"] == "conflict"
    assert entry["constraint_sync"] == {
        "state": "conflict",
        "open_conflict_count": 1,
        "last_verified_at": entry["constraint_sync"]["last_verified_at"],
    }
    for row in _constraint_totals(answer):
        assert (row["value"], row["reasons"]) == (None, ["sync_conflict"])


# --- legacy Issue links and Issue states (R4-F02, R4-F16) ------------------------


def test_a_legacy_issue_link_makes_the_issue_metric_not_reportable(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Legacy", 2)
    legacy = runtime.issue("s4-legacy-open")
    runtime.seeds.legacy_issue_link(members[0].project_id, legacy)
    runtime.linked_issue("legacy-native", members[1].project_id)
    answer = runtime.overview(program)
    entry = _project(answer, members[0].project_id)
    assert (entry["legacy_issue_links"], entry["legacy_issue_links_closed"]) == (1, 0)
    row = _metric(entry["metrics"], "issue_outstanding")
    assert (row["value"], row["value_state"], row["reasons"]) == (
        None,
        "not_reportable",
        ["issue_link_unverified"],
    )
    # The other Project's Issue metric is reported; every total holding the
    # legacy Project is not.
    assert _value(_project(answer, members[1].project_id)["metrics"], "issue_outstanding") == 1
    for scope in (answer["programs"][0], answer["portfolio"]):
        total = _metric(scope["totals"], "issue_outstanding")
        assert (total["value"], total["reasons"]) == (None, ["issue_link_unverified"])
        assert scope["denominator"]["legacy_issue_links"] == 1
        assert scope["project_ids_with_legacy_issue_links"] == [members[0].project_id]
    # The legacy link is neither counted nor repaired: it is still not an event.
    assert (
        _direct(
            runtime,
            "SELECT count(*) FROM knowledge.issue_project_membership_events "
            "WHERE principal_id = :principal AND issue_id = :issue",
            principal=PRINCIPAL,
            issue=legacy,
        )
        == 0
    )


def test_a_legacy_link_of_a_closed_issue_is_disclosed_and_never_gates(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Closed legacy", 1)
    closed = runtime.issue("s4-closed-legacy")
    runtime.seeds.close_issue(closed)
    runtime.seeds.legacy_issue_link(members[0].project_id, closed)
    answer = runtime.overview(program)
    entry = _project(answer, members[0].project_id)
    assert (entry["legacy_issue_links"], entry["legacy_issue_links_closed"]) == (0, 1)
    assert _metric(entry["metrics"], "issue_outstanding")["value_state"] == "reported"
    for scope in (answer["programs"][0], answer["portfolio"]):
        total = _metric(scope["totals"], "issue_outstanding")
        assert (total["value_state"], total["value"], total["reasons"]) == ("reported", 0, [])
        assert scope["denominator"]["legacy_issue_links"] == 0
        assert scope["denominator"]["legacy_issue_links_closed"] == 1
        assert scope["project_ids_with_legacy_issue_links"] == []


def test_a_suspended_issue_is_outstanding(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Suspended", 1)
    project_id = members[0].project_id
    open_issue = runtime.linked_issue("open-one", project_id)
    suspended = runtime.linked_issue("suspended-one", project_id)
    runtime.suspend_issue(suspended, "suspended-one")
    closed = runtime.linked_issue("closed-one", project_id)
    runtime.seeds.close_issue(closed)
    assert open_issue
    answer = runtime.overview(program)
    assert _value(_project(answer, project_id)["metrics"], "issue_outstanding") == 2
    assert _value(answer["programs"][0]["totals"], "issue_outstanding") == 2


# --- each Project's own calendar ------------------------------------------------


def _two_calendars(runtime: S4Runtime, name: str) -> tuple[str, _Project, _Project, date]:
    """A Program of an east (UTC+14) and a west (UTC-11) Project, and the west's today.

    One Constraint each, due on the west Project's today: due today (due soon)
    in the west, already past (overdue) in the east.
    """
    program = runtime.seeds.program(name)
    east = _member(runtime, f"{name} east", program, zone=EAST)
    west = _member(runtime, f"{name} west", program, zone=WEST)
    west_today = _today(runtime, WEST)
    assert _today(runtime, EAST) > west_today
    for project in (east, west):
        assert project.category_id is not None
        runtime.seeds.constraint(project.project_id, project.category_id, due_date=west_today)
    return program, east, west, west_today


def _days_at_the_cutoff(answer: dict[str, Any]) -> tuple[date, date]:
    """Each zone's calendar day at the answer's own snapshot instant: `(east, west)`.

    The expectations derive from the instant the overview read, never from a
    clock read before seeding, so a midnight crossing in either zone between
    the seeding and the snapshot cannot flake the test.
    """
    cutoff = datetime.fromisoformat(answer["source_cutoff_at"])
    east, west = project_today(cutoff, EAST), project_today(cutoff, WEST)
    assert east > west
    return east, west


def _due_soon(today: date, due: date) -> int:
    return int(today <= due <= due_soon_through(today))


def test_constraint_due_soon_uses_each_projects_own_calendar(runtime: S4Runtime) -> None:
    program, east, west, due = _two_calendars(runtime, "Due soon")
    answer = runtime.overview(program)
    east_today, west_today = _days_at_the_cutoff(answer)
    west_entry = _project(answer, west.project_id)
    east_entry = _project(answer, east.project_id)
    assert west_entry["calendar"] == {
        "timezone_name": WEST,
        "project_today": west_today.isoformat(),
    }
    assert east_entry["calendar"] == {
        "timezone_name": EAST,
        "project_today": east_today.isoformat(),
    }
    expected = {"west": _due_soon(west_today, due), "east": _due_soon(east_today, due)}
    if west_today == due:
        # No midnight crossing since seeding: due today in the west, already
        # past in the east -- one due date, 2 calendars, 2 answers.
        assert expected == {"west": 1, "east": 0}
    assert _value(west_entry["metrics"], "constraint_due_soon") == expected["west"]
    assert _value(east_entry["metrics"], "constraint_due_soon") == expected["east"]
    assert _value(answer["programs"][0]["totals"], "constraint_due_soon") == sum(expected.values())


def test_constraint_overdue_uses_each_projects_own_calendar(runtime: S4Runtime) -> None:
    program, east, west, due = _two_calendars(runtime, "Overdue")
    answer = runtime.overview(program)
    east_today, west_today = _days_at_the_cutoff(answer)
    expected = {"west": int(due < west_today), "east": int(due < east_today)}
    if west_today == due:
        # No midnight crossing since seeding: overdue in the east only.
        assert expected == {"west": 0, "east": 1}
    assert (
        _value(_project(answer, east.project_id)["metrics"], "constraint_overdue")
        == expected["east"]
    )
    assert (
        _value(_project(answer, west.project_id)["metrics"], "constraint_overdue")
        == expected["west"]
    )
    total = _metric(answer["programs"][0]["totals"], "constraint_overdue")
    assert (total["value_state"], total["value"], total["nonadditive_across_projects"]) == (
        "reported",
        sum(expected.values()),
        False,
    )


def test_a_project_without_a_calendar_is_disclosed_not_dropped(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Calendar", 1)
    bare = _member(runtime, "No calendar", program, zone=None, sync="in_sync")
    answer = runtime.overview(program)
    assert bare.project_id in answer["programs"][0]["project_ids"]
    entry = _project(answer, bare.project_id)
    assert entry["calendar"] == {"timezone_name": None, "project_today": None}
    assert entry["constraint_source_state"] == "calendar_unconfigured"
    # Its sync is still shown (from the stored target), deciding nothing.
    assert entry["constraint_sync"]["state"] == "in_sync"
    for metric_id in CONSTRAINT_METRICS:
        row = _metric(entry["metrics"], metric_id)
        assert (row["value"], row["value_state"], row["reasons"]) == (
            None,
            "not_reportable",
            ["calendar_unconfigured"],
        )
    for row in _constraint_totals(answer):
        assert (row["value"], row["reasons"]) == (None, ["calendar_unconfigured"])
    scope = answer["programs"][0]
    assert scope["denominator"]["projects_by_constraint_source_state"]["calendar_unconfigured"] == 1
    assert scope["project_ids_by_constraint_source_state"]["calendar_unconfigured"] == [
        bare.project_id
    ]
    # The calendared member keeps its figures.
    assert _metric(_project(answer, members[0].project_id)["metrics"], "constraint_open")[
        "value_state"
    ] == ("reported")


def test_a_verified_zero_is_reported_as_zero(runtime: S4Runtime) -> None:
    program, _members = _clean_program(runtime, "Zero", 2)
    answer = runtime.overview(program)
    for scope in (answer["programs"][0], answer["portfolio"]):
        for metric_id in METRICS:
            row = _metric(scope["totals"], metric_id)
            if metric_id in ACCEPTED:
                assert (row["value"], row["reasons"]) == (None, ["acceptance_unverified"])
                continue
            assert (row["value_state"], row["value"], row["reasons"]) == ("reported", 0, [])
    assert answer["complete_state"] == "complete"


def test_the_denominator_names_every_project_state(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    answer = runtime.overview(scene.g, scene.h)
    g, h = answer["programs"]
    assert g["project_ids"] == sorted(
        [scene.b1.project_id, scene.b2.project_id, scene.b3.project_id]
    )
    assert h["project_ids"] == sorted([scene.b3.project_id, scene.u.project_id])
    assert g["denominator"] == {
        "member_projects": 3,
        "unresolved_members": 0,
        "legacy_issue_links": 1,
        "legacy_issue_links_closed": 1,
        "projects_by_constraint_source_state": {
            "in_sync": 1,
            "never_synced": 1,
            "unverified": 0,
            "sync_degraded": 1,
            "conflict": 0,
            "calendar_unconfigured": 0,
        },
    }
    assert g["project_ids_by_constraint_source_state"] == {
        "in_sync": [scene.b1.project_id],
        "never_synced": [scene.b2.project_id],
        "unverified": [],
        "sync_degraded": [scene.b3.project_id],
        "conflict": [],
        "calendar_unconfigured": [],
    }
    assert g["project_ids_with_legacy_issue_links"] == [scene.b2.project_id]
    portfolio = answer["portfolio"]
    assert portfolio["project_ids"] == sorted(
        [scene.b1.project_id, scene.b2.project_id, scene.b3.project_id, scene.u.project_id]
    )
    assert portfolio["overlaps"] == [
        {"project_id": scene.b3.project_id, "program_entity_ids": sorted([scene.g, scene.h])}
    ]
    assert portfolio["denominator"]["member_projects"] == 4
    assert (
        portfolio["denominator"]["projects_by_constraint_source_state"]["calendar_unconfigured"]
        == 1
    )
    assert portfolio["project_ids_by_constraint_source_state"]["calendar_unconfigured"] == [
        scene.u.project_id
    ]
    # Every total of G names its reasons: the B2 legacy link gates the Issue
    # metric; never-synced and degraded gate the Constraint metrics.
    assert _reasons(g["totals"], "issue_outstanding") == ["issue_link_unverified"]
    for metric_id in CONSTRAINT_METRICS:
        assert _reasons(g["totals"], metric_id) == ["never_synced", "sync_degraded"]
        assert _reasons(portfolio["totals"], metric_id) == [
            "calendar_unconfigured",
            "never_synced",
            "sync_degraded",
        ]
    # The B1/B2 Issue counts once in G (it is the only countable Issue there
    # besides B3's suspended one), while the per-Project B2 figure is gated.
    assert _metric(_project(answer, scene.b2.project_id)["metrics"], "issue_outstanding")[
        "reasons"
    ] == ["issue_link_unverified"]
    assert _value(_project(answer, scene.b1.project_id)["metrics"], "issue_outstanding") == 1


def test_the_overview_digest_is_stable_and_sensitive(runtime: S4Runtime) -> None:
    program, members = _clean_program(runtime, "Digest", 2)
    first = runtime.overview(program)
    second = runtime.overview(program)
    # 2 snapshots of an unchanged state: different cutoffs, one digest.
    assert first["source_cutoff_at"] != second["source_cutoff_at"]
    assert first["overview_sha256"] == second["overview_sha256"]
    seen = {first["overview_sha256"]}

    def changed() -> str:
        digest = str(runtime.overview(program)["overview_sha256"])
        assert digest not in seen
        seen.add(digest)
        return digest

    # A metric value.
    runtime.work_commitment("digest-proposed", project_id=members[0].project_id, accepted=False)
    changed()
    # A reportability reason and source state (a degraded second workbook).
    runtime.seeds.sync_target(members[1].project_id, last_run_state="partial")
    changed()
    # Membership (a third member).
    _member(runtime, "Digest third", program)
    changed()
    # A per-Project-only fact: the 2nd member's Constraint calendar zone.
    with runtime.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.constraint_project_settings SET timezone_name = :zone "
                "WHERE principal_id = :principal AND project_id = :project_id"
            ),
            {"zone": EAST, "principal": PRINCIPAL, "project_id": members[1].project_id},
        )
    changed()
    # Another Principal's rows never move it.
    current = runtime.overview(program)["overview_sha256"]
    other_program, _other = (
        runtime.seeds.program("Digest other", principal_id=OTHER_PRINCIPAL),
        None,
    )
    _member(runtime, "Digest foreign", other_program, principal_id=OTHER_PRINCIPAL)
    assert runtime.overview(program)["overview_sha256"] == current
