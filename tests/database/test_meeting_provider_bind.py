"""WP2-W3: `meetings.provider.bind` through `ApplicationService.invoke` on PostgreSQL.

The `database` tier. Every case is a canonical request through the real
`ApplicationService` over the production general unit of work on a disposable
current-head database, so the committed binding, series binding, receipt,
write request, Record Event and audit rows are what is checked:

* a single-meeting bind and an occurrence bind (which also binds the Meeting's
  current series to the provider series UID);
* every refusal: no series for an occurrence key, a series bound to another
  UID, a UID bound to another series, a key bound to another Meeting, an
  already-bound Meeting, single and occurrence mixing for one UID (D9), and an
  unbind of an unbound Meeting -- each writing nothing;
* unbind deletes the occurrence binding and keeps the series binding;
* a stale `expected_version`; an idempotent replay; a digest conflict;
* Principal isolation;
* the history receipt (`update`, actor `principal`), the `provider_binding`
  Record Event and the audit row naming the capability;
* the D6 path: a series move of a bound Meeting is refused, then an unbind, then
  the same move succeeds.

Every identifier, title and key here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, Table, func, select

from my_pa.application.commands import BindMeetingProvider, Command, CreateMeeting, UpdateMeeting
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.infrastructure.persistence.tables import (
    audit_events,
    meeting_history,
    meeting_provider_bindings,
    meeting_series_provider_bindings,
    meeting_write_requests,
    meetings,
    record_events,
)
from tests.contract.test_meeting_mcp import Partition, _insert_partition
from tests.database.test_task_record_events import Runtime

pytestmark = pytest.mark.database

START: Final = datetime(2026, 12, 1, 15, tzinfo=UTC)
ORIGINAL: Final = "2026-12-02T14:00:00Z"
CALENDAR: Final = "cal-synthetic"
SERIES_UID: Final = "uid-series@example.invalid"
SINGLE_UID: Final = "uid-single@example.invalid"
BIND: Final = "meetings.provider.bind"


@dataclass
class Scene:
    runtime: Runtime
    mine: Partition
    theirs: Partition

    @property
    def principal_id(self) -> str:
        return self.mine.principal.principal_id

    @property
    def engine(self) -> Engine:
        return self.runtime.work_engine

    def invoke(self, command: Command, *, principal_id: str | None = None) -> ResponseEnvelope:
        return self.runtime.invoke(command, principal_id=principal_id or self.principal_id)

    def ok(self, command: Command, *, principal_id: str | None = None) -> dict[str, Any]:
        return self.runtime.ok(command, principal_id=principal_id or self.principal_id)

    def refused(
        self, command: Command, code: ErrorCode, detail: str, *, principal_id: str | None = None
    ) -> None:
        response = self.invoke(command, principal_id=principal_id)
        assert response.error is not None, response.result
        assert response.error.code is code, response.error
        assert detail in response.error.safe_details, response.error

    def count(self, table: Table, **where: object) -> int:
        statement = select(func.count()).select_from(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        with self.engine.connect() as connection:
            return int(connection.execute(statement).scalar_one())

    def rows(self, table: Table, **where: object) -> list[dict[str, Any]]:
        statement = select(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def version(self, meeting_id: str) -> int:
        (row,) = self.rows(meetings, meeting_id=meeting_id)
        return int(row["version"])

    def writes(self) -> int:
        """Every row a refused bind must not have written."""
        return (
            self.count(meeting_provider_bindings)
            + self.count(meeting_series_provider_bindings)
            + self.count(meeting_history)
            + self.count(record_events)
            + self.count(meeting_write_requests, capability=BIND)
        )


@pytest.fixture
def scene(disposable_database: str) -> Iterator[Scene]:
    runtime = Runtime(disposable_database)
    try:
        with runtime.work_engine.begin() as connection:
            mine = _insert_partition(connection)
            theirs = _insert_partition(connection)
        yield Scene(runtime=runtime, mine=mine, theirs=theirs)
    finally:
        runtime.close()


def _create(
    scene: Scene, key: str, *, series: str | None = "Synthetic series", **extra: object
) -> dict[str, Any]:
    fields: dict[str, object] = {"series_title": series} if series is not None else {}
    fields.update(extra)
    return scene.ok(
        CreateMeeting(
            title="Synthetic meeting",
            start_at=START,
            timezone_name="UTC",
            idempotency_key=key,
            **fields,
        ),
        principal_id=None,
    )["meeting"]


def _occurrence(
    meeting_id: str, key: str, version: int = 1, **overrides: object
) -> BindMeetingProvider:
    values: dict[str, object] = {
        "action": "bind",
        "meeting_id": meeting_id,
        "expected_version": version,
        "idempotency_key": key,
        "calendar_ref": CALENDAR,
        "ical_uid": SERIES_UID,
        "occurrence_original_start_utc": datetime(2026, 12, 2, 14, tzinfo=UTC),
        "series_ical_uid": SERIES_UID,
        "provider_event_id": "evt-0001",
        "provider_event_id_format": "mutable",
    }
    values.update(overrides)
    return BindMeetingProvider(**values)  # type: ignore[arg-type]


def _single(
    meeting_id: str, key: str, version: int = 1, **overrides: object
) -> BindMeetingProvider:
    values: dict[str, object] = {
        "ical_uid": SINGLE_UID,
        "occurrence_original_start_utc": None,
        "series_ical_uid": None,
    }
    values.update(overrides)
    return _occurrence(meeting_id, key, version, **values)


def _unbind(meeting_id: str, key: str, version: int) -> BindMeetingProvider:
    return BindMeetingProvider(
        action="unbind", meeting_id=meeting_id, expected_version=version, idempotency_key=key
    )


# ---- bind ---------------------------------------------------------------------------


def test_a_single_meeting_bind(scene: Scene) -> None:
    meeting = _create(scene, "create-single", series=None)
    answer = scene.ok(_single(meeting["meeting_id"], "bind-single"))
    assert (answer["meeting_id"], answer["version"], answer["action"]) == (
        meeting["meeting_id"],
        2,
        "bind",
    )
    assert answer["replayed"] is False
    binding = answer["binding"]
    assert binding["ical_uid"] == SINGLE_UID
    assert binding["occurrence_original_start_utc"] is None
    assert binding["series_ical_uid"] is None and binding["meeting_series_id"] is None
    assert (binding["provider_event_id"], binding["provider_event_id_format"]) == (
        "evt-0001",
        "mutable",
    )
    assert binding["provider_state"] == "active" and binding["last_seen_at"] is None
    assert "principal_id" not in binding
    (row,) = scene.rows(meeting_provider_bindings, meeting_id=meeting["meeting_id"])
    assert row["principal_id"] == scene.principal_id
    assert row["last_seen_source_sha256"] is None
    # A bind carries no publication: no ordering stamp until a sync applies one.
    assert row["last_applied_generated_at_utc"] is None
    assert scene.count(meeting_series_provider_bindings) == 0
    assert scene.version(meeting["meeting_id"]) == 2


def test_an_occurrence_bind_also_binds_the_meetings_series(scene: Scene) -> None:
    meeting = _create(scene, "create-occurrence")
    answer = scene.ok(_occurrence(meeting["meeting_id"], "bind-occurrence"))
    assert answer["binding"]["meeting_series_id"] == meeting["meeting_series_id"]
    assert answer["binding"]["occurrence_original_start_utc"] == ORIGINAL.replace("Z", ".000Z")
    (series,) = scene.rows(meeting_series_provider_bindings, principal_id=scene.principal_id)
    assert (series["meeting_series_id"], series["calendar_ref"], series["series_ical_uid"]) == (
        meeting["meeting_series_id"],
        CALENDAR,
        SERIES_UID,
    )
    # A second occurrence of the same series reuses the series binding.
    second = scene.ok(
        CreateMeeting(
            title="Second",
            start_at=START,
            timezone_name="UTC",
            idempotency_key="create-second",
            meeting_series_id=meeting["meeting_series_id"],
        )
    )["meeting"]
    scene.ok(
        _occurrence(
            second["meeting_id"],
            "bind-second",
            occurrence_original_start_utc=datetime(2026, 12, 9, 14, tzinfo=UTC),
        )
    )
    assert scene.count(meeting_series_provider_bindings) == 1
    assert scene.count(meeting_provider_bindings) == 2


def test_the_receipt_event_and_audit_row(scene: Scene) -> None:
    meeting = _create(scene, "create-receipt")
    answer = scene.ok(_occurrence(meeting["meeting_id"], "bind-receipt"))
    history = answer["history"]
    assert (history["action"], history["actor"], history["outcome"]) == (
        "update",
        "principal",
        "applied",
    )
    assert (history["before_version"], history["after_version"]) == (1, 2)
    (receipt,) = scene.rows(meeting_history, history_id=history["history_id"])
    assert receipt["idempotency_key"] == "bind-receipt"
    (request,) = scene.rows(meeting_write_requests, capability=BIND)
    assert (request["meeting_history_id"], request["result_version"]) == (history["history_id"], 2)
    (event,) = [
        row
        for row in scene.rows(record_events, record_id=meeting["meeting_id"])
        if row["source_capability"] == BIND
    ]
    assert event["changed_fields"] == ["provider_binding"]
    assert (event["event_kind"], event["record_version"], event["actor_class"]) == (
        "updated",
        2,
        "principal",
    )
    assert event["source_receipt_id"] == history["history_id"]
    audits = scene.rows(audit_events, capability=BIND)
    assert [(row["purpose"], row["outcome"]) for row in audits] == [
        ("meeting_authoring", "allowed")
    ]


# ---- refusals ---------------------------------------------------------------------


def test_an_occurrence_key_on_a_standalone_meeting_is_refused(scene: Scene) -> None:
    meeting = _create(scene, "create-standalone", series=None)
    before = scene.writes()
    scene.refused(
        _occurrence(meeting["meeting_id"], "bind-standalone"),
        ErrorCode.INVALID_REQUEST,
        "provider_binding_requires_series",
    )
    assert scene.writes() == before
    assert scene.version(meeting["meeting_id"]) == 1


def test_a_series_bound_to_a_different_uid_is_refused(scene: Scene) -> None:
    first = _create(scene, "create-uid-a")
    scene.ok(_occurrence(first["meeting_id"], "bind-uid-a"))
    second = scene.ok(
        CreateMeeting(
            title="Same series",
            start_at=START,
            timezone_name="UTC",
            idempotency_key="create-uid-b",
            meeting_series_id=first["meeting_series_id"],
        )
    )["meeting"]
    before = scene.writes()
    scene.refused(
        _occurrence(second["meeting_id"], "bind-uid-b", ical_uid="uid-b", series_ical_uid="uid-b"),
        ErrorCode.INVALID_REQUEST,
        "provider_series_binding_conflict",
    )
    assert scene.writes() == before


def test_a_uid_bound_to_another_series_is_refused(scene: Scene) -> None:
    first = _create(scene, "create-series-a")
    scene.ok(_occurrence(first["meeting_id"], "bind-series-a"))
    other = _create(scene, "create-series-b", series="Another series")
    before = scene.writes()
    scene.refused(
        _occurrence(
            other["meeting_id"],
            "bind-series-b",
            occurrence_original_start_utc=datetime(2026, 12, 9, 14, tzinfo=UTC),
        ),
        ErrorCode.INVALID_REQUEST,
        "provider_series_binding_conflict",
    )
    assert scene.writes() == before


def test_a_key_bound_to_another_meeting_is_refused(scene: Scene) -> None:
    first = _create(scene, "create-key-a", series=None)
    scene.ok(_single(first["meeting_id"], "bind-key-a"))
    other = _create(scene, "create-key-b", series=None)
    before = scene.writes()
    scene.refused(
        _single(other["meeting_id"], "bind-key-b"),
        ErrorCode.INVALID_REQUEST,
        "provider_key_bound_to_another_meeting",
    )
    assert scene.writes() == before


def test_an_already_bound_meeting_is_refused(scene: Scene) -> None:
    meeting = _create(scene, "create-twice", series=None)
    scene.ok(_single(meeting["meeting_id"], "bind-twice-1"))
    before = scene.writes()
    for key, ical_uid in (("bind-twice-2", SINGLE_UID), ("bind-twice-3", "uid-another")):
        scene.refused(
            _single(meeting["meeting_id"], key, 2, ical_uid=ical_uid),
            ErrorCode.INVALID_REQUEST,
            "meeting_already_provider_bound",
        )
    assert scene.writes() == before


def test_single_and_occurrence_bindings_never_mix_for_one_uid(scene: Scene) -> None:
    single = _create(scene, "create-mix-single", series=None)
    scene.ok(_single(single["meeting_id"], "bind-mix-single", ical_uid=SERIES_UID))
    occurrence = _create(scene, "create-mix-occurrence")
    before = scene.writes()
    scene.refused(
        _occurrence(occurrence["meeting_id"], "bind-mix-occurrence"),
        ErrorCode.INVALID_REQUEST,
        "provider_binding_kind_conflict",
    )
    assert scene.writes() == before


def test_an_unbind_of_an_unbound_meeting_is_refused(scene: Scene) -> None:
    meeting = _create(scene, "create-unbound")
    before = scene.writes()
    scene.refused(
        _unbind(meeting["meeting_id"], "unbind-unbound", 1),
        ErrorCode.INVALID_REQUEST,
        "meeting_not_provider_bound",
    )
    assert scene.writes() == before


# ---- unbind, CAS, replay ----------------------------------------------------------


def test_unbind_deletes_the_binding_and_keeps_the_series_binding(scene: Scene) -> None:
    meeting = _create(scene, "create-unbind")
    scene.ok(_occurrence(meeting["meeting_id"], "bind-unbind"))
    answer = scene.ok(_unbind(meeting["meeting_id"], "unbind-0001", 2))
    assert (answer["action"], answer["version"], answer["binding"]) == ("unbind", 3, None)
    assert scene.count(meeting_provider_bindings) == 0
    assert scene.count(meeting_series_provider_bindings) == 1
    events = [
        row
        for row in scene.rows(record_events, record_id=meeting["meeting_id"])
        if row["source_capability"] == BIND
    ]
    assert sorted(row["record_version"] for row in events) == [2, 3]
    # Its own series stays bound to the same UID, so it can be bound again.
    again = scene.ok(_occurrence(meeting["meeting_id"], "bind-again", 3))
    assert again["version"] == 4


def test_a_stale_version_is_conflict_and_writes_nothing(scene: Scene) -> None:
    meeting = _create(scene, "create-stale", series=None)
    before = scene.writes()
    scene.refused(
        _single(meeting["meeting_id"], "bind-stale", 2), ErrorCode.CONFLICT, "stale_version"
    )
    assert scene.writes() == before


def test_a_replay_answers_the_original_and_a_changed_request_is_a_conflict(scene: Scene) -> None:
    meeting = _create(scene, "create-replay", series=None)
    first = scene.ok(_single(meeting["meeting_id"], "bind-replay"))
    replay = scene.ok(_single(meeting["meeting_id"], "bind-replay"))
    assert replay["replayed"] is True
    assert (replay["version"], replay["history"]) == (first["version"], first["history"])
    assert replay["binding"] == first["binding"]
    assert scene.version(meeting["meeting_id"]) == 2
    assert scene.count(meeting_history, meeting_id=meeting["meeting_id"]) == 2
    scene.refused(
        _single(meeting["meeting_id"], "bind-replay", provider_event_id="evt-changed"),
        ErrorCode.CONFLICT,
        "idempotency_conflict",
    )
    assert scene.version(meeting["meeting_id"]) == 2


def test_principals_are_isolated(scene: Scene) -> None:
    meeting = _create(scene, "create-isolated", series=None)
    other = scene.theirs.principal.principal_id
    # Another Principal cannot see, bind or unbind it: absent and foreign are one answer.
    scene.refused(
        _single(meeting["meeting_id"], "bind-foreign"),
        ErrorCode.NOT_FOUND,
        "meeting_id",
        principal_id=other,
    )
    scene.ok(_single(meeting["meeting_id"], "bind-mine"))
    scene.refused(
        _unbind(meeting["meeting_id"], "unbind-foreign", 2),
        ErrorCode.NOT_FOUND,
        "meeting_id",
        principal_id=other,
    )
    # The same key in another partition binds that Principal's own Meeting.
    theirs = scene.ok(
        CreateMeeting(
            title="Theirs", start_at=START, timezone_name="UTC", idempotency_key="create-theirs"
        ),
        principal_id=other,
    )["meeting"]
    scene.ok(_single(theirs["meeting_id"], "bind-mine"), principal_id=other)
    assert scene.count(meeting_provider_bindings, principal_id=other) == 1
    assert scene.count(meeting_provider_bindings, principal_id=scene.principal_id) == 1


# ---- D6 ----------------------------------------------------------------------------


def test_d6_a_bound_series_move_is_refused_then_unbind_then_it_succeeds(scene: Scene) -> None:
    meeting = _create(scene, "create-d6")
    target = _create(scene, "create-d6-target", series="Target series")
    scene.ok(_occurrence(meeting["meeting_id"], "bind-d6"))
    move = UpdateMeeting(
        meeting_id=meeting["meeting_id"],
        expected_version=2,
        idempotency_key="move-d6-1",
        meeting_series_id=target["meeting_series_id"],
    )
    scene.refused(move, ErrorCode.INVALID_REQUEST, "meeting_series_change_refused_provider_bound")
    scene.ok(_unbind(meeting["meeting_id"], "unbind-d6", 2))
    moved = scene.ok(
        UpdateMeeting(
            meeting_id=meeting["meeting_id"],
            expected_version=3,
            idempotency_key="move-d6-2",
            meeting_series_id=target["meeting_series_id"],
        )
    )
    assert moved["meeting"]["meeting_series_id"] == target["meeting_series_id"]
    assert moved["meeting"]["version"] == 4
