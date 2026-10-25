"""Record lineage S3.1: the Issue close gate's review scope (OD-03, database).

S3.1 contract sections 4.6, 4.7 and 7.5 through `ApplicationService.invoke`
against PostgreSQL (worker N2). The S2/S3 gate gains one condition: no link in
the Issue's **review scope** -- every link `in_issue_context`, in any head
state, ended heads included -- has a `client_identified` head revision. So a
client's assert, end, reinstate or evidence correction in scope **holds** the
close instead of opening it; a client's resolution evidence never satisfies a
mandatory member until the human channel confirms it; `issues.closure_readiness`
lists the unreviewed links and is not ready; the human channel clears a hold by
confirming or by writing its own revision; links outside the scope hold
nothing; a close and a client revision in scope serialize; and the client's
`user_directed` claim changes no outcome.

Every fixture of this module writes at least 1 fact with `user_directed:
true` (R31-F06). Every identity and every body here is synthetic.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.commands import (
    AddIssueProjectLink,
    ConfirmIssueMembership,
    ConfirmRecordAssociation,
    EndIssueMembership,
    EndRecordAssociation,
    ReadIssue,
    ReadRelatedRecords,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.intelligence.catalog import IntelligenceStage
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.database.lineage_record_harness import NOTE_BODY, membership, note_anchor
from tests.database.lineage_s2_harness import (
    assertion,
    close,
    correct,
    handoff,
    resolution_anchor,
)
from tests.database.lineage_s3_harness import contest, contradicts, corroborates, reinstate
from tests.database.lineage_s3_read_harness import horizon
from tests.database.lineage_s31_harness import (
    GATEWAY,
    OTHER_CLIENT,
    OpenScene,
    S31ReportRuntime,
    S31Runtime,
    lineage_reference,
    open_scene,
)

pytestmark = pytest.mark.database

BLOCK_DEADLINE_SECONDS: Final = 15.0
JOIN_TIMEOUT_SECONDS: Final = 60.0


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


@pytest.fixture
def report_runtime(disposable_database: str) -> Iterator[S31ReportRuntime]:
    """The same calls over the S4 runtime, which also commits reports (worker N4)."""
    composed = S31ReportRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _claimed(command: Any) -> Any:  # noqa: ANN401
    """The same request with the client's `user_directed` claim."""
    return replace(command, user_directed=True)


def _closure(runtime: S31Runtime, key: str) -> tuple[dict[str, object], ...]:
    _, _, anchor = runtime.evidence_source(f"{key}-closure")
    return (anchor,)


def _try_close(runtime: S31Runtime, issue: str, key: str) -> dict[str, Any] | None:
    """`issues.close` by the operator at the Issue's current version; the error, if any."""
    version = runtime.issue_version(issue)
    envelope = runtime.invoke(close(issue, version, key, _closure(runtime, key)), surface=GATEWAY)
    error = envelope.to_canonical_dict().get("error")
    assert error is None or isinstance(error, dict)
    return error


def _held(error: dict[str, Any] | None) -> bool:
    return error is not None and (error["code"], error["safe_details"]) == (
        "conflict",
        ["closure_gate"],
    )


def _blocks(runtime: S31Runtime, scene: OpenScene, key: str, *, context: bool = True) -> Any:  # noqa: ANN401
    task_a = runtime.task(f"{key}-a")
    task_b = runtime.task(f"{key}-b")
    return assertion(
        "blocks",
        ("task", task_a),
        ("task", task_b),
        key,
        (corroborates(scene.meeting, scene.note),),
        context=scene.issue if context else None,
    )


def _confirm(link: str, revision: int, key: str) -> ConfirmRecordAssociation:
    return ConfirmRecordAssociation(
        link_id=link,
        expected_revision=revision,
        idempotency_key=f"s31-gate-confirm-{key}",
        reason="Checked.",
    )


def _confirm_member(link: str, revision: int, key: str) -> ConfirmIssueMembership:
    return ConfirmIssueMembership(
        link_id=link,
        expected_revision=revision,
        idempotency_key=f"s31-gate-confirm-member-{key}",
        reason="Checked.",
    )


# ---- what holds the close -----------------------------------------------------------


def test_an_unreviewed_membership_holds_the_close(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "gate-member", operator=True)
    member = runtime.client_ok(
        _claimed(membership(scene.issue, "task", scene.member_task, "gate", role="reference"))
    )["membership"]["link_id"]
    assert _held(_try_close(runtime, scene.issue, "gate-member-1"))
    runtime.ok(_confirm_member(member, 1, "gate-member"), surface=GATEWAY)
    assert _try_close(runtime, scene.issue, "gate-member-2") is None


def test_an_unreviewed_semantic_link_in_context_holds_the_close(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "gate-link", operator=True)
    link = runtime.client_ok(_claimed(_blocks(runtime, scene, "gate-link")))["association"]
    assert _held(_try_close(runtime, scene.issue, "gate-link-1"))
    runtime.ok(_confirm(link["link_id"], 1, "gate-link"), surface=GATEWAY)
    assert _try_close(runtime, scene.issue, "gate-link-2") is None


def test_a_client_end_of_a_mandatory_member_holds_the_close_until_confirmed(
    runtime: S31Runtime,
) -> None:
    """Section 4.6: counting only live heads, a client's end would open the gate (D-02)."""
    scene = open_scene(runtime, "gate-end", operator=True)
    open_task = runtime.task("gate-end-open")
    member = runtime.client_ok(membership(scene.issue, "task", open_task, "gate-end", role="work"))[
        "membership"
    ]["link_id"]
    assert _held(_try_close(runtime, scene.issue, "gate-end-1"))
    runtime.client_ok(
        _claimed(
            EndIssueMembership(
                link_id=member,
                expected_revision=1,
                idempotency_key="s31-gate-end-member-end",
                reason="A client ended the open work member.",
            )
        ),
        client=OTHER_CLIENT,
    )
    # The open work member is gone from the live set, yet the close is held.
    assert _held(_try_close(runtime, scene.issue, "gate-end-2"))
    readiness = runtime.readiness(scene.issue)
    assert readiness["ready"] is False and readiness["blockers"] == []
    assert [entry["link_id"] for entry in readiness["unreviewed_links"]] == [member]
    runtime.ok(_confirm_member(member, 2, "gate-end"), surface=GATEWAY)
    assert _try_close(runtime, scene.issue, "gate-end-3") is None


def test_a_client_reinstatement_of_a_contested_link_holds_the_close(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "gate-reinstate", operator=True)
    link = runtime.client_ok(_blocks(runtime, scene, "gate-reinstate"))["association"]["link_id"]
    runtime.client_ok(
        contest(link, 1, "gate-reinstate", (contradicts(scene.meeting, scene.note),)),
        client=OTHER_CLIENT,
    )
    assert _held(_try_close(runtime, scene.issue, "gate-reinstate-1"))
    reinstated = runtime.client_ok(
        _claimed(reinstate(link, 2, "gate-reinstate", (corroborates(scene.meeting, scene.note),)))
    )["association"]
    assert reinstated["lifecycle_state"] == "active"
    # No longer contested, still unreviewed: held.
    assert _held(_try_close(runtime, scene.issue, "gate-reinstate-2"))
    runtime.ok(_confirm(link, 3, "gate-reinstate"), surface=GATEWAY)
    assert _try_close(runtime, scene.issue, "gate-reinstate-3") is None


def _resolved_member_scene(
    runtime: S31Runtime, key: str, *, claimed: bool = True
) -> tuple[OpenScene, str]:
    """A completed, accepted Task whose `work` membership a client wrote with
    exact resolution evidence (claimed user-directed unless `claimed` is false)."""
    scene = open_scene(runtime, key, operator=True)
    task_id = runtime.task(f"{key}-done")
    runtime.transition(task_id, TaskLifecycleState.COMPLETED, key)
    added = membership(
        scene.issue,
        "task",
        task_id,
        key,
        role="work",
        anchors=(resolution_anchor(scene.meeting, scene.note),),
    )
    member = runtime.client_ok(_claimed(added) if claimed else added)["membership"]["link_id"]
    return scene, member


def test_client_resolution_evidence_never_satisfies_the_gate_until_confirmed(
    runtime: S31Runtime,
) -> None:
    scene, member = _resolved_member_scene(runtime, "gate-resolution")
    readiness = runtime.readiness(scene.issue)
    (blocker,) = readiness["blockers"]
    assert blocker["link_id"] == member
    # The client's anchors are not accepted-grade: no resolution evidence.
    assert blocker["reasons"] == ["resolution_evidence_missing"]
    assert _held(_try_close(runtime, scene.issue, "gate-resolution-1"))
    runtime.ok(_confirm_member(member, 1, "gate-resolution"), surface=GATEWAY)
    readiness = runtime.readiness(scene.issue)
    assert readiness["ready"] is True and readiness["blockers"] == []
    assert _try_close(runtime, scene.issue, "gate-resolution-2") is None


def test_readiness_lists_unreviewed_links_and_is_not_ready(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "gate-ready", operator=True)
    link = runtime.client_ok(_claimed(_blocks(runtime, scene, "gate-ready")))["association"]
    member = runtime.local_ok(
        membership(scene.issue, "task", scene.member_task, "gate-ready", role="reference")
    )["membership"]
    readiness = runtime.readiness(scene.issue)
    assert readiness["ready"] is False
    assert readiness["blockers"] == [] and readiness["contested_links"] == []
    assert readiness["unreviewed_links_truncated"] is False
    assert readiness["restricted"] is False
    entries = sorted(readiness["unreviewed_links"], key=lambda entry: entry["link_id"])
    expected = sorted(
        [
            {
                "link_id": link["link_id"],
                "kind": "semantic",
                "relation_type": "blocks",
                "member_role": None,
                "lifecycle_state": "active",
                "revision_no": 1,
                "action": "assert",
                "user_directed_claim": True,
                "recorded_at": link["recorded_at"],
            },
            {
                "link_id": member["link_id"],
                "kind": "issue_membership",
                "relation_type": "issue_member",
                "member_role": "reference",
                "lifecycle_state": "active",
                "revision_no": 1,
                "action": "assert",
                "user_directed_claim": False,
                "recorded_at": member["recorded_at"],
            },
        ],
        key=lambda entry: str(entry["link_id"]),
    )
    assert entries == expected
    assert [entry["link_id"] for entry in readiness["unreviewed_links"]] == sorted(
        entry["link_id"] for entry in expected
    )


def test_confirming_or_an_operator_revision_clears_the_hold(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "gate-clear", operator=True)
    link = runtime.client_ok(_claimed(_blocks(runtime, scene, "gate-clear")))["association"]
    member = runtime.client_ok(
        membership(scene.issue, "task", scene.member_task, "gate-clear", role="reference")
    )["membership"]["link_id"]
    assert _held(_try_close(runtime, scene.issue, "gate-clear-1"))
    # The operator's own revision of the link clears it; a confirm clears the member.
    runtime.ok(
        EndRecordAssociation(
            link_id=link["link_id"],
            expected_revision=1,
            idempotency_key="s31-gate-clear-end",
            reason="Not a real dependency.",
        ),
        surface=GATEWAY,
    )
    assert _held(_try_close(runtime, scene.issue, "gate-clear-2"))
    runtime.ok(_confirm_member(member, 1, "gate-clear"), surface=GATEWAY)
    assert runtime.readiness(scene.issue)["ready"] is True
    assert _try_close(runtime, scene.issue, "gate-clear-3") is None


def test_confirming_a_client_end_clears_the_hold_and_a_new_root_restores_the_relationship(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "gate-new-root", operator=True)
    member = runtime.client_ok(
        membership(scene.issue, "task", scene.member_task, "gate-new-root", role="reference")
    )["membership"]["link_id"]
    runtime.client_ok(
        _claimed(
            EndIssueMembership(
                link_id=member,
                expected_revision=1,
                idempotency_key="s31-gate-new-root-end",
                reason="A client ended it.",
            )
        )
    )
    assert runtime.readiness(scene.issue)["ready"] is False
    runtime.ok(_confirm_member(member, 2, "gate-new-root"), surface=GATEWAY)
    assert runtime.readiness(scene.issue)["ready"] is True
    restored = runtime.ok(
        membership(scene.issue, "task", scene.member_task, "gate-new-root-again", role="reference"),
        surface=GATEWAY,
    )
    assert restored["created"] is True
    association = restored["membership"]
    assert association["link_id"] != member
    assert (association["acceptance_basis"], association["lifecycle_state"]) == (
        "user_confirmed",
        "active",
    )
    assert _try_close(runtime, scene.issue, "gate-new-root") is None


def test_unreviewed_links_outside_the_review_scope_do_not_hold_it(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "gate-outside", operator=True)
    # A null-context link between records outside the Issue, a Project link and
    # a handoff: client facts, none in the review scope.
    runtime.client_ok(_claimed(_blocks(runtime, scene, "gate-outside", context=False)))
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-gate-outside-link",
            user_directed=True,
        )
    )
    runtime.client_ok(
        handoff(
            scene.issue,
            scene.handoff_commitment,
            "counterparty",
            scene.handoff_effective_at,
            "gate-outside",
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff"),
        )
    )
    other = runtime.issue("gate-outside-other")
    runtime.client_ok(membership(other, "task", scene.member_task, "gate-outside-other"))
    readiness = runtime.readiness(scene.issue)
    assert readiness["ready"] is True and readiness["unreviewed_links"] == []
    assert _try_close(runtime, scene.issue, "gate-outside") is None


# ---- serialization (section 4.6) -----------------------------------------------------


def _waiting(engine: Engine) -> int:
    with engine.connect() as observer:
        return int(
            observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
        )


def _race(
    runtime: S31Runtime, issue: str, writers: list[Callable[[], ResponseEnvelope]]
) -> list[ResponseEnvelope]:
    """Hold the Issue `FOR UPDATE`, start each writer, wait until all wait, release."""
    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=len(writers)) as pool:
        held = holder.begin()
        holder.execute(
            text(
                "SELECT situation_id FROM knowledge.situations WHERE situation_id = :id FOR UPDATE"
            ),
            {"id": issue},
        )
        futures: list[Future[ResponseEnvelope]] = []
        for writer in writers:
            futures.append(pool.submit(writer))
            deadline = time.monotonic() + BLOCK_DEADLINE_SECONDS
            while _waiting(runtime.engine) < len(futures):
                assert not any(future.done() for future in futures), "a side did not wait"
                assert time.monotonic() < deadline, "the expected sides never blocked"
                time.sleep(0.02)
        held.rollback()
        return [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]


def _detail(envelope: ResponseEnvelope) -> tuple[str, list[str]] | None:
    error = envelope.to_canonical_dict().get("error")
    assert error is None or isinstance(error, dict)
    return None if error is None else (str(error["code"]), list(error["safe_details"]))


def test_a_close_and_a_client_revision_in_scope_serialize(runtime: S31Runtime) -> None:
    """A client's contest of an accepted link in scope and a close: never both."""
    scene = open_scene(runtime, "gate-race", operator=True)
    link = runtime.ok(_blocks(runtime, scene, "gate-race"), surface=GATEWAY)["association"]
    closure = _closure(runtime, "gate-race")
    closing = close(scene.issue, 1, "gate-race", closure)
    disputing = _claimed(
        contest(link["link_id"], 1, "gate-race", (contradicts(scene.meeting, scene.note),))
    )
    closed, contested = _race(
        runtime,
        scene.issue,
        [
            lambda: runtime.invoke(closing, surface=GATEWAY),
            lambda: runtime.client(disputing),
        ],
    )
    state = runtime.ok(ReadIssue(issue_id=scene.issue))["issue"]["state"]
    if _detail(closed) is None:
        # The close committed first: the Issue is frozen against the contest.
        assert _detail(contested) == ("conflict", ["state"])
        assert state == "closed"
    else:
        # The contest committed first: the close saw it, contested and unreviewed.
        assert _detail(closed) == ("conflict", ["closure_gate"])
        assert _detail(contested) is None
        assert state == "open"


# ---- the claim changes no outcome (R31-F06) --------------------------------------------


def _lineage_verification(runtime: S31ReportRuntime, key: str, issue_id: str) -> dict[str, Any]:
    """S3.1 section 7.9 for the scenario: a report citing a related read of the Issue.

    The manifest's lineage `verification_state` and its server counts, without
    what names this scenario's records (the digest and the cut) and without the
    count of claims, which `claims` reports apart.
    """
    seeds = (("situation", issue_id),)
    answer = runtime.ok(
        ReadRelatedRecords(
            seeds=({"family": "situation", "record_id": issue_id},),
            known_at=horizon(runtime.engine),
        )
    )
    cycle = runtime.cycle(key)
    researcher = runtime.research(cycle, key)
    written = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.SYNTHESIZER,
            f"{key}-synth",
            dependencies=(researcher,),
            structured_content=lineage_reference(answer, seeds),
        )
    )
    stored = runtime.stored_manifest(written["report_id"])
    assert stored is not None
    section = json.loads(stored["manifest_canonical"])["lineage"]
    server = section["server"]
    return {
        "verification_state": section["verification_state"],
        "recompute_failure": section["recompute_failure"],
        "server": {
            name: value
            for name, value in server.items()
            if name not in ("related_sha256", "known_at", "user_directed_claims")
        },
        "user_directed_claims": server["user_directed_claims"],
    }


def _outcome(runtime: S31ReportRuntime, *, claimed: bool) -> dict[str, Any]:
    """One scenario with every client write claimed or not; everything a gate decides."""
    key = f"gate-claim-{claimed}"
    scene, member = _resolved_member_scene(runtime, key, claimed=claimed)
    sent = _claimed if claimed else (lambda command: command)
    link = runtime.client_ok(sent(_blocks(runtime, scene, f"{key}-link")))["association"]
    runtime.client_ok(
        sent(
            correct(
                member,
                1,
                f"{key}-member",
                (
                    resolution_anchor(scene.meeting, scene.note),
                    resolution_anchor(
                        scene.meeting, scene.note, role="corroborates", passage="pour"
                    ),
                ),
            )
        )
    )
    readiness = runtime.readiness(scene.issue)
    error = _try_close(runtime, scene.issue, key)
    verification = _lineage_verification(runtime, key, scene.issue)
    # Worker N4: an Issue whose only hold is the client's unreviewed link, so a
    # gate that skipped a claimed link would close it.
    alone = open_scene(runtime, f"{key}-alone", operator=True)
    runtime.client_ok(sent(_blocks(runtime, alone, f"{key}-alone-link")))
    alone_error = _try_close(runtime, alone.issue, f"{key}-alone")
    with runtime.engine.connect() as connection:
        consumed = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.lineage_write_requests"
                " WHERE decision_channel = 'remote_interactive' AND completed_at IS NOT NULL"
            )
        ).scalar_one()
    return {
        "ready": readiness["ready"],
        "blockers": [
            {k: v for k, v in blocker.items() if k not in ("link_id", "member")}
            for blocker in readiness["blockers"]
        ],
        "unreviewed": sorted(
            (
                {k: v for k, v in entry.items() if k not in ("link_id", "recorded_at")}
                | {"user_directed_claim": None}
                for entry in readiness["unreviewed_links"]
            ),
            key=lambda entry: str(entry["kind"]),
        ),
        "claims": {entry["user_directed_claim"] for entry in readiness["unreviewed_links"]},
        "close": None if error is None else (error["code"], error["safe_details"]),
        "close_held_only_by_review": None
        if alone_error is None
        else (alone_error["code"], alone_error["safe_details"]),
        "consumed": int(consumed),
        "link_state": link["lifecycle_state"],
        "verification": verification,
    }


def test_the_user_directed_claim_changes_no_outcome(report_runtime: S31ReportRuntime) -> None:
    """R31-F06: the same scenario with the claim false and true decides identically.

    `ready`, the blockers, the unreviewed links (but for the displayed claim),
    the close's answer, the budget a client consumed and -- worker N4, S3.1
    section 7.9 -- the lineage `verification_state` and server counts of a
    report citing a related read of the Issue (the manifest counts the claims,
    and nothing else differs). Program reportability under the claim is pinned
    with the S4 rows (`test_an_unreviewed_issue_link_makes_the_issue_metric_not_reportable`
    writes its link claimed).
    """
    runtime = report_runtime
    without = _outcome(runtime, claimed=False)
    consumed = without.pop("consumed")
    with_claim = _outcome(runtime, claimed=True)
    assert with_claim.pop("consumed") - consumed == consumed
    assert without.pop("claims") == {False}
    assert with_claim.pop("claims") == {True}
    assert without["verification"].pop("user_directed_claims") == 0
    assert with_claim["verification"].pop("user_directed_claims") > 0
    assert without["verification"]["verification_state"] == "verified_at_commit"
    assert with_claim == without
    assert without["close"] == ("conflict", ["closure_gate"])
    assert without["close_held_only_by_review"] == ("conflict", ["closure_gate"])
