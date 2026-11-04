"""Reports Modernization WP03, RM-AC-009: real concurrency on the report root lock.

The `database` tier, on a disposable head-migrated clone per test. Two writers
on two separate connections: writer A takes the root lock and writes, holding
its transaction open; writer B, on a thread, is observed BLOCKED on a lock in
`pg_stat_activity` before A commits; after A commits, B proceeds and gets the
typed answer (stale version, stale lifecycle revision, or a replay of A's
receipt) and nothing of B commits.

No test can hang: B runs with `SET LOCAL lock_timeout = '20s'`, the wait for
the lock is bounded, and the thread join has a timeout.

Every identifier, title and byte is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, text

from my_pa.contracts.ports import ReportStaleLifecycleRevisionError, ReportStaleVersionError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.revision import (
    LifecycleRequest,
    LifecycleResult,
    ReportPatch,
    UpdateRequest,
    UpdateResult,
)
from my_pa.domain.reports.vocabulary import LifecycleOperation, ReceiptOutcome
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from tests.database.test_reports_general_persistence import (
    PRINCIPAL_A,
    _counts,
    _publish_committed,
    _request,
    _wait_until,
)

pytestmark = pytest.mark.database

JOIN_SECONDS: Final = 30.0


def _update_on(connection: Connection, report_id: str, title: str, key: str) -> UpdateResult:
    return SqlGeneralReportRepository(connection).update(
        UpdateRequest(
            report_id=report_id,
            expected_version=1,
            patch=ReportPatch(title=title),
            change_reason="Concurrent change.",
        ),
        principal_id=PRINCIPAL_A,
        idempotency_key=key,
        recorded_at=datetime.now(UTC),
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
    )


def _transition_on(
    connection: Connection, operation: LifecycleOperation, report_id: str, key: str
) -> LifecycleResult:
    return SqlGeneralReportRepository(connection).transition(
        LifecycleRequest(operation, report_id, 0),
        principal_id=PRINCIPAL_A,
        idempotency_key=key,
        recorded_at=datetime.now(UTC),
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
    )


def _blocked_on_a_lock(engine: Engine) -> bool:
    with engine.connect() as observer:
        return bool(
            observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND state = 'active'"
                )
            ).scalar_one()
        )


def _race[T](
    engine: Engine,
    first: Callable[[Connection], object],
    second: Callable[[Connection], T],
) -> tuple[object, dict[str, object]]:
    """Run `first` on A and hold it; run `second` on B; prove B blocked; commit A."""
    outcome: dict[str, object] = {}

    def writer_b() -> None:
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '20s'"))
                outcome["result"] = second(connection)
        except Exception as error:  # the typed refusal is the assertion target
            outcome["error"] = error

    connection_a = engine.connect()
    transaction = connection_a.begin()
    thread = threading.Thread(target=writer_b, daemon=True)
    try:
        winner = first(connection_a)
        thread.start()
        assert _wait_until(lambda: _blocked_on_a_lock(engine)), "writer B never blocked"
        assert thread.is_alive()
        assert not outcome, "writer B finished while A held the root lock"
        transaction.commit()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection_a.close()
    thread.join(timeout=JOIN_SECONDS)
    assert not thread.is_alive(), "writer B did not finish after A committed"
    return winner, outcome


def test_two_updates_of_one_version_commit_exactly_one(migrated_engine: Engine) -> None:
    report_id = _publish_committed(migrated_engine, _request(), "pub").receipt.report_id
    before = _counts(migrated_engine)
    winner, outcome = _race(
        migrated_engine,
        lambda c: _update_on(c, report_id, "Writer A", "key-a"),
        lambda c: _update_on(c, report_id, "Writer B", "key-b"),
    )
    assert isinstance(winner, UpdateResult) and winner.version_number == 2
    assert isinstance(outcome.get("error"), ReportStaleVersionError), outcome
    after = _counts(migrated_engine)
    # Only A's rows: one version, manifest and receipt; B committed nothing.
    assert after["report_versions"] == before["report_versions"] + 1
    assert after["report_version_manifests"] == before["report_version_manifests"] + 1
    assert after["report_receipts"] == before["report_receipts"] + 1
    assert after["report_content_objects"] == before["report_content_objects"]
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT version_number, title FROM knowledge.report_versions "
                "WHERE report_id = :r AND version_number = 2"
            ),
            {"r": report_id},
        ).all()
        keys = connection.execute(
            text("SELECT idempotency_key FROM knowledge.report_receipts WHERE operation = 'update'")
        ).scalars()
        assert list(keys) == ["key-a"]
    assert [tuple(row) for row in rows] == [(2, "Writer A")]


def test_two_same_key_updates_replay_the_first(migrated_engine: Engine) -> None:
    report_id = _publish_committed(migrated_engine, _request(), "pub").receipt.report_id
    before = _counts(migrated_engine)
    winner, outcome = _race(
        migrated_engine,
        lambda c: _update_on(c, report_id, "Same", "same-key"),
        lambda c: _update_on(c, report_id, "Same", "same-key"),
    )
    assert "error" not in outcome, outcome.get("error")
    loser = outcome["result"]
    assert isinstance(winner, UpdateResult) and isinstance(loser, UpdateResult)
    assert loser.replayed is True and winner.replayed is False
    assert (loser.receipt_id, loser.version_id) == (winner.receipt_id, winner.version_id)
    after = _counts(migrated_engine)
    assert after["report_versions"] == before["report_versions"] + 1
    assert after["report_receipts"] == before["report_receipts"] + 1


@pytest.mark.parametrize(
    ("operation_a", "operation_b"),
    [
        (LifecycleOperation.ARCHIVE, LifecycleOperation.ARCHIVE),
        (LifecycleOperation.ARCHIVE, LifecycleOperation.DELETE),
        (LifecycleOperation.DELETE, LifecycleOperation.DELETE),
    ],
)
def test_two_transitions_of_one_revision_commit_exactly_one(
    migrated_engine: Engine, operation_a: LifecycleOperation, operation_b: LifecycleOperation
) -> None:
    report_id = _publish_committed(migrated_engine, _request(), "pub").receipt.report_id
    before = _counts(migrated_engine)
    winner, outcome = _race(
        migrated_engine,
        lambda c: _transition_on(c, operation_a, report_id, "key-a"),
        lambda c: _transition_on(c, operation_b, report_id, "key-b"),
    )
    assert isinstance(winner, LifecycleResult)
    assert winner.outcome is ReceiptOutcome.APPLIED and winner.lifecycle_revision == 1
    assert isinstance(outcome.get("error"), ReportStaleLifecycleRevisionError), outcome
    after = _counts(migrated_engine)
    assert after["report_lifecycle_events"] == before["report_lifecycle_events"] + 1
    assert after["report_receipts"] == before["report_receipts"] + 1
    with migrated_engine.connect() as connection:
        revision = connection.execute(
            text("SELECT lifecycle_revision FROM knowledge.report_roots WHERE report_id = :r"),
            {"r": report_id},
        ).scalar_one()
    assert revision == 1


def test_two_same_key_transitions_replay_the_first(migrated_engine: Engine) -> None:
    report_id = _publish_committed(migrated_engine, _request(), "pub").receipt.report_id
    winner, outcome = _race(
        migrated_engine,
        lambda c: _transition_on(c, LifecycleOperation.DELETE, report_id, "same"),
        lambda c: _transition_on(c, LifecycleOperation.DELETE, report_id, "same"),
    )
    assert "error" not in outcome, outcome.get("error")
    loser = outcome["result"]
    assert isinstance(winner, LifecycleResult) and isinstance(loser, LifecycleResult)
    assert loser.replayed is True
    assert (loser.receipt_id, loser.event_id) == (winner.receipt_id, winner.event_id)
