"""Reports Modernization WP05b W3: retention history, trash preflight, held and scan on PostgreSQL.

The `database` tier, each test on its own disposable head-migrated clone
(`migrated_engine`) and a real `FilesystemReportContentStore` per namespace
under one root in `tmp_path` (`Stores`, shared with the hold suite). What it
proves:

* the retention policy history: set / modify / unset append-only rows with
  old, new, authority and time (an UPDATE is refused by the table); stale
  revision; same-key replay and conflict; the two-session race on one
  revision (one wins, the other is stale, or replays its own key); Principal
  scoping; eligibility through the application helper;
* the trash preflight: a missing blob file, a corrupt blob file and a corrupt
  inline digest refuse the delete with ZERO lifecycle rows; healthy inline
  and blob reports trash;
* `held` on the SQL catalog page;
* the preservation scan and `apps/cli/report_content.py preservation-verify`:
  exit 0 when every copy verifies, 2 with a corrupted part, a missing part
  and an orphan, each named by identifier and part only; orphans apart from
  integrity findings (finding 2): orphans alone exit 0 (listed), 3 with
  `--fail-on-orphans`, an integrity finding 2 whatever the flag, a refusal 1.

Every identifier, title and byte is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import report_content as report_content_cli
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.report_preservation import scan_report_preservation
from my_pa.application.report_retention import report_purge_eligibility
from my_pa.contracts.ports import (
    ReportContentPart,
    ReportContentStore,
    ReportIdempotencyConflictError,
    ReportStalePolicyRevisionError,
    ReportTrashPreflightError,
)
from my_pa.domain.common.identifiers import IdKind, parse_identifier
from my_pa.domain.reports.catalog import CatalogFilters
from my_pa.domain.reports.custody import (
    HoldOperation,
    PurgeEligibilityReason,
    RetentionPeriod,
    RetentionResult,
    RetentionSetRequest,
    RetentionUnit,
    preservation_seal_parts,
)
from my_pa.domain.reports.revision import LifecycleRequest, LifecycleResult
from my_pa.domain.reports.vocabulary import LifecycleOperation
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from tests.database.test_reports_custody import (
    AUTHORITY,
    Stores,
    _hold,
    _lifecycle_rows,
    _now,
    _publish,
    _race,
)
from tests.database.test_reports_general_persistence import PRINCIPAL_A, PRINCIPAL_B

pytestmark = pytest.mark.database

REASON: Final = "Synthetic retention decision."
DAYS_30: Final = RetentionPeriod(30, RetentionUnit.DAYS)
YEARS_5: Final = RetentionPeriod(5, RetentionUnit.YEARS)
BLOB_BODY: Final = "Synthetic blob paragraph. " * 20


@pytest.fixture
def stores(tmp_path: Path) -> Stores:
    return Stores(tmp_path)


def _set_on(
    connection: Connection,
    period: RetentionPeriod | None,
    revision: int,
    key: str,
    *,
    principal_id: str = PRINCIPAL_A,
    reason: str = REASON,
) -> RetentionResult:
    return SqlGeneralReportRepository(connection).set_retention(
        RetentionSetRequest(period, revision, reason),
        principal_id=principal_id,
        idempotency_key=key,
        authority=AUTHORITY,
        **_now(),
    )


def _set(engine: Engine, *args: Any, **kwargs: Any) -> RetentionResult:  # noqa: ANN401
    with engine.begin() as connection:
        return _set_on(connection, *args, **kwargs)


def _retention_rows(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.report_retention_policy_events")
            ).scalar_one()
        )


def _delete_on(
    connection: Connection,
    report_id: str,
    revision: int,
    key: str,
    *,
    content_store: ReportContentStore | None = None,
    operation: LifecycleOperation = LifecycleOperation.DELETE,
) -> LifecycleResult:
    return SqlGeneralReportRepository(connection).transition(
        LifecycleRequest(operation, report_id, revision),
        principal_id=PRINCIPAL_A,
        idempotency_key=key,
        content_store=content_store,
        **_now(),
    )


def _delete(engine: Engine, *args: Any, **kwargs: Any) -> LifecycleResult:  # noqa: ANN401
    with engine.begin() as connection:
        return _delete_on(connection, *args, **kwargs)


def _content_part(stores: Stores, content_id: str, part: ReportContentPart) -> Path:
    _kind, suffix = parse_identifier(content_id)
    return stores.root / "content" / suffix[:2] / content_id / part.value


def _content_id(engine: Engine, report_id: str) -> str:
    with engine.connect() as connection:
        head = SqlGeneralReportRepository(connection).read_version(
            report_id, principal_id=PRINCIPAL_A
        )
    assert head is not None
    return head.content_id


# ---- B6: the retention policy history -------------------------------------------------------


def test_set_modify_and_unset_append_rows_with_old_new_authority_and_time(
    migrated_engine: Engine,
) -> None:
    engine = migrated_engine
    first = _set(engine, YEARS_5, 0, "r1")
    second = _set(engine, DAYS_30, 1, "r2")
    third = _set(engine, None, 2, "r3", reason="Unset by the operator.")
    assert [(r.policy_revision, r.previous_period, r.period) for r in (first, second, third)] == [
        (1, None, YEARS_5),
        (2, YEARS_5, DAYS_30),
        (3, DAYS_30, None),
    ]
    with engine.connect() as connection:
        view = SqlGeneralReportRepository(connection).retention_policy(principal_id=PRINCIPAL_A)
        rows = connection.execute(
            text(
                "SELECT policy_revision, period_count, period_unit, previous_period_count, "
                "previous_period_unit, authority_class, decision_channel "
                "FROM knowledge.report_retention_policy_events ORDER BY policy_revision"
            )
        ).all()
    assert view.policy_revision == 3 and view.period is None
    assert [e.event_id for e in view.history] == [third.event_id, second.event_id, first.event_id]
    assert [e.predecessor_event_id for e in view.history] == [
        second.event_id,
        first.event_id,
        None,
    ]
    assert all(e.authority == AUTHORITY for e in view.history)
    assert [e.recorded_at for e in view.history] == sorted(
        (e.recorded_at for e in view.history), reverse=True
    )
    assert [tuple(row) for row in rows] == [
        (1, 5, "years", None, None, "local_operator", "local_cli"),
        (2, 30, "days", 5, "years", "local_operator", "local_cli"),
        (3, None, None, 30, "days", "local_operator", "local_cli"),
    ]
    # Append-only: the table refuses to rewrite history.
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text("UPDATE knowledge.report_retention_policy_events SET reason = 'rewritten'")
        )
    with engine.connect() as connection:
        limited = SqlGeneralReportRepository(connection).retention_policy(
            principal_id=PRINCIPAL_A, history_limit=1
        )
    assert [e.policy_revision for e in limited.history] == [3]


def test_stale_replay_and_conflict_write_nothing_more(migrated_engine: Engine) -> None:
    engine = migrated_engine
    first = _set(engine, YEARS_5, 0, "r1")
    with pytest.raises(ReportStalePolicyRevisionError):
        _set(engine, DAYS_30, 0, "r2")
    with pytest.raises(ReportStalePolicyRevisionError):
        _set(engine, DAYS_30, 2, "r2")
    replay = _set(engine, YEARS_5, 0, "r1")
    assert replay.replayed and replay.event_id == first.event_id
    assert replay.recorded_at == first.recorded_at
    with pytest.raises(ReportIdempotencyConflictError):
        _set(engine, DAYS_30, 0, "r1")
    assert _retention_rows(engine) == 1


@pytest.mark.parametrize("same_key", [False, True], ids=["other-key", "same-key"])
def test_two_sessions_setting_one_revision_one_wins(
    migrated_engine: Engine, same_key: bool
) -> None:
    engine = migrated_engine
    winner, outcome = _race(
        engine,
        lambda c: _set_on(c, YEARS_5, 0, "race-a"),
        lambda c: _set_on(c, YEARS_5, 0, "race-a" if same_key else "race-b"),
    )
    assert isinstance(winner, RetentionResult) and winner.policy_revision == 1
    if same_key:
        replayed = outcome.get("result")
        assert isinstance(replayed, RetentionResult), outcome
        assert replayed.replayed and replayed.event_id == winner.event_id
    else:
        assert isinstance(outcome.get("error"), ReportStalePolicyRevisionError), outcome
    assert _retention_rows(engine) == 1


def test_policy_and_eligibility_are_principal_scoped(migrated_engine: Engine) -> None:
    engine = migrated_engine
    report = _publish(engine)
    _set(engine, DAYS_30, 0, "r1")
    with engine.connect() as connection:
        repository = SqlGeneralReportRepository(connection)
        assert repository.retention_policy(principal_id=PRINCIPAL_B).current is None
        assert repository.retention_eligibility_inputs(report, principal_id=PRINCIPAL_B) is None
        assert (
            report_purge_eligibility(
                repository, report, principal_id=PRINCIPAL_B, now=datetime.now(UTC)
            )
            is None
        )
    # The same key under another Principal is that Principal's own revision 1.
    assert _set(engine, YEARS_5, 0, "r1", principal_id=PRINCIPAL_B).policy_revision == 1


def test_eligibility_reads_the_newest_delete_and_the_policy(migrated_engine: Engine) -> None:
    engine = migrated_engine
    report = _publish(engine)

    def eligibility(now: datetime) -> Any:  # noqa: ANN401
        with engine.connect() as connection:
            return report_purge_eligibility(
                SqlGeneralReportRepository(connection), report, principal_id=PRINCIPAL_A, now=now
            )

    assert eligibility(datetime.now(UTC)).reason is PurgeEligibilityReason.NO_POLICY
    _set(engine, DAYS_30, 0, "r1")
    assert eligibility(datetime.now(UTC)).reason is PurgeEligibilityReason.NOT_TRASHED
    trashed = _delete(engine, report, 0, "d1")
    answer = eligibility(trashed.issued_at + timedelta(days=30))
    assert answer.reason is PurgeEligibilityReason.ELIGIBLE
    assert answer.clock_start == trashed.issued_at
    assert answer.eligible_at == trashed.issued_at + timedelta(days=30)
    running = eligibility(trashed.issued_at + timedelta(days=29))
    assert running.reason is PurgeEligibilityReason.RETENTION_RUNNING


# ---- B4: the trash preflight ----------------------------------------------------------------


def test_a_missing_blob_file_refuses_the_delete_with_zero_lifecycle_rows(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    report = _publish(engine, {"format": "text", "body": BLOB_BODY}, content_store=stores.content)
    _content_part(stores, _content_id(engine, report), ReportContentPart.DECODED).unlink()
    with pytest.raises(ReportTrashPreflightError):
        _delete(engine, report, 0, "d", content_store=stores.content)
    with pytest.raises(ReportTrashPreflightError):
        _delete(engine, report, 0, "d")  # no store: the blob is missing too
    assert _lifecycle_rows(engine, report) == 0


def test_a_corrupt_blob_file_refuses_the_delete_with_zero_lifecycle_rows(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    report = _publish(engine, {"format": "text", "body": BLOB_BODY}, content_store=stores.content)
    path = _content_part(stores, _content_id(engine, report), ReportContentPart.DECODED)
    data = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(data[:-1] + b"X")
    with pytest.raises(ReportTrashPreflightError):
        _delete(engine, report, 0, "d", content_store=stores.content)
    assert _lifecycle_rows(engine, report) == 0


def test_a_corrupt_inline_digest_refuses_the_delete_with_zero_lifecycle_rows(
    migrated_engine: Engine,
) -> None:
    """The plane is append-only: the tamper exists only inside this test's transaction.

    `session_replication_role = replica` (the lineage suites' precedent) skips
    the append-only trigger for the one UPDATE; JSON inline data has no SQL
    digest CHECK. The role is restored before the delete, which then runs on
    the same transaction and is rolled back with it.
    """
    engine = migrated_engine
    report = _publish(engine, {"format": "json", "data": {"kept": True}})
    content_id = _content_id(engine, report)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            changed = connection.execute(
                text(
                    "UPDATE knowledge.report_content_objects "
                    "SET inline_data = '{\"kept\": false}'::jsonb WHERE content_id = :c"
                ),
                {"c": content_id},
            ).rowcount
            assert changed == 1
            connection.execute(text("SET LOCAL session_replication_role = origin"))
            with pytest.raises(ReportTrashPreflightError):
                _delete_on(connection, report, 0, "d")
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM knowledge.report_lifecycle_events "
                        "WHERE report_id = :r"
                    ),
                    {"r": report},
                ).scalar_one()
                == 0
            )
        finally:
            transaction.rollback()
    assert _lifecycle_rows(engine, report) == 0


def test_healthy_inline_and_blob_reports_pass_the_preflight(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    inline = _publish(engine, key="inline")
    blob = _publish(
        engine, {"format": "text", "body": BLOB_BODY}, key="blob", content_store=stores.content
    )
    assert _delete(engine, inline, 0, "d-inline").resulting_state.value == "trashed"
    assert (
        _delete(engine, blob, 0, "d-blob", content_store=stores.content).resulting_state.value
        == "trashed"
    )
    # Restore never preflights: it moves a report whose blob is gone.
    _content_part(stores, _content_id(engine, blob), ReportContentPart.DECODED).unlink()
    restored = _delete(engine, blob, 1, "r-blob", operation=LifecycleOperation.RESTORE)
    assert restored.resulting_state.value == "active"


# ---- B7: held on the catalog page -----------------------------------------------------------


def test_the_catalog_page_reads_the_root_hold_cache(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    held = _publish(engine, key="held")
    free = _publish(engine, key="free")
    _hold(engine, HoldOperation.PLACE, held, "h", 0, store=stores.preservation)
    with engine.connect() as connection:
        page = SqlGeneralReportRepository(connection).catalog_page(
            principal_id=PRINCIPAL_A, filters=CatalogFilters(), query=None, after=None, limit=10
        )
    assert {entry.report_id: entry.held for entry in page} == {held: True, free: False}


# ---- B5: the preservation scan and its operator command -------------------------------------


def test_preservation_verify_finds_a_corrupt_part_a_missing_part_and_an_orphan(
    migrated_engine: Engine,
    stores: Stores,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = migrated_engine
    mine = _hold(
        engine, HoldOperation.PLACE, _publish(engine, key="a"), "h-a", 0, store=stores.preservation
    )
    theirs = _hold(
        engine,
        HoldOperation.PLACE,
        _publish(engine, key="b", principal_id=PRINCIPAL_B),
        "h-b",
        0,
        store=stores.preservation,
        principal_id=PRINCIPAL_B,
    )
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", str(stores.root))
    assert report_content_cli.main(["preservation-verify"]) == 0
    out = capsys.readouterr().out
    # Across Principals: both copies checked, neither an orphan.
    assert "holds_checked 2" in out and "orphaned_objects 0" in out
    assert str(stores.root) not in out

    def listed(result: Any) -> str:  # noqa: ANN401
        seal = stores.part_path(result.preservation.seal_object_id, ReportContentPart.DECODED)
        (object_id,) = {
            p.preservation_object_id for p in preservation_seal_parts(seal.read_bytes())
        }
        return object_id

    corrupt, lost = listed(mine), listed(theirs)
    path = stores.part_path(corrupt, ReportContentPart.DECODED)
    data = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(data[:-1] + b"Z")
    stores.part_path(lost, ReportContentPart.DECODED).unlink()
    orphan = issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT)
    stores.preservation.put(orphan, decoded=b"left behind by a failed placement", original=None)

    with engine.connect() as connection:
        scan = scan_report_preservation(SqlGeneralReportRepository(connection), stores.preservation)
    assert scan.checked == 2 and not scan.consistent
    assert scan.missing == ((lost, ReportContentPart.DECODED),)
    assert [(m.object_id, m.part, m.mismatch) for m in scan.mismatched] == [
        (corrupt, ReportContentPart.DECODED, "digest")
    ]
    assert scan.orphans == (orphan,)

    assert report_content_cli.main(["preservation-verify"]) == 2
    out = capsys.readouterr().out
    assert f"missing {lost} decoded" in out
    assert f"mismatch {corrupt} decoded digest" in out
    assert f"orphan {orphan}" in out
    assert str(stores.root) not in out

    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", "")
    assert report_content_cli.main(["preservation-verify"]) == 1


def test_preservation_verify_exit_codes_keep_orphans_apart_from_integrity_findings(
    migrated_engine: Engine,
    stores: Stores,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = migrated_engine
    placed = _hold(
        engine, HoldOperation.PLACE, _publish(engine, key="a"), "h-a", 0, store=stores.preservation
    )
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", str(stores.root))

    def run(*flags: str) -> tuple[int, str]:
        code = report_content_cli.main(["preservation-verify", *flags])
        out = capsys.readouterr().out
        assert str(stores.root) not in out
        return code, out

    # Clean: 0, with or without the flag.
    for flags in ((), ("--fail-on-orphans",)):
        code, out = run(*flags)
        assert code == report_content_cli.EXIT_OK == 0
        assert "integrity_findings 0" in out and "orphans 0" in out
        assert "orphans_informational" not in out

    # Orphan only: 0 and listed in its own section; 3 with --fail-on-orphans.
    orphan = issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT)
    stores.preservation.put(orphan, decoded=b"left behind by a failed placement", original=None)
    code, out = run()
    assert code == 0
    assert "integrity_findings 0" in out and "orphans 1" in out
    section = out.index("orphans_informational")
    assert out.index(f"orphan {orphan}") > section
    code, out = run("--fail-on-orphans")
    assert code == report_content_cli.EXIT_ORPHANS == 3 and f"orphan {orphan}" in out

    seal = stores.part_path(placed.preservation.seal_object_id, ReportContentPart.DECODED)
    (listed,) = {p.preservation_object_id for p in preservation_seal_parts(seal.read_bytes())}
    path = stores.part_path(listed, ReportContentPart.DECODED)
    kept = path.read_bytes()
    path.chmod(0o600)

    # A corrupt referenced part (an orphan present too): 2, with or without the flag.
    path.write_bytes(kept[:-1] + b"Z")
    for flags in ((), ("--fail-on-orphans",)):
        code, out = run(*flags)
        assert code == report_content_cli.EXIT_INCONSISTENT == 2
        assert f"mismatch {listed} decoded digest" in out and "integrity_findings 1" in out
        assert f"orphan {orphan}" in out

    # A missing referenced part: 2.
    path.unlink()
    code, out = run()
    assert code == 2 and f"missing {listed} decoded" in out and "missing_parts 1" in out

    # Operational errors and usage errors: 1.
    code, _out = run("--no-such-flag")
    assert code == report_content_cli.EXIT_REFUSED == 1
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", "")
    code, _out = run("--fail-on-orphans")
    assert code == 1
