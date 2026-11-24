"""The explicit `meetings.provider.bind` reconciliation, as pure decisions (WP2-W3).

Contract section 12.2 rule 4 (Manager ruling D10): an existing Meeting is bound
to a provider identity only by an explicit call naming **both** -- the Meeting
and the full provider key -- and never by title or time. The same capability
also unbinds (the D6 "unbind first" path), so a Meeting whose series the
provider owns can be released before its series is changed.

`MeetingProviderBindRequest` is the normalized request: `action` is `bind` or
`unbind` (the `context.feedback` precedent of one closed `action` field with
per-action field rules). A bind names the key: `calendar_ref`, `ical_uid`, and
either both `occurrence_original_start_utc` and `series_ical_uid` (an
occurrence) or neither (a single meeting), plus an optional provider event id
and its format; an unbind names the Meeting only.

`adopt_provider_series` (WP3b ruling D6, default `False`) is an occurrence
bind's consent to let the provider series decide the Meeting's series: when the
provider series is already bound to a MeetingSeries the Meeting is moved into
it, and when the provider series is unbound and the Meeting is standalone a
MeetingSeries is created for it, titled with the Meeting's title, and bound.
Without it both cases stay refusals, as before.

`bind_decision` is the closed refusal order over the state the application read
under the Meeting lock. Every refusal is a `MeetingErrorField` token naming the
rule, never a key value or the other Meeting a key is bound to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.meeting.model import (
    MeetingErrorField,
    MeetingInvalidRequestError,
    validate_aware_instant,
    validate_meeting_id,
)
from my_pa.domain.meeting_sync.model import (
    MAX_CALENDAR_REF_CHARACTERS,
    MAX_ICAL_UID_CHARACTERS,
    MAX_PROVIDER_EVENT_ID_CHARACTERS,
    OccurrenceKey,
    ProviderEventIdFormat,
)

__all__ = [
    "BindDecision",
    "BoundSeries",
    "MeetingProviderBindRequest",
    "ProviderBindAction",
    "bind_decision",
]


class ProviderBindAction(StrEnum):
    """What one `meetings.provider.bind` request does."""

    BIND = "bind"
    UNBIND = "unbind"


def _bounded_text(value: object, maximum: int, token: MeetingErrorField) -> str:
    """1..`maximum` characters, not all whitespace, stored exactly (the binding bounds)."""
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value.strip() == "":
        raise MeetingInvalidRequestError(token)
    return value


@dataclass(frozen=True, slots=True)
class MeetingProviderBindRequest:
    """A normalized `meetings.provider.bind` request (module docstring).

    Constructing one validates it; a refusal names the first offending field.
    An unbind that names any key field is refused on that field, so an unbind
    can never be mistaken for a bind of a different key.
    """

    action: ProviderBindAction
    meeting_id: str
    calendar_ref: str | None = None
    ical_uid: str | None = None
    occurrence_original_start_utc: datetime | None = None
    series_ical_uid: str | None = None
    provider_event_id: str | None = None
    provider_event_id_format: ProviderEventIdFormat | None = None
    adopt_provider_series: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action, ProviderBindAction):
            raise MeetingInvalidRequestError(MeetingErrorField.ACTION)
        validate_meeting_id(self.meeting_id)
        if not isinstance(self.adopt_provider_series, bool):
            raise MeetingInvalidRequestError(MeetingErrorField.ADOPT_PROVIDER_SERIES)
        if self.action is ProviderBindAction.UNBIND:
            if self.adopt_provider_series:
                raise MeetingInvalidRequestError(MeetingErrorField.ADOPT_PROVIDER_SERIES)
            for value, token in (
                (self.calendar_ref, MeetingErrorField.CALENDAR_REF),
                (self.ical_uid, MeetingErrorField.ICAL_UID),
                (
                    self.occurrence_original_start_utc,
                    MeetingErrorField.OCCURRENCE_ORIGINAL_START_UTC,
                ),
                (self.series_ical_uid, MeetingErrorField.SERIES_ICAL_UID),
                (self.provider_event_id, MeetingErrorField.PROVIDER_EVENT_ID),
                (self.provider_event_id_format, MeetingErrorField.PROVIDER_EVENT_ID_FORMAT),
            ):
                if value is not None:
                    raise MeetingInvalidRequestError(token)
            return
        _bounded_text(
            self.calendar_ref, MAX_CALENDAR_REF_CHARACTERS, MeetingErrorField.CALENDAR_REF
        )
        _bounded_text(self.ical_uid, MAX_ICAL_UID_CHARACTERS, MeetingErrorField.ICAL_UID)
        if self.occurrence_original_start_utc is not None:
            object.__setattr__(
                self,
                "occurrence_original_start_utc",
                validate_aware_instant(
                    self.occurrence_original_start_utc,
                    token=MeetingErrorField.OCCURRENCE_ORIGINAL_START_UTC,
                ),
            )
        if self.series_ical_uid is not None:
            _bounded_text(
                self.series_ical_uid, MAX_ICAL_UID_CHARACTERS, MeetingErrorField.SERIES_ICAL_UID
            )
        # An occurrence names both its series and its original start; a single
        # meeting names neither (the binding table's own CHECK).
        if self.occurrence_original_start_utc is None and self.series_ical_uid is not None:
            raise MeetingInvalidRequestError(MeetingErrorField.OCCURRENCE_ORIGINAL_START_UTC)
        if self.occurrence_original_start_utc is not None and self.series_ical_uid is None:
            raise MeetingInvalidRequestError(MeetingErrorField.SERIES_ICAL_UID)
        # Only an occurrence has a provider series to adopt (D6).
        if self.adopt_provider_series and self.occurrence_original_start_utc is None:
            raise MeetingInvalidRequestError(MeetingErrorField.ADOPT_PROVIDER_SERIES)
        if self.provider_event_id is not None:
            _bounded_text(
                self.provider_event_id,
                MAX_PROVIDER_EVENT_ID_CHARACTERS,
                MeetingErrorField.PROVIDER_EVENT_ID,
            )
        event_id_format = self.provider_event_id_format
        if event_id_format is not None and not isinstance(event_id_format, ProviderEventIdFormat):
            raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_EVENT_ID_FORMAT)
        # A stability claim needs the id it is about.
        if (
            self.provider_event_id is None
            and event_id_format is not None
            and event_id_format is not ProviderEventIdFormat.UNKNOWN
        ):
            raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_EVENT_ID_FORMAT)

    @property
    def key(self) -> OccurrenceKey:
        """The provider identity a bind names. Only a bind has one."""
        if self.calendar_ref is None or self.ical_uid is None:
            raise MeetingInvalidRequestError(MeetingErrorField.ACTION)
        return OccurrenceKey(self.calendar_ref, self.ical_uid, self.occurrence_original_start_utc)

    @property
    def event_id_format(self) -> ProviderEventIdFormat:
        """The stored format: `unknown` unless the request stated one."""
        return self.provider_event_id_format or ProviderEventIdFormat.UNKNOWN


@dataclass(frozen=True, slots=True)
class BoundSeries:
    """One existing series binding: which MeetingSeries, which provider series UID."""

    meeting_series_id: str
    calendar_ref: str
    series_ical_uid: str


@dataclass(frozen=True, slots=True)
class BindDecision:
    """An accepted bind: what must be written with it.

    * `create_series_binding` -- bind the provider series to the Meeting's
      (post-write) series;
    * `move_to_series_id` -- D6 adopt: move the Meeting into this MeetingSeries,
      which the provider series is already bound to;
    * `create_series` -- D6 adopt: create a MeetingSeries for the standalone
      Meeting (then `create_series_binding` is set too).
    """

    create_series_binding: bool
    move_to_series_id: str | None = None
    create_series: bool = False


def bind_decision(
    request: MeetingProviderBindRequest,
    *,
    meeting_id: str,
    meeting_series_id: str | None,
    meeting_is_bound: bool,
    key_bound_meeting_id: str | None,
    other_kind_bound: bool,
    uid_series: BoundSeries | None,
    meeting_series_binding: BoundSeries | None,
) -> BindDecision:
    """Accept or refuse one bind, in a fixed order (module docstring).

    * `meeting_series_id` -- the locked Meeting's current series, or `None`;
    * `meeting_is_bound` -- whether the Meeting already has a binding;
    * `key_bound_meeting_id` -- the Meeting the key is bound to, or `None`;
    * `other_kind_bound` -- the UID is bound as the other kind (D9);
    * `uid_series` -- the series binding of the key's series UID, or `None`;
    * `meeting_series_binding` -- the series binding of the Meeting's series.

    Never reads a title, a time or any other Meeting content: rule 4. With
    `request.adopt_provider_series` (D6) the two series refusals that the
    provider series can settle become a move or a series creation; a Meeting
    series already bound to a *different* provider series stays refused.
    """
    if meeting_is_bound:
        raise MeetingInvalidRequestError(MeetingErrorField.MEETING_ALREADY_PROVIDER_BOUND)
    if key_bound_meeting_id is not None and key_bound_meeting_id != meeting_id:
        raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_KEY_BOUND_TO_ANOTHER_MEETING)
    if other_kind_bound:
        raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_BINDING_KIND_CONFLICT)
    if request.occurrence_original_start_utc is None:
        return BindDecision(create_series_binding=False)
    if request.adopt_provider_series:
        if uid_series is not None and uid_series.meeting_series_id != meeting_series_id:
            # The provider series is another MeetingSeries': the Meeting moves into it.
            return BindDecision(
                create_series_binding=False, move_to_series_id=uid_series.meeting_series_id
            )
        if uid_series is None and meeting_series_id is None:
            # An unbound provider series and a standalone Meeting: a series is born.
            return BindDecision(create_series_binding=True, create_series=True)
    if meeting_series_id is None:
        raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_BINDING_REQUIRES_SERIES)
    if uid_series is not None and uid_series.meeting_series_id != meeting_series_id:
        # The provider series is already another MeetingSeries'.
        raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_SERIES_BINDING_CONFLICT)
    if meeting_series_binding is not None and (
        meeting_series_binding.calendar_ref != request.calendar_ref
        or meeting_series_binding.series_ical_uid != request.series_ical_uid
    ):
        # The Meeting's series is already bound to a different provider series.
        raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_SERIES_BINDING_CONFLICT)
    return BindDecision(create_series_binding=uid_series is None)
