"""AT-023 (S2, database): attested S2 writes, the switch and foreign subjects.

S2 contract sections 3.2, 6.1 and 7.5 against PostgreSQL, through
`ApplicationService.invoke`, for the S2 Issue writes and read this slice
implements -- `issues.close`, `issues.reopen`, `issues.memberships.correct`
and `issues.closure_readiness` (the handoff and composite rows are the
composite worker's, S2 contract section 9, K2):

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
from typing import Any

import pytest

from my_pa.application.commands import ReadIssueClosureReadiness
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, REMOTE_CLIENT
from tests.database.lineage_s2_harness import (
    GATEWAY,
    S2Runtime,
    all_s2_counts,
    close,
    correct,
    reopen,
)

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


def _scene(runtime: S2Runtime, key: str) -> dict[str, Any]:
    """An Issue with a completed Task member and a closure set, ready to write."""
    issue = runtime.issue(key)
    task_id = runtime.task(key)
    link = runtime.member(issue, "task", task_id, key, "work")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, key)
    _, _, member_anchor = runtime.evidence_source(f"{key}-member")
    _, _, closure_anchor = runtime.evidence_source(f"{key}-closure")
    return {
        "issue": issue,
        "link": link,
        "correct": correct(link, 1, key, (member_anchor,)),
        "close": close(issue, 1, key, (closure_anchor,)),
        "reopen": reopen(issue, 2, key),
    }


def test_an_ordinary_remote_client_is_denied_every_s2_write(runtime: S2Runtime) -> None:
    scene = _scene(runtime, "deny")
    before = all_s2_counts(runtime.engine)
    for command in (scene["correct"], scene["close"]):
        assert _code(runtime, command, remote_client=REMOTE_CLIENT)[0] == "denied"
        assert _code(runtime, command)[0] == "denied"
    assert all_s2_counts(runtime.engine) == before
    runtime.ok(scene["correct"], surface=GATEWAY)
    runtime.ok(scene["close"], surface=GATEWAY)
    before = all_s2_counts(runtime.engine)
    assert _code(runtime, scene["reopen"], remote_client=REMOTE_CLIENT)[0] == "denied"
    assert _code(runtime, scene["reopen"])[0] == "denied"
    assert all_s2_counts(runtime.engine) == before
    # The read is not attested: a recorded caller may evaluate the gate.
    assert runtime.ok(ReadIssueClosureReadiness(issue_id=scene["issue"]))["state"] == "closed"


def test_a_replayed_s2_write_from_an_ordinary_client_is_denied_before_the_replay_lookup(
    runtime: S2Runtime,
) -> None:
    scene = _scene(runtime, "replay")
    for name in ("correct", "close", "reopen"):
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
    finally:
        on.close()
    off = S2Runtime(disposable_database, lineage_enabled=False)
    try:
        before = all_s2_counts(off.engine)
        for command in (
            scene["correct"],  # a replay of a write committed while the switch was on
            scene["close"],
            scene["reopen"],
            ReadIssueClosureReadiness(issue_id=scene["issue"]),
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
