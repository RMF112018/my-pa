"""One normalised request, whichever protocol delivered it.

A driving adapter's whole job is to turn `(capability name, arguments)` into the
`(RequestMetadata, Command)` pair `ApplicationService.invoke` takes. This module
is that turn, and it is shared rather than per-transport because
`SPEC-AC-001` asks for two transports that produce *equal* pairs — a claim that
is proved by construction when both call this function, and only tested by
sampling when each has its own copy.

**There is no validation here, and that is the point.** `D-25` chose Starlette
over FastAPI precisely so that HTTP would not acquire a second validation layer
that MCP has no counterpart for. So every rule a request is held to is already
owned by something else: `RequestMetadata` is a `StrictModel`, which rejects an
unknown field, a bad purpose, a malformed principal identifier, and the wrong
contract version; each command's `__post_init__` rejects a malformed identifier,
a contradictory selector, and a non-positive count. What this module does is
*shape* conversion — a JSON array is not a tuple and a JSON string is not a
`Representation` — plus the one classification that shape conversion needs: a
`TypeError` from a constructor that was handed a field it does not have becomes
`invalid_request` rather than escaping as a crash.

**Failures are raised, never rendered.** Every refusal leaves as
`InvalidRequestError`, which the caller renders through
`application.errors.problem_detail` exactly as the application's own refusals
are rendered. A transport that built its own error body would be a second error
vocabulary, and the point of one validation path is that there is one of those
too.

**Nothing here reads a value into a message.** The refusals below carry no
`safe_details` at all: the field names this layer could report — `request_id`,
`purpose`, `requested_at` — are not members of `application.errors.SafeDetail`,
and that closed set is what keeps a rejected value out of a public error. A
command's own refusal carries its own token, so the details a caller does get
are the ones the application already vouches for.

**The one bound that lives here, and why it is not in a transport.**
`MAX_REQUEST_BYTES` is derived from the largest request the *contract* can
express, not from anything a protocol does, so it is a property of the request
and belongs beside the function that builds one. It was written in
`adapters/http/app.py` when HTTP was the only transport, and WP-4B2b moved it:
three transports importing a ceiling from one transport's module would say that
deleting HTTP breaks MCP, which is false, and a structural claim that is false
misleads the next reader more than a duplicated constant would. Enforcing it is
still each transport's own act — HTTP refuses on the declared `content-length`
before reading, and the other two measure a document the protocol has already
delivered — but the number they enforce is one number.
"""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as BinasciiError
from collections.abc import Callable, Mapping
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from my_pa.application.commands import (
    AddEntityAlias,
    ArchiveEntity,
    ArchiveManagedDocument,
    ArchiveRelationshipMemory,
    BeginIntelligenceCycle,
    BindEntityIdentifier,
    BulkConfirmTasks,
    BulkPreviewTasks,
    CloseCommitment,
    Command,
    CommitIntelligenceArtifact,
    CreateCapture,
    CreateCommitment,
    CreateEntity,
    CreateEntityAssignment,
    CreateEntityRelationship,
    CreateManagedDocument,
    CreateProject,
    CreateRelationshipMemory,
    CreateSituation,
    CreateTask,
    DecideReviewCase,
    EndEntityAssignment,
    EndEntityRelationship,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetCommitmentHistory,
    GetCorpusCoverage,
    GetEntity,
    GetEntityContext,
    GetEntityRelationships,
    GetGoodNotesContent,
    GetGoodNotesWork,
    GetGsqsB0Status,
    GetLatestIntelligenceArtifact,
    GetPulse,
    GetRelationshipMemory,
    GetRelationshipMemoryHistory,
    GetSourceMetadata,
    GetSourceStatus,
    GetTaskHistory,
    ListCaptures,
    ListCommitments,
    ListEntityAliases,
    ListEntityAssignments,
    ListEntityIdentifiers,
    ListEntityObservations,
    ListIntelligenceArtifacts,
    ListManagedDocuments,
    ListProjects,
    ListRelationshipMemories,
    ListReviewCases,
    ListSituations,
    ListSources,
    ListTasks,
    ListUnresolvedMentions,
    ObserveEntityMention,
    PrepareContext,
    ReadCapture,
    ReadCommitment,
    ReadIntelligenceArtifact,
    ReadKnowledge,
    ReadManagedDocument,
    ReadTask,
    RecordContextFeedback,
    RecordIntelligenceRunState,
    RecordTask,
    Representation,
    ResolveEntity,
    ResolveIntelligenceSet,
    ResolveUnresolvedMention,
    RestoreEntity,
    RestoreManagedDocument,
    RestoreRelationshipMemory,
    RetireEntityAlias,
    RetireEntityIdentifier,
    RevealSubject,
    ReviseCapture,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
    ReviseManagedDocument,
    ReviseRelationshipMemory,
    SearchCaptures,
    SearchCommitments,
    SearchEntities,
    SearchIntelligenceArtifacts,
    SearchKnowledge,
    SearchRelationshipMemories,
    SearchTasks,
    StartGsqsB0,
    SubmitGoodNotesProposal,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
    TransitionTask,
    UpdateCommitment,
    UpdateEntity,
    UpdateTask,
    WaitingOn,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail, UnsupportedError
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.context import ContextPlane
from my_pa.domain.context.preference import ContextPreferenceAction
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.intelligence.catalog import (
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ResolverSetId,
    SourceLaneId,
)
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    AssignmentType,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifierNamespace,
    IdentifierState,
)
from my_pa.domain.relationship.governance import (
    ObservationAuthority,
    ObservationKind,
    ResolutionDisposition,
)
from my_pa.domain.relationship.memory import MemoryKind, MemoryLifecycle
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    CommitmentWorkView,
)
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_ITEMS
from my_pa.domain.task.lifecycle import (
    TaskArchiveMode,
    TaskLifecycleState,
    TaskPriority,
    TaskWorkView,
)
from my_pa.domain.task.role import TaskRole

__all__ = ["MAX_REQUEST_BYTES", "PAYLOAD_KEY", "normalize"]

#: Where a request's capability-specific fields live, separated from the common
#: metadata beside them. Separate rather than flat because the two are validated
#: by different owners — the envelope by `RequestMetadata`, the payload by the
#: command — and a flat document would make "which owner rejected this" a
#: question about field names.
PAYLOAD_KEY: Final = "payload"

#: An identifier in a JSON array: at most 72 characters, which is the bound
#: `domain.common.identifiers` enforces, plus the two quotes and the comma that
#: carry it. Restated rather than imported because that bound is private to the
#: module that enforces it — and checked rather than trusted, by
#: `test_the_request_ceiling_admits_the_largest_request_the_contract_allows`,
#: which builds identifiers at the real maximum and measures the result.
_IDENTIFIER_JSON_BYTES: Final = 75

#: Everything a request carries that is not `sources.enroll`'s object list. An
#: enrollment may name 32 media types and neither the domain nor the contract
#: bounds one's length, so this is where a media type is bounded, at 128 bytes
#: each. The rest is small and enumerable: a request id and an idempotency key
#: at 128 characters each, a search query and a cursor at 512 characters and at
#: most four UTF-8 bytes per character, and a dozen short scalars. Eight
#: kibibytes covers all of it several times over.
_ENVELOPE_BYTES: Final = 32 * 128 + 8 * 1024

#: Most bytes one request may carry, derived from the largest request the
#: contract can express rather than chosen as a round number. `sources.enroll`
#: at its domain ceiling is that request: `MAX_ENROLLMENT_ITEMS` object
#: identifiers, and everything else beside them.
#:
#: `capture.create` at *its* domain ceiling is the other candidate and is
#: smaller: `MAX_CAPTURE_CHARACTERS` characters escape to at most six JSON bytes
#: each, which is under this bound with the envelope beside it. So the ceiling
#: the domain publishes for a capture is reachable over every transport rather
#: than being silently cut off by this one — which would refuse the largest legal
#: capture with `invalid_request` and no field to name.
#:
#: A caller can exceed this — `RequestMetadata.scope` takes identifier lists the
#: contract does not bound — and exceeding it is refused rather than truncated.
#: The declared scope is correlation input that authorization does not read, so
#: nothing is lost by bounding it here.
#:
#: It lives beside `normalize` rather than in a transport because it is derived
#: from the contract; see the module docstring.
MAX_REQUEST_BYTES: Final = MAX_ENROLLMENT_ITEMS * _IDENTIFIER_JSON_BYTES + _ENVELOPE_BYTES


def _strings(value: object, detail: SafeDetail) -> tuple[str, ...]:
    """A JSON array of strings as the tuple a command declares.

    JSON has no tuple and no way to say "strings only", so this is conversion
    rather than validation. It refuses a non-string entry because the field it
    feeds — an enrollment's media-type allowlist — would otherwise reach the
    domain as a list containing an integer and fail as a `TypeError` from a
    regular expression, which is a crash where a refusal belongs.
    """
    if not isinstance(value, list):
        raise InvalidRequestError(detail)
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InvalidRequestError(detail)
        items.append(item)
    return tuple(items)


def _get_capabilities(payload: Mapping[str, Any]) -> Command:
    return GetCapabilities(**payload)


def _list_sources(payload: Mapping[str, Any]) -> Command:
    return ListSources(**payload)


def _get_source_metadata(payload: Mapping[str, Any]) -> Command:
    return GetSourceMetadata(**payload)


def _fetch_source(payload: Mapping[str, Any]) -> Command:
    """`sources.fetch`, with the representation resolved to its enum member.

    Resolved here because `FetchSource` refuses anything that is not a
    `Representation`, so a caller's `"raw_bytes"` would otherwise be rejected for
    being a string rather than for naming something. An unresolvable string is
    refused with the same token the command uses, so the two paths report the
    same field.
    """
    named = payload.get("representation")
    if not isinstance(named, str):
        # Left alone: `FetchSource` refuses a non-string representation itself,
        # and an absent one takes the command's own default.
        return FetchSource(**payload)
    try:
        representation = Representation(named)
    except ValueError:
        pass
    else:
        return FetchSource(**{**payload, "representation": representation})
    raise InvalidRequestError(SafeDetail.REPRESENTATION)


def _get_source_status(payload: Mapping[str, Any]) -> Command:
    return GetSourceStatus(**payload)


def _enroll_source(payload: Mapping[str, Any]) -> Command:
    """`sources.enroll`, with its two JSON arrays converted to tuples.

    Converted only when present: `object_ids` is optional, and an absent one
    means the request selects a root instead — a distinction `EnrollmentScope`
    enforces and this must not erase by supplying an empty tuple of its own.
    """
    converted = dict(payload)
    if "media_types" in converted:
        converted["media_types"] = _strings(converted["media_types"], SafeDetail.MEDIA_TYPES)
    if "object_ids" in converted:
        converted["object_ids"] = _strings(converted["object_ids"], SafeDetail.SOURCE_OBJECT_ID)
    return EnrollSource(**converted)


def _search_knowledge(payload: Mapping[str, Any]) -> Command:
    return SearchKnowledge(**payload)


def _read_knowledge(payload: Mapping[str, Any]) -> Command:
    return ReadKnowledge(**payload)


#: The two caller-supplied times a capture may carry, and the token each is
#: refused under. Both are optional and neither is ever defaulted from the other
#: or from the request clock (`QC-AC-012`).
_CAPTURE_MOMENTS: Mapping[str, SafeDetail] = MappingProxyType(
    {
        "client_created_at": SafeDetail.CLIENT_CREATED_AT,
        "occurred_at": SafeDetail.OCCURRED_AT,
    }
)


def _moments(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a capture's optional times from RFC 3339 strings to datetimes.

    Shape conversion, like `_fetch_source`'s representation: JSON has no
    datetime, and the command refuses anything that is not one, so a caller's
    `"2026-08-03T09:00:00Z"` would otherwise be rejected for being a string
    rather than for naming a moment. `fromisoformat` accepts the `Z` suffix on
    Python 3.11 and later, which is the form the contract publishes.

    A key that is absent stays absent, and a key that is present and `null`
    stays `None`: the command distinguishes "the caller did not say" from "the
    caller said nothing", and both mean the same stored value here — but
    inventing one from the request clock would be the coercion `QC-AC-012`
    exists to prevent, so neither is filled in.
    """
    converted = dict(payload)
    for name, detail in _CAPTURE_MOMENTS.items():
        supplied = converted.get(name)
        if supplied is None:
            continue
        if not isinstance(supplied, str):
            raise InvalidRequestError(detail)
        try:
            converted[name] = datetime.fromisoformat(supplied)
        except ValueError:
            pass
        else:
            continue
        # Outside the handler: the original renders the rejected value.
        raise InvalidRequestError(detail)
    return converted


def _create_capture(payload: Mapping[str, Any]) -> Command:
    converted = _moments(payload)
    named = converted.get("capture_kind")
    if isinstance(named, str):
        try:
            converted["capture_kind"] = CaptureKind(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.CAPTURE_KIND) from None
    return CreateCapture(**converted)


def _revise_capture(payload: Mapping[str, Any]) -> Command:
    return ReviseCapture(**_moments(payload))


def _read_capture(payload: Mapping[str, Any]) -> Command:
    return ReadCapture(**payload)


def _list_captures(payload: Mapping[str, Any]) -> Command:
    return ListCaptures(**payload)


def _search_captures(payload: Mapping[str, Any]) -> Command:
    return SearchCaptures(**payload)


def _reveal_subject(payload: Mapping[str, Any]) -> Command:
    return RevealSubject(**payload)


def _list_review_cases(payload: Mapping[str, Any]) -> Command:
    return ListReviewCases(**payload)


def _get_pulse(payload: Mapping[str, Any]) -> Command:
    return GetPulse(**payload)


def _list_situations(payload: Mapping[str, Any]) -> Command:
    return ListSituations(**payload)


def _list_projects(payload: Mapping[str, Any]) -> Command:
    return ListProjects(**payload)


def _create_project(payload: Mapping[str, Any]) -> Command:
    return CreateProject(**payload)


def _create_situation(payload: Mapping[str, Any]) -> Command:
    return CreateSituation(**payload)


def _record_task(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    supplied = converted.get("due_at")
    if isinstance(supplied, str):
        try:
            converted["due_at"] = datetime.fromisoformat(supplied)
        except ValueError:
            raise InvalidRequestError(SafeDetail.DUE_AT) from None
    return RecordTask(**converted)


def _get_corpus_coverage(payload: Mapping[str, Any]) -> Command:
    return GetCorpusCoverage(**payload)


def _read_task(payload: Mapping[str, Any]) -> Command:
    return ReadTask(**payload)


def _list_tasks(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    named = converted.get("archive_mode")
    if isinstance(named, str):
        try:
            converted["archive_mode"] = TaskArchiveMode(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named = converted.get("lifecycle_state")
    if isinstance(named, str):
        try:
            converted["lifecycle_state"] = TaskLifecycleState(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.LIFECYCLE_STATE) from None
    named = converted.get("priority")
    if isinstance(named, str):
        try:
            converted["priority"] = TaskPriority(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.PRIORITY) from None
    named = converted.get("work_view")
    if isinstance(named, str):
        try:
            converted["work_view"] = TaskWorkView(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named_date = converted.get("work_date")
    if isinstance(named_date, str):
        try:
            converted["work_date"] = date.fromisoformat(named_date)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    return ListTasks(**converted)


def _search_tasks(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    named = converted.get("archive_mode")
    if isinstance(named, str):
        try:
            converted["archive_mode"] = TaskArchiveMode(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named = converted.get("work_view")
    if isinstance(named, str):
        try:
            converted["work_view"] = TaskWorkView(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named_date = converted.get("work_date")
    if isinstance(named_date, str):
        try:
            converted["work_date"] = date.fromisoformat(named_date)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    return SearchTasks(**converted)


def _get_task_history(payload: Mapping[str, Any]) -> Command:
    return GetTaskHistory(**payload)


def _task_moment(converted: dict[str, Any], field_name: str, detail: SafeDetail) -> None:
    """Resolve one of a task command's optional RFC 3339 fields in place.

    The same shape conversion `_moments` performs for a capture's two moments,
    generalised over a field name because the task-write plane has three of
    them (`due_at`, `scheduled_at`, `deferred_until`) spread across two
    commands rather than one fixed pair on one command.
    """
    supplied = converted.get(field_name)
    if not isinstance(supplied, str):
        return
    try:
        converted[field_name] = datetime.fromisoformat(supplied)
    except ValueError:
        raise InvalidRequestError(detail) from None


def _create_task(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    _task_moment(converted, "due_at", SafeDetail.DUE_AT)
    named = converted.get("priority")
    if isinstance(named, str):
        try:
            converted["priority"] = TaskPriority(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.PRIORITY) from None
    named = converted.get("role")
    if isinstance(named, str):
        try:
            converted["role"] = TaskRole(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    return CreateTask(**converted)


def _update_task(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    _task_moment(converted, "due_at", SafeDetail.DUE_AT)
    _task_moment(converted, "scheduled_at", SafeDetail.SCHEDULED_AT)
    _task_moment(converted, "deferred_until", SafeDetail.DEFERRED_UNTIL)
    named = converted.get("priority")
    if isinstance(named, str):
        try:
            converted["priority"] = TaskPriority(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.PRIORITY) from None
    named = converted.get("role")
    if isinstance(named, str):
        try:
            converted["role"] = TaskRole(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    return UpdateTask(**converted)


def _transition_task(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    named = converted.get("to_state")
    if isinstance(named, str):
        try:
            converted["to_state"] = TaskLifecycleState(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.LIFECYCLE_STATE) from None
    return TransitionTask(**converted)


def _mutations(value: object) -> tuple[dict[str, object], ...]:
    """A JSON array of objects as the tuple of mappings `BulkPreviewTasks` holds.

    Each entry stays a `dict` for the command boundary. The application bulk
    normalizer then enforces the closed update/transition vocabulary, canonical
    ordering, bounds, and digest; creation is not a bulk mutation.
    """
    if not isinstance(value, list):
        raise InvalidRequestError(SafeDetail.MUTATIONS)
    mutations: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidRequestError(SafeDetail.MUTATIONS)
        mutations.append(item)
    return tuple(mutations)


def _bulk_preview_tasks(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    if "mutations" in converted:
        converted["mutations"] = _mutations(converted["mutations"])
    return BulkPreviewTasks(**converted)


def _bulk_confirm_tasks(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    if "mutations" in converted:
        converted["mutations"] = _mutations(converted["mutations"])
    return BulkConfirmTasks(**converted)


def _read_commitment(payload: Mapping[str, Any]) -> Command:
    return ReadCommitment(**payload)


def _list_commitments(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    named = converted.get("direction")
    if isinstance(named, str):
        try:
            converted["direction"] = CommitmentDirection(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named = converted.get("state")
    if isinstance(named, str):
        try:
            converted["state"] = CommitmentState(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named = converted.get("work_view")
    if isinstance(named, str):
        try:
            converted["work_view"] = CommitmentWorkView(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named_date = converted.get("work_date")
    if isinstance(named_date, str):
        try:
            converted["work_date"] = date.fromisoformat(named_date)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    return ListCommitments(**converted)


def _search_commitments(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    named = converted.get("direction")
    if isinstance(named, str):
        try:
            converted["direction"] = CommitmentDirection(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named = converted.get("state")
    if isinstance(named, str):
        try:
            converted["state"] = CommitmentState(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named = converted.get("work_view")
    if isinstance(named, str):
        try:
            converted["work_view"] = CommitmentWorkView(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    named_date = converted.get("work_date")
    if isinstance(named_date, str):
        try:
            converted["work_date"] = date.fromisoformat(named_date)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    return SearchCommitments(**converted)


def _get_commitment_history(payload: Mapping[str, Any]) -> Command:
    return GetCommitmentHistory(**payload)


def _waiting_on(payload: Mapping[str, Any]) -> Command:
    return WaitingOn(**payload)


def _create_commitment(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    _task_moment(converted, "due_at", SafeDetail.DUE_AT)
    named = converted.get("direction")
    if isinstance(named, str):
        try:
            converted["direction"] = CommitmentDirection(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SELECTOR) from None
    return CreateCommitment(**converted)


def _update_commitment(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    _task_moment(converted, "due_at", SafeDetail.DUE_AT)
    return UpdateCommitment(**converted)


def _close_commitment(payload: Mapping[str, Any]) -> Command:
    return CloseCommitment(**payload)


def _prepare_context(payload: Mapping[str, Any]) -> Command:
    """`context.prepare`, with JSON arrays converted to the tuples the command holds.

    Shape conversion, like `_enroll_source`: JSON has no tuple and no enum, so a
    caller's `["knowledge"]` would otherwise be rejected for being a list of
    strings rather than for naming a plane. An unresolvable string is refused
    with the same token the command uses.
    """
    converted = dict(payload)
    if "subject_hints" in converted:
        converted["subject_hints"] = _strings(converted["subject_hints"], SafeDetail.SUBJECT_HINTS)
    if "requested_planes" in converted:
        named = converted["requested_planes"]
        if not isinstance(named, list):
            raise InvalidRequestError(SafeDetail.REQUESTED_PLANES)
        planes: list[ContextPlane] = []
        for item in named:
            if not isinstance(item, str):
                raise InvalidRequestError(SafeDetail.REQUESTED_PLANES)
            try:
                planes.append(ContextPlane(item))
            except ValueError:
                raise InvalidRequestError(SafeDetail.REQUESTED_PLANES) from None
        converted["requested_planes"] = tuple(planes)
    return PrepareContext(**converted)


def _record_context_feedback(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    if "action" in converted:
        named = converted["action"]
        if not isinstance(named, str):
            raise InvalidRequestError(SafeDetail.ACTION)
        try:
            converted["action"] = ContextPreferenceAction(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.ACTION) from None
    return RecordContextFeedback(**converted)


def _get_goodnotes_work(payload: Mapping[str, Any]) -> Command:
    return GetGoodNotesWork(**payload)


def _start_gsqs_b0(payload: Mapping[str, Any]) -> Command:
    return StartGsqsB0(**payload)


def _get_gsqs_b0_status(payload: Mapping[str, Any]) -> Command:
    return GetGsqsB0Status(**payload)


def _search_entities(payload: Mapping[str, Any]) -> Command:
    return SearchEntities(**payload)


def _get_entity(payload: Mapping[str, Any]) -> Command:
    return GetEntity(**payload)


def _resolve_entity(payload: Mapping[str, Any]) -> Command:
    """`entities.resolve`, with `as_of` parsed from the wire's RFC 3339 string.

    Shape conversion, for the reason `_moments` gives: JSON has no datetime, and
    the command refuses anything that is not one, so a caller's
    `"2026-08-18T12:00:00Z"` would otherwise be rejected for being a string
    rather than for naming a moment.
    """
    converted = dict(payload)
    supplied = converted.get("as_of")
    if supplied is not None:
        if not isinstance(supplied, str):
            raise InvalidRequestError(SafeDetail.OCCURRED_AT)
        try:
            converted["as_of"] = datetime.fromisoformat(supplied)
        except ValueError:
            raise InvalidRequestError(SafeDetail.OCCURRED_AT) from None
    return ResolveEntity(**converted)


def _get_entity_context(payload: Mapping[str, Any]) -> Command:
    return GetEntityContext(**payload)


def _get_entity_relationships(payload: Mapping[str, Any]) -> Command:
    return GetEntityRelationships(**payload)


def _list_unresolved_mentions(payload: Mapping[str, Any]) -> Command:
    return ListUnresolvedMentions(**payload)


#: The directed-relationship times a caller may supply. Separate from
#: `_MEMORY_MOMENTS` for the reason that mapping is separate from
#: `_CAPTURE_MOMENTS`: the planes carry different fields, and one shared mapping
#: would convert a key on a command that has no such field.
_DIRECTED_MOMENTS: Mapping[str, SafeDetail] = MappingProxyType(
    {
        "effective_from": SafeDetail.EFFECTIVE_FROM,
        "effective_to": SafeDetail.EFFECTIVE_TO,
        "effective_end": SafeDetail.EFFECTIVE_TO,
    }
)


def _directed_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """One directed-write payload, in the shapes the command declares.

    Shape conversion only: JSON has no datetime, no tuple and no enum. A value
    outside a closed vocabulary is left exactly as it arrived so the command
    reports it under its own field name, which is the rule `_memory_vocabulary`
    states and for the same reason -- refusing here would report the wrong field
    for a payload that got two things wrong.
    """
    converted = dict(payload)
    for name, detail in _DIRECTED_MOMENTS.items():
        supplied = converted.get(name)
        if supplied is None:
            continue
        if not isinstance(supplied, str):
            raise InvalidRequestError(detail)
        try:
            converted[name] = datetime.fromisoformat(supplied)
        except ValueError:
            pass
        else:
            continue
        # Outside the handler: the original renders the rejected value.
        raise InvalidRequestError(detail)
    for name, vocabulary in (
        ("assignment_type", AssignmentType),
        ("relationship_type", EntityRelationshipType),
    ):
        value = converted.get(name)
        if isinstance(value, str):
            try:
                converted[name] = vocabulary(value)
            except ValueError:
                continue
    for name in ("evidence_refs", "clear"):
        value = converted.get(name)
        if isinstance(value, list):
            converted[name] = tuple(value)
    return converted


def _list_entity_assignments(payload: Mapping[str, Any]) -> Command:
    return ListEntityAssignments(**payload)


def _create_entity_assignment(payload: Mapping[str, Any]) -> Command:
    return CreateEntityAssignment(**_directed_payload(payload))


def _revise_entity_assignment(payload: Mapping[str, Any]) -> Command:
    return ReviseEntityAssignment(**_directed_payload(payload))


def _end_entity_assignment(payload: Mapping[str, Any]) -> Command:
    return EndEntityAssignment(**_directed_payload(payload))


def _create_entity_relationship(payload: Mapping[str, Any]) -> Command:
    return CreateEntityRelationship(**_directed_payload(payload))


def _revise_entity_relationship(payload: Mapping[str, Any]) -> Command:
    return ReviseEntityRelationship(**_directed_payload(payload))


def _end_entity_relationship(payload: Mapping[str, Any]) -> Command:
    return EndEntityRelationship(**_directed_payload(payload))


def _list_entity_observations(payload: Mapping[str, Any]) -> Command:
    return ListEntityObservations(**payload)


def _observe_entity_mention(payload: Mapping[str, Any]) -> Command:
    """Shape conversion only: JSON has no enum and no datetime.

    The two closed vocabularies become the members the command declares, so the
    published MCP schema names them and a caller can see what it may send. A
    value outside either vocabulary is refused *here*, under its own field name,
    rather than passed through -- `authority` is the field this plane most needs
    a caller to get right, and reporting it as a generic bad request would tell
    a caller the least useful true thing.
    """
    converted = dict(payload)
    converted["kind"] = _enum_or_invalid(
        converted.get("kind"), ObservationKind, SafeDetail.OBSERVATION_KIND
    )
    converted["authority"] = _enum_or_invalid(
        converted.get("authority"), ObservationAuthority, SafeDetail.OBSERVATION_AUTHORITY
    )
    observed_at = converted.get("observed_at")
    if isinstance(observed_at, str):
        try:
            converted["observed_at"] = datetime.fromisoformat(observed_at)
        except ValueError:
            raise InvalidRequestError(SafeDetail.OBSERVED_AT) from None
    return ObserveEntityMention(**converted)


def _resolve_unresolved_mention(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    converted["disposition"] = _enum_or_invalid(
        converted.get("disposition"), ResolutionDisposition, SafeDetail.DISPOSITION
    )
    if converted.get("entity_type") is not None:
        converted["entity_type"] = _enum_or_invalid(
            converted["entity_type"], EntityType, SafeDetail.ENTITY_TYPE
        )
    return ResolveUnresolvedMention(**converted)


#: The Relationship Memory times a caller may supply, and the field each is
#: reported under when it is not a moment. Separate from `_CAPTURE_MOMENTS`
#: because the two planes carry different fields, and one shared mapping would
#: convert a key on a command that has no such field.
_MEMORY_MOMENTS: Mapping[str, SafeDetail] = MappingProxyType(
    {
        "observed_at": SafeDetail.OBSERVED_AT,
        "effective_from": SafeDetail.EFFECTIVE_FROM,
        "effective_to": SafeDetail.EFFECTIVE_TO,
        "as_of": SafeDetail.AS_OF,
    }
)


def _memory_moments(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a memory's optional times from RFC 3339 strings to datetimes.

    Shape conversion only, exactly as `_moments` is for the capture plane: JSON
    has no datetime and the command refuses anything that is not one. An absent
    key stays absent and a null stays null — an unknown moment is a real answer
    here, and filling one in from the request clock would fabricate a fact about
    the world out of a fact about this process.
    """
    converted = dict(payload)
    for name, detail in _MEMORY_MOMENTS.items():
        supplied = converted.get(name)
        if supplied is None:
            continue
        if not isinstance(supplied, str):
            raise InvalidRequestError(detail)
        try:
            converted[name] = datetime.fromisoformat(supplied)
        except ValueError:
            pass
        else:
            continue
        # Outside the handler: the original renders the rejected value.
        raise InvalidRequestError(detail)
    return converted


def _memory_vocabulary(payload: dict[str, Any]) -> dict[str, Any]:
    """Closed-vocabulary strings as the enum members the commands declare.

    JSON has no enum and no tuple. The commands hold `MemoryKind` and
    `MemoryLifecycle` so the published MCP schema names the members a caller may
    use, and this is where a caller's string becomes one — the same conversion
    `_fetch_source` performs for `Representation`.

    A value outside the vocabulary is left exactly as it arrived rather than
    refused here, so the command reports it under its own field name. Converting
    would need a second copy of each vocabulary's error mapping, and refusing
    here would report the wrong field for a payload that got two things wrong.
    """
    for name, vocabulary in (("kind", MemoryKind), ("lifecycle", MemoryLifecycle)):
        value = payload.get(name)
        if isinstance(value, str):
            try:
                payload[name] = vocabulary(value)
            except ValueError:
                continue
    kinds = payload.get("kinds")
    if isinstance(kinds, list):
        converted: list[Any] = []
        for entry in kinds:
            try:
                converted.append(MemoryKind(entry) if isinstance(entry, str) else entry)
            except ValueError:
                converted.append(entry)
        payload["kinds"] = tuple(converted)
    links = payload.get("context_links")
    if isinstance(links, list):
        payload["context_links"] = tuple(links)
    return payload


def _create_relationship_memory(payload: Mapping[str, Any]) -> Command:
    return CreateRelationshipMemory(**_memory_vocabulary(_memory_moments(payload)))


def _get_relationship_memory(payload: Mapping[str, Any]) -> Command:
    return GetRelationshipMemory(**payload)


def _list_relationship_memories(payload: Mapping[str, Any]) -> Command:
    return ListRelationshipMemories(**_memory_vocabulary(_memory_moments(payload)))


def _search_relationship_memories(payload: Mapping[str, Any]) -> Command:
    return SearchRelationshipMemories(**_memory_vocabulary(dict(payload)))


def _get_relationship_memory_history(payload: Mapping[str, Any]) -> Command:
    return GetRelationshipMemoryHistory(**payload)


def _revise_relationship_memory(payload: Mapping[str, Any]) -> Command:
    return ReviseRelationshipMemory(**_memory_vocabulary(_memory_moments(payload)))


def _archive_relationship_memory(payload: Mapping[str, Any]) -> Command:
    return ArchiveRelationshipMemory(**payload)


def _restore_relationship_memory(payload: Mapping[str, Any]) -> Command:
    return RestoreRelationshipMemory(**payload)


# --- the entity plane's authoring half (WP-RI-A-02) --------------------------
#
# Shape conversion and nothing else, exactly as the memory builders above are.
# A value outside a vocabulary is left as it arrived so the command reports it
# under its own field name; converting here would need a second copy of each
# vocabulary's error mapping, and refusing here would report the wrong field for
# a payload that got two things wrong.

#: The entity times a caller may supply, and the field each is reported under
#: when it is not a moment. Separate from `_MEMORY_MOMENTS` because the two
#: planes carry different fields, and one shared mapping would convert a key on
#: a command that has no such field.
_ENTITY_MOMENTS: Mapping[str, SafeDetail] = MappingProxyType(
    {
        "effective_from": SafeDetail.EFFECTIVE_FROM,
        "effective_to": SafeDetail.EFFECTIVE_TO,
    }
)

#: Which closed vocabulary each scalar entity field belongs to.
_ENTITY_VOCABULARIES: Mapping[str, type[StrEnum]] = MappingProxyType(
    {
        "entity_type": EntityType,
        "status": EntityStatus,
        "namespace": CallerNamespace,
        "alias_type": AliasType,
    }
)

#: Which closed vocabulary each list-valued entity filter belongs to. `states`
#: is in neither mapping and is resolved per command, because the identifier and
#: alias planes declare separate state vocabularies -- deliberately separate, so
#: that widening one cannot silently widen the other -- and a single entry here
#: would convert an alias state against the identifier's set.
_ENTITY_FILTERS: Mapping[str, type[StrEnum]] = MappingProxyType(
    {
        "namespaces": ExternalIdentifierNamespace,
        "alias_types": AliasType,
    }
)

#: Fields whose JSON array becomes a tuple, with no per-item conversion.
_ENTITY_SEQUENCES = ("evidence", "aliases", "identifiers")


def _entity_moments(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve an entity write's optional times from RFC 3339 strings to datetimes."""
    converted = dict(payload)
    for name, detail in _ENTITY_MOMENTS.items():
        supplied = converted.get(name)
        if supplied is None:
            continue
        if not isinstance(supplied, str):
            raise InvalidRequestError(detail)
        try:
            converted[name] = datetime.fromisoformat(supplied)
        except ValueError:
            pass
        else:
            continue
        # Outside the handler: the original renders the rejected value.
        raise InvalidRequestError(detail)
    return converted


def _entity_member(value: object, vocabulary: type[StrEnum]) -> object:
    """One vocabulary string as its member, or exactly what arrived."""
    if not isinstance(value, str):
        return value
    try:
        return vocabulary(value)
    except ValueError:
        return value


def _entity_vocabulary(
    payload: dict[str, Any], states: type[StrEnum] | None = None
) -> dict[str, Any]:
    """Closed-vocabulary strings as the enum members the entity commands declare."""
    for name, vocabulary in _ENTITY_VOCABULARIES.items():
        if name in payload:
            payload[name] = _entity_member(payload[name], vocabulary)
    filters = dict(_ENTITY_FILTERS)
    if states is not None:
        filters["states"] = states
    for name, vocabulary in filters.items():
        supplied = payload.get(name)
        if isinstance(supplied, list):
            payload[name] = tuple(_entity_member(entry, vocabulary) for entry in supplied)
    for name in _ENTITY_SEQUENCES:
        supplied = payload.get(name)
        if isinstance(supplied, list):
            payload[name] = tuple(supplied)
    return payload


def _list_entity_identifiers(payload: Mapping[str, Any]) -> Command:
    return ListEntityIdentifiers(**_entity_vocabulary(dict(payload), IdentifierState))


def _list_entity_aliases(payload: Mapping[str, Any]) -> Command:
    return ListEntityAliases(**_entity_vocabulary(dict(payload), AliasState))


def _create_entity(payload: Mapping[str, Any]) -> Command:
    return CreateEntity(**_entity_vocabulary(dict(payload)))


def _update_entity(payload: Mapping[str, Any]) -> Command:
    return UpdateEntity(**_entity_vocabulary(dict(payload)))


def _archive_entity(payload: Mapping[str, Any]) -> Command:
    return ArchiveEntity(**payload)


def _restore_entity(payload: Mapping[str, Any]) -> Command:
    return RestoreEntity(**payload)


def _bind_entity_identifier(payload: Mapping[str, Any]) -> Command:
    return BindEntityIdentifier(**_entity_vocabulary(_entity_moments(payload)))


def _retire_entity_identifier(payload: Mapping[str, Any]) -> Command:
    return RetireEntityIdentifier(**payload)


def _supersede_entity_identifier(payload: Mapping[str, Any]) -> Command:
    return SupersedeEntityIdentifier(**_entity_vocabulary(_entity_moments(payload)))


def _add_entity_alias(payload: Mapping[str, Any]) -> Command:
    return AddEntityAlias(**_entity_vocabulary(_entity_moments(payload)))


def _retire_entity_alias(payload: Mapping[str, Any]) -> Command:
    return RetireEntityAlias(**payload)


def _supersede_entity_alias(payload: Mapping[str, Any]) -> Command:
    return SupersedeEntityAlias(**_entity_vocabulary(_entity_moments(payload)))


def _get_goodnotes_content(payload: Mapping[str, Any]) -> Command:
    if "path" in payload or "principal_id" in payload:
        raise InvalidRequestError(SafeDetail.RUN_ID)
    return GetGoodNotesContent(**payload)


def _enum_or_invalid[T](value: object, enum: type[T], detail: SafeDetail) -> T:
    if isinstance(value, enum):
        return value
    if not isinstance(value, str):
        raise InvalidRequestError(detail)
    try:
        return enum(value)  # type: ignore[call-arg]
    except ValueError:
        raise InvalidRequestError(detail) from None


def _begin_intelligence_cycle(payload: Mapping[str, Any]) -> Command:
    return BeginIntelligenceCycle(**payload)


def _commit_intelligence_artifact(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    converted["stage"] = _enum_or_invalid(
        converted.get("stage"), IntelligenceStage, SafeDetail.STAGE
    )
    converted["artifact_kind"] = _enum_or_invalid(
        converted.get("artifact_kind"), ArtifactKind, SafeDetail.ARTIFACT_KIND
    )
    converted["artifact_state"] = _enum_or_invalid(
        converted.get("artifact_state"), ArtifactState, SafeDetail.SELECTOR
    )
    if converted.get("focus_area_id") is not None:
        converted["focus_area_id"] = _enum_or_invalid(
            converted["focus_area_id"], FocusAreaId, SafeDetail.FOCUS_AREA_ID
        )
    if converted.get("source_lane") is not None:
        converted["source_lane"] = _enum_or_invalid(
            converted["source_lane"], SourceLaneId, SafeDetail.SOURCE_LANE
        )
    if "dependency_report_ids" in converted:
        named = converted["dependency_report_ids"]
        if not isinstance(named, list):
            raise InvalidRequestError(SafeDetail.DEPENDENCY_REPORT_IDS)
        converted["dependency_report_ids"] = tuple(named)
    if "provenance" in converted:
        named = converted["provenance"]
        if not isinstance(named, list):
            raise InvalidRequestError(SafeDetail.PROVENANCE)
        converted["provenance"] = tuple(named)
    _task_moment(converted, "coverage_start", SafeDetail.SCHEDULED_AT)
    _task_moment(converted, "coverage_end", SafeDetail.DEFERRED_UNTIL)
    return CommitIntelligenceArtifact(**converted)


def _record_intelligence_run_state(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    converted["stage"] = _enum_or_invalid(
        converted.get("stage"), IntelligenceStage, SafeDetail.STAGE
    )
    converted["artifact_kind"] = _enum_or_invalid(
        converted.get("artifact_kind"), ArtifactKind, SafeDetail.ARTIFACT_KIND
    )
    converted["state"] = _enum_or_invalid(
        converted.get("state"), ProducerRunState, SafeDetail.SELECTOR
    )
    if converted.get("focus_area_id") is not None:
        converted["focus_area_id"] = _enum_or_invalid(
            converted["focus_area_id"], FocusAreaId, SafeDetail.FOCUS_AREA_ID
        )
    if converted.get("source_lane") is not None:
        converted["source_lane"] = _enum_or_invalid(
            converted["source_lane"], SourceLaneId, SafeDetail.SOURCE_LANE
        )
    return RecordIntelligenceRunState(**converted)


def _read_intelligence_artifact(payload: Mapping[str, Any]) -> Command:
    return ReadIntelligenceArtifact(**payload)


def _latest_intelligence_artifact(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    if converted.get("stage") is not None:
        converted["stage"] = _enum_or_invalid(
            converted["stage"], IntelligenceStage, SafeDetail.STAGE
        )
    if converted.get("artifact_kind") is not None:
        converted["artifact_kind"] = _enum_or_invalid(
            converted["artifact_kind"], ArtifactKind, SafeDetail.ARTIFACT_KIND
        )
    if converted.get("focus_area_id") is not None:
        converted["focus_area_id"] = _enum_or_invalid(
            converted["focus_area_id"], FocusAreaId, SafeDetail.FOCUS_AREA_ID
        )
    if converted.get("source_lane") is not None:
        converted["source_lane"] = _enum_or_invalid(
            converted["source_lane"], SourceLaneId, SafeDetail.SOURCE_LANE
        )
    return GetLatestIntelligenceArtifact(**converted)


def _list_intelligence_artifacts(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    if converted.get("stage") is not None:
        converted["stage"] = _enum_or_invalid(
            converted["stage"], IntelligenceStage, SafeDetail.STAGE
        )
    if converted.get("artifact_kind") is not None:
        converted["artifact_kind"] = _enum_or_invalid(
            converted["artifact_kind"], ArtifactKind, SafeDetail.ARTIFACT_KIND
        )
    if converted.get("focus_area_id") is not None:
        converted["focus_area_id"] = _enum_or_invalid(
            converted["focus_area_id"], FocusAreaId, SafeDetail.FOCUS_AREA_ID
        )
    if converted.get("source_lane") is not None:
        converted["source_lane"] = _enum_or_invalid(
            converted["source_lane"], SourceLaneId, SafeDetail.SOURCE_LANE
        )
    return ListIntelligenceArtifacts(**converted)


def _search_intelligence_artifacts(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    if converted.get("stage") is not None:
        converted["stage"] = _enum_or_invalid(
            converted["stage"], IntelligenceStage, SafeDetail.STAGE
        )
    if converted.get("artifact_kind") is not None:
        converted["artifact_kind"] = _enum_or_invalid(
            converted["artifact_kind"], ArtifactKind, SafeDetail.ARTIFACT_KIND
        )
    if converted.get("focus_area_id") is not None:
        converted["focus_area_id"] = _enum_or_invalid(
            converted["focus_area_id"], FocusAreaId, SafeDetail.FOCUS_AREA_ID
        )
    if converted.get("source_lane") is not None:
        converted["source_lane"] = _enum_or_invalid(
            converted["source_lane"], SourceLaneId, SafeDetail.SOURCE_LANE
        )
    return SearchIntelligenceArtifacts(**converted)


def _resolve_intelligence_set(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    converted["set_id"] = _enum_or_invalid(
        converted.get("set_id"), ResolverSetId, SafeDetail.SET_ID
    )
    if converted.get("focus_area_id") is not None:
        converted["focus_area_id"] = _enum_or_invalid(
            converted["focus_area_id"], FocusAreaId, SafeDetail.FOCUS_AREA_ID
        )
    return ResolveIntelligenceSet(**converted)


def _submit_goodnotes_proposal(payload: Mapping[str, Any]) -> Command:
    """`goodnotes.propose`, with JSON arrays converted to the tuples the command holds."""
    converted = dict(payload)
    if "segments" in converted:
        named = converted["segments"]
        if not isinstance(named, list):
            raise InvalidRequestError(SafeDetail.SEGMENTS)
        converted["segments"] = tuple(named)
    if "candidate_tags" in converted:
        converted["candidate_tags"] = _strings(
            converted["candidate_tags"], SafeDetail.CANDIDATE_TAGS
        )
    if "ranked_candidates" in converted:
        named = converted["ranked_candidates"]
        if not isinstance(named, list):
            raise InvalidRequestError(SafeDetail.RANKED_CANDIDATES)
        converted["ranked_candidates"] = tuple(named)
    return SubmitGoodNotesProposal(**converted)


def _managed_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Decode a managed write's base64 `content` into the bytes the command holds.

    Shape conversion, exactly like `_moments` and `_fetch_source`'s
    representation: JSON has no byte string, the wire form is base64 — which is
    what `adapters.mcp.tools` publishes as this field's `contentEncoding` — and
    the command refuses anything that is not `bytes`. So a caller's text would
    otherwise be rejected for being a string rather than for not decoding.

    `validate=True` is not decoration. Without it `b64decode` silently discards
    every character outside the alphabet, so `"aGV<>sbG8="` and `"aGVsbG8="`
    decode to the same bytes and a corrupted body is stored as if it were the
    one the caller sent. Refused rather than repaired.

    An absent key is left absent so the command's own constructor reports the
    missing required field, and a non-string is left alone for the same reason:
    two refusals for one fault would be two different tokens for one mistake.
    """
    converted = dict(payload)
    supplied = converted.get("content")
    if not isinstance(supplied, str):
        return converted
    try:
        converted["content"] = b64decode(supplied, validate=True)
    except (BinasciiError, ValueError):
        pass
    else:
        return converted
    # Outside the handler: the original renders the rejected value.
    raise InvalidRequestError(SafeDetail.CONTENT)


def _create_managed_document(payload: Mapping[str, Any]) -> Command:
    return CreateManagedDocument(**_managed_content(payload))


def _revise_managed_document(payload: Mapping[str, Any]) -> Command:
    return ReviseManagedDocument(**_managed_content(payload))


def _read_managed_document(payload: Mapping[str, Any]) -> Command:
    return ReadManagedDocument(**payload)


def _list_managed_documents(payload: Mapping[str, Any]) -> Command:
    return ListManagedDocuments(**payload)


def _archive_managed_document(payload: Mapping[str, Any]) -> Command:
    return ArchiveManagedDocument(**payload)


def _restore_managed_document(payload: Mapping[str, Any]) -> Command:
    return RestoreManagedDocument(**payload)


def _decide_review_case(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    named = converted.get("disposition")
    if isinstance(named, str):
        try:
            converted["disposition"] = Disposition(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.DISPOSITION) from None
    return DecideReviewCase(**converted)


#: One builder per command owned by these legacy transports. WP-12C adds a
#: distinct authenticated native-host boundary; its capabilities are valid
#: audit vocabulary but remain intentionally absent here until WP-12G owns the
#: gateway/UI route. The Command union and this mapping stay equal, so absence
#: is explicit rather than a half-wired route.
_BUILDERS: Mapping[Capability, Callable[[Mapping[str, Any]], Command]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: _get_capabilities,
        Capability.SOURCES_LIST: _list_sources,
        Capability.SOURCES_METADATA: _get_source_metadata,
        Capability.SOURCES_FETCH: _fetch_source,
        Capability.SOURCES_STATUS: _get_source_status,
        Capability.SOURCES_ENROLL: _enroll_source,
        Capability.KNOWLEDGE_SEARCH: _search_knowledge,
        Capability.KNOWLEDGE_READ: _read_knowledge,
        Capability.KNOWLEDGE_REVEAL: _reveal_subject,
        Capability.CAPTURE_CREATE: _create_capture,
        Capability.CAPTURE_REVISE: _revise_capture,
        Capability.CAPTURE_READ: _read_capture,
        Capability.CAPTURE_LIST: _list_captures,
        Capability.CAPTURE_SEARCH: _search_captures,
        Capability.REVIEW_LIST: _list_review_cases,
        Capability.REVIEW_DECIDE: _decide_review_case,
        Capability.CONTINUITY_PULSE: _get_pulse,
        Capability.CONTINUITY_SITUATIONS: _list_situations,
        Capability.CONTINUITY_PROJECTS: _list_projects,
        Capability.CONTINUITY_PROJECTS_CREATE: _create_project,
        Capability.CONTINUITY_SITUATIONS_CREATE: _create_situation,
        Capability.CONTINUITY_TASKS_CREATE: _record_task,
        Capability.KNOWLEDGE_COVERAGE: _get_corpus_coverage,
        Capability.DOCUMENTS_CREATE: _create_managed_document,
        Capability.DOCUMENTS_REVISE: _revise_managed_document,
        Capability.DOCUMENTS_READ: _read_managed_document,
        Capability.DOCUMENTS_LIST: _list_managed_documents,
        Capability.DOCUMENTS_ARCHIVE: _archive_managed_document,
        Capability.DOCUMENTS_RESTORE: _restore_managed_document,
        Capability.TASKS_READ: _read_task,
        Capability.TASKS_LIST: _list_tasks,
        Capability.TASKS_SEARCH: _search_tasks,
        Capability.TASKS_HISTORY: _get_task_history,
        Capability.TASKS_CREATE: _create_task,
        Capability.TASKS_UPDATE: _update_task,
        Capability.TASKS_TRANSITION: _transition_task,
        Capability.TASKS_BULK_PREVIEW: _bulk_preview_tasks,
        Capability.TASKS_BULK_CONFIRM: _bulk_confirm_tasks,
        Capability.COMMITMENTS_READ: _read_commitment,
        Capability.COMMITMENTS_LIST: _list_commitments,
        Capability.COMMITMENTS_SEARCH: _search_commitments,
        Capability.COMMITMENTS_HISTORY: _get_commitment_history,
        Capability.COMMITMENTS_WAITING_ON: _waiting_on,
        Capability.COMMITMENTS_CREATE: _create_commitment,
        Capability.COMMITMENTS_UPDATE: _update_commitment,
        Capability.COMMITMENTS_CLOSE: _close_commitment,
        Capability.CONTEXT_PREPARE: _prepare_context,
        Capability.CONTEXT_FEEDBACK: _record_context_feedback,
        Capability.GOODNOTES_WORK: _get_goodnotes_work,
        Capability.GOODNOTES_CONTENT: _get_goodnotes_content,
        Capability.GOODNOTES_PROPOSE: _submit_goodnotes_proposal,
        Capability.GSQS_START: _start_gsqs_b0,
        Capability.GSQS_STATUS: _get_gsqs_b0_status,
        Capability.REPORTS_BEGIN_CYCLE: _begin_intelligence_cycle,
        Capability.REPORTS_COMMIT: _commit_intelligence_artifact,
        Capability.REPORTS_RECORD_RUN_STATE: _record_intelligence_run_state,
        Capability.REPORTS_READ: _read_intelligence_artifact,
        Capability.REPORTS_LATEST: _latest_intelligence_artifact,
        Capability.REPORTS_LIST: _list_intelligence_artifacts,
        Capability.REPORTS_SEARCH: _search_intelligence_artifacts,
        Capability.REPORTS_RESOLVE_SET: _resolve_intelligence_set,
        Capability.ENTITIES_SEARCH: _search_entities,
        Capability.ENTITIES_GET: _get_entity,
        Capability.ENTITIES_RESOLVE: _resolve_entity,
        Capability.ENTITIES_CONTEXT: _get_entity_context,
        Capability.ENTITIES_RELATIONSHIPS: _get_entity_relationships,
        Capability.ENTITIES_UNRESOLVED_MENTIONS: _list_unresolved_mentions,
        Capability.ENTITIES_IDENTIFIERS_LIST: _list_entity_identifiers,
        Capability.ENTITIES_ALIASES_LIST: _list_entity_aliases,
        Capability.ENTITIES_CREATE: _create_entity,
        Capability.ENTITIES_UPDATE: _update_entity,
        Capability.ENTITIES_ARCHIVE: _archive_entity,
        Capability.ENTITIES_RESTORE: _restore_entity,
        Capability.ENTITIES_IDENTIFIERS_BIND: _bind_entity_identifier,
        Capability.ENTITIES_IDENTIFIERS_RETIRE: _retire_entity_identifier,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE: _supersede_entity_identifier,
        Capability.ENTITIES_ALIASES_ADD: _add_entity_alias,
        Capability.ENTITIES_ALIASES_RETIRE: _retire_entity_alias,
        Capability.ENTITIES_ALIASES_SUPERSEDE: _supersede_entity_alias,
        Capability.ENTITIES_ASSIGNMENTS_LIST: _list_entity_assignments,
        Capability.ENTITIES_ASSIGNMENTS_CREATE: _create_entity_assignment,
        Capability.ENTITIES_ASSIGNMENTS_REVISE: _revise_entity_assignment,
        Capability.ENTITIES_ASSIGNMENTS_END: _end_entity_assignment,
        Capability.ENTITIES_RELATIONSHIPS_CREATE: _create_entity_relationship,
        Capability.ENTITIES_RELATIONSHIPS_REVISE: _revise_entity_relationship,
        Capability.ENTITIES_RELATIONSHIPS_END: _end_entity_relationship,
        Capability.ENTITIES_OBSERVATIONS_LIST: _list_entity_observations,
        Capability.ENTITIES_OBSERVE: _observe_entity_mention,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE: _resolve_unresolved_mention,
        Capability.RELATIONSHIP_MEMORY_CREATE: _create_relationship_memory,
        Capability.RELATIONSHIP_MEMORY_GET: _get_relationship_memory,
        Capability.RELATIONSHIP_MEMORY_LIST: _list_relationship_memories,
        Capability.RELATIONSHIP_MEMORY_SEARCH: _search_relationship_memories,
        Capability.RELATIONSHIP_MEMORY_HISTORY: _get_relationship_memory_history,
        Capability.RELATIONSHIP_MEMORY_REVISE: _revise_relationship_memory,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE: _archive_relationship_memory,
        Capability.RELATIONSHIP_MEMORY_RESTORE: _restore_relationship_memory,
    }
)


def _named(capability: str) -> Capability:
    """The capability this request names, or a refusal.

    An unknown name is `invalid_request` and not `unsupported`: `unsupported`
    says this build does not serve a capability that exists, and a name that is
            not one of the ninety-seven names nothing.
    """
    try:
        return Capability(capability)
    except ValueError:
        try:
            NativeSourceCapability(capability)
        except ValueError:
            pass
        else:
            raise UnsupportedError() from None
    raise InvalidRequestError()


def _metadata(capability: Capability, arguments: Mapping[str, Any]) -> RequestMetadata:
    """The common envelope, built by the contract model that owns its rules.

    The capability comes from the transport's own routing rather than from the
    document, so the two cannot disagree. A document that names it anyway is
    refused — `RequestMetadata` would receive the argument twice — rather than
    accepted with one of the two winning silently.
    """
    fields = {name: value for name, value in arguments.items() if name != PAYLOAD_KEY}
    try:
        return RequestMetadata(capability=capability, **fields)
    except (TypeError, ValueError):
        # `ValidationError` is a `ValueError`. Caught together because the two
        # say the same thing here: the envelope the caller sent is not one.
        pass
    # Raised outside the handler, as everywhere else in this repository: the
    # original renders the rejected input, and leaving the handler first is what
    # actually clears `__context__`.
    raise InvalidRequestError()


def _command(capability: Capability, payload: Mapping[str, Any]) -> Command:
    """The command for `capability`, built from the caller's payload.

    A `TypeError` is the constructor saying the payload named a field the
    command does not have, or omitted one it requires, or was not an object at
    all. All three are `invalid_request`, and none of them may escape as a crash.
    """
    build = _BUILDERS.get(capability)
    if build is None:
        # A known capability with no command on this transport is unsupported,
        # not malformed and never an internal KeyError.
        raise UnsupportedError()
    try:
        return build(payload)
    except TypeError:
        pass
    raise InvalidRequestError()


def normalize(capability: str, arguments: Mapping[str, Any]) -> tuple[RequestMetadata, Command]:
    """Build the request pair `ApplicationService.invoke` takes, or refuse.

    `capability` is the name the transport routed on — an HTTP path segment, an
    MCP tool name. `arguments` is the document beside it: the common metadata
    fields, and the capability's own fields under `payload`.

    Raises `InvalidRequestError` and nothing else. Every other outcome is the
    application's to decide, including whether the request is allowed.
    """
    named = _named(capability)
    payload = arguments.get(PAYLOAD_KEY, {})
    if not isinstance(payload, Mapping):
        raise InvalidRequestError()
    return _metadata(named, arguments), _command(named, payload)
