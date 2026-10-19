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

The read rows of this crosswalk entry (`a remote lineage read without its
grant`, `cross-principal reads`) are the read packages'. Every identity here is
synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest

from my_pa.application.commands import (
    Command,
    PlanLineageBackfill,
    ReadIssueHistory,
    ReadIssueTimeline,
    ReadRecordAssociationHistory,
    ReportLineageBackfill,
)
from my_pa.domain.lineage.vocabulary import LINEAGE_BACKFILL_CAPABILITIES
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, REMOTE_CLIENT
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
    assert all_s3_counts(runtime.engine) == before
