"""Shared database harness for the record lineage S3.1 open-write tests (worker N2).

A helper module, not a test module: pytest does not collect it. It extends the
S3 read harness (`lineage_s3_read_harness.S3ReadRuntime`: a real
`ApplicationService` over PostgreSQL whose remote calls may carry an exact
grant set) with what the S3.1 write tests need:

* `client_grants(capability)` -- a granted remote client that sees every
  lineage family (S3 section 6.4, the S4 `project` family) and holds the native
  create grants a composite needs (S3.1 section 6.4), plus its own grant;
* `S31Runtime.client(...)` / `client_ok` / `client_refused` -- one call by such
  a remote client (`remote_interactive`, its OAuth client id recorded), and
  `local_ok` / `local_refused` -- an unstamped local caller (stdio MCP:
  `local_unattested`, no client id);
* `fact_rows(...)` -- the provenance columns of every fact row a write left, and
  `request_writer(...)` -- the writer columns of a request row;
* scene builders: a client membership, a client semantic link, an operator one.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Final

from sqlalchemy import Engine, text

from my_pa.application.commands import (
    AddIssueProjectLink,
    Command,
    CorrectRecordAssociation,
    CreateIssue,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.lineage.vocabulary import OPEN_LINEAGE_WRITE_CAPABILITIES
from tests.database.lineage_issue_harness import PRINCIPAL, REMOTE_CLIENT
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    capture,
    membership,
    note_anchor,
    originated_from,
)
from tests.database.lineage_s2_harness import (
    REVIEW_DECISION,
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
    reinstate,
    shortly_after,
)
from tests.database.lineage_s3_read_harness import READS, Grants, S3ReadRuntime, grant
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

__all__ = [
    "GATEWAY",
    "OTHER_CLIENT",
    "REMOTE_CLIENT",
    "OpenScene",
    "S31Runtime",
    "client_grants",
    "commitment_object",
    "completed_requests",
    "every_open_write",
    "fact_rows",
    "open_scene",
    "request_writer",
    "seed_completed_requests",
]

#: A second synthetic OAuth client of the same Principal.
OTHER_CLIENT: Final = "synthetic-lineage-other-client"

#: The family reads a fully visible remote client holds: the S3 section 6.4
#: reads and the S4 `project` family read (Project-link writes, S3.1 6.4).
_FAMILY_READS: Final = (*READS, "continuity.projects")

#: S3.1 section 6.4 step 2: the native create grants a composite needs.
_NATIVE_CREATES: Final[Grants] = frozenset(
    {
        (Capability.TASKS_CREATE, Purpose.TASK_AUTHORING),
        (Capability.COMMITMENTS_CREATE, Purpose.COMMITMENT_AUTHORING),
    }
)


def client_grants(capability: Capability, *, without: tuple[str, ...] = ()) -> Grants:
    """A remote client's grants for `capability`: its own, every family read, native creates.

    `without` drops the named capabilities' grants (a hidden family, a missing
    native create grant, or the write's own grant).
    """
    granted = grant(*_FAMILY_READS) | _NATIVE_CREATES | grant(capability.value)
    return frozenset(pair for pair in granted if pair[0].value not in without)


class S31Runtime(S3ReadRuntime):
    """`S3ReadRuntime` with remote and unstamped-local client calls."""

    def client(
        self,
        command: Command,
        *,
        client: str = REMOTE_CLIENT,
        grants: Grants | None = None,
        principal_id: str = PRINCIPAL,
    ) -> ResponseEnvelope:
        """One call by a granted remote client that sees every lineage family."""
        return self.invoke(
            command,
            principal_id=principal_id,
            remote_client=client,
            grants=client_grants(command.capability) if grants is None else grants,
        )

    def client_ok(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.client(command, **kwargs)
        assert envelope.error is None, (command.capability.value, envelope.error)
        dumped = envelope.to_canonical_dict()["result"]
        assert isinstance(dumped, dict)
        return dumped

    def client_refused(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.client(command, **kwargs)
        assert envelope.error is not None, command.capability.value
        error = envelope.to_canonical_dict()["error"]
        assert isinstance(error, dict)
        return error

    def local_ok(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """An unstamped local caller (stdio MCP): `local_unattested`, no client id."""
        return self.ok(command, **kwargs)

    def local_refused(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.refused(command, **kwargs)


#: The 4 fact tables and their identity column (S3.1 section 5.1).
_FACT_TABLES: Final = {
    "record_link_revisions": "link_id || ':' || revision_no",
    "issue_project_membership_events": "membership_event_id",
    "issue_responsibility_events": "handoff_id",
    "issue_responsibility_corrections": "correction_id",
}


def fact_rows(engine: Engine, table: str) -> dict[str, tuple[Any, ...]]:
    """Each row of a fact table: `(acceptance_basis, authority_class, decision_channel,
    asserting_client_id, user_directed_claim, source_capability)` by its identity."""
    identity = _FACT_TABLES[table]
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT {identity} AS identity, acceptance_basis, authority_class,"  # noqa: S608
                " decision_channel, asserting_client_id, user_directed_claim,"
                f" source_capability FROM knowledge.{table}"
            )
        ).all()
    return {
        str(row.identity): (
            row.acceptance_basis,
            row.authority_class,
            row.decision_channel,
            row.asserting_client_id,
            row.user_directed_claim,
            row.source_capability,
        )
        for row in rows
    }


def request_writer(engine: Engine, capability: str, idempotency_key: str) -> tuple[Any, ...]:
    """A request row's writer columns and completion: `(channel, client, completed)`."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT decision_channel, asserting_client_id, completed_at IS NOT NULL AS done"
                " FROM knowledge.lineage_write_requests"
                " WHERE capability = :capability AND idempotency_key = :key"
            ),
            {"capability": capability, "key": idempotency_key},
        ).one()
    return (row.decision_channel, row.asserting_client_id, row.done)


# --- the 14 open writes, in an order one caller admits (S3.1 section 1) ---------


def commitment_object(runtime: S31Runtime, key: str) -> dict[str, object]:
    """The native object of an `issues.work.create_commitment` (S2 shape)."""
    origin, _, _ = capture(runtime, f"{key}-native-origin")
    return {
        "counterparty_entity_id": seed_counterparty_entity(runtime.engine, PRINCIPAL),
        "direction": "owed_to_principal",
        "summary": f"Synthetic composite commitment {key}",
        "origin_evidence_ref": origin,
        "accepted_by_review_decision_id": REVIEW_DECISION,
    }


@dataclass(frozen=True, slots=True)
class OpenScene:
    """The native records and operator setup the 14 open writes of one caller name."""

    key: str
    issue: str
    project: str
    meeting: str
    note: str
    origin_commitment: str
    member_task: str
    handoff_commitment: str
    handoff_effective_at: str
    native_commitment: dict[str, object]


def open_scene(runtime: S31Runtime, key: str, *, operator: bool = False) -> OpenScene:
    """An Issue, a Project, a note, a Commitment with a passage source, a Task, and a
    Commitment the operator made an Issue member (a handoff names an active member).

    `operator` creates the Issue through the human channel too, so the scene
    leaves no client request row (the harness's `issue` is an unstamped call).
    """
    issue = (
        str(
            runtime.ok(
                CreateIssue(title=f"Synthetic issue {key}", idempotency_key=f"s31-scene-{key}"),
                surface=GATEWAY,
            )["issue"]["issue_id"]
        )
        if operator
        else runtime.issue(f"open-{key}")
    )
    project = runtime.project(f"open-{key}")
    meeting_id, note_id = runtime.note(f"open-{key}")
    origin_commitment = runtime.commitment(f"open-{key}-origin")
    member_task = runtime.task(f"open-{key}-member")
    handoff_commitment = runtime.commitment(f"open-{key}-handoff")
    runtime.member(issue, "commitment", handoff_commitment, f"open-{key}-handoff", "discussion")
    created = str(runtime.commitment_view(handoff_commitment)["created_at"])
    return OpenScene(
        key=key,
        issue=issue,
        project=project,
        meeting=meeting_id,
        note=note_id,
        origin_commitment=origin_commitment,
        member_task=member_task,
        handoff_commitment=handoff_commitment,
        handoff_effective_at=shortly_after(created, 10),
        native_commitment=commitment_object(runtime, f"open-{key}"),
    )


type Call = Callable[[Command], dict[str, Any]]


def every_open_write(
    scene: OpenScene, call: Call, *, user_directed: bool = False
) -> dict[str, dict[str, Any]]:
    """The 14 open writes through `call`, each on the facts the earlier ones wrote.

    Returns each capability's answer. `user_directed` sets the client's claim on
    every request.
    """
    key, meeting_id, note_id = scene.key, scene.meeting, scene.note
    origin = note_anchor(meeting_id, note_id, NOTE_BODY)
    answers: dict[str, dict[str, Any]] = {}

    def run(command: Command) -> dict[str, Any]:
        sent = replace(command, user_directed=True) if user_directed else command  # type: ignore[type-var]
        answer = call(sent)
        answers[command.capability.value] = answer
        return answer

    link = run(
        originated_from(
            "commitment",
            scene.origin_commitment,
            "meeting_note_version",
            note_id,
            f"open-{key}",
            (origin,),
        )
    )["association"]["link_id"]
    run(
        CorrectRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key=f"s31-open-{key}-correct",
            reason="A narrower synthetic passage.",
            evidence_anchors=(note_anchor(meeting_id, note_id, NOTE_BODY, passage="façade"),),
        )
    )
    run(contest(link, 2, f"open-{key}", (contradicts(meeting_id, note_id),)))
    run(reinstate(link, 3, f"open-{key}", (origin,)))
    run(
        EndRecordAssociation(
            link_id=link,
            expected_revision=4,
            idempotency_key=f"s31-open-{key}-end",
            reason="Synthetic end.",
        )
    )
    member = run(
        membership(scene.issue, "task", scene.member_task, f"open-{key}", role="reference")
    )["membership"]["link_id"]
    run(correct(member, 1, f"open-{key}", (resolution_anchor(meeting_id, note_id),)))
    run(
        EndIssueMembership(
            link_id=member,
            expected_revision=2,
            idempotency_key=f"s31-open-{key}-member-end",
            reason="Synthetic end.",
        )
    )
    run(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key=f"s31-open-{key}-link-add",
        )
    )
    run(
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=1,
            idempotency_key=f"s31-open-{key}-link-end",
            reason="Synthetic end.",
        )
    )
    event = run(
        handoff(
            scene.issue,
            scene.handoff_commitment,
            "counterparty",
            scene.handoff_effective_at,
            f"open-{key}",
            note_anchor(meeting_id, note_id, NOTE_BODY, role="handoff"),
        )
    )["handoff"]["handoff_id"]
    run(correct_handoff(event, "void", f"open-{key}", contradicts(meeting_id, note_id)))
    run(work_task(scene.issue, f"open-{key}"))
    run(work_commitment(scene.issue, f"open-{key}", scene.native_commitment))
    assert set(answers) == set(OPEN_LINEAGE_WRITE_CAPABILITIES)
    return answers


# --- the section 4.8 budgets ---------------------------------------------------------


def seed_completed_requests(
    engine: Engine,
    count: int,
    *,
    issue_id: str,
    channel: str,
    client: str | None,
    age: str = "10 minutes",
    prefix: str = "seed",
    principal_id: str = PRINCIPAL,
) -> None:
    """`count` completed `issues.create` request rows of one writer, `age` old.

    Synthetic bookkeeping rows naming one existing Issue's revision 1: the
    section 4.8 counts read request rows, so a budget is filled without `count`
    round trips.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.lineage_write_requests (principal_id, capability,"
                " idempotency_key, request_digest, created_at, completed_at, result_issue_id,"
                " result_issue_version, decision_channel, asserting_client_id)"
                " SELECT :principal, 'issues.create', :prefix || '-' || n, repeat('a', 64),"
                " now() - CAST(:age AS interval), now() - CAST(:age AS interval),"
                " :issue, 1, :channel, :client FROM generate_series(1, :count) AS n"
            ),
            {
                "principal": principal_id,
                "prefix": f"s31-{prefix}-{channel}-{client}",
                "age": age,
                "issue": issue_id,
                "channel": channel,
                "client": client,
                "count": count,
            },
        )


def completed_requests(
    engine: Engine, *, channel: str, client: str | None, principal_id: str = PRINCIPAL
) -> int:
    """The completed request rows of one writer bucket."""
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.lineage_write_requests"
                    " WHERE principal_id = :principal AND decision_channel = :channel"
                    " AND asserting_client_id IS NOT DISTINCT FROM :client"
                    " AND completed_at IS NOT NULL"
                ),
                {"principal": principal_id, "channel": channel, "client": client},
            ).scalar_one()
        )
