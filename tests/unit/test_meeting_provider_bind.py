"""WP2-W3: the `meetings.provider.bind` request model and its pure decision rules.

FAST. `MeetingProviderBindRequest` validates the per-action field rules and the
provider-key bounds; `bind_decision` is the closed refusal order of contract
section 12.2 rule 4 (Manager rulings D9, D10). The application half over the
fake unit of work is at the bottom; the database half is
`tests/database/test_meeting_provider_bind.py`. Every value is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Final

import pytest

from my_pa.application.meetings import (
    MeetingApplication,
    MeetingProviderBindResult,
    meeting_request_digest,
)
from my_pa.domain.meeting.model import (
    MEETINGS_PROVIDER_BIND_NAME,
    MeetingCreateRequest,
    MeetingErrorField,
    MeetingInvalidRequestError,
    MeetingNotFoundError,
    MeetingStaleVersionError,
)
from my_pa.domain.meeting_sync.binding import (
    BoundSeries,
    MeetingProviderBindRequest,
    ProviderBindAction,
    bind_decision,
)
from my_pa.domain.meeting_sync.model import ProviderBindingState, ProviderEventIdFormat
from tests.conftest import FakeUnitOfWork, World

MEETING: Final = "mtg_bindunit00000001"
OTHER_MEETING: Final = "mtg_bindunit00000002"
SERIES: Final = "mser_bindunit0000001"
OTHER_SERIES: Final = "mser_bindunit0000002"
ORIGINAL: Final = datetime(2026, 12, 2, 14, tzinfo=UTC)
CALENDAR: Final = "cal-synthetic"
UID: Final = "uid-series@example.invalid"
PRINCIPAL: Final = "prn_bindunitfast0001"
NOW: Final = datetime(2026, 11, 21, 6, tzinfo=UTC)
APP: Final = MeetingApplication()


def _bind(**overrides: Any) -> MeetingProviderBindRequest:  # noqa: ANN401
    values: dict[str, Any] = {
        "action": ProviderBindAction.BIND,
        "meeting_id": MEETING,
        "calendar_ref": CALENDAR,
        "ical_uid": UID,
        "occurrence_original_start_utc": ORIGINAL,
        "series_ical_uid": UID,
    }
    values.update(overrides)
    return MeetingProviderBindRequest(**values)


def _single(**overrides: Any) -> MeetingProviderBindRequest:  # noqa: ANN401
    values: dict[str, Any] = {
        "occurrence_original_start_utc": None,
        "series_ical_uid": None,
        "ical_uid": "uid-single@example.invalid",
    }
    values.update(overrides)
    return _bind(**values)


def _refused(token: MeetingErrorField, **overrides: Any) -> None:  # noqa: ANN401
    with pytest.raises(MeetingInvalidRequestError) as refused:
        _bind(**overrides)
    assert refused.value.field is token


# ---- the request model ---------------------------------------------------------


def test_an_occurrence_and_a_single_bind_are_accepted() -> None:
    occurrence = _bind()
    assert occurrence.key.is_occurrence
    assert occurrence.event_id_format is ProviderEventIdFormat.UNKNOWN
    single = _single(
        provider_event_id="evt-1", provider_event_id_format=ProviderEventIdFormat.MUTABLE
    )
    assert not single.key.is_occurrence
    assert single.event_id_format is ProviderEventIdFormat.MUTABLE


def test_the_original_start_is_canonicalized_to_utc_and_a_naive_one_is_refused() -> None:
    offset = timezone(timedelta(hours=-5))
    request = _bind(occurrence_original_start_utc=datetime(2026, 12, 2, 9, tzinfo=offset))
    assert request.occurrence_original_start_utc == ORIGINAL
    assert request.occurrence_original_start_utc.tzinfo is UTC
    _refused(
        MeetingErrorField.OCCURRENCE_ORIGINAL_START_UTC,
        occurrence_original_start_utc=datetime(2026, 12, 2, 14),
    )


@pytest.mark.parametrize(
    ("overrides", "token"),
    [
        ({"action": "bind"}, MeetingErrorField.ACTION),
        ({"meeting_id": "mser_bindunit0000001"}, MeetingErrorField.MEETING_ID),
        ({"calendar_ref": None}, MeetingErrorField.CALENDAR_REF),
        ({"calendar_ref": ""}, MeetingErrorField.CALENDAR_REF),
        ({"calendar_ref": "   "}, MeetingErrorField.CALENDAR_REF),
        ({"calendar_ref": "c" * 321}, MeetingErrorField.CALENDAR_REF),
        ({"ical_uid": None}, MeetingErrorField.ICAL_UID),
        ({"ical_uid": "u" * 1025}, MeetingErrorField.ICAL_UID),
        ({"series_ical_uid": None}, MeetingErrorField.SERIES_ICAL_UID),
        ({"series_ical_uid": ""}, MeetingErrorField.SERIES_ICAL_UID),
        ({"occurrence_original_start_utc": None}, MeetingErrorField.OCCURRENCE_ORIGINAL_START_UTC),
        ({"provider_event_id": ""}, MeetingErrorField.PROVIDER_EVENT_ID),
        ({"provider_event_id": "e" * 1025}, MeetingErrorField.PROVIDER_EVENT_ID),
        ({"provider_event_id_format": "mutable"}, MeetingErrorField.PROVIDER_EVENT_ID_FORMAT),
        (
            {"provider_event_id_format": ProviderEventIdFormat.IMMUTABLE_VERIFIED},
            MeetingErrorField.PROVIDER_EVENT_ID_FORMAT,
        ),
    ],
)
def test_a_malformed_bind_names_its_field(
    overrides: dict[str, Any], token: MeetingErrorField
) -> None:
    _refused(token, **overrides)


def test_an_unknown_format_needs_no_id() -> None:
    request = _bind(provider_event_id_format=ProviderEventIdFormat.UNKNOWN)
    assert request.event_id_format is ProviderEventIdFormat.UNKNOWN


def test_an_unbind_names_only_the_meeting() -> None:
    unbind = MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=MEETING)
    with pytest.raises(MeetingInvalidRequestError):
        _ = unbind.key
    for name, value, token in (
        ("calendar_ref", CALENDAR, MeetingErrorField.CALENDAR_REF),
        ("ical_uid", UID, MeetingErrorField.ICAL_UID),
        (
            "occurrence_original_start_utc",
            ORIGINAL,
            MeetingErrorField.OCCURRENCE_ORIGINAL_START_UTC,
        ),
        ("series_ical_uid", UID, MeetingErrorField.SERIES_ICAL_UID),
        ("provider_event_id", "evt-1", MeetingErrorField.PROVIDER_EVENT_ID),
        (
            "provider_event_id_format",
            ProviderEventIdFormat.MUTABLE,
            MeetingErrorField.PROVIDER_EVENT_ID_FORMAT,
        ),
    ):
        with pytest.raises(MeetingInvalidRequestError) as refused:
            MeetingProviderBindRequest(
                action=ProviderBindAction.UNBIND, meeting_id=MEETING, **{name: value}
            )
        assert refused.value.field is token


def test_no_refusal_echoes_a_key_value() -> None:
    private_ref = "private-calendar-of-someone@example.invalid"
    with pytest.raises(MeetingInvalidRequestError) as refused:
        _bind(calendar_ref=private_ref + " " * 400)
    assert private_ref not in str(refused.value)
    assert str(refused.value) == "invalid meeting request: calendar_ref"


def test_the_digest_covers_the_action_key_and_version_only() -> None:
    def digest(request: MeetingProviderBindRequest, version: int = 1) -> str:
        return meeting_request_digest(
            MEETINGS_PROVIDER_BIND_NAME, PRINCIPAL, request, expected_version=version
        )

    base = digest(_bind())
    assert base == digest(_bind())
    assert base != digest(_bind(), 2)
    assert base != digest(_bind(ical_uid="uid-other"))
    assert base != digest(_bind(provider_event_id="evt-1"))
    unbind = MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=MEETING)
    assert digest(unbind) != base


# ---- the decision ----------------------------------------------------------------


def _decide(request: MeetingProviderBindRequest | None = None, **state: Any) -> bool:  # noqa: ANN401
    values: dict[str, Any] = {
        "meeting_id": MEETING,
        "meeting_series_id": SERIES,
        "meeting_is_bound": False,
        "key_bound_meeting_id": None,
        "other_kind_bound": False,
        "uid_series": None,
        "meeting_series_binding": None,
    }
    values.update(state)
    return bind_decision(request or _bind(), **values).create_series_binding


def _decision_refused(
    token: MeetingErrorField,
    request: MeetingProviderBindRequest | None = None,
    **state: Any,  # noqa: ANN401
) -> None:
    with pytest.raises(MeetingInvalidRequestError) as refused:
        _decide(request, **state)
    assert refused.value.field is token


BOUND: Final = BoundSeries(meeting_series_id=SERIES, calendar_ref=CALENDAR, series_ical_uid=UID)


def test_an_occurrence_of_an_unbound_series_creates_the_series_binding() -> None:
    assert _decide() is True


def test_an_occurrence_of_its_own_bound_series_creates_none() -> None:
    assert _decide(uid_series=BOUND, meeting_series_binding=BOUND) is False


def test_a_single_bind_needs_no_series_and_creates_none() -> None:
    assert _decide(_single(), meeting_series_id=None) is False


def test_an_already_bound_meeting_is_refused() -> None:
    _decision_refused(MeetingErrorField.MEETING_ALREADY_PROVIDER_BOUND, meeting_is_bound=True)


def test_a_key_bound_to_another_meeting_is_refused() -> None:
    _decision_refused(
        MeetingErrorField.PROVIDER_KEY_BOUND_TO_ANOTHER_MEETING,
        key_bound_meeting_id=OTHER_MEETING,
    )


def test_single_and_occurrence_never_mix_for_one_uid() -> None:
    _decision_refused(MeetingErrorField.PROVIDER_BINDING_KIND_CONFLICT, other_kind_bound=True)
    _decision_refused(
        MeetingErrorField.PROVIDER_BINDING_KIND_CONFLICT, _single(), other_kind_bound=True
    )


def test_an_occurrence_of_a_standalone_meeting_is_refused() -> None:
    _decision_refused(MeetingErrorField.PROVIDER_BINDING_REQUIRES_SERIES, meeting_series_id=None)


def test_a_provider_series_bound_to_another_series_is_refused() -> None:
    _decision_refused(
        MeetingErrorField.PROVIDER_SERIES_BINDING_CONFLICT,
        uid_series=BoundSeries(OTHER_SERIES, CALENDAR, UID),
    )


def test_a_series_bound_to_a_different_uid_is_refused() -> None:
    _decision_refused(
        MeetingErrorField.PROVIDER_SERIES_BINDING_CONFLICT,
        meeting_series_binding=BoundSeries(SERIES, CALENDAR, "uid-other-series"),
    )
    _decision_refused(
        MeetingErrorField.PROVIDER_SERIES_BINDING_CONFLICT,
        meeting_series_binding=BoundSeries(SERIES, "cal-other", UID),
    )


def test_the_refusal_order_is_fixed() -> None:
    everything: dict[str, Any] = {
        "meeting_series_id": None,
        "meeting_is_bound": True,
        "key_bound_meeting_id": OTHER_MEETING,
        "other_kind_bound": True,
    }
    order = (
        ("meeting_is_bound", MeetingErrorField.MEETING_ALREADY_PROVIDER_BOUND),
        ("key_bound_meeting_id", MeetingErrorField.PROVIDER_KEY_BOUND_TO_ANOTHER_MEETING),
        ("other_kind_bound", MeetingErrorField.PROVIDER_BINDING_KIND_CONFLICT),
        ("meeting_series_id", MeetingErrorField.PROVIDER_BINDING_REQUIRES_SERIES),
    )
    state = dict(everything)
    for name, token in order:
        _decision_refused(token, **state)
        state[name] = {"meeting_series_id": SERIES, "key_bound_meeting_id": None}.get(name, False)


# ---- the application over the fake unit of work -----------------------------------


def _meeting(uow: FakeUnitOfWork, key: str, *, series_title: str | None = "Series") -> str:
    created = APP.create_meeting(
        uow,
        PRINCIPAL,
        MeetingCreateRequest(
            title="Synthetic", start_at=NOW, timezone_name="UTC", series_title=series_title
        ),
        key,
        NOW,
    )
    return created.meeting.meeting_id


def _apply(
    uow: FakeUnitOfWork, request: MeetingProviderBindRequest, version: int, key: str
) -> MeetingProviderBindResult:
    return APP.bind_meeting_provider(uow, PRINCIPAL, request, version, key, NOW)


def test_bind_then_unbind_over_the_fake() -> None:
    uow = FakeUnitOfWork(World())
    meeting_id = _meeting(uow, "create-0001")
    bound = _apply(uow, _bind(meeting_id=meeting_id), 1, "bind-0001")
    assert (bound.version, bound.replayed, bound.action) == (2, False, ProviderBindAction.BIND)
    assert bound.binding is not None
    assert bound.binding.provider_state is ProviderBindingState.ACTIVE
    assert bound.binding.meeting_series_id is not None
    assert bound.receipt.after_version == 2
    replay = _apply(uow, _bind(meeting_id=meeting_id), 1, "bind-0001")
    assert (replay.replayed, replay.version, replay.receipt) == (True, 2, bound.receipt)
    unbound = _apply(
        uow,
        MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=meeting_id),
        2,
        "unbind-0001",
    )
    assert (unbound.version, unbound.binding) == (3, None)


def test_the_gates_over_the_fake() -> None:
    uow = FakeUnitOfWork(World())
    meeting_id = _meeting(uow, "create-0002")
    with pytest.raises(MeetingStaleVersionError):
        _apply(uow, _bind(meeting_id=meeting_id), 2, "bind-stale")
    with pytest.raises(MeetingNotFoundError):
        _apply(uow, _bind(meeting_id="mtg_bindunitabsent01"), 1, "bind-absent")
    with pytest.raises(MeetingInvalidRequestError) as unbound:
        _apply(
            uow,
            MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=meeting_id),
            1,
            "unbind-unbound",
        )
    assert unbound.value.field is MeetingErrorField.MEETING_NOT_PROVIDER_BOUND
