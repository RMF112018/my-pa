"""WP3b-S3: `MeetingSyncApplier` over the FAST fakes (rulings D1, D4, D5, D7, D8, D9).

The FAST half; the database half is
`tests/database/test_meeting_sync_apply_application.py`. The staged rows are
written straight into the fake planes (the staging handler is S2's and proved
in `test_meeting_sync_ingest.py`); the applier, the provider sync and the
Meeting application are the real ones. Proved here: the latch gate (nothing
applied before it, everything after, a rerun idempotent); the publication
order and the per-source high-water gate (`skipped_stale`,
`skipped_ordering_conflict`); the key order of events within a publication;
the unbind tombstone suppressing a re-create until an explicit bind wins;
`not_seen` marked, restored on a sighting, suppressed by any quarantine, never
written without coverage, never touching the Meeting; the binding-writer lock
taken by every writer; a failed publication stopping its source; and the D6
series refusal over the explicit-bind path. Everything is synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.meeting_provider_sync import MeetingProviderSync, MeetingSyncOutcome
from my_pa.application.meeting_sync_apply import (
    APPLY_COUNT_NAMES,
    MeetingSyncApplier,
    publication_gate,
)
from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.ports import (
    IngestConsumer,
    IngestSnapshotRecord,
    IngestSnapshotStatus,
    IngestSourceRecord,
    MeetingProviderBindingRecord,
    MeetingProviderReconciliationPassRecord,
    MeetingSyncApplyOutcome,
    MeetingSyncEventRecord,
    MeetingSyncPublicationRecord,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.meeting.model import (
    MeetingCreateRequest,
    MeetingErrorField,
    MeetingInvalidRequestError,
    MeetingUpdateRequest,
)
from my_pa.domain.meeting_sync.binding import MeetingProviderBindRequest, ProviderBindAction
from my_pa.domain.meeting_sync.model import (
    EventStatus,
    MeetingSyncEvent,
    ProviderBindingState,
    ProviderEventIdFormat,
)
from my_pa.domain.meeting_sync.resolution import ResolutionDiagnostic
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import World
from tests.unit.communications_ingest_fakes import IngestUnitOfWork, IngestWorld

P: Final = "prn_msyncapply000001"
SOURCE: Final = "isrc_msyncapply00001"
CAL: Final = "cal-synthetic"
T0: Final = datetime(2026, 11, 24, 6, tzinfo=UTC)
START: Final = datetime(2026, 12, 1, 15, tzinfo=UTC)
WINDOW: Final = (datetime(2026, 11, 1, tzinfo=UTC), datetime(2027, 1, 31, tzinfo=UTC))
APP: Final = MeetingApplication()


def stamp(hours: int) -> datetime:
    return T0 - timedelta(hours=10) + timedelta(hours=hours)


@dataclass(frozen=True)
class Ev:
    """One staged event: its key and the provider-owned fields that matter here."""

    uid: str
    title: str = "Synthetic"
    start: datetime = START
    original: datetime | None = None
    status: EventStatus = EventStatus.CONFIRMED
    calendar: str = CAL


class Scene:
    def __init__(self) -> None:
        self.world = World()
        self.ingest = IngestWorld()
        self.now = T0
        self.ingest.sources[(P, SOURCE)] = IngestSourceRecord(
            ingest_source_id=SOURCE,
            consumer=IngestConsumer.MEETING_SYNC_V1,
            workspace_id="mcp",
            path_prefix="My PA/Daily Intelligence/meetings/",
            file_pattern="*-meetings.json",
            enabled=True,
            admitted_at=T0,
        )
        self.applier = MeetingSyncApplier(unit_of_work=self.uow, clock=self.clock)

    def uow(self) -> UnitOfWork:
        return IngestUnitOfWork(self.ingest, self.world)

    def clock(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now

    def stage(
        self,
        at: datetime,
        *events: Ev,
        sha: str | None = None,
        coverage: bool = False,
        quarantined: int = 0,
        source: str = SOURCE,
    ) -> str:
        snapshot_id = issue_identifier(IdKind.INGEST_SNAPSHOT)
        digest = sha or f"{len(self.ingest.snapshots):064x}"
        self.ingest.snapshots[(P, snapshot_id)] = IngestSnapshotRecord(
            snapshot_id=snapshot_id,
            ingest_source_id=source,
            file_sha256=digest,
            byte_count=1,
            observed_version_token=None,
            first_seen_at=self.now,
            status=IngestSnapshotStatus.INGESTED,
        )
        with self.uow() as unit:
            unit.meeting_sync.insert_publication(
                P,
                MeetingSyncPublicationRecord(
                    snapshot_id=snapshot_id,
                    ingest_source_id=source,
                    generated_at_utc=at,
                    record_count=len(events) + quarantined,
                    accepted_count=len(events),
                    quarantined_count=quarantined,
                    staged_at=self.now,
                    coverage_start_utc=WINDOW[0] if coverage else None,
                    coverage_end_utc=WINDOW[1] if coverage else None,
                    coverage_calendar_refs=(CAL,) if coverage else None,
                ),
            )
            unit.meeting_sync.insert_events(
                P,
                [
                    MeetingSyncEventRecord(
                        event_id=issue_identifier(IdKind.MEETING_SYNC_EVENT),
                        snapshot_id=snapshot_id,
                        record_ordinal=ordinal,
                        calendar_ref=event.calendar,
                        ical_uid=event.uid,
                        series_ical_uid=None if event.original is None else event.uid,
                        occurrence_original_start_utc=event.original,
                        start_utc=event.start,
                        end_utc=event.start + timedelta(hours=1),
                        timezone_name="UTC",
                        status=event.status,
                        title=event.title,
                        location_text=None,
                        virtual_meeting_url=None,
                        provider_event_id=None,
                        provider_event_id_format=ProviderEventIdFormat.UNKNOWN,
                        staged_at=self.now,
                    )
                    for ordinal, event in enumerate(events)
                ],
            )
        return snapshot_id

    def latch(self) -> None:
        with self.uow() as unit:
            unit.meeting_sync.insert_reconciliation_pass(
                P,
                MeetingProviderReconciliationPassRecord(
                    completed_at=self.now, reviewed_meetings=0, reconcile_correlation_id="corr_x"
                ),
            )

    def apply(self) -> dict[str, int]:
        counts = dict(self.applier.apply_pending(P).counts)
        assert {name for name in counts if not name.startswith("events_skipped_")} <= (
            APPLY_COUNT_NAMES
        )
        return counts

    def publication(self, snapshot_id: str) -> MeetingSyncPublicationRecord:
        record = self.world.meeting_sync_publications[(P, snapshot_id)]
        return record

    def binding(self, uid: str) -> MeetingProviderBindingRecord:
        (found,) = [
            b for (owner, _), b in self.world.meeting_provider_bindings.items() if b.ical_uid == uid
        ]
        return found

    def titles(self) -> list[str]:
        return sorted(m.title for (owner, _), m in self.world.meetings.items() if owner == P)


@pytest.fixture
def scene() -> Scene:
    return Scene()


# ---- the latch gate (D4) ----------------------------------------------------------


def test_nothing_applies_before_the_latch_and_everything_after(scene: Scene) -> None:
    first = scene.stage(stamp(1), Ev("uid-1"))
    second = scene.stage(stamp(2), Ev("uid-2"))
    assert scene.apply() == {"unapplied_awaiting_reconciliation": 2}
    assert scene.world.meetings == {}
    assert scene.world.meeting_provider_bindings == {}
    assert scene.publication(first).applied_at is None
    assert scene.world.provider_binding_writer_locks == []

    scene.latch()
    assert scene.apply() == {"events_created": 2, "publications_applied": 2}
    assert scene.titles() == ["Synthetic", "Synthetic"]
    for snapshot_id in (first, second):
        applied = scene.publication(snapshot_id)
        assert applied.apply_outcome is MeetingSyncApplyOutcome.APPLIED
        assert applied.apply_counts == {"events_created": 1}
    assert scene.binding("uid-1").origin_snapshot_id == first
    # A rerun finds nothing unapplied and writes nothing.
    meetings = dict(scene.world.meetings)
    assert scene.apply() == {}
    assert scene.world.meetings == meetings


def test_no_staged_publication_and_no_latch_reports_nothing(scene: Scene) -> None:
    assert scene.apply() == {}


# ---- order and the high-water gate (D8) -----------------------------------------


def test_publications_apply_in_stamp_order_whatever_the_staging_order(scene: Scene) -> None:
    scene.latch()
    later = scene.stage(stamp(2), Ev("uid-1", title="Later"))
    earlier = scene.stage(stamp(1), Ev("uid-1", title="Earlier"))
    assert scene.apply() == {
        "events_created": 1,
        "events_updated": 1,
        "publications_applied": 2,
    }
    assert scene.titles() == ["Later"]
    assert scene.publication(earlier).apply_counts == {"events_created": 1}
    assert scene.publication(later).apply_counts == {"events_updated": 1}


def test_an_older_publication_than_the_newest_applied_is_skipped_stale(scene: Scene) -> None:
    scene.latch()
    scene.stage(stamp(5), Ev("uid-1", title="Current"))
    assert scene.apply()["publications_applied"] == 1
    # Staged late, older stamp, and an unknown key: it must not create anything.
    stale = scene.stage(stamp(3), Ev("uid-1", title="Old"), Ev("uid-new"))
    assert scene.apply() == {"publications_skipped_stale": 1}
    assert scene.titles() == ["Current"]
    record = scene.publication(stale)
    assert (record.apply_outcome, record.apply_counts) == (
        MeetingSyncApplyOutcome.SKIPPED_STALE,
        {},
    )
    assert record.applied_at is not None


def test_an_equal_stamp_with_other_bytes_is_an_ordering_conflict(scene: Scene) -> None:
    scene.latch()
    first = scene.stage(stamp(4), Ev("uid-1", title="A"), sha="a" * 64)
    second = scene.stage(stamp(4), Ev("uid-1", title="B"), Ev("uid-2"), sha="b" * 64)
    assert scene.apply() == {
        "events_created": 1,
        "publications_applied": 1,
        "publications_skipped_ordering_conflict": 1,
    }
    assert scene.titles() == ["A"]
    assert scene.publication(first).apply_outcome is MeetingSyncApplyOutcome.APPLIED
    assert (
        scene.publication(second).apply_outcome is MeetingSyncApplyOutcome.SKIPPED_ORDERING_CONFLICT
    )


def test_a_skipped_publication_does_not_advance_the_high_water(scene: Scene) -> None:
    scene.latch()
    scene.stage(stamp(4), Ev("uid-1"), sha="a" * 64)
    scene.stage(stamp(4), Ev("uid-1"), sha="b" * 64)
    scene.apply()
    newer = scene.stage(stamp(5), Ev("uid-1", title="Newer"))
    assert scene.apply() == {"events_updated": 1, "publications_applied": 1}
    assert scene.publication(newer).apply_outcome is MeetingSyncApplyOutcome.APPLIED


def test_the_high_water_is_per_source(scene: Scene) -> None:
    other = "isrc_msyncapply00002"
    scene.ingest.sources[(P, other)] = IngestSourceRecord(
        ingest_source_id=other,
        consumer=IngestConsumer.MEETING_SYNC_V1,
        workspace_id="mcp",
        path_prefix="elsewhere/",
        file_pattern="*-meetings.json",
        enabled=True,
        admitted_at=T0,
    )
    scene.latch()
    scene.stage(stamp(5), Ev("uid-1"))
    older_elsewhere = scene.stage(stamp(1), Ev("uid-2"), source=other)
    assert scene.apply() == {"events_created": 2, "publications_applied": 2}
    assert scene.publication(older_elsewhere).apply_outcome is MeetingSyncApplyOutcome.APPLIED


@pytest.mark.parametrize(
    ("at", "high", "outcome"),
    [
        (stamp(2), None, MeetingSyncApplyOutcome.APPLIED),
        (stamp(2), stamp(1), MeetingSyncApplyOutcome.APPLIED),
        (stamp(1), stamp(2), MeetingSyncApplyOutcome.SKIPPED_STALE),
        (stamp(2), stamp(2), MeetingSyncApplyOutcome.SKIPPED_ORDERING_CONFLICT),
    ],
)
def test_the_gate_decision(
    at: datetime, high: datetime | None, outcome: MeetingSyncApplyOutcome
) -> None:
    assert publication_gate(at, high) is outcome


class _Recording(MeetingProviderSync):
    """The real sync, recording the key order it is called in (or failing on demand)."""

    def apply_event(  # type: ignore[override]
        self,
        uow: UnitOfWork,
        principal_id: str,
        event: MeetingSyncEvent,
        *,
        source_sha256: str,
        source_snapshot_id: str,
        now: datetime,
    ) -> MeetingSyncOutcome:
        if event.ical_uid == _RECORDING_FAIL[0]:
            raise RuntimeError("injected")
        _RECORDED.append(
            (event.calendar_ref, event.ical_uid, event.occurrence_original_start_utc, event.ordinal)
        )
        return MeetingProviderSync.apply_event(
            self,
            uow,
            principal_id,
            event,
            source_sha256=source_sha256,
            source_snapshot_id=source_snapshot_id,
            now=now,
        )


_RECORDED: list[tuple[str, str, datetime | None, int]] = []
_RECORDING_FAIL: list[str | None] = [None]


def test_events_apply_in_key_order_nulls_first(scene: Scene) -> None:
    _RECORDED.clear()
    _RECORDING_FAIL[0] = None
    scene.applier = MeetingSyncApplier(unit_of_work=scene.uow, clock=scene.clock, sync=_Recording())
    scene.latch()
    o1 = datetime(2026, 12, 2, 14, tzinfo=UTC)
    o2 = datetime(2026, 12, 9, 14, tzinfo=UTC)
    scene.stage(
        stamp(1),
        Ev("uid-b"),
        Ev("uid-s", original=o2, start=o2),
        Ev("uid-a", calendar="cal-z"),
        Ev("uid-s", original=o1, start=o1),
        Ev("uid-a"),
    )
    scene.apply()
    seen = list(_RECORDED)
    assert seen == [
        (CAL, "uid-a", None, 4),
        (CAL, "uid-b", None, 0),
        (CAL, "uid-s", o1, 3),
        (CAL, "uid-s", o2, 1),
        ("cal-z", "uid-a", None, 2),
    ]


def test_a_failed_publication_stops_its_source_and_is_retried(scene: Scene) -> None:
    _RECORDED.clear()
    _RECORDING_FAIL[0] = "uid-boom"
    scene.applier = MeetingSyncApplier(unit_of_work=scene.uow, clock=scene.clock, sync=_Recording())
    scene.latch()
    failing = scene.stage(stamp(1), Ev("uid-boom"))
    later = scene.stage(stamp(2), Ev("uid-2"))
    assert scene.apply() == {"publications_failed": 1}
    assert scene.publication(failing).applied_at is None
    assert scene.publication(later).applied_at is None
    _RECORDING_FAIL[0] = None
    assert scene.apply() == {"events_created": 2, "publications_applied": 2}


# ---- the binding-writer lock (D8) ---------------------------------------------------


def test_every_binding_writer_takes_the_principal_lock(scene: Scene) -> None:
    scene.latch()
    scene.stage(stamp(1), Ev("uid-1"))
    scene.apply()
    # The publication transaction takes it, then `apply_event` (re-entrant).
    assert scene.world.provider_binding_writer_locks == [P, P]
    meeting_id = scene.binding("uid-1").meeting_id
    scene.world.provider_binding_writer_locks.clear()
    with scene.uow() as unit:
        APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=meeting_id),
            1,
            "unbind-lock",
            T0,
        )
    assert scene.world.provider_binding_writer_locks == [P]


# ---- the tombstone (D5) -------------------------------------------------------------


def test_an_unbound_key_is_suppressed_until_an_explicit_bind_wins(scene: Scene) -> None:
    scene.latch()
    scene.stage(stamp(1), Ev("uid-1", title="Provider"))
    scene.apply()
    binding = scene.binding("uid-1")
    with scene.uow() as unit:
        unbound = APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(
                action=ProviderBindAction.UNBIND, meeting_id=binding.meeting_id
            ),
            1,
            "unbind-0001",
            T0,
        )
    ((owner, _), tombstone), *rest = scene.world.meeting_provider_key_tombstones.items()
    assert rest == [] and owner == P
    assert (tombstone.binding_id, tombstone.meeting_id) == (binding.binding_id, binding.meeting_id)
    assert (tombstone.calendar_ref, tombstone.ical_uid) == (CAL, "uid-1")
    assert tombstone.occurrence_original_start_utc is None
    assert tombstone.meeting_history_id == unbound.receipt.history_id

    # The next publication names the key again: nothing is created or bound.
    meetings = dict(scene.world.meetings)
    suppressed = scene.stage(stamp(2), Ev("uid-1", title="Provider again"))
    assert scene.apply() == {
        "events_skipped": 1,
        "events_skipped_unbound_key_suppressed": 1,
        "publications_applied": 1,
    }
    assert scene.world.meetings == meetings
    assert scene.world.meeting_provider_bindings == {}
    assert scene.publication(suppressed).apply_counts == {
        "events_skipped": 1,
        "events_skipped_unbound_key_suppressed": 1,
    }

    # An explicit bind of the key wins: the binding is read first.
    with scene.uow() as unit:
        APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(
                action=ProviderBindAction.BIND,
                meeting_id=binding.meeting_id,
                calendar_ref=CAL,
                ical_uid="uid-1",
            ),
            2,
            "rebind-0001",
            T0,
        )
    scene.stage(stamp(3), Ev("uid-1", title="Provider third"))
    assert scene.apply() == {"events_updated": 1, "publications_applied": 1}
    assert scene.titles() == ["Provider third"]
    assert len(scene.world.meeting_provider_key_tombstones) == 1  # it stays


def test_a_tombstone_suppresses_only_its_exact_key(scene: Scene) -> None:
    scene.latch()
    o1 = datetime(2026, 12, 2, 14, tzinfo=UTC)
    o2 = datetime(2026, 12, 9, 14, tzinfo=UTC)
    scene.stage(stamp(1), Ev("uid-s", original=o1, start=o1))
    scene.apply()
    meeting_id = scene.binding("uid-s").meeting_id
    with scene.uow() as unit:
        APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=meeting_id),
            1,
            "unbind-occ",
            T0,
        )
    scene.stage(stamp(2), Ev("uid-s", original=o1, start=o1), Ev("uid-s", original=o2, start=o2))
    assert scene.apply() == {
        "events_created": 1,
        "events_skipped": 1,
        "events_skipped_unbound_key_suppressed": 1,
        "publications_applied": 1,
    }
    assert scene.binding("uid-s").occurrence_original_start_utc == o2


# ---- not_seen (D7) ------------------------------------------------------------------


def _meeting_state(scene: Scene) -> dict[tuple[str, str], object]:
    return dict(scene.world.meetings)


def test_a_covered_absence_marks_not_seen_and_a_sighting_restores_it(scene: Scene) -> None:
    scene.latch()
    first = scene.stage(stamp(1), Ev("uid-1"), Ev("uid-2"), coverage=True)
    scene.apply()
    before = scene.binding("uid-2")
    meetings = _meeting_state(scene)
    history = dict(scene.world.meeting_history)

    absent = scene.stage(stamp(2), Ev("uid-1"), coverage=True)
    assert scene.apply() == {
        "bindings_marked_not_seen": 1,
        "events_unchanged": 1,
        "publications_applied": 1,
    }
    marked = scene.binding("uid-2")
    assert marked.provider_state is ProviderBindingState.NOT_SEEN
    assert marked.version == before.version + 1
    assert marked.last_applied_generated_at_utc == stamp(2)
    assert (marked.last_seen_source_sha256, marked.last_seen_snapshot_id) == (
        before.last_seen_source_sha256,
        first,
    )
    assert marked.last_seen_record_ordinal == before.last_seen_record_ordinal
    assert marked.last_seen_at == before.last_seen_at
    # The Meeting is never touched: no field, no version, no receipt.
    assert _meeting_state(scene) == meetings
    assert scene.world.meeting_history == history
    assert scene.publication(absent).apply_counts == {
        "bindings_marked_not_seen": 1,
        "events_unchanged": 1,
    }

    # Still absent: already not_seen, so not marked again.
    scene.stage(stamp(3), Ev("uid-1"), coverage=True)
    assert scene.apply() == {"events_unchanged": 1, "publications_applied": 1}
    assert scene.binding("uid-2").version == marked.version

    # Seen again: the ordinary refresh restores the state.
    scene.stage(stamp(4), Ev("uid-1"), Ev("uid-2"), coverage=True)
    assert scene.apply() == {
        "events_unchanged": 1,
        "events_updated": 1,
        "publications_applied": 1,
    }
    assert scene.binding("uid-2").provider_state is ProviderBindingState.ACTIVE


def test_any_quarantine_suppresses_the_whole_not_seen_pass(scene: Scene) -> None:
    scene.latch()
    scene.stage(stamp(1), Ev("uid-1"), Ev("uid-2"), coverage=True)
    scene.apply()
    suppressed = scene.stage(stamp(2), Ev("uid-1"), coverage=True, quarantined=1)
    assert scene.apply() == {
        "events_unchanged": 1,
        "not_seen_suppressed_quarantine": 1,
        "publications_applied": 1,
    }
    assert scene.binding("uid-2").provider_state is ProviderBindingState.ACTIVE
    assert scene.publication(suppressed).apply_counts == {
        "events_unchanged": 1,
        "not_seen_suppressed_quarantine": 1,
    }


def test_without_coverage_not_seen_is_never_written(scene: Scene) -> None:
    scene.latch()
    scene.stage(stamp(1), Ev("uid-1"), Ev("uid-2"))
    scene.apply()
    scene.stage(stamp(2), Ev("uid-1"))
    assert scene.apply() == {"events_unchanged": 1, "publications_applied": 1}
    assert scene.binding("uid-2").provider_state is ProviderBindingState.ACTIVE


def test_not_seen_reaches_only_covered_calendars_inside_the_window(scene: Scene) -> None:
    scene.latch()
    outside = WINDOW[1] + timedelta(days=1)
    scene.stage(
        stamp(1),
        Ev("uid-in"),
        Ev("uid-late", start=outside),
        Ev("uid-other", calendar="cal-uncovered"),
        Ev("uid-edge", start=WINDOW[1]),
    )
    scene.apply()
    scene.stage(stamp(2), coverage=True)
    assert scene.apply() == {"bindings_marked_not_seen": 2, "publications_applied": 1}
    states = {
        uid: scene.binding(uid).provider_state
        for uid in ("uid-in", "uid-late", "uid-other", "uid-edge")
    }
    assert states == {
        "uid-in": ProviderBindingState.NOT_SEEN,
        "uid-late": ProviderBindingState.ACTIVE,
        "uid-other": ProviderBindingState.ACTIVE,
        "uid-edge": ProviderBindingState.NOT_SEEN,  # the window is inclusive
    }


def test_an_explicit_bind_with_no_stamp_can_be_marked_not_seen(scene: Scene) -> None:
    scene.latch()
    with scene.uow() as unit:
        created = APP.create_meeting(
            unit,
            P,
            MeetingCreateRequest(title="Hand made", start_at=START, timezone_name="UTC"),
            "create-hand",
            T0,
        )
        APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(
                action=ProviderBindAction.BIND,
                meeting_id=created.meeting.meeting_id,
                calendar_ref=CAL,
                ical_uid="uid-hand",
            ),
            1,
            "bind-hand",
            T0,
        )
    scene.stage(stamp(1), coverage=True)
    assert scene.apply() == {"bindings_marked_not_seen": 1, "publications_applied": 1}
    marked = scene.binding("uid-hand")
    assert marked.provider_state is ProviderBindingState.NOT_SEEN
    assert marked.last_seen_source_sha256 is None


# ---- D6 over the explicit-bind path (R2-5(i)) ----------------------------------------


def test_d6_an_explicitly_bound_series_move_is_refused_until_the_unbind(scene: Scene) -> None:
    with scene.uow() as unit:
        meeting = APP.create_meeting(
            unit,
            P,
            MeetingCreateRequest(
                title="Bound", start_at=START, timezone_name="UTC", series_title="Mine"
            ),
            "create-d6",
            T0,
        ).meeting
        target = APP.create_meeting(
            unit,
            P,
            MeetingCreateRequest(
                title="Target", start_at=START, timezone_name="UTC", series_title="Target"
            ),
            "create-d6-target",
            T0,
        ).meeting
        original = datetime(2026, 12, 2, 14, tzinfo=UTC)
        APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(
                action=ProviderBindAction.BIND,
                meeting_id=meeting.meeting_id,
                calendar_ref=CAL,
                ical_uid="uid-d6",
                occurrence_original_start_utc=original,
                series_ical_uid="uid-d6",
            ),
            1,
            "bind-d6",
            T0,
        )
    move = MeetingUpdateRequest(
        meeting_id=meeting.meeting_id, meeting_series_id=target.meeting_series_id
    )
    for index, request in enumerate(
        (move, MeetingUpdateRequest(meeting_id=meeting.meeting_id, detach_series=True))
    ):
        with pytest.raises(MeetingInvalidRequestError) as refused, scene.uow() as unit:
            APP.update_meeting(unit, P, request, 2, f"move-d6-{index}", T0)
        assert refused.value.field is MeetingErrorField.MEETING_SERIES_CHANGE_REFUSED_PROVIDER_BOUND
    with scene.uow() as unit:
        APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(
                action=ProviderBindAction.UNBIND, meeting_id=meeting.meeting_id
            ),
            2,
            "unbind-d6",
            T0,
        )
        moved = APP.update_meeting(unit, P, move, 3, "move-d6-after", T0)
    assert moved.meeting.meeting_series_id == target.meeting_series_id
    assert len(scene.world.meeting_provider_key_tombstones) == 1


def test_the_resolution_vocabulary_gains_exactly_the_tombstone_skip() -> None:
    assert {member.value for member in ResolutionDiagnostic} == {
        "cancelled_unknown_skipped",
        "binding_kind_conflict",
        "stale_record_skipped",
        "ordering_conflict_skipped",
        "unbound_key_suppressed",
    }
