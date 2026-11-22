"""WP2: provider binding persistence and `MeetingProviderSync` on PostgreSQL.

The `database` tier. Every case drives `MeetingProviderSync` (and, for D6,
`MeetingApplication`) through the real `SqlAlchemyUnitOfWork`, on a disposable
current-head database:

* a known occurrence updates its Meeting through the CAS with a `system` receipt
  and a `system.meeting_provider.sync` Record Event, its key in that one
  internal namespace (WP2-W3), so a client key never collides with it;
* a new occurrence joins a known series; an unknown series is created and bound
  in the same transaction as its first occurrence;
* a moved occurrence keeps its identity by original start;
* a changed provider event id is the same Meeting;
* a cancelled event cancels the Meeting and keeps the row; a cancelled unknown
  event writes nothing;
* an identical replay writes nothing and bumps no version;
* Principals are isolated;
* D6: a series move or detach of a bound Meeting is refused;
* uniqueness and `ON DELETE RESTRICT` hold through the repository.

Every identifier, title and address here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import IntegrityError

from my_pa.application.meeting_provider_sync import (
    MEETINGS_PROVIDER_SYNC_SOURCE,
    MeetingProviderSync,
    MeetingSyncOutcome,
    SyncOutcomeKind,
)
from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.meeting.model import (
    MEETING_PROVIDER_SYNC_NAME,
    MeetingCreateRequest,
    MeetingErrorField,
    MeetingInvalidRequestError,
    MeetingStatus,
    MeetingUpdateRequest,
)
from my_pa.domain.meeting_sync.model import MeetingSyncEvent, ProviderBindingState
from my_pa.domain.meeting_sync.resolution import ResolutionDiagnostic, sync_idempotency_key
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.meeting_sync.parser import parse_publication
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import (
    meeting_history,
    meeting_provider_bindings,
    meeting_series,
    meeting_series_provider_bindings,
    meeting_write_requests,
    meetings,
    record_events,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

NOW: Final = datetime(2026, 11, 21, 6, tzinfo=UTC)
LATER: Final = NOW + timedelta(hours=1)
SHA_A: Final = "a" * 64
SHA_B: Final = "b" * 64
GENERATED: Final = "2026-11-21T05:00:00Z"
STAMP_A: Final = datetime(2026, 11, 21, 5, tzinfo=UTC)
STAMP_B: Final = STAMP_A + timedelta(hours=1)
#: A test's publication digest names its ordering stamp unless it states one: A,
#: B, C in publication order (resolution rule 7).
SHA_C: Final = "c" * 64
STAMP_C: Final = STAMP_B + timedelta(hours=1)
STAMPS: Final = {SHA_A: STAMP_A, SHA_B: STAMP_B, SHA_C: STAMP_C}


def _stamped(event: MeetingSyncEvent, sha: str, stamp: datetime | None) -> MeetingSyncEvent:
    return replace(event, generated_at_utc=STAMPS.get(sha, STAMP_A) if stamp is None else stamp)


SERIES_UID: Final = "uid-series@example.invalid"
SYNC: Final = MeetingProviderSync()
APP: Final = MeetingApplication()


def _event(**overrides: object) -> MeetingSyncEvent:
    record: dict[str, object] = {
        "calendar_ref": "cal-synthetic",
        "ical_uid": "uid-0001@example.invalid",
        "start_utc": "2026-12-01T15:00:00Z",
        "end_utc": "2026-12-01T16:00:00Z",
        "timezone_name": "America/New_York",
        "status": "confirmed",
        "all_day": False,
        "provider_event_id": "evt-0001",
        "provider_event_id_format": "mutable",
        "title": "Synthetic sync",
        "location_text": "Room 1",
        "virtual_meeting_url": "https://meet.example.invalid/sync",
    }
    record.update(overrides)
    data = json.dumps(
        {
            "schema": "meeting_sync_v1",
            "schema_version": "1.0.0",
            "generated_at_utc": GENERATED,
            "events": [record],
        }
    ).encode()
    publication = parse_publication(data).publication
    assert publication is not None
    (event,) = publication.events
    return event


def _occurrence(original: str = "2026-12-02T14:00:00Z", **overrides: object) -> MeetingSyncEvent:
    values: dict[str, object] = {
        "ical_uid": SERIES_UID,
        "series_ical_uid": SERIES_UID,
        "occurrence_original_start_utc": original,
        "start_utc": original,
        "end_utc": original.replace("14:00", "14:30"),
    }
    values.update(overrides)
    return _event(**values)


class Harness:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.audit = SqlAlchemyAuditSink(engine)

    def run[ResultT](self, work: Callable[[UnitOfWork], ResultT]) -> ResultT:
        with SqlAlchemyUnitOfWork(self.engine, audit=self.audit) as uow:
            return work(uow)

    def apply(
        self,
        principal_id: str,
        event: MeetingSyncEvent,
        *,
        sha: str = SHA_A,
        now: datetime = NOW,
        stamp: datetime | None = None,
    ) -> MeetingSyncOutcome:
        stamped = _stamped(event, sha, stamp)
        return self.run(
            lambda uow: SYNC.apply_event(uow, principal_id, stamped, source_sha256=sha, now=now)
        )

    def rows(self, table: Any, **where: object) -> list[dict[str, Any]]:  # noqa: ANN401
        statement = select(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def count(self, table: Any, **where: object) -> int:  # noqa: ANN401
        statement = select(func.count()).select_from(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        with self.engine.connect() as connection:
            return int(connection.execute(statement).scalar_one())


@pytest.fixture
def harness(db_engine: Engine) -> Harness:
    return Harness(db_engine)


@pytest.fixture
def principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def _meeting(harness: Harness, meeting_id: str | None) -> dict[str, Any]:
    (row,) = harness.rows(meetings, meeting_id=meeting_id)
    return row


def test_an_unknown_single_meeting_is_created_and_bound(harness: Harness, principal: str) -> None:
    outcome = harness.apply(principal, _event())
    assert outcome.kind is SyncOutcomeKind.CREATED
    meeting = _meeting(harness, outcome.meeting_id)
    assert meeting["principal_id"] == principal
    assert meeting["meeting_series_id"] is None
    assert meeting["virtual_meeting_url"] == "https://meet.example.invalid/sync"
    (binding,) = harness.rows(meeting_provider_bindings, meeting_id=outcome.meeting_id)
    assert binding["principal_id"] == principal
    assert binding["occurrence_original_start_utc"] is None
    assert binding["provider_state"] == "active"
    assert (binding["last_seen_source_sha256"], binding["last_seen_record_ordinal"]) == (SHA_A, 0)
    (receipt,) = harness.rows(meeting_history, meeting_id=outcome.meeting_id)
    assert receipt["actor"] == "system"
    assert receipt["idempotency_key"].startswith("mpsync_")
    (event,) = harness.rows(record_events, record_id=outcome.meeting_id)
    assert event["source_capability"] == MEETINGS_PROVIDER_SYNC_SOURCE
    assert event["actor_class"] == "system"


def test_a_new_series_is_bound_with_its_first_occurrence_and_a_later_one_joins(
    harness: Harness, principal: str
) -> None:
    first = harness.apply(principal, _occurrence())
    second = harness.apply(principal, _occurrence("2026-12-09T14:00:00Z"))
    series_id = _meeting(harness, first.meeting_id)["meeting_series_id"]
    assert series_id is not None
    assert _meeting(harness, second.meeting_id)["meeting_series_id"] == series_id
    (series,) = harness.rows(meeting_series, meeting_series_id=series_id)
    assert series["title"] == "Synthetic sync"
    (series_binding,) = harness.rows(meeting_series_provider_bindings, principal_id=principal)
    assert series_binding["meeting_series_id"] == series_id
    assert series_binding["series_ical_uid"] == SERIES_UID
    assert harness.count(meeting_provider_bindings, principal_id=principal) == 2


def test_a_known_occurrence_moves_through_the_cas_and_keeps_its_identity(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _occurrence())
    moved = harness.apply(
        principal,
        _occurrence(start_utc="2026-12-02T18:00:00Z", end_utc="2026-12-02T19:00:00Z"),
        sha=SHA_B,
        now=LATER,
    )
    assert moved.kind is SyncOutcomeKind.UPDATED
    assert (moved.meeting_id, moved.binding_id) == (created.meeting_id, created.binding_id)
    meeting = _meeting(harness, created.meeting_id)
    assert meeting["start_at"] == datetime(2026, 12, 2, 18, tzinfo=UTC)
    assert meeting["version"] == 2
    receipts = harness.rows(meeting_history, meeting_id=created.meeting_id)
    assert sorted((r["before_version"], r["after_version"], r["actor"]) for r in receipts) == [
        (0, 1, "system"),
        (1, 2, "system"),
    ]
    (binding,) = harness.rows(meeting_provider_bindings, meeting_id=created.meeting_id)
    assert binding["occurrence_original_start_utc"] == datetime(2026, 12, 2, 14, tzinfo=UTC)
    assert binding["last_seen_source_sha256"] == SHA_B
    assert binding["version"] == 1
    assert harness.count(meetings, principal_id=principal) == 1


def test_a_changed_provider_id_is_the_same_meeting(harness: Harness, principal: str) -> None:
    created = harness.apply(principal, _event())
    renamed = harness.apply(principal, _event(provider_event_id="evt-renamed"), sha=SHA_B)
    assert renamed.meeting_id == created.meeting_id
    assert _meeting(harness, created.meeting_id)["version"] == 1
    (binding,) = harness.rows(meeting_provider_bindings, meeting_id=created.meeting_id)
    assert (binding["provider_event_id"], binding["version"]) == ("evt-renamed", 2)


def test_a_cancel_keeps_the_row_and_an_unknown_cancel_writes_nothing(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _event())
    harness.apply(principal, _event(status="cancelled"), sha=SHA_B, now=LATER)
    meeting = _meeting(harness, created.meeting_id)
    assert meeting["status"] == MeetingStatus.CANCELLED.value
    assert meeting["cancelled_at"] == LATER
    (binding,) = harness.rows(meeting_provider_bindings, meeting_id=created.meeting_id)
    assert binding["provider_state"] == ProviderBindingState.CANCELLED.value
    # Un-cancel.
    harness.apply(principal, _event(), sha=SHA_C, now=LATER + timedelta(hours=1))
    assert _meeting(harness, created.meeting_id)["status"] == MeetingStatus.SCHEDULED.value
    before = harness.count(meetings, principal_id=principal)
    skipped = harness.apply(principal, _event(ical_uid="uid-unknown", status="cancelled"))
    assert skipped.diagnostic is ResolutionDiagnostic.CANCELLED_UNKNOWN_SKIPPED
    assert harness.count(meetings, principal_id=principal) == before
    assert harness.count(meeting_provider_bindings, principal_id=principal) == 1


def test_an_identical_replay_writes_nothing(harness: Harness, principal: str) -> None:
    created = harness.apply(principal, _event())
    history = harness.count(meeting_history, meeting_id=created.meeting_id)
    events = harness.count(record_events, record_id=created.meeting_id)
    assert harness.apply(principal, _event()).kind is SyncOutcomeKind.REPLAYED
    assert harness.apply(principal, _event(), sha=SHA_B).kind is SyncOutcomeKind.UNCHANGED
    assert _meeting(harness, created.meeting_id)["version"] == 1
    assert harness.count(meeting_history, meeting_id=created.meeting_id) == history
    assert harness.count(record_events, record_id=created.meeting_id) == events
    (binding,) = harness.rows(meeting_provider_bindings, meeting_id=created.meeting_id)
    assert binding["version"] == 1


def test_a_replay_of_an_older_record_does_not_rewind(harness: Harness, principal: str) -> None:
    created = harness.apply(principal, _event())
    harness.apply(principal, _event(title="Second"), sha=SHA_B)
    harness.apply(principal, _event(title="Third"), sha=SHA_C)
    # SHA_B's record again: its stamp is older than the binding's, so nothing moves.
    replay = harness.apply(principal, _event(title="Second"), sha=SHA_B)
    assert replay.kind is SyncOutcomeKind.SKIPPED
    assert replay.diagnostic is ResolutionDiagnostic.STALE_RECORD_SKIPPED
    assert _meeting(harness, created.meeting_id)["title"] == "Third"


def test_a_replay_of_an_applied_record_under_a_newer_stamp_still_does_not_rewind(
    harness: Harness, principal: str
) -> None:
    """The reserved-key guard behind rule 7 (WP2-W3), isolated from the ordering guard.

    One publication digest always carries one stamp, so this case is
    synthetic: the record's key is already reserved, and the stamp is one the
    ordering guard cannot refuse.
    """
    created = harness.apply(principal, _event())
    harness.apply(principal, _event(title="Second"), sha=SHA_B)
    harness.apply(principal, _event(title="Third"), sha=SHA_C)
    replay = harness.apply(
        principal, _event(title="Second"), sha=SHA_B, stamp=STAMP_C + timedelta(hours=1)
    )
    assert replay.kind is SyncOutcomeKind.REPLAYED
    assert _meeting(harness, created.meeting_id)["title"] == "Third"


def test_an_identical_replay_of_a_binding_only_record_is_replayed(
    harness: Harness, principal: str
) -> None:
    """A record that changed only the binding reserves no key; its replay still writes nothing.

    WP2-W3 prove-red isolation of the identical-observation guard: the creating
    record's replay is also caught by its reserved key, so this case is the one
    only that guard covers.
    """
    created = harness.apply(principal, _event())
    renamed = harness.apply(principal, _event(provider_event_id="evt-renamed"), sha=SHA_B)
    assert renamed.kind is SyncOutcomeKind.UPDATED
    (before,) = harness.rows(meeting_provider_bindings, meeting_id=created.meeting_id)
    replay = harness.apply(principal, _event(provider_event_id="evt-renamed"), sha=SHA_B, now=LATER)
    assert replay.kind is SyncOutcomeKind.REPLAYED
    (after,) = harness.rows(meeting_provider_bindings, meeting_id=created.meeting_id)
    assert after == before


def test_a_replay_of_the_creating_record_after_an_update_does_not_rewind(
    harness: Harness, principal: str
) -> None:
    """WP2-W3 carry-over (2): one sync namespace for a create and an update.

    Under per-capability namespaces the creating record's key sat in the create
    space, so re-applying it after a later update found no key in the update
    space and rewound the Meeting to the older record.
    """
    created = harness.apply(principal, _event())
    harness.apply(principal, _event(title="Second"), sha=SHA_B)
    # The ordering guard (rule 7) skips this as stale on its own; a stamp it
    # cannot refuse isolates the one-namespace key guard this case is about.
    assert harness.apply(principal, _event()).diagnostic is (
        ResolutionDiagnostic.STALE_RECORD_SKIPPED
    )
    replay = harness.apply(principal, _event(), stamp=STAMP_C)
    assert replay.kind is SyncOutcomeKind.REPLAYED
    meeting = _meeting(harness, created.meeting_id)
    assert (meeting["title"], meeting["version"]) == ("Second", 2)
    requests = harness.rows(meeting_write_requests, principal_id=principal)
    assert {row["capability"] for row in requests} == {MEETING_PROVIDER_SYNC_NAME}
    assert len(requests) == 2


# ---- rule 7: publication ordering (WP2-F1) -------------------------------------------


def _binding(harness: Harness, meeting_id: str | None) -> dict[str, Any]:
    (row,) = harness.rows(meeting_provider_bindings, meeting_id=meeting_id)
    return row


def test_an_older_publication_after_a_newer_one_rewinds_nothing(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _event(), sha=SHA_A)
    assert _binding(harness, created.meeting_id)["last_applied_generated_at_utc"] == STAMP_A
    moved = harness.apply(
        principal,
        _event(
            title="Newer",
            start_utc="2026-12-01T18:00:00Z",
            end_utc="2026-12-01T19:00:00Z",
            timezone_name="Europe/London",
            location_text="Room 9",
            virtual_meeting_url="https://meet.example.invalid/newer",
        ),
        sha=SHA_C,
        now=LATER,
    )
    assert moved.kind is SyncOutcomeKind.UPDATED
    meeting_before = _meeting(harness, created.meeting_id)
    binding_before = _binding(harness, created.meeting_id)
    assert binding_before["last_applied_generated_at_utc"] == STAMP_C
    events_before = harness.count(record_events, record_id=created.meeting_id)
    requests_before = harness.count(meeting_write_requests, principal_id=principal)
    # An older publication never applied before: no key is reserved for it.
    stale = harness.apply(principal, _event(status="cancelled"), sha=SHA_B, now=LATER)
    assert stale.kind is SyncOutcomeKind.SKIPPED
    assert stale.diagnostic is ResolutionDiagnostic.STALE_RECORD_SKIPPED
    assert stale.meeting_id == created.meeting_id
    assert _meeting(harness, created.meeting_id) == meeting_before
    assert meeting_before["version"] == 2 and meeting_before["title"] == "Newer"
    assert _binding(harness, created.meeting_id) == binding_before
    assert harness.count(record_events, record_id=created.meeting_id) == events_before
    assert harness.count(meeting_write_requests, principal_id=principal) == requests_before


def test_a_no_change_newer_record_still_blocks_an_older_changing_one(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _event(), sha=SHA_A)
    # The newer publication changes nothing: no Meeting write, no reserved key.
    unchanged = harness.apply(principal, _event(), sha=SHA_C, now=LATER)
    assert unchanged.kind is SyncOutcomeKind.UNCHANGED
    binding_before = _binding(harness, created.meeting_id)
    assert binding_before["last_applied_generated_at_utc"] == STAMP_C
    assert binding_before["last_seen_source_sha256"] == SHA_C
    meeting_before = _meeting(harness, created.meeting_id)
    stale = harness.apply(
        principal,
        _event(title="Older", start_utc="2026-12-01T09:00:00Z", end_utc="2026-12-01T10:00:00Z"),
        sha=SHA_B,
        now=LATER,
    )
    assert stale.kind is SyncOutcomeKind.SKIPPED
    assert stale.diagnostic is ResolutionDiagnostic.STALE_RECORD_SKIPPED
    meeting = _meeting(harness, created.meeting_id)
    assert meeting == meeting_before
    assert (meeting["title"], meeting["version"]) == ("Synthetic sync", 1)
    assert _binding(harness, created.meeting_id) == binding_before


def test_an_equal_stamp_from_another_publication_is_an_ordering_conflict(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _event(), sha=SHA_A)
    meeting_before = _meeting(harness, created.meeting_id)
    binding_before = _binding(harness, created.meeting_id)
    conflict = harness.apply(
        principal, _event(title="Same stamp"), sha=SHA_B, stamp=STAMP_A, now=LATER
    )
    assert conflict.kind is SyncOutcomeKind.SKIPPED
    assert conflict.diagnostic is ResolutionDiagnostic.ORDERING_CONFLICT_SKIPPED
    assert _meeting(harness, created.meeting_id) == meeting_before
    assert _binding(harness, created.meeting_id) == binding_before


def test_an_identical_replay_under_ordering_is_still_a_no_op(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _event(title="Second"), sha=SHA_B)
    meeting_before = _meeting(harness, created.meeting_id)
    binding_before = _binding(harness, created.meeting_id)
    replay = harness.apply(principal, _event(title="Second"), sha=SHA_B, now=LATER)
    assert replay.kind is SyncOutcomeKind.REPLAYED and replay.diagnostic is None
    assert _meeting(harness, created.meeting_id) == meeting_before
    assert _binding(harness, created.meeting_id) == binding_before


def test_a_bind_leaves_the_stamp_null_and_the_next_sync_applies(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _event(), sha=SHA_B)
    with harness.engine.begin() as connection:
        connection.execute(
            meeting_provider_bindings.update()
            .where(meeting_provider_bindings.c.meeting_id == created.meeting_id)
            .values(
                last_applied_generated_at_utc=None,
                last_seen_source_sha256=None,
                last_seen_record_ordinal=None,
                last_seen_at=None,
            )
        )
    # An unstamped binding (as an explicit bind leaves it) accepts any stamp.
    applied = harness.apply(principal, _event(title="After bind"), sha=SHA_A, now=LATER)
    assert applied.kind is SyncOutcomeKind.UPDATED
    assert _binding(harness, created.meeting_id)["last_applied_generated_at_utc"] == STAMP_A


def test_a_client_key_never_collides_with_a_sync_key(harness: Harness, principal: str) -> None:
    """A client `meetings.update` under the very key a sync record will use."""
    created = harness.apply(principal, _event())
    key = sync_idempotency_key(_event().key, source_sha256=SHA_B, record_ordinal=0)
    harness.run(
        lambda uow: APP.update_meeting(
            uow,
            principal,
            MeetingUpdateRequest(meeting_id=created.meeting_id, title="Mine"),
            1,
            key,
            LATER,
        )
    )
    # The sync record with that key still applies: the client row is in the
    # `meetings.update` space and neither replays nor suppresses it.
    applied = harness.apply(principal, _event(title="Provider"), sha=SHA_B, now=LATER)
    assert applied.kind is SyncOutcomeKind.UPDATED
    assert _meeting(harness, created.meeting_id)["title"] == "Provider"


def test_principals_are_isolated(harness: Harness, principal: str) -> None:
    other = issue_identifier(IdKind.PRINCIPAL)
    mine = harness.apply(principal, _occurrence())
    theirs = harness.apply(other, _occurrence())
    assert theirs.kind is SyncOutcomeKind.CREATED
    assert theirs.meeting_id != mine.meeting_id
    assert _meeting(harness, theirs.meeting_id)["principal_id"] == other
    assert harness.count(meeting_series_provider_bindings, principal_id=other) == 1
    assert harness.count(meeting_series_provider_bindings, principal_id=principal) == 1


def test_d6_a_bound_meetings_series_cannot_move_or_detach(harness: Harness, principal: str) -> None:
    created = harness.apply(principal, _occurrence())
    target = harness.run(
        lambda uow: APP.create_meeting(
            uow,
            principal,
            MeetingCreateRequest(
                title="Unbound", start_at=NOW, timezone_name="UTC", series_title="Other"
            ),
            "principal-create-0001",
            NOW,
        )
    )
    for index, request in enumerate(
        (
            MeetingUpdateRequest(meeting_id=created.meeting_id, detach_series=True),
            MeetingUpdateRequest(
                meeting_id=created.meeting_id,
                meeting_series_id=target.meeting.meeting_series_id,
            ),
        )
    ):
        with pytest.raises(MeetingInvalidRequestError) as refused:
            harness.run(
                lambda uow, request=request, index=index: APP.update_meeting(
                    uow, principal, request, 1, f"principal-move-{index}", LATER
                )
            )
        assert refused.value.field is MeetingErrorField.MEETING_SERIES_CHANGE_REFUSED_PROVIDER_BOUND
    meeting = _meeting(harness, created.meeting_id)
    assert meeting["version"] == 1 and meeting["meeting_series_id"] is not None


def test_uniqueness_and_restrict_hold_through_the_repository(
    harness: Harness, principal: str
) -> None:
    created = harness.apply(principal, _event())
    (stored,) = harness.rows(meeting_provider_bindings, meeting_id=created.meeting_id)

    def second_binding(uow: UnitOfWork) -> None:
        binding = uow.meetings.lock_provider_binding(
            principal, "cal-synthetic", "uid-0001@example.invalid", None
        )
        assert binding is not None
        uow.meetings.insert_provider_binding(
            principal,
            binding.__class__(
                **{
                    **{name: getattr(binding, name) for name in binding.__slots__},
                    "binding_id": issue_identifier(IdKind.MEETING_PROVIDER_BINDING),
                }
            ),
        )

    with pytest.raises(IntegrityError):
        harness.run(second_binding)
    with pytest.raises(IntegrityError), harness.engine.begin() as connection:
        connection.execute(delete(meetings).where(meetings.c.meeting_id == created.meeting_id))
    assert harness.count(meeting_provider_bindings, binding_id=stored["binding_id"]) == 1
    # The repository reads are partitioned: another Principal sees nothing.
    other = issue_identifier(IdKind.PRINCIPAL)
    assert (
        harness.run(
            lambda uow: uow.meetings.read_provider_binding_for_meeting(other, created.meeting_id)
        )
        is None
    )
