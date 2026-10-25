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

The `issues.memberships.*` and `records.associations.*` rows (worker I3): an
operator-review client can call no S1 write, a replay of an attested write
from an ordinary client is denied before the replay lookup, an ordinary remote
client is denied the membership and association writes, and the switch-off
row covers all fourteen S1 names. Every identity here is synthetic.

**S3.1** (S3.1 contract section 10.1, the operator directives of 2026-10-20
and 2026-10-25): the membership, association and Project-link writes are open.
A remote client and an unstamped local caller are admitted and recorded
`client_identified` (never `user_confirmed`, and still denied a revision of
accepted lineage), and another writer re-sending the operator's request is
`conflict` / `idempotency_conflict` instead of `denied`. The four converted
functions keep their names (the S1 scope guard binds them).
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
from typing import Any, Final

import pytest
from sqlalchemy import select

from my_pa.application.commands import (
    AddIssueProjectLink,
    CorrectRecordAssociation,
    CreateCommitment,
    CreateIssue,
    CreateRelationshipMemory,
    CreateSituation,
    CreateTask,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
    ListIssues,
    ListMeetingNoteVersions,
    ReadIssue,
    ReadMeetingNoteVersion,
    ReadRecordLineage,
    RecordTask,
    UpdateIssue,
)
from my_pa.bootstrap.knowledge_discovery_profiles import resolve_knowledge_client_overlay
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.lineage.vocabulary import S1_LINEAGE_WRITE_CAPABILITIES as S1_WRITES
from my_pa.domain.situation.continuity import ClosureEvidenceKind, CommitmentDirection
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.situation_repository import (
    SqlFrameRepository,
    SqlProjectRepository,
    SqlSituationRepository,
)
from my_pa.infrastructure.persistence.tables import issue_project_membership_events
from tests.database.lineage_issue_harness import (
    OTHER_PRINCIPAL,
    PRINCIPAL,
    REMOTE_CLIENT,
    LineageRuntime,
    lineage_row_counts,
)
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    all_lineage_counts,
    commitment,
    meeting,
    membership,
    note_anchor,
    originated_from,
)
from tests.database.lineage_s31_harness import client_grants, fact_rows
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity
from tests.schema.lineage_schema_ahead_contract import S1_CAPABILITIES

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
    """S3.1 section 10.1 conversion (the operator directives of 2026-10-20 and 2026-10-25).

    Before S3.1 each S1 link write by a remote client or an unstamped local
    caller was `denied` and wrote nothing. The directive opens them: each is
    admitted, and every fact row it writes is `client_identified` -- never
    `user_confirmed` -- so the client is still denied an *accepted* link: it
    can neither write one nor end or correct one the operator accepted.
    """
    for key, kwargs, channel, client in (
        ("remote", {"remote_client": REMOTE_CLIENT}, "remote_interactive", REMOTE_CLIENT),
        ("unstamped", {}, "local_unattested", None),
    ):
        before = {name: fact_rows(runtime.engine, name) for name in _FACT_TABLES}
        # Every write is admitted for the caller (never `denied`).
        _client_link_writes(runtime, key, kwargs)
        issue = runtime.issue(f"attested-{key}")
        project = runtime.project(f"attested-{key}")
        _granted_ok(runtime, _link(issue, project, key), kwargs)
        written: list[tuple[object, ...]] = []
        for name in _FACT_TABLES:
            after = fact_rows(runtime.engine, name)
            written.extend(row for identity, row in after.items() if identity not in before[name])
        assert len(written) == 6, key
        for row in written:
            # (basis, class, channel, client, claim): never the human channel's.
            assert row[:5] == ("client_identified", "ordinary_reviewer", channel, client, False)
    # The client is still denied an accepted link: the operator's membership
    # and association cannot be ended or corrected by either caller.
    operator = _link_writes(runtime, "accepted", local_link=None)
    member = runtime.ok(operator[0], surface=OperatorSurface.HTTP_GATEWAY)["membership"]
    association = runtime.ok(operator[2], surface=OperatorSurface.HTTP_GATEWAY)["association"]
    before_all = all_lineage_counts(runtime.engine)
    for key, kwargs in (("remote", {"remote_client": REMOTE_CLIENT}), ("unstamped", {})):
        for command in (
            EndIssueMembership(
                link_id=member["link_id"],
                expected_revision=1,
                idempotency_key=f"lineage-accepted-member-end-{key}",
                reason="synthetic",
            ),
            EndRecordAssociation(
                link_id=association["link_id"],
                expected_revision=1,
                idempotency_key=f"lineage-accepted-assoc-end-{key}",
                reason="synthetic",
            ),
        ):
            error = _granted_refused(runtime, command, kwargs)
            assert error["code"] == "denied", (key, command.capability.value)
    assert all_lineage_counts(runtime.engine) == before_all


#: The S3.1 fact tables (section 5.1) the S1 writes reach.
_FACT_TABLES: Final = ("record_link_revisions", "issue_project_membership_events")


def _granted(command: Any, kwargs: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    """A remote caller sees every family its write names (S3.1 section 6.4)."""
    if "remote_client" in kwargs:
        return {**kwargs, "grants": client_grants(command.capability)}
    return kwargs


def _granted_ok(runtime: LineageRuntime, command: Any, kwargs: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    return runtime.ok(command, **_granted(command, kwargs))


def _granted_refused(
    runtime: LineageRuntime,
    command: Any,  # noqa: ANN401
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return runtime.refused(command, **_granted(command, kwargs))


def _client_link_writes(runtime: LineageRuntime, key: str, kwargs: dict[str, Any]) -> list[Any]:
    """The five S1 link writes made by one client caller on its own links, each admitted."""
    issue = runtime.issue(f"client-links-{key}")
    meeting_id, note_id = meeting(runtime, f"client-links-{key}")
    c1 = commitment(runtime, f"client-links-{key}")
    added = _granted_ok(
        runtime,
        membership(issue, "meeting", meeting_id, f"client-{key}", role="discussion"),
        kwargs,
    )["membership"]
    end_member = EndIssueMembership(
        link_id=added["link_id"],
        expected_revision=1,
        idempotency_key=f"lineage-client-{key}-member-end",
        reason="synthetic",
    )
    _granted_ok(runtime, end_member, kwargs)
    asserted = _granted_ok(
        runtime,
        originated_from(
            "commitment",
            c1,
            "meeting_note_version",
            note_id,
            f"client-{key}",
            (note_anchor(meeting_id, note_id, NOTE_BODY),),
        ),
        kwargs,
    )["association"]
    correct = CorrectRecordAssociation(
        link_id=asserted["link_id"],
        expected_revision=1,
        idempotency_key=f"lineage-client-{key}-correct",
        reason="synthetic",
        evidence_anchors=(note_anchor(meeting_id, note_id, NOTE_BODY, passage="façade"),),
    )
    _granted_ok(runtime, correct, kwargs)
    end = EndRecordAssociation(
        link_id=asserted["link_id"],
        expected_revision=2,
        idempotency_key=f"lineage-client-{key}-end",
        reason="synthetic",
    )
    _granted_ok(runtime, end, kwargs)
    return [added, end_member, asserted, correct, end]


def test_switch_off_answers_unsupported_and_writes_nothing(disposable_database: str) -> None:
    on = LineageRuntime(disposable_database)
    off = LineageRuntime(disposable_database, lineage_enabled=False)
    try:
        issue = on.issue("switch-off")
        project = on.project("switch-off")
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
            *_link_writes(on, "off", local_link=None),
            ReadRecordLineage(origin={"family": "situation", "record_id": issue}),
            ListMeetingNoteVersions(meeting_id=_SYNTHETIC_MEETING),
            ReadMeetingNoteVersion(meeting_id=_SYNTHETIC_MEETING, note_version_id=_SYNTHETIC_NOTE),
            ReadIssue(issue_id=issue, include_members=True),
        ]
        assert {command.capability.value for command in commands} == S1_CAPABILITIES
        before = lineage_row_counts(off.engine)
        for command in commands:
            # The switch is checked before authority: even the operator surface
            # an attested write needs answers `unsupported`.
            error = off.refused(command, surface=OperatorSurface.HTTP_GATEWAY)
            assert error["code"] == "unsupported", command.capability.value
        assert lineage_row_counts(off.engine) == before
        assert all_lineage_counts(off.engine)["record_links"] == 0
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


# ---- memberships and associations (worker I3) -----------------------------------

_SYNTHETIC_MEETING = "mtg_lineageattest0001"
_SYNTHETIC_NOTE = "mnote_lineageattest0001"
_SYNTHETIC_LINK = "irl_lineageattest0001"


def _link_writes(runtime: LineageRuntime, key: str, *, local_link: str | None) -> list[Any]:
    """The five S1 link writes, well formed; `.end`/`.correct` name `local_link`."""
    issue = runtime.issue(f"links-{key}")
    meeting_id, note_id = meeting(runtime, f"links-{key}")
    c1 = commitment(runtime, f"links-{key}")
    anchor = note_anchor(meeting_id, note_id, NOTE_BODY)
    link = local_link or _SYNTHETIC_LINK
    return [
        membership(issue, "meeting", meeting_id, f"links-{key}", role="discussion"),
        EndIssueMembership(
            link_id=link,
            expected_revision=1,
            idempotency_key=f"lineage-links-{key}-member-end",
            reason="synthetic",
        ),
        originated_from(
            "commitment", c1, "meeting_note_version", note_id, f"links-{key}", (anchor,)
        ),
        CorrectRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key=f"lineage-links-{key}-correct",
            reason="synthetic",
            evidence_anchors=(note_anchor(meeting_id, note_id, NOTE_BODY, passage="façade"),),
        ),
        EndRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key=f"lineage-links-{key}-end",
            reason="synthetic",
        ),
    ]


class _Allowlists:
    """The four Knowledge allowlists, with the client bound to operator review."""

    def __init__(self, client: str) -> None:
        self._client = client

    def knowledge_discovery_oauth_client_id_set(self) -> frozenset[str]:
        return frozenset()

    def knowledge_operator_review_oauth_client_id_set(self) -> frozenset[str]:
        return frozenset({self._client})

    def chatllm_gateway_oauth_client_id_set(self) -> frozenset[str]:
        return frozenset()

    def knowledge_manager_oauth_client_id_set(self) -> frozenset[str]:
        return frozenset()


def test_an_operator_review_client_cannot_call_any_s1_write(disposable_database: str) -> None:
    runtime = LineageRuntime(
        disposable_database, knowledge_operator_review_client_ids=frozenset({REMOTE_CLIENT})
    )
    try:
        writes = [capability for capability in Capability if capability.value in S1_WRITES]
        assert len(writes) == 9
        # The remote composition narrows an operator-review client to its
        # Knowledge profile: no S1 capability survives, so none is published or
        # granted to it.
        allowed, pairs = resolve_knowledge_client_overlay(
            _Allowlists(REMOTE_CLIENT),
            REMOTE_CLIENT,
            frozenset(Capability),
            frozenset((capability, None) for capability in Capability),
        )
        assert not allowed & frozenset(writes)
        assert not {capability for capability, _ in pairs} & frozenset(writes)
        # S3.1 section 10.1 (the operator directives of 2026-10-20 and
        # 2026-10-25): granted directly, each S1 write is now admitted -- and
        # recorded `client_identified` / `remote_interactive`, never
        # `remote_operator_attested`: the Knowledge allowlists still confer
        # nothing on lineage (both are empty for it, section 6.1).
        before = {name: fact_rows(runtime.engine, name) for name in _FACT_TABLES}
        remote = {"remote_client": REMOTE_CLIENT}
        _client_link_writes(runtime, "review", remote)
        issue = runtime.issue("review-project")
        project = runtime.project("review-project")
        _granted_ok(runtime, _link(issue, project, "review"), remote)
        written = [
            row
            for name in _FACT_TABLES
            for identity, row in fact_rows(runtime.engine, name).items()
            if identity not in before[name]
        ]
        assert len(written) == 6
        for row in written:
            assert row[:4] == (
                "client_identified",
                "ordinary_reviewer",
                "remote_interactive",
                REMOTE_CLIENT,
            )
    finally:
        runtime.close()


def test_a_replayed_attested_write_from_an_ordinary_client_is_denied_before_the_replay_lookup(
    runtime: LineageRuntime,
) -> None:
    writes = _link_writes(runtime, "replay", local_link=None)
    added = runtime.ok(writes[0], surface=OperatorSurface.HTTP_GATEWAY)
    asserted = runtime.ok(writes[2], surface=OperatorSurface.HTTP_GATEWAY)
    before = all_lineage_counts(runtime.engine)
    for command in (writes[0], writes[2]):
        # S3.1 section 10.1 (the operator directives of 2026-10-20 and
        # 2026-10-25; section 4.9): the same key and payload a local operator
        # committed is a replay for the operator and, for an ordinary remote
        # client and an unstamped local caller, a different writer's request:
        # `conflict` / `idempotency_conflict`, nothing written, never the operator's
        # answer.
        for kwargs in ({"remote_client": REMOTE_CLIENT}, {}):
            error = _granted_refused(runtime, command, kwargs)
            assert error["code"] == "conflict", command.capability.value
            # `idempotency_conflict`: the existing detail of a key bound to a
            # different request (S3.1 section 12.1, N2-01: the contract's
            # `idempotency_key` names the malformed-key detail).
            assert error["safe_details"] == ["idempotency_conflict"], command.capability.value
            assert "result" not in error
    assert all_lineage_counts(runtime.engine) == before
    again = runtime.ok(writes[0], surface=OperatorSurface.HTTP_GATEWAY)
    assert again["replayed"] is True and again["membership"] == added["membership"]
    replayed = runtime.ok(writes[2], surface=OperatorSurface.HTTP_GATEWAY)
    assert replayed["replayed"] is True and replayed["association"] == asserted["association"]


# ---- I5 hardening: replay ordering for every S1 write ------------------------------


def _committed_writes(runtime: LineageRuntime, key: str) -> list[tuple[Any, dict[str, Any]]]:
    """All nine S1 writes, each committed once by a local operator, with its answer."""
    gateway = OperatorSurface.HTTP_GATEWAY
    project = runtime.project(f"replay-all-{key}")
    meeting_id, note_id = meeting(runtime, f"replay-all-{key}")
    c1 = commitment(runtime, f"replay-all-{key}")
    committed: list[tuple[Any, dict[str, Any]]] = []

    def commit(command: Any) -> dict[str, Any]:  # noqa: ANN401
        answer = runtime.ok(command, surface=gateway)
        committed.append((command, answer))
        return answer

    issue = commit(
        CreateIssue(title=f"Synthetic replay {key}", idempotency_key=f"lineage-ra-{key}-create")
    )["issue"]["issue_id"]
    commit(
        UpdateIssue(
            issue_id=issue,
            expected_version=1,
            idempotency_key=f"lineage-ra-{key}-update",
            state="active",
        )
    )
    commit(_link(issue, project, f"ra-{key}"))
    commit(
        EndIssueProjectLink(
            issue_id=issue,
            project_id=project,
            expected_membership_revision=1,
            idempotency_key=f"lineage-ra-{key}-link-end",
            reason="synthetic end",
        )
    )
    member = commit(membership(issue, "meeting", meeting_id, f"ra-{key}", role="discussion"))[
        "membership"
    ]["link_id"]
    commit(
        EndIssueMembership(
            link_id=member,
            expected_revision=1,
            idempotency_key=f"lineage-ra-{key}-member-end",
            reason="synthetic end",
        )
    )
    link = commit(
        originated_from(
            "commitment",
            c1,
            "meeting_note_version",
            note_id,
            f"ra-{key}",
            (note_anchor(meeting_id, note_id, NOTE_BODY),),
        )
    )["association"]["link_id"]
    commit(
        CorrectRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key=f"lineage-ra-{key}-correct",
            reason="a narrower synthetic passage",
            evidence_anchors=(note_anchor(meeting_id, note_id, NOTE_BODY, passage="façade"),),
        )
    )
    commit(
        EndRecordAssociation(
            link_id=link,
            expected_revision=2,
            idempotency_key=f"lineage-ra-{key}-end",
            reason="synthetic end",
        )
    )
    assert {command.capability.value for command, _ in committed} == S1_WRITES
    return committed


def _without_replayed(answer: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in answer.items() if key != "replayed"}


def test_every_replayed_attested_write_is_denied_before_the_replay_lookup(
    runtime: LineageRuntime,
) -> None:
    """S3.1 section 10.1: a client re-sending any of the seven is a different writer.

    The membership and association asserts are pinned above; this extends the
    rule to `issues.project_links.add/end`, `issues.memberships.end` and
    `records.associations.correct/end`. A replay of exactly what the operator
    committed is `conflict` / `idempotency_conflict` for an ordinary remote client
    and for an unstamped local caller (S3.1 section 4.9, the writer bound into
    the digest), writes nothing, and the operator's own replay still answers
    the original. The two recorded writes (`issues.create`/`update`) keep their
    channel-blind replay, so an ordinary client's replay of them is a replay.
    """
    committed = _committed_writes(runtime, "attested")
    before = all_lineage_counts(runtime.engine)
    attested = 0
    for command, original in committed:
        capability = command.capability.value
        if capability in {"issues.create", "issues.update"}:
            again = runtime.ok(command, remote_client=REMOTE_CLIENT)
            assert again["replayed"] is True, capability
            assert _without_replayed(again) == _without_replayed(original), capability
            continue
        attested += 1
        for kwargs in ({"remote_client": REMOTE_CLIENT}, {}):
            # S3.1 section 10.1 (the operator directives of 2026-10-20 and
            # 2026-10-25; section 4.9): the open write binds its writer into
            # the digest, so a client re-sending the operator's request is
            # `conflict` / `idempotency_conflict`, never the stored answer.
            error = _granted_refused(runtime, command, kwargs)
            assert error["code"] == "conflict", (capability, kwargs)
            assert error["safe_details"] == ["idempotency_conflict"], (capability, kwargs)
        assert all_lineage_counts(runtime.engine) == before, capability
        again = runtime.ok(command, surface=OperatorSurface.HTTP_GATEWAY)
        assert again["replayed"] is True, capability
        assert _without_replayed(again) == _without_replayed(original), capability
    assert attested == 7
    assert all_lineage_counts(runtime.engine) == before


def test_switch_off_answers_unsupported_even_for_a_committed_replay(
    disposable_database: str,
) -> None:
    """Section 7.5: the switch is checked before the reservation, so no replay answers.

    Every one of the nine S1 lineage writes, committed while the plane was on, is
    resubmitted byte-for-byte with the plane off by the same local operator:
    each answers `unsupported` (never the stored replay), and no row moves.
    """
    on = LineageRuntime(disposable_database)
    off = LineageRuntime(disposable_database, lineage_enabled=False)
    try:
        committed = _committed_writes(on, "switch-off")
        before = all_lineage_counts(off.engine)
        for command, _original in committed:
            error = off.refused(command, surface=OperatorSurface.HTTP_GATEWAY)
            assert error["code"] == "unsupported", command.capability.value
        assert all_lineage_counts(off.engine) == before
        # Turning the plane back on changes no row: the original replays.
        command, original = committed[-1]
        again = on.ok(command, surface=OperatorSurface.HTTP_GATEWAY)
        assert again["replayed"] is True
        assert _without_replayed(again) == _without_replayed(original)
    finally:
        on.close()
        off.close()


def test_frame_and_project_link_writers_refuse_an_issue(runtime: LineageRuntime) -> None:
    """FR1-F04 (section 9): the internal frame and legacy Project-link writers refuse an Issue.

    Both are reached only through the internal `SituationService`; each answers
    an Issue exactly as an absent Situation, in the writer's own statement,
    while a context Situation is still admitted.
    """
    issue = runtime.issue("f04-internal")
    context = _context_situation(runtime, "f04-internal")
    project = runtime.project("f04-internal")
    for situation_id, admitted in ((issue, False), (context, True)):
        with runtime.engine.connect() as connection:
            transaction = connection.begin()
            try:
                enter = partial(
                    SqlFrameRepository(connection).enter_frame,
                    principal_id=PRINCIPAL,
                    situation_id=situation_id,
                    label="Synthetic frame",
                    evidence_refs=(),
                    alternatives=(),
                    obligations=(),
                    uncertainty=None,
                    next_authority=None,
                )
                link = partial(
                    SqlProjectRepository(connection).link_situation,
                    principal_id=PRINCIPAL,
                    project_id=project,
                    situation_id=situation_id,
                    evidence_kind=ClosureEvidenceKind.REVIEW_DECISION,
                    evidence_ref="rdec_lineagef04internal",
                )
                for write in (enter, link):
                    if admitted:
                        write()
                    else:
                        with pytest.raises(UnknownScopeError):
                            write()
            finally:
                transaction.rollback()
