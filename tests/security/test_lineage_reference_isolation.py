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

from my_pa.application.commands import (
    AssertRecordAssociation,
    CreateSituation,
    ReadMeetingNoteVersion,
    ReadRecordLineage,
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
