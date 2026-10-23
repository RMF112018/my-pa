"""AT-005 / CR-006: the composite Work writes, one native create with its lineage.

S2 contract sections 3.1, 6.2, 6.3, 6.4 and 7.2 against PostgreSQL, through
`ApplicationService.invoke`. `issues.work.create_task` and
`issues.work.create_commitment` run exactly the v1 `tasks.create` /
`commitments.create` body on the unit of work `invoke` opened, then write the
new record's `work` membership and its association intents: one transaction,
one idempotency record (the lineage request row), one native Record Event,
and a byte-stable replay that never re-runs the native create.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, select

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    AddIssueProjectLink,
    CreateCommitment,
    CreateTask,
    EndIssueProjectLink,
    ReadTask,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.ports import RepositoryFailureError
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.issues import SqlIssueRepository
from my_pa.infrastructure.persistence.tables import (
    commitment_history,
    commitments,
    lineage_write_request_links,
    lineage_write_requests,
    record_events,
    record_link_revisions,
    record_links,
    task_history,
    tasks,
)
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_record_harness import NOTE_BODY, capture, meeting, note_anchor
from tests.database.lineage_s2_harness import (
    GATEWAY,
    REVIEW_DECISION,
    S2Runtime,
    all_s2_counts,
    work_commitment,
    work_task,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

pytestmark = pytest.mark.database

_NATIVE_TABLES: Final = (tasks, task_history, commitments, commitment_history, record_events)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _ok(runtime: S2Runtime, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    return runtime.ok(command, **kwargs)


def _refused(runtime: S2Runtime, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


def _counts(engine: Engine) -> dict[str, int]:
    """Every lineage, request and native Work row count, Record Events included."""
    counts = dict(all_s2_counts(engine))
    with engine.connect() as connection:
        for table in _NATIVE_TABLES:
            counts[table.name] = int(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
            )
        counts["lineage_write_requests"] = int(
            connection.execute(
                select(func.count()).select_from(lineage_write_requests)
            ).scalar_one()
        )
    return counts


def _commitment_object(runtime: S2Runtime, key: str, **fields: object) -> dict[str, object]:
    origin, _, _ = capture(runtime, f"{key}-native-origin")
    return {
        "counterparty_entity_id": seed_counterparty_entity(runtime.engine, PRINCIPAL),
        "direction": "owed_to_principal",
        "summary": f"Synthetic composite commitment {key}",
        "origin_evidence_ref": origin,
        "accepted_by_review_decision_id": REVIEW_DECISION,
        **fields,
    }


def _origin_intent(runtime: S2Runtime, key: str) -> dict[str, object]:
    meeting_id, note_id = meeting(runtime, f"{key}-n1")
    return {
        "relation_type": "originated_from",
        "to_record": {"family": "meeting_note_version", "record_id": note_id},
        "evidence_anchors": [note_anchor(meeting_id, note_id, NOTE_BODY)],
    }


def _resolve_intent(
    issue: str, purpose: object = "Resolve the façade survey."
) -> dict[str, object]:
    intent: dict[str, object] = {
        "relation_type": "created_to_resolve",
        "to_record": {"family": "situation", "record_id": issue},
        "evidence_anchors": [],
    }
    if purpose is not None:
        intent["purpose"] = purpose
    return intent


def _arguments(name: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-lineage-s2-composite",
        "purpose": "issue_work_authoring",
        "principal_id": PRINCIPAL,
        "requested_at": "2026-10-18T12:00:00Z",
        "payload": payload,
    }


def test_a_composite_writes_native_row_membership_and_links_atomically(
    runtime: S2Runtime,
) -> None:
    issue = runtime.issue("atomic")
    before = _counts(runtime.engine)
    written = _ok(
        runtime,
        work_commitment(
            issue,
            "atomic",
            _commitment_object(runtime, "atomic"),
            intents=(_origin_intent(runtime, "atomic"), _resolve_intent(issue)),
        ),
    )
    record = written["record"]
    assert record["family"] == "commitment"
    commitment_id = record["record_id"]
    membership = written["membership"]
    assert membership["kind"] == "issue_membership"
    assert membership["member_role"] == "work"
    assert membership["from"] == {"family": "situation", "record_id": issue}
    assert membership["to"] == {"family": "commitment", "record_id": commitment_id}
    assert [view["relation_type"] for view in written["associations"]] == [
        "originated_from",
        "created_to_resolve",
    ]
    for view in written["associations"]:
        assert view["from"] == {"family": "commitment", "record_id": commitment_id}
        assert view["context_issue_id"] == issue
        assert view["revision_no"] == 1
    assert written["replayed"] is False
    after = _counts(runtime.engine)
    assert after["commitments"] == before["commitments"] + 1
    assert after["record_links"] == before["record_links"] + 3
    assert after["lineage_write_request_links"] == before["lineage_write_request_links"] + 3
    with runtime.engine.connect() as connection:
        links = connection.execute(
            select(lineage_write_request_links.c.ordinal, lineage_write_request_links.c.link_id)
            .where(lineage_write_request_links.c.idempotency_key == "s2-work-commitment-atomic")
            .order_by(lineage_write_request_links.c.ordinal)
        ).all()
        assert [(row.ordinal, row.link_id) for row in links] == [
            (1, membership["link_id"]),
            *((n, view["link_id"]) for n, view in enumerate(written["associations"], 2)),
        ]
        request = connection.execute(
            select(
                lineage_write_requests.c.result_record_family,
                lineage_write_requests.c.result_record_id,
                lineage_write_requests.c.result_link_id,
            ).where(lineage_write_requests.c.idempotency_key == "s2-work-commitment-atomic")
        ).one()
        assert (request.result_record_family, request.result_record_id) == (
            "commitment",
            commitment_id,
        )
        assert request.result_link_id is None
        # The membership records the new record's native version; the intents none.
        versions = dict(
            connection.execute(
                select(
                    record_link_revisions.c.link_id, record_link_revisions.c.member_native_version
                ).where(record_link_revisions.c.link_id.in_([row.link_id for row in links]))
            ).all()
        )
        assert versions[membership["link_id"]] == 1
        assert {versions[view["link_id"]] for view in written["associations"]} == {None}
        capabilities = set(
            connection.execute(
                select(record_links.c.source_capability).where(
                    record_links.c.link_id.in_([row.link_id for row in links])
                )
            ).scalars()
        )
        assert capabilities == {"issues.work.create_commitment"}
    # The new Commitment is natively what the nested object stated.
    view = runtime.commitment_view(commitment_id)
    assert (view["direction"], view["state"], view["evidence_state"]) == (
        "owed_to_principal",
        "open",
        "accepted",
    )


def test_a_refused_composite_writes_no_native_row_or_request(
    runtime: S2Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = runtime.issue("refused")
    outsider = runtime.task("refused-outsider")
    meeting_id, note_id = meeting(runtime, "refused-n1")
    delegation = {
        "relation_type": "delegated_from",
        "to_record": {"family": "task", "record_id": outsider},
        "evidence_anchors": [note_anchor(meeting_id, note_id, NOTE_BODY)],
    }
    native = _commitment_object(runtime, "refused")
    before = _counts(runtime.engine)
    # A lineage rule refuses (the Task is not a member of the Issue) ...
    assert _refused(
        runtime, work_commitment(issue, "refused-rule", native, intents=(delegation,))
    ) == ("invalid_request", ["to"])
    # ... a v1 rule refuses inside the native create (an absent Commitment) ...
    assert _refused(
        runtime,
        work_task(
            issue,
            "refused-native",
            {
                "title": "Synthetic follow-up",
                "origin_kind": "direct_principal",
                "role": "follow_up",
                "commitment_id": "cmt_lineages2absent0003",
            },
        ),
    ) == ("not_found", ["commitment_id"])
    assert _counts(runtime.engine) == before

    # ... and a failure after the native create and the links rolls them all back.
    def fail(*_args: object, **_kwargs: object) -> None:
        raise RepositoryFailureError

    monkeypatch.setattr(SqlIssueRepository, "insert_write_request_links", fail)
    envelope = runtime.invoke(work_task(issue, "refused-late"), surface=GATEWAY)
    assert envelope.error is not None
    assert envelope.error.code.value == "internal_error"
    assert _counts(runtime.engine) == before


def test_a_composite_replay_returns_the_original_result_without_a_native_write(
    runtime: S2Runtime,
) -> None:
    issue = runtime.issue("replay")
    command = work_task(
        issue,
        "replay",
        intents=(_origin_intent(runtime, "replay"), _resolve_intent(issue)),
    )
    original = _ok(runtime, command)
    before = _counts(runtime.engine)
    replayed = _ok(runtime, command)
    assert replayed["replayed"] is True
    assert {k: v for k, v in replayed.items() if k != "replayed"} == {
        k: v for k, v in original.items() if k != "replayed"
    }
    # No native row, history receipt, Record Event or link was written again.
    assert _counts(runtime.engine) == before
    # The same key for another request is a conflict, and writes nothing.
    changed = work_task(issue, "replay", {"title": "Another", "origin_kind": "direct_principal"})
    assert _refused(runtime, changed) == ("conflict", ["idempotency_conflict"])
    assert _counts(runtime.engine) == before


def test_a_composite_refuses_situation_id_and_idempotency_key_inside_the_native_object(
    runtime: S2Runtime,
) -> None:
    issue = runtime.issue("nested")
    task = {"title": "Synthetic task", "origin_kind": "direct_principal"}
    commitment = _commitment_object(runtime, "nested")
    refused = {
        "idempotency_key": "nested-key",
        "situation_id": issue,
        "principal_id": PRINCIPAL,
        "unknown": "x",
    }
    for name, key, document in (
        ("issues.work.create_task", "task", task),
        ("issues.work.create_commitment", "commitment", commitment),
    ):
        base = {"issue_id": issue, "idempotency_key": f"s2-nested-{key}", key: document}
        normalize(name, _arguments(name, base))
        for field, value in refused.items():
            with pytest.raises(InvalidRequestError):
                normalize(name, _arguments(name, {**base, key: {**document, field: value}}))
        # Not an object at all.
        with pytest.raises(InvalidRequestError):
            normalize(name, _arguments(name, {**base, key: [document]}))
    # The v1 rules still apply inside the object: a blank title, a bad enum.
    with pytest.raises(InvalidRequestError):
        work_task(issue, "nested-blank", {"title": " ", "origin_kind": "direct_principal"})
    with pytest.raises(InvalidRequestError) as caught:
        work_task(issue, "nested-enum", {"title": "x", "origin_kind": "invented"})
    assert [detail.value for detail in caught.value.safe_details] == ["origin_kind"]
    before = _counts(runtime.engine)
    _ok(runtime, work_task(issue, "nested-ok", task))
    assert _counts(runtime.engine)["tasks"] == before["tasks"] + 1


def test_a_composite_project_outside_the_issue_links_is_refused(runtime: S2Runtime) -> None:
    issue = runtime.issue("project")
    linked = runtime.project("project-linked")
    unlinked = runtime.project("project-unlinked")
    _ok(
        runtime,
        AddIssueProjectLink(
            issue_id=issue,
            project_id=linked,
            expected_membership_revision=0,
            idempotency_key="s2-project-link",
        ),
    )
    before = _counts(runtime.engine)
    for project, key in ((unlinked, "unlinked"), ("prj_lineages2absent0001", "absent")):
        task = {"title": "Synthetic task", "origin_kind": "direct_principal", "project_id": project}
        assert _refused(runtime, work_task(issue, f"project-{key}", task)) == (
            "invalid_request",
            ["project_id"],
        )
    commitment = _commitment_object(runtime, "project-c", project_id=unlinked)
    counts = _counts(runtime.engine)
    assert _refused(runtime, work_commitment(issue, "project-c", commitment)) == (
        "invalid_request",
        ["project_id"],
    )
    assert _counts(runtime.engine) == counts
    assert _counts(runtime.engine)["tasks"] == before["tasks"]
    written = _ok(
        runtime,
        work_task(
            issue,
            "project-linked",
            {"title": "Synthetic task", "origin_kind": "direct_principal", "project_id": linked},
        ),
    )
    task_view = runtime.ok(ReadTask(task_id=written["record"]["record_id"]))["task"]
    assert task_view["project_id"] == linked
    # An ended link no longer qualifies the Project.
    _ok(
        runtime,
        EndIssueProjectLink(
            issue_id=issue,
            project_id=linked,
            expected_membership_revision=1,
            idempotency_key="s2-project-unlink",
            reason="Out of scope.",
        ),
    )
    assert _refused(
        runtime,
        work_task(
            issue,
            "project-ended",
            {"title": "Synthetic task", "origin_kind": "direct_principal", "project_id": linked},
        ),
    ) == ("invalid_request", ["project_id"])


def test_a_composite_emits_only_its_native_record_event(runtime: S2Runtime) -> None:
    issue = runtime.issue("event")
    for name, command, family in (
        (
            "issues.work.create_task",
            work_task(issue, "event-t", intents=(_resolve_intent(issue),)),
            "task",
        ),
        (
            "issues.work.create_commitment",
            work_commitment(issue, "event-c", _commitment_object(runtime, "event-c")),
            "commitment",
        ),
    ):
        before = _counts(runtime.engine)["record_events"]
        record_id = _ok(runtime, command)["record"]["record_id"]
        with runtime.engine.connect() as connection:
            rows = connection.execute(
                select(
                    record_events.c.record_family,
                    record_events.c.record_id,
                    record_events.c.event_kind,
                    record_events.c.source_capability,
                ).order_by(record_events.c.sequence_number.desc())
            ).all()
        assert len(rows) == before + 1
        assert tuple(rows[0]) == (family, record_id, "created", name)


def _without(view: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in view.items() if key not in keys}


#: What differs between two creates with the same fields: identity and time.
_TASK_IDENTITY: Final = frozenset({"task_id", "created_at", "updated_at"})
_COMMITMENT_IDENTITY: Final = frozenset({"commitment_id", "created_at", "updated_at", "opened_at"})


def test_a_composite_native_row_reads_like_a_v1_create(runtime: S2Runtime) -> None:
    issue = runtime.issue("v1")
    fields: dict[str, object] = {
        "title": "Synthetic same task",
        "origin_kind": "direct_principal",
        "description": "Same fields.",
        "priority": "p2",
        "due_at": "2026-11-01T12:00:00+00:00",
    }
    composite = _ok(runtime, work_task(issue, "v1-task", fields))["record"]["record_id"]
    v1 = runtime.ok(
        normalize(
            "tasks.create",
            {
                "request_id": "req-lineage-s2-v1",
                "purpose": "task_authoring",
                "principal_id": PRINCIPAL,
                "requested_at": "2026-10-18T12:00:00Z",
                "payload": {**fields, "idempotency_key": "s2-v1-task"},
            },
        )[1]
    )["task"]["task_id"]
    composite_view = runtime.ok(ReadTask(task_id=composite))["task"]
    v1_view = runtime.ok(ReadTask(task_id=v1))["task"]
    assert set(composite_view) == set(v1_view)
    differing = {key for key in composite_view if composite_view[key] != v1_view[key]}
    assert differing <= _TASK_IDENTITY | {"opened_at"}
    assert _without(composite_view, _TASK_IDENTITY | {"opened_at"}) == _without(
        v1_view, _TASK_IDENTITY | {"opened_at"}
    )
    origin, _, _ = capture(runtime, "v1-commitment-origin")
    counterparty = seed_counterparty_entity(runtime.engine, PRINCIPAL)
    commitment_fields: dict[str, object] = {
        "counterparty_entity_id": counterparty,
        "direction": "owed_by_principal",
        "summary": "Synthetic same commitment",
        "origin_evidence_ref": origin,
        "accepted_by_review_decision_id": REVIEW_DECISION,
    }
    composite_c = _ok(runtime, work_commitment(issue, "v1-commitment", commitment_fields))[
        "record"
    ]["record_id"]
    v1_c = runtime.ok(
        CreateCommitment(
            counterparty_entity_id=counterparty,
            direction=CommitmentDirection.OWED_BY_PRINCIPAL,
            summary="Synthetic same commitment",
            origin_evidence_ref=origin,
            accepted_by_review_decision_id=REVIEW_DECISION,
            idempotency_key="s2-v1-commitment",
        )
    )["commitment"]["commitment_id"]
    composite_cv, v1_cv = runtime.commitment_view(composite_c), runtime.commitment_view(v1_c)
    assert set(composite_cv) == set(v1_cv)
    assert _without(composite_cv, _COMMITMENT_IDENTITY) == _without(v1_cv, _COMMITMENT_IDENTITY)
    # The v1 commands themselves are untouched by the composite path.
    assert CreateTask.capability.value == "tasks.create"
    assert TaskOriginKind.DIRECT_PRINCIPAL.value == fields["origin_kind"]


def test_created_to_resolve_needs_a_purpose(runtime: S2Runtime) -> None:
    issue = runtime.issue("purpose")
    for purpose in (None, "   ", "", 7, "x" * 2001):
        with pytest.raises(InvalidRequestError) as caught:
            work_task(issue, "purpose-missing", intents=(_resolve_intent(issue, purpose),))
        assert [detail.value for detail in caught.value.safe_details] == ["purpose"], purpose
    # A purpose on any other relation is not a field it has.
    with pytest.raises(InvalidRequestError) as caught:
        work_task(
            issue,
            "purpose-other",
            intents=({**_origin_intent(runtime, "purpose-other"), "purpose": "x"},),
        )
    assert [detail.value for detail in caught.value.safe_details] == ["association_intents"]
    written = _ok(
        runtime,
        work_task(issue, "purpose-ok", intents=(_resolve_intent(issue, "Resolve it."),)),
    )
    (resolving,) = written["associations"]
    assert resolving["to"] == {"family": "situation", "record_id": issue}
    with runtime.engine.connect() as connection:
        reason = connection.execute(
            select(record_link_revisions.c.reason).where(
                record_link_revisions.c.link_id == resolving["link_id"],
                record_link_revisions.c.revision_no == 1,
            )
        ).scalar_one()
    assert reason == "Resolve it."
    # Another Issue is not the composite's Issue.
    other = runtime.issue("purpose-other-issue")
    assert _refused(
        runtime, work_task(issue, "purpose-elsewhere", intents=(_resolve_intent(other),))
    ) == ("invalid_request", ["to"])


def test_a_composite_task_refuses_a_review_decision_id(runtime: S2Runtime) -> None:
    issue = runtime.issue("review")
    with pytest.raises(InvalidRequestError):
        work_task(
            issue,
            "review",
            {
                "title": "Synthetic task",
                "origin_kind": "evidence",
                "origin_evidence_ref": "cap_lineages2review0001",
                "accepted_by_review_decision_id": REVIEW_DECISION,
            },
        )
    with pytest.raises(InvalidRequestError):
        normalize(
            "issues.work.create_task",
            _arguments(
                "issues.work.create_task",
                {
                    "issue_id": issue,
                    "idempotency_key": "s2-review-normalized",
                    "task": {
                        "title": "Synthetic task",
                        "origin_kind": "direct_principal",
                        "accepted_by_review_decision_id": REVIEW_DECISION,
                    },
                },
            ),
        )
    # An evidence-origin composite Task is proposed: it cannot satisfy the gate.
    origin, _, _ = capture(runtime, "review-origin")
    proposed = _ok(
        runtime,
        work_task(
            issue,
            "review-evidence",
            {"title": "Synthetic task", "origin_kind": "evidence", "origin_evidence_ref": origin},
        ),
    )["record"]["record_id"]
    assert runtime.ok(ReadTask(task_id=proposed))["task"]["evidence_state"] == "proposed"
    # The Commitment composite keeps the v1 field and meaning (section 12, D-05).
    accepted = _ok(
        runtime, work_commitment(issue, "review-c", _commitment_object(runtime, "review-c"))
    )["record"]["record_id"]
    assert runtime.commitment_view(accepted)["evidence_state"] == "accepted"
