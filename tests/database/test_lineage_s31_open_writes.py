"""Record lineage S3.1 Part A: connected clients commit the open lineage writes (database).

S3.1 contract sections 4.1, 4.2, 4.4, 4.5, 4.9, 6.1, 6.2 and 7.1 against
PostgreSQL through `ApplicationService.invoke` (worker N2):

* every one of the 14 open writes is admitted for a remote client, a stdio or
  unstamped local caller and the operator, and every fact row it writes carries
  the server-derived provenance of its channel -- `client_identified` with the
  OAuth client id for a remote client, without one for a local client,
  `user_confirmed` with no client for the human channel;
* the client-declared `user_directed` flag is stored as an unverified claim
  that upgrades nothing; the human channel may not send it; no payload can name
  provenance;
* replay binds the writer: a client's own retry replays, another writer's
  reuse of a key is `conflict` / `idempotency_conflict`, and an operator key
  recorded before S3.1 still replays for the operator;
* an active identity answers `created: false` and keeps its provenance;
* clients revise each other's never-accepted facts within the Principal, may
  contest an accepted semantic link once, and can never end, correct or
  reinstate a fact the human channel has accepted at any revision;
* the residuals R31-F11 d and e are pinned; another Principal's subjects answer
  like absent ones; the switch answers `unsupported` first; Issue metadata
  writes keep their S1 rules.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command as alembic
from alembic.config import Config
from sqlalchemy import text

from my_pa.adapters.normalization import normalize
from my_pa.application import issues as issues_module
from my_pa.application import record_lineage as record_lineage_module
from my_pa.application.commands import (
    AddIssueProjectLink,
    ConfirmIssueMembership,
    ConfirmIssueProjectLink,
    ConfirmRecordAssociation,
    CorrectRecordAssociation,
    CreateIssue,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
    UpdateIssue,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.issue_handoffs import handoff_document
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.lineage.canonical import request_digest
from my_pa.domain.lineage.vocabulary import OPEN_LINEAGE_WRITE_CAPABILITIES
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    all_lineage_counts,
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
    OTHER_CLIENT,
    REMOTE_CLIENT,
    OpenScene,
    S31Runtime,
    every_open_write,
    fact_rows,
    open_scene,
    request_writer,
)

pytestmark = pytest.mark.database

_FACT_TABLES: Final = (
    "record_link_revisions",
    "issue_project_membership_events",
    "issue_responsibility_events",
    "issue_responsibility_corrections",
)
_ROOT: Final = Path(__file__).resolve().parents[2]
_S4_HEAD: Final = "c5260943d933"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _facts(runtime: S31Runtime) -> dict[str, dict[str, tuple[Any, ...]]]:
    return {name: fact_rows(runtime.engine, name) for name in _FACT_TABLES}


def _new_rows(
    runtime: S31Runtime, before: dict[str, dict[str, tuple[Any, ...]]]
) -> list[tuple[Any, ...]]:
    return [
        row
        for name in _FACT_TABLES
        for identity, row in fact_rows(runtime.engine, name).items()
        if identity not in before[name]
    ]


def _keys(answers: dict[str, dict[str, Any]], scene: OpenScene) -> dict[str, str]:
    """Each open write's idempotency key, as `every_open_write` named it."""
    key = scene.key
    return {
        "records.associations.assert": f"lineage-assoc-open-{key}",
        "records.associations.correct": f"s31-open-{key}-correct",
        "records.associations.contest": f"s3-contest-open-{key}",
        "records.associations.reinstate": f"s3-reinstate-open-{key}",
        "records.associations.end": f"s31-open-{key}-end",
        "issues.memberships.add": f"lineage-member-open-{key}",
        "issues.memberships.correct": f"s2-correct-open-{key}",
        "issues.memberships.end": f"s31-open-{key}-member-end",
        "issues.project_links.add": f"s31-open-{key}-link-add",
        "issues.project_links.end": f"s31-open-{key}-link-end",
        "issues.handoffs.record": f"s2-handoff-open-{key}",
        "issues.handoffs.correct": f"s3-handoff-correct-open-{key}",
        "issues.work.create_task": f"s2-work-task-open-{key}",
        "issues.work.create_commitment": f"s2-work-commitment-open-{key}",
    }


def _assert_every_open_write(
    runtime: S31Runtime,
    call: Any,  # noqa: ANN401
    key: str,
    expected: tuple[Any, ...],
    *,
    user_directed: bool = False,
) -> dict[str, dict[str, Any]]:
    scene = open_scene(runtime, key)
    before = _facts(runtime)
    answers = every_open_write(scene, call, user_directed=user_directed)
    rows = _new_rows(runtime, before)
    assert {row[5] for row in rows} == set(OPEN_LINEAGE_WRITE_CAPABILITIES)
    for row in rows:
        assert row[:5] == expected, row
    for capability, idempotency_key in _keys(answers, scene).items():
        assert request_writer(runtime.engine, capability, idempotency_key) == (
            expected[2],
            expected[3],
            True,
        ), capability
        # Section 6.4: every open-write answer says whether anything was withheld.
        assert answers[capability]["restricted"] is False, capability
    return answers


# ---- the three channels (sections 4.1, 6.1) ---------------------------------------


def test_a_remote_client_commits_every_open_lineage_write(runtime: S31Runtime) -> None:
    _assert_every_open_write(
        runtime,
        runtime.client_ok,
        "remote",
        ("client_identified", "ordinary_reviewer", "remote_interactive", REMOTE_CLIENT, False),
    )


def test_a_local_unattested_caller_commits_as_client_identified_without_a_client_id(
    runtime: S31Runtime,
) -> None:
    _assert_every_open_write(
        runtime,
        runtime.local_ok,
        "local",
        ("client_identified", "ordinary_reviewer", "local_unattested", None, False),
    )


def test_an_operator_write_still_records_user_confirmed_and_no_client(
    runtime: S31Runtime,
) -> None:
    _assert_every_open_write(
        runtime,
        lambda command: runtime.ok(command, surface=GATEWAY),
        "operator",
        ("user_confirmed", "local_operator", "local_web", None, False),
    )
    # The CLI is the other human channel: `local_cli`, no client.
    before = _facts(runtime)
    issue = runtime.issue("operator-cli")
    task_id = runtime.task("operator-cli")
    runtime.ok(membership(issue, "task", task_id, "operator-cli"), surface=OperatorSurface.CLI)
    (row,) = _new_rows(runtime, before)
    assert row[:5] == ("user_confirmed", "local_operator", "local_cli", None, False)


# ---- the claim (sections 4.1, 4.9) -------------------------------------------------


def test_user_directed_is_stored_as_an_unverified_claim(runtime: S31Runtime) -> None:
    _assert_every_open_write(
        runtime,
        runtime.client_ok,
        "claimed",
        ("client_identified", "ordinary_reviewer", "remote_interactive", REMOTE_CLIENT, True),
        user_directed=True,
    )
    # The claim is part of the request: the same key without it is another request.
    scene = open_scene(runtime, "claimed-key")
    issue_link = AddIssueProjectLink(
        issue_id=scene.issue,
        project_id=scene.project,
        expected_membership_revision=0,
        idempotency_key="s31-claimed-key-link",
        user_directed=True,
    )
    runtime.client_ok(issue_link)
    error = runtime.client_refused(replace(issue_link, user_directed=False))
    assert (error["code"], error["safe_details"]) == ("conflict", ["idempotency_conflict"])
    # A local client may claim it too; still `client_identified`.
    before = _facts(runtime)
    task_id = runtime.task("claimed-local")
    runtime.local_ok(
        replace(membership(scene.issue, "task", task_id, "claimed-local"), user_directed=True)
    )
    (row,) = _new_rows(runtime, before)
    assert row[:5] == ("client_identified", "ordinary_reviewer", "local_unattested", None, True)


def test_the_operator_cannot_send_a_user_directed_claim(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "operator-claim")
    before = all_lineage_counts(runtime.engine)
    for surface in (OperatorSurface.HTTP_GATEWAY, OperatorSurface.CLI):
        for command in _first_writes(scene):
            error = runtime.refused(replace(command, user_directed=True), surface=surface)
            assert (error["code"], error["safe_details"]) == (
                "invalid_request",
                ["user_directed"],
            ), (surface, command.capability.value)
    assert all_lineage_counts(runtime.engine) == before


def _first_writes(scene: OpenScene) -> tuple[Any, ...]:
    """Open writes that each stand alone on a fresh scene."""
    return (
        originated_from(
            "commitment",
            scene.origin_commitment,
            "meeting_note_version",
            scene.note,
            f"first-{scene.key}",
            (note_anchor(scene.meeting, scene.note, NOTE_BODY),),
        ),
        membership(scene.issue, "task", scene.member_task, f"first-{scene.key}"),
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key=f"s31-first-{scene.key}-link",
        ),
        handoff(
            scene.issue,
            scene.handoff_commitment,
            "counterparty",
            scene.handoff_effective_at,
            f"first-{scene.key}",
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff"),
        ),
        work_task(scene.issue, f"first-{scene.key}"),
    )


def test_no_payload_can_supply_provenance(runtime: S31Runtime) -> None:
    """Section 4.1: provenance is server-derived; a payload naming any of it is refused."""
    for name in sorted(OPEN_LINEAGE_WRITE_CAPABILITIES):
        for field in (
            "acceptance_basis",
            "authority_class",
            "decision_channel",
            "asserting_client_id",
            "user_directed_claim",
        ):
            arguments = {
                "request_id": "req-lineage-s31-db",
                "purpose": sorted(permitted_purposes(Capability(name)))[0].value,
                "principal_id": PRINCIPAL,
                "requested_at": "2026-10-25T12:00:00Z",
                "payload": {field: "user_confirmed"},
            }
            with pytest.raises(InvalidRequestError):
                normalize(name, arguments)
    # Each client's rows carry its own authenticated id, whatever it sends.
    scene = open_scene(runtime, "ids")
    before = _facts(runtime)
    first, second = _first_writes(scene)[:2]
    runtime.client_ok(first, client=REMOTE_CLIENT)
    runtime.client_ok(second, client=OTHER_CLIENT)
    rows = sorted(_new_rows(runtime, before), key=lambda row: row[5])
    assert [(row[3], row[5]) for row in rows] == [
        (OTHER_CLIENT, "issues.memberships.add"),
        (REMOTE_CLIENT, "records.associations.assert"),
    ]


# ---- replay binds the writer (section 4.9) -----------------------------------------


def test_a_client_replay_of_its_own_write_is_a_replay(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "own-replay")
    for command in _first_writes(scene):
        original = runtime.client_ok(command)
        before = all_lineage_counts(runtime.engine)
        again = runtime.client_ok(command)
        assert again["replayed"] is True, command.capability.value
        assert {k: v for k, v in again.items() if k != "replayed"} == {
            k: v for k, v in original.items() if k != "replayed"
        }
        assert all_lineage_counts(runtime.engine) == before


def _conflict(error: dict[str, Any]) -> bool:
    return (error["code"], error.get("safe_details")) == ("conflict", ["idempotency_conflict"])


def test_a_client_reusing_an_operator_key_is_conflict_and_writes_nothing(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "operator-key")
    for command in _first_writes(scene):
        runtime.ok(command, surface=GATEWAY)
        before = all_lineage_counts(runtime.engine)
        error = runtime.client_refused(command)
        assert _conflict(error), command.capability.value
        assert "result" not in error
        assert all_lineage_counts(runtime.engine) == before


def test_the_operator_reusing_a_client_key_is_conflict(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "client-key")
    for command in _first_writes(scene):
        runtime.client_ok(command)
        before = all_lineage_counts(runtime.engine)
        assert _conflict(runtime.refused(command, surface=GATEWAY)), command.capability.value
        assert all_lineage_counts(runtime.engine) == before


def test_a_client_reusing_another_clients_key_is_conflict(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "other-key")
    for command in _first_writes(scene):
        runtime.client_ok(command, client=REMOTE_CLIENT)
        before = all_lineage_counts(runtime.engine)
        assert _conflict(runtime.client_refused(command, client=OTHER_CLIENT))
        # The stdio caller is another writer too.
        assert _conflict(runtime.local_refused(command))
        assert all_lineage_counts(runtime.engine) == before


def _alembic() -> Config:
    return Config(str(_ROOT / "alembic.ini"))


def _s4_digest(command: Any) -> str:  # noqa: ANN401
    """The S1-S4 request digest of an operator request: no writer, no claim."""
    name = command.capability.value
    if name == "records.associations.assert":
        document = record_lineage_module._assert_document(command.lineage_request())
    elif name == "issues.memberships.add":
        document = record_lineage_module._membership_add_document(command.lineage_request())
    elif name == "issues.project_links.add":
        document = issues_module._link_add_document(command.issue_request())
    elif name == "issues.handoffs.record":
        document = handoff_document(command.handoff_request())
    else:
        document = command.work_request().digest_document()
    return request_digest(name, PRINCIPAL, document)


def _stored_digest(runtime: S31Runtime, command: Any) -> str:  # noqa: ANN401
    with runtime.engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT request_digest FROM knowledge.lineage_write_requests"
                    " WHERE capability = :capability AND idempotency_key = :key"
                ),
                {"capability": command.capability.value, "key": command.idempotency_key},
            ).scalar_one()
        )


def test_an_operator_replay_of_a_pre_s31_key_answers_the_original(runtime: S31Runtime) -> None:
    """Section 4.9: a key recorded at `c5260943d933` replays byte-identically for the operator.

    The operator's requests are committed, the schema goes back to the S4 head
    (dropping the S3.1 writer columns, so the rows are exactly the pre-S3.1
    shape) and up again, and the same requests are re-sent.
    """
    scene = open_scene(runtime, "pre-s31", operator=True)
    commands = _first_writes(scene)
    originals = [runtime.ok(command, surface=GATEWAY) for command in commands]
    # The human channel's digest document is exactly the S1-S4 one.
    for command in commands:
        assert _stored_digest(runtime, command) == _s4_digest(command), command.capability.value
    runtime.engine.dispose()
    runtime.audit_engine.dispose()
    alembic.downgrade(_alembic(), _S4_HEAD)
    alembic.upgrade(_alembic(), "head")
    with runtime.engine.connect() as connection:
        writers = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.lineage_write_requests"
                " WHERE decision_channel IS NOT NULL OR asserting_client_id IS NOT NULL"
            )
        ).scalar_one()
    assert writers == 0
    before = all_lineage_counts(runtime.engine)
    for command, original in zip(commands, originals, strict=True):
        again = runtime.ok(command, surface=GATEWAY)
        assert again["replayed"] is True, command.capability.value
        assert {k: v for k, v in again.items() if k != "replayed"} == {
            k: v for k, v in original.items() if k != "replayed"
        }, command.capability.value
        # A client never receives the operator's answer.
        assert _conflict(runtime.client_refused(command)), command.capability.value
    assert all_lineage_counts(runtime.engine) == before


# ---- identity (section 4.5) --------------------------------------------------------


def test_an_active_identity_answers_created_false_and_never_changes_its_provenance(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "identity")
    meeting_id, note_id = scene.meeting, scene.note
    for first, second, basis in (
        (
            runtime.client_ok,
            lambda command: runtime.ok(command, surface=GATEWAY),
            "client_identified",
        ),
        (lambda command: runtime.ok(command, surface=GATEWAY), runtime.client_ok, "user_confirmed"),
    ):
        task_a = runtime.task(f"identity-{basis}-a")
        task_b = runtime.task(f"identity-{basis}-b")

        blocks = [
            assertion(
                "blocks",
                ("task", task_a),
                ("task", task_b),
                f"identity-{basis}-{key}",
                (corroborates(meeting_id, note_id),),
            )
            for key in ("first", "second")
        ]
        created = first(blocks[0])
        assert created["created"] is True
        before = _facts(runtime)
        answered = second(blocks[1])
        assert answered["created"] is False
        assert answered["association"] == created["association"]
        assert answered["association"]["acceptance_basis"] == basis
        assert answered["association"]["revision_no"] == 1
        assert _new_rows(runtime, before) == []


# ---- revisions between clients and accepted lineage (section 4.4) ------------------


def _client_link(runtime: S31Runtime, scene: OpenScene, key: str, **kwargs: Any) -> str:  # noqa: ANN401
    task_a = runtime.task(f"{key}-a")
    task_b = runtime.task(f"{key}-b")
    written = runtime.client_ok(
        assertion(
            "blocks",
            ("task", task_a),
            ("task", task_b),
            key,
            (corroborates(scene.meeting, scene.note),),
            context=scene.issue,
        ),
        **kwargs,
    )
    return str(written["association"]["link_id"])


def _operator_link(runtime: S31Runtime, scene: OpenScene, key: str) -> str:
    task_a = runtime.task(f"{key}-a")
    task_b = runtime.task(f"{key}-b")
    written = runtime.ok(
        assertion(
            "blocks",
            ("task", task_a),
            ("task", task_b),
            key,
            (corroborates(scene.meeting, scene.note),),
            context=scene.issue,
        ),
        surface=GATEWAY,
    )
    return str(written["association"]["link_id"])


def _correct_link(link: str, revision: int, key: str, scene: OpenScene) -> CorrectRecordAssociation:
    return CorrectRecordAssociation(
        link_id=link,
        expected_revision=revision,
        idempotency_key=f"s31-correct-{key}",
        reason="A second source.",
        evidence_anchors=(
            corroborates(scene.meeting, scene.note),
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="corroborates", passage="pour"),
        ),
    )


def _end_link(link: str, revision: int, key: str) -> EndRecordAssociation:
    return EndRecordAssociation(
        link_id=link,
        expected_revision=revision,
        idempotency_key=f"s31-end-{key}",
        reason="Synthetic end.",
    )


def test_clients_end_correct_and_contest_each_others_links_within_the_principal(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "each-other")
    link = _client_link(runtime, scene, "each-other", client=REMOTE_CLIENT)
    runtime.client_ok(_correct_link(link, 1, "each-other", scene), client=OTHER_CLIENT)
    runtime.client_ok(
        contest(link, 2, "each-other", (contradicts(scene.meeting, scene.note),)),
        client=OTHER_CLIENT,
    )
    runtime.local_ok(reinstate(link, 3, "each-other", (corroborates(scene.meeting, scene.note),)))
    ended = runtime.client_ok(_end_link(link, 4, "each-other"), client=REMOTE_CLIENT)
    assert ended["association"]["lifecycle_state"] == "ended"
    assert ended["association"]["acceptance_basis"] == "client_identified"
    # A client membership, ended by another client.
    task_id = runtime.task("each-other-member")
    member = runtime.client_ok(
        membership(scene.issue, "task", task_id, "each-other"), client=REMOTE_CLIENT
    )["membership"]["link_id"]
    runtime.client_ok(
        EndIssueMembership(
            link_id=member,
            expected_revision=1,
            idempotency_key="s31-each-other-member-end",
            reason="Synthetic end.",
        ),
        client=OTHER_CLIENT,
    )


def test_a_client_composite_writes_client_identified_links(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "composite")
    before = _facts(runtime)
    written = runtime.client_ok(
        work_task(
            scene.issue,
            "composite",
            intents=(
                {
                    "relation_type": "created_to_resolve",
                    "to_record": {"family": "situation", "record_id": scene.issue},
                    "evidence_anchors": [],
                    "purpose": "Close the synthetic gap.",
                },
            ),
        )
    )
    assert written["membership"]["acceptance_basis"] == "client_identified"
    assert [view["acceptance_basis"] for view in written["associations"]] == ["client_identified"]
    rows = _new_rows(runtime, before)
    assert len(rows) == 2
    for row in rows:
        assert row == (
            "client_identified",
            "ordinary_reviewer",
            "remote_interactive",
            REMOTE_CLIENT,
            False,
            "issues.work.create_task",
        )


def _denied(error: dict[str, Any]) -> bool:
    return error["code"] == "denied" and not error.get("safe_details")


def test_a_client_cannot_end_or_correct_accepted_lineage(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "accepted")
    link = _operator_link(runtime, scene, "accepted-link")
    contested = _operator_link(runtime, scene, "accepted-contested")
    runtime.ok(
        contest(contested, 1, "accepted-operator", (contradicts(scene.meeting, scene.note),)),
        surface=GATEWAY,
    )
    task_id = runtime.task("accepted-member")
    member = runtime.member(scene.issue, "task", task_id, "accepted-member", "reference")
    runtime.ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-accepted-link-add",
        ),
        surface=GATEWAY,
    )
    other_project = runtime.project("accepted-ended")
    runtime.ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=other_project,
            expected_membership_revision=0,
            idempotency_key="s31-accepted-ended-add",
        ),
        surface=GATEWAY,
    )
    runtime.ok(
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=other_project,
            expected_membership_revision=1,
            idempotency_key="s31-accepted-ended-end",
            reason="Synthetic end.",
        ),
        surface=GATEWAY,
    )
    commands = (
        _end_link(link, 1, "accepted"),
        _correct_link(link, 1, "accepted", scene),
        reinstate(contested, 2, "accepted", (corroborates(scene.meeting, scene.note),)),
        EndIssueMembership(
            link_id=member,
            expected_revision=1,
            idempotency_key="s31-accepted-member-end",
            reason="Synthetic end.",
        ),
        correct(member, 1, "accepted", (resolution_anchor(scene.meeting, scene.note),)),
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=1,
            idempotency_key="s31-accepted-link-end",
            reason="Synthetic end.",
        ),
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=other_project,
            expected_membership_revision=2,
            idempotency_key="s31-accepted-reinstating-add",
        ),
    )
    before = all_lineage_counts(runtime.engine)
    for command in commands:
        assert _denied(runtime.client_refused(command)), command.capability.value
        assert _denied(runtime.local_refused(command)), command.capability.value
    assert all_lineage_counts(runtime.engine) == before
    # The human channel may write them (one revision of each fact).
    for command in (commands[1], *commands[2:3], *commands[4:]):
        runtime.ok(command, surface=GATEWAY)


def test_a_client_may_contest_an_accepted_semantic_link(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "contest-accepted")
    link = _operator_link(runtime, scene, "contest-accepted")
    written = runtime.client_ok(
        contest(link, 1, "contest-accepted", (contradicts(scene.meeting, scene.note),))
    )
    association = written["association"]
    assert (association["lifecycle_state"], association["acceptance_basis"]) == (
        "contested",
        "client_identified",
    )


def test_a_client_cannot_end_or_reinstate_its_own_contest_of_accepted_lineage(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "own-contest")
    link = _operator_link(runtime, scene, "own-contest")
    runtime.client_ok(contest(link, 1, "own-contest", (contradicts(scene.meeting, scene.note),)))
    before = all_lineage_counts(runtime.engine)
    # After the 1 contest only the human channel writes the link.
    assert _denied(runtime.client_refused(_end_link(link, 2, "own-contest")))
    assert _denied(
        runtime.client_refused(
            reinstate(link, 2, "own-contest", (corroborates(scene.meeting, scene.note),))
        )
    )
    assert all_lineage_counts(runtime.engine) == before
    # The operator reinstates the client's contest; a client correction is
    # still a revision of accepted lineage.
    runtime.ok(
        reinstate(link, 2, "own-contest-operator", (corroborates(scene.meeting, scene.note),)),
        surface=GATEWAY,
    )
    assert _denied(runtime.client_refused(_correct_link(link, 3, "own-contest", scene)))
    assert all_lineage_counts(runtime.engine)["record_link_revisions"] == (
        before["record_link_revisions"] + 1
    )


def test_a_client_cannot_revise_a_confirmed_client_fact(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "confirmed")
    link = _client_link(runtime, scene, "confirmed")
    runtime.ok(
        ConfirmRecordAssociation(
            link_id=link,
            expected_revision=1,
            idempotency_key="s31-confirmed-confirm",
            reason="Checked against the source.",
        ),
        surface=GATEWAY,
    )
    task_id = runtime.task("confirmed-member")
    member = runtime.client_ok(membership(scene.issue, "task", task_id, "confirmed"))["membership"][
        "link_id"
    ]
    runtime.ok(
        ConfirmIssueMembership(
            link_id=member,
            expected_revision=1,
            idempotency_key="s31-confirmed-member-confirm",
            reason="Checked.",
        ),
        surface=GATEWAY,
    )
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-confirmed-link-add",
        )
    )
    runtime.ok(
        ConfirmIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=1,
            idempotency_key="s31-confirmed-link-confirm",
            reason="Checked.",
        ),
        surface=GATEWAY,
    )
    before = all_lineage_counts(runtime.engine)
    for command in (
        _end_link(link, 2, "confirmed"),
        _correct_link(link, 2, "confirmed", scene),
        EndIssueMembership(
            link_id=member,
            expected_revision=2,
            idempotency_key="s31-confirmed-member-end",
            reason="Synthetic end.",
        ),
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=2,
            idempotency_key="s31-confirmed-link-end",
            reason="Synthetic end.",
        ),
    ):
        assert _denied(runtime.client_refused(command)), command.capability.value
    assert all_lineage_counts(runtime.engine) == before
    # The 1 contest exception still holds for a confirmed semantic link; after
    # it the head is the client's, yet the link stays accepted (its history).
    runtime.client_ok(contest(link, 2, "confirmed", (contradicts(scene.meeting, scene.note),)))
    assert _denied(runtime.client_refused(_end_link(link, 3, "confirmed-after-contest")))


def test_a_client_cannot_void_or_retime_a_human_channel_handoff(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "handoff-accepted")
    anchor = note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff")
    event = runtime.ok(
        handoff(
            scene.issue,
            scene.handoff_commitment,
            "counterparty",
            scene.handoff_effective_at,
            "handoff-accepted",
            anchor,
        ),
        surface=GATEWAY,
    )["handoff"]
    before = all_lineage_counts(runtime.engine)
    void = correct_handoff(
        event["handoff_id"], "void", "handoff-accepted", contradicts(scene.meeting, scene.note)
    )
    retime = correct_handoff(
        event["handoff_id"],
        "retime",
        "handoff-accepted-retime",
        anchor,
        effective_at=scene.handoff_effective_at,
    )
    for command in (void, retime):
        assert _denied(runtime.client_refused(command)), command.action
        assert _denied(runtime.local_refused(command)), command.action
    assert all_lineage_counts(runtime.engine) == before
    # A client's own handoff the operator corrected is accepted too.
    second = open_scene(runtime, "handoff-corrected")
    client_event = runtime.client_ok(
        handoff(
            second.issue,
            second.handoff_commitment,
            "counterparty",
            second.handoff_effective_at,
            "handoff-corrected",
            note_anchor(second.meeting, second.note, NOTE_BODY, role="handoff"),
        )
    )["handoff"]
    runtime.ok(
        correct_handoff(
            client_event["handoff_id"],
            "retime",
            "handoff-corrected-operator",
            note_anchor(second.meeting, second.note, NOTE_BODY, role="handoff"),
            effective_at=second.handoff_effective_at,
        ),
        surface=GATEWAY,
    )
    assert _denied(
        runtime.client_refused(
            correct_handoff(
                client_event["handoff_id"],
                "void",
                "handoff-corrected-client",
                contradicts(second.meeting, second.note),
            )
        )
    )


def test_clients_may_revise_client_identified_facts(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "revise-client")
    link = _client_link(runtime, scene, "revise-client")
    runtime.client_ok(_correct_link(link, 1, "revise-client", scene), client=OTHER_CLIENT)
    runtime.client_ok(_end_link(link, 2, "revise-client"))
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key="s31-revise-client-add",
        )
    )
    runtime.local_ok(
        EndIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=1,
            idempotency_key="s31-revise-client-end",
            reason="Synthetic end.",
        )
    )
    runtime.client_ok(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=2,
            idempotency_key="s31-revise-client-reinstate",
        ),
        client=OTHER_CLIENT,
    )
    event = runtime.client_ok(
        handoff(
            scene.issue,
            scene.handoff_commitment,
            "counterparty",
            scene.handoff_effective_at,
            "revise-client",
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff"),
        )
    )["handoff"]
    voided = runtime.client_ok(
        correct_handoff(
            event["handoff_id"], "void", "revise-client", contradicts(scene.meeting, scene.note)
        ),
        client=OTHER_CLIENT,
    )
    assert voided["handoff"]["voided"] is True


# ---- residuals R31-F11 d and e ----------------------------------------------------


def test_a_remote_byte_identical_reassert_after_an_end_replays_the_old_answer(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "reassert")
    task_a = runtime.task("reassert-a")
    task_b = runtime.task("reassert-b")
    command = assertion(
        "blocks",
        ("task", task_a),
        ("task", task_b),
        "reassert",
        (corroborates(scene.meeting, scene.note),),
    )
    original = runtime.client_ok(command)
    runtime.client_ok(_end_link(original["association"]["link_id"], 1, "reassert"))
    before = all_lineage_counts(runtime.engine)
    again = runtime.client_ok(command)
    # The derived key names the earlier request: its stored answer, no new root.
    assert again["replayed"] is True
    assert again["association"] == original["association"]
    assert all_lineage_counts(runtime.engine) == before


def test_a_local_caller_reusing_an_operator_key_gets_conflict(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "local-key")
    for command in _first_writes(scene):
        runtime.ok(command, surface=GATEWAY)
        assert _conflict(runtime.local_refused(command)), command.capability.value


# ---- isolation, the switch and the Issue metadata writes ---------------------------


def test_cross_principal_open_writes_answer_like_absent(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "foreign")
    link = _client_link(runtime, scene, "foreign")
    absent_link = "irl_lineages31absent0001"
    absent_issue = "sit_lineages31absent0001"
    for subject_link, subject_issue in ((link, scene.issue), (absent_link, absent_issue)):
        answers = [
            runtime.client_refused(command, principal_id=OTHER_PRINCIPAL)
            for command in (
                _end_link(subject_link, 1, f"foreign-{subject_link}"),
                AddIssueProjectLink(
                    issue_id=subject_issue,
                    project_id=runtime.project(
                        f"foreign-{subject_link}", principal_id=OTHER_PRINCIPAL
                    ),
                    expected_membership_revision=0,
                    idempotency_key=f"s31-foreign-{subject_link}",
                ),
            )
        ]
        assert [(error["code"], error["safe_details"]) for error in answers] == [
            ("not_found", ["link_id"]),
            ("not_found", ["issue_id"]),
        ]


def test_switch_off_answers_unsupported_for_every_open_write(disposable_database: str) -> None:
    on = S31Runtime(disposable_database)
    try:
        scene = open_scene(on, "switch")
        commands = _first_writes(scene)
    finally:
        on.close()
    off = S31Runtime(disposable_database, lineage_enabled=False)
    try:
        before = all_lineage_counts(off.engine)
        for command in commands:
            for error in (
                off.client_refused(command),
                off.local_refused(command),
                off.refused(command, surface=GATEWAY),
            ):
                assert error["code"] == "unsupported", command.capability.value
        assert all_lineage_counts(off.engine) == before
    finally:
        off.close()


def test_issue_metadata_writes_keep_their_s1_rules(runtime: S31Runtime) -> None:
    """Sections 4.8, 12 (D-06, D-13): `issues.create`/`update` stay open and channel-blind.

    A client's create and update record the S1 class and channel on the Issue
    revision and the writer on the request row; a client's replay of the
    operator's create is a replay; a closed Issue's correction stays attested.
    """
    created = runtime.client_ok(CreateIssue(title="Client issue", idempotency_key="s31-meta"))
    issue = created["issue"]["issue_id"]
    runtime.client_ok(
        UpdateIssue(
            issue_id=issue, expected_version=1, idempotency_key="s31-meta-update", title="Retitled"
        )
    )
    assert request_writer(runtime.engine, "issues.create", "s31-meta") == (
        "remote_interactive",
        REMOTE_CLIENT,
        True,
    )
    with runtime.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT authority_class, decision_channel FROM knowledge.issue_revisions"
                " WHERE issue_id = :issue ORDER BY version"
            ),
            {"issue": issue},
        ).all()
    assert [tuple(row) for row in rows] == [("ordinary_reviewer", "remote_interactive")] * 2
    operator = CreateIssue(title="Operator issue", idempotency_key="s31-meta-operator")
    original = runtime.ok(operator, surface=GATEWAY)
    again = runtime.client_ok(operator)
    assert again["replayed"] is True and again["issue"] == original["issue"]
    # The closed-Issue correction stays attested.
    scene = open_scene(runtime, "meta-closed")
    _, _, anchor = runtime.evidence_source("meta-closed")
    runtime.ok(close(scene.issue, 1, "meta-closed", (anchor,)), surface=GATEWAY)
    error = runtime.client_refused(
        UpdateIssue(
            issue_id=scene.issue,
            expected_version=2,
            idempotency_key="s31-meta-closed-update",
            title="Corrected",
        )
    )
    assert error["code"] == "denied"
