"""AT-017 (scenario D): one Issue shared across two Projects.

S2 contract sections 3.1, 3.3 and 6.4 against PostgreSQL, through
`ApplicationService.invoke`. One Issue links two Projects (each once), holds
two Constraints -- one per Project -- as independent `constraint` members, each
escalated from the same Task by its own Project-qualified `escalated_from`.
Closing one Constraint natively closes neither the other nor the Issue (no
cascade), an escalation whose Constraint's Project is not actively linked to
the Issue is refused, and a Project link is never a generic membership.

Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from my_pa.application.commands import (
    AddIssueProjectLink,
    EndIssueMembership,
    EndIssueProjectLink,
    ReadConstraint,
    ReadIssue,
    ReadRecordLineage,
)
from tests.database.lineage_record_harness import NOTE_BODY, meeting, note_anchor
from tests.database.lineage_s2_harness import GATEWAY, S2Runtime, all_s2_counts, assertion

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


@dataclass(frozen=True)
class _Shared:
    issue: str
    projects: tuple[str, str]
    task: str
    constraints: tuple[str, str]
    constraint_links: tuple[str, str]
    origin: dict[str, object]


def _shared(runtime: S2Runtime, key: str) -> _Shared:
    """I linked to P1 and P2; T1 a `work` member; X1 in P1 and X2 in P2, `constraint` members."""
    issue = runtime.issue(key)
    projects = (
        runtime.project_with_constraints(f"{key}-p1"),
        runtime.project_with_constraints(f"{key}-p2"),
    )
    for index, project in enumerate(projects, start=1):
        runtime.link_project(issue, project, f"{key}-p{index}")
    task_id = runtime.task(key)
    runtime.member(issue, "task", task_id, f"{key}-t1", "work")
    constraints = (
        runtime.constraint(projects[0], f"{key}-x1"),
        runtime.constraint(projects[1], f"{key}-x2"),
    )
    links = (
        runtime.member(issue, "constraint", constraints[0], f"{key}-x1", "constraint"),
        runtime.member(issue, "constraint", constraints[1], f"{key}-x2", "constraint"),
    )
    meeting_id, note_id = meeting(runtime, f"{key}-n")
    origin = note_anchor(meeting_id, note_id, NOTE_BODY)
    return _Shared(issue, projects, task_id, constraints, links, origin)


def _escalate(scene: _Shared, constraint: str, key: str) -> Any:  # noqa: ANN401
    return assertion(
        "escalated_from",
        ("constraint", constraint),
        ("task", scene.task),
        key,
        (scene.origin,),
        context=scene.issue,
    )


def _constraint(runtime: S2Runtime, constraint_id: str) -> dict[str, Any]:
    return dict(runtime.ok(ReadConstraint(constraint_id=constraint_id))["constraint"])


def _issue(runtime: S2Runtime, issue_id: str) -> dict[str, Any]:
    return dict(runtime.ok(ReadIssue(issue_id=issue_id, include_members=True)))


def test_one_issue_links_two_projects_once_each(runtime: S2Runtime) -> None:
    issue = runtime.issue("xp-links")
    projects = [runtime.project(f"xp-links-p{index}") for index in (1, 2)]
    commands = [
        AddIssueProjectLink(
            issue_id=issue,
            project_id=project,
            expected_membership_revision=0,
            idempotency_key=f"s2-xp-link-{index}",
        )
        for index, project in enumerate(projects, start=1)
    ]
    for command in commands:
        runtime.ok(command, surface=GATEWAY)
    counts = all_s2_counts(runtime.engine)
    # The same request again is its replay, never a second link.
    for command in commands:
        assert runtime.ok(command, surface=GATEWAY)["replayed"] is True
    assert all_s2_counts(runtime.engine) == counts
    links = runtime.ok(ReadIssue(issue_id=issue))["issue"]["project_links"]
    assert sorted(link["project_id"] for link in links) == sorted(projects)
    assert {(link["state"], link["membership_revision_no"]) for link in links} == {("active", 1)}
    assert counts["project_situations"] == 2


def test_two_constraints_in_two_projects_are_independent_members(runtime: S2Runtime) -> None:
    scene = _shared(runtime, "xp-members")
    escalations = [
        runtime.ok(_escalate(scene, constraint, f"xp-members-esc-{index}"), surface=GATEWAY)[
            "association"
        ]
        for index, constraint in enumerate(scene.constraints, start=1)
    ]
    assert len({view["link_id"] for view in escalations}) == 2
    assert [view["from"]["record_id"] for view in escalations] == list(scene.constraints)
    members = _issue(runtime, scene.issue)["memberships"]
    constraint_members = [view for view in members if view["member_role"] == "constraint"]
    assert sorted(view["to"]["record_id"] for view in constraint_members) == sorted(
        scene.constraints
    )
    # Each blocks the gate on its own.
    blocked = {
        blocker["member"]["record_id"]: blocker["reasons"]
        for blocker in runtime.readiness(scene.issue)["blockers"]
    }
    assert set(scene.constraints) <= set(blocked)
    # Ending one membership leaves the other, and both escalations, untouched.
    runtime.ok(
        EndIssueMembership(
            link_id=scene.constraint_links[0],
            expected_revision=1,
            idempotency_key="s2-xp-members-end-x1",
            reason="X1 leaves the Issue's scope.",
        ),
        surface=GATEWAY,
    )
    after = {view["link_id"]: view for view in _issue(runtime, scene.issue)["memberships"]}
    assert scene.constraint_links[0] not in after
    assert after[scene.constraint_links[1]]["revision_no"] == 1
    for view in escalations:
        lineage = runtime.ok(
            ReadRecordLineage(
                origin={"family": "constraint", "record_id": view["from"]["record_id"]},
                issue_id=scene.issue,
            )
        )
        assert view["link_id"] in {edge["link_id"] for edge in lineage["typed_edges"]}


def test_closing_one_constraint_closes_neither_the_other_nor_the_issue(
    runtime: S2Runtime,
) -> None:
    scene = _shared(runtime, "xp-close")
    for index, constraint in enumerate(scene.constraints, start=1):
        runtime.ok(_escalate(scene, constraint, f"xp-close-esc-{index}"), surface=GATEWAY)
    x1, x2 = scene.constraints
    other_before = _constraint(runtime, x2)
    issue_before = _issue(runtime, scene.issue)
    counts = all_s2_counts(runtime.engine)
    runtime.close_constraint(x1, "xp-close-x1")
    assert _constraint(runtime, x1)["status"] == "closed"
    assert _constraint(runtime, x2) == other_before
    assert other_before["status"] == "identified"
    assert _issue(runtime, scene.issue) == issue_before
    assert issue_before["issue"]["state"] == "open"
    # No lineage row moved with the native close.
    assert all_s2_counts(runtime.engine) == counts
    blocked = {
        blocker["member"]["record_id"]: blocker["reasons"]
        for blocker in runtime.readiness(scene.issue)["blockers"]
    }
    # X1 is closed, but its membership carries no resolution evidence, and what
    # it recorded predates the close; X2 is still open.
    assert blocked[x1] == ["resolution_evidence_missing", "resolution_evidence_stale"]
    assert blocked[x2][0] == "native_open"


def test_an_escalation_outside_a_linked_project_is_refused(runtime: S2Runtime) -> None:
    scene = _shared(runtime, "xp-outside")
    unlinked = runtime.project_with_constraints("xp-outside-p3")
    x3 = runtime.constraint(unlinked, "xp-outside-x3")
    runtime.member(scene.issue, "constraint", x3, "xp-outside-x3", "constraint")
    counts = all_s2_counts(runtime.engine)
    # X3 is a member, but its Project P3 was never linked to the Issue.
    error = runtime.refused(_escalate(scene, x3, "xp-outside-x3"), surface=GATEWAY)
    assert (error["code"], error["safe_details"]) == ("invalid_request", ["project_id"])
    assert all_s2_counts(runtime.engine) == counts
    # A link that has ended no longer qualifies the Project either.
    runtime.ok(
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.projects[1],
            expected_membership_revision=1,
            idempotency_key="s2-xp-outside-unlink-p2",
            reason="P2 leaves the Issue.",
        ),
        surface=GATEWAY,
    )
    counts = all_s2_counts(runtime.engine)
    error = runtime.refused(
        _escalate(scene, scene.constraints[1], "xp-outside-x2"), surface=GATEWAY
    )
    assert (error["code"], error["safe_details"]) == ("invalid_request", ["project_id"])
    assert all_s2_counts(runtime.engine) == counts
    # The still-linked Project's Constraint escalates.
    runtime.ok(_escalate(scene, scene.constraints[0], "xp-outside-x1"), surface=GATEWAY)


def test_project_links_create_no_generic_membership(runtime: S2Runtime) -> None:
    issue = runtime.issue("xp-generic")
    for index in (1, 2):
        runtime.link_project(issue, runtime.project(f"xp-generic-p{index}"), f"xp-generic-{index}")
    read = _issue(runtime, issue)
    assert read["memberships"] == []
    assert len(read["issue"]["project_links"]) == 2
    counts = all_s2_counts(runtime.engine)
    assert counts["record_links"] == 0
    lineage = runtime.ok(ReadRecordLineage(origin={"family": "situation", "record_id": issue}))
    assert [(node["family"], node["record_id"]) for node in lineage["nodes"]] == [
        ("situation", issue)
    ]
    assert lineage["typed_edges"] == []
