"""Apply `meeting_sync_v1` events to Meetings, inside the caller's unit of work (WP2).

`MeetingProviderSync` is stateless, like `MeetingApplication`: every method takes
the unit of work its caller **already opened**, the server-derived
`principal_id`, the parsed event and the SHA-256 of the publication it came
from. It opens no transaction; any exception rolls back everything the event
wrote, Meeting and bindings together (Manager ruling D7).

**Resolution is `domain.meeting_sync.resolution`'s** (contract section 12.2):
this module reads the state the rules need -- the occurrence binding `FOR
UPDATE`, the series binding, whether the UID is bound as the other kind -- and
carries out the decision:

* a known key updates the bound Meeting through `MeetingApplication.update_meeting`
  and its CAS, with the version read under the Meeting row lock in this same
  transaction, naming only the provider-owned fields (ruling D2), then
  refreshes the binding's attributes;
* an unknown key creates the Meeting through `MeetingApplication.create_meeting`
  -- standalone, in the bound series, or with a new series titled by the event --
  and inserts the series binding (for a new series) and the occurrence binding;
* a cancelled unknown event and a UID bound as the other kind are skipped with
  a content-free diagnostic, and nothing is written.

**Writes are the system's** (ruling D12): every Meeting write records actor
`system` and the source token `system.meeting_provider.sync`
(`MEETING_PROVIDER_SYNC_NAME`; under `system.`, the internal-token precedent of
`system.entity_reenrichment.rebind`, so no reader can take it for a
`Capability` beside the real `meetings.provider.bind`). This is a direct
call: no `ApplicationService.invoke`, no grant check and no audit row (WP3
decides the audit routing).

**Idempotency.** Each applied record has one deterministic key
(`sync_idempotency_key`: the binding key, the publication SHA-256 and the record
ordinal), reserved in `meeting_write_requests` under the one internal namespace
`system.meeting_provider.sync` (WP2-W3), for a create and an update alike. So a
client's own `meetings.create`/`meetings.update` key can never collide with,
replay or suppress a sync write, and a record applied once -- as a create or as
an update -- is recognised as applied whichever path a re-application would
take. Re-applying a record already applied, or an identical event from any
publication, writes no Meeting change and bumps no version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.ports import (
    MeetingProviderBindingRecord,
    MeetingSeriesProviderBindingRecord,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.meetings import MeetingView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.meeting.model import MEETING_PROVIDER_SYNC_NAME, MeetingActor
from my_pa.domain.meeting_sync.model import MeetingSyncEvent
from my_pa.domain.meeting_sync.resolution import (
    BindingAttributes,
    KnownOccurrence,
    ProviderFields,
    ResolutionDiagnostic,
    ResolutionKind,
    provider_create,
    provider_update,
    refreshed_binding,
    resolve_event,
    sync_idempotency_key,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "MEETINGS_PROVIDER_SYNC_SOURCE",
    "MeetingProviderSync",
    "MeetingSyncOutcome",
    "SyncOutcomeKind",
]

#: The Record Event `source_capability` of every sync write (ruling D12) and the
#: `meeting_write_requests` namespace of its key. Not a `Capability` member: no
#: client can invoke it, and `Capability(...)` of it raises.
MEETINGS_PROVIDER_SYNC_SOURCE: Final = MEETING_PROVIDER_SYNC_NAME

_SHA256: Final = re.compile(r"[0-9a-f]{64}")


class SyncOutcomeKind(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    REPLAYED = "replayed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class MeetingSyncOutcome:
    """What applying one event did. Identifiers and codes only, never content."""

    ordinal: int
    kind: SyncOutcomeKind
    meeting_id: str | None = None
    binding_id: str | None = None
    diagnostic: ResolutionDiagnostic | None = None


def _provider_fields(view: MeetingView) -> ProviderFields:
    return ProviderFields(
        title=view.title,
        start_at=view.start_at,
        end_at=view.end_at,
        timezone_name=view.timezone_name,
        status=view.status,
        location_text=view.location_text,
        virtual_meeting_url=view.virtual_meeting_url,
    )


def _attributes(binding: MeetingProviderBindingRecord) -> BindingAttributes:
    return BindingAttributes(
        provider_event_id=binding.provider_event_id,
        provider_event_id_format=binding.provider_event_id_format,
        provider_state=binding.provider_state,
        last_seen_source_sha256=binding.last_seen_source_sha256,
        last_seen_record_ordinal=binding.last_seen_record_ordinal,
        last_seen_at=binding.last_seen_at,
    )


@dataclass(frozen=True, slots=True)
class MeetingProviderSync:
    """Resolution rules 1-6 over the caller's unit of work."""

    meetings: MeetingApplication = field(default_factory=MeetingApplication)

    def apply_event(
        self,
        uow: UnitOfWork,
        principal_id: str,
        event: MeetingSyncEvent,
        *,
        source_sha256: str,
        now: datetime,
    ) -> MeetingSyncOutcome:
        """Resolve and apply one event (module docstring)."""
        if _SHA256.fullmatch(source_sha256) is None:
            raise ValueError("source_sha256 must be lowercase SHA-256 hex")
        at = ensure_utc(now)
        key = event.key
        repository = uow.meetings
        idempotency_key = sync_idempotency_key(
            key, source_sha256=source_sha256, record_ordinal=event.ordinal
        )

        bound = repository.lock_provider_binding(
            principal_id, key.calendar_ref, key.ical_uid, key.original_start_utc
        )
        series_binding = (
            None
            if event.series_ical_uid is None
            else repository.read_series_provider_binding(
                principal_id, key.calendar_ref, event.series_ical_uid
            )
        )
        other_kind_bound = bound is None and repository.provider_uid_bound_as_other_kind(
            principal_id, key.calendar_ref, key.ical_uid, occurrence=key.is_occurrence
        )
        resolution = resolve_event(
            event,
            bound=None
            if bound is None
            else KnownOccurrence(binding_id=bound.binding_id, meeting_id=bound.meeting_id),
            series_id=None if series_binding is None else series_binding.meeting_series_id,
            other_kind_bound=other_kind_bound,
        )

        if resolution.kind is ResolutionKind.SKIP:
            return MeetingSyncOutcome(
                event.ordinal, SyncOutcomeKind.SKIPPED, diagnostic=resolution.diagnostic
            )
        if bound is not None:
            return self._update(uow, principal_id, event, bound, source_sha256, idempotency_key, at)
        return self._create(
            uow,
            principal_id,
            event,
            resolution.kind,
            resolution.meeting_series_id,
            source_sha256,
            idempotency_key,
            at,
        )

    def _update(
        self,
        uow: UnitOfWork,
        principal_id: str,
        event: MeetingSyncEvent,
        bound: MeetingProviderBindingRecord,
        source_sha256: str,
        idempotency_key: str,
        at: datetime,
    ) -> MeetingSyncOutcome:
        """Rules 1, 5, 6: the bound Meeting's provider-owned fields, then the binding."""
        repository = uow.meetings
        refreshed = refreshed_binding(
            _attributes(bound), event, source_sha256=source_sha256, seen_at=at
        )
        replayed = MeetingSyncOutcome(
            event.ordinal,
            SyncOutcomeKind.REPLAYED,
            meeting_id=bound.meeting_id,
            binding_id=bound.binding_id,
        )
        if refreshed is None:
            # The binding already records this exact observation.
            return replayed
        if (
            repository.read_write_request(principal_id, MEETING_PROVIDER_SYNC_NAME, idempotency_key)
            is not None
        ):
            # This record was applied before and a later one has been seen
            # since: re-applying it would rewind the Meeting.
            return replayed

        current = repository.lock_meeting_for_update(principal_id, bound.meeting_id)
        if current is None:
            # The composite foreign key keeps the bound Meeting in this partition.
            raise RepositoryFailureError
        request = provider_update(current.meeting_id, _provider_fields(current), event)
        if request is not None:
            self.meetings.update_meeting(
                uow,
                principal_id,
                request,
                current.version,
                idempotency_key,
                at,
                source_capability=MEETINGS_PROVIDER_SYNC_SOURCE,
                actor=MeetingActor.SYSTEM,
                request_capability=MEETING_PROVIDER_SYNC_NAME,
            )
        attributes, material = refreshed
        repository.update_provider_binding(
            principal_id,
            replace(
                bound,
                provider_event_id=attributes.provider_event_id,
                provider_event_id_format=attributes.provider_event_id_format,
                provider_state=attributes.provider_state,
                last_seen_source_sha256=attributes.last_seen_source_sha256,
                last_seen_record_ordinal=attributes.last_seen_record_ordinal,
                last_seen_at=attributes.last_seen_at,
                version=bound.version + 1 if material else bound.version,
                updated_at=at,
            ),
        )
        kind = (
            SyncOutcomeKind.UPDATED
            if request is not None or material
            else SyncOutcomeKind.UNCHANGED
        )
        return MeetingSyncOutcome(
            event.ordinal, kind, meeting_id=bound.meeting_id, binding_id=bound.binding_id
        )

    def _create(
        self,
        uow: UnitOfWork,
        principal_id: str,
        event: MeetingSyncEvent,
        kind: ResolutionKind,
        meeting_series_id: str | None,
        source_sha256: str,
        idempotency_key: str,
        at: datetime,
    ) -> MeetingSyncOutcome:
        """Rules 2, 3 and the standalone case: the Meeting and its bindings (D7)."""
        repository = uow.meetings
        prior = repository.read_write_request(
            principal_id, MEETING_PROVIDER_SYNC_NAME, idempotency_key
        )
        if prior is not None:
            # This record was applied before -- as a create or as an update --
            # and its Meeting's binding has since been removed (the unbind):
            # never re-create or rebind from it implicitly.
            return MeetingSyncOutcome(
                event.ordinal, SyncOutcomeKind.REPLAYED, meeting_id=prior.meeting_id
            )
        new_series = kind is ResolutionKind.CREATE_SERIES
        result = self.meetings.create_meeting(
            uow,
            principal_id,
            provider_create(event, meeting_series_id=meeting_series_id, new_series=new_series),
            idempotency_key,
            at,
            source_capability=MEETINGS_PROVIDER_SYNC_SOURCE,
            actor=MeetingActor.SYSTEM,
            request_capability=MEETING_PROVIDER_SYNC_NAME,
        )
        if result.replayed:
            # This record created a Meeting before whose binding has since been
            # removed (the W3 unbind): never rebind it implicitly.
            return MeetingSyncOutcome(
                event.ordinal, SyncOutcomeKind.REPLAYED, meeting_id=result.meeting.meeting_id
            )
        meeting = result.meeting
        if new_series:
            if meeting.meeting_series_id is None or event.series_ical_uid is None:
                raise RepositoryFailureError
            repository.insert_series_provider_binding(
                principal_id,
                MeetingSeriesProviderBindingRecord(
                    series_binding_id=issue_identifier(IdKind.MEETING_SERIES_PROVIDER_BINDING),
                    meeting_series_id=meeting.meeting_series_id,
                    calendar_ref=event.calendar_ref,
                    series_ical_uid=event.series_ical_uid,
                    created_at=at,
                ),
            )
        binding = MeetingProviderBindingRecord(
            binding_id=issue_identifier(IdKind.MEETING_PROVIDER_BINDING),
            meeting_id=meeting.meeting_id,
            calendar_ref=event.calendar_ref,
            ical_uid=event.ical_uid,
            occurrence_original_start_utc=event.occurrence_original_start_utc,
            series_ical_uid=event.series_ical_uid,
            provider_event_id=event.provider_event_id,
            provider_event_id_format=event.provider_event_id_format,
            provider_state=event.provider_state,
            last_seen_source_sha256=source_sha256,
            last_seen_record_ordinal=event.ordinal,
            last_seen_at=at,
            version=1,
            created_at=at,
            updated_at=at,
        )
        repository.insert_provider_binding(principal_id, binding)
        return MeetingSyncOutcome(
            event.ordinal,
            SyncOutcomeKind.CREATED,
            meeting_id=meeting.meeting_id,
            binding_id=binding.binding_id,
        )
