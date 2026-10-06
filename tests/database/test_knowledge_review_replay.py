"""KLP-WP-04 slice C: Knowledge `review.decide` replays byte-identically (KLP-AC-038).

Marked `database` (auto `database_clone`), routed to `database-current-head`.

A Knowledge decision reserves C1 in `relationship_write_requests` before any
Knowledge lock and completes it with `result_family = review_decision`,
`result_id = kadec_`, `result_assertion_id = kasr_` and `receipt_id = kamut_`
(R6 section 10.1, ALTER N1: no DDL). An identical retry under the same request
id is answered by the *generic* replay builder: a payload byte-identical to the
fresh one, with exactly the existing seven keys and no discriminator, and no
second decision, mutation, assertion or Record Event. The same request id with
a different request is `conflict(idempotency_conflict)` and writes nothing.

Every identity here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from tests.database.test_knowledge_assertion_repository import counts
from tests.database.test_knowledge_assertion_review import (
    CLI,
    DECIDE_KEYS,
    OPERATOR_CLIENT,
    ReviewRuntime,
    _queued,
    decisions_of,
    remote,
    write_request_of,
)
from tests.database.test_task_record_events import next_sequence

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]


@pytest.fixture
def review(disposable_database: str) -> Iterator[ReviewRuntime]:
    composed = ReviewRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize(
    ("disposition", "patch", "via"),
    [
        (Disposition.ACCEPT, None, CLI),
        (Disposition.CORRECT_AND_ACCEPT, {"value": "Synthetic net 45 terms"}, CLI),
        (Disposition.ACCEPT, None, remote(OPERATOR_CLIENT)),
        (Disposition.REJECT, None, CLI),
        (Disposition.DEFER, None, remote(OPERATOR_CLIENT)),
    ],
    ids=["accept", "correct", "accept_remote_operator", "reject", "defer_remote"],
)
def test_an_identical_retry_replays_the_fresh_payload_byte_for_byte(
    review: ReviewRuntime,
    disposition: Disposition,
    patch: dict[str, object] | None,
    via: dict[str, object],
) -> None:
    principal, _entity, case = _queued(review)
    command = review.decide_command(case, disposition, patch=patch)
    request_id = issue_identifier(IdKind.CORRELATION)
    fresh = review.invoke_with_request_id(
        command, principal_id=principal, request_id=request_id, **via
    )
    assert fresh.error is None, fresh.error
    assert fresh.result is not None
    assert set(fresh.result) == DECIDE_KEYS
    committed = counts(review.engine, principal)
    sequence = next_sequence(review.engine, principal)

    replayed = review.invoke_with_request_id(
        command, principal_id=principal, request_id=request_id, **via
    )
    assert replayed.error is None, replayed.error
    assert replayed.result is not None
    assert _canonical(replayed.result) == _canonical(fresh.result)
    assert counts(review.engine, principal) == committed
    assert next_sequence(review.engine, principal) == sequence
    assert len(decisions_of(review.engine, case)) == 1

    stored = write_request_of(review.engine, str(fresh.result["decision_id"]))
    assert stored["result_family"] == "review_decision"
    assert str(stored["result_id"]).startswith("kadec_")
    if fresh.result["assertion_id"] is None:
        assert stored["result_assertion_id"] is None
        assert stored["receipt_id"] is None
    else:
        assert str(stored["result_assertion_id"]).startswith("kasr_")
        assert str(stored["receipt_id"]).startswith("kamut_")


def test_the_same_request_id_with_another_request_conflicts_and_writes_nothing(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    request_id = issue_identifier(IdKind.CORRELATION)
    first = review.invoke_with_request_id(
        review.decide_command(case, Disposition.DEFER),
        principal_id=principal,
        request_id=request_id,
        **CLI,
    )
    assert first.error is None, first.error
    committed = counts(review.engine, principal)
    changed = review.invoke_with_request_id(
        review.decide_command(case, Disposition.REJECT, version=1),
        principal_id=principal,
        request_id=request_id,
        **CLI,
    )
    assert changed.error is not None
    assert changed.error.code.value == "conflict"
    assert changed.error.safe_details == ("idempotency_conflict",)
    assert counts(review.engine, principal) == committed
    assert len(decisions_of(review.engine, case)) == 1


def test_a_refused_decide_leaves_no_reservation_to_replay(review: ReviewRuntime) -> None:
    """A stale-version refusal rolls the C1 reservation back with everything else."""
    principal, _entity, case = _queued(review)
    request_id = issue_identifier(IdKind.CORRELATION)
    stale = review.invoke_with_request_id(
        review.decide_command(case, Disposition.ACCEPT, version=5),
        principal_id=principal,
        request_id=request_id,
        **CLI,
    )
    assert stale.error is not None
    assert stale.error.code.value == "conflict"
    retried = review.invoke_with_request_id(
        review.decide_command(case, Disposition.ACCEPT, version=0),
        principal_id=principal,
        request_id=request_id,
        **CLI,
    )
    assert retried.error is None, retried.error
    assert retried.result is not None
    assert retried.result["proposal_state"] == "accepted"
