"""Two racing submissions of one idempotency key admit one capture.

`tests/capture/test_idempotency.py` proves the **sequential** halves of
`QC-AC-031`/`QC-AC-032`: a replay after the first request finished, and a
conflicting payload after it finished. Neither touches the case the property
actually exists for — a client that retried because it never saw the first
response, with the first request still in flight. Sequential replay is satisfied
by an implementation that checks a key with `SELECT` and then inserts, and that
implementation admits **two** captures when the two `SELECT`s both run before
either `INSERT`.

So the race is reproduced rather than reasoned about. One transaction admits the
key and is **held open**; a second thread submits the identical request and is
observed *blocking on a lock in the server* — not merely "not finished yet", which
a slow machine also satisfies — before the first commits. `pg_stat_activity` is
what makes that an observation.

**Why this drives `admit_capture` rather than `service.invoke`.** The race is
between two open transactions, and an `invoke` opens and commits its own inside
one call, so there is no instant at which a test could hold one of them. This is
the same production function the use case calls, on two real connections, against
the real unique index. What it does not cover is the application layer above it,
which is what the sequential tests cover.

Every value here is synthetic. No source is opened and no path is reached.
"""

from __future__ import annotations

import threading
from typing import Final

import pytest
from sqlalchemy import Engine, text
from tests.capture.conftest import WHEN, counts

from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.ports import CaptureAdmission, CaptureAdmissionRequest
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.capture import admit_capture
from my_pa.infrastructure.persistence.principal_scope import capture_context

#: The one key both racers submit. The whole subject of the test, so it is a
#: constant rather than a value formatted twice.
KEY: Final = "racing-shortcut-0001"

TEXT: Final = "synthetic note alpha — quarterly widget review"

#: How long the observation of the blocked racer may take before the test
#: concludes the race did not happen. Generous, because what is being waited for
#: is a lock the server reports, and a machine under load may take a moment to
#: get there; the test fails rather than passes if the wait runs out.
_BLOCK_TIMEOUT_SECONDS: Final = 10.0


def _request(principal_id: str, tag: str) -> CaptureAdmissionRequest:
    """The identical request both racers submit, save for its correlation ids.

    `request_id` and `correlation_id` differ deliberately: two retries of one
    submission are two requests, and holding them identical would let a test pass
    against an implementation that keyed idempotency on the request identifier.
    """
    return CaptureAdmissionRequest(
        capture_id=None,
        content=CaptureContent(TEXT),
        idempotency_key=KEY,
        request_id=f"req-race-{tag}",
        correlation_id=issue_identifier(IdKind.CORRELATION),
        principal_id=principal_id,
        audit_id=issue_identifier(IdKind.AUDIT),
        classification=Classification.PRIVATE_LOCAL,
        processing_policy=ProcessingPolicy.LOCAL_ONLY,
        server_received_at=WHEN,
        accepted_at=WHEN,
        client_created_at=None,
        occurred_at=None,
        capture_kind=CaptureKind.QUICK_NOTE,
        context_source_object_id=None,
        context_source_version_id=None,
    )


def _blocked_sessions(engine: Engine) -> int:
    """How many backends this database is currently waiting on a lock in.

    Read from the server rather than inferred from elapsed time. A racer that is
    merely slow is not evidence that anything serialised it; a backend the server
    reports as waiting on a `Lock` is.
    """
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND state = 'active'"
                )
            ).scalar_one()
        )


@pytest.mark.database
def test_two_racing_submissions_of_one_key_admit_one_capture_and_share_one_receipt(
    runtime: GatewayRuntime,
) -> None:
    """One winner, one replay, one capture — with the race actually reproduced.

    Four assertions, and the first is the one that keeps the rest honest:

    1. the second submission **blocked in the server** while the first was open,
       so the two really did overlap;
    2. both callers hold the **same** receipt, so the loser is not told its
       retry stored something new;
    3. exactly one capture, version, receipt, submission and queued job exist —
       a second capture is the failure this test is about, and a second **job**
       would mean one capture owed two units of processing;
    4. only one of the two answers reports `created`.
    """
    engine = runtime.work_engine
    principal_id = runtime.principal.principal_id
    context = capture_context(principal_id)

    loser: dict[str, CaptureAdmission] = {}
    failure: dict[str, BaseException] = {}
    submitted = threading.Event()

    def race() -> None:
        try:
            with engine.begin() as connection:
                submitted.set()
                loser["admission"] = admit_capture(
                    connection, _request(principal_id, "second"), context=context
                )
        except BaseException as error:  # re-raised in the main thread
            submitted.set()
            failure["error"] = error

    winner_connection = engine.connect()
    transaction = winner_connection.begin()
    try:
        winner = admit_capture(winner_connection, _request(principal_id, "first"), context=context)

        racer = threading.Thread(target=race, name="second-submission")
        racer.start()
        assert submitted.wait(_BLOCK_TIMEOUT_SECONDS), "the second submission never started"

        # 1. The race, observed rather than assumed.
        deadline = threading.Event()
        blocked = False
        for _ in range(int(_BLOCK_TIMEOUT_SECONDS * 20)):
            if _blocked_sessions(engine) >= 1:
                blocked = True
                break
            deadline.wait(0.05)
        assert blocked, (
            "the second submission never blocked on a lock while the first transaction "
            "was open, so the two did not overlap and this test measured a sequential "
            "replay that `test_idempotency.py` already covers"
        )
        assert racer.is_alive(), "the second submission finished before the first committed"

        transaction.commit()
    finally:
        if transaction.is_active:
            transaction.rollback()
        winner_connection.close()

    racer.join(timeout=_BLOCK_TIMEOUT_SECONDS)
    assert not racer.is_alive(), "the second submission never unblocked after the commit"
    if "error" in failure:
        raise AssertionError(
            "the second submission failed rather than replaying the winner's receipt"
        ) from failure["error"]

    replayed = loser["admission"]

    # 2. One receipt, held by both callers.
    assert replayed.receipt == winner.receipt, (
        "two concurrent submissions of one idempotency key produced two different "
        "receipts. The loser of the race must be handed the winner's receipt, not "
        "one of its own"
    )

    # 3. One of everything.
    stored = counts(engine)
    assert stored["knowledge.captures"] == 1, (
        f"two racing submissions stored {stored['knowledge.captures']} captures"
    )
    assert stored["knowledge.capture_versions"] == 1
    assert stored["knowledge.capture_receipts"] == 1
    assert stored["knowledge.capture_submissions"] == 1
    assert stored["knowledge.capture_jobs"] == 1, (
        "one capture owed two units of processing, so the loser of the race enqueued "
        "a second job for a version it did not create"
    )

    # 4. And exactly one of them created anything.
    assert winner.created is True
    assert replayed.created is False, (
        "the loser of the race reported that it created the capture. A caller "
        "retrying a request it never saw the answer to has to be able to tell that "
        "its retry stored nothing new"
    )
