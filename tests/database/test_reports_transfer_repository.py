"""Reports Modernization WP06 B3/B6: the transfer session repository on PostgreSQL.

The `database` tier, each test on its own disposable head clone
(`migrated_engine`) with a filesystem transfer staging under `tmp_path`.

* The behaviour table (`tests/report_transfer_behaviour.py`, also run against
  the fake in `tests/unit/test_reports_transfer_repository_fake.py`): keyed
  begin replay and conflict, the T6 quotas per client / owner / declared bytes
  with expired and aborted sessions uncounted, append order, identical replay,
  different-bytes conflict, gap, ahead, oversize, wrong non-final size,
  overrun, append on a finalized session, the whole-digest check and a
  tampered staged chunk, finalize incomplete / settled, the uniform
  `not_found` of every claim, lock and abort refusal, consumption, abort
  outcomes, and the GC queries.
* PostgreSQL-only: concurrent begins on two real sessions serialize on the
  per-owner advisory lock (B observed blocked, then refused by the quota), and
  eight concurrent begins on eight connections admit exactly four;
  `expire_due` skips a row another transaction holds (`SKIP LOCKED`); begin's
  keyed-expired-but-not-reaped branch ends the keyed session both when the
  reap skipped it (held) and when it was past the reap limit; the chunk
  is staged BEFORE the ledger INSERT (a failing INSERT leaves an unledgered
  file that a later identical append reuses); the row facts the repository
  wrote; no `knowledge.intelligence_*` row changes.

No test can hang: lock waits are bounded (`lock_timeout`), thread joins time
out. Every identifier, title and byte is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeVar

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.pool import NullPool

from my_pa.contracts.ports import (
    ReportIdempotencyConflictError,
    ReportTransferQuotaError,
    ReportTransferRepository,
    TransferBegin,
)
from my_pa.domain.reports.vocabulary import TransferState
from my_pa.infrastructure.persistence import report_transfers
from my_pa.infrastructure.persistence.report_transfers import SqlReportTransferRepository
from my_pa.infrastructure.report_content_stores.staging import FilesystemReportTransferStaging
from tests.database.test_reports_general_persistence import (
    _intelligence_counts,
    _publish_committed,
    _request,
    _wait_until,
)
from tests.report_transfer_behaviour import (
    CLIENT_1,
    EXPIRED,
    PRINCIPAL_A,
    SCENARIOS,
    T0,
    THREE,
    append,
    begin,
    declaration,
    lock,
    payload,
    pieces,
    sha,
)

pytestmark = pytest.mark.database

T = TypeVar("T")
JOIN_SECONDS: Final = 30.0


class SqlHarness:
    def __init__(self, engine: Engine, root: Path) -> None:
        self.engine = engine
        root.mkdir()
        self.staging_root = root
        self.staging = FilesystemReportTransferStaging(root)
        self._published = 0

    def tx(self, work: Callable[[ReportTransferRepository], T]) -> T:
        with self.engine.begin() as connection:
            return work(SqlReportTransferRepository(connection))

    def content_id(self, principal_id: str) -> str:
        self._published += 1
        result = _publish_committed(
            self.engine, _request(), f"content-{self._published}", principal_id=principal_id
        )
        return result.content_id


def _harness(engine: Engine, tmp_path: Path) -> SqlHarness:
    return SqlHarness(engine, tmp_path / "staging")


def _begin_on(connection: Connection, key: str) -> object:
    return SqlReportTransferRepository(connection).begin(
        declaration(byte_count=10),
        principal_id=PRINCIPAL_A,
        client_ref=CLIENT_1,
        idempotency_key=key,
        now=T0,
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


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
        )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_behaviour_table_on_postgres(
    migrated_engine: Engine, tmp_path: Path, name: str
) -> None:
    before = _intelligence_counts(migrated_engine)
    SCENARIOS[name](_harness(migrated_engine, tmp_path))
    assert _intelligence_counts(migrated_engine) == before


def test_a_concurrent_begin_waits_for_the_owner_lock_then_meets_the_quota(
    migrated_engine: Engine,
) -> None:
    for i in range(3):
        with migrated_engine.begin() as connection:
            _begin_on(connection, f"pre-{i}")
    outcome: dict[str, object] = {}

    def writer_b() -> None:
        try:
            with migrated_engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '20s'"))
                outcome["result"] = _begin_on(connection, "b")
        except Exception as error:  # the typed refusal is the assertion target
            outcome["error"] = error

    connection_a = migrated_engine.connect()
    transaction = connection_a.begin()
    thread = threading.Thread(target=writer_b, daemon=True)
    try:
        _begin_on(connection_a, "a")  # the fourth live session, uncommitted
        thread.start()
        assert _wait_until(lambda: _blocked_on_a_lock(migrated_engine)), "B never blocked"
        assert thread.is_alive() and not outcome
        transaction.commit()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection_a.close()
    thread.join(timeout=JOIN_SECONDS)
    assert not thread.is_alive()
    assert isinstance(outcome.get("error"), ReportTransferQuotaError), outcome
    assert _count(migrated_engine, "report_transfer_sessions") == 4


def test_eight_concurrent_begins_admit_exactly_the_client_quota(migrated_engine: Engine) -> None:
    # Eight real connections at once: unpooled, so no checkout waits on another.
    engine = create_engine(migrated_engine.url, poolclass=NullPool)
    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def run(index: int) -> None:
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '20s'"))
                barrier.wait(timeout=20)
                _begin_on(connection, f"race-{index}")
            outcomes.append("begun")
        except ReportTransferQuotaError:
            outcomes.append("quota")
        except Exception as error:  # surfaced by the assertion below
            outcomes.append(type(error).__name__)

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_SECONDS)
    engine.dispose()
    assert sorted(outcomes) == ["begun"] * 4 + ["quota"] * 4
    assert _count(migrated_engine, "report_transfer_sessions") == 4


def test_expire_due_skips_a_session_another_transaction_holds(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    harness = _harness(migrated_engine, tmp_path)
    held, _ = begin(harness, declaration(payload(5), ttl=300), "held")
    free, _ = begin(harness, declaration(payload(5), ttl=600), "free")
    due = T0 + (free.expires_at - T0) * 2
    connection_a = migrated_engine.connect()
    transaction = connection_a.begin()
    try:
        SqlReportTransferRepository(connection_a).lock_usable(
            held.session_id, principal_id=PRINCIPAL_A, client_ref=CLIENT_1, now=T0
        )
        with migrated_engine.begin() as connection_b:
            connection_b.execute(text("SET LOCAL lock_timeout = '5s'"))
            moved = SqlReportTransferRepository(connection_b).expire_due(now=due, limit=10)
        assert moved == (free.session_id,)
    finally:
        transaction.rollback()
        connection_a.close()
    assert harness.tx(lambda r: r.expire_due(now=due, limit=10)) == (held.session_id,)
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT session_id, state FROM knowledge.report_transfer_sessions")
        ).all()
    states = {str(row[0]): str(row[1]) for row in rows}
    assert states == {held.session_id: "expired", free.session_id: "expired"}


def _states(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT session_id, state FROM knowledge.report_transfer_sessions")
        ).all()
    return {str(row[0]): str(row[1]) for row in rows}


def test_a_keyed_session_the_reap_skipped_while_held_is_ended_by_the_keyed_branch(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """WP08 C-WP06 (review WP06 R2 #1): `begin`'s keyed-expired-but-not-reaped branch.

    The keyed session is expired by time but held by another transaction, so
    the reap's `SKIP LOCKED` passes it by; the keyed `FOR UPDATE` waits; once
    the holder rolls back, the keyed lookup finds it live by state and expired
    by time, and the branch ends it, frees the key, names it among the reaped
    ids and begins a NEW session for the same declaration.
    """
    harness = _harness(migrated_engine, tmp_path)
    decl = declaration(payload(5), ttl=300)
    stale, _ = begin(harness, decl, "k-held")
    outcome: dict[str, object] = {}

    def writer_b() -> None:
        try:
            with migrated_engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '20s'"))
                outcome["result"] = SqlReportTransferRepository(connection).begin(
                    decl,
                    principal_id=PRINCIPAL_A,
                    client_ref=CLIENT_1,
                    idempotency_key="k-held",
                    now=EXPIRED,
                )
        except Exception as error:  # surfaced by the assertion below
            outcome["error"] = error

    connection_a = migrated_engine.connect()
    transaction = connection_a.begin()
    thread = threading.Thread(target=writer_b, daemon=True)
    try:
        connection_a.execute(
            text(
                "SELECT session_id FROM knowledge.report_transfer_sessions "
                "WHERE session_id = :session_id FOR UPDATE"
            ),
            {"session_id": stale.session_id},
        ).one()
        thread.start()
        assert _wait_until(lambda: _blocked_on_a_lock(migrated_engine)), "B never blocked"
        assert thread.is_alive() and not outcome
    finally:
        transaction.rollback()
        connection_a.close()
    thread.join(timeout=JOIN_SECONDS)
    assert not thread.is_alive()
    begun = outcome.get("result")
    assert isinstance(begun, TransferBegin), outcome
    assert begun.replayed is False
    assert begun.session.session_id != stale.session_id
    assert begun.session.state is TransferState.OPEN
    assert begun.reaped_session_ids == (stale.session_id,)
    assert _states(migrated_engine) == {
        stale.session_id: "expired",
        begun.session.session_id: "open",
    }
    # The key now binds the new session: replay, then conflict on another intent.
    assert begin(harness, decl, "k-held", now=EXPIRED) == (begun.session, True)
    with pytest.raises(ReportIdempotencyConflictError):
        begin(harness, declaration(payload(7)), "k-held", now=EXPIRED)


def test_a_keyed_session_past_the_reap_limit_is_ended_by_the_keyed_branch(
    migrated_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP08 C-WP06 (review WP06 R2 #1): the same branch when the keyed row is past the limit.

    With the reap bound lowered to 1, the older expired session fills it and
    the keyed one (expired later) is left for the keyed branch, which ends it
    too: both are named reaped, oldest first, and a new session begins.
    """
    monkeypatch.setattr(report_transfers, "TRANSFER_BEGIN_REAP_LIMIT", 1)
    harness = _harness(migrated_engine, tmp_path)
    older, _ = begin(harness, declaration(payload(5), ttl=300), "k-older")
    keyed_decl = declaration(payload(6), ttl=600)
    keyed, _ = begin(harness, keyed_decl, "k-keyed")
    begun = harness.tx(
        lambda r: r.begin(
            keyed_decl,
            principal_id=PRINCIPAL_A,
            client_ref=CLIENT_1,
            idempotency_key="k-keyed",
            now=EXPIRED,
        )
    )
    assert begun.replayed is False
    assert begun.session.session_id not in {older.session_id, keyed.session_id}
    assert begun.reaped_session_ids == (older.session_id, keyed.session_id)
    assert _states(migrated_engine) == {
        older.session_id: "expired",
        keyed.session_id: "expired",
        begun.session.session_id: "open",
    }


def test_the_chunk_is_staged_before_its_ledger_insert(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    harness = _harness(migrated_engine, tmp_path)
    session, _ = begin(harness, declaration(THREE), "k")
    first = pieces(THREE)[0]
    # In this disposable clone only: make the ledger INSERT fail.
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION knowledge.wp06_test_refuse() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'refused by the test'; END; $$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER wp06_test_refuse BEFORE INSERT ON knowledge.report_transfer_chunks "
                "FOR EACH ROW EXECUTE FUNCTION knowledge.wp06_test_refuse()"
            )
        )
    with pytest.raises(Exception, match="refused by the test"):
        append(harness, session.session_id, 0, first)
    staged = [p for p in harness.staging_root.rglob("*") if p.is_file()]
    assert [p.name for p in staged] == [f"00-{sha(first)}"]
    assert _count(migrated_engine, "report_transfer_chunks") == 0
    assert lock(harness, session.session_id).received_byte_count == 0
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DROP TRIGGER wp06_test_refuse ON knowledge.report_transfer_chunks")
        )
    _chunk, replayed = append(harness, session.session_id, 0, first)
    assert replayed is False
    assert [p.name for p in harness.staging_root.rglob("*") if p.is_file()] == [f"00-{sha(first)}"]
    assert _count(migrated_engine, "report_transfer_chunks") == 1
    assert lock(harness, session.session_id).received_byte_count == len(first)


def test_the_rows_hold_what_the_repository_wrote(migrated_engine: Engine, tmp_path: Path) -> None:
    harness = _harness(migrated_engine, tmp_path)
    session, _ = begin(harness, declaration(THREE), "k")
    for sequence, piece in enumerate(pieces(THREE)):
        append(harness, session.session_id, sequence, piece)
    with migrated_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT owner_principal_id, client_ref, state, chunk_byte_limit, "
                    "received_byte_count, declared_byte_count, idempotency_key, intent_digest, "
                    "content_token_digest FROM knowledge.report_transfer_sessions"
                )
            )
            .mappings()
            .one()
        )
        ledger = connection.execute(
            text(
                "SELECT sequence, byte_offset, byte_count, chunk_sha256, owner_principal_id "
                "FROM knowledge.report_transfer_chunks ORDER BY sequence"
            )
        ).all()
    assert dict(row) == {
        "owner_principal_id": PRINCIPAL_A,
        "client_ref": CLIENT_1,
        "state": "open",
        "chunk_byte_limit": 262144,
        "received_byte_count": len(THREE),
        "declared_byte_count": len(THREE),
        "idempotency_key": "k",
        "intent_digest": declaration(THREE).intent_digest,
        "content_token_digest": None,
    }
    assert [tuple(r) for r in ledger] == [
        (i, i * 262144, len(p), sha(p), PRINCIPAL_A) for i, p in enumerate(pieces(THREE))
    ]
