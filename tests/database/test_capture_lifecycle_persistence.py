"""CRL-WP-03 CP-CRL-02: the Capture lifecycle schema and repository on a real database.

Marked `database` (auto `database_clone`): every test runs on a fresh clone of
the current head. Seeds are raw synthetic rows; nothing here goes through the
application service, which arrives at CP-CRL-03. This module proves:

* **append-only** -- both lifecycle tables refuse UPDATE and DELETE (CW-003);
* **declarative contiguity and alternation** -- the table refuses a skipped,
  duplicated, mis-alternating, mislinked, half-linked or foreign-owner event
  (CW-AC-05), each by the named constraint;
* **honest receipts** -- the outcome CHECKs, one key per Principal, and a
  receipt bound to an event of its own root, revision and operation;
* **same-owner protection** -- no lifecycle row can name a root under another
  Principal, through the `captures (capture_id, owner_principal_id)` UNIQUE;
* **the repository** -- the root lock is `FOR NO KEY UPDATE` (it blocks
  `FOR SHARE` but not a foreign-key check), foreign and absent roots answer
  alike, the latest projection and bounded history read 0 -> 1 -> 2, receipts
  are partitioned, and job suspension and resumption change exactly the rows
  plan (f) names.

Every identity and value is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, Table, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.domain.capture.lifecycle import (
    CaptureLifecycleEvent,
    CaptureLifecycleOperation,
    CaptureLifecycleOutcome,
    CaptureLifecycleProjection,
    CaptureLifecycleReceipt,
    CaptureLifecycleState,
    CaptureProcessingEligibility,
    CaptureProcessingSubject,
    decide_transition,
    operation_for_revision,
)
from my_pa.domain.capture.version import digest_of
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.capture_lifecycle import (
    MAX_LIFECYCLE_HISTORY,
    JobResumption,
    latest_lifecycle,
    lifecycle_history,
    lifecycle_receipt,
    lock_capture_root,
    record_lifecycle_event,
    record_lifecycle_receipt,
    resume_capture_jobs,
    suspend_capture_jobs,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.tables import (
    capture_jobs,
    capture_lifecycle_events,
    capture_lifecycle_receipts,
    capture_versions,
    captures,
)

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 10, 1, 12, tzinfo=UTC)
DIGEST: Final = "b" * 64
RESTRICT_VIOLATION: Final = "23001"
LOCK_NOT_AVAILABLE: Final = "55P03"
NOTE: Final = "Synthetic lifecycle note."


def _principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def _corr() -> str:
    return issue_identifier(IdKind.CORRELATION)


def _audit() -> str:
    return issue_identifier(IdKind.AUDIT)


def _seed_capture(
    connection: Connection, owner: str, *, versions: int = 1
) -> tuple[str, list[str]]:
    capture_id = issue_identifier(IdKind.CAPTURE)
    connection.execute(
        insert(captures).values(capture_id=capture_id, owner_principal_id=owner, created_at=WHEN)
    )
    version_ids: list[str] = []
    previous: str | None = None
    for number in range(1, versions + 1):
        version_id = issue_identifier(IdKind.CAPTURE_VERSION)
        connection.execute(
            insert(capture_versions).values(
                version_id=version_id,
                capture_id=capture_id,
                version_number=number,
                supersedes_version_id=previous,
                content=NOTE,
                content_sha256=digest_of(NOTE),
                owner_principal_id=owner,
                classification="private_local",
                processing_policy="local_only",
                idempotency_key=f"seed-{version_id}",
                correlation_id=_corr(),
                audit_id=_audit(),
                server_received_at=WHEN,
                accepted_at=WHEN,
                recorded_at=WHEN,
            )
        )
        version_ids.append(version_id)
        previous = version_id
    return capture_id, version_ids


def _seed_job(
    connection: Connection, owner: str, version_id: str, *, state: str, attempts: int = 0
) -> str:
    operation_id = issue_identifier(IdKind.OPERATION)
    values: dict[str, object] = {
        "operation_id": operation_id,
        "version_id": version_id,
        "principal_id": owner,
        "state": state,
        "attempt_count": attempts,
    }
    if state == "running":
        values |= {"lease_owner": "worker-seed", "lease_expires_at": WHEN + timedelta(days=3650)}
    if state == "failed":
        values |= {"dead_lettered_at": WHEN, "last_error_code": "internal_error"}
    connection.execute(insert(capture_jobs).values(values))
    return operation_id


def _job(connection: Connection, operation_id: str) -> dict[str, Any]:
    return dict(
        connection.execute(
            text(
                "SELECT state, attempt_count, lease_owner, lease_expires_at, lease_generation, "
                "pause_cause, next_attempt_at, last_error_code "
                "FROM knowledge.capture_jobs WHERE operation_id = :id"
            ),
            {"id": operation_id},
        )
        .mappings()
        .one()
    )


def _event_values(
    owner: str, capture_id: str, revision: int, **overrides: object
) -> dict[str, object]:
    operation = operation_for_revision(revision).value
    values: dict[str, object] = {
        "event_id": issue_identifier(IdKind.CAPTURE_LIFECYCLE_EVENT),
        "owner_principal_id": owner,
        "capture_id": capture_id,
        "lifecycle_revision": revision,
        "operation": operation,
        "resulting_state": "archived" if operation == "archive" else "active",
        "predecessor_event_id": None,
        "predecessor_revision": None,
        "transitioned_at": WHEN + timedelta(minutes=revision),
        "intent_digest": DIGEST,
        "correlation_id": _corr(),
        "audit_id": _audit(),
        "reason_category": "owner_stated",
    }
    values.update(overrides)
    return values


def _refused(engine: Engine, table: Table, values: dict[str, object]) -> str:
    """Insert `values` and return the name of the constraint that refused them."""
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(insert(table).values(values))
    return str(refused.value.orig.diag.constraint_name)  # type: ignore[union-attr]


def _events(
    connection: Connection, owner: str, capture_id: str, count: int
) -> list[CaptureLifecycleEvent]:
    """Append `count` valid events through the domain and the repository."""
    context = capture_context(owner)
    written: list[CaptureLifecycleEvent] = []
    for _ in range(count):
        projection = latest_lifecycle(connection, capture_id, context=context)
        operation = operation_for_revision(projection.revision + 1)
        decision = decide_transition(projection, operation, projection.revision)
        event = CaptureLifecycleEvent.following(
            projection,
            decision,
            event_id=issue_identifier(IdKind.CAPTURE_LIFECYCLE_EVENT),
            transitioned_at=WHEN + timedelta(minutes=projection.revision + 1),
            intent_digest=DIGEST,
            correlation_id=_corr(),
            audit_id=_audit(),
        )
        record_lifecycle_event(connection, event, context=context)
        written.append(event)
    return written


@pytest.fixture
def engine(migrated_engine: Engine) -> Engine:
    return migrated_engine


@pytest.fixture
def root(engine: Engine) -> Iterator[tuple[str, str]]:
    owner = _principal()
    with engine.begin() as connection:
        capture_id, _ = _seed_capture(connection, owner)
    yield owner, capture_id


# ---- append-only (CW-003) ------------------------------------------------------


def test_append_only_triggers_refuse_update_and_delete(
    engine: Engine, root: tuple[str, str]
) -> None:
    owner, capture_id = root
    with engine.begin() as connection:
        (event,) = _events(connection, owner, capture_id, 1)
        projection = latest_lifecycle(connection, capture_id, context=capture_context(owner))
        record_lifecycle_receipt(
            connection,
            CaptureLifecycleReceipt(
                receipt_id=issue_identifier(IdKind.CAPTURE_LIFECYCLE_RECEIPT),
                owner_principal_id=owner,
                idempotency_key="key-append-only",
                capture_id=capture_id,
                operation=CaptureLifecycleOperation.ARCHIVE,
                intent_digest=DIGEST,
                expected_lifecycle_revision=0,
                resulting_lifecycle_revision=projection.revision,
                outcome=CaptureLifecycleOutcome.APPLIED,
                event_id=event.event_id,
                issued_at=WHEN,
                correlation_id=_corr(),
                audit_id=_audit(),
            ),
            context=capture_context(owner),
        )
    for statement in (
        "UPDATE knowledge.capture_lifecycle_events SET intent_digest = :d",
        "DELETE FROM knowledge.capture_lifecycle_events",
        "UPDATE knowledge.capture_lifecycle_receipts SET intent_digest = :d",
        "DELETE FROM knowledge.capture_lifecycle_receipts",
    ):
        with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
            connection.execute(text(statement), {"d": "c" * 64})
        assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION, statement
        assert "append-only" in str(refused.value.orig)


# ---- contiguity, alternation and same-owner (CW-AC-05) ------------------------------


def test_contiguity_and_alternation_are_declarative(engine: Engine, root: tuple[str, str]) -> None:
    owner, capture_id = root
    table = capture_lifecycle_events
    # Revision 1 must archive.
    assert (
        _refused(
            engine,
            table,
            _event_values(owner, capture_id, 1, operation="restore", resulting_state="active"),
        )
        == "odd_capture_lifecycle_revisions_archive"
    )
    # An archive results in archived.
    assert (
        _refused(engine, table, _event_values(owner, capture_id, 1, resulting_state="active"))
        == "a_capture_archive_results_in_archived"
    )
    # A later event without a predecessor.
    assert (
        _refused(engine, table, _event_values(owner, capture_id, 2))
        == "only_the_first_capture_lifecycle_event_has_no_predecessor"
    )
    with engine.begin() as connection:
        first = _event_values(owner, capture_id, 1)
        connection.execute(insert(table).values(first))
    # Half a predecessor: the self-reference is MATCH SIMPLE, so the CHECK holds it.
    assert (
        _refused(
            engine,
            table,
            _event_values(owner, capture_id, 2, predecessor_event_id=first["event_id"]),
        )
        == "a_capture_lifecycle_predecessor_is_whole"
    )
    # A skipped revision.
    assert (
        _refused(
            engine,
            table,
            _event_values(
                owner,
                capture_id,
                3,
                predecessor_event_id=first["event_id"],
                predecessor_revision=1,
            ),
        )
        == "a_capture_lifecycle_predecessor_is_the_prior_revision"
    )
    # A second event at the same revision (a fork).
    assert (
        _refused(engine, table, _event_values(owner, capture_id, 1))
        == "one_capture_lifecycle_event_per_revision"
    )
    # A predecessor that is no event of this root.
    with engine.begin() as connection:
        other_capture, _ = _seed_capture(connection, owner)
        other_first = _event_values(owner, other_capture, 1)
        connection.execute(insert(table).values(other_first))
    assert (
        _refused(
            engine,
            table,
            _event_values(
                owner,
                capture_id,
                2,
                predecessor_event_id=other_first["event_id"],
                predecessor_revision=1,
            ),
        )
        == "a_capture_lifecycle_predecessor_is_an_event_of_its_root"
    )
    # The valid successor is accepted.
    with engine.begin() as connection:
        connection.execute(
            insert(table).values(
                _event_values(
                    owner,
                    capture_id,
                    2,
                    predecessor_event_id=first["event_id"],
                    predecessor_revision=1,
                )
            )
        )


def test_no_lifecycle_row_can_name_a_root_under_another_principal(
    engine: Engine, root: tuple[str, str]
) -> None:
    owner, capture_id = root
    intruder = _principal()
    assert (
        _refused(engine, capture_lifecycle_events, _event_values(intruder, capture_id, 1))
        == "a_capture_lifecycle_event_names_a_capture_of_its_owner"
    )
    receipt = {
        "receipt_id": issue_identifier(IdKind.CAPTURE_LIFECYCLE_RECEIPT),
        "owner_principal_id": intruder,
        "idempotency_key": "key-intruder",
        "capture_id": capture_id,
        "operation": "restore",
        "intent_digest": DIGEST,
        "expected_lifecycle_revision": 0,
        "resulting_lifecycle_revision": 0,
        "outcome": "no_op",
        "event_id": None,
        "issued_at": WHEN,
        "correlation_id": _corr(),
        "audit_id": _audit(),
    }
    assert (
        _refused(engine, capture_lifecycle_receipts, receipt)
        == "a_capture_lifecycle_receipt_names_a_capture_of_its_owner"
    )
    del owner


def _receipt_values(owner: str, capture_id: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "receipt_id": issue_identifier(IdKind.CAPTURE_LIFECYCLE_RECEIPT),
        "owner_principal_id": owner,
        "idempotency_key": f"key-{issue_identifier(IdKind.OPERATION)}",
        "capture_id": capture_id,
        "operation": "restore",
        "intent_digest": DIGEST,
        "expected_lifecycle_revision": 0,
        "resulting_lifecycle_revision": 0,
        "outcome": "no_op",
        "event_id": None,
        "issued_at": WHEN,
        "correlation_id": _corr(),
        "audit_id": _audit(),
    }
    values.update(overrides)
    return values


def test_receipts_record_only_honest_outcomes(engine: Engine, root: tuple[str, str]) -> None:
    owner, capture_id = root
    table = capture_lifecycle_receipts
    with engine.begin() as connection:
        (archive,) = _events(connection, owner, capture_id, 1)
    applied: dict[str, object] = {
        "operation": "archive",
        "outcome": "applied",
        "resulting_lifecycle_revision": 1,
        "event_id": archive.event_id,
    }
    cases: dict[str, dict[str, object]] = {
        "an_applied_capture_lifecycle_receipt_moves_the_revision_by_one": {
            **applied,
            "resulting_lifecycle_revision": 0,
            "event_id": None,
        },
        "an_applied_capture_lifecycle_receipt_names_its_event": {**applied, "event_id": None},
        "a_no_op_capture_lifecycle_receipt_names_the_latest_event": {
            "event_id": archive.event_id,
        },
        "a_capture_lifecycle_outcome_is_known": {"outcome": "replayed"},
        "a_capture_lifecycle_receipt_records_a_bounded_key": {"idempotency_key": "k" * 129},
        # A receipt naming the right event under the wrong operation.
        "a_capture_lifecycle_receipt_names_its_root_event": {
            **applied,
            "operation": "restore",
            "outcome": "applied",
        },
    }
    for constraint, overrides in cases.items():
        refused = _refused(engine, table, _receipt_values(owner, capture_id, **overrides))
        if constraint == "an_applied_capture_lifecycle_receipt_moves_the_revision_by_one":
            assert refused in {
                constraint,
                "an_applied_capture_lifecycle_receipt_names_its_event",
            }
        else:
            assert refused == constraint, (constraint, refused)
    with engine.begin() as connection:
        connection.execute(insert(table).values(_receipt_values(owner, capture_id, **applied)))
        connection.execute(insert(table).values(_receipt_values(owner, capture_id)))


def test_one_key_admits_one_request_per_principal(engine: Engine, root: tuple[str, str]) -> None:
    owner, capture_id = root
    other = _principal()
    with engine.begin() as connection:
        other_capture, _ = _seed_capture(connection, other)
        connection.execute(
            insert(capture_lifecycle_receipts).values(
                _receipt_values(owner, capture_id, idempotency_key="shared-key")
            )
        )
        # The same key in another Principal's partition is a different request.
        connection.execute(
            insert(capture_lifecycle_receipts).values(
                _receipt_values(other, other_capture, idempotency_key="shared-key")
            )
        )
    assert (
        _refused(
            engine,
            capture_lifecycle_receipts,
            _receipt_values(owner, capture_id, idempotency_key="shared-key"),
        )
        == "a_capture_lifecycle_key_admits_one_request_per_principal"
    )


# ---- the repository ---------------------------------------------------------------


def test_the_root_lock_is_owner_scoped_and_answers_foreign_and_absent_alike(
    engine: Engine, root: tuple[str, str]
) -> None:
    owner, capture_id = root
    with engine.begin() as connection:
        assert lock_capture_root(connection, capture_id, context=capture_context(owner))
        assert not lock_capture_root(connection, capture_id, context=capture_context(_principal()))
        assert not lock_capture_root(
            connection, issue_identifier(IdKind.CAPTURE), context=capture_context(owner)
        )


def test_the_root_lock_blocks_for_share_but_not_a_foreign_key_check(
    engine: Engine, root: tuple[str, str]
) -> None:
    """MR-C06: `FOR NO KEY UPDATE` conflicts with `FOR SHARE`, not with `KEY SHARE`."""
    owner, capture_id = root
    with engine.connect() as holder:
        transaction = holder.begin()
        assert lock_capture_root(holder, capture_id, context=capture_context(owner))
        with engine.connect() as other:
            share = other.begin()
            other.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(DBAPIError) as blocked:
                other.execute(
                    text("SELECT 1 FROM knowledge.captures WHERE capture_id = :id FOR SHARE"),
                    {"id": capture_id},
                )
            assert getattr(blocked.value.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE
            share.rollback()
            # A foreign-key check on the root takes only KEY SHARE: not blocked.
            keyed = other.begin()
            other.execute(text("SET LOCAL lock_timeout = '200ms'"))
            assert (
                other.execute(
                    text("SELECT 1 FROM knowledge.captures WHERE capture_id = :id FOR KEY SHARE"),
                    {"id": capture_id},
                ).scalar_one()
                == 1
            )
            keyed.rollback()
        transaction.rollback()


def test_latest_projection_and_history_read_zero_one_two(
    engine: Engine, root: tuple[str, str]
) -> None:
    owner, capture_id = root
    context = capture_context(owner)
    with engine.begin() as connection:
        assert latest_lifecycle(
            connection, capture_id, context=context
        ) == CaptureLifecycleProjection.initial(owner_principal_id=owner, capture_id=capture_id)
        archive, restore = _events(connection, owner, capture_id, 2)
    with engine.connect() as connection:
        projection = latest_lifecycle(connection, capture_id, context=context)
        assert (projection.state, projection.revision, projection.archived_at) == (
            CaptureLifecycleState.ACTIVE,
            2,
            None,
        )
        assert projection.latest_event_id == restore.event_id
        assert lifecycle_history(connection, capture_id, context=context) == (archive, restore)
        assert lifecycle_history(connection, capture_id, context=context, limit=1) == (restore,)
        # Another Principal sees neither history nor state.
        stranger = capture_context(_principal())
        assert lifecycle_history(connection, capture_id, context=stranger) == ()
        assert latest_lifecycle(connection, capture_id, context=stranger).revision == 0
    with pytest.raises(ValueError), engine.connect() as connection:
        lifecycle_history(connection, capture_id, context=context, limit=MAX_LIFECYCLE_HISTORY + 1)


def test_a_value_naming_another_owner_is_refused_before_any_write(
    engine: Engine, root: tuple[str, str]
) -> None:
    owner, capture_id = root
    projection = CaptureLifecycleProjection.initial(owner_principal_id=owner, capture_id=capture_id)
    decision = decide_transition(projection, CaptureLifecycleOperation.ARCHIVE, 0)
    event = CaptureLifecycleEvent.following(
        projection,
        decision,
        event_id=issue_identifier(IdKind.CAPTURE_LIFECYCLE_EVENT),
        transitioned_at=WHEN,
        intent_digest=DIGEST,
        correlation_id=_corr(),
        audit_id=_audit(),
    )
    with pytest.raises(CallerSuppliedPrincipalError), engine.begin() as connection:
        record_lifecycle_event(connection, event, context=capture_context(_principal()))


def test_a_receipt_is_found_only_in_its_own_partition(
    engine: Engine, root: tuple[str, str]
) -> None:
    owner, capture_id = root
    receipt = CaptureLifecycleReceipt(
        receipt_id=issue_identifier(IdKind.CAPTURE_LIFECYCLE_RECEIPT),
        owner_principal_id=owner,
        idempotency_key="key-partitioned",
        capture_id=capture_id,
        operation=CaptureLifecycleOperation.RESTORE,
        intent_digest=DIGEST,
        expected_lifecycle_revision=0,
        resulting_lifecycle_revision=0,
        outcome=CaptureLifecycleOutcome.NO_OP,
        event_id=None,
        issued_at=WHEN,
        correlation_id=_corr(),
        audit_id=_audit(),
    )
    with engine.begin() as connection:
        record_lifecycle_receipt(connection, receipt, context=capture_context(owner))
    with engine.connect() as connection:
        assert lifecycle_receipt(connection, "key-partitioned", context=capture_context(owner)) == (
            receipt
        )
        assert (
            lifecycle_receipt(connection, "key-partitioned", context=capture_context(_principal()))
            is None
        )
        assert lifecycle_receipt(connection, "key-absent", context=capture_context(owner)) is None


def test_suspension_withdraws_unfinished_work_without_failing_it(engine: Engine) -> None:
    """Plan (f): queued gains the pause; running is requeued, fenced and refunded."""
    owner = _principal()
    with engine.begin() as connection:
        capture_id, (v1, v2) = _seed_capture(connection, owner, versions=2)
        other_capture, (other_version,) = _seed_capture(connection, owner)
        queued = _seed_job(connection, owner, v1, state="queued", attempts=1)
        running = _seed_job(connection, owner, v2, state="running", attempts=3)
        succeeded = _seed_job(connection, owner, v1, state="succeeded", attempts=1)
        failed = _seed_job(connection, owner, v2, state="failed", attempts=3)
        bystander = _seed_job(connection, owner, other_version, state="queued")
        before = {op: _job(connection, op) for op in (queued, succeeded, failed, bystander)}
    with engine.begin() as connection:
        assert lock_capture_root(connection, capture_id, context=capture_context(owner))
        assert suspend_capture_jobs(connection, capture_id, context=capture_context(owner)) == 2
    with engine.connect() as connection:
        after_queued = _job(connection, queued)
        assert after_queued["pause_cause"] == "capture_withdrawn"
        assert after_queued["state"] == "queued"
        for preserved in (
            "attempt_count",
            "next_attempt_at",
            "last_error_code",
            "lease_generation",
        ):
            assert after_queued[preserved] == before[queued][preserved], preserved
        after_running = _job(connection, running)
        assert after_running["state"] == "queued"
        assert after_running["pause_cause"] == "capture_withdrawn"
        assert after_running["lease_owner"] is None
        assert after_running["lease_expires_at"] is None
        assert after_running["lease_generation"] == 1
        assert after_running["attempt_count"] == 2
        assert after_running["last_error_code"] is None
        for untouched in (succeeded, failed, bystander):
            assert _job(connection, untouched) == before[untouched], untouched
    # A stranger suspends nothing of this root.
    with engine.begin() as connection:
        assert (
            suspend_capture_jobs(connection, capture_id, context=capture_context(_principal())) == 0
        )
    del other_capture


def test_the_overlay_refuses_a_pause_on_a_running_or_terminal_job(engine: Engine) -> None:
    owner = _principal()
    with engine.begin() as connection:
        _capture_id, (version,) = _seed_capture(connection, owner)
        running = _seed_job(connection, owner, version, state="running")
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.capture_jobs SET pause_cause = 'capture_withdrawn' "
                "WHERE operation_id = :id"
            ),
            {"id": running},
        )
    assert refused.value.orig.diag.constraint_name == "only_a_queued_capture_job_is_paused"  # type: ignore[union-attr]


def test_resumption_applies_then_current_eligibility(engine: Engine) -> None:
    """MR-C12: eligible work is cleared, ineligible work stays visibly paused."""
    owner = _principal()
    with engine.begin() as connection:
        capture_id, (v1, v2) = _seed_capture(connection, owner, versions=2)
        first = _seed_job(connection, owner, v1, state="queued")
        second = _seed_job(connection, owner, v2, state="queued")
        done = _seed_job(connection, owner, v1, state="succeeded")
    with engine.begin() as connection:
        lock_capture_root(connection, capture_id, context=capture_context(owner))
        suspend_capture_jobs(connection, capture_id, context=capture_context(owner))
    asked: list[CaptureProcessingSubject] = []

    def only_the_first(subject: CaptureProcessingSubject) -> CaptureProcessingEligibility:
        asked.append(subject)
        if subject.version_id == v1:
            return CaptureProcessingEligibility.ELIGIBLE
        return CaptureProcessingEligibility.INELIGIBLE

    with engine.begin() as connection:
        lock_capture_root(connection, capture_id, context=capture_context(owner))
        outcome = resume_capture_jobs(
            connection, capture_id, context=capture_context(owner), eligibility=only_the_first
        )
    assert outcome == JobResumption(resumed=1, still_paused=1)
    assert {subject.version_id for subject in asked} == {v1, v2}
    assert all(subject.owner_principal_id == owner for subject in asked)
    with engine.connect() as connection:
        assert _job(connection, first)["pause_cause"] is None
        assert _job(connection, second)["pause_cause"] == "current_policy_ineligible"
        assert _job(connection, done)["pause_cause"] is None
        assert _job(connection, done)["state"] == "succeeded"


def test_root_lock_serializes_two_lifecycle_writers(engine: Engine, root: tuple[str, str]) -> None:
    """The second `FOR NO KEY UPDATE` waits for the first and then sees its event."""
    owner, capture_id = root
    context = capture_context(owner)
    first_locked = threading.Event()
    release = threading.Event()
    seen: list[int] = []

    def first() -> None:
        with engine.begin() as connection:
            assert lock_capture_root(connection, capture_id, context=context)
            first_locked.set()
            release.wait(10)
            _events(connection, owner, capture_id, 1)

    worker = threading.Thread(target=first)
    worker.start()
    assert first_locked.wait(10)
    with engine.connect() as connection:
        with pytest.raises(DBAPIError) as blocked, connection.begin():
            connection.execute(text("SET LOCAL lock_timeout = '200ms'"))
            lock_capture_root(connection, capture_id, context=context)
        assert getattr(blocked.value.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE
    release.set()
    worker.join(10)
    with engine.begin() as connection:
        assert lock_capture_root(connection, capture_id, context=context)
        seen.append(latest_lifecycle(connection, capture_id, context=context).revision)
    assert seen == [1]
