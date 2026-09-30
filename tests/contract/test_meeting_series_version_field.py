"""WP-RE-05, OD-7 (i): `series_version` on the Meeting read shapes (plan D-21, V-006).

A `meeting_series` Record Event carries the series version as its
`record_version`. Under operator ruling OD-7 (i) a consumer must be able to
compare that against the locally held canonical version, so the two Meeting
read shapes -- `MeetingView` (`meetings.read` and every write answer) and
`MeetingListEntry` (`meetings.list`/`meetings.search`) -- gain the additive
field `series_version: int | None`. It is named so it can never be confused with
the Meeting's own `version`, which keeps its name and meaning.

What is pinned here (FAST, no marker):

* both shapes declare `series_version`, nullable, `>= 1`, beside an unchanged
  `version`;
* a standalone Meeting carries no series version; a series member may carry one;
* the canonical dictionary publishes it;
* through the application over the conftest fake, a read and a list row carry
  the series' current version, which advances on a material retitle while the
  Meeting's own `version` does not.

The SQL read query's half is `tests/database/test_meeting_record_events.py`.
Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import ValidationError
from tests.conftest import FakeUnitOfWork, World

from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.v1.meetings import MeetingListEntry, MeetingView
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.meeting.model import (
    MeetingCreateRequest,
    MeetingListRequest,
    MeetingSeriesUpdateRequest,
    MeetingStatus,
)

PRINCIPAL: Final = "prn_meetseriesver0001"
AT: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
MEETING: Final = make_identifier(IdKind.MEETING, "seriesver0001")
SERIES: Final = make_identifier(IdKind.MEETING_SERIES, "seriesver0001")
APP: Final = MeetingApplication()

type Builder = Callable[..., MeetingView | MeetingListEntry]


def _view(**extra: object) -> MeetingView:
    fields: dict[str, Any] = {
        "meeting_id": MEETING,
        "title": "Synthetic sync",
        "status": MeetingStatus.SCHEDULED,
        "start_at": AT,
        "timezone_name": "UTC",
        "version": 3,
        "created_at": AT,
        "updated_at": AT,
        **extra,
    }
    return MeetingView(**fields)


def _entry(**extra: object) -> MeetingListEntry:
    fields: dict[str, Any] = {
        "meeting_id": MEETING,
        "title": "Synthetic sync",
        "status": MeetingStatus.SCHEDULED,
        "start_at": AT,
        "timezone_name": "UTC",
        "version": 3,
        "attendee_count": 0,
        "attachment_count": 0,
        "updated_at": AT,
        **extra,
    }
    return MeetingListEntry(**fields)


@pytest.mark.parametrize("shape", [MeetingView, MeetingListEntry], ids=lambda s: s.__name__)
def test_both_read_shapes_declare_a_nullable_series_version_beside_version(
    shape: type[MeetingView] | type[MeetingListEntry],
) -> None:
    field = shape.model_fields["series_version"]
    assert field.annotation == int | None
    assert field.default is None
    assert any(getattr(item, "ge", None) == 1 for item in field.metadata)
    assert shape.model_fields["version"].annotation is int


@pytest.mark.parametrize("build", [_view, _entry], ids=["MeetingView", "MeetingListEntry"])
def test_a_series_member_carries_its_series_version_and_publishes_it(build: Builder) -> None:
    built = build(meeting_series_id=SERIES, series_title="Synthetic series", series_version=5)
    assert built.series_version == 5
    assert built.version == 3
    dumped = built.to_canonical_dict()
    assert dumped["series_version"] == 5
    assert dumped["version"] == 3


@pytest.mark.parametrize("build", [_view, _entry], ids=["MeetingView", "MeetingListEntry"])
def test_a_standalone_meeting_carries_no_series_version(build: Builder) -> None:
    assert build().series_version is None
    assert build().to_canonical_dict()["series_version"] is None
    with pytest.raises(ValidationError, match="standalone Meeting carries no series version"):
        build(series_version=1)


@pytest.mark.parametrize("build", [_view, _entry], ids=["MeetingView", "MeetingListEntry"])
def test_a_series_version_below_one_is_refused(build: Builder) -> None:
    with pytest.raises(ValidationError):
        build(meeting_series_id=SERIES, series_title="Synthetic series", series_version=0)


def test_reads_carry_the_current_series_version_through_a_retitle() -> None:
    world = World()
    with FakeUnitOfWork(world) as uow:
        created = APP.create_meeting(
            uow,
            PRINCIPAL,
            MeetingCreateRequest(
                title="Synthetic sync",
                start_at=AT,
                timezone_name="UTC",
                series_title="Synthetic series",
            ),
            "series-version-create",
            AT,
        )
    series_id = created.meeting.meeting_series_id
    assert series_id is not None
    assert created.meeting.series_version == 1
    with FakeUnitOfWork(world) as uow:
        APP.update_meeting_series(
            uow,
            PRINCIPAL,
            MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Renamed series"),
            1,
            "series-version-retitle",
            AT,
        )
    with FakeUnitOfWork(world) as uow:
        read = APP.read_meeting(uow, PRINCIPAL, created.meeting.meeting_id)
        page = APP.list_meetings(uow, PRINCIPAL, MeetingListRequest(page_size=10), AT)
    assert read.series_version == 2
    assert read.version == 1
    assert len(page.entries) == 1
    (entry,) = page.entries
    assert entry.series_version == 2
    assert entry.version == 1
