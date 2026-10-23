"""AT-023 (S3, database): attested S3 writes, the switches and foreign subjects.

S3 contract sections 6.1, 7.5 and 7.7 against PostgreSQL, through
`ApplicationService.invoke`. Worker L2's rows (the writes): for
`records.associations.contest`, `records.associations.reinstate` and
`issues.handoffs.correct` -- and, for the denial, `records.backfill.plan`:

* an ordinary remote client (and an unstamped local caller) is `denied` every
  S3 write before any row is written and before any commit mark is taken;
* a byte-identical replay of an operator's committed S3 write by such a caller
  is `denied` before the replay lookup -- it never sees the stored answer;
* with `lineage_enabled` off every one of the 8 S3 capabilities answers
  `unsupported`, including a replay of a write committed while it was on; with
  lineage on and the backfill sub-switch off, both backfill capabilities do;
* a foreign link or handoff answers exactly like an absent one.

Worker L5's rows (the backfill): an enumeration and a classifying batch replay
byte for byte for the operator and are `denied` to anyone else, and another
Principal's run answers `records.backfill.plan` and `records.backfill.report`
exactly like an absent one.

Worker L3's read rows (with worker L4's `issues.timeline` among the reads): a
remote lineage read without a grant on its own capability is `unsupported` (S3
section 6.1, R3-F13), and another Principal's reads of this Principal's
subjects answer exactly like reads of absent ones. Every identity here is
synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Final

import pytest

from my_pa.application.commands import (
    Command,
    ListIssueHandoffs,
    ListIssues,
    ListMeetingNoteVersions,
    PlanLineageBackfill,
    ReadIssue,
    ReadIssueClosureReadiness,
    ReadIssueHistory,
    ReadIssueTimeline,
    ReadMeetingNoteVersion,
    ReadRecordAssociationHistory,
    ReadRecordLineage,
    ReportLineageBackfill,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.lineage.vocabulary import LINEAGE_BACKFILL_CAPABILITIES
from my_pa.domain.source.registry import issue_identifier
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL, REMOTE_CLIENT, WHEN
from tests.database.lineage_s2_harness import handoff
from tests.database.lineage_s3_harness import (
    GATEWAY,
    S3Runtime,
    all_s3_counts,
    blocks_scene,
    contest,
    contradicts,
    correct_handoff,
    reinstate,
    shortly_after,
)

pytestmark = pytest.mark.database

#: The S3 writes this package builds, in the order one scene admits them.
_WRITES: Final = ("contest", "reinstate", "correct")
_ABSENT_RUN: Final = "lbfr_lineages3absent0001"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3Runtime]:
    composed = S3Runtime(disposable_database, lineage_backfill_enabled=True)
    try:
        yield composed
    finally:
        composed.close()


def _code(runtime: S3Runtime, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


def _scene(runtime: S3Runtime, key: str) -> dict[str, Any]:
    """A `blocks` link to contest and reinstate, and a handoff to void."""
    scene = blocks_scene(runtime, key)
    commitment = runtime.commitment(key)
    runtime.member(scene["issue"], "commitment", commitment, key, "discussion")
    created = str(runtime.commitment_view(commitment)["created_at"])
    event = runtime.ok(
        handoff(
            scene["issue"],
            commitment,
            "counterparty",
            shortly_after(created, 10),
            key,
            runtime.handoff_anchor(f"{key}-handoff"),
        ),
        surface=GATEWAY,
    )["handoff"]
    return {
        **scene,
        "commitment": commitment,
        "handoff": event["handoff_id"],
        "contest": contest(scene["link"], 1, key, (scene["contradicts"],)),
        "reinstate": reinstate(scene["link"], 2, key, (scene["corroborates"],)),
        "correct": correct_handoff(
            event["handoff_id"], "void", key, contradicts(scene["meeting"], scene["note"])
        ),
    }


def _reads(scene: dict[str, Any]) -> tuple[Command, ...]:
    return (
        ReadRecordAssociationHistory(link_id=scene["link"]),
        ReadIssueHistory(issue_id=scene["issue"]),
        ReadIssueTimeline(issue_id=scene["issue"]),
        ReportLineageBackfill(run_id=_ABSENT_RUN),
    )


def test_an_ordinary_remote_client_is_denied_every_s3_write(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "deny")
    plan = PlanLineageBackfill(idempotency_key="s3-deny-plan")
    for name in _WRITES:
        before = all_s3_counts(runtime.engine)
        command = scene[name]
        assert _code(runtime, command, remote_client=REMOTE_CLIENT)[0] == "denied", name
        assert _code(runtime, command)[0] == "denied", name
        # Nothing written, and no commit mark taken.
        assert all_s3_counts(runtime.engine) == before, name
        # The operator's own request is admitted.
        runtime.ok(command, surface=GATEWAY)
    before = all_s3_counts(runtime.engine)
    assert _code(runtime, plan, remote_client=REMOTE_CLIENT)[0] == "denied"
    assert _code(runtime, plan)[0] == "denied"
    assert all_s3_counts(runtime.engine) == before


def test_a_replayed_s3_write_from_an_ordinary_client_is_denied_before_the_replay_lookup(
    runtime: S3Runtime,
) -> None:
    scene = _scene(runtime, "replay")
    for name in _WRITES:
        command = scene[name]
        original = runtime.ok(command, surface=GATEWAY)
        assert original["replayed"] is False
        # Exactly the operator's request, by a caller who may not make it.
        assert _code(runtime, command, remote_client=REMOTE_CLIENT)[0] == "denied", name
        assert _code(runtime, command)[0] == "denied", name
        replayed = runtime.ok(command, surface=GATEWAY)
        assert replayed["replayed"] is True
        assert {k: v for k, v in replayed.items() if k != "replayed"} == {
            k: v for k, v in original.items() if k != "replayed"
        }, name
    # Worker L5's write: an enumeration and a classifying batch, each replayed.
    enumerated = runtime.ok(PlanLineageBackfill(idempotency_key="s3-replay-plan"), surface=GATEWAY)
    batch = PlanLineageBackfill(
        idempotency_key="s3-replay-plan-batch",
        run_id=enumerated["run"]["run_id"],
        expected_checkpoint=0,
        batch_size=2,
    )
    classified = runtime.ok(batch, surface=GATEWAY)
    for command, original in (
        (PlanLineageBackfill(idempotency_key="s3-replay-plan"), enumerated),
        (batch, classified),
    ):
        assert original["replayed"] is False
        assert _code(runtime, command, remote_client=REMOTE_CLIENT)[0] == "denied"
        assert _code(runtime, command)[0] == "denied"
        replayed = runtime.ok(command, surface=GATEWAY)
        assert replayed["replayed"] is True
        assert {k: v for k, v in replayed.items() if k != "replayed"} == {
            k: v for k, v in original.items() if k != "replayed"
        }


def test_switch_off_answers_unsupported_for_every_s3_capability(disposable_database: str) -> None:
    on = S3Runtime(disposable_database, lineage_backfill_enabled=True)
    try:
        scene = _scene(on, "switch")
        for name in _WRITES:
            on.ok(scene[name], surface=GATEWAY)
    finally:
        on.close()
    plan = PlanLineageBackfill(idempotency_key="s3-switch-plan")
    every = (*(scene[name] for name in _WRITES), plan, *_reads(scene))
    assert {command.capability.value for command in every} >= LINEAGE_BACKFILL_CAPABILITIES
    assert len({command.capability for command in every}) == 8
    off = S3Runtime(disposable_database, lineage_enabled=False, lineage_backfill_enabled=True)
    try:
        before = all_s3_counts(off.engine)
        # Replays of writes committed while the switch was on, the backfill
        # write, and every S3 read.
        for command in every:
            assert _code(off, command, surface=GATEWAY)[0] == "unsupported", command.capability
        assert all_s3_counts(off.engine) == before
    finally:
        off.close()
    # Lineage on and the backfill sub-switch off: both backfill names are withheld.
    lineage_only = S3Runtime(disposable_database)
    try:
        for command in (plan, ReportLineageBackfill(run_id=_ABSENT_RUN)):
            assert _code(lineage_only, command, surface=GATEWAY)[0] == "unsupported"
            assert command.capability.value in LINEAGE_BACKFILL_CAPABILITIES
    finally:
        lineage_only.close()


def test_every_s3_capability_answers_a_foreign_subject_like_an_absent_one(
    runtime: S3Runtime,
) -> None:
    foreign = _scene(runtime, "foreign")
    # The caller's own evidence, so only the subject differs.
    meeting_id, note_id = runtime.note("foreign-own", principal_id=OTHER_PRINCIPAL)
    own = contradicts(meeting_id, note_id)
    before = all_s3_counts(runtime.engine)
    for link in (foreign["link"], "irl_lineages3absent0001"):
        assert _code(
            runtime,
            contest(link, 1, f"foreign-{link}", (own,)),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["link_id"])
        assert _code(
            runtime,
            reinstate(link, 1, f"foreign-{link}", (own,)),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["link_id"])
    for subject in (foreign["handoff"], "ihnd_lineages3absent0001"):
        assert _code(
            runtime,
            correct_handoff(subject, "void", f"foreign-{subject}", own),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["handoff_id"])
    # Worker L3's reads: a foreign link's or Issue's history answers like an absent one.
    for link in (foreign["link"], "irl_lineages3absent0001"):
        assert _code(
            runtime, ReadRecordAssociationHistory(link_id=link), principal_id=OTHER_PRINCIPAL
        ) == ("not_found", ["link_id"])
    for issue in (foreign["issue"], "sit_lineages3absent0001"):
        assert _code(runtime, ReadIssueHistory(issue_id=issue), principal_id=OTHER_PRINCIPAL) == (
            "not_found",
            ["issue_id"],
        )
        # Worker L4's read: a foreign Issue's timeline answers like an absent one.
        assert _code(runtime, ReadIssueTimeline(issue_id=issue), principal_id=OTHER_PRINCIPAL) == (
            "not_found",
            ["issue_id"],
        )
    # Worker L5's backfill: another Principal's run answers exactly like an absent one.
    run_id = runtime.ok(PlanLineageBackfill(idempotency_key="s3-foreign-plan"), surface=GATEWAY)[
        "run"
    ]["run_id"]
    before = all_s3_counts(runtime.engine)
    for subject in (run_id, _ABSENT_RUN):
        assert _code(
            runtime,
            PlanLineageBackfill(
                idempotency_key=f"s3-foreign-plan-{subject}",
                run_id=subject,
                expected_checkpoint=0,
            ),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["run_id"])
        assert _code(
            runtime,
            ReportLineageBackfill(run_id=subject),
            principal_id=OTHER_PRINCIPAL,
            surface=GATEWAY,
        ) == ("not_found", ["run_id"])
    assert all_s3_counts(runtime.engine) == before


# ---- the read rows (worker L3; S3 sections 6.1 and 6.4) -------------------------------


def _lineage_reads(scene: dict[str, Any]) -> tuple[Command, ...]:
    """Every S1, S2 and S3 lineage read L3 re-checks, on one scene's subjects.

    `issues.timeline` is worker L4's read and joins this set with it.
    """
    return (
        ReadRecordLineage(origin={"family": "situation", "record_id": scene["issue"]}),
        ReadIssueHistory(issue_id=scene["issue"]),
        ReadIssueTimeline(issue_id=scene["issue"]),
        ReadRecordAssociationHistory(link_id=scene["link"]),
        ReadIssue(issue_id=scene["issue"], include_members=True),
        ListIssues(),
        ListIssueHandoffs(issue_id=scene["issue"]),
        ReadIssueClosureReadiness(issue_id=scene["issue"]),
        ListMeetingNoteVersions(meeting_id=scene["meeting"]),
        ReadMeetingNoteVersion(meeting_id=scene["meeting"], note_version_id=scene["note"]),
    )


_FAMILY_READS: Final = (
    "issues.read",
    "issues.list",
    "meetings.read",
    "tasks.read",
    "commitments.read",
    "constraints.read",
    "capture.read",
)


def test_a_remote_lineage_read_without_its_grant_is_unsupported(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "read-grant")
    every_family = {(Capability(name), _purpose(name)) for name in _FAMILY_READS}
    before = all_s3_counts(runtime.engine)
    for command in _lineage_reads(scene):
        name = command.capability.value
        # Every family read, but not this capability: hidden, not forbidden.
        without = frozenset(pair for pair in every_family if pair[0] is not command.capability)
        error = _remote(runtime, command, without).to_canonical_dict()["error"]
        assert (error["code"], error.get("safe_details") or []) == ("unsupported", []), name
        # With its grant (and the family reads) the same caller is served.
        granted = without | {(command.capability, _purpose(name))}
        envelope = _remote(runtime, command, granted)
        assert envelope.error is None, (name, envelope.error)
    assert all_s3_counts(runtime.engine) == before


def test_cross_principal_reads_disclose_nothing(runtime: S3Runtime) -> None:
    scene = _scene(runtime, "read-cross")
    runtime.issue("read-cross-other", principal_id=OTHER_PRINCIPAL)
    absent = {
        "issue": "sit_lineages3absent0001",
        "link": "irl_lineages3absent0001",
        "meeting": "mtg_lineages3absent0001",
        "note": "mnote_lineages3absent0001",
    }
    for foreign, missing in zip(
        _lineage_reads(scene), _lineage_reads({**scene, **absent}), strict=True
    ):
        name = foreign.capability.value
        seen = _answer(runtime, foreign, principal_id=OTHER_PRINCIPAL)
        assert seen == _answer(runtime, missing, principal_id=OTHER_PRINCIPAL), name
        rendered = json.dumps(seen)
        for identifier in (scene["link"], scene["meeting"], scene["note"], scene["handoff"]):
            assert identifier not in rendered, name
        if name == "issues.list":
            assert seen["result"]["issues"] != [] and scene["issue"] not in rendered
        else:
            assert seen.get("code") == "not_found", (name, seen)
    # A cursor of the owner's read is another Principal's binding.
    page = runtime.ok(
        ReadRecordLineage(origin={"family": "situation", "record_id": scene["issue"]}, page_size=10)
    )
    if page["next_cursor"] is not None:
        error = runtime.refused(
            ReadRecordLineage(
                origin={"family": "situation", "record_id": scene["issue"]},
                page_size=10,
                cursor=page["next_cursor"],
            ),
            principal_id=OTHER_PRINCIPAL,
        )
        assert (error["code"], error["safe_details"]) == ("conflict", ["cursor"])


def _answer(runtime: S3Runtime, command: Command, *, principal_id: str) -> dict[str, Any]:
    """The answer without its request-scoped fields."""
    envelope = runtime.invoke(command, principal_id=principal_id).to_canonical_dict()
    error = envelope.get("error")
    if error is not None:
        return {"code": error["code"], "safe_details": error.get("safe_details")}
    result = dict(envelope["result"])
    result.pop("known_at", None)
    result.pop("native_cut_at", None)
    return {"result": result}


def _purpose(name: str) -> Purpose:
    return sorted(permitted_purposes(Capability(name)))[0]


def _remote(
    runtime: S3Runtime,
    command: Command,
    grants: frozenset[tuple[Capability, Purpose | None]],
) -> ResponseEnvelope:
    """`command` from an ordinary remote client holding exactly `grants`."""
    return runtime.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=command.capability,
            purpose=_purpose(command.capability.value),
            principal_id=PRINCIPAL,
            requested_at=WHEN,
        ),
        command,
        principal=Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
        transport=CaptureTransport.REMOTE_CLIENT,
        capability_grants=grants,
        authenticated_client_id=REMOTE_CLIENT,
        operator_surface=None,
    )
