"""WP3b-S4: the reconciliation pass over the FAST fakes (rulings D2, D3, D4, D6, D8).

FAST. The pure values (`domain/meeting_sync/reconcile.py`), the D6
`adopt_provider_series` decision, and `MeetingProviderReconciliation` over the
in-memory `World`: the review's two side-by-side lists, its scope (cancelled
and older-than-lookback Meetings excluded, the lookback edge included) and
keyset paging; reconcile item isolation (a refused item rolls back alone),
marks that never version the Meeting, the latch written once and only when
nothing in scope is left unreviewed, an empty batch completing an empty pass,
D6 adopt moving a Meeting or creating its series, and whole-batch replay. The
database half is `tests/database/test_meeting_provider_reconcile.py`. Every
value is synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.application.commands import ReviewMeetingProviders
from my_pa.application.meeting_provider_reconcile import MeetingProviderReconciliation
from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.ports import MeetingSyncEventRecord, MeetingSyncPublicationRecord
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.meeting.model import (
    MeetingCreateRequest,
    MeetingCursorError,
    MeetingErrorField,
    MeetingInvalidRequestError,
    MeetingStatus,
    MeetingUpdateRequest,
)
from my_pa.domain.meeting_sync.binding import (
    BoundSeries,
    MeetingProviderBindRequest,
    ProviderBindAction,
    bind_decision,
)
from my_pa.domain.meeting_sync.model import COLLECTOR_LOOKBACK, EventStatus, ProviderEventIdFormat
from my_pa.domain.meeting_sync.reconcile import (
    MAX_RECONCILE_ITEMS,
    MAX_UNBOUND_PROVIDER_EVENTS,
    RECONCILE_ITEM_KEY_PREFIX,
    ReconcileItem,
    ReconcileItemAction,
    ReconcileItemOutcome,
    ReconciliationPassState,
    reconcile_item_key,
    review_scope_start,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import FakeUnitOfWork, World

P: Final = "prn_reconcileunit001"
NOW: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
SOON: Final = NOW + timedelta(days=3)
CAL: Final = "cal-synthetic"
SERIES_UID: Final = "uid-series@example.invalid"
ORIGINAL: Final = datetime(2026, 12, 2, 14, tzinfo=UTC)
APP: Final = MeetingApplication()
PASS: Final = MeetingProviderReconciliation(APP)
CORRELATION: Final = "corr_reconcileunit00001"
_SEQ = [0]


def _key() -> str:
    _SEQ[0] += 1
    return f"create-{_SEQ[0]:04d}"


class Scene:
    def __init__(self) -> None:
        self.world = World()
        self.uow = FakeUnitOfWork(self.world)

    def meeting(
        self,
        title: str = "Synthetic",
        *,
        start: datetime = SOON,
        series_title: str | None = None,
        series_id: str | None = None,
    ) -> str:
        return APP.create_meeting(
            self.uow,
            P,
            MeetingCreateRequest(
                title=title,
                start_at=start,
                timezone_name="UTC",
                series_title=series_title,
                meeting_series_id=series_id,
            ),
            _key(),
            NOW,
        ).meeting.meeting_id

    def record(self, meeting_id: str) -> Any:  # noqa: ANN401
        return self.world.meetings[(P, meeting_id)]

    def stage(self, *events: dict[str, Any], source: str = "isrc_reconcileunit001") -> list[str]:
        snapshot_id = issue_identifier(IdKind.INGEST_SNAPSHOT)
        self.uow.meeting_sync.insert_publication(
            P,
            MeetingSyncPublicationRecord(
                snapshot_id=snapshot_id,
                ingest_source_id=source,
                generated_at_utc=NOW,
                record_count=len(events),
                accepted_count=len(events),
                quarantined_count=0,
                staged_at=NOW,
            ),
        )
        ids: list[str] = []
        records = []
        for ordinal, event in enumerate(events):
            event_id = issue_identifier(IdKind.MEETING_SYNC_EVENT)
            ids.append(event_id)
            records.append(
                MeetingSyncEventRecord(
                    event_id=event_id,
                    snapshot_id=snapshot_id,
                    record_ordinal=ordinal,
                    calendar_ref=CAL,
                    ical_uid=event["uid"],
                    series_ical_uid=event.get("series"),
                    occurrence_original_start_utc=event.get("original"),
                    start_utc=event.get("start", SOON),
                    end_utc=event.get("start", SOON) + timedelta(hours=1),
                    timezone_name="UTC",
                    status=EventStatus.CONFIRMED,
                    title=event.get("title", "Provider title"),
                    location_text=None,
                    virtual_meeting_url=None,
                    provider_event_id=None,
                    provider_event_id_format=ProviderEventIdFormat.UNKNOWN,
                    staged_at=NOW,
                )
            )
        self.uow.meeting_sync.insert_events(P, records)
        return ids

    def reconcile(self, *items: ReconcileItem, key: str = "batch-0001") -> Any:  # noqa: ANN401
        with self.uow as unit:  # commits: the Record Events reach the feed
            return PASS.reconcile(unit, P, items, key, NOW, correlation_id=CORRELATION)

    def review(self, **kwargs: Any) -> Any:  # noqa: ANN401
        return PASS.review(self.uow, P, now=NOW, **kwargs)


def bind(meeting_id: str, version: int = 1, **fields: Any) -> ReconcileItem:  # noqa: ANN401
    values: dict[str, Any] = {"calendar_ref": CAL, "ical_uid": f"uid-{meeting_id}"}
    if "provider_event_ref" in fields:
        values = {}
    values.update(fields)
    return ReconcileItem(
        action=ReconcileItemAction.BIND, meeting_id=meeting_id, expected_version=version, **values
    )


def mark(meeting_id: str) -> ReconcileItem:
    return ReconcileItem(action=ReconcileItemAction.NO_PROVIDER_EVENT, meeting_id=meeting_id)


@pytest.fixture
def scene() -> Scene:
    return Scene()


# ---- the pure values --------------------------------------------------------


def test_the_item_key_is_derived_from_the_batch_key_and_index() -> None:
    first = reconcile_item_key("batch", 0)
    assert first.startswith(RECONCILE_ITEM_KEY_PREFIX)
    assert len(first) <= 128
    assert first == reconcile_item_key("batch", 0)
    assert first != reconcile_item_key("batch", 1)
    assert first != reconcile_item_key("batch2", 0)


def test_the_scope_starts_one_lookback_before_now() -> None:
    assert review_scope_start(NOW) == NOW - COLLECTOR_LOOKBACK == NOW - timedelta(days=30)


@pytest.mark.parametrize(
    ("fields", "token"),
    [
        ({"expected_version": 1}, MeetingErrorField.EXPECTED_VERSION),
        ({"provider_event_ref": "msevt_00000000"}, MeetingErrorField.PROVIDER_EVENT_REF),
        ({"calendar_ref": CAL}, MeetingErrorField.CALENDAR_REF),
        ({"adopt_provider_series": True}, MeetingErrorField.ADOPT_PROVIDER_SERIES),
    ],
)
def test_a_mark_names_only_the_meeting(fields: dict[str, Any], token: MeetingErrorField) -> None:
    with pytest.raises(MeetingInvalidRequestError) as refused:
        ReconcileItem(
            action=ReconcileItemAction.NO_PROVIDER_EVENT,
            meeting_id="mtg_reconcile00000001",
            **fields,
        )
    assert refused.value.field is token


@pytest.mark.parametrize(
    ("fields", "token"),
    [
        ({"expected_version": None, "calendar_ref": CAL}, MeetingErrorField.EXPECTED_VERSION),
        ({"expected_version": 0, "calendar_ref": CAL}, MeetingErrorField.EXPECTED_VERSION),
        ({"expected_version": 1}, MeetingErrorField.PROVIDER_EVENT_REF),
        (
            {"expected_version": 1, "provider_event_ref": "msevt_00000000", "ical_uid": "u"},
            MeetingErrorField.ICAL_UID,
        ),
    ],
)
def test_a_bind_names_a_version_and_either_a_reference_or_a_key(
    fields: dict[str, Any], token: MeetingErrorField
) -> None:
    with pytest.raises(MeetingInvalidRequestError) as refused:
        ReconcileItem(action=ReconcileItemAction.BIND, meeting_id="mtg_reconcile00000001", **fields)
    assert refused.value.field is token


# ---- D6: adopt_provider_series (pure) -----------------------------------------


def _occurrence(adopt: bool) -> MeetingProviderBindRequest:
    return MeetingProviderBindRequest(
        action=ProviderBindAction.BIND,
        meeting_id="mtg_reconcile00000001",
        calendar_ref=CAL,
        ical_uid=SERIES_UID,
        occurrence_original_start_utc=ORIGINAL,
        series_ical_uid=SERIES_UID,
        adopt_provider_series=adopt,
    )


def _decide(adopt: bool, *, series: str | None, uid_series: str | None) -> Any:  # noqa: ANN401
    return bind_decision(
        _occurrence(adopt),
        meeting_id="mtg_reconcile00000001",
        meeting_series_id=series,
        meeting_is_bound=False,
        key_bound_meeting_id=None,
        other_kind_bound=False,
        uid_series=None if uid_series is None else BoundSeries(uid_series, CAL, SERIES_UID),
        meeting_series_binding=None,
    )


def test_adopt_moves_a_meeting_into_the_provider_series_mseries() -> None:
    for current in (None, "mser_reconcileother01"):
        decision = _decide(True, series=current, uid_series="mser_reconcileprov001")
        assert decision.move_to_series_id == "mser_reconcileprov001"
        assert not decision.create_series_binding
        assert not decision.create_series
        with pytest.raises(MeetingInvalidRequestError):
            _decide(False, series=current, uid_series="mser_reconcileprov001")


def test_adopt_creates_a_series_for_a_standalone_meeting_of_an_unbound_series() -> None:
    decision = _decide(True, series=None, uid_series=None)
    assert (decision.create_series, decision.create_series_binding) == (True, True)
    assert decision.move_to_series_id is None
    with pytest.raises(MeetingInvalidRequestError) as refused:
        _decide(False, series=None, uid_series=None)
    assert refused.value.field is MeetingErrorField.PROVIDER_BINDING_REQUIRES_SERIES


def test_adopt_is_an_occurrence_bind_flag_only() -> None:
    with pytest.raises(MeetingInvalidRequestError) as refused:
        MeetingProviderBindRequest(
            action=ProviderBindAction.BIND,
            meeting_id="mtg_reconcile00000001",
            calendar_ref=CAL,
            ical_uid="uid-single",
            adopt_provider_series=True,
        )
    assert refused.value.field is MeetingErrorField.ADOPT_PROVIDER_SERIES
    with pytest.raises(MeetingInvalidRequestError) as refused:
        MeetingProviderBindRequest(
            action=ProviderBindAction.UNBIND,
            meeting_id="mtg_reconcile00000001",
            adopt_provider_series=True,
        )
    assert refused.value.field is MeetingErrorField.ADOPT_PROVIDER_SERIES


# ---- review -------------------------------------------------------------------


def test_review_lists_in_scope_unreviewed_meetings_and_unbound_events_side_by_side(
    scene: Scene,
) -> None:
    edge = scene.meeting("Edge", start=NOW - COLLECTOR_LOOKBACK)
    old = scene.meeting("Old", start=NOW - COLLECTOR_LOOKBACK - timedelta(seconds=1))
    cancelled = scene.meeting("Cancelled")
    APP.update_meeting(
        scene.uow,
        P,
        MeetingUpdateRequest(meeting_id=cancelled, status=MeetingStatus.CANCELLED),
        1,
        _key(),
        NOW,
    )
    later = scene.meeting("Later")
    refs = scene.stage({"uid": "uid-a"}, {"uid": "uid-b"})
    page = scene.review()
    assert [m.meeting_id for m in page.unreviewed_meetings] == [edge, later]
    assert old not in {m.meeting_id for m in page.unreviewed_meetings}
    assert page.reconciliation.state is ReconciliationPassState.PENDING
    assert page.reconciliation.unreviewed_count == 2
    assert [e.event.event_id for e in page.unbound_provider_events] == refs
    assert not any(e.suppressed for e in page.unbound_provider_events)
    assert page.next_after is None


def test_review_pages_by_start_then_id(scene: Scene) -> None:
    ids = [scene.meeting(f"M{n}", start=SOON + timedelta(hours=n)) for n in range(5)]
    first = scene.review(page_size=2)
    assert [m.meeting_id for m in first.unreviewed_meetings] == ids[:2]
    assert first.next_after == ids[1]
    second = scene.review(page_size=2, after=first.next_after)
    assert [m.meeting_id for m in second.unreviewed_meetings] == ids[2:4]
    last = scene.review(page_size=2, after=second.next_after)
    assert [m.meeting_id for m in last.unreviewed_meetings] == ids[4:]
    assert last.next_after is None


def test_a_bound_key_leaves_the_event_list_and_a_tombstoned_key_is_suppressed(
    scene: Scene,
) -> None:
    meeting = scene.meeting()
    ref_a, ref_b = scene.stage({"uid": "uid-a"}, {"uid": "uid-b"})
    result = scene.reconcile(bind(meeting, provider_event_ref=ref_a))
    assert result.items[0].outcome is ReconcileItemOutcome.BOUND
    assert [e.event.event_id for e in scene.review().unbound_provider_events] == [ref_b]
    APP.bind_meeting_provider(
        scene.uow,
        P,
        MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=meeting),
        2,
        "unbind-0001",
        NOW,
    )
    listed = {e.event.event_id: e.suppressed for e in scene.review().unbound_provider_events}
    assert listed == {ref_a: True, ref_b: False}


def test_the_unbound_event_list_is_bounded_ordered_by_start_then_key(scene: Scene) -> None:
    # Ruling on the S4 handoff, decision 6 amended: at most 200 events, ordered
    # deterministically (start, then key), with the full count and a flag.
    assert MAX_UNBOUND_PROVIDER_EVENTS == 200
    # Staged out of order across two sources; two events share each start.
    starts = [SOON + timedelta(minutes=n // 2) for n in range(MAX_UNBOUND_PROVIDER_EVENTS + 1)]
    events = [{"uid": f"uid-{n % 2}-{n:04d}", "start": start} for n, start in enumerate(starts)]
    scene.stage(*reversed(events[: len(events) // 2]), source="isrc_reconcileunit001")
    scene.stage(*reversed(events[len(events) // 2 :]), source="isrc_reconcileunit002")
    page = scene.review()
    listed = page.unbound_provider_events
    assert len(listed) == MAX_UNBOUND_PROVIDER_EVENTS
    assert page.unbound_provider_events_total == MAX_UNBOUND_PROVIDER_EVENTS + 1
    assert page.unbound_provider_events_truncated is True
    order = [(e.event.start_utc, e.event.calendar_ref, e.event.ical_uid) for e in listed]
    assert order == sorted(order)
    assert [e.event.ical_uid for e in listed] == [e["uid"] for e in events][:-1]
    # Deterministic: the same staged state answers the same list.
    assert scene.review().unbound_provider_events == listed


def test_a_series_master_precedes_its_occurrences_at_one_start(scene: Scene) -> None:
    scene.stage(
        {"uid": "uid-b", "series": SERIES_UID, "original": ORIGINAL},
        {"uid": "uid-b"},
        {"uid": "uid-a"},
    )
    listed = [
        (e.event.ical_uid, e.event.occurrence_original_start_utc)
        for e in scene.review().unbound_provider_events
    ]
    assert listed == [("uid-a", None), ("uid-b", None), ("uid-b", ORIGINAL)]


def test_at_the_bound_the_list_is_whole_and_not_truncated(scene: Scene) -> None:
    scene.stage(*({"uid": f"uid-{n:04d}"} for n in range(MAX_UNBOUND_PROVIDER_EVENTS)))
    page = scene.review()
    assert len(page.unbound_provider_events) == MAX_UNBOUND_PROVIDER_EVENTS
    assert page.unbound_provider_events_total == MAX_UNBOUND_PROVIDER_EVENTS
    assert page.unbound_provider_events_truncated is False


def test_the_event_cursor_pages_past_the_bound_in_a_stable_order(scene: Scene) -> None:
    # R1 finding 2: events beyond the bound are reachable before the latch,
    # through a keyset cursor independent of the Meetings' cursor.
    starts = [SOON + timedelta(minutes=n // 2) for n in range(MAX_UNBOUND_PROVIDER_EVENTS + 1)]
    events = [{"uid": f"uid-{n % 2}-{n:04d}", "start": start} for n, start in enumerate(starts)]
    scene.stage(*reversed(events[: len(events) // 2]), source="isrc_reconcileunit001")
    scene.stage(*reversed(events[len(events) // 2 :]), source="isrc_reconcileunit002")
    first = scene.review()
    assert len(first.unbound_provider_events) == MAX_UNBOUND_PROVIDER_EVENTS
    assert first.unbound_provider_events_truncated is True
    assert first.unbound_provider_events_next == first.unbound_provider_events[-1].event.event_id
    second = scene.review(events_after=first.unbound_provider_events_next)
    assert [e.event.ical_uid for e in second.unbound_provider_events] == [events[-1]["uid"]]
    assert second.unbound_provider_events_total == MAX_UNBOUND_PROVIDER_EVENTS + 1
    assert second.unbound_provider_events_truncated is False
    assert second.unbound_provider_events_next is None
    # Stable: the two pages are the whole ordered list, once each.
    every = [*first.unbound_provider_events, *second.unbound_provider_events]
    assert [e.event.ical_uid for e in every] == [e["uid"] for e in events]
    assert [e.review_order for e in every] == sorted(e.review_order for e in every)
    # Independent of the Meetings' cursor: the event cursor leaves them unchanged.
    assert second.unreviewed_meetings == first.unreviewed_meetings


def test_the_event_cursor_survives_its_anchor_being_bound(scene: Scene) -> None:
    refs = scene.stage(*({"uid": f"uid-{n:04d}"} for n in range(3)))
    meeting = scene.meeting()
    scene.reconcile(bind(meeting, provider_event_ref=refs[0]))
    page = scene.review(events_after=refs[0])
    assert [e.event.event_id for e in page.unbound_provider_events] == refs[1:]
    assert page.unbound_provider_events_total == 2


def test_an_unknown_event_cursor_is_refused_cursor(scene: Scene) -> None:
    scene.stage({"uid": "uid-a"})
    with pytest.raises(MeetingCursorError):
        scene.review(events_after="msevt_reconcileunknown01")


def test_the_review_tool_description_states_the_event_bound() -> None:
    assert f"at most\n    {MAX_UNBOUND_PROVIDER_EVENTS}" in (ReviewMeetingProviders.__doc__ or "")


# ---- reconcile ------------------------------------------------------------------


def test_items_are_independent_a_refused_item_rolls_back_alone(scene: Scene) -> None:
    first = scene.meeting("First")
    second = scene.meeting("Second")
    third = scene.meeting("Third")
    result = scene.reconcile(
        bind(first),
        bind(second, version=7),  # stale: refused after its reservation was written
        mark(third),
    )
    outcomes = [(i.index, i.outcome) for i in result.items]
    assert outcomes == [
        (0, ReconcileItemOutcome.BOUND),
        (1, ReconcileItemOutcome.REFUSED),
        (2, ReconcileItemOutcome.MARKED),
    ]
    refused = result.items[1].refusal
    assert (refused.code, refused.safe_detail) == (ErrorCode.CONFLICT, "stale_version")
    # The refused item left nothing: no reservation, no binding, no version bump.
    assert scene.record(second).version == 1
    assert not any(
        key[1] == "meetings.provider.bind" and key[2] == reconcile_item_key("batch-0001", 1)
        for key in scene.world.meeting_write_requests
    )
    assert scene.record(first).version == 2
    # A later batch can still bind it (its own derived key is unused).
    again = scene.reconcile(bind(second), key="batch-0002")
    assert again.items[0].outcome is ReconcileItemOutcome.BOUND


def test_a_mark_never_versions_the_meeting_and_is_idempotent(scene: Scene) -> None:
    meeting = scene.meeting()
    other = scene.meeting("Other")
    first = scene.reconcile(mark(meeting))
    assert first.items[0].outcome is ReconcileItemOutcome.MARKED
    assert scene.record(meeting).version == 1
    again = scene.reconcile(mark(meeting), key="batch-0002")
    assert again.items[0].outcome is ReconcileItemOutcome.REPLAYED
    assert scene.reconcile(bind(other), key="batch-0003").items[0].outcome is (
        ReconcileItemOutcome.BOUND
    )
    refused = scene.reconcile(mark(other), key="batch-0004").items[0]
    assert refused.outcome is ReconcileItemOutcome.REFUSED
    assert refused.refusal.safe_detail == "meeting_already_provider_bound"


def test_a_mark_replays_after_its_meeting_was_bound_and_a_new_mark_is_refused(
    scene: Scene,
) -> None:
    # R1 finding 5: an existing mark answers `replayed` before the binding check.
    meeting = scene.meeting()
    other = scene.meeting("Other")
    assert scene.reconcile(mark(meeting)).items[0].outcome is ReconcileItemOutcome.MARKED
    bound = scene.reconcile(bind(meeting), bind(other), key="batch-0002")
    assert [i.outcome for i in bound.items] == [ReconcileItemOutcome.BOUND] * 2
    replay = scene.reconcile(mark(meeting))
    assert replay.items[0].outcome is ReconcileItemOutcome.REPLAYED
    assert replay.items[0].refusal is None
    fresh = scene.reconcile(mark(other), key="batch-0003").items[0]
    assert fresh.outcome is ReconcileItemOutcome.REFUSED
    assert fresh.refusal.safe_detail == "meeting_already_provider_bound"
    assert (P, other) not in scene.world.meeting_provider_review_marks


@dataclass(frozen=True, slots=True)
class _RefusedAfterStaging(MeetingApplication):
    """A bind that stages its Record Event and is then refused (R1 finding 4)."""

    refused_meeting_id: str = ""

    def bind_meeting_provider(self, uow: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        written = MeetingApplication.bind_meeting_provider(self, uow, *args, **kwargs)
        if written.meeting_id == self.refused_meeting_id:
            assert uow.record_events.pending_count > 0
            raise MeetingInvalidRequestError(MeetingErrorField.MEETING_ID)
        return written


def test_a_refused_item_after_staging_leaves_no_record_event_draft(scene: Scene) -> None:
    first, second, third = (scene.meeting(t) for t in ("First", "Second", "Third"))
    feed_before = len(scene.world.record_events)
    with scene.uow as unit:
        result = MeetingProviderReconciliation(
            _RefusedAfterStaging(refused_meeting_id=second)
        ).reconcile(
            unit,
            P,
            (bind(first), bind(second), bind(third)),
            "batch-0001",
            NOW,
            correlation_id=CORRELATION,
        )
    assert [i.outcome for i in result.items] == [
        ReconcileItemOutcome.BOUND,
        ReconcileItemOutcome.REFUSED,
        ReconcileItemOutcome.BOUND,
    ]
    published = scene.world.record_events[feed_before:]
    assert sorted(e.record_id for e in published) == sorted([first, third])
    assert scene.record(second).version == 1


def test_the_latch_waits_for_every_in_scope_meeting_then_is_written_once(scene: Scene) -> None:
    first = scene.meeting("First")
    second = scene.meeting("Second")
    scene.meeting("Old", start=NOW - COLLECTOR_LOOKBACK - timedelta(days=1))
    partial = scene.reconcile(mark(first))
    assert partial.reconciliation.state is ReconciliationPassState.PENDING
    assert partial.reconciliation.unreviewed_count == 1
    assert not partial.sync_enabled
    assert P not in scene.world.meeting_provider_reconciliation_passes
    done = scene.reconcile(bind(second), key="batch-0002")
    assert done.reconciliation.state is ReconciliationPassState.COMPLETE
    assert done.reconciliation.completed_at == NOW
    assert done.sync_enabled
    latch = scene.world.meeting_provider_reconciliation_passes[P]
    assert (latch.reviewed_meetings, latch.reconcile_correlation_id) == (2, CORRELATION)
    # Written once: a later call, and a new unreviewed Meeting, leave it as is.
    scene.meeting("New")
    after = scene.reconcile(key="batch-0003")
    assert after.reconciliation.state is ReconciliationPassState.COMPLETE
    assert after.reconciliation.unreviewed_count == 1
    assert scene.world.meeting_provider_reconciliation_passes[P] is latch


def test_a_refused_last_item_keeps_the_pass_pending(scene: Scene) -> None:
    meeting = scene.meeting()
    result = scene.reconcile(bind(meeting, version=9))
    assert result.items[0].outcome is ReconcileItemOutcome.REFUSED
    assert result.reconciliation.state is ReconciliationPassState.PENDING
    assert P not in scene.world.meeting_provider_reconciliation_passes


def test_an_empty_batch_completes_a_pass_with_nothing_left(scene: Scene) -> None:
    scene.meeting("Old", start=NOW - COLLECTOR_LOOKBACK - timedelta(days=1))
    result = scene.reconcile()
    assert result.items == ()
    assert result.sync_enabled
    assert scene.world.meeting_provider_reconciliation_passes[P].reviewed_meetings == 0


def test_an_empty_batch_with_meetings_left_records_nothing(scene: Scene) -> None:
    scene.meeting()
    result = scene.reconcile()
    assert not result.sync_enabled
    assert P not in scene.world.meeting_provider_reconciliation_passes


def test_more_than_fifty_items_are_refused_whole(scene: Scene) -> None:
    meeting = scene.meeting()
    with pytest.raises(MeetingInvalidRequestError) as refused:
        scene.reconcile(*[mark(meeting)] * (MAX_RECONCILE_ITEMS + 1))
    assert refused.value.field is MeetingErrorField.ITEMS


def test_an_unknown_reference_is_refused_not_found(scene: Scene) -> None:
    meeting = scene.meeting()
    result = scene.reconcile(bind(meeting, provider_event_ref="msevt_reconcileunknown01"))
    refusal = result.items[0].refusal
    assert (refusal.code, refusal.safe_detail) == (ErrorCode.NOT_FOUND, "provider_event_ref")


def test_a_replay_answers_every_item_from_its_stored_state(scene: Scene) -> None:
    first = scene.meeting("First")
    second = scene.meeting("Second")
    items = (bind(first), mark(second))
    original = scene.reconcile(*items)
    assert [i.outcome for i in original.items] == [
        ReconcileItemOutcome.BOUND,
        ReconcileItemOutcome.MARKED,
    ]
    meetings = dict(scene.world.meetings)
    replay = scene.reconcile(*items)
    assert [i.outcome for i in replay.items] == [
        ReconcileItemOutcome.REPLAYED,
        ReconcileItemOutcome.REPLAYED,
    ]
    assert replay.items[0].version == original.items[0].version == 2
    assert replay.items[0].binding == original.items[0].binding
    assert scene.world.meetings == meetings
    assert replay.sync_enabled
    # The same batch key with a changed bind item is a conflict on that item.
    changed = scene.reconcile(bind(first, ical_uid="uid-other"), mark(second))
    assert changed.items[0].refusal.safe_detail == "idempotency_conflict"


def test_a_reference_binds_the_staged_key(scene: Scene) -> None:
    meeting = scene.meeting(series_title="Weekly")
    (ref,) = scene.stage({"uid": SERIES_UID, "series": SERIES_UID, "original": ORIGINAL})
    result = scene.reconcile(bind(meeting, provider_event_ref=ref))
    binding = result.items[0].binding
    assert (binding.ical_uid, binding.occurrence_original_start_utc) == (SERIES_UID, ORIGINAL)
    assert binding.series_ical_uid == SERIES_UID


# ---- D6 adopt over the fake -------------------------------------------------------


def _occurrence_item(meeting_id: str, original: datetime, adopt: bool) -> ReconcileItem:
    return bind(
        meeting_id,
        ical_uid=SERIES_UID,
        series_ical_uid=SERIES_UID,
        occurrence_original_start_utc=original,
        adopt_provider_series=adopt,
    )


def test_adopt_moves_the_meeting_into_the_bound_provider_series(scene: Scene) -> None:
    anchor = scene.meeting("Anchor", series_title="Provider weekly")
    series = scene.record(anchor).meeting_series_id
    scene.reconcile(_occurrence_item(anchor, ORIGINAL, False))
    stray = scene.meeting("Stray", series_title="Hand-made")
    week = ORIGINAL + timedelta(days=7)
    refused = scene.reconcile(_occurrence_item(stray, week, False), key="batch-0002")
    assert refused.items[0].refusal.safe_detail == "provider_series_binding_conflict"
    moved = scene.reconcile(_occurrence_item(stray, week, True), key="batch-0003")
    assert moved.items[0].outcome is ReconcileItemOutcome.BOUND
    assert scene.record(stray).meeting_series_id == series
    assert moved.items[0].binding.meeting_series_id == series
    event = scene.world.record_events[-1]
    assert event.changed_fields == ("meeting_series_id", "provider_binding")
    assert event.source_capability == "meetings.provider.reconcile"


def test_adopt_creates_a_series_for_a_standalone_meeting(scene: Scene) -> None:
    standalone = scene.meeting("Standup")
    refused = scene.reconcile(_occurrence_item(standalone, ORIGINAL, False))
    assert refused.items[0].refusal.safe_detail == "provider_binding_requires_series"
    adopted = scene.reconcile(_occurrence_item(standalone, ORIGINAL, True), key="batch-0002")
    assert adopted.items[0].outcome is ReconcileItemOutcome.BOUND
    series_id = scene.record(standalone).meeting_series_id
    assert series_id is not None
    assert scene.world.meeting_series[(P, series_id)].title == "Standup"
    assert adopted.items[0].binding.meeting_series_id == series_id
    families = [e.record_family.value for e in scene.world.record_events[-2:]]
    assert families == ["meeting_series", "meeting"]
