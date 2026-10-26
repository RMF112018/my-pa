"""Record lineage S3.1: what the directive did not open stays attested (database).

S3.1 contract sections 1 ("Unchanged and still gated"), 4.9 and 6.2 (worker
N2). Issue close and reopen, the correction of a closed Issue, the backfill
plan and report, and the 3 new confirms are local-operator attested exactly as
S1-S3 state: a remote client and an unstamped local caller are `denied` before
any row and before the replay lookup -- a byte-identical replay of the
operator's committed request is `denied` too, never the stored answer -- and
nothing is written. Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from my_pa.application.commands import (
    AddIssueProjectLink,
    ConfirmIssueMembership,
    ConfirmIssueProjectLink,
    ConfirmRecordAssociation,
    PlanLineageBackfill,
    ReportLineageBackfill,
    UpdateIssue,
)
from my_pa.domain.identity.operation import Capability, is_operator_only
from tests.database.lineage_record_harness import membership
from tests.database.lineage_s2_harness import assertion, close, reopen
from tests.database.lineage_s3_harness import all_s3_counts, corroborates
from tests.database.lineage_s31_harness import (
    GATEWAY,
    S31Runtime,
    client_grants,
    open_scene,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database, lineage_backfill_enabled=True)
    try:
        yield composed
    finally:
        composed.close()


def _callers(runtime: S31Runtime, command: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    """The remote client (every grant it could hold) and the unstamped local caller."""
    return [runtime.client_refused(command), runtime.local_refused(command)]


def _denied(errors: list[dict[str, Any]]) -> bool:
    return all(error["code"] == "denied" and not error.get("safe_details") for error in errors)


def test_close_reopen_and_closed_issue_corrections_stay_operator_attested(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "gates")
    _, _, anchor = runtime.evidence_source("gates-closure")
    closing = close(scene.issue, 1, "gates", (anchor,))
    before = all_s3_counts(runtime.engine)
    assert _denied(_callers(runtime, closing))
    assert all_s3_counts(runtime.engine) == before
    original = runtime.ok(closing, surface=GATEWAY)
    before = all_s3_counts(runtime.engine)
    # The operator's own request, re-sent: `denied` before the replay lookup.
    assert _denied(_callers(runtime, closing))
    correction = UpdateIssue(
        issue_id=scene.issue,
        expected_version=2,
        idempotency_key="s31-gates-correction",
        title="A corrected title",
    )
    assert _denied(_callers(runtime, correction))
    reopening = reopen(scene.issue, 2, "gates")
    assert _denied(_callers(runtime, reopening))
    assert all_s3_counts(runtime.engine) == before
    # The operator replays its close, corrects and reopens as before.
    again = runtime.ok(closing, surface=GATEWAY)
    assert again["replayed"] is True and again["issue"] == original["issue"]
    runtime.ok(correction, surface=GATEWAY)
    corrected_before = all_s3_counts(runtime.engine)
    assert _denied(_callers(runtime, correction))
    assert all_s3_counts(runtime.engine) == corrected_before
    reopened = runtime.ok(reopen(scene.issue, 3, "gates-operator"), surface=GATEWAY)
    assert reopened["issue"]["state"] == "active"
    assert _denied(_callers(runtime, reopen(scene.issue, 3, "gates-operator")))
    for name in ("issues.close", "issues.reopen"):
        assert is_operator_only(Capability(name))


def test_backfill_stays_operator_only_and_attested(runtime: S31Runtime) -> None:
    plan = PlanLineageBackfill(idempotency_key="s31-gates-plan")
    before = all_s3_counts(runtime.engine)
    assert _denied(_callers(runtime, plan))
    assert all_s3_counts(runtime.engine) == before
    enumerated = runtime.ok(plan, surface=GATEWAY)
    report = ReportLineageBackfill(run_id=enumerated["run"]["run_id"])
    before = all_s3_counts(runtime.engine)
    assert _denied(_callers(runtime, plan))
    assert _denied(_callers(runtime, report))
    assert all_s3_counts(runtime.engine) == before
    assert runtime.ok(report, surface=GATEWAY)["run"]["run_id"] == enumerated["run"]["run_id"]
    for name in ("records.backfill.plan", "records.backfill.report"):
        assert is_operator_only(Capability(name))


def test_confirm_capabilities_are_operator_attested_before_the_replay_lookup(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "confirm-gate")
    task_a = runtime.task("confirm-gate-a")
    task_b = runtime.task("confirm-gate-b")
    link = runtime.client_ok(
        assertion(
            "blocks",
            ("task", task_a),
            ("task", task_b),
            "confirm-gate",
            (corroborates(scene.meeting, scene.note),),
            context=scene.issue,
        )
    )["association"]["link_id"]
    member = runtime.client_ok(membership(scene.issue, "task", task_a, "confirm-gate"))[
        "membership"
    ]["link_id"]
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-confirm-gate-link",
        )
    )
    confirms = (
        ConfirmRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key="s31-confirm-gate-assoc",
            reason="Checked against the source.",
        ),
        ConfirmIssueMembership(
            link_id=member,
            expected_revision=1,
            idempotency_key="s31-confirm-gate-member",
            reason="Checked.",
        ),
        ConfirmIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=1,
            idempotency_key="s31-confirm-gate-plink",
            reason="Checked.",
        ),
    )
    before = all_s3_counts(runtime.engine)
    for command in confirms:
        assert is_operator_only(command.capability)
        assert _denied(_callers(runtime, command)), command.capability.value
        # Even granted every capability it names, a remote client is not the human channel.
        assert _denied(
            [
                runtime.client_refused(
                    command,
                    grants=client_grants(command.capability)
                    | client_grants(Capability.ISSUES_READ),
                )
            ]
        )
    assert all_s3_counts(runtime.engine) == before
    originals = [runtime.ok(command, surface=GATEWAY) for command in confirms]
    before = all_s3_counts(runtime.engine)
    for command, original in zip(confirms, originals, strict=True):
        # Byte-identical replays of the operator's confirms: `denied`, never
        # the stored answer.
        errors = _callers(runtime, command)
        assert _denied(errors), command.capability.value
        assert all("result" not in error for error in errors)
        again = runtime.ok(command, surface=GATEWAY)
        assert again["replayed"] is True
        assert {k: v for k, v in again.items() if k != "replayed"} == {
            k: v for k, v in original.items() if k != "replayed"
        }
    assert all_s3_counts(runtime.engine) == before
