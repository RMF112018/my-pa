"""The Meeting records use cases, on the general unit of work (WP-MTG-03).

`MeetingApplication` is stateless. Every method takes the unit of work that
`ApplicationService.invoke` has **already opened**, the authenticated
`principal_id` as a plain parameter, the normalized WP-MTG-01 request value and,
for a write, the idempotency key and the authorization time. It opens no
transaction, nests none and owns no factory for one (readiness F015): each
reservation, parent lock, child write, receipt, note version and request
completion below runs in the caller's one transaction, so any exception rolls
all of them back together (AC-031).

**The Principal is a parameter, never read back.** Nothing here reads a
`principal_id` off a record, a view or a request, and nothing names a table:
every row is reached through `uow.meetings`, which applies the partition on
every statement (plan D-23/D-24).

**Errors are the closed domain Meeting family only** (plan D-20). An absent or
foreign reference is `MeetingNotFoundError`, a refused value is
`MeetingInvalidRequestError`, a stale `expected_version` is
`MeetingStaleVersionError`, and a reused key with a different digest is
`MeetingIdempotencyConflictError` (raised by the repository's reservation). Each
carries a field token and nothing else. WP-MTG-04 translates them to the fixed
`ErrorCode`/`RetryGuidance`/`SafeDetail` map. A state that the schema and this
module together make impossible (a completed request whose receipt is missing,
say) raises the port's existing `RepositoryFailureError`, which is what the
repository itself raises for the same class of fault; it is an internal error,
never a refusal a caller could correct.

**The order of every write is package section 35.10's.** Create: digest,
reserve, nonlocking Project and ManagedDocument reads, Person Entities `FOR
SHARE` in ascending id, the existing series read without a lock or a new series
and its receipt, the Meeting, its attendees in digest order, its attachments,
its receipt, its first note version, then completion. Update: digest, reserve,
Meeting `FOR UPDATE`, version gate, nonlocking reference reads, Entities `FOR
SHARE`, the exact no-op/material delta, the core row and child retire/insert,
one receipt, the note version, completion. Series update: digest, reserve,
series `FOR UPDATE`, version gate, the title, one receipt, completion. No child
row is locked, and no Project or ManagedDocument is locked at all.

**Replay answers with the original receipt and the current state** (section
35.7): the receipt the request row names, beside a fresh read of the aggregate,
and `replayed=True`. No response body is ever stored.

**A same-field set and clear: the clear wins.** `MeetingUpdateRequest` accepts
`end_at`, `location_text`, `virtual_meeting_url` or `description` together with
the same field in `clear_fields` (only the `project_id` pair is refused, which
is all section 19.6/34.17/35.8 say). Sections 34 and 35 are silent on the
other four pairs, so the rule rests on the post-WP03 operator ruling R3-02,
which accepts clear-wins: an explicit clear always leaves the field NULL, and
the supplied value is still part of the request digest (WP-MTG-01 review
finding F-01, now resolved by that ruling).

The history-bearing results carry their receipt as `receipt`, and the methods
are named `*_meeting(s)`, so no Meeting symbol shares a name with the
relationship-memory port methods the memory-row guard sweeps for (plan D-29).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from my_pa.contracts.ports import (
    MeetingAttachmentRecord,
    MeetingAttendeeRecord,
    MeetingListPage,
    MeetingNoteRecord,
    MeetingRecord,
    MeetingRepository,
    MeetingWriteRequestRecord,
    RecordEventStager,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.meetings import (
    MeetingAttendeeView,
    MeetingHistoryView,
    MeetingSeriesHistoryView,
    MeetingSeriesView,
    MeetingView,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.meeting.model import (
    MAX_MEETING_ATTACHMENTS,
    MAX_MEETING_IDEMPOTENCY_KEY_CHARACTERS,
    MEETINGS_CREATE_NAME,
    MEETINGS_SERIES_UPDATE_NAME,
    MEETINGS_UPDATE_NAME,
    MIN_MEETING_IDEMPOTENCY_KEY_CHARACTERS,
    MeetingActor,
    MeetingClearField,
    MeetingCreateRequest,
    MeetingErrorField,
    MeetingHistoryAction,
    MeetingInvalidRequestError,
    MeetingListRequest,
    MeetingNotesMode,
    MeetingNotFoundError,
    MeetingOutcome,
    MeetingSearchRequest,
    MeetingSeriesSelector,
    MeetingSeriesUpdateRequest,
    MeetingStaleVersionError,
    MeetingStatus,
    MeetingUpdateRequest,
    NormalizedAttendee,
    attendee_digest_sort_key,
    compose_appended_note,
    note_content_sha256,
    validate_meeting_notes_markdown,
    validate_meeting_time_range,
)
from my_pa.domain.record_events import (
    MEETING_ACTOR_CLASSES,
    NON_MEMORY_CLASSIFICATION,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
    field_set,
)
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "MeetingApplication",
    "MeetingSeriesWriteResult",
    "MeetingWriteResult",
    "meeting_request_digest",
]

#: The receipt actor every v1 write records (readiness F020).
_ACTOR: Final = MeetingActor.PRINCIPAL


# ------------------------------------------------------------------- results


@dataclass(frozen=True, slots=True)
class MeetingWriteResult:
    """What `meetings.create` and `meetings.update` answer.

    `meeting` is the current Meeting view, read after the write (or, on a
    replay, now). `receipt` is the immutable Meeting receipt of the original
    write. `series_receipt` is present only for a create that also created its
    series: the one request identity names both receipts (section 34.14).
    """

    meeting: MeetingView
    receipt: MeetingHistoryView
    replayed: bool
    series_receipt: MeetingSeriesHistoryView | None = None


@dataclass(frozen=True, slots=True)
class MeetingSeriesWriteResult:
    """What `meetings.series.update` answers: the current series and its receipt."""

    series: MeetingSeriesView
    receipt: MeetingSeriesHistoryView
    replayed: bool


# -------------------------------------------------------------------- digest


type _DigestValue = str | int | bool | list[_DigestValue] | dict[str, _DigestValue] | None


def _instant(value: datetime) -> str:
    """Canonical UTC RFC 3339, with every stored microsecond.

    Not `format_rfc3339`, which truncates to milliseconds: two schedules one
    microsecond apart are different stored states and must hash differently.
    """
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sorted_strings(values: Iterable[str]) -> list[_DigestValue]:
    """A lexicographically sorted identifier or token collection (section 35.9)."""
    ordered: list[_DigestValue] = []
    ordered.extend(sorted(values))
    return ordered


def _attendee_document(attendee: NormalizedAttendee) -> dict[str, _DigestValue]:
    return {
        "display_name": attendee.display_name,
        "email_normalized": attendee.email_normalized,
        "entity_id": attendee.entity_id,
        "is_organizer": attendee.is_organizer,
        "response_status": attendee.response_status.value,
    }


def _attendees_document(attendees: tuple[NormalizedAttendee, ...]) -> list[_DigestValue]:
    """The attendee set in `attendee_digest_sort_key` order (section 35.9)."""
    return [
        _attendee_document(attendee) for attendee in sorted(attendees, key=attendee_digest_sort_key)
    ]


def _present(document: dict[str, _DigestValue], name: str, value: _DigestValue) -> None:
    """Record `value` under `name` only when supplied: omission is not null."""
    if value is not None:
        document[name] = value


def _create_document(request: MeetingCreateRequest) -> dict[str, _DigestValue]:
    document: dict[str, _DigestValue] = {
        "title": request.title,
        "start_at": _instant(request.start_at),
        "timezone_name": request.timezone_name,
        "series_selector": request.series_selector.value,
        "attendees": _attendees_document(request.attendees),
        "attachment_document_ids": _sorted_strings(request.attachment_document_ids),
    }
    _present(document, "end_at", None if request.end_at is None else _instant(request.end_at))
    _present(document, "meeting_series_id", request.meeting_series_id)
    _present(document, "series_title", request.series_title)
    _present(document, "location_text", request.location_text)
    _present(document, "virtual_meeting_url", request.virtual_meeting_url)
    _present(document, "description", request.description)
    _present(document, "project_id", request.project_id)
    _present(document, "notes_markdown", request.notes_markdown)
    return document


def _update_document(
    request: MeetingUpdateRequest, expected_version: int | None
) -> dict[str, _DigestValue]:
    document: dict[str, _DigestValue] = {
        "meeting_id": request.meeting_id,
        "expected_version": expected_version,
        "clear_fields": _sorted_strings(member.value for member in request.clear_fields),
        "attachment_add_document_ids": _sorted_strings(request.attachment_add_document_ids),
        "attachment_remove_ids": _sorted_strings(request.attachment_remove_ids),
    }
    _present(document, "title", request.title)
    _present(document, "start_at", None if request.start_at is None else _instant(request.start_at))
    _present(document, "end_at", None if request.end_at is None else _instant(request.end_at))
    _present(document, "timezone_name", request.timezone_name)
    _present(document, "status", None if request.status is None else request.status.value)
    _present(document, "location_text", request.location_text)
    _present(document, "virtual_meeting_url", request.virtual_meeting_url)
    _present(document, "description", request.description)
    _present(document, "project_id", request.project_id)
    if request.attendees_replace is not None:
        # Present-and-empty replaces the active set with nothing; absent leaves
        # it alone. The two must hash differently (section 35.9).
        document["attendees_replace"] = _attendees_document(request.attendees_replace)
    _present(
        document, "notes_mode", None if request.notes_mode is None else request.notes_mode.value
    )
    _present(document, "notes_markdown", request.notes_markdown)
    return document


def _series_update_document(
    request: MeetingSeriesUpdateRequest, expected_version: int | None
) -> dict[str, _DigestValue]:
    return {
        "meeting_series_id": request.meeting_series_id,
        "expected_version": expected_version,
        "title": request.title,
    }


def meeting_request_digest(
    capability_name: str,
    principal_id: str,
    normalized_request: MeetingCreateRequest | MeetingUpdateRequest | MeetingSeriesUpdateRequest,
    *,
    expected_version: int | None = None,
) -> str:
    """The application request digest of one Meeting write (sections 34.14, 35.9).

    Computed over the capability, the authenticated Principal and the normalized
    domain request -- plus `expected_version` for the two version-bearing
    writes -- serialized as UTF-8 canonical JSON (sorted keys, `(",", ":")`
    separators) and hashed with SHA-256, lowercase hex.

    Excluded by construction, because none of them is an input here: the
    idempotency key, request/correlation/audit identifiers, the server clock and
    every server-minted identifier. Timestamps are canonical UTC RFC 3339; the
    virtual URL is the exact accepted string; `clear_fields` and attachment
    identifier collections are sorted; attendees are ordered by
    `attendee_digest_sort_key`; an omitted field is absent from the document,
    so it is distinct from an explicit empty replacement, and a clear appears
    only in `clear_fields`, never as a null.
    """
    request: dict[str, _DigestValue]
    if isinstance(normalized_request, MeetingCreateRequest):
        request = _create_document(normalized_request)
    elif isinstance(normalized_request, MeetingUpdateRequest):
        request = _update_document(normalized_request, expected_version)
    else:
        request = _series_update_document(normalized_request, expected_version)
    document: dict[str, _DigestValue] = {
        "capability": capability_name,
        "principal_id": principal_id,
        "request": request,
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ helpers


def _checked_idempotency_key(value: object) -> str:
    """A key of 1..128 characters, no character class (section 35.6, plan D-16)."""
    if not isinstance(value, str) or not (
        MIN_MEETING_IDEMPOTENCY_KEY_CHARACTERS
        <= len(value)
        <= MAX_MEETING_IDEMPOTENCY_KEY_CHARACTERS
    ):
        raise MeetingInvalidRequestError(MeetingErrorField.IDEMPOTENCY_KEY)
    return value


def _checked_expected_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MeetingInvalidRequestError(MeetingErrorField.EXPECTED_VERSION)
    return value


def _snapshot(attendee: MeetingAttendeeView) -> NormalizedAttendee:
    """An active attendee row in the normalized form a replacement is compared in."""
    return NormalizedAttendee(
        display_name=attendee.display_name,
        email_normalized=attendee.email,
        entity_id=attendee.entity_id,
        is_organizer=attendee.is_organizer,
        response_status=attendee.response_status,
    )


def _in_digest_order(attendees: tuple[NormalizedAttendee, ...]) -> tuple[NormalizedAttendee, ...]:
    return tuple(sorted(attendees, key=attendee_digest_sort_key))


def _require_project(meetings: MeetingRepository, principal_id: str, project_id: str) -> None:
    """Any-state same-Principal Project; absent and foreign are one answer."""
    if not meetings.project_is_owned(principal_id, project_id):
        raise MeetingNotFoundError(MeetingErrorField.PROJECT_ID)


def _require_documents(
    meetings: MeetingRepository, principal_id: str, document_ids: tuple[str, ...]
) -> None:
    """Every named ManagedDocument is this Principal's, ACTIVE or ARCHIVED.

    `DocumentState` has exactly those two members, so any owned document is an
    eligible attachment target; an absent or foreign one has no entry.
    """
    if not document_ids:
        return
    owned = meetings.owned_managed_documents(principal_id, document_ids)
    if any(document_id not in owned for document_id in document_ids):
        raise MeetingNotFoundError(MeetingErrorField.DOCUMENT_ID)


def _require_active_people(
    meetings: MeetingRepository, principal_id: str, attendees: tuple[NormalizedAttendee, ...]
) -> None:
    """Share-lock the named Person Entities in ascending id and validate them.

    Absent or foreign: not found. Present but not a Person, or not ACTIVE
    (inactive, historical, merged redirect, archived): invalid, and a merge
    redirect is never followed (section 35.6).
    """
    wanted = sorted({attendee.entity_id for attendee in attendees if attendee.entity_id})
    if not wanted:
        return
    locked = meetings.share_lock_person_entities(principal_id, wanted)
    found = {state.entity_id: state for state in locked}
    if any(entity_id not in found for entity_id in wanted):
        raise MeetingNotFoundError(MeetingErrorField.ENTITY_ID)
    for entity_id in wanted:
        state = found[entity_id]
        if (
            state.entity_type != EntityType.PERSON.value
            or state.status != EntityStatus.ACTIVE.value
        ):
            raise MeetingInvalidRequestError(MeetingErrorField.ENTITY_ID)


def _attendee_records(
    attendees: tuple[NormalizedAttendee, ...],
) -> tuple[MeetingAttendeeRecord, ...]:
    """Minted attendee rows, in deterministic normalized (digest) order."""
    return tuple(
        MeetingAttendeeRecord(
            attendee_id=issue_identifier(IdKind.MEETING_ATTENDEE), attendee=attendee
        )
        for attendee in _in_digest_order(attendees)
    )


def _attachment_records(document_ids: tuple[str, ...]) -> tuple[MeetingAttachmentRecord, ...]:
    return tuple(
        MeetingAttachmentRecord(
            attachment_id=issue_identifier(IdKind.MEETING_ATTACHMENT), document_id=document_id
        )
        for document_id in sorted(document_ids)
    )


def _current_meeting(
    meetings: MeetingRepository, principal_id: str, meeting_id: str
) -> MeetingView:
    """The Meeting a completed write names. Its absence is an internal fault."""
    view = meetings.read_meeting(principal_id, meeting_id)
    if view is None:
        raise RepositoryFailureError
    return view


def _create_completion_ids(
    selector: MeetingSeriesSelector,
    meeting: MeetingView,
    series_receipt: MeetingSeriesHistoryView | None,
) -> tuple[str | None, str | None]:
    """`(meeting_series_id, meeting_series_history_id)` a completed create stores.

    Package section 35.7's application rule, which the schema's nullable
    composite keys cannot enforce alone (WP-MTG-02 review F-05): a create that
    made a new series stores both its id and its create receipt, a standalone
    create stores neither, and an existing-series occurrence stores the series
    id and no series receipt. The series id is the Meeting's own.
    """
    series_id = meeting.meeting_series_id
    if selector is MeetingSeriesSelector.NEW_SERIES:
        if (
            series_id is None
            or series_receipt is None
            or series_receipt.meeting_series_id != series_id
        ):
            raise RepositoryFailureError
        return series_id, series_receipt.series_history_id
    if selector is MeetingSeriesSelector.EXISTING_SERIES:
        if series_id is None or series_receipt is not None:
            raise RepositoryFailureError
        return series_id, None
    if series_id is not None or series_receipt is not None:
        raise RepositoryFailureError
    return None, None


# ------------------------------------------------- WP-RE-05: Record Events
#
# Rows MT1-MT4 of the emitter matrix. Staged on the caller's generic unit of
# work (U1) only on an APPLIED, non-replay branch, after the request is
# completed; U1 flushes the buffer in `__exit__`. Names, versions and ids only:
# `changed_fields` names fields, never a value, a note body or an attendee.

#: The scalar fields every Meeting create materializes.
_MEETING_CREATED_FIELDS: Final = ("start_at", "status", "timezone_name", "title")
#: The one field a MeetingSeries create or retitle writes.
_SERIES_TITLE_FIELDS: Final = ("title",)


def _stage_meeting_event(
    stager: RecordEventStager,
    *,
    principal_id: str,
    record_family: RecordEventFamily,
    record_id: str,
    event_kind: RecordEventKind,
    record_version: int,
    changed_fields: tuple[str, ...],
    source_capability: str,
    correlation_id: str | None,
    source_receipt_id: str,
    occurred_at: datetime,
    causation_event_id: str | None = None,
) -> RecordEventDraft:
    """Build one Meeting-plane draft, stage it, and return it (for causation).

    `principal_id` is the server-resolved caller the application was handed,
    never a value read off a record.
    """
    draft = RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=record_family,
        record_id=record_id,
        event_kind=event_kind,
        record_version=record_version,
        changed_fields=changed_fields,
        source_capability=source_capability,
        actor_class=MEETING_ACTOR_CLASSES[_ACTOR],
        classification=NON_MEMORY_CLASSIFICATION,
        occurred_at=occurred_at,
        source_receipt_id=source_receipt_id,
        correlation_id=correlation_id,
        causation_event_id=causation_event_id,
    )
    stager.stage(draft)
    return draft


def _meeting_created_fields(request: MeetingCreateRequest) -> tuple[str, ...]:
    """MT2: the static scalar names plus each optional part the create holds."""
    optional: dict[str, bool] = {
        "end_at": request.end_at is not None,
        "location_text": request.location_text is not None,
        "virtual_meeting_url": request.virtual_meeting_url is not None,
        "description": request.description is not None,
        "project_id": request.project_id is not None,
        "meeting_series_id": (
            request.meeting_series_id is not None or request.series_title is not None
        ),
        "attendees": bool(request.attendees),
        "attachments": bool(request.attachment_document_ids),
        "notes": request.notes_markdown is not None,
    }
    return field_set(*_MEETING_CREATED_FIELDS, *(name for name, held in optional.items() if held))


# --------------------------------------------------------------- the service


@dataclass(frozen=True, slots=True)
class MeetingApplication:
    """The six Meeting use cases, over the unit of work the caller already opened.

    Stateless: no constructor dependencies, no clock (`now` is an argument),
    and no transaction of its own.
    """

    # --- meetings.create --------------------------------------------------

    def create_meeting(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: MeetingCreateRequest,
        idempotency_key: str,
        now: datetime,
        *,
        source_capability: str = Capability.MEETINGS_CREATE.value,
        correlation_id: str | None = None,
    ) -> MeetingWriteResult:
        """Create a standalone Meeting, a new series and its first occurrence, or
        an occurrence of an existing series, as one request identity (AC-022).

        Stages the series `created` event first when this call made the series,
        then the Meeting `created` event, caused by it (WP-RE-05 MT1/MT2).
        """
        key = _checked_idempotency_key(idempotency_key)
        at = ensure_utc(now)
        digest = meeting_request_digest(MEETINGS_CREATE_NAME, principal_id, request)
        meetings = uow.meetings

        prior = meetings.reserve_write_request(
            principal_id, MEETINGS_CREATE_NAME, key, digest, created_at=at
        )
        if prior is not None:
            return self._replayed_meeting(meetings, principal_id, prior)

        if request.project_id is not None:
            _require_project(meetings, principal_id, request.project_id)
        _require_documents(meetings, principal_id, request.attachment_document_ids)
        _require_active_people(meetings, principal_id, request.attendees)

        series_id: str | None = None
        series_receipt: MeetingSeriesHistoryView | None = None
        # The selector is derived from exactly these two fields (WP-MTG-01), and
        # the request refuses both at once, so branching on them is the selector.
        if request.meeting_series_id is not None:
            # Read-only for an occurrence create: no lock, no version change.
            if meetings.read_owned_series(principal_id, request.meeting_series_id) is None:
                raise MeetingNotFoundError(MeetingErrorField.MEETING_SERIES_ID)
            series_id = request.meeting_series_id
        elif request.series_title is not None:
            series = MeetingSeriesView(
                meeting_series_id=issue_identifier(IdKind.MEETING_SERIES),
                title=request.series_title,
                version=1,
                created_at=at,
                updated_at=at,
            )
            series_receipt = MeetingSeriesHistoryView(
                series_history_id=issue_identifier(IdKind.MEETING_SERIES_HISTORY),
                meeting_series_id=series.meeting_series_id,
                action=MeetingHistoryAction.CREATE,
                actor=_ACTOR,
                outcome=MeetingOutcome.APPLIED,
                before_version=0,
                after_version=1,
                occurred_at=at,
                recorded_at=at,
            )
            meetings.insert_series(principal_id, series)
            meetings.insert_series_history(
                principal_id, series_receipt, idempotency_key=key, request_digest=digest
            )
            series_id = series.meeting_series_id

        meeting_id = issue_identifier(IdKind.MEETING)
        meetings.insert_meeting(
            principal_id,
            MeetingRecord(
                meeting_id=meeting_id,
                meeting_series_id=series_id,
                title=request.title,
                start_at=request.start_at,
                end_at=request.end_at,
                timezone_name=request.timezone_name,
                status=MeetingStatus.SCHEDULED,
                cancelled_at=None,
                location_text=request.location_text,
                virtual_meeting_url=request.virtual_meeting_url,
                description=request.description,
                project_id=request.project_id,
                version=1,
                created_at=at,
                updated_at=at,
            ),
        )
        meetings.insert_attendees(
            principal_id, meeting_id, _attendee_records(request.attendees), added_at=at
        )
        meetings.insert_attachments(
            principal_id,
            meeting_id,
            _attachment_records(request.attachment_document_ids),
            added_at=at,
        )
        receipt = MeetingHistoryView(
            history_id=issue_identifier(IdKind.MEETING_HISTORY),
            meeting_id=meeting_id,
            action=MeetingHistoryAction.CREATE,
            actor=_ACTOR,
            outcome=MeetingOutcome.APPLIED,
            before_version=0,
            after_version=1,
            occurred_at=at,
            recorded_at=at,
        )
        meetings.insert_meeting_history(
            principal_id,
            receipt,
            meeting_series_id=series_id,
            idempotency_key=key,
            request_digest=digest,
        )
        if request.notes_markdown is not None:
            body = validate_meeting_notes_markdown(request.notes_markdown)
            meetings.insert_note_version(
                principal_id,
                MeetingNoteRecord(
                    note_version_id=issue_identifier(IdKind.MEETING_NOTE_VERSION),
                    meeting_id=meeting_id,
                    version_number=1,
                    supersedes_note_version_id=None,
                    content_markdown=body,
                    content_sha256=note_content_sha256(body),
                    meeting_history_id=receipt.history_id,
                    recorded_at=at,
                ),
            )

        view = _current_meeting(meetings, principal_id, meeting_id)
        completed_series_id, completed_series_receipt_id = _create_completion_ids(
            request.series_selector, view, series_receipt
        )
        meetings.complete_write_request(
            principal_id,
            MEETINGS_CREATE_NAME,
            key,
            request_digest=digest,
            meeting_id=meeting_id,
            meeting_series_id=completed_series_id,
            meeting_history_id=receipt.history_id,
            meeting_series_history_id=completed_series_receipt_id,
            result_version=view.version,
            completed_at=at,
        )
        series_event_id: str | None = None
        if series_receipt is not None:
            series_event_id = _stage_meeting_event(
                uow.record_events,
                principal_id=principal_id,
                record_family=RecordEventFamily.MEETING_SERIES,
                record_id=series_receipt.meeting_series_id,
                event_kind=RecordEventKind.CREATED,
                record_version=series_receipt.after_version,
                changed_fields=_SERIES_TITLE_FIELDS,
                source_capability=source_capability,
                correlation_id=correlation_id,
                source_receipt_id=series_receipt.series_history_id,
                occurred_at=at,
            ).event_id
        _stage_meeting_event(
            uow.record_events,
            principal_id=principal_id,
            record_family=RecordEventFamily.MEETING,
            record_id=meeting_id,
            event_kind=RecordEventKind.CREATED,
            record_version=receipt.after_version,
            changed_fields=_meeting_created_fields(request),
            source_capability=source_capability,
            correlation_id=correlation_id,
            source_receipt_id=receipt.history_id,
            occurred_at=at,
            causation_event_id=series_event_id,
        )
        return MeetingWriteResult(
            meeting=view, receipt=receipt, replayed=False, series_receipt=series_receipt
        )

    # --- meetings.read / list / search -------------------------------------

    def read_meeting(self, uow: UnitOfWork, principal_id: str, meeting_id: str) -> MeetingView:
        """One Meeting by durable id. Absent and foreign are the same answer."""
        view = uow.meetings.read_meeting(principal_id, meeting_id)
        if view is None:
            raise MeetingNotFoundError(MeetingErrorField.MEETING_ID)
        return view

    def list_meetings(
        self, uow: UnitOfWork, principal_id: str, request: MeetingListRequest, now: datetime
    ) -> MeetingListPage:
        """One bounded keyset page under the structured filters (AC-024).

        An `after` anchor that is absent, foreign or outside the same filter
        partition raises `MeetingCursorError` from the repository.
        """
        return uow.meetings.list_meetings(principal_id, request, now=ensure_utc(now))

    def search_meetings(
        self, uow: UnitOfWork, principal_id: str, request: MeetingSearchRequest, now: datetime
    ) -> MeetingListPage:
        """One bounded keyset page of Meetings matching the query (AC-025)."""
        return uow.meetings.search_meetings(principal_id, request, now=ensure_utc(now))

    # --- meetings.update -----------------------------------------------------

    def update_meeting(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: MeetingUpdateRequest,
        expected_version: int,
        idempotency_key: str,
        now: datetime,
        *,
        source_capability: str = Capability.MEETINGS_UPDATE.value,
        correlation_id: str | None = None,
    ) -> MeetingWriteResult:
        """Patch one Meeting's scalars, attendees, attachments and note atomically.

        One row lock, one `expected_version` gate and at most one version
        increment, however many children change (section 19.6). A request that
        normalizes to the current state records a `no_op` receipt and leaves the
        version alone (section 35.9). Only a material change stages its one
        `updated` event (WP-RE-05 MT3); a cancel is an `updated` event too.
        """
        key = _checked_idempotency_key(idempotency_key)
        version = _checked_expected_version(expected_version)
        at = ensure_utc(now)
        digest = meeting_request_digest(
            MEETINGS_UPDATE_NAME, principal_id, request, expected_version=version
        )
        meetings = uow.meetings

        prior = meetings.reserve_write_request(
            principal_id, MEETINGS_UPDATE_NAME, key, digest, created_at=at
        )
        if prior is not None:
            return self._replayed_meeting(meetings, principal_id, prior)

        current = meetings.lock_meeting_for_update(principal_id, request.meeting_id)
        if current is None:
            raise MeetingNotFoundError(MeetingErrorField.MEETING_ID)
        if current.version != version:
            raise MeetingStaleVersionError()

        if request.project_id is not None:
            _require_project(meetings, principal_id, request.project_id)
        _require_documents(meetings, principal_id, request.attachment_add_document_ids)
        if request.attendees_replace is not None:
            _require_active_people(meetings, principal_id, request.attendees_replace)

        record, scalar_fields = _updated_record(current, request, at)

        attendees_retired: tuple[str, ...] = ()
        attendees_added: tuple[MeetingAttendeeRecord, ...] = ()
        if request.attendees_replace is not None:
            replacement = _in_digest_order(request.attendees_replace)
            active = _in_digest_order(tuple(_snapshot(a) for a in current.attendees))
            if replacement != active:
                attendees_retired = tuple(a.attendee_id for a in current.attendees)
                attendees_added = _attendee_records(replacement)

        attachments_retired, attachments_added = _attachment_delta(current, request)

        note_body = _note_body(current, request)
        material = (
            bool(scalar_fields)
            or bool(attendees_retired or attendees_added)
            or bool(attachments_retired or attachments_added)
            or note_body is not None
        )
        after_version = current.version + 1 if material else current.version

        if material:
            meetings.update_meeting(
                principal_id, replace(record, version=after_version, updated_at=at)
            )
            if attendees_retired:
                meetings.retire_attendees(
                    principal_id, current.meeting_id, attendees_retired, removed_at=at
                )
            meetings.insert_attendees(
                principal_id, current.meeting_id, attendees_added, added_at=at
            )
            if attachments_retired:
                meetings.retire_attachments(
                    principal_id, current.meeting_id, attachments_retired, removed_at=at
                )
            meetings.insert_attachments(
                principal_id, current.meeting_id, attachments_added, added_at=at
            )

        receipt = MeetingHistoryView(
            history_id=issue_identifier(IdKind.MEETING_HISTORY),
            meeting_id=current.meeting_id,
            action=MeetingHistoryAction.UPDATE,
            actor=_ACTOR,
            outcome=MeetingOutcome.APPLIED if material else MeetingOutcome.NO_OP,
            before_version=current.version,
            after_version=after_version,
            occurred_at=at,
            recorded_at=at,
        )
        # The receipt, the note linkage and the completed request all name the
        # Meeting's own series, which update can never change (WP-MTG-02 F-05).
        meetings.insert_meeting_history(
            principal_id,
            receipt,
            meeting_series_id=current.meeting_series_id,
            idempotency_key=key,
            request_digest=digest,
        )
        if note_body is not None:
            head = current.notes
            meetings.insert_note_version(
                principal_id,
                MeetingNoteRecord(
                    note_version_id=issue_identifier(IdKind.MEETING_NOTE_VERSION),
                    meeting_id=current.meeting_id,
                    version_number=1 if head is None else head.version_number + 1,
                    supersedes_note_version_id=None if head is None else head.note_version_id,
                    content_markdown=note_body,
                    content_sha256=note_content_sha256(note_body),
                    meeting_history_id=receipt.history_id,
                    recorded_at=at,
                ),
            )
        view = _current_meeting(meetings, principal_id, current.meeting_id)
        if view.meeting_series_id != current.meeting_series_id or view.version != after_version:
            raise RepositoryFailureError
        meetings.complete_write_request(
            principal_id,
            MEETINGS_UPDATE_NAME,
            key,
            request_digest=digest,
            meeting_id=current.meeting_id,
            meeting_series_id=current.meeting_series_id,
            meeting_history_id=receipt.history_id,
            meeting_series_history_id=None,
            result_version=after_version,
            completed_at=at,
        )
        if material:
            child_fields: dict[str, bool] = {
                "attendees": bool(attendees_retired or attendees_added),
                "attachments": bool(attachments_retired or attachments_added),
                "notes": note_body is not None,
            }
            _stage_meeting_event(
                uow.record_events,
                principal_id=principal_id,
                record_family=RecordEventFamily.MEETING,
                record_id=current.meeting_id,
                event_kind=RecordEventKind.UPDATED,
                record_version=after_version,
                changed_fields=field_set(
                    *scalar_fields, *(name for name, held in child_fields.items() if held)
                ),
                source_capability=source_capability,
                correlation_id=correlation_id,
                source_receipt_id=receipt.history_id,
                occurred_at=at,
            )
        return MeetingWriteResult(meeting=view, receipt=receipt, replayed=False)

    # --- meetings.series.update ---------------------------------------------

    def update_meeting_series(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: MeetingSeriesUpdateRequest,
        expected_version: int,
        idempotency_key: str,
        now: datetime,
        *,
        source_capability: str = Capability.MEETINGS_SERIES_UPDATE.value,
        correlation_id: str | None = None,
    ) -> MeetingSeriesWriteResult:
        """Retitle one MeetingSeries. No occurrence is locked or rewritten (AC-027).

        Only a material retitle stages its one `updated` event (WP-RE-05 MT4).
        """
        key = _checked_idempotency_key(idempotency_key)
        version = _checked_expected_version(expected_version)
        at = ensure_utc(now)
        digest = meeting_request_digest(
            MEETINGS_SERIES_UPDATE_NAME, principal_id, request, expected_version=version
        )
        meetings = uow.meetings

        prior = meetings.reserve_write_request(
            principal_id, MEETINGS_SERIES_UPDATE_NAME, key, digest, created_at=at
        )
        if prior is not None:
            if prior.meeting_series_id is None or prior.series_receipt is None:
                raise RepositoryFailureError
            series = meetings.read_owned_series(principal_id, prior.meeting_series_id)
            if series is None:
                raise RepositoryFailureError
            return MeetingSeriesWriteResult(
                series=series, receipt=prior.series_receipt, replayed=True
            )

        current = meetings.lock_series_for_update(principal_id, request.meeting_series_id)
        if current is None:
            raise MeetingNotFoundError(MeetingErrorField.MEETING_SERIES_ID)
        if current.version != version:
            raise MeetingStaleVersionError()

        material = request.title != current.title
        after_version = current.version + 1 if material else current.version
        if material:
            meetings.update_series_title(
                principal_id,
                current.meeting_series_id,
                title=request.title,
                version=after_version,
                updated_at=at,
            )
        receipt = MeetingSeriesHistoryView(
            series_history_id=issue_identifier(IdKind.MEETING_SERIES_HISTORY),
            meeting_series_id=current.meeting_series_id,
            action=MeetingHistoryAction.UPDATE,
            actor=_ACTOR,
            outcome=MeetingOutcome.APPLIED if material else MeetingOutcome.NO_OP,
            before_version=current.version,
            after_version=after_version,
            occurred_at=at,
            recorded_at=at,
        )
        meetings.insert_series_history(
            principal_id, receipt, idempotency_key=key, request_digest=digest
        )
        meetings.complete_write_request(
            principal_id,
            MEETINGS_SERIES_UPDATE_NAME,
            key,
            request_digest=digest,
            meeting_id=None,
            meeting_series_id=current.meeting_series_id,
            meeting_history_id=None,
            meeting_series_history_id=receipt.series_history_id,
            result_version=after_version,
            completed_at=at,
        )
        if material:
            _stage_meeting_event(
                uow.record_events,
                principal_id=principal_id,
                record_family=RecordEventFamily.MEETING_SERIES,
                record_id=current.meeting_series_id,
                event_kind=RecordEventKind.UPDATED,
                record_version=after_version,
                changed_fields=_SERIES_TITLE_FIELDS,
                source_capability=source_capability,
                correlation_id=correlation_id,
                source_receipt_id=receipt.series_history_id,
                occurred_at=at,
            )
        series = meetings.read_owned_series(principal_id, current.meeting_series_id)
        if series is None:
            raise RepositoryFailureError
        return MeetingSeriesWriteResult(series=series, receipt=receipt, replayed=False)

    # --- replay -------------------------------------------------------------

    @staticmethod
    def _replayed_meeting(
        meetings: MeetingRepository, principal_id: str, prior: MeetingWriteRequestRecord
    ) -> MeetingWriteResult:
        """The original receipt(s) beside the Meeting's current view (section 35.7)."""
        if prior.meeting_id is None or prior.meeting_receipt is None:
            raise RepositoryFailureError
        return MeetingWriteResult(
            meeting=_current_meeting(meetings, principal_id, prior.meeting_id),
            receipt=prior.meeting_receipt,
            replayed=True,
            series_receipt=prior.series_receipt,
        )


# ------------------------------------------------------------ update deltas


def _updated_record(
    current: MeetingView, request: MeetingUpdateRequest, at: datetime
) -> tuple[MeetingRecord, tuple[str, ...]]:
    """The Meeting's scalar state after the patch, and the names of the fields
    that differ (sorted; empty when nothing scalar changes).

    Omitted means unchanged; a `clear_fields` member means NULL, and wins over
    a value supplied for the same field (module docstring, ruling R3-02). Series
    membership, identity and creation time are carried over unchanged.
    """
    clears = frozenset(request.clear_fields)

    def patched[ValueT](
        supplied: ValueT | None, existing: ValueT | None, clear: MeetingClearField | None
    ) -> ValueT | None:
        if clear is not None and clear in clears:
            return None
        return existing if supplied is None else supplied

    title = current.title if request.title is None else request.title
    start_at = current.start_at if request.start_at is None else request.start_at
    end_at = patched(request.end_at, current.end_at, MeetingClearField.END_AT)
    timezone_name = (
        current.timezone_name if request.timezone_name is None else request.timezone_name
    )
    status = current.status if request.status is None else MeetingStatus(request.status)
    location_text = patched(
        request.location_text, current.location_text, MeetingClearField.LOCATION_TEXT
    )
    virtual_meeting_url = patched(
        request.virtual_meeting_url,
        current.virtual_meeting_url,
        MeetingClearField.VIRTUAL_MEETING_URL,
    )
    description = patched(request.description, current.description, MeetingClearField.DESCRIPTION)
    project_id = patched(request.project_id, current.project_id, MeetingClearField.PROJECT_ID)

    # The resulting schedule, not only the supplied pair, must be ordered: a
    # later start alone can overtake the stored end.
    validate_meeting_time_range(start_at, end_at)

    if status is current.status:
        cancelled_at = current.cancelled_at
    elif status is MeetingStatus.CANCELLED:
        cancelled_at = at
    else:
        cancelled_at = None

    record = MeetingRecord(
        meeting_id=current.meeting_id,
        meeting_series_id=current.meeting_series_id,
        title=title,
        start_at=start_at,
        end_at=end_at,
        timezone_name=timezone_name,
        status=status,
        cancelled_at=cancelled_at,
        location_text=location_text,
        virtual_meeting_url=virtual_meeting_url,
        description=description,
        project_id=project_id,
        version=current.version,
        created_at=current.created_at,
        updated_at=current.updated_at,
    )
    # A typed comparison over explicitly spelled fields (WP-RE-05 MT3, R3).
    # `cancelled_at` moves exactly when `status` enters or leaves CANCELLED, so
    # it never makes a patch material on its own, but it is named when it moves.
    before: dict[str, object] = {
        "title": current.title,
        "start_at": current.start_at,
        "end_at": current.end_at,
        "timezone_name": current.timezone_name,
        "status": current.status,
        "cancelled_at": current.cancelled_at,
        "location_text": current.location_text,
        "virtual_meeting_url": current.virtual_meeting_url,
        "description": current.description,
        "project_id": current.project_id,
    }
    after: dict[str, object] = {
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
        "timezone_name": timezone_name,
        "status": status,
        "cancelled_at": cancelled_at,
        "location_text": location_text,
        "virtual_meeting_url": virtual_meeting_url,
        "description": description,
        "project_id": project_id,
    }
    return record, field_set(*(name for name, value in after.items() if before[name] != value))


def _attachment_delta(
    current: MeetingView, request: MeetingUpdateRequest
) -> tuple[tuple[str, ...], tuple[MeetingAttachmentRecord, ...]]:
    """The attachment ids to retire and the relations to insert.

    Adding a document that is already actively attached is a refused
    duplicate, never silently ignored; removing an attachment id that is not
    active on this Meeting (absent, retired or foreign) is not found (section
    35.9). The resulting active set stays within 50.
    """
    active_documents = {attachment.document_id for attachment in current.attachments}
    active_ids = {attachment.attachment_id for attachment in current.attachments}
    if any(document_id in active_documents for document_id in request.attachment_add_document_ids):
        raise MeetingInvalidRequestError(MeetingErrorField.DOCUMENT_ID)
    if any(attachment_id not in active_ids for attachment_id in request.attachment_remove_ids):
        raise MeetingNotFoundError(MeetingErrorField.ATTACHMENT_ID)
    remaining = (
        len(current.attachments)
        - len(request.attachment_remove_ids)
        + len(request.attachment_add_document_ids)
    )
    if remaining > MAX_MEETING_ATTACHMENTS:
        raise MeetingInvalidRequestError(MeetingErrorField.DOCUMENT_ID)
    return (
        tuple(sorted(request.attachment_remove_ids)),
        _attachment_records(request.attachment_add_document_ids),
    )


def _note_body(current: MeetingView, request: MeetingUpdateRequest) -> str | None:
    """The new note body, or `None` when the note does not change.

    Append always changes it (separator plus a nonblank chunk). Replace with a
    body whose content hash equals the current head's is a no-op (section
    34.12/35.9).
    """
    if request.notes_mode is None or request.notes_markdown is None:
        return None
    head = current.notes
    if request.notes_mode is MeetingNotesMode.APPEND:
        return compose_appended_note(
            None if head is None else head.body_markdown, request.notes_markdown
        )
    body = validate_meeting_notes_markdown(request.notes_markdown)
    if head is not None and note_content_sha256(head.body_markdown) == note_content_sha256(body):
        return None
    return body
