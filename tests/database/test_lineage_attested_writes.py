"""Record lineage S1 authority, switch and Issue-reference refusals (AT-023, database).

S1 contract sections 6.1, 7.5 and 8 against PostgreSQL through
`ApplicationService.invoke`:

* an attested write (`issues.project_links.*`) is local-operator only -- a local
  operator surface records `local_operator` and its channel, an ordinary remote
  client is `denied` and writes nothing;
* with `lineage_enabled` off every Issue capability answers `unsupported` and
  writes nothing;
* the Work and Memory writers refuse an Issue `situation_id`, still accept a
  context Situation, and answer a foreign Issue exactly as before S1;
* `SqlSituationRepository.list_situations` omits an Issue row (R1-F26).

The `issues.memberships.*` and `records.associations.*` rows of this module
(`test_an_operator_review_client_cannot_call_any_s1_write`,
`test_a_replayed_attested_write_from_an_ordinary_client_is_denied_before_the_replay_lookup`)
join with those capabilities. Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select

from my_pa.application.commands import (
    AddIssueProjectLink,
    CreateCommitment,
    CreateIssue,
    CreateRelationshipMemory,
    CreateSituation,
    CreateTask,
    EndIssueProjectLink,
    ListIssues,
    ReadIssue,
    RecordTask,
    UpdateIssue,
)
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.situation_repository import SqlSituationRepository
from my_pa.infrastructure.persistence.tables import issue_project_membership_events
from tests.database.lineage_issue_harness import (
    OTHER_PRINCIPAL,
    PRINCIPAL,
    REMOTE_CLIENT,
    LineageRuntime,
    lineage_row_counts,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _link(issue_id: str, project_id: str, key: str, expected: int = 0) -> AddIssueProjectLink:
    return AddIssueProjectLink(
        issue_id=issue_id,
        project_id=project_id,
        expected_membership_revision=expected,
        idempotency_key=f"lineage-link-{key}",
    )


def test_a_local_operator_write_records_its_class_and_channel(runtime: LineageRuntime) -> None:
    issue = runtime.issue("attested-local")
    project = runtime.project("attested-local")
    for surface, channel, key in (
        (OperatorSurface.HTTP_GATEWAY, "local_web", "gateway"),
        (OperatorSurface.CLI, "local_cli", "cli"),
    ):
        expected = 0 if surface is OperatorSurface.HTTP_GATEWAY else 2
        written = runtime.ok(_link(issue, project, key, expected), surface=surface)
        assert written["replayed"] is False
        link = written["project_link"]
        assert link["state"] == "active"
        assert link["acceptance_basis"] == "user_confirmed"
        if surface is OperatorSurface.HTTP_GATEWAY:
            runtime.ok(
                EndIssueProjectLink(
                    issue_id=issue,
                    project_id=project,
                    expected_membership_revision=1,
                    idempotency_key="lineage-link-end-gateway",
                    reason="the synthetic issue left the project",
                ),
                surface=surface,
            )
        with runtime.engine.connect() as connection:
            row = connection.execute(
                select(
                    issue_project_membership_events.c.authority_class,
                    issue_project_membership_events.c.decision_channel,
                ).where(
                    issue_project_membership_events.c.revision_no == link["membership_revision_no"]
                )
            ).one()
        assert (row.authority_class, row.decision_channel) == ("local_operator", channel)


def test_an_ordinary_remote_client_is_denied_accepted_lineage_writes(
    runtime: LineageRuntime,
) -> None:
    issue = runtime.issue("attested-remote")
    project = runtime.project("attested-remote")
    before = lineage_row_counts(runtime.engine)
    error = runtime.refused(_link(issue, project, "remote"), remote_client=REMOTE_CLIENT)
    assert error["code"] == "denied"
    # A local caller with no stamped operator surface is not `local_operator`
    # either (stdio MCP, an unstamped composition): denied the same way.
    unstamped = runtime.refused(_link(issue, project, "unstamped"))
    assert unstamped["code"] == "denied"
    assert lineage_row_counts(runtime.engine) == before


def test_switch_off_answers_unsupported_and_writes_nothing(disposable_database: str) -> None:
    on = LineageRuntime(disposable_database)
    off = LineageRuntime(disposable_database, lineage_enabled=False)
    try:
        issue = on.issue("switch-off")
        project = on.project("switch-off")
        before = lineage_row_counts(off.engine)
        commands: list[Any] = [
            CreateIssue(title="Never written", idempotency_key="lineage-off-create"),
            ReadIssue(issue_id=issue),
            ListIssues(),
            UpdateIssue(
                issue_id=issue,
                expected_version=1,
                idempotency_key="lineage-off-update",
                title="Never retitled",
            ),
            _link(issue, project, "off"),
            EndIssueProjectLink(
                issue_id=issue,
                project_id=project,
                expected_membership_revision=1,
                idempotency_key="lineage-off-end",
                reason="never ended",
            ),
        ]
        for command in commands:
            # The switch is checked before authority: even the operator surface
            # an attested write needs answers `unsupported`.
            error = off.refused(command, surface=OperatorSurface.HTTP_GATEWAY)
            assert error["code"] == "unsupported", command.capability.value
        assert lineage_row_counts(off.engine) == before
    finally:
        on.close()
        off.close()


def _context_situation(runtime: LineageRuntime, key: str, principal_id: str = PRINCIPAL) -> str:
    written = runtime.ok(
        CreateSituation(title=f"Synthetic context {key}", idempotency_key=f"lineage-ctx-{key}"),
        principal_id=principal_id,
    )
    return str(written["situation_id"])


def _writers(
    runtime: LineageRuntime, situation_id: str, key: str, principal_id: str = PRINCIPAL
) -> list[Any]:
    counterparty = seed_counterparty_entity(runtime.engine, principal_id)
    return [
        CreateTask(
            title=f"Synthetic task {key}",
            idempotency_key=f"lineage-task-{key}",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            situation_id=situation_id,
        ),
        RecordTask(
            title=f"Synthetic continuity task {key}",
            idempotency_key=f"lineage-ctask-{key}",
            situation_id=situation_id,
        ),
        CreateCommitment(
            counterparty_entity_id=counterparty,
            direction=CommitmentDirection.OWED_BY_PRINCIPAL,
            summary=f"Synthetic commitment {key}",
            origin_evidence_ref=_capture(runtime, key, principal_id),
            idempotency_key=f"lineage-cmt-{key}",
            situation_id=situation_id,
        ),
    ]


def _capture(runtime: LineageRuntime, key: str, principal_id: str) -> str:
    from my_pa.application.commands import CreateCapture

    written = runtime.ok(
        CreateCapture(text=f"Synthetic origin {key}", idempotency_key=f"lineage-cap-{key}"),
        principal_id=principal_id,
    )
    return str(written["capture_id"])


def _memory(entity_id: str, situation_id: str, key: str) -> CreateRelationshipMemory:
    return CreateRelationshipMemory(
        entity_id=entity_id,
        statement=f"Synthetic memory {key}",
        idempotency_key=f"lineage-mem-{key}",
        context_links=(
            {"target_type": "situation", "target_id": situation_id, "role": "applies_in"},
        ),
    )


def test_work_and_memory_writers_refuse_an_issue_situation_id(runtime: LineageRuntime) -> None:
    issue = runtime.issue("f04")
    for command in _writers(runtime, issue, "f04-issue"):
        error = runtime.refused(command)
        assert error["code"] == "invalid_request", command.capability.value
        assert error["safe_details"] == ["situation_id"], command.capability.value
    # Relationship Memory: an Issue target answers exactly what a context
    # Situation target answers (this build validates only Entity targets).
    entity = seed_counterparty_entity(runtime.engine, PRINCIPAL)
    context = _context_situation(runtime, "f04-memory")
    issue_answer = runtime.refused(_memory(entity, issue, "f04-memory-issue"))
    context_answer = runtime.refused(_memory(entity, context, "f04-memory-context"))
    assert issue_answer["code"] == context_answer["code"]
    assert issue_answer.get("safe_details") == context_answer.get("safe_details")


def test_work_writers_still_accept_a_context_situation_id(runtime: LineageRuntime) -> None:
    context = _context_situation(runtime, "f04-ctx")
    for command in _writers(runtime, context, "f04-context"):
        runtime.ok(command)


def test_a_foreign_issue_situation_id_answers_as_before(runtime: LineageRuntime) -> None:
    """A foreign Issue answers exactly what a foreign context Situation answers."""
    foreign_issue = runtime.issue("f04-foreign", principal_id=OTHER_PRINCIPAL)
    foreign_context = _context_situation(runtime, "f04-foreign", principal_id=OTHER_PRINCIPAL)
    issue_writers = _writers(runtime, foreign_issue, "f04-foreign-issue")
    context_writers = _writers(runtime, foreign_context, "f04-foreign-context")
    for issue_command, context_command in zip(issue_writers, context_writers, strict=True):
        issue_envelope = runtime.invoke(issue_command)
        context_envelope = runtime.invoke(context_command)
        issue_error = issue_envelope.to_canonical_dict().get("error")
        context_error = context_envelope.to_canonical_dict().get("error")
        assert (issue_error is None) is (context_error is None), issue_command.capability.value
        if issue_error is not None and context_error is not None:
            assert issue_error["code"] == context_error["code"]
            assert issue_error.get("safe_details") == context_error.get("safe_details")


def test_list_situations_omits_an_issue_row(runtime: LineageRuntime) -> None:
    """R1-F26: the shared repository listing selects context Situations only."""
    issue = runtime.issue("f26")
    context = _context_situation(runtime, "f26")
    with runtime.engine.begin() as connection:
        listed = SqlSituationRepository(connection).list_situations(PRINCIPAL)
        fetched = SqlSituationRepository(connection).get_situation(PRINCIPAL, issue)
    assert [situation.situation_id for situation in listed] == [context]
    # `get_situation` still resolves the Issue (it is how the Work writers find
    # one to refuse), and maps its kind and version.
    assert fetched is not None
    assert fetched.kind.value == "issue_workstream" and fetched.version == 1
