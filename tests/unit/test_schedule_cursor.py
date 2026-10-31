"""CPM Workbench S5b-2: the Schedule keyset cursor (FAST).

Worker and capabilities contract section 3.7 (R2 section 32.1): the round trip
for each of the 5 orders, the 512-character bound, the 300 s TTL and the
future-issue refusal, a binding that covers every input that decides a page
(capability, Principal, purpose, every normalized command field, the effective
page size, the order and, for changes, the delta algorithm), and a forged
position that carries no authority. Every value is synthetic.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.application import schedules as schedules_module
from my_pa.application.commands import (
    ListScheduleActivities,
    ListScheduleChanges,
    ListSchedulePublications,
    ListScheduleSeries,
    ReadScheduleActivityHistory,
)
from my_pa.domain.schedule import cursor as cursor_module
from my_pa.domain.schedule.cursor import (
    DEFAULT_SCHEDULE_PAGE_SIZE,
    MAX_SCHEDULE_CURSOR_CHARACTERS,
    MAX_SCHEDULE_PAGE_SIZE,
    SCHEDULE_CURSOR_TTL_SECONDS,
    ScheduleCursorError,
    ScheduleCursorOrder,
    decode_schedule_cursor,
    encode_schedule_cursor,
    schedule_cursor_binding,
)

NOW: Final = datetime(2026, 10, 31, 12, tzinfo=UTC)
INSTANT: Final = datetime(2026, 10, 30, 8, 15, 30, 123456, tzinfo=UTC)

_POSITIONS: Final[dict[ScheduleCursorOrder, tuple[Any, ...]]] = {
    ScheduleCursorOrder.SERIES: (INSTANT, "sser_cursor0001"),
    ScheduleCursorOrder.PUBLICATIONS: (INSTANT, "spub_cursor0001"),
    ScheduleCursorOrder.ACTIVITIES: (17, "srow_cursor0001"),
    ScheduleCursorOrder.HISTORY: (date(2026, 5, 4), INSTANT, "spub_cursor0001"),
    ScheduleCursorOrder.CHANGES: (125,),
}


def _binding(**overrides: Any) -> str:  # noqa: ANN401
    inputs: dict[str, Any] = {
        "capability": "schedule_series.list",
        "principal_id": "prn_cursor0001",
        "purpose": "schedule_read",
        "request": {"project_id": "prj_cursor0001"},
        "page_size": 25,
        "order": ScheduleCursorOrder.SERIES,
    }
    inputs.update(overrides)
    return schedule_cursor_binding(**inputs)


def _token(document: dict[str, Any]) -> str:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_the_bounds_are_the_contract_constants() -> None:
    assert (MAX_SCHEDULE_PAGE_SIZE, DEFAULT_SCHEDULE_PAGE_SIZE) == (100, 25)
    assert (MAX_SCHEDULE_CURSOR_CHARACTERS, SCHEDULE_CURSOR_TTL_SECONDS) == (512, 300)


@pytest.mark.parametrize("order", list(ScheduleCursorOrder), ids=lambda order: order.name)
def test_round_trip(order: ScheduleCursorOrder) -> None:
    binding = _binding(order=order)
    token = encode_schedule_cursor(
        binding=binding, order=order, position=_POSITIONS[order], issued_at=NOW
    )
    assert len(token) <= MAX_SCHEDULE_CURSOR_CHARACTERS
    assert "=" not in token
    decoded = decode_schedule_cursor(token, binding=binding, order=order, now=NOW)
    assert decoded.position == _POSITIONS[order]
    assert decoded.order is order
    # No position carries source text: every element is an instant, a date, an
    # integer or an opaque identifier.
    document = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert set(document) == {"b", "p", "t", "v"}


def test_length_bound() -> None:
    binding = _binding()
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(
            "A" * (MAX_SCHEDULE_CURSOR_CHARACTERS + 1),
            binding=binding,
            order=ScheduleCursorOrder.SERIES,
            now=NOW,
        )
    # The bound is checked before anything is decoded: an over-long token that
    # is otherwise a perfectly valid cursor is refused.
    valid = encode_schedule_cursor(
        binding=binding,
        order=ScheduleCursorOrder.SERIES,
        position=_POSITIONS[ScheduleCursorOrder.SERIES],
        issued_at=NOW,
    )
    padded = _token(
        {
            "b": binding,
            "p": [INSTANT.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "sser_" + "a" * 64],
            "t": int(NOW.timestamp()),
            "v": 1,
        }
    )
    assert len(valid) <= MAX_SCHEDULE_CURSOR_CHARACTERS
    long_token = padded + "A" * (MAX_SCHEDULE_CURSOR_CHARACTERS + 1 - len(padded))
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(
            long_token, binding=binding, order=ScheduleCursorOrder.SERIES, now=NOW
        )
    # An encoder result over the bound is a programming error, never a token.
    with pytest.raises(ValueError, match="exceeds its bound"):
        encode_schedule_cursor(
            binding=binding,
            order=ScheduleCursorOrder.ACTIVITIES,
            position=(1, "srow_" + "a" * 600),
            issued_at=NOW,
        )


def test_ttl() -> None:
    binding = _binding()
    order = ScheduleCursorOrder.SERIES
    token = encode_schedule_cursor(
        binding=binding, order=order, position=_POSITIONS[order], issued_at=NOW
    )
    at_limit = NOW + timedelta(seconds=SCHEDULE_CURSOR_TTL_SECONDS)
    assert decode_schedule_cursor(token, binding=binding, order=order, now=at_limit)
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(
            token, binding=binding, order=order, now=at_limit + timedelta(seconds=1)
        )
    # Issued in the future (beyond a 5 s allowance) is refused too.
    assert decode_schedule_cursor(
        token, binding=binding, order=order, now=NOW - timedelta(seconds=5)
    )
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(token, binding=binding, order=order, now=NOW - timedelta(seconds=6))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not base64 at all",
        "!!!!",
        _token({"b": "0" * 64, "p": [], "t": 0}),
        _token({"b": "0" * 64, "p": [1], "t": 0, "v": 2}),
        _token({"b": "0" * 64, "p": [1], "t": "0", "v": 1}),
        _token({"b": "0" * 64, "p": [1], "t": True, "v": 1}),
        base64.urlsafe_b64encode(b"[1,2,3]").decode().rstrip("="),
        # A non-canonical spelling of an otherwise valid document.
        base64.urlsafe_b64encode(b'{"v":1,"t":0,"p":[1],"b":"' + b"0" * 64 + b'"}')
        .decode()
        .rstrip("="),
    ],
    ids=[
        "empty",
        "spaces",
        "alphabet",
        "missing_key",
        "version",
        "text_time",
        "bool_time",
        "not_object",
        "not_canonical",
    ],
)
def test_malformed_cursors_are_one_refusal(token: str) -> None:
    with pytest.raises(ScheduleCursorError) as refused:
        decode_schedule_cursor(token, binding="0" * 64, order=ScheduleCursorOrder.CHANGES, now=NOW)
    assert str(refused.value) == "the schedule cursor cannot continue this request"


@pytest.mark.parametrize(
    ("order", "position"),
    [
        (ScheduleCursorOrder.SERIES, ["2026-10-30T08:15:30Z", "sser_cursor0001"]),
        (ScheduleCursorOrder.SERIES, ["2026-10-30T08:15:30.123456Z", "spub_cursor0001"]),
        (ScheduleCursorOrder.PUBLICATIONS, ["2026-13-30T08:15:30.123456Z", "spub_cursor0001"]),
        (ScheduleCursorOrder.ACTIVITIES, [0, "srow_cursor0001"]),
        (ScheduleCursorOrder.ACTIVITIES, [True, "srow_cursor0001"]),
        (ScheduleCursorOrder.HISTORY, ["2026-05-04", "2026-10-30T08:15:30.123456Z"]),
        (ScheduleCursorOrder.CHANGES, [-1]),
        (ScheduleCursorOrder.CHANGES, ["A-100"]),
    ],
    ids=[
        "instant_format",
        "wrong_id_kind",
        "invalid_month",
        "ordinal_zero",
        "ordinal_bool",
        "history_short",
        "negative_offset",
        "published_id_offset",
    ],
)
def test_each_position_element_is_shape_checked(
    order: ScheduleCursorOrder, position: list[object]
) -> None:
    binding = _binding(order=order)
    token = _token({"b": binding, "p": position, "t": int(NOW.timestamp()), "v": 1})
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(token, binding=binding, order=order, now=NOW)


# ---- the binding covers every field ------------------------------------------------------


#: One representative command per list read, every optional field set.
_COMMANDS: Final[dict[str, Any]] = {
    "series": ListScheduleSeries(project_id="prj_cursor0001", page_size=10),
    "publications": ListSchedulePublications(
        series_id="sser_cursor0001",
        publication_role="update",
        status="complete",
        page_size=10,
    ),
    "activities": ListScheduleActivities(
        publication_id="spub_cursor0001",
        row_type="activity",
        hierarchy_prefix=("Synthetic WBS",),
        start_from="2026-05-01",
        start_to="2026-05-31",
        finish_from="2026-06-01",
        finish_to="2026-06-30",
        page_size=10,
    ),
    "history": ReadScheduleActivityHistory(schedule_activity_id="sact_cursor0001", page_size=10),
    "changes": ListScheduleChanges(
        from_publication_id="spub_cursor0001",
        to_publication_id="spub_cursor0002",
        change_kind="renamed",
        page_size=10,
    ),
}

#: A different, still valid, value for every command field a cursor binds.
_OTHER: Final[dict[str, object]] = {
    "project_id": "prj_cursor0002",
    "series_id": "sser_cursor0002",
    "publication_role": "baseline",
    "status": "partial",
    "publication_id": "spub_cursor0009",
    "row_type": "milestone",
    "hierarchy_prefix": ("Other WBS",),
    "start_from": "2026-05-02",
    "start_to": "2026-05-30",
    "finish_from": "2026-06-02",
    "finish_to": "2026-06-29",
    "schedule_activity_id": "sact_cursor0002",
    "from_publication_id": "spub_cursor0003",
    "to_publication_id": "spub_cursor0004",
    "change_kind": "added",
}


def _request_cases() -> list[tuple[str, str]]:
    return [
        (name, item.name)
        for name, command in _COMMANDS.items()
        for item in fields(command)
        if item.name not in {"cursor", "page_size"}
    ]


@pytest.mark.parametrize(
    "field",
    ["capability", "principal_id", "purpose", "page_size", "order", "algorithm_version"],
)
def test_binding_covers_every_field(field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    changes = {"order": ScheduleCursorOrder.CHANGES}
    base = _binding(**changes)
    if field == "algorithm_version":
        # Offset semantics depend on the algorithm, so a new version rebinds.
        monkeypatch.setattr(cursor_module, "DELTA_ALGORITHM_VERSION", "cpm-workbench-full-delta-v2")
        other = _binding(**changes)
    elif field == "order":
        other = _binding(order=ScheduleCursorOrder.HISTORY)
    else:
        varied: dict[str, Any] = {
            "capability": "schedule_changes.list",
            "principal_id": "prn_cursor0002",
            "purpose": "schedule_import",
            "page_size": 26,
        }
        other = _binding(**changes, **{field: varied[field]})
    assert other != base
    token = encode_schedule_cursor(
        binding=base, order=ScheduleCursorOrder.CHANGES, position=(5,), issued_at=NOW
    )
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(token, binding=other, order=ScheduleCursorOrder.CHANGES, now=NOW)


@pytest.mark.parametrize(("read", "field"), _request_cases(), ids=lambda value: str(value))
def test_binding_covers_every_request_field(read: str, field: str) -> None:
    """Every normalized command field of every list read moves the binding."""
    command = _COMMANDS[read]
    request: Callable[[object], dict[str, object]] = schedules_module._request_of
    baseline = request(command)
    changed = request(replace(command, **{field: _OTHER[field]}))
    assert set(baseline) == {item.name for item in fields(command)} - {"cursor", "page_size"}
    assert changed != baseline
    assert _binding(request=changed) != _binding(request=baseline)


def test_forged_position_reads_nothing_unauthorized() -> None:
    """A position is a keyset bound, not a capability.

    A caller who forges a well-formed position under its own binding gets back
    only that position -- an instant and an identifier the same query compares
    against inside the caller's partition, every page re-authorized by
    `invoke` (the database tier proves the page stays the caller's). A forged
    position under any other request's binding, or naming an identifier of
    another kind, is refused before any read.
    """
    order = ScheduleCursorOrder.SERIES
    mine = _binding(order=order)
    theirs = _binding(order=order, principal_id="prn_cursor0002")
    forged = (datetime(2099, 1, 1, tzinfo=UTC), "sser_someoneelse0001")
    token = encode_schedule_cursor(binding=mine, order=order, position=forged, issued_at=NOW)
    decoded = decode_schedule_cursor(token, binding=mine, order=order, now=NOW)
    assert decoded.position == forged
    assert decoded.binding == mine
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(token, binding=theirs, order=order, now=NOW)
    wrong_kind = _token(
        {
            "b": mine,
            "p": ["2099-01-01T00:00:00.000000Z", "prj_someoneelse0001"],
            "t": int(NOW.timestamp()),
            "v": 1,
        }
    )
    with pytest.raises(ScheduleCursorError):
        decode_schedule_cursor(wrong_kind, binding=mine, order=order, now=NOW)
