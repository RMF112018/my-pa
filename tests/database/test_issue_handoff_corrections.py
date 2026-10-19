"""The S2 residual: handoff corrections (S3 contract sections 3.3, 3.4, 7.1 and 7.4).

`issues.handoffs.correct` appends one immutable correction naming one handoff
event and never changes the event:

* `retime` -- the event happened at another business time: exactly one exact
  `handoff` anchor, and the new time stays at or after the Commitment's
  creation and the previous live event, at or before the next live event and
  its own recording (`invalid_request` / `effective_at`);
* `void` -- the event did not happen: exactly one exact `contradicts` anchor,
  and only the chain's last live event (`invalid_request` / `handoff_id`);
* a voided event is terminal (`conflict` / `state`), a closed Issue's handoffs
  are frozen (`conflict` / `state`), and a foreign handoff answers like an
  absent one (`not_found` / `handoff_id`);
* the chain skips voided events: a new handoff follows the last live holder;
* `issues.handoffs.list` reports events and corrections as known at
  `known_at`.

Every write is a stamped local-operator write. Every identity and every body is
synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.application.commands import ListIssueHandoffs
from my_pa.application.errors import InvalidRequestError
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL
from tests.database.lineage_record_harness import capture, legacy_anchor
from tests.database.lineage_s2_harness import close, handoff
from tests.database.lineage_s3_harness import (
    GATEWAY,
    S3Runtime,
    all_s3_counts,
    contradicts,
    correct_handoff,
    mark_count,
    mark_taken_first,
    shortly_after,
    statements,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3Runtime]:
    composed = S3Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _ok(runtime: S3Runtime, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    return runtime.ok(command, **kwargs)


def _refused(runtime: S3Runtime, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    kwargs.setdefault("surface", GATEWAY)
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


@dataclass
class _Chain:
    """One Commitment's chain in one Issue, and the instants used to build it."""

    runtime: S3Runtime
    issue: str
    commitment: str
    created_at: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def at(self, microseconds: int) -> str:
        return shortly_after(self.created_at, microseconds)

    def record(self, side: str, microseconds: int, key: str) -> dict[str, Any]:
        written = _ok(
            self.runtime,
            handoff(
                self.issue,
                self.commitment,
                side,
                self.at(microseconds),
                key,
                self.runtime.handoff_anchor(key),
            ),
        )["handoff"]
        self.events.append(written)
        return written


def _chain(runtime: S3Runtime, key: str, sides: tuple[str, ...] = ()) -> _Chain:
    """A Commitment (a `discussion` member, so the Issue stays closable) and its events.

    Event *n* is effective `100 * n` microseconds after the shown creation
    instant plus one millisecond.
    """
    issue = runtime.issue(key)
    commitment = runtime.commitment(key)
    runtime.member(issue, "commitment", commitment, key, "discussion")
    chain = _Chain(
        runtime=runtime,
        issue=issue,
        commitment=commitment,
        created_at=str(runtime.commitment_view(commitment)["created_at"]),
    )
    for number, side in enumerate(sides, start=1):
        chain.record(side, 100 * number, f"{key}-{number}")
    return chain


def _void_anchor(runtime: S3Runtime, key: str) -> dict[str, object]:
    meeting_id, note_id = runtime.note(f"{key}-void")
    return contradicts(meeting_id, note_id)


def _shown(instant: str) -> str:
    """An instant as a view shows it: RFC 3339 UTC to the millisecond."""
    value = datetime.fromisoformat(instant)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---- retime -------------------------------------------------------------------------------


def test_a_retime_needs_a_handoff_anchor_and_stays_in_order(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "retime", ("counterparty", "principal", "counterparty"))
    middle = chain.events[1]["handoff_id"]
    anchor = runtime.handoff_anchor("retime-correction")
    # The anchor is exactly one exact `handoff` anchor, and a retime states its time.
    with pytest.raises(InvalidRequestError):
        correct_handoff(
            middle,
            "retime",
            "wrong-role",
            _void_anchor(runtime, "retime-wrong-role"),
            effective_at=chain.at(150),
        )
    capture_id, _, _ = capture(runtime, "retime-legacy")
    with pytest.raises(InvalidRequestError):
        correct_handoff(
            middle,
            "retime",
            "legacy",
            legacy_anchor(capture_id, role="handoff"),
            effective_at=chain.at(150),
        )
    with pytest.raises(InvalidRequestError):
        correct_handoff(middle, "retime", "no-time", anchor)
    with pytest.raises(InvalidRequestError):
        correct_handoff(middle, "void", "void-with-time", anchor, effective_at=chain.at(150))
    before = all_s3_counts(runtime.engine)
    for name, instant in (
        # Before the previous live event's current effective time.
        ("before-previous", chain.at(50)),
        # After the next live event's.
        ("after-next", chain.at(350)),
        # Before the Commitment existed.
        ("before-creation", "2020-01-01T00:00:00+00:00"),
    ):
        assert _refused(
            runtime, correct_handoff(middle, "retime", name, anchor, effective_at=instant)
        ) == ("invalid_request", ["effective_at"]), name
    assert all_s3_counts(runtime.engine) == before
    marks = mark_count(runtime.engine)
    with statements(runtime.engine) as seen:
        written = _ok(
            runtime,
            correct_handoff(middle, "retime", "in-order", anchor, effective_at=chain.at(250)),
        )
    # Section 6.2 step 1b: the mark right after the reservation, before any lock.
    assert mark_taken_first(seen)
    assert written["replayed"] is False
    correction = written["correction"]
    assert (correction["handoff_id"], correction["correction_no"], correction["action"]) == (
        middle,
        1,
        "retime",
    )
    assert correction["effective_at"] == _shown(chain.at(250))
    assert correction["evidence"]["role"] == "handoff"
    view = written["handoff"]
    # The event keeps its recorded time; the correction moves its current one.
    assert view["effective_at"] == chain.events[1]["effective_at"]
    assert view["current_effective_at"] == _shown(chain.at(250))
    assert (view["voided"], view["correction_ids"]) == (False, [correction["correction_id"]])
    assert mark_count(runtime.engine) == marks + 1
    # The retimed time now bounds its neighbours: the last event cannot move before it.
    last = chain.events[2]["handoff_id"]
    assert _refused(
        runtime, correct_handoff(last, "retime", "last-early", anchor, effective_at=chain.at(240))
    ) == ("invalid_request", ["effective_at"])
    # A replay answers the stored correction and the handoff as it stood then.
    replay = _ok(
        runtime, correct_handoff(middle, "retime", "in-order", anchor, effective_at=chain.at(250))
    )
    assert replay["replayed"] is True
    assert {k: v for k, v in replay.items() if k != "replayed"} == {
        k: v for k, v in written.items() if k != "replayed"
    }


# ---- void ---------------------------------------------------------------------------------


def test_only_the_last_live_handoff_can_be_voided(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "void-last", ("counterparty", "principal"))
    first, second = (event["handoff_id"] for event in chain.events)
    anchor = _void_anchor(runtime, "void-last")
    before = all_s3_counts(runtime.engine)
    with statements(runtime.engine) as seen:
        refused = _refused(runtime, correct_handoff(first, "void", "first-early", anchor))
    # The application refuses it; no correction INSERT ever reaches the database.
    assert refused == ("invalid_request", ["handoff_id"])
    assert not any(
        "INSERT INTO knowledge.issue_responsibility_corrections" in statement for statement in seen
    )
    assert all_s3_counts(runtime.engine) == before
    voided = _ok(runtime, correct_handoff(second, "void", "second", anchor))
    assert voided["correction"]["action"] == "void"
    assert voided["correction"]["effective_at"] is None
    assert voided["handoff"]["voided"] is True
    # With the second voided, the first is the chain's last live event.
    assert _ok(runtime, correct_handoff(first, "void", "first", anchor))["handoff"]["voided"]


def test_a_void_needs_a_contradicting_anchor(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "void-anchor", ("counterparty",))
    target = chain.events[0]["handoff_id"]
    capture_id, _, _ = capture(runtime, "void-anchor-legacy")
    for name, anchor in (
        ("handoff-role", runtime.handoff_anchor("void-anchor-wrong")),
        ("legacy", legacy_anchor(capture_id, role="contradicts")),
    ):
        with pytest.raises(InvalidRequestError):
            correct_handoff(target, "void", name, anchor)
    written = _ok(
        runtime, correct_handoff(target, "void", "good", _void_anchor(runtime, "void-anchor"))
    )
    assert written["correction"]["evidence"]["role"] == "contradicts"
    assert written["correction"]["evidence"]["version_kind"] == "immutable_version"


def test_a_voided_handoff_is_not_the_chain_holder(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "holder", ("counterparty", "principal"))
    # Event 1: counterparty -> Principal; event 2: Principal -> counterparty.
    assert chain.events[0]["to"]["kind"] == "principal"
    assert chain.events[1]["to"]["kind"] == "entity"
    _ok(
        runtime,
        correct_handoff(
            chain.events[1]["handoff_id"], "void", "holder", _void_anchor(runtime, "holder")
        ),
    )
    # The chain's holder is event 1's arriving holder again: the counterparty side is wrong.
    assert _refused(
        runtime,
        handoff(
            chain.issue,
            chain.commitment,
            "counterparty",
            chain.at(300),
            "holder-wrong-side",
            runtime.handoff_anchor("holder-wrong-side"),
        ),
    ) == ("invalid_request", ["from"])
    # And its time bounds the next: before event 2's (voided) time is admitted.
    third = chain.record("principal", 150, "holder-3")
    assert (third["sequence_no"], third["from"]["kind"], third["to"]["kind"]) == (
        3,
        "principal",
        "entity",
    )
    # A chain whose every event is voided starts again under the event-1 rule.
    lone = _chain(runtime, "holder-lone", ("counterparty",))
    _ok(
        runtime,
        correct_handoff(
            lone.events[0]["handoff_id"], "void", "lone", _void_anchor(runtime, "holder-lone")
        ),
    )
    restarted = lone.record("principal", 50, "holder-lone-2")
    assert (restarted["sequence_no"], restarted["from"]["kind"]) == (2, "principal")


def test_a_correction_of_a_voided_handoff_is_refused(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "terminal", ("counterparty",))
    target = chain.events[0]["handoff_id"]
    anchor = _void_anchor(runtime, "terminal")
    _ok(runtime, correct_handoff(target, "void", "terminal", anchor))
    before = all_s3_counts(runtime.engine)
    assert _refused(runtime, correct_handoff(target, "void", "terminal-again", anchor)) == (
        "conflict",
        ["state"],
    )
    assert _refused(
        runtime,
        correct_handoff(
            target,
            "retime",
            "terminal-retime",
            runtime.handoff_anchor("terminal-retime"),
            effective_at=chain.at(50),
        ),
    ) == ("conflict", ["state"])
    assert all_s3_counts(runtime.engine) == before


def test_a_correction_on_a_closed_issue_is_refused(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "closed", ("counterparty",))
    target = chain.events[0]["handoff_id"]
    _, _, closure = runtime.evidence_source("closed-closure")
    _ok(runtime, close(chain.issue, 1, "closed", (closure,)))
    before = all_s3_counts(runtime.engine)
    assert _refused(
        runtime, correct_handoff(target, "void", "closed", _void_anchor(runtime, "closed"))
    ) == ("conflict", ["state"])
    assert _refused(
        runtime,
        correct_handoff(
            target,
            "retime",
            "closed-retime",
            runtime.handoff_anchor("closed-retime"),
            effective_at=chain.at(50),
        ),
    ) == ("conflict", ["state"])
    assert all_s3_counts(runtime.engine) == before


def test_handoffs_list_reports_corrections_at_known_at(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "known", ("counterparty", "principal"))
    first, second = (event["handoff_id"] for event in chain.events)
    listed = _ok(runtime, ListIssueHandoffs(issue_id=chain.issue))
    before_corrections = str(listed["known_at"])
    assert [event["voided"] for event in listed["handoffs"]] == [False, False]
    retimed = _ok(
        runtime,
        correct_handoff(
            first,
            "retime",
            "known-retime",
            runtime.handoff_anchor("known-retime"),
            effective_at=chain.at(150),
        ),
    )["correction"]["correction_id"]
    after_retime = str(_ok(runtime, ListIssueHandoffs(issue_id=chain.issue))["known_at"])
    voided = _ok(
        runtime, correct_handoff(second, "void", "known-void", _void_anchor(runtime, "known"))
    )["correction"]["correction_id"]
    # Now: event 1 retimed, event 2 voided, each naming its correction.
    now = _ok(runtime, ListIssueHandoffs(issue_id=chain.issue))
    assert [
        (event["current_effective_at"], event["voided"], event["correction_ids"])
        for event in now["handoffs"]
    ] == [
        (_shown(chain.at(150)), False, [retimed]),
        (chain.events[1]["effective_at"], True, [voided]),
    ]
    # As known before the void: retimed, not yet voided.
    middle = _ok(runtime, ListIssueHandoffs(issue_id=chain.issue, known_at=after_retime))
    assert middle["known_at"] == after_retime
    assert [
        (event["current_effective_at"], event["voided"], event["correction_ids"])
        for event in middle["handoffs"]
    ] == [
        (_shown(chain.at(150)), False, [retimed]),
        (chain.events[1]["effective_at"], False, []),
    ]
    # As known before any correction: the events exactly as recorded.
    past = _ok(runtime, ListIssueHandoffs(issue_id=chain.issue, known_at=before_corrections))
    assert past["handoffs"] == listed["handoffs"]
    # A `known_at` after now is refused.
    assert _refused(
        runtime, ListIssueHandoffs(issue_id=chain.issue, known_at="2999-01-01T00:00:00+00:00")
    ) == ("invalid_request", ["known_at"])
    # An event recorded after the cut is not listed at it.
    chain.record("principal", 300, "known-3")
    assert (
        len(
            _ok(runtime, ListIssueHandoffs(issue_id=chain.issue, known_at=after_retime))["handoffs"]
        )
        == 2
    )


def test_a_foreign_handoff_answers_like_an_absent_one(runtime: S3Runtime) -> None:
    chain = _chain(runtime, "foreign", ("counterparty",))
    target = chain.events[0]["handoff_id"]
    meeting_id, note_id = runtime.note("foreign-own", principal_id=OTHER_PRINCIPAL)
    own_anchor = contradicts(meeting_id, note_id)
    before = all_s3_counts(runtime.engine)
    answers = [
        _refused(
            runtime,
            correct_handoff(subject, "void", f"foreign-{subject}", own_anchor),
            principal_id=OTHER_PRINCIPAL,
        )
        for subject in (target, "ihnd_lineages3absent0001")
    ]
    assert answers == [("not_found", ["handoff_id"])] * 2
    assert all_s3_counts(runtime.engine) == before
    # The owner's chain is untouched.
    with runtime.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM knowledge.issue_responsibility_corrections")
            ).scalar_one()
            == 0
        )
