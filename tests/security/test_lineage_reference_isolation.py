"""AT-009: record lineage S1 references are Principal-isolated and fail closed.

S1 contract sections 3.2 (check order: prefix, then Principal-scoped existence
under the right parent, then linkability) and 4.3 (a linked native record is
never deleted), against PostgreSQL through `ApplicationService.invoke`. An
absent and a foreign record answer one `not_found`; a foreign archived Task
and a foreign context Situation answer exactly like a foreign live Task, so
linkability never leaks across Principals; own non-linkable records are
`invalid_request` / `endpoint`; and a refused reference writes nothing.
Every identity here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL, LineageRuntime
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    all_lineage_counts,
    capture,
    capture_anchor,
    commitment,
    meeting,
    membership,
    note_anchor,
    originated_from,
    task,
)
from tests.schema.lineage_schema_ahead_contract import S1_CAPABILITIES

from my_pa.application.commands import (
    AddIssueProjectLink,
    AssertRecordAssociation,
    CorrectRecordAssociation,
    CreateSituation,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
    ListIssues,
    ListMeetingNoteVersions,
    ReadIssue,
    ReadMeetingNoteVersion,
    ReadRecordLineage,
    UpdateIssue,
    UpdateTask,
)

pytestmark = pytest.mark.database

_ABSENT_TASK = "tsk_lineageabsent0001"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _error(runtime: LineageRuntime, command: Any) -> dict[str, Any]:  # noqa: ANN401
    before = all_lineage_counts(runtime.engine)
    error = runtime.refused(command, surface=GATEWAY)
    assert all_lineage_counts(runtime.engine) == before, command.capability.value
    return {"code": error["code"], "safe_details": error.get("safe_details")}


def _archived_task(runtime: LineageRuntime, key: str, principal_id: str = PRINCIPAL) -> str:
    task_id = task(runtime, key, principal_id=principal_id)
    runtime.ok(
        UpdateTask(
            task_id=task_id,
            expected_version=1,
            idempotency_key=f"lineage-archive-task-{key}",
            archived=True,
        ),
        principal_id=principal_id,
    )
    return task_id


def _context(runtime: LineageRuntime, key: str, principal_id: str = PRINCIPAL) -> str:
    written = runtime.ok(
        CreateSituation(title=f"Synthetic context {key}", idempotency_key=f"lineage-ctx-{key}"),
        principal_id=principal_id,
    )
    return str(written["situation_id"])


def _discusses(meeting_id: str, family: str, record_id: str, anchor: dict[str, object], key: str):  # noqa: ANN202
    return AssertRecordAssociation(
        from_record={"family": "meeting", "record_id": meeting_id},
        to_record={"family": family, "record_id": record_id},
        relation_type="discusses",
        idempotency_key=f"lineage-discusses-{key}",
        evidence_anchors=(anchor,),
    )


def test_absent_and_foreign_endpoints_answer_alike(runtime: LineageRuntime) -> None:
    issue = runtime.issue("alike")
    foreign = task(runtime, "alike-foreign", principal_id=OTHER_PRINCIPAL)
    absent = _error(runtime, membership(issue, "task", _ABSENT_TASK, "alike-absent"))
    other = _error(runtime, membership(issue, "task", foreign, "alike-foreign"))
    assert absent == other == {"code": "not_found", "safe_details": ["member"]}


def test_a_context_situation_is_not_an_issue_endpoint(runtime: LineageRuntime) -> None:
    context = _context(runtime, "ctx-endpoint")
    m1, n1 = meeting(runtime, "ctx-endpoint")
    anchor = note_anchor(m1, n1, NOTE_BODY, role="discussion")
    endpoint = _error(runtime, _discusses(m1, "situation", context, anchor, "ctx-endpoint"))
    assert endpoint == {"code": "invalid_request", "safe_details": ["endpoint"]}
    # Named as the Issue of a membership, a context Situation is no Issue at all.
    as_issue = _error(runtime, membership(context, "meeting", m1, "ctx-as-issue"))
    assert as_issue == {"code": "not_found", "safe_details": ["issue_id"]}


def test_a_wrong_parent_note_version_is_not_found(runtime: LineageRuntime) -> None:
    issue = runtime.issue("wrong-parent")
    _m1, n1 = meeting(runtime, "wrong-parent-1")
    m2, _n2 = meeting(runtime, "wrong-parent-2")
    anchor = note_anchor(m2, n1, NOTE_BODY, role="discussion")
    error = _error(runtime, membership(issue, "meeting", m2, "wrong-parent", anchors=(anchor,)))
    assert error == {"code": "not_found", "safe_details": ["evidence_anchors"]}


def test_an_archived_task_is_not_linkable(runtime: LineageRuntime) -> None:
    issue = runtime.issue("archived-task")
    archived = _archived_task(runtime, "archived-task")
    error = _error(runtime, membership(issue, "task", archived, "archived-task"))
    assert error == {"code": "invalid_request", "safe_details": ["endpoint"]}


def test_a_foreign_issue_context_is_not_found(runtime: LineageRuntime) -> None:
    foreign_issue = runtime.issue("foreign-context", principal_id=OTHER_PRINCIPAL)
    m1, n1 = meeting(runtime, "foreign-context")
    c1 = commitment(runtime, "foreign-context")
    error = _error(
        runtime,
        originated_from(
            "commitment",
            c1,
            "meeting_note_version",
            n1,
            "foreign-context",
            (note_anchor(m1, n1, NOTE_BODY),),
            context_issue_id=foreign_issue,
        ),
    )
    assert error == {"code": "not_found", "safe_details": ["context_issue_id"]}


def test_a_lineage_read_of_a_foreign_root_is_not_found(runtime: LineageRuntime) -> None:
    foreign = task(runtime, "foreign-root", principal_id=OTHER_PRINCIPAL)
    for record_id in (foreign, _ABSENT_TASK):
        error = runtime.refused(
            ReadRecordLineage(origin={"family": "task", "record_id": record_id})
        )
        assert error["code"] == "not_found" and error["safe_details"] == ["origin"]


def test_a_linked_native_record_cannot_be_deleted(runtime: LineageRuntime) -> None:
    issue = runtime.issue("no-delete")
    m1, _n1 = meeting(runtime, "no-delete")
    runtime.ok(membership(issue, "meeting", m1, "no-delete", role="discussion"), surface=GATEWAY)
    for statement, parameter in (
        ("DELETE FROM knowledge.meetings WHERE meeting_id = :id", m1),
        ("DELETE FROM knowledge.situations WHERE situation_id = :id", issue),
    ):
        with pytest.raises(DBAPIError) as refused, runtime.engine.begin() as connection:
            connection.execute(text(statement), {"id": parameter})
        assert "a record link names is never deleted" in str(refused.value)


def test_no_row_is_written_for_a_refused_reference(runtime: LineageRuntime) -> None:
    issue = runtime.issue("no-row")
    m1, n1 = meeting(runtime, "no-row")
    foreign_meeting, foreign_note = meeting(runtime, "no-row-foreign", principal_id=OTHER_PRINCIPAL)
    commands = [
        membership(issue, "task", _ABSENT_TASK, "no-row-absent"),
        membership(
            issue,
            "meeting",
            m1,
            "no-row-anchor",
            anchors=(note_anchor(foreign_meeting, foreign_note, NOTE_BODY, role="discussion"),),
        ),
        membership("sit_lineageabsent0001", "meeting", m1, "no-row-issue"),
    ]
    for command in commands:
        assert _error(runtime, command)["code"] == "not_found"
    assert n1


def test_a_foreign_archived_task_answers_not_found(runtime: LineageRuntime) -> None:
    issue = runtime.issue("foreign-archived")
    archived = _archived_task(runtime, "foreign-archived", principal_id=OTHER_PRINCIPAL)
    live = task(runtime, "foreign-live", principal_id=OTHER_PRINCIPAL)
    assert (
        _error(runtime, membership(issue, "task", archived, "foreign-archived"))
        == _error(runtime, membership(issue, "task", live, "foreign-live"))
        == {"code": "not_found", "safe_details": ["member"]}
    )


def test_a_foreign_context_situation_answers_not_found(runtime: LineageRuntime) -> None:
    foreign_context = _context(runtime, "foreign-ctx", principal_id=OTHER_PRINCIPAL)
    foreign_issue = runtime.issue("foreign-ctx-issue", principal_id=OTHER_PRINCIPAL)
    m1, n1 = meeting(runtime, "foreign-ctx")
    anchor = note_anchor(m1, n1, NOTE_BODY, role="discussion")
    context_answer = _error(runtime, _discusses(m1, "situation", foreign_context, anchor, "fc"))
    issue_answer = _error(runtime, _discusses(m1, "situation", foreign_issue, anchor, "fi"))
    assert context_answer == issue_answer == {"code": "not_found", "safe_details": ["to"]}


def test_read_version_of_a_foreign_note_is_not_found(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "read-foreign", principal_id=OTHER_PRINCIPAL)
    error = runtime.refused(
        ReadMeetingNoteVersion(meeting_id=m1, note_version_id=n1, include_body=True)
    )
    assert error["code"] == "not_found" and error["safe_details"] == ["note_version_id"]


def test_read_version_under_the_wrong_meeting_is_not_found(runtime: LineageRuntime) -> None:
    _m1, n1 = meeting(runtime, "read-wrong-1")
    m2, _n2 = meeting(runtime, "read-wrong-2")
    error = runtime.refused(
        ReadMeetingNoteVersion(meeting_id=m2, note_version_id=n1, include_body=True)
    )
    assert error["code"] == "not_found" and error["safe_details"] == ["note_version_id"]


def test_a_foreign_capture_root_anchor_is_not_found(runtime: LineageRuntime) -> None:
    issue = runtime.issue("foreign-capture")
    root, version, _ = capture(runtime, "foreign-capture", principal_id=OTHER_PRINCIPAL)
    m1, _n1 = meeting(runtime, "foreign-capture")
    error = _error(
        runtime,
        membership(
            issue,
            "meeting",
            m1,
            "foreign-capture",
            anchors=(capture_anchor(root, version, NOTE_BODY, role="corroborates"),),
        ),
    )
    assert error == {"code": "not_found", "safe_details": ["evidence_anchors"]}


# ---- I5 hardening: every S1 capability, foreign subject vs absent subject ---------

_ABSENT_ISSUE = "sit_lineageabsent0002"
_ABSENT_PROJECT = "prj_lineageabsent0001"
_ABSENT_MEETING = "mtg_lineageabsent0001"
_ABSENT_NOTE = "mnote_lineageabsent0001"
_ABSENT_LINK = "irl_lineageabsent0001"
_ABSENT_COMMITMENT = "cmt_lineageabsent0001"


def _answer(runtime: LineageRuntime, command: Any) -> dict[str, Any]:  # noqa: ANN401
    """The whole answer with the request-scoped fields dropped; writes nothing."""
    before = all_lineage_counts(runtime.engine)
    envelope = runtime.invoke(command, surface=GATEWAY).to_canonical_dict()
    assert all_lineage_counts(runtime.engine) == before, command.capability.value
    error = envelope.get("error")
    if error is not None:
        assert isinstance(error, dict)
        return {"code": error["code"], "safe_details": error.get("safe_details")}
    return {"result": envelope["result"]}


def test_every_s1_capability_answers_a_foreign_subject_like_an_absent_one(
    runtime: LineageRuntime,
) -> None:
    """Cross-Principal parity across the S1 surface (section 3.2 check order).

    Each pair names the same request twice: once with a subject the other
    Principal really holds (an Issue, Project, Project link, membership,
    semantic link, Meeting or note version), once with an absent one. The two
    answers must be identical, so no capability tells a caller that another
    Principal's record exists -- nor its kind: a foreign membership named to
    an association write, and a foreign semantic link named to a membership
    write, answer like an absent link rather than `invalid_request` / `link_id`.
    `issues.create` names no existing record and has no pair.
    """
    other = OTHER_PRINCIPAL
    f_issue = runtime.issue("parity-foreign", principal_id=other)
    f_project = runtime.project("parity-foreign", principal_id=other)
    f_meeting, f_note = meeting(runtime, "parity-foreign", principal_id=other)
    f_commitment = commitment(runtime, "parity-foreign", principal_id=other)
    runtime.ok(
        AddIssueProjectLink(
            issue_id=f_issue,
            project_id=f_project,
            expected_membership_revision=0,
            idempotency_key="lineage-parity-foreign-link",
        ),
        principal_id=other,
        surface=GATEWAY,
    )
    f_membership = runtime.ok(
        membership(f_issue, "meeting", f_meeting, "parity-foreign", role="discussion"),
        principal_id=other,
        surface=GATEWAY,
    )["membership"]["link_id"]
    f_semantic = runtime.ok(
        originated_from(
            "commitment",
            f_commitment,
            "meeting_note_version",
            f_note,
            "parity-foreign",
            (note_anchor(f_meeting, f_note, NOTE_BODY),),
        ),
        principal_id=other,
        surface=GATEWAY,
    )["association"]["link_id"]
    issue = runtime.issue("parity-own")
    project = runtime.project("parity-own")
    m1, n1 = meeting(runtime, "parity-own")
    own_anchor = note_anchor(m1, n1, NOTE_BODY)

    def update(issue_id: str) -> UpdateIssue:
        return UpdateIssue(
            issue_id=issue_id,
            expected_version=1,
            idempotency_key="lineage-parity-update",
            title="Never retitled",
        )

    def link_add(issue_id: str, project_id: str) -> AddIssueProjectLink:
        return AddIssueProjectLink(
            issue_id=issue_id,
            project_id=project_id,
            expected_membership_revision=0,
            idempotency_key="lineage-parity-link-add",
        )

    def link_end(issue_id: str, project_id: str) -> EndIssueProjectLink:
        return EndIssueProjectLink(
            issue_id=issue_id,
            project_id=project_id,
            expected_membership_revision=1,
            idempotency_key="lineage-parity-link-end",
            reason="never ended",
        )

    def member_end(link_id: str) -> EndIssueMembership:
        return EndIssueMembership(
            link_id=link_id,
            expected_revision=1,
            idempotency_key="lineage-parity-member-end",
            reason="never ended",
        )

    def correct(link_id: str) -> CorrectRecordAssociation:
        return CorrectRecordAssociation(
            link_id=link_id,
            expected_revision=1,
            idempotency_key="lineage-parity-correct",
            reason="never corrected",
            evidence_anchors=(own_anchor,),
        )

    def end(link_id: str) -> EndRecordAssociation:
        return EndRecordAssociation(
            link_id=link_id,
            expected_revision=1,
            idempotency_key="lineage-parity-end",
            reason="never ended",
        )

    def lineage(origin: tuple[str, str], issue_id: str | None = None) -> ReadRecordLineage:
        return ReadRecordLineage(
            origin={"family": origin[0], "record_id": origin[1]}, issue_id=issue_id
        )

    pairs: list[tuple[Any, Any]] = [
        (ReadIssue(issue_id=f_issue), ReadIssue(issue_id=_ABSENT_ISSUE)),
        (
            ReadIssue(issue_id=f_issue, include_members=True),
            ReadIssue(issue_id=_ABSENT_ISSUE, include_members=True),
        ),
        (ListIssues(project_id=f_project), ListIssues(project_id=_ABSENT_PROJECT)),
        (ListIssues(after=f_issue), ListIssues(after=_ABSENT_ISSUE)),
        (update(f_issue), update(_ABSENT_ISSUE)),
        (link_add(f_issue, project), link_add(_ABSENT_ISSUE, project)),
        (link_add(issue, f_project), link_add(issue, _ABSENT_PROJECT)),
        (link_end(f_issue, f_project), link_end(_ABSENT_ISSUE, _ABSENT_PROJECT)),
        (link_end(issue, f_project), link_end(issue, _ABSENT_PROJECT)),
        (
            membership(f_issue, "meeting", m1, "parity-foreign-issue", role="discussion"),
            membership(_ABSENT_ISSUE, "meeting", m1, "parity-foreign-issue", role="discussion"),
        ),
        (
            membership(issue, "meeting", f_meeting, "parity-foreign-member", role="discussion"),
            membership(
                issue, "meeting", _ABSENT_MEETING, "parity-foreign-member", role="discussion"
            ),
        ),
        (member_end(f_membership), member_end(_ABSENT_LINK)),
        (member_end(f_semantic), member_end(_ABSENT_LINK)),
        (
            originated_from(
                "commitment", f_commitment, "meeting_note_version", n1, "parity", (own_anchor,)
            ),
            originated_from(
                "commitment",
                _ABSENT_COMMITMENT,
                "meeting_note_version",
                n1,
                "parity",
                (own_anchor,),
            ),
        ),
        (correct(f_semantic), correct(_ABSENT_LINK)),
        (correct(f_membership), correct(_ABSENT_LINK)),
        (end(f_semantic), end(_ABSENT_LINK)),
        (end(f_membership), end(_ABSENT_LINK)),
        (lineage(("situation", f_issue)), lineage(("situation", _ABSENT_ISSUE))),
        (lineage(("meeting", f_meeting)), lineage(("meeting", _ABSENT_MEETING))),
        (lineage(("meeting", m1), f_issue), lineage(("meeting", m1), _ABSENT_ISSUE)),
        (
            ListMeetingNoteVersions(meeting_id=f_meeting),
            ListMeetingNoteVersions(meeting_id=_ABSENT_MEETING),
        ),
        (
            ReadMeetingNoteVersion(meeting_id=f_meeting, note_version_id=f_note, include_body=True),
            ReadMeetingNoteVersion(
                meeting_id=_ABSENT_MEETING, note_version_id=_ABSENT_NOTE, include_body=True
            ),
        ),
        (
            ReadMeetingNoteVersion(meeting_id=m1, note_version_id=f_note, include_body=True),
            ReadMeetingNoteVersion(meeting_id=m1, note_version_id=_ABSENT_NOTE, include_body=True),
        ),
    ]
    covered = {foreign.capability.value for foreign, _ in pairs}
    assert covered == S1_CAPABILITIES - {"issues.create"}
    for foreign, absent in pairs:
        capability = foreign.capability.value
        foreign_answer = _answer(runtime, foreign)
        assert foreign_answer == _answer(runtime, absent), capability
        if capability == "issues.list":
            # A filter or cursor names no record of yours either way.
            assert foreign_answer in (
                {"result": {"issues": [], "next_cursor": None}},
                {"code": "invalid_request", "safe_details": ["cursor"]},
            ), foreign_answer
        else:
            assert foreign_answer["code"] == "not_found", (capability, foreign_answer)


def test_no_s1_answer_carries_a_source_digest_or_body_except_read_version(
    runtime: LineageRuntime,
) -> None:
    """F11 and section 7: digests and bodies leave only through `read_version`.

    Every S1 answer the plane produces over a real database -- writes, their
    replays, and reads, from every root -- is scanned for the stored note
    content digest, the cited passage digest, the note body and the passage
    text. Only `meetings.notes.read_version` may carry the content digest, and
    the body only when `include_body` was asked for.
    """
    issue = runtime.issue("leak")
    project = runtime.project("leak")
    m1, n1 = meeting(runtime, "leak")
    c1 = commitment(runtime, "leak")
    anchor = note_anchor(m1, n1, NOTE_BODY)
    corrected = note_anchor(m1, n1, NOTE_BODY, passage="Next: pour")
    discussion = note_anchor(m1, n1, NOTE_BODY, role="discussion", passage="Decisions")
    secrets = {
        str(anchor["source_sha256"]),
        str(anchor["passage_sha256"]),
        str(corrected["passage_sha256"]),
        str(discussion["passage_sha256"]),
        NOTE_BODY,
        "façade survey",
    }
    link = AddIssueProjectLink(
        issue_id=issue,
        project_id=project,
        expected_membership_revision=0,
        idempotency_key="lineage-leak-link",
        evidence_anchor=discussion,
    )
    member = membership(issue, "meeting", m1, "leak", role="discussion", anchors=(discussion,))
    assertion = originated_from(
        "commitment", c1, "meeting_note_version", n1, "leak", (anchor,), context_issue_id=issue
    )
    answers: list[dict[str, Any]] = []
    for command in (link, member, assertion):
        answers.append(runtime.ok(command, surface=GATEWAY))
        answers.append(runtime.ok(command, surface=GATEWAY))  # the replay
    link_id = answers[-1]["association"]["link_id"]
    answers.append(
        runtime.ok(
            CorrectRecordAssociation(
                link_id=link_id,
                expected_revision=1,
                idempotency_key="lineage-leak-correct",
                reason="a narrower synthetic passage",
                evidence_anchors=(corrected,),
            ),
            surface=GATEWAY,
        )
    )
    answers.append(runtime.ok(ReadIssue(issue_id=issue, include_members=True)))
    answers.append(runtime.ok(ListIssues()))
    for family, record_id in (
        ("situation", issue),
        ("meeting", m1),
        ("meeting_note_version", n1),
        ("commitment", c1),
    ):
        answers.append(
            runtime.ok(ReadRecordLineage(origin={"family": family, "record_id": record_id}))
        )
    answers.append(runtime.ok(ListMeetingNoteVersions(meeting_id=m1)))
    answers.append(
        runtime.ok(
            EndRecordAssociation(
                link_id=link_id,
                expected_revision=2,
                idempotency_key="lineage-leak-end",
                reason="synthetic end",
            ),
            surface=GATEWAY,
        )
    )
    for answer in answers:
        rendered = json.dumps(answer, ensure_ascii=False)
        leaked = sorted(secret for secret in secrets if secret in rendered)
        assert leaked == [], (sorted(answer), leaked)
    bare = runtime.ok(ReadMeetingNoteVersion(meeting_id=m1, note_version_id=n1))
    assert bare["note"]["content_sha256"] == anchor["source_sha256"]
    assert "body_markdown" not in bare["note"] and NOTE_BODY not in json.dumps(bare)
    full = runtime.ok(ReadMeetingNoteVersion(meeting_id=m1, note_version_id=n1, include_body=True))
    assert full["note"]["body_markdown"] == NOTE_BODY
