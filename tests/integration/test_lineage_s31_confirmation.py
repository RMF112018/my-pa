"""Record lineage S3.1: the human channel confirms a client fact (database).

S3.1 contract sections 4.7, 7.2 and 7.3 through `ApplicationService.invoke`
against PostgreSQL (worker N2). A confirmation is a new immutable revision (or
Project-link event), never a mutation: action `confirm`, the same lifecycle
state, `user_confirmed`, the attested pair and a reason, the head's evidence
re-cited anchor by anchor and its recorded member version copied. Only a
`client_identified` head that is `active` or `ended` is confirmed; anything
else is `conflict` / `state`, a stale expectation `conflict` /
`stale_version`, and a closed Issue refuses the confirm of a link in its
context. Every identity and every body here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.application.commands import (
    AddIssueProjectLink,
    ConfirmIssueMembership,
    ConfirmIssueProjectLink,
    ConfirmRecordAssociation,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
)
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.database.lineage_record_harness import NOTE_BODY, membership, note_anchor
from tests.database.lineage_s2_harness import assertion, close, resolution_anchor
from tests.database.lineage_s3_harness import contest, contradicts, corroborates
from tests.database.lineage_s31_harness import GATEWAY, OpenScene, S31Runtime, open_scene

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _blocks(runtime: S31Runtime, scene: OpenScene, key: str, *, context: bool = True) -> Any:  # noqa: ANN401
    task_a = runtime.task(f"{key}-a")
    task_b = runtime.task(f"{key}-b")
    return assertion(
        "blocks",
        ("task", task_a),
        ("task", task_b),
        key,
        (
            corroborates(scene.meeting, scene.note),
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="corroborates", passage="pour"),
        ),
        context=scene.issue if context else None,
    )


def _confirm(link_id: str, revision: int, key: str) -> ConfirmRecordAssociation:
    return ConfirmRecordAssociation(
        link_id=link_id,
        expected_revision=revision,
        idempotency_key=f"s31-confirm-{key}",
        reason="Checked against the cited passage.",
    )


def _confirm_member(link_id: str, revision: int, key: str) -> ConfirmIssueMembership:
    return ConfirmIssueMembership(
        link_id=link_id,
        expected_revision=revision,
        idempotency_key=f"s31-confirm-member-{key}",
        reason="Checked.",
    )


def _confirm_link(scene: OpenScene, revision: int, key: str) -> ConfirmIssueProjectLink:
    return ConfirmIssueProjectLink(
        issue_id=scene.issue,
        project_id=scene.project,
        expected_membership_revision=revision,
        idempotency_key=f"s31-confirm-link-{key}",
        reason="Checked.",
    )


def _revisions(runtime: S31Runtime, link_id: str) -> list[tuple[Any, ...]]:
    with runtime.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT revision_no, action, lifecycle_state, acceptance_basis, authority_class,"
                " decision_channel, evidence_set_digest, evidence_count, member_native_version,"
                " reason FROM knowledge.record_link_revisions WHERE link_id = :link"
                " ORDER BY revision_no"
            ),
            {"link": link_id},
        ).all()
    return [tuple(row) for row in rows]


def _cited(runtime: S31Runtime, link_id: str, revision: int) -> list[tuple[Any, ...]]:
    with runtime.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT ordinal, anchor_id, role FROM knowledge.record_link_revision_evidence"
                " WHERE link_id = :link AND revision_no = :revision ORDER BY ordinal"
            ),
            {"link": link_id, "revision": revision},
        ).all()
    return [tuple(row) for row in rows]


def _state(error: dict[str, Any]) -> tuple[str, list[str]]:
    return str(error["code"]), list(error.get("safe_details") or [])


def test_confirm_appends_a_user_confirmed_revision_with_the_same_evidence(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "confirm")
    asserted = runtime.client_ok(_blocks(runtime, scene, "confirm"))["association"]
    link = asserted["link_id"]
    written = runtime.ok(_confirm(link, 1, "confirm"), surface=GATEWAY)
    association = written["association"]
    assert written["restricted"] is False
    assert (association["revision_no"], association["lifecycle_state"]) == (2, "active")
    assert association["acceptance_basis"] == "user_confirmed"
    assert association["evidence"] == asserted["evidence"]
    first, confirmed = _revisions(runtime, link)
    assert confirmed[1:6] == (
        "confirm",
        "active",
        "user_confirmed",
        "local_operator",
        "local_web",
    )
    # The same evidence set: same digest and count, the same anchors in order.
    assert confirmed[6:9] == first[6:9]
    assert confirmed[9] == "Checked against the cited passage."
    assert _cited(runtime, link, 2) == _cited(runtime, link, 1)


def test_confirm_of_a_user_confirmed_or_contested_head_is_conflict_state(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "confirm-state")
    operator = runtime.ok(_blocks(runtime, scene, "confirm-state-operator"), surface=GATEWAY)
    contested = runtime.client_ok(_blocks(runtime, scene, "confirm-state-contested"))
    runtime.client_ok(
        contest(
            contested["association"]["link_id"],
            1,
            "confirm-state",
            (contradicts(scene.meeting, scene.note),),
        )
    )
    confirmed = runtime.client_ok(_blocks(runtime, scene, "confirm-state-twice"))
    runtime.ok(_confirm(confirmed["association"]["link_id"], 1, "twice-1"), surface=GATEWAY)
    before = _revisions(runtime, confirmed["association"]["link_id"])
    for link, revision, key in (
        (operator["association"]["link_id"], 1, "operator"),
        (contested["association"]["link_id"], 2, "contested"),
        (confirmed["association"]["link_id"], 2, "twice-2"),
    ):
        error = runtime.refused(_confirm(link, revision, key), surface=GATEWAY)
        assert _state(error) == ("conflict", ["state"]), key
    assert _revisions(runtime, confirmed["association"]["link_id"]) == before


def test_confirm_of_a_client_ended_link_keeps_it_ended(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "confirm-ended")
    link = runtime.client_ok(_blocks(runtime, scene, "confirm-ended"))["association"]["link_id"]
    runtime.client_ok(
        EndRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key="s31-confirm-ended-end",
            reason="A client ended it.",
        )
    )
    written = runtime.ok(_confirm(link, 2, "ended"), surface=GATEWAY)["association"]
    assert (written["lifecycle_state"], written["acceptance_basis"]) == ("ended", "user_confirmed")
    member = runtime.client_ok(membership(scene.issue, "task", scene.member_task, "ended"))[
        "membership"
    ]["link_id"]
    runtime.local_ok(
        EndIssueMembership(
            link_id=member,
            expected_revision=1,
            idempotency_key="s31-confirm-ended-member-end",
            reason="A client ended it.",
        )
    )
    confirmed = runtime.ok(_confirm_member(member, 2, "ended"), surface=GATEWAY)["membership"]
    assert (confirmed["lifecycle_state"], confirmed["revision_no"]) == ("ended", 3)
    assert [row[1:4] for row in _revisions(runtime, member)] == [
        ("assert", "active", "client_identified"),
        ("end", "ended", "client_identified"),
        ("confirm", "ended", "user_confirmed"),
    ]


def test_a_confirmed_membership_keeps_its_recorded_member_version(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "confirm-version")
    task_id = runtime.task("confirm-version")
    recorded = runtime.task_version(task_id)
    member = runtime.client_ok(
        membership(
            scene.issue,
            "task",
            task_id,
            "confirm-version",
            role="work",
            anchors=(resolution_anchor(scene.meeting, scene.note),),
        )
    )["membership"]["link_id"]
    moved = runtime.transition(task_id, TaskLifecycleState.COMPLETED, "confirm-version")
    assert moved != recorded
    runtime.ok(_confirm_member(member, 1, "version"), surface=GATEWAY)
    revisions = _revisions(runtime, member)
    # The head's observed version is copied: evidence that was stale stays stale.
    assert [row[8] for row in revisions] == [recorded, recorded]
    readiness = runtime.readiness(scene.issue)
    (blocker,) = readiness["blockers"]
    assert "resolution_evidence_stale" in blocker["reasons"]


def test_project_link_confirm_appends_a_confirm_event(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "confirm-plink")
    anchor = note_anchor(scene.meeting, scene.note, NOTE_BODY, role="corroborates", passage=None)
    added = runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-confirm-plink-add",
            evidence_anchor=anchor,
        )
    )["project_link"]
    confirmed = runtime.ok(_confirm_link(scene, 1, "plink"), surface=GATEWAY)
    view = confirmed["project_link"]
    assert confirmed["restricted"] is False
    assert (view["state"], view["membership_revision_no"], view["acceptance_basis"]) == (
        "active",
        2,
        "user_confirmed",
    )
    assert view["evidence_anchor_id"] == added["evidence_anchor_id"] is not None
    with runtime.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT revision_no, action, state, acceptance_basis, decision_channel, reason"
                " FROM knowledge.issue_project_membership_events"
                " WHERE issue_id = :issue ORDER BY revision_no"
            ),
            {"issue": scene.issue},
        ).all()
    assert [tuple(row) for row in rows] == [
        (1, "assert", "active", "client_identified", "remote_interactive", None),
        (2, "confirm", "active", "user_confirmed", "local_web", "Checked."),
    ]
    # A client's end is confirmed as an end: the state is kept.
    other = runtime.project("confirm-plink-ended")
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=other,
            expected_membership_revision=0,
            idempotency_key="s31-confirm-plink-other",
        )
    )
    runtime.client_ok(
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=other,
            expected_membership_revision=1,
            idempotency_key="s31-confirm-plink-other-end",
            reason="A client ended it.",
        )
    )
    ended = runtime.ok(
        ConfirmIssueProjectLink(
            issue_id=scene.issue,
            project_id=other,
            expected_membership_revision=2,
            idempotency_key="s31-confirm-plink-other-confirm",
            reason="The end is right.",
        ),
        surface=GATEWAY,
    )["project_link"]
    assert (ended["state"], ended["acceptance_basis"]) == ("ended", "user_confirmed")
    # An event that is already the human channel's is not confirmed again.
    error = runtime.refused(_confirm_link(scene, 2, "plink-again"), surface=GATEWAY)
    assert _state(error) == ("conflict", ["state"])


def test_confirm_is_refused_on_a_closed_issue(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "confirm-closed", operator=True)
    task_a = runtime.task("confirm-closed-a")
    task_b = runtime.task("confirm-closed-b")
    for task_id, key in ((task_a, "a"), (task_b, "b")):
        runtime.member(scene.issue, "task", task_id, f"confirm-closed-{key}", "reference")
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-confirm-closed-link",
        )
    )
    _, _, closure = runtime.evidence_source("confirm-closed")
    version = runtime.issue_version(scene.issue)
    runtime.ok(close(scene.issue, version, "confirm-closed", (closure,)), surface=GATEWAY)
    # A null-context client link inside the closed Issue is admitted (S3 3.2)
    # and lies in its context, so its confirm is refused with the Issue frozen.
    link = runtime.client_ok(
        assertion(
            "blocks",
            ("task", task_a),
            ("task", task_b),
            "confirm-closed",
            (corroborates(scene.meeting, scene.note),),
        )
    )["association"]["link_id"]
    for command in (_confirm(link, 1, "closed"), _confirm_link(scene, 1, "closed")):
        error = runtime.refused(command, surface=GATEWAY)
        assert _state(error) == ("conflict", ["state"]), command.capability.value
    assert [row[1] for row in _revisions(runtime, link)] == ["assert"]


def test_confirm_with_a_stale_expected_revision_is_conflict(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "confirm-stale")
    link = runtime.client_ok(_blocks(runtime, scene, "confirm-stale"))["association"]["link_id"]
    member = runtime.client_ok(membership(scene.issue, "task", scene.member_task, "stale"))[
        "membership"
    ]["link_id"]
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-confirm-stale-link",
        )
    )
    for command in (
        _confirm(link, 2, "stale"),
        _confirm_member(member, 2, "stale"),
        _confirm_link(scene, 2, "stale"),
    ):
        error = runtime.refused(command, surface=GATEWAY)
        assert _state(error) == ("conflict", ["stale_version"]), command.capability.value
    # A link id of the other kind is `invalid_request` / `link_id`.
    error = runtime.refused(_confirm_member(link, 1, "kind"), surface=GATEWAY)
    assert _state(error) == ("invalid_request", ["link_id"])
    error = runtime.refused(_confirm("irl_lineages31absent0001", 1, "absent"), surface=GATEWAY)
    assert _state(error) == ("not_found", ["link_id"])
