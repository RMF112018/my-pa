"""Reports Modernization WP05b W3: retention, purge eligibility, trash preflight, held, scan.

The FAST tier, over the in-memory general report fake (`_GeneralReports`) and
in-memory report content stores. What it proves:

* the pure eligibility function, by its reason table (each reason, the
  reason order, days and calendar years, Feb 29, the `now == eligible_at`
  boundary) and the one clock start strategy (not trashed, trashed, restored
  then trashed again uses the newest delete);
* the retention policy history: unset by default (`no_policy`), set / modify
  / unset append-only with old, new, authority and time, stale revision,
  same-key replay and conflict, Principal scoping;
* the trash preflight: a missing or corrupt blob part, a blob with no store
  and a corrupt inline digest refuse the delete with ZERO lifecycle events;
  healthy inline and blob reports trash; archive and restore never preflight;
  the service answers `internal_error`;
* `held` on the standalone read, history and list outputs;
* the preservation scan: a corrupted and a missing part, an orphan.

The PostgreSQL behaviour (rows, the two-session race, a real filesystem
store, the operator command) is `tests/database/test_reports_retention.py`'s.
Every title, body and identifier is synthetic.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.report_preservation import scan_report_preservation
from my_pa.application.report_retention import report_purge_eligibility
from my_pa.contracts.ports import (
    ReportContentNamespace,
    ReportContentPart,
    ReportIdempotencyConflictError,
    ReportStalePolicyRevisionError,
    ReportTrashPreflightError,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.custody import (
    CustodyAuthority,
    HoldOperation,
    HoldRequest,
    PurgeEligibilityReason,
    RetentionClockStart,
    RetentionPeriod,
    RetentionSetRequest,
    RetentionUnit,
    preservation_seal_parts,
    purge_eligibility,
    retention_clock_start,
)
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import PublicationRequest
from my_pa.domain.reports.records import ReportLifecycleEventRecord
from my_pa.domain.reports.revision import LifecycleRequest
from my_pa.domain.reports.vocabulary import LifecycleOperation, LifecycleState
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import InMemoryReportContentStore, Scene, _GeneralReports, build_service

AUTHORITY: Final = CustodyAuthority("local_operator", "local_cli")
WHEN: Final = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
FOREIGN: Final = "prn_ffff0009ffff0009ffff0009"
REASON: Final = "Synthetic retention decision."
LOW: Final = 64
DAYS_30: Final = RetentionPeriod(30, RetentionUnit.DAYS)
YEARS_5: Final = RetentionPeriod(5, RetentionUnit.YEARS)


def _ids() -> dict[str, Any]:
    return {
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
    }


def _publish(
    reports: _GeneralReports,
    principal_id: str,
    content: dict[str, Any] | None = None,
    *,
    key: str = "pub",
    content_store: InMemoryReportContentStore | None = None,
    inline_max_bytes: int = 262_144,
) -> str:
    return reports.publish(
        PublicationRequest(
            title="Synthetic retained report",
            content=validate_content(content or {"format": "markdown", "body": "# Kept\n"}),
        ),
        principal_id=principal_id,
        creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal_id),
        idempotency_key=key,
        recorded_at=WHEN,
        content_store=content_store,
        inline_max_bytes=inline_max_bytes,
        **_ids(),
    ).receipt.report_id


def _move(
    reports: _GeneralReports,
    principal_id: str,
    operation: LifecycleOperation,
    report_id: str,
    revision: int,
    key: str,
    *,
    at: datetime = WHEN,
    content_store: InMemoryReportContentStore | None = None,
) -> None:
    reports.transition(
        LifecycleRequest(operation, report_id, revision),
        principal_id=principal_id,
        idempotency_key=key,
        recorded_at=at,
        content_store=content_store,
        **_ids(),
    )


def _set(
    reports: _GeneralReports,
    principal_id: str,
    period: RetentionPeriod | None,
    revision: int,
    key: str,
    *,
    at: datetime = WHEN,
    reason: str = REASON,
) -> Any:  # noqa: ANN401
    return reports.set_retention(
        RetentionSetRequest(period, revision, reason),
        principal_id=principal_id,
        idempotency_key=key,
        authority=AUTHORITY,
        recorded_at=at,
        **_ids(),
    )


def _event(revision: int, operation: LifecycleOperation, at: datetime) -> Any:  # noqa: ANN401
    prior, resulting = {
        LifecycleOperation.ARCHIVE: (LifecycleState.ACTIVE, LifecycleState.ARCHIVED),
        LifecycleOperation.DELETE: (LifecycleState.ACTIVE, LifecycleState.TRASHED),
        LifecycleOperation.RESTORE: (LifecycleState.TRASHED, LifecycleState.ACTIVE),
    }[operation]
    return ReportLifecycleEventRecord(
        event_id=issue_identifier(IdKind.REPORT_LIFECYCLE_EVENT),
        lifecycle_revision=revision,
        operation=operation,
        prior_state=prior,
        resulting_state=resulting,
        reason=None,
        transitioned_at=at,
    )


# ---- B1: the pure eligibility function ------------------------------------------------------


def test_a_retention_period_is_bounded_per_unit() -> None:
    assert RetentionPeriod(1, RetentionUnit.DAYS).as_dict() == {"count": 1, "unit": "days"}
    assert RetentionPeriod(36525, RetentionUnit.DAYS).count == 36525
    assert RetentionPeriod(100, RetentionUnit.YEARS).count == 100
    for count, unit in (
        (0, RetentionUnit.DAYS),
        (36526, RetentionUnit.DAYS),
        (0, RetentionUnit.YEARS),
        (101, RetentionUnit.YEARS),
    ):
        with pytest.raises(ReportValidationError) as raised:
            RetentionPeriod(count, unit)
        assert (raised.value.field, raised.value.code) == ("period.count", "bounds")
    with pytest.raises(ReportValidationError):
        RetentionPeriod(True, RetentionUnit.DAYS)
    with pytest.raises(ReportValidationError):
        RetentionPeriod(5, "years")  # type: ignore[arg-type]


def test_a_retention_set_request_validates_and_digests_its_caller_fields() -> None:
    first = RetentionSetRequest(YEARS_5, 0, REASON)
    assert first.intent_digest == RetentionSetRequest(YEARS_5, 0, REASON).intent_digest
    others = {
        RetentionSetRequest(None, 0, REASON).intent_digest,
        RetentionSetRequest(YEARS_5, 1, REASON).intent_digest,
        RetentionSetRequest(RetentionPeriod(5, RetentionUnit.DAYS), 0, REASON).intent_digest,
        RetentionSetRequest(YEARS_5, 0, "Another reason.").intent_digest,
    }
    assert first.intent_digest not in others and len(others) == 4
    bad: tuple[tuple[Any, Any, Any], ...] = (
        (YEARS_5, -1, REASON),
        (YEARS_5, True, REASON),
        (YEARS_5, 0, ""),
        ({"count": 5}, 0, REASON),
    )
    for period, revision, reason in bad:
        with pytest.raises(ReportValidationError):
            RetentionSetRequest(period, revision, reason)


START: Final = datetime(2026, 1, 10, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("period", "held", "state", "clock_start", "now", "reason"),
    [
        # no_policy outranks everything, held and trashed past any period included.
        (None, True, LifecycleState.TRASHED, START, START + timedelta(days=99999), "no_policy"),
        (None, False, LifecycleState.ACTIVE, None, START, "no_policy"),
        # held outranks not_trashed and an elapsed period.
        (DAYS_30, True, LifecycleState.TRASHED, START, START + timedelta(days=31), "held"),
        (DAYS_30, True, LifecycleState.ACTIVE, None, START, "held"),
        (DAYS_30, False, LifecycleState.ACTIVE, None, START, "not_trashed"),
        (DAYS_30, False, LifecycleState.ARCHIVED, None, START, "not_trashed"),
        (DAYS_30, False, LifecycleState.TRASHED, START, START, "retention_running"),
        (
            DAYS_30,
            False,
            LifecycleState.TRASHED,
            START,
            START + timedelta(days=30) - timedelta(microseconds=1),
            "retention_running",
        ),
        # The boundary: now == eligible_at is eligible.
        (DAYS_30, False, LifecycleState.TRASHED, START, START + timedelta(days=30), "eligible"),
        (YEARS_5, False, LifecycleState.TRASHED, START, START.replace(year=2031), "eligible"),
        (
            YEARS_5,
            False,
            LifecycleState.TRASHED,
            START,
            START.replace(year=2031) - timedelta(microseconds=1),
            "retention_running",
        ),
    ],
)
def test_purge_eligibility_by_its_reason_table(
    period: RetentionPeriod | None,
    held: bool,
    state: LifecycleState,
    clock_start: datetime | None,
    now: datetime,
    reason: str,
) -> None:
    answer = purge_eligibility(
        period=period, held=held, lifecycle_state=state, clock_start=clock_start, now=now
    )
    assert answer.reason is PurgeEligibilityReason(reason)
    assert answer.eligible is (reason == "eligible")
    assert answer.clock_start == clock_start
    assert answer.clock_start_strategy is RetentionClockStart.MOST_RECENT_TRASH_EVENT
    if period is not None and clock_start is not None:
        assert answer.eligible_at == period.added_to(clock_start)
    else:
        assert answer.eligible_at is None


def test_the_reason_order_is_exactly_the_contract_order() -> None:
    assert [member.value for member in PurgeEligibilityReason] == [
        "no_policy",
        "held",
        "not_trashed",
        "retention_running",
        "eligible",
    ]
    assert [member.value for member in RetentionClockStart] == ["most_recent_trash_event"]


def test_years_are_calendar_years_and_feb_29_lands_on_feb_28() -> None:
    leap = datetime(2028, 2, 29, 8, 0, tzinfo=UTC)
    assert RetentionPeriod(1, RetentionUnit.YEARS).added_to(leap) == datetime(
        2029, 2, 28, 8, 0, tzinfo=UTC
    )
    assert RetentionPeriod(4, RetentionUnit.YEARS).added_to(leap) == datetime(
        2032, 2, 29, 8, 0, tzinfo=UTC
    )
    # Days are whole days, whatever the calendar: 365 days from a leap Feb 29.
    assert RetentionPeriod(365, RetentionUnit.DAYS).added_to(leap) == datetime(
        2029, 2, 28, 8, 0, tzinfo=UTC
    )
    assert RetentionPeriod(1, RetentionUnit.DAYS).added_to(leap) == datetime(
        2028, 3, 1, 8, 0, tzinfo=UTC
    )
    # The arithmetic is in UTC whatever offset the start carries.
    offset = datetime(2026, 3, 1, 1, 0, tzinfo=UTC).astimezone(
        datetime.now(UTC).astimezone().tzinfo
    )
    assert RetentionPeriod(1, RetentionUnit.YEARS).added_to(offset) == datetime(
        2027, 3, 1, 1, 0, tzinfo=UTC
    )
    answer = purge_eligibility(
        period=RetentionPeriod(1, RetentionUnit.YEARS),
        held=False,
        lifecycle_state=LifecycleState.TRASHED,
        clock_start=leap,
        now=datetime(2029, 2, 28, 8, 0, tzinfo=UTC),
    )
    assert answer.eligible and answer.eligible_at == datetime(2029, 2, 28, 8, 0, tzinfo=UTC)


def test_eligibility_refuses_naive_and_inconsistent_inputs() -> None:
    common: dict[str, Any] = {"period": DAYS_30, "held": False}
    with pytest.raises(ReportValidationError):
        purge_eligibility(
            **common,
            lifecycle_state=LifecycleState.ACTIVE,
            clock_start=None,
            now=datetime(2026, 1, 1),
        )
    with pytest.raises(ReportValidationError):
        # A trashed report always has a clock under the one strategy.
        purge_eligibility(
            **common, lifecycle_state=LifecycleState.TRASHED, clock_start=None, now=START
        )
    with pytest.raises(ReportValidationError):
        purge_eligibility(
            **common, lifecycle_state=LifecycleState.ACTIVE, clock_start=START, now=START
        )


def test_the_clock_starts_at_the_newest_delete_of_a_trashed_report() -> None:
    strategy = RetentionClockStart.MOST_RECENT_TRASH_EVENT
    first, again = START, START + timedelta(days=40)
    trashed_once = [_event(1, LifecycleOperation.DELETE, first)]
    assert retention_clock_start(strategy, LifecycleState.TRASHED, trashed_once) == first
    restored = [*trashed_once, _event(2, LifecycleOperation.RESTORE, first + timedelta(days=1))]
    assert retention_clock_start(strategy, LifecycleState.ACTIVE, restored) is None
    retrashed = [*restored, _event(3, LifecycleOperation.DELETE, again)]
    # Restored then trashed again: the clock restarts at the newest delete,
    # whatever order the events arrive in.
    assert retention_clock_start(strategy, LifecycleState.TRASHED, retrashed) == again
    assert retention_clock_start(strategy, LifecycleState.TRASHED, retrashed[::-1]) == again
    assert retention_clock_start(strategy, LifecycleState.ACTIVE, []) is None
    assert (
        retention_clock_start(
            strategy, LifecycleState.ARCHIVED, [_event(1, LifecycleOperation.ARCHIVE, first)]
        )
        is None
    )
    with pytest.raises(ReportValidationError):
        retention_clock_start(strategy, LifecycleState.TRASHED, [])
    with pytest.raises(ReportValidationError):
        retention_clock_start("most_recent_trash_event", LifecycleState.TRASHED, trashed_once)  # type: ignore[arg-type]


# ---- B6: the retention policy history (fake) -------------------------------------------------


def test_retention_is_unset_by_default_so_every_report_is_no_policy(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    _move(reports, p, LifecycleOperation.DELETE, report, 0, "del")
    view = reports.retention_policy(principal_id=p)
    assert (view.current, view.history, view.policy_revision, view.period) == (None, (), 0, None)
    answer = report_purge_eligibility(
        reports, report, principal_id=p, now=WHEN + timedelta(days=365 * 200)
    )
    assert answer is not None
    assert (answer.eligible, answer.reason) == (False, PurgeEligibilityReason.NO_POLICY)
    assert answer.clock_start == WHEN and answer.eligible_at is None


def test_set_modify_and_unset_append_history_with_old_new_authority_and_time(
    scene: Scene,
) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    t1, t2, t3 = WHEN, WHEN + timedelta(hours=1), WHEN + timedelta(hours=2)
    first = _set(reports, p, YEARS_5, 0, "r1", at=t1)
    assert (first.policy_revision, first.period, first.previous_period, first.replayed) == (
        1,
        YEARS_5,
        None,
        False,
    )
    second = _set(reports, p, DAYS_30, 1, "r2", at=t2)
    assert (second.policy_revision, second.period, second.previous_period) == (2, DAYS_30, YEARS_5)
    third = _set(reports, p, None, 2, "r3", at=t3, reason="Unset by the operator.")
    assert (third.policy_revision, third.period, third.previous_period) == (3, None, DAYS_30)

    view = reports.retention_policy(principal_id=p)
    assert view.policy_revision == 3 and view.period is None
    assert [event.policy_revision for event in view.history] == [3, 2, 1]
    assert [(e.previous_period, e.period) for e in view.history] == [
        (DAYS_30, None),
        (YEARS_5, DAYS_30),
        (None, YEARS_5),
    ]
    assert [e.recorded_at for e in view.history] == [t3, t2, t1]
    assert all(e.authority == AUTHORITY for e in view.history)
    assert [e.predecessor_event_id for e in view.history] == [
        second.event_id,
        first.event_id,
        None,
    ]
    assert view.history[0].reason == "Unset by the operator."
    # Append-only: the earlier events are unchanged by the later ones.
    assert scene.world.general_report_retention_events[p][0].period == YEARS_5
    assert [
        e.policy_revision for e in reports.retention_policy(principal_id=p, history_limit=2).history
    ] == [3, 2]
    for limit in (0, 51, True):
        with pytest.raises(ReportValidationError):
            reports.retention_policy(principal_id=p, history_limit=limit)


def test_a_stale_revision_is_refused_and_writes_nothing(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    _set(reports, p, YEARS_5, 0, "r1")
    for revision in (0, 2):
        with pytest.raises(ReportStalePolicyRevisionError):
            _set(reports, p, DAYS_30, revision, f"stale-{revision}")
    assert len(scene.world.general_report_retention_events[p]) == 1


def test_a_same_key_replays_and_another_intent_under_it_conflicts(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    first = _set(reports, p, YEARS_5, 0, "r1")
    replay = _set(reports, p, YEARS_5, 0, "r1", at=WHEN + timedelta(days=1))
    assert replay == replace(first, replayed=True)
    with pytest.raises(ReportIdempotencyConflictError):
        _set(reports, p, DAYS_30, 0, "r1")
    with pytest.raises(ReportIdempotencyConflictError):
        _set(reports, p, YEARS_5, 1, "r1")
    assert len(scene.world.general_report_retention_events[p]) == 1


def test_policy_and_eligibility_are_principal_scoped(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    _set(reports, p, DAYS_30, 0, "r1")
    assert reports.retention_policy(principal_id=FOREIGN).current is None
    # The same key under another Principal is that Principal's own first write.
    assert _set(reports, FOREIGN, YEARS_5, 0, "r1").policy_revision == 1
    assert reports.retention_policy(principal_id=p).period == DAYS_30
    assert reports.retention_eligibility_inputs(report, principal_id=FOREIGN) is None
    assert report_purge_eligibility(reports, report, principal_id=FOREIGN, now=WHEN) is None
    missing = "grpt_" + "0" * 26
    assert report_purge_eligibility(reports, missing, principal_id=p, now=WHEN) is None


def test_eligibility_through_the_helper_follows_trash_hold_and_time(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    _set(reports, p, DAYS_30, 0, "r1")

    def reason(now: datetime) -> PurgeEligibilityReason:
        answer = report_purge_eligibility(reports, report, principal_id=p, now=now)
        assert answer is not None
        return answer.reason

    assert reason(WHEN) is PurgeEligibilityReason.NOT_TRASHED
    trashed_at = WHEN + timedelta(days=2)
    _move(reports, p, LifecycleOperation.DELETE, report, 0, "d1", at=trashed_at)
    assert reason(trashed_at + timedelta(days=29)) is PurgeEligibilityReason.RETENTION_RUNNING
    assert reason(trashed_at + timedelta(days=30)) is PurgeEligibilityReason.ELIGIBLE
    # Restored and trashed again: the clock restarts at the newest delete.
    _move(reports, p, LifecycleOperation.RESTORE, report, 1, "r1", at=trashed_at)
    again = trashed_at + timedelta(days=10)
    _move(reports, p, LifecycleOperation.DELETE, report, 2, "d2", at=again)
    assert reason(trashed_at + timedelta(days=30)) is PurgeEligibilityReason.RETENTION_RUNNING
    assert reason(again + timedelta(days=30)) is PurgeEligibilityReason.ELIGIBLE
    # A hold outranks an elapsed period; the report stays trashed and kept.
    reports.place_hold(
        HoldRequest(HoldOperation.PLACE, report, 0, REASON),
        principal_id=p,
        idempotency_key="h",
        authority=AUTHORITY,
        recorded_at=WHEN,
        preservation_store=InMemoryReportContentStore(ReportContentNamespace.PRESERVATION),
        content_store=None,
        **_ids(),
    )
    assert reason(again + timedelta(days=3000)) is PurgeEligibilityReason.HELD
    head = reports.read_version(report, principal_id=p)
    assert head is not None and head.root.lifecycle_state is LifecycleState.TRASHED


# ---- B4: the trash preflight (fake) ---------------------------------------------------------


def _blob_report(
    reports: _GeneralReports, p: str, store: InMemoryReportContentStore, key: str = "blob"
) -> tuple[str, str]:
    raw = ("Synthetic blob paragraph. " * 20).encode()
    report = _publish(
        reports,
        p,
        {"format": "text", "body": raw.decode()},
        key=key,
        content_store=store,
        inline_max_bytes=LOW,
    )
    head = reports.read_version(report, principal_id=p)
    assert head is not None
    return report, head.content_id


def _events(scene: Scene, p: str, report: str) -> list[Any]:
    return scene.world.general_report_events.get((p, report), [])


def test_a_missing_blob_part_refuses_the_delete_with_no_lifecycle_event(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    store = InMemoryReportContentStore()
    report, content_id = _blob_report(reports, p, store)
    del store.objects[content_id][ReportContentPart.DECODED]
    with pytest.raises(ReportTrashPreflightError):
        _move(reports, p, LifecycleOperation.DELETE, report, 0, "d", content_store=store)
    assert _events(scene, p, report) == []
    # No store at all is a missing part too.
    with pytest.raises(ReportTrashPreflightError):
        _move(reports, p, LifecycleOperation.DELETE, report, 0, "d")
    assert _events(scene, p, report) == []


def test_a_corrupt_blob_part_refuses_the_delete_with_no_lifecycle_event(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    store = InMemoryReportContentStore()
    report, content_id = _blob_report(reports, p, store)
    good = store.objects[content_id][ReportContentPart.DECODED]
    store.objects[content_id][ReportContentPart.DECODED] = good[:-1] + b"X"
    with pytest.raises(ReportTrashPreflightError):
        _move(reports, p, LifecycleOperation.DELETE, report, 0, "d", content_store=store)
    assert _events(scene, p, report) == []
    head = reports.read_version(report, principal_id=p)
    assert head is not None and head.root.lifecycle_state is LifecycleState.ACTIVE


def test_a_corrupt_inline_digest_refuses_the_delete_with_no_lifecycle_event(
    scene: Scene,
) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    key = (p, report)
    stored = scene.world.general_report_versions[key]
    tampered = replace(stored, content=replace(stored.content, decoded=b"# Tampered\n"))
    scene.world.general_report_versions[key] = tampered
    scene.world.general_report_ledger[key] = [tampered]
    with pytest.raises(ReportTrashPreflightError):
        _move(reports, p, LifecycleOperation.DELETE, report, 0, "d")
    assert _events(scene, p, report) == []
    assert scene.world.general_report_lifecycle_receipts == {}


def test_healthy_inline_and_blob_reports_trash_and_archive_restore_never_preflight(
    scene: Scene,
) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    store = InMemoryReportContentStore()
    inline = _publish(reports, p, key="inline")
    blob, content_id = _blob_report(reports, p, store)
    _move(reports, p, LifecycleOperation.DELETE, inline, 0, "d-inline", content_store=store)
    _move(reports, p, LifecycleOperation.DELETE, blob, 0, "d-blob", content_store=store)
    assert [e.operation for e in _events(scene, p, blob)] == [LifecycleOperation.DELETE]
    # Archive and restore move a report whose blob is gone: they never preflight.
    del store.objects[content_id]
    _move(reports, p, LifecycleOperation.RESTORE, blob, 1, "r-blob", content_store=store)
    _move(reports, p, LifecycleOperation.ARCHIVE, blob, 2, "a-blob")
    assert [e.operation.value for e in _events(scene, p, blob)] == [
        "delete",
        "restore",
        "archive",
    ]


def _invoke(
    service: Any,  # noqa: ANN401
    scene: Scene,
    capability: Capability,
    payload: dict[str, Any],
) -> dict[str, Any]:
    (purpose,) = permitted_purposes(capability)
    metadata, command = normalize(
        capability.value,
        {
            "request_id": "req",
            "purpose": purpose.value,
            "principal_id": scene.principal.principal_id,
            "requested_at": "2026-11-06T12:00:00Z",
            "payload": payload,
        },
    )
    answer = service.invoke(metadata, command, principal=scene.principal)
    return answer.model_dump(mode="json")  # type: ignore[no-any-return]


def test_the_service_answers_a_failed_preflight_as_internal_error(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    service = build_service(
        scene.world,
        scene.providers,
        report_content_store=store,
        report_content_inline_max_bytes=LOW,
    )
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report, content_id = _blob_report(reports, p, store)
    payload = {"report_id": report, "expected_lifecycle_revision": 0, "idempotency_key": "d"}
    store.objects[content_id][ReportContentPart.DECODED] = b"corrupt"
    refused = _invoke(service, scene, Capability.REPORTS_DELETE, payload)
    assert refused["result"] is None
    assert refused["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert refused["error"]["safe_details"] == []
    assert report not in json.dumps(refused["error"]) and content_id not in json.dumps(refused)
    assert _events(scene, p, report) == []


def test_the_service_passes_its_content_store_to_a_healthy_blob_delete(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    service = build_service(
        scene.world,
        scene.providers,
        report_content_store=store,
        report_content_inline_max_bytes=LOW,
    )
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report, _content_id = _blob_report(reports, p, store)
    payload = {"report_id": report, "expected_lifecycle_revision": 0, "idempotency_key": "d"}
    answer = _invoke(service, scene, Capability.REPORTS_DELETE, payload)
    assert answer["error"] is None
    assert answer["result"]["lifecycle_state"] == "trashed"


# ---- B7: held on the standalone read surfaces ----------------------------------------------


def test_held_is_on_read_history_and_list_and_follows_the_root_cache(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)

    def surfaces() -> tuple[Any, Any, Any]:
        read = _invoke(service, scene, Capability.REPORTS_READ, {"report_id": report})
        history = _invoke(service, scene, Capability.REPORTS_HISTORY, {"report_id": report})
        listed = _invoke(service, scene, Capability.REPORTS_LIST, {"plane": "standalone"})
        everything = _invoke(service, scene, Capability.REPORTS_LIST, {"plane": "all"})
        assert read["error"] is None and history["error"] is None and listed["error"] is None
        (item,) = listed["result"]["items"]
        (merged,) = [i for i in everything["result"]["items"] if i["report_id"] == report]
        assert item["held"] is merged["held"]
        return read["result"]["held"], history["result"]["held"], item["held"]

    assert surfaces() == (False, False, False)
    placed = reports.place_hold(
        HoldRequest(HoldOperation.PLACE, report, 0, REASON),
        principal_id=p,
        idempotency_key="h",
        authority=AUTHORITY,
        recorded_at=WHEN,
        preservation_store=InMemoryReportContentStore(ReportContentNamespace.PRESERVATION),
        content_store=None,
        **_ids(),
    )
    assert surfaces() == (True, True, True)
    read = _invoke(service, scene, Capability.REPORTS_READ, {"report_id": report})
    text = json.dumps(read["result"])
    # Only the boolean: never the reason, event, actor or seal.
    assert placed.event_id not in text and REASON not in text
    assert placed.preservation is not None
    assert placed.preservation.seal_object_id not in text


# ---- B5: the preservation scan (fake) -------------------------------------------------------


def test_the_scan_finds_corrupted_and_missing_parts_and_orphans(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    preservation = InMemoryReportContentStore(ReportContentNamespace.PRESERVATION)

    def place(report: str, principal_id: str = p) -> Any:  # noqa: ANN401
        return reports.place_hold(
            HoldRequest(HoldOperation.PLACE, report, 0, REASON),
            principal_id=principal_id,
            idempotency_key=f"h-{report}",
            authority=AUTHORITY,
            recorded_at=WHEN,
            preservation_store=preservation,
            content_store=None,
            **_ids(),
        )

    mine = place(_publish(reports, p, key="a"))
    theirs = place(_publish(reports, FOREIGN, key="b"), FOREIGN)
    clean = scan_report_preservation(reports, preservation)
    # Across Principals: the other Principal's copy is checked, not an orphan.
    assert (clean.checked, clean.missing, clean.mismatched, clean.orphans) == (2, (), (), ())
    assert clean.consistent and clean.intact and clean.integrity_findings == 0

    # An orphan alone (finding 2) is informational: intact, but not fully consistent.
    early = issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT)
    preservation.put(early, decoded=b"left behind earlier", original=None)
    orphaned = scan_report_preservation(reports, preservation)
    assert orphaned.orphans == (early,) and orphaned.integrity_findings == 0
    assert orphaned.intact and not orphaned.consistent

    def listed(result: Any) -> list[str]:  # noqa: ANN401
        data = preservation.objects[result.preservation.seal_object_id][ReportContentPart.DECODED]
        return sorted({part.preservation_object_id for part in preservation_seal_parts(data)})

    seal = mine.preservation.seal_object_id
    (corrupted,) = listed(mine)
    (their_object,) = listed(theirs)
    good = preservation.objects[corrupted][ReportContentPart.DECODED]
    preservation.objects[corrupted][ReportContentPart.DECODED] = good[:-1] + b"Z"
    del preservation.objects[their_object][ReportContentPart.DECODED]
    orphan = issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT)
    preservation.put(orphan, decoded=b"left behind by a failed placement", original=None)

    scan = scan_report_preservation(reports, preservation)
    assert scan.checked == 2 and not scan.consistent
    assert scan.missing == ((their_object, ReportContentPart.DECODED),)
    assert [(m.object_id, m.part, m.mismatch) for m in scan.mismatched] == [
        (corrupted, ReportContentPart.DECODED, "digest")
    ]
    assert scan.orphans == tuple(sorted((early, orphan)))
    # The two orphans are not integrity findings; the corrupt and the missing part are.
    assert scan.integrity_findings == 2 and not scan.intact

    # A missing seal is reported as missing; its objects cannot be attributed.
    del preservation.objects[seal]
    lost = scan_report_preservation(reports, preservation)
    assert (seal, ReportContentPart.DECODED) in lost.missing
    assert corrupted in lost.orphans
