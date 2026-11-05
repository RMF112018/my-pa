"""Reports Modernization WP03, RM-AC-009: real concurrency on the report root lock.

The `database` tier, on a disposable head-migrated clone per test. Two writers
on two separate connections: writer A takes the root lock and writes, holding
its transaction open; writer B, on a thread, is observed BLOCKED on a lock in
`pg_stat_activity` before A commits; after A commits, B proceeds and gets the
typed answer (stale version, stale lifecycle revision, or a replay of A's
receipt) and nothing of B commits. WP04 C11(2) adds the cross-report case:
one key on two reports, where B blocks on the receipt key rather than the
root, and settles as an idempotency conflict.

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

from my_pa.contracts.ports import (
    ReportIdempotencyConflictError,
    ReportStaleLifecycleRevisionError,
    ReportStaleVersionError,
)
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


def _update_any(connection: Connection, report_id: str, key: str) -> UpdateResult:
    return _update_on(connection, report_id, f"Title {report_id[-4:]}", key)


def _archive_any(connection: Connection, report_id: str, key: str) -> LifecycleResult:
    return _transition_on(connection, LifecycleOperation.ARCHIVE, report_id, key)


@pytest.mark.parametrize(
    ("write", "grown"),
    [
        (_update_any, ("report_versions", "report_version_manifests", "report_receipts")),
        (_archive_any, ("report_lifecycle_events", "report_receipts")),
    ],
    ids=["update", "transition"],
)
def test_one_key_on_two_reports_settles_the_loser_as_a_conflict(
    migrated_engine: Engine,
    write: Callable[[Connection, str, str], object],
    grown: tuple[str, ...],
) -> None:
    """WP04 C11(2): the cross-report same-key settle path of update and transition.

    A writes report 1 under key K and holds its transaction; B locks report 2
    (no contention on the root) and blocks only on the receipt key's unique
    index. A commits: B's insert violates the key constraint, its SAVEPOINT
    rolls back, and the settle reads A's receipt, bound to another intent:
    `ReportIdempotencyConflictError`. Only A's rows are committed.
    """
    first = _publish_committed(migrated_engine, _request(), "pub-1").receipt.report_id
    second = _publish_committed(
        migrated_engine, _request(title="Second"), "pub-2"
    ).receipt.report_id
    before = _counts(migrated_engine)
    winner, outcome = _race(
        migrated_engine,
        lambda c: write(c, first, "shared-key"),
        lambda c: write(c, second, "shared-key"),
    )
    assert isinstance(outcome.get("error"), ReportIdempotencyConflictError), outcome
    assert "result" not in outcome
    assert getattr(winner, "report_id", None) == first
    after = _counts(migrated_engine)
    assert after == {table: count + (1 if table in grown else 0) for table, count in before.items()}
    with migrated_engine.connect() as connection:
        roots = {
            str(row[0]): (int(row[1]), int(row[2]))
            for row in connection.execute(
                text(
                    "SELECT report_id, head_version_number, lifecycle_revision "
                    "FROM knowledge.report_roots WHERE report_id IN (:a, :b)"
                ),
                {"a": first, "b": second},
            )
        }
        keyed = connection.execute(
            text(
                "SELECT report_id FROM knowledge.report_receipts "
                "WHERE idempotency_key = 'shared-key'"
            )
        ).scalars()
        assert list(keyed) == [first]
    assert roots[second] == (1, 0)
    assert roots[first] != (1, 0)
