"""Record lineage S3.1: remote write visibility and grants (R31-F01, RR1-F02; database).

S3.1 contract section 6.4 through `ApplicationService.invoke` against
PostgreSQL (worker N2). S3 section 6.4 is the intra-Principal disclosure
control for remote callers; before S3.1 it applied only to reads. For every
open write and every remote caller:

* a remote write without a grant on its own capability is `unsupported`, and a
  composite without the native create grant is `denied`;
* every subject in a family the caller cannot see answers exactly as an absent
  one -- an endpoint, an Issue, an anchor's source, a handoff's Commitment, a
  Project, the root a `link_id` addresses -- before any row, the replay lookup
  and the rate count, so even at the budget bound a hidden and an absent
  subject answer alike;
* a semantic-link or membership write without Issue visibility answers as
  absent whatever the Issue's state (the frozen-closed refusal never
  discloses a hidden Issue);
* a write answer withholds an anchor of an invisible family and says
  `restricted`.

The truncation-visibility row of this module (R31-F10,
`test_related_and_readiness_truncation_count_only_visible_items`) is worker
N3's, with the related read. Every identity and every body here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import text
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    all_lineage_counts,
    capture,
    capture_anchor,
    membership,
    note_anchor,
    originated_from,
)
from tests.database.lineage_s2_harness import (
    assertion,
    close,
    correct,
    handoff,
    resolution_anchor,
    work_commitment,
    work_task,
)
from tests.database.lineage_s3_harness import (
    contest,
    contradicts,
    correct_handoff,
    corroborates,
    reinstate,
)
from tests.database.lineage_s31_harness import (
    GATEWAY,
    OpenScene,
    S31Runtime,
    client_grants,
    open_scene,
)

from my_pa.application.commands import (
    AddIssueProjectLink,
    CorrectRecordAssociation,
    CreateIssue,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.lineage.vocabulary import (
    CLIENT_LINEAGE_WRITES_PER_HOUR,
    OPEN_LINEAGE_WRITE_CAPABILITIES,
)
from my_pa.domain.source.registry import issue_identifier

pytestmark = pytest.mark.database

#: Well-formed identifiers no row carries (absent subjects).
_ABSENT_LINK: Final = issue_identifier(IdKind.RECORD_LINK)
_ABSENT_TASK: Final = issue_identifier(IdKind.TASK)
_ABSENT_COMMITMENT: Final = issue_identifier(IdKind.COMMITMENT)
_ABSENT_PROJECT: Final = issue_identifier(IdKind.PROJECT)
_ABSENT_ISSUE: Final = issue_identifier(IdKind.SITUATION)
_ABSENT_HANDOFF: Final = issue_identifier(IdKind.ISSUE_HANDOFF)
_ABSENT_CAPTURE: Final = issue_identifier(IdKind.CAPTURE)
_ABSENT_CAPTURE_VERSION: Final = issue_identifier(IdKind.CAPTURE_VERSION)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _answer(error: dict[str, Any]) -> tuple[str, list[str]]:
    return str(error["code"]), list(error.get("safe_details") or [])


def _completed_client_requests(runtime: S31Runtime) -> int:
    with runtime.engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.lineage_write_requests"
                    " WHERE decision_channel = 'remote_interactive' AND completed_at IS NOT NULL"
                )
            ).scalar_one()
        )


def _client_link(runtime: S31Runtime, scene: OpenScene, key: str) -> str:
    task_a = runtime.task(f"{key}-a")
    task_b = runtime.task(f"{key}-b")
    return str(
        runtime.client_ok(
            assertion(
                "blocks",
                ("task", task_a),
                ("task", task_b),
                key,
                (corroborates(scene.meeting, scene.note),),
                context=scene.issue,
            )
        )["association"]["link_id"]
    )


def _hidden_and_absent(
    runtime: S31Runtime, scene: OpenScene
) -> list[tuple[Any, tuple[str, ...], Any, tuple[str, list[str]]]]:
    """Per open write: `(hidden request, family reads withheld, absent request, answer)`."""
    key = scene.key
    origin = note_anchor(scene.meeting, scene.note, NOTE_BODY)
    link = _client_link(runtime, scene, f"{key}-link")
    member = runtime.client_ok(membership(scene.issue, "task", scene.member_task, f"{key}-member"))[
        "membership"
    ]["link_id"]
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key=f"s31-hidden-{key}-plink",
        )
    )
    event = runtime.client_ok(
        handoff(
            scene.issue,
            scene.handoff_commitment,
            "counterparty",
            scene.handoff_effective_at,
            f"{key}-handoff",
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff"),
        )
    )["handoff"]["handoff_id"]
    no_tasks = ("tasks.read",)

    def revise(link_id: str, which: str) -> Any:  # noqa: ANN401
        if which == "correct":
            return CorrectRecordAssociation(
                link_id=link_id,
                expected_revision=1,
                idempotency_key=f"s31-hidden-{key}-{which}",
                reason="Synthetic.",
                evidence_anchors=(corroborates(scene.meeting, scene.note), origin),
            )
        if which == "end":
            return EndRecordAssociation(
                link_id=link_id,
                expected_revision=1,
                idempotency_key=f"s31-hidden-{key}-{which}",
                reason="Synthetic.",
            )
        if which == "contest":
            return contest(link_id, 1, f"hidden-{key}", (contradicts(scene.meeting, scene.note),))
        return reinstate(link_id, 1, f"hidden-{key}", (corroborates(scene.meeting, scene.note),))

    def end_member(link_id: str) -> EndIssueMembership:
        return EndIssueMembership(
            link_id=link_id,
            expected_revision=1,
            idempotency_key=f"s31-hidden-{key}-member-end",
            reason="Synthetic.",
        )

    def plink(project_id: str, *, end: bool) -> Any:  # noqa: ANN401
        if end:
            return EndIssueProjectLink(
                issue_id=scene.issue,
                project_id=project_id,
                expected_membership_revision=1,
                idempotency_key=f"s31-hidden-{key}-plink-end",
                reason="Synthetic.",
            )
        return AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=project_id,
            expected_membership_revision=0,
            idempotency_key=f"s31-hidden-{key}-plink-add",
        )

    def assert_from(commitment_id: str) -> Any:  # noqa: ANN401
        return originated_from(
            "commitment",
            commitment_id,
            "meeting_note_version",
            scene.note,
            f"hidden-{key}",
            (origin,),
        )

    def record_handoff(commitment_id: str) -> Any:  # noqa: ANN401
        return handoff(
            scene.issue,
            commitment_id,
            "counterparty",
            scene.handoff_effective_at,
            f"hidden-{key}-second",
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff"),
        )

    def correct_event(handoff_id: str) -> Any:  # noqa: ANN401
        return correct_handoff(
            handoff_id, "void", f"hidden-{key}", contradicts(scene.meeting, scene.note)
        )

    return [
        (
            assert_from(scene.origin_commitment),
            ("commitments.read",),
            assert_from(_ABSENT_COMMITMENT),
            ("not_found", ["from"]),
        ),
        *(
            (revise(link, which), no_tasks, revise(_ABSENT_LINK, which), ("not_found", ["link_id"]))
            for which in ("correct", "end", "contest", "reinstate")
        ),
        (
            membership(scene.issue, "task", runtime.task(f"{key}-new"), f"hidden-{key}"),
            no_tasks,
            membership(scene.issue, "task", _ABSENT_TASK, f"hidden-{key}"),
            ("not_found", ["member"]),
        ),
        (end_member(member), no_tasks, end_member(_ABSENT_LINK), ("not_found", ["link_id"])),
        (
            correct(member, 1, f"hidden-{key}", (resolution_anchor(scene.meeting, scene.note),)),
            no_tasks,
            correct(
                _ABSENT_LINK, 1, f"hidden-{key}", (resolution_anchor(scene.meeting, scene.note),)
            ),
            ("not_found", ["link_id"]),
        ),
        (
            plink(runtime.project(f"{key}-other"), end=False),
            ("continuity.projects",),
            plink(_ABSENT_PROJECT, end=False),
            ("not_found", ["project_id"]),
        ),
        (
            plink(scene.project, end=True),
            ("continuity.projects",),
            plink(_ABSENT_PROJECT, end=True),
            ("not_found", ["project_id"]),
        ),
        (
            record_handoff(scene.handoff_commitment),
            ("commitments.read",),
            record_handoff(_ABSENT_COMMITMENT),
            ("not_found", ["commitment_id"]),
        ),
        (
            correct_event(event),
            ("commitments.read",),
            correct_event(_ABSENT_HANDOFF),
            ("not_found", ["handoff_id"]),
        ),
        (
            work_task(scene.issue, f"hidden-{key}"),
            ("issues.read",),
            work_task(_ABSENT_ISSUE, f"hidden-{key}"),
            ("not_found", ["issue_id"]),
        ),
        (
            work_commitment(scene.issue, f"hidden-{key}", scene.native_commitment),
            ("issues.read",),
            work_commitment(_ABSENT_ISSUE, f"hidden-{key}", scene.native_commitment),
            ("not_found", ["issue_id"]),
        ),
    ]


def test_an_absent_and_a_hidden_endpoint_answer_alike(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "alike")
    cases = _hidden_and_absent(runtime, scene)
    assert {hidden.capability.value for hidden, *_ in cases} == set(OPEN_LINEAGE_WRITE_CAPABILITIES)
    before = all_lineage_counts(runtime.engine)
    consumed = _completed_client_requests(runtime)
    for hidden, withheld, absent, expected in cases:
        name = hidden.capability.value
        hidden_answer = _answer(
            runtime.client_refused(
                hidden, grants=client_grants(hidden.capability, without=withheld)
            )
        )
        absent_answer = _answer(runtime.client_refused(absent))
        assert hidden_answer == absent_answer == expected, name
    assert all_lineage_counts(runtime.engine) == before
    assert _completed_client_requests(runtime) == consumed


def test_a_hidden_link_revision_answers_not_found(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "hidden-link")
    link = _client_link(runtime, scene, "hidden-link")
    before = all_lineage_counts(runtime.engine)
    commands = (
        EndRecordAssociation(
            link_id=link, expected_revision=1, idempotency_key="s31-hl-end", reason="Synthetic."
        ),
        CorrectRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key="s31-hl-correct",
            reason="Synthetic.",
            evidence_anchors=(
                corroborates(scene.meeting, scene.note),
                note_anchor(
                    scene.meeting, scene.note, NOTE_BODY, role="corroborates", passage="pour"
                ),
            ),
        ),
        contest(link, 1, "hl", (contradicts(scene.meeting, scene.note),)),
        reinstate(link, 1, "hl", (corroborates(scene.meeting, scene.note),)),
    )
    for command in commands:
        # An invisible endpoint, or the invisible context Issue.
        for withheld in (("tasks.read",), ("issues.read",)):
            error = runtime.client_refused(
                command, grants=client_grants(command.capability, without=withheld)
            )
            assert _answer(error) == ("not_found", ["link_id"]), (command.capability, withheld)
    assert all_lineage_counts(runtime.engine) == before


def test_a_hidden_anchor_source_answers_not_found(runtime: S31Runtime) -> None:
    capture_id, version_id, _ = capture(runtime, "hidden-anchor")
    task_a = runtime.task("hidden-anchor-a")
    task_b = runtime.task("hidden-anchor-b")

    def blocks(anchor: dict[str, object]) -> Any:  # noqa: ANN401
        return assertion("blocks", ("task", task_a), ("task", task_b), "hidden-anchor", (anchor,))

    hidden = blocks(capture_anchor(capture_id, version_id, NOTE_BODY, role="corroborates"))
    absent = blocks(
        capture_anchor(_ABSENT_CAPTURE, _ABSENT_CAPTURE_VERSION, NOTE_BODY, role="corroborates")
    )
    before = all_lineage_counts(runtime.engine)
    hidden_answer = runtime.client_refused(
        hidden, grants=client_grants(hidden.capability, without=("capture.read",))
    )
    absent_answer = runtime.client_refused(absent)
    assert _answer(hidden_answer) == _answer(absent_answer) == ("not_found", ["evidence_anchors"])
    assert all_lineage_counts(runtime.engine) == before
    # Granted the Capture read, the same request is admitted.
    assert runtime.client_ok(hidden)["created"] is True


def test_a_hidden_handoff_commitment_answers_not_found(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "hidden-handoff")
    anchor = note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff")
    record = handoff(
        scene.issue,
        scene.handoff_commitment,
        "counterparty",
        scene.handoff_effective_at,
        "hidden-handoff",
        anchor,
    )
    no_commitments = client_grants(record.capability, without=("commitments.read",))
    assert _answer(runtime.client_refused(record, grants=no_commitments)) == (
        "not_found",
        ["commitment_id"],
    )
    event = runtime.client_ok(record)["handoff"]["handoff_id"]
    void = correct_handoff(event, "void", "hidden-handoff", contradicts(scene.meeting, scene.note))
    before = all_lineage_counts(runtime.engine)
    for withheld in (("commitments.read",), ("issues.read",)):
        error = runtime.client_refused(
            void, grants=client_grants(void.capability, without=withheld)
        )
        assert _answer(error) == ("not_found", ["handoff_id"]), withheld
    assert all_lineage_counts(runtime.engine) == before


def test_a_hidden_project_answers_not_found_for_project_link_writes(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "hidden-project")
    add = AddIssueProjectLink(
        issue_id=scene.issue,
        project_id=scene.project,
        expected_membership_revision=0,
        idempotency_key="s31-hidden-project-add",
    )
    end = EndIssueProjectLink(
        issue_id=scene.issue,
        project_id=scene.project,
        expected_membership_revision=1,
        idempotency_key="s31-hidden-project-end",
        reason="Synthetic.",
    )
    for command in (add, end):
        error = runtime.client_refused(
            command, grants=client_grants(command.capability, without=("continuity.projects",))
        )
        assert _answer(error) == ("not_found", ["project_id"]), command.capability.value
        if command is add:
            runtime.client_ok(add)


def test_a_write_answer_withholds_a_hidden_anchor_and_says_restricted(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "answer-filter")
    capture_id, version_id, _ = capture(runtime, "answer-filter")
    task_a = runtime.task("answer-filter-a")
    task_b = runtime.task("answer-filter-b")
    note = corroborates(scene.meeting, scene.note)
    # The operator's link cites a Capture version and a note.
    operator = runtime.ok(
        assertion(
            "blocks",
            ("task", task_a),
            ("task", task_b),
            "answer-filter-operator",
            (capture_anchor(capture_id, version_id, NOTE_BODY, role="corroborates"), note),
        ),
        surface=GATEWAY,
    )["association"]
    again = assertion("blocks", ("task", task_a), ("task", task_b), "answer-filter", (note,))
    # A client that may not read Captures asserts the same identity: the
    # existing link answers, its Capture anchor withheld, and says so.
    filtered = runtime.client_ok(
        again, grants=client_grants(again.capability, without=("capture.read",))
    )
    assert filtered["created"] is False and filtered["restricted"] is True
    assert [anchor["family"] for anchor in filtered["association"]["evidence"]] == [
        "meeting_note_version"
    ]
    # Its replay applies the same filter.
    replayed = runtime.client_ok(
        again, grants=client_grants(again.capability, without=("capture.read",))
    )
    assert replayed["replayed"] is True and replayed["restricted"] is True
    # A client that reads Captures sees it whole; so does a local caller.
    whole = runtime.client_ok(
        assertion("blocks", ("task", task_a), ("task", task_b), "answer-filter-whole", (note,))
    )
    assert whole["restricted"] is False
    assert whole["association"]["evidence"] == operator["evidence"]


def test_a_composite_without_the_native_create_grant_is_denied(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "native-grant")
    before = all_lineage_counts(runtime.engine)
    for command, native in (
        (work_task(scene.issue, "native-grant"), "tasks.create"),
        (
            work_commitment(scene.issue, "native-grant", scene.native_commitment),
            "commitments.create",
        ),
    ):
        error = runtime.client_refused(
            command, grants=client_grants(command.capability, without=(native,))
        )
        assert _answer(error) == ("denied", []), command.capability.value
    assert all_lineage_counts(runtime.engine) == before
    with runtime.engine.connect() as connection:
        tasks = connection.execute(
            text("SELECT count(*) FROM knowledge.tasks WHERE title = 'Synthetic task native-grant'")
        ).scalar_one()
    assert tasks == 0


def test_a_remote_write_without_its_own_grant_is_unsupported(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "own-grant")
    cases = _hidden_and_absent(runtime, scene)
    before = all_lineage_counts(runtime.engine)
    for hidden, _withheld, _absent, _expected in cases:
        name = hidden.capability.value
        error = runtime.client_refused(
            hidden, grants=client_grants(hidden.capability, without=(name,))
        )
        assert _answer(error) == ("unsupported", []), name
    assert all_lineage_counts(runtime.engine) == before


def test_hidden_and_absent_answer_alike_at_the_budget_bound(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "bound")
    for index in range(CLIENT_LINEAGE_WRITES_PER_HOUR - _completed_client_requests(runtime)):
        runtime.client_ok(
            CreateIssue(title=f"Budget {index}", idempotency_key=f"s31-bound-{index}")
        )
    assert _completed_client_requests(runtime) == CLIENT_LINEAGE_WRITES_PER_HOUR
    hidden = membership(scene.issue, "task", scene.member_task, "bound")
    absent = membership(scene.issue, "task", _ABSENT_TASK, "bound")
    hidden_answer = runtime.client_refused(
        hidden, grants=client_grants(hidden.capability, without=("tasks.read",))
    )
    absent_answer = runtime.client_refused(absent)
    assert _answer(hidden_answer) == _answer(absent_answer) == ("not_found", ["member"])
    # A write that passes every check is refused by the bound.
    assert _answer(runtime.client_refused(hidden)) == ("rate_limited", ["lineage_write_budget"])
    assert _completed_client_requests(runtime) == CLIENT_LINEAGE_WRITES_PER_HOUR


def test_a_link_or_membership_write_without_issue_visibility_answers_as_absent(
    runtime: S31Runtime,
) -> None:
    """RR1-F02: no frozen-closed or Issue-context refusal discloses a hidden Issue."""
    open_issue = open_scene(runtime, "issue-hidden-open", operator=True)
    closed_issue = open_scene(runtime, "issue-hidden-closed", operator=True)
    _, _, anchor = runtime.evidence_source("issue-hidden-closure")
    runtime.ok(close(closed_issue.issue, 1, "issue-hidden", (anchor,)), surface=GATEWAY)
    task_a = runtime.task("issue-hidden-a")
    task_b = runtime.task("issue-hidden-b")
    no_issues = ("issues.read",)
    before = all_lineage_counts(runtime.engine)
    answers: set[tuple[str, tuple[str, ...]]] = set()
    for scene in (open_issue, closed_issue):
        for command in (
            assertion(
                "blocks",
                ("task", task_a),
                ("task", task_b),
                f"issue-hidden-{scene.key}",
                (corroborates(scene.meeting, scene.note),),
                context=scene.issue,
            ),
            assertion(
                "blocks",
                ("task", _ABSENT_TASK),
                ("task", task_b),
                f"issue-hidden-absent-{scene.key}",
                (corroborates(scene.meeting, scene.note),),
                context=scene.issue,
            ),
        ):
            code, details = _answer(
                runtime.client_refused(
                    command, grants=client_grants(command.capability, without=no_issues)
                )
            )
            answers.add((code, tuple(details)))
        member = membership(scene.issue, "task", task_a, f"issue-hidden-{scene.key}")
        assert _answer(
            runtime.client_refused(
                member, grants=client_grants(member.capability, without=no_issues)
            )
        ) == ("not_found", ["issue_id"])
        composite = work_task(scene.issue, f"issue-hidden-{scene.key}")
        assert _answer(
            runtime.client_refused(
                composite, grants=client_grants(composite.capability, without=no_issues)
            )
        ) == ("not_found", ["issue_id"])
    # Open, closed or with an absent endpoint: one answer, the absent one's.
    assert answers == {("not_found", ("from",))}
    assert all_lineage_counts(runtime.engine) == before
    # With Issue visibility the closed Issue's refusal is its own.
    command = assertion(
        "blocks",
        ("task", task_a),
        ("task", task_b),
        "issue-visible-closed",
        (corroborates(closed_issue.meeting, closed_issue.note),),
        context=closed_issue.issue,
    )
    assert _answer(runtime.client_refused(command)) == ("conflict", ["state"])
