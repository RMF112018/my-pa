"""UTC time primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc, format_rfc3339, utc_now


def test_utc_now_is_aware_and_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(NaiveDatetimeError):
        ensure_utc(datetime(2026, 7, 30, 20, 0, 0))


def test_offset_datetime_is_converted_not_relabelled() -> None:
    eastern = timezone(timedelta(hours=-4))
    value = datetime(2026, 7, 30, 16, 0, 0, tzinfo=eastern)
    converted = ensure_utc(value)
    assert converted.tzinfo is UTC
    assert converted.hour == 20
    assert converted == value


def test_rfc3339_uses_z_suffix_and_millisecond_precision() -> None:
    value = datetime(2026, 7, 30, 20, 0, 1, 123456, tzinfo=UTC)
    assert format_rfc3339(value) == "2026-07-30T20:00:01.123Z"


def test_rfc3339_normalises_offset_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    value = datetime(2026, 7, 30, 16, 0, 1, 0, tzinfo=eastern)
    assert format_rfc3339(value) == "2026-07-30T20:00:01.000Z"


def test_rfc3339_rejects_naive() -> None:
    with pytest.raises(NaiveDatetimeError):
        format_rfc3339(datetime(2026, 7, 30))
