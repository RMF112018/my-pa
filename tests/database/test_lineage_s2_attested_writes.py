"""AT-023 (S2, database): attested S2 writes, the switch and foreign subjects.

S2 contract sections 3.2, 6.1 and 7.5 against PostgreSQL, through
`ApplicationService.invoke`, for every S2 capability -- `issues.close`,
`issues.reopen`, `issues.memberships.correct`, `issues.closure_readiness`,
`issues.handoffs.record`, `issues.handoffs.list`, `issues.work.create_task`
and `issues.work.create_commitment`:

* an ordinary remote client (and an unstamped local caller) is `denied` every
  S2 write before any row is written;
* a byte-identical replay of an operator's committed S2 write by such a caller
  is `denied` before the replay lookup -- it never sees the stored answer;
* with `lineage_enabled` off each answers `unsupported`, including a replay of
  a write committed while it was on;
* a foreign Issue or membership answers exactly like an absent one.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.application.commands import ListIssueHandoffs, ReadIssueClosureReadiness
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL, REMOTE_CLIENT
from tests.database.lineage_record_harness import capture
from tests.database.lineage_s2_harness import (
    GATEWAY,
    REVIEW_DECISION,
    S2Runtime,
    all_s2_counts,
    close,
    correct,
    handoff,
    reopen,
    work_commitment,
    work_task,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _code(runtime: S2Runtime, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


def _commitment_object(runtime: S2Runtime, key: str) -> dict[str, object]:
    origin, _, _ = capture(runtime, f"{key}-native-origin")
    return {
        "counterparty_entity_id": seed_counterparty_entity(runtime.engine, PRINCIPAL),
        "direction": "owed_to_principal",
        "summary": f"Synthetic composite commitment {key}",
        "origin_evidence_ref": origin,
        "accepted_by_review_decision_id": REVIEW_DECISION,
    }


def _scene(runtime: S2Runtime, key: str) -> dict[str, Any]:
    """An Issue with a completed Task member, a Commitment member and a closure set.

    The handoff is written before the close: a closed Issue refuses it
    (`conflict` / `state`).
    """
    issue = runtime.issue(key)
    work_issue = runtime.issue(f"{key}-work")
    task_id = runtime.task(key)
    link = runtime.member(issue, "task", task_id, key, "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, key)
    commitment = runtime.commitment(key, accepted=False)
    runtime.member(issue, "commitment", commitment, f"{key}-c", "discussion")
    created = datetime.fromisoformat(str(runtime.commitment_view(commitment)["created_at"]))
    effective = (created + timedelta(milliseconds=1)).isoformat()
    _, _, member_anchor = runtime.evidence_source(f"{key}-member")
    _, _, closure_anchor = runtime.evidence_source(f"{key}-closure")
    return {
        "issue": issue,
        "link": link,
        "commitment": commitment,
        "correct": correct(link, 1, key, (member_anchor,)),
        "handoff": handoff(
            issue,
            commitment,
            "counterparty",
            effective,
            key,
            runtime.handoff_anchor(f"{key}-handoff"),
        ),
        # On their own Issue: a composite's `work` member is mandatory, and
        # an open one would hold the scene's Issue below its gate.
        "work_issue": work_issue,
        "work_task": work_task(work_issue, key),
        "work_commitment": work_commitment(work_issue, key, _commitment_object(runtime, key)),
        "close": close(issue, 1, key, (closure_anchor,)),
        "reopen": reopen(issue, 2, key),
    }


#: The S2 writes in the order a scene admits them (the close freezes the Issue).
_WRITES: Final = ("correct", "handoff", "work_task", "work_commitment", "close", "reopen")


def test_an_ordinary_remote_client_is_denied_every_s2_write(runtime: S2Runtime) -> None:
    scene = _scene(runtime, "deny")
    before = all_s2_counts(runtime.engine)
    for command in (scene[name] for name in _WRITES[:-1]):
        assert _code(runtime, command, remote_client=REMOTE_CLIENT)[0] == "denied"
        assert _code(runtime, command)[0] == "denied"
    assert all_s2_counts(runtime.engine) == before
    runtime.ok(scene["correct"], surface=GATEWAY)
    runtime.ok(scene["close"], surface=GATEWAY)
    before = all_s2_counts(runtime.engine)
    assert _code(runtime, scene["reopen"], remote_client=REMOTE_CLIENT)[0] == "denied"
    assert _code(runtime, scene["reopen"])[0] == "denied"
    assert all_s2_counts(runtime.engine) == before
    # The reads are not attested: a recorded caller may evaluate the gate and list.
    assert runtime.ok(ReadIssueClosureReadiness(issue_id=scene["issue"]))["state"] == "closed"
    assert runtime.ok(ListIssueHandoffs(issue_id=scene["issue"]))["handoffs"] == []


def test_a_replayed_s2_write_from_an_ordinary_client_is_denied_before_the_replay_lookup(
    runtime: S2Runtime,
) -> None:
    scene = _scene(runtime, "replay")
    for name in _WRITES:
        command = scene[name]
        original = runtime.ok(command, surface=GATEWAY)
        assert original["replayed"] is False
        # Exactly the operator's request, by a caller who may not make it.
        assert _code(runtime, command, remote_client=REMOTE_CLIENT)[0] == "denied", name
        assert _code(runtime, command)[0] == "denied", name
        replayed = runtime.ok(command, surface=GATEWAY)
        assert replayed["replayed"] is True
        assert {k: v for k, v in replayed.items() if k != "replayed"} == {
            k: v for k, v in original.items() if k != "replayed"
        }, name


def test_switch_off_answers_unsupported_for_every_s2_capability(disposable_database: str) -> None:
    on = S2Runtime(disposable_database)
    try:
        scene = _scene(on, "switch")
        on.ok(scene["correct"], surface=GATEWAY)
        on.ok(scene["handoff"], surface=GATEWAY)
        on.ok(scene["work_task"], surface=GATEWAY)
    finally:
        on.close()
    off = S2Runtime(disposable_database, lineage_enabled=False)
    try:
        before = all_s2_counts(off.engine)
        for command in (
            # Replays of writes committed while the switch was on.
            scene["correct"],
            scene["handoff"],
            scene["work_task"],
            scene["work_commitment"],
            scene["close"],
            scene["reopen"],
            ReadIssueClosureReadiness(issue_id=scene["issue"]),
            ListIssueHandoffs(issue_id=scene["issue"]),
        ):
            assert _code(off, command, surface=GATEWAY)[0] == "unsupported", command.capability
        assert all_s2_counts(off.engine) == before
    finally:
        off.close()


def test_every_s2_capability_answers_a_foreign_subject_like_an_absent_one(
    runtime: S2Runtime,
) -> None:
    foreign = _scene(runtime, "foreign")
    absent_issue = "sit_lineages2absent0001"
    absent_link = "irl_lineages2absent0001"
    for subject, link in ((foreign["issue"], foreign["link"]), (absent_issue, absent_link)):
        closure = foreign["close"].closure_evidence_anchors
        assert _code(
            runtime,
            close(subject, 1, f"foreign-{subject}", closure),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["issue_id"])
        assert _code(
            runtime,
            reopen(subject, 2, f"foreign-{subject}"),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["issue_id"])
        assert _code(
            runtime,
            ReadIssueClosureReadiness(issue_id=subject),
            principal_id=OTHER_PRINCIPAL,
        ) == ("not_found", ["issue_id"])
        assert _code(
            runtime,
            correct(link, 1, f"foreign-{link}", ()),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["link_id"])
        for commitment in (foreign["commitment"], "cmt_lineages2absent0001"):
            assert _code(
                runtime,
                handoff(
                    subject,
                    commitment,
                    "counterparty",
                    foreign["handoff"].effective_at,
                    f"foreign-handoff-{subject}-{commitment}",
                    foreign["handoff"].evidence_anchor,
                ),
                principal_id=OTHER_PRINCIPAL,
                surface=GATEWAY,
            ) == ("not_found", ["commitment_id"])
        assert _code(
            runtime, ListIssueHandoffs(issue_id=subject), principal_id=OTHER_PRINCIPAL
        ) == ("not_found", ["issue_id"])
        for command in (
            work_task(subject, f"foreign-task-{subject}"),
            work_commitment(
                subject, f"foreign-commitment-{subject}", foreign["work_commitment"].commitment
            ),
        ):
            assert _code(runtime, command, principal_id=OTHER_PRINCIPAL, surface=GATEWAY) == (
                "not_found",
                ["issue_id"],
            )
    # Within the caller's own Issue, a foreign Commitment is an absent one.
    own = runtime.issue("foreign-own", principal_id=OTHER_PRINCIPAL)
    for commitment in (foreign["commitment"], "cmt_lineages2absent0001"):
        assert _code(
            runtime,
            ListIssueHandoffs(issue_id=own, commitment_id=commitment),
            principal_id=OTHER_PRINCIPAL,
        ) == ("not_found", ["commitment_id"])
