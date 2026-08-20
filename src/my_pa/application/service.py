"""Every capability, behind one authorization and one transaction.

`ApplicationService` has exactly one public method. That is the whole design.
A use case cannot be reached without going through `invoke`, `invoke` cannot
reach a use case without going through `authorize`, and there is no second door
— no per-capability entry point, no "internal" variant that skips the check, and
no handler a caller holds a reference to. Bypassing the authorization path is
therefore not something a use case is trusted not to do; it is something the
shape of this class does not offer.

**The transaction is opened once, around the decision and the work.** Leaving
`invoke`'s `with` block normally commits, which matters most on the paths that
look least like they need a transaction: a refusal returns out of the block
normally, so the audit event recording it commits, where raising from inside
would have rolled the record of the refusal back along with everything else.

**Which outcomes leave a durable trace.** An incomplete disclosure of an audit
gap is itself a gap, and this list has been wrong twice — once by omitting the
capability mismatch, and once by omitting case 5 while claiming to be complete.
So it is derived rather than surveyed, and the derivation itself changed when
WP-4B1 gave the audit its own transaction (`D-34`).

`AuditSink.record` has exactly two call sites in this layer,
`authorization.authorize` and the mismatch branch of `_run`. Both are still
reached from inside the transaction `_run` opens, and neither is written by it:
the durable sink commits the event on its own connection before returning, so
whether an audit survives no longer depends on how the work transaction ended.
Every outcome is therefore some combination of two facts — was `record`
reached, and did `record` itself succeed — and the list below is closed because
those two facts have no third value, not because seven cases is where the
searching stopped.

1. *Policy denied the request.* Recorded and durable. The reason is in the record
   and never in the answer.
2. *The declared capability and the payload's capability disagree.* A
   security-relevant refusal — it is the guard against a request authorized as
   one capability and executed as another — so it is recorded as `failed` and
   durable. `failed` rather than `denied` because no policy decision was reached:
   there is nothing to name a `DenialReason` from, and inventing one would
   misreport why the request stopped.
3. *Allowed, and the handler succeeded.* Recorded as allowed and durable; the
   work commits after it.
4. *Allowed, and the handler then failed.* Recorded as allowed and **still
   durable**, because the event was committed before the handler ran and the
   rollback that discards the half-written work cannot reach it. This is the
   asymmetry WP-4B1 closed. What the record claims is that the request was
   authorized, which is true whether or not the work landed; it does not claim
   the work committed, and no second event is written to say that it did not —
   the job plane and `sources.status` are where that is recorded.
5. *A failure before any decision was reached.* A port failure in `authorize`'s
   own reads — `for_principal`, or the operation and object lookups that resolve
   a status request's scope — raises before `record` is called, and the unit of
   work may also fail to open at all. Nothing is recorded, and nothing is
   missing: no decision existed to record.
6. *The audit itself could not be persisted.* Nothing is recorded, and the
   request **fails closed**: `record` raises, the exception leaves the `with`
   block so the work rolls back, and `invoke` answers with an error. This is the
   case that separates the new design from the old one — a decision was reached
   and its record was lost, and the only correct response is to refuse the
   request rather than to complete it unrecorded
   (`module-boundaries.md` section 5.6). It is `_run`'s only path where a request
   that policy allowed still fails without the handler being at fault.
7. *A command that could not be constructed at all.* Not recorded, and cannot be:
   a malformed command is refused by its own `__post_init__` before `invoke` is
   called, so this layer never sees the attempt. Whatever calls it is the only
   thing that could record one.

**No code in this class changed to achieve that**, and the reason is worth
stating rather than leaving as an absence. Durability is a property of the sink's
transaction, which this layer is deliberately unable to see; fail-closed is a
property of not catching what `record` raises, which this layer already did. What
changed is which implementation a composition root supplies, and the enumeration
above, which was describing the old one.

**Provider reads happen inside that transaction.** `module-boundaries.md`
section 10 says long source fetches are not held inside database transactions,
and the reading here is bounded by `max_fetch_bytes` against a local filesystem
adapter — the rule's target is the worker's extraction path, which this package
does not own. What is gained is that the coverage a disclosure states and the
bytes the same response returns come from one consistent read. Should a provider
ever be remote, this is the sentence that has to change first.

`_enumerate` is a *new caller* of that decision and not a reopening of it, and it
is said here rather than left to be discovered in review. It reads no bytes —
`iterdir` and `stat`, bounded by the enrollment's own `max_items` — so it is
strictly cheaper than `sources.fetch`, which already runs inside the transaction
under the same decision. It has to be inside: the identifiers it records are
issued by a provider bound to this connection, so an enrollment that rolls back
must issue none, and the enumerated set has to commit with the acceptance it
measures or the two can disagree.

**Nothing here decides what is authorized.** The handlers receive an
`Authorization`, not a `Principal`; there is no `is_operator` to consult, no
scope to widen, and the enrollments were loaded once by the shared path. What a
handler decides is what a *result* is, which is a different question.

**Every limit enforced here is the limit published by `capabilities.get`.**
`_effective_limits` builds one `EffectiveLimits` from validated configuration
and the domain's own ceilings, and that single object is what the manifest
publishes and what every clamp below reads. There is no second copy to drift
(`D-24`).
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from types import MappingProxyType
from typing import Any, Final, assert_never

from my_pa.application.authorization import Authorization, authorize
from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.application.commands import (
    ArchiveManagedDocument,
    ArchiveManagedDocumentCommand,
    BulkConfirmTasks,
    BulkPreviewTasks,
    CloseCommitment,
    Command,
    CreateCapture,
    CreateCommitment,
    CreateManagedDocument,
    CreateManagedDocumentCommand,
    CreateProject,
    CreateSituation,
    CreateTask,
    DecideReviewCase,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetCorpusCoverage,
    GetEntity,
    GetEntityContext,
    GetEntityRelationships,
    GetGoodNotesContent,
    GetGoodNotesWork,
    GetPulse,
    GetSourceMetadata,
    GetSourceStatus,
    GetTaskHistory,
    ListCaptures,
    ListCommitments,
    ListManagedDocuments,
    ListManagedDocumentsCommand,
    ListProjects,
    ListReviewCases,
    ListSituations,
    ListSources,
    ListTasks,
    ListUnresolvedMentions,
    PrepareContext,
    ReadCapture,
    ReadCommitment,
    ReadKnowledge,
    ReadManagedDocument,
    ReadManagedDocumentCommand,
    ReadTask,
    RecordContextFeedback,
    RecordTask,
    Representation,
    ResolveEntity,
    RestoreManagedDocument,
    RestoreManagedDocumentCommand,
    RevealSubject,
    ReviseCapture,
    ReviseManagedDocument,
    ReviseManagedDocumentCommand,
    SearchCaptures,
    SearchEntities,
    SearchKnowledge,
    SearchTasks,
    SubmitGoodNotesProposal,
    TransitionTask,
    UpdateTask,
    WaitingOn,
)
from my_pa.application.commitments import CommitmentManagementService
from my_pa.application.context import ContextPreparationService
from my_pa.application.disclosure import (
    Limitation,
    corpus_disclosure,
    disclosure_for,
    unavailable_disclosure,
    unenrolled_disclosure,
    with_corpus_caveat,
)
from my_pa.application.entity_context import EntityContextService
from my_pa.application.entity_resolution import (
    ACTIVE_ASSIGNMENT_STATUS,
    ACTIVE_RELATIONSHIP_STATE,
    EntityResolutionService,
    ResolutionRequest,
    is_in_force,
)
from my_pa.application.errors import (
    AmbiguousRequestError,
    ApplicationError,
    ConflictError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    QuarantinedError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
    problem_detail,
)
from my_pa.application.goodnotes_content import content_payload, lookup_content
from my_pa.application.goodnotes_semantics import (
    lookup_work,
    proposal_payload,
    submit_proposal,
    work_payload,
)
from my_pa.application.managed_documents import ManagedDocumentService
from my_pa.application.model_gate import BoundedModelGate
from my_pa.application.tasks import TaskManagementService
from my_pa.contracts.ports import (
    Acceptance,
    AuthoringConflictError,
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureSearchOutcome,
    CaptureSearchRequest,
    EntitySummary,
    EvidenceUnavailableError,
    ManagedByteStore,
    PortError,
    PreferenceConflictError,
    ReviewDecisionRequest,
    SearchOutcome,
    UnitOfWork,
    UnknownScopeError,
)
from my_pa.contracts.v1.capabilities import EffectiveLimits, ReadinessReport, ReadinessState
from my_pa.contracts.v1.capture import CaptureListEntry, CaptureReceiptView, CaptureVersionView
from my_pa.contracts.v1.commitments import CommitmentListEntry, CommitmentView, WaitingOnEntry
from my_pa.contracts.v1.disclosure import Disclosure, SourceReference, Truncation
from my_pa.contracts.v1.documents import (
    ManagedDocumentListEntry,
    ManagedDocumentReceiptView,
    ManagedDocumentVersionView,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.reveal import RevealView
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.contracts.v1.tasks import TaskHistoryEntryView, TaskListEntry, TaskView
from my_pa.domain.audit.events import AuditEvent, AuditOutcome
from my_pa.domain.capture.errors import (
    CaptureBoundsError,
    CaptureConflictError,
    CaptureError,
    EmptyCaptureError,
)
from my_pa.domain.capture.reveal import EvidenceState
from my_pa.domain.capture.review import (
    ReviewCase,
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewUnsupportedError,
)
from my_pa.domain.capture.submission import CaptureKind, CaptureTransport
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.common.time import format_rfc3339, utc_now
from my_pa.domain.documents.managed import (
    DocumentState,
    ManagedDocumentConflictError,
    ManagedDocumentError,
    ManagedDocumentReceipt,
    MediaTypeNotManagedError,
    StaleExpectedVersionError,
    UnmanageableTitleError,
)
from my_pa.domain.extraction.coverage import CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus, extract_text
from my_pa.domain.goodnotes.models import GoodNotesReviewCase
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION
from my_pa.domain.relationship.context_card import EntityContextCard
from my_pa.domain.relationship.entity import (
    Assignment,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.governance import EntityObservation
from my_pa.domain.relationship.resolution import EntityResolution
from my_pa.domain.search.query import (
    DEFAULT_SNIPPET_WORDS,
    MAX_PAGE_SIZE,
    EmptySearchQueryError,
    SearchCursorError,
    SearchQuery,
    SearchQueryError,
    SearchRequest,
    label_for_media_type,
)
from my_pa.domain.situation.situation import Project, Situation
from my_pa.domain.source.enrollment import (
    MAX_ENROLLMENT_BYTES,
    MAX_ENROLLMENT_DEPTH,
    MAX_ENROLLMENT_ITEMS,
    Enrollment,
    EnrollmentBoundsError,
    EnrollmentConflictError,
    EnrollmentRequest,
    EnrollmentScope,
)
from my_pa.domain.source.provider import (
    ENUMERABLE_KINDS,
    ObjectKind,
    ProviderError,
    SourceObject,
    SourceProvider,
    TraversalDeniedError,
    VersionChangedError,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.history import TaskHistoryEntry as TaskManagementHistoryEntry
from my_pa.domain.task.task import Task as TaskManagementTask

__all__ = ["ApplicationService"]

#: The absence of truncation, as one shared immutable value. A default argument
#: may not be a constructor call, and a frozen contract model is safe to share.
_NO_TRUNCATION: Final = Truncation()


@dataclass(frozen=True, slots=True)
class _Result:
    """One capability's payload and the envelope that must accompany it."""

    payload: dict[str, Any]
    disclosure: Disclosure


def _review_case_payload(case: ReviewCase | GoodNotesReviewCase) -> dict[str, Any]:
    common = {
        "review_case_id": case.review_case_id,
        "proposal_id": case.proposal_id,
        "proposal_state": case.proposal_state.value,
        "risk_class": case.risk_class.value,
        "opened_at": format_rfc3339(case.opened_at),
        "review_version": case.review_version,
        "latest_disposition": (
            None if case.latest_disposition is None else case.latest_disposition.value
        ),
    }
    if isinstance(case, GoodNotesReviewCase):
        return {
            **common,
            "subject_kind": "goodnotes_region",
            "region_id": case.region_id,
            "page_version_id": case.page_version_id,
            "confidence": case.confidence,
        }
    return {
        **common,
        "subject_kind": "capture_proposal",
        "capture_id": case.capture_id,
        "version_id": case.version_id,
        "proposal_type": case.proposal_type.value,
    }


def _effective_limits(configured: EffectiveLimits) -> EffectiveLimits:
    """The limits that will actually be enforced, which are the ones published.

    Configuration cannot raise a bound the domain already fixes: a page size
    above `domain.search.query.MAX_PAGE_SIZE` would be published and then not
    honoured by `knowledge.search`, and an enrollment depth above
    `domain.source.enrollment.MAX_ENROLLMENT_DEPTH` would be published and then
    refused by the value object that enforces it. Taking the smaller of the two
    here is what keeps the published number equal to the enforced one, in the
    one direction that cannot be wrong (`D-24`).
    """
    max_page_size = min(configured.max_page_size, MAX_PAGE_SIZE)
    return EffectiveLimits(
        max_page_size=max_page_size,
        default_page_size=min(configured.default_page_size, max_page_size),
        max_fetch_bytes=configured.max_fetch_bytes,
        max_enrollment_depth=min(configured.max_enrollment_depth, MAX_ENROLLMENT_DEPTH),
    )


def _observed(source_object: SourceObject) -> dict[str, Any]:
    """One object as the contract may disclose it: opaque, and with no locator."""
    return {
        "source_object_id": source_object.source_object_id,
        "version_id": source_object.version_id,
        "kind": source_object.kind.value,
        "media_type": source_object.media_type,
        "size_bytes": source_object.size_bytes,
        "modified_at": format_rfc3339(source_object.modified_at),
    }


def _reference(source_object: SourceObject) -> SourceReference:
    return SourceReference(
        source_id=source_object.source_id,
        source_object_id=source_object.source_object_id,
        version_id=source_object.version_id,
    )


def _state_of_coverage(state: CoverageState) -> SourceStatusState:
    """The public status a coverage state implies.

    Written out exhaustively rather than with a fallback, because a fallback is
    how a newly added coverage state would silently be reported as something it
    is not. `assert_never` makes that a type error instead.
    """
    match state:
        case CoverageState.NOT_ENROLLED:
            return SourceStatusState.CONFIGURED
        case CoverageState.ELIGIBLE:
            return SourceStatusState.ACCEPTED
        case CoverageState.QUEUED:
            return SourceStatusState.QUEUED
        case CoverageState.PROCESSED:
            return SourceStatusState.COMPLETE_FOR_SCOPE
        case CoverageState.PARTIALLY_PROCESSED | CoverageState.STALE | CoverageState.SUPERSEDED:
            # All three say the answer is incomplete: one because outcomes are
            # mixed or outstanding, and two because the snapshot no longer
            # describes the source. None of them may report completion.
            return SourceStatusState.PARTIALLY_COMPLETE
        case CoverageState.QUARANTINED:
            return SourceStatusState.QUARANTINED
        case CoverageState.UNSUPPORTED:
            return SourceStatusState.UNSUPPORTED
        case CoverageState.UNAVAILABLE:
            return SourceStatusState.UNAVAILABLE
    assert_never(state)


def _state_of_outcome(outcome: ExtractionStatus | None) -> SourceStatusState:
    """The public status one object's stored outcome implies."""
    match outcome:
        case None:
            # Enrolled and no outcome recorded. `accepted` rather than
            # `complete_for_scope`, because nothing has happened to it yet.
            return SourceStatusState.ACCEPTED
        case ExtractionStatus.EXTRACTED:
            return SourceStatusState.COMPLETE_FOR_SCOPE
        case ExtractionStatus.UNSUPPORTED:
            return SourceStatusState.UNSUPPORTED
        case ExtractionStatus.QUARANTINED:
            return SourceStatusState.QUARANTINED
    assert_never(outcome)


def _port_failure(error: PortError) -> ApplicationError:
    """The public error a port failure is, by classification and nothing else."""
    if isinstance(error, UnknownScopeError):
        return NotFoundError(SafeDetail.ENROLLMENT_ID)
    if isinstance(error, EvidenceUnavailableError):
        return UnavailableError()
    return InternalError()


def _provider_failure(error: ProviderError) -> ApplicationError:
    """The public error a source-provider failure is.

    `docs/specs` section 10 puts these in three rows with three different retry
    answers, and `INV-PKL-007` forbids converting one into another — a refusal
    stays `denied`, a changed object stays `conflict`, and a shortage stays
    `unavailable`. The provider already refuses to distinguish "absent" from
    "outside the root" in its message, and giving both the same public code is
    what preserves that.
    """
    if isinstance(error, TraversalDeniedError):
        return DeniedError()
    if isinstance(error, VersionChangedError):
        return ConflictError(SafeDetail.SOURCE_OBJECT_ID)
    return UnavailableError(SafeDetail.SOURCE_OBJECT_ID)


#: What a capture answer's trust rests on. Not `source_provider` and not
#: `text_extractor`: nothing read a source and nothing derived anything.
#: `ADR-003` makes a user-authored record an authority in its own right, so the
#: level is `source_original` and the basis names the person who wrote it.
_CAPTURE_TRUST_BASIS: Final = ("user_authored",)

#: What a reveal's trust rests on. The stored rows and nothing else: every value
#: in the answer was read from `capture_spans`, `capture_proposals`,
#: `capture_review_decisions`, `capture_assertions` and
#: `capture_promotion_receipts`, and none of it was computed here. Naming
#: `stored_evidence_rows` rather than reusing `_CAPTURE_TRUST_BASIS` is the
#: difference between "the person wrote this" and "these are the rows that
#: record what was derived from what the person wrote".
_REVEAL_TRUST_BASIS: Final = ("stored_evidence_rows", "reviewed_promotion")

#: What a continuity answer rests on. `principal_partition` because every row was
#: selected under a `principal_id` predicate, and `accepted_continuity` because
#: the Pulse derivation additionally filters to `evidence_state = 'accepted'`. Two
#: named bases rather than one, so a reader can tell which claim is which.
_CONTINUITY_TRUST_BASIS: Final = ("principal_partition", "accepted_continuity")


def _authoring_digest(capability: str, fields: Mapping[str, object]) -> str:
    """Stable digest of the domain fields that make two writes the same write."""
    return hashlib.sha256(
        json.dumps(
            {"capability": capability, **fields},
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _capture_content(text: str) -> CaptureContent:
    """Build the domain value, reporting which field a refusal was about.

    The two refusals are different answers and are reported as such: an empty
    capture names the field, and one past the bound names the field and the
    bound. Neither message carries the text — the domain's own exceptions do not
    hold it, and the public error's details are closed tokens.
    """
    failure: ApplicationError | None = None
    try:
        return CaptureContent(text)
    except EmptyCaptureError:
        failure = InvalidRequestError(SafeDetail.TEXT)
    except CaptureBoundsError:
        failure = InvalidRequestError(SafeDetail.TEXT, SafeDetail.MAX_CAPTURE_CHARACTERS)
    except CaptureError:
        failure = InvalidRequestError(SafeDetail.TEXT)
    # Raised outside the handler so the original — whose traceback frames render
    # the value that was refused — is not left in `__context__`.
    raise failure


def _capture_version_view(version: CaptureVersion, *, is_current: bool) -> CaptureVersionView:
    """One stored version as the contract publishes it.

    `is_current` is passed in rather than read off the version, because there is
    no column that says so: the current version is the greatest version number
    the capture holds, and the use case is what has read both.
    """
    return CaptureVersionView(
        capture_id=version.capture_id,
        version_id=version.version_id,
        version_number=version.version_number,
        supersedes_version_id=version.supersedes_version_id,
        is_current=is_current,
        owner_principal_id=version.owner_principal_id,
        classification=version.classification,
        processing_policy=version.processing_policy.value,
        content_sha256=version.content.digest,
        character_count=version.content.character_count,
        text=version.content.text,
        client_created_at=version.client_created_at,
        server_received_at=version.server_received_at,
        occurred_at=version.occurred_at,
        accepted_at=version.accepted_at,
        recorded_at=version.recorded_at,
    )


def _task_view(task: TaskManagementTask) -> TaskView:
    """One task, in full, as `tasks.read` publishes it. No owner (WP-TM-03)."""
    return TaskView(
        task_id=task.task_id,
        title=task.title,
        description=task.description,
        lifecycle_state=task.lifecycle_state,
        evidence_state=task.evidence_state,
        version=task.version,
        priority=task.priority,
        due_at=task.due_at,
        scheduled_at=task.scheduled_at,
        deferred_until=task.deferred_until,
        archived_at=task.archived_at,
        project_id=task.project_id,
        situation_id=task.situation_id,
        recurrence_id=task.recurrence_id,
        opened_at=task.opened_at,
        closed_at=task.closed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        commitment_id=task.commitment_id,
        role=task.role.value if task.role is not None else None,
    )


def _task_list_entry(task: TaskManagementTask) -> TaskListEntry:
    """One task, as a page row, as `tasks.list`/`tasks.search` publish it."""
    return TaskListEntry(
        task_id=task.task_id,
        title=task.title,
        lifecycle_state=task.lifecycle_state,
        priority=task.priority,
        due_at=task.due_at,
        archived_at=task.archived_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _task_history_view(entry: TaskManagementHistoryEntry) -> TaskHistoryEntryView:
    """One mutation receipt, as `tasks.history` publishes it. No `client_context`."""
    return TaskHistoryEntryView(
        history_id=entry.history_id,
        task_id=entry.task_id,
        action=entry.action,
        actor=entry.actor,
        outcome=entry.outcome,
        before_version=entry.before_version,
        after_version=entry.after_version,
        occurred_at=entry.occurred_at,
        recorded_at=entry.recorded_at,
    )


def _commitment_view(commitment: Commitment) -> CommitmentView:
    return CommitmentView(
        commitment_id=commitment.commitment_id,
        principal_id=commitment.principal_id,
        direction=commitment.direction.value,
        state=commitment.state.value,
        counterparty_person_id=commitment.counterparty_person_id,
        title=commitment.summary,
        description=None,
        due_date=commitment.due_at.isoformat() if commitment.due_at is not None else None,
        created_at=commitment.created_at.isoformat(),
        updated_at=commitment.updated_at.isoformat(),
        version=commitment.version,
    )


def _commitment_list_entry(commitment: Commitment) -> CommitmentListEntry:
    return CommitmentListEntry(
        commitment_id=commitment.commitment_id,
        principal_id=commitment.principal_id,
        direction=commitment.direction.value,
        state=commitment.state.value,
        counterparty_person_id=commitment.counterparty_person_id,
        title=commitment.summary,
        description=None,
        due_date=commitment.due_at.isoformat() if commitment.due_at is not None else None,
        created_at=commitment.created_at.isoformat(),
        updated_at=commitment.updated_at.isoformat(),
        version=commitment.version,
    )


@contextmanager
def _translated() -> Iterator[None]:
    """Run a block, converting a port or provider failure into a public error.

    The `raise` is outside the `except` block, which is the same discipline the
    persistence and provider layers apply: `raise … from None` clears
    `__cause__` and leaves the original in `__context__`, where a rendered
    traceback would show whatever it carried. Leaving the handler first is what
    actually empties it.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except PortError as error:
        failure = _port_failure(error)
    except ProviderError as error:
        failure = _provider_failure(error)
    if failure is not None:
        raise failure


@contextmanager
def _managed_translated() -> Iterator[None]:
    """Run a managed-document call, classifying what WP-27's plane refuses.

    Inside `_translated`, deliberately, so this sees a `PortError` before that
    one turns it into the enrollment-shaped `not_found` every other capability
    wants. `UnknownScopeError` from the managed plane means "no such document in
    this partition", and reporting `enrollment_id` for it would name a field the
    request does not have.

    Three refusals, three public codes, and none of them is invented here: a
    stale expectation and a bound idempotency key are both `conflict` because
    the request contradicts state that already exists, and a document that
    exceeds a domain bound or carries nothing is `invalid_request`. **This is
    classification, not decision** — every one of these was raised by WP-27's
    domain or repository, and nothing in this layer decides whether a write is
    permitted.

    A refusal from the *byte store* is not here. `ManagedByteStore` declares no
    exception vocabulary — `ManagedStoreError` is an infrastructure class the
    application may not import — so a store failure reaches
    `invoke`'s terminal catch and answers `internal_error`. That is honest for
    what those failures are (a full device, a lost root, an object that already
    exists) and is recorded as a limit rather than papered over with a guess.

    The `raise` is outside the handlers, as everywhere else here: the domain
    errors carry titles and identifiers in their messages and leaving the
    handler first is what actually clears `__context__`.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except UnknownScopeError:
        failure = NotFoundError(SafeDetail.DOCUMENT_ID)
    except StaleExpectedVersionError:
        failure = ConflictError(SafeDetail.EXPECTED_VERSION_NUMBER)
    except ManagedDocumentConflictError:
        failure = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
    except UnmanageableTitleError:
        failure = InvalidRequestError(SafeDetail.TITLE)
    except MediaTypeNotManagedError:
        failure = InvalidRequestError(SafeDetail.MEDIA_TYPE)
    except ManagedDocumentError:
        # `EmptyDocumentError` and `ManagedDocumentBoundsError`, and any sibling
        # a later revision of the domain adds. Named as the base rather than as
        # two leaves so a new bound is refused as a bad request rather than
        # escaping as `internal_error`.
        failure = InvalidRequestError(SafeDetail.CONTENT)
    if failure is not None:
        raise failure


#: What a managed-document answer's trust rests on. `principal_partition`
#: because every statement under it carries the authenticated partition, and
#: `product_managed_custody` because the bytes are the product's own — written
#: into the designated managed root by this product and never read from a source
#: system. Not `user_authored`: a managed document is not an ADR-003 record.
_MANAGED_TRUST_BASIS: Final = ("principal_partition", "product_managed_custody")


#: What a task-read answer's trust rests on (WP-TM-03). `principal_partition`
#: because every `TaskManagementRepository` read method filters by the
#: authenticated caller's partition, the same basis `_CONTINUITY_TRUST_BASIS`
#: names for the two-state model's own rows. Not `accepted_continuity`: a task
#: carries no `evidence_state` gate the way `_CONTINUITY_TRUST_BASIS`'s second
#: basis names — WP-TM-01's `Task` does carry `evidence_state`, but nothing in
#: this package's four reads filters on it, so naming that basis here would
#: claim a guarantee this plane does not make.
def _entity_view(entity: Entity) -> dict[str, object]:
    """One entity as the wire sees it.

    `canonical_name` is included alongside `display_name` because resolution
    matches on it: a caller debugging why a reference did not resolve needs the
    form that was compared, not only the form that is shown.
    """
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type.value,
        "canonical_name": entity.canonical_name,
        "display_name": entity.display_name,
        "status": entity.status.value,
        "created_at": format_rfc3339(entity.created_at),
        "updated_at": format_rfc3339(entity.updated_at),
        "version": entity.version,
        "superseded_by_entity_id": entity.superseded_by_entity_id,
    }


def _entity_summary_view(summary: EntitySummary) -> dict[str, object]:
    return {
        "entity_id": summary.entity_id,
        "entity_type": summary.entity_type.value,
        "canonical_name": summary.canonical_name,
        "display_name": summary.display_name,
        "status": summary.status.value,
    }


def _alias_view(alias: EntityAlias) -> dict[str, object]:
    return {
        "alias_id": alias.alias_id,
        "alias_type": alias.alias_type.value,
        "display_value": alias.display_value,
        "effective_from": _moment_or_none(alias.effective_from),
        "effective_to": _moment_or_none(alias.effective_to),
    }


def _identifier_view(identifier: ExternalIdentifier) -> dict[str, object]:
    """One external identifier, as recorded.

    The value is the Principal's own record of their own contact, returned to
    the Principal who holds it, so it is not withheld here. It is withheld from
    *logs*, which is where `AGENTS.md` section 5 places the rule.
    """
    return {
        "identifier_id": identifier.identifier_id,
        "namespace": identifier.namespace.value,
        "display_value": identifier.display_value,
        "verified": identifier.verified,
        "effective_from": _moment_or_none(identifier.effective_from),
        "effective_to": _moment_or_none(identifier.effective_to),
    }


def _assignment_view(assignment: Assignment, at: datetime | None = None) -> dict[str, object]:
    """One assignment as the wire sees it, labelled current or historical.

    **`is_current` is computed here rather than left to the reader.** The raw
    columns are all present, so a caller could derive it — and that is the
    problem. Currency on this plane is one rule (`is_in_force`, plus the status
    the assignment plane uses to say a row is over), and it is the rule the
    resolver applies when deciding whether an assignment may corroborate an
    identity. A surface that separates "current" from "historical" by
    re-implementing that rule would be a second business logic plane, which
    `RI-I-012` forbids, and the two would diverge at exactly the boundaries this
    campaign has already got wrong twice.

    `None` when the caller supplies no moment: a listing that is not asked
    "as of when" does not get an answer invented for it.
    """
    is_current: bool | None = None
    if at is not None:
        is_current = assignment.status == ACTIVE_ASSIGNMENT_STATUS and is_in_force(
            assignment.effective_from, assignment.effective_to, at
        )
    return {
        "assignment_id": assignment.assignment_id,
        "assignment_type": assignment.assignment_type.value,
        "scope_entity_id": assignment.scope_entity_id,
        "role": assignment.role,
        "discipline": assignment.discipline,
        "responsibility_class": assignment.responsibility_class,
        "status": assignment.status,
        "is_current": is_current,
        "effective_from": _moment_or_none(assignment.effective_from),
        "effective_to": _moment_or_none(assignment.effective_to),
    }


def _relationship_view(edge: EntityRelationship, at: datetime | None = None) -> dict[str, object]:
    """One edge as the wire sees it, labelled current or historical.

    The same rule as `_assignment_view`, for the same reason, spelled with the
    edge plane's own liveness column (`state`) instead of the assignment plane's
    (`status`). The resolver treats an edge whose state says it ended as unable
    to corroborate; a surface that showed it as a live relationship would
    disagree with the answer `entities.resolve` gives about the same row.
    """
    is_current: bool | None = None
    if at is not None:
        is_current = edge.state == ACTIVE_RELATIONSHIP_STATE and is_in_force(
            edge.effective_from, edge.effective_to, at
        )
    return {
        "relationship_id": edge.relationship_id,
        "is_current": is_current,
        "from_entity_id": edge.from_entity_id,
        "relationship_type": edge.relationship_type.value,
        "to_entity_id": edge.to_entity_id,
        "scope_entity_id": edge.scope_entity_id,
        "state": edge.state,
        "effective_from": _moment_or_none(edge.effective_from),
        "effective_to": _moment_or_none(edge.effective_to),
        "version": edge.version,
    }


def _resolution_view(answer: EntityResolution) -> dict[str, object]:
    """One resolution as the wire sees it.

    `entity_id` is present and `null` on every unresolved answer rather than
    absent, so a caller that reads it without reading `outcome` gets `null`
    rather than a key error and a retry -- the field is the derived property, so
    there is no arrangement of this payload in which an ambiguous answer carries
    an identifier.
    """
    return {
        "outcome": answer.outcome.value,
        "entity_id": answer.resolved_entity_id,
        "candidates": [
            {
                "entity_id": candidate.entity_id,
                "entity_type": candidate.entity_type.value,
                "display_name": candidate.display_name,
                "status": candidate.status.value,
                "superseded_by_entity_id": candidate.superseded_by_entity_id,
                "matched_on": [item.basis.value for item in candidate.evidence],
                "signals": [signal.value for signal in candidate.signals],
            }
            for candidate in answer.candidates
        ],
        "warnings": [warning.value for warning in answer.warnings],
        "candidates_were_truncated": answer.candidates_were_truncated,
    }


def _context_card_view(card: EntityContextCard) -> dict[str, object]:
    """One context card as the wire sees it.

    `coverage` and `limitations` come before the records in reading order for the
    reason `RI-AC-013` gives: coverage, freshness and exclusions belong *before*
    synthesis, not appended after it where a reader has already drawn a
    conclusion.
    """
    return {
        "entity": _entity_view(card.entity),
        "assembled_at": format_rfc3339(card.assembled_at),
        "coverage": [
            {
                "source_id": entry.source_id,
                "observation_count": entry.observation_count,
                "most_recent_observation_at": format_rfc3339(entry.most_recent_observation_at),
            }
            for entry in card.coverage
        ],
        "most_recent_observation_at": _moment_or_none(card.most_recent_observation_at),
        "limitations": [limitation.value for limitation in card.limitations],
        "is_complete": card.is_complete,
        "aliases": [_alias_view(alias) for alias in card.aliases],
        "identifiers": [_identifier_view(item) for item in card.identifiers],
        "assignments": [_assignment_view(item, card.assembled_at) for item in card.assignments],
        "relationships": [
            _relationship_view(edge, card.assembled_at) for edge in card.relationships
        ],
        "observations": [_observation_view(item) for item in card.observations],
    }


def _observation_view(observation: EntityObservation) -> dict[str, object]:
    """One observation, without the value it observed.

    The card carries *that* a source said something and when, not the text it
    said: the observed value is a name or an address lifted out of someone's
    mail, and a context card is a summary rather than the evidence itself.
    `entities.get` on the source object is where the evidence lives.
    """
    return {
        "observation_id": observation.observation_id,
        "kind": observation.kind.value,
        "source_id": observation.source_id,
        "source_object_id": observation.source_object_id,
        "source_version_id": observation.source_version_id,
        "observed_at": format_rfc3339(observation.observed_at),
        "recorded_at": format_rfc3339(observation.recorded_at),
    }


def _unresolved_mention_view(observation: EntityObservation) -> dict[str, object]:
    """One unresolved mention, with the form that would match and not the raw text.

    See `_entities_unresolved_mentions` for why this differs from
    `_observation_view`: a queue of things nobody could place is useless without
    the thing that could not be placed.
    """
    return {
        "observation_id": observation.observation_id,
        "kind": observation.kind.value,
        "normalized_value": observation.normalized_value,
        "source_id": observation.source_id,
        "source_object_id": observation.source_object_id,
        "source_version_id": observation.source_version_id,
        "observed_at": format_rfc3339(observation.observed_at),
        "recorded_at": format_rfc3339(observation.recorded_at),
    }


def _moment_or_none(moment: datetime | None) -> str | None:
    return None if moment is None else format_rfc3339(moment)


def _entity_type_or_refuse(named: str | None) -> EntityType | None:
    """A caller-supplied entity type, or `invalid_request`.

    Refused rather than ignored: a caller who asked for a project and silently
    received a person would read the wrong answer as the right one.
    """
    if named is None:
        return None
    try:
        return EntityType(named)
    except ValueError:
        raise InvalidRequestError(SafeDetail.SELECTOR) from None


def _namespace_or_refuse(named: str | None) -> ExternalIdentifierNamespace | None:
    if named is None:
        return None
    try:
        return ExternalIdentifierNamespace(named)
    except ValueError:
        raise InvalidRequestError(SafeDetail.SELECTOR) from None


_TASK_TRUST_BASIS: Final = ("principal_partition",)
_COMMITMENT_TRUST_BASIS: Final = ("product_owned_commitment",)
#: The entity plane reads the acting Principal's own partition and nothing else,
#: so its trust basis is the partition, exactly as the task plane's is.
_ENTITY_TRUST_BASIS: Final = ("principal_partition",)


class ApplicationService:
    """Every capability this build can execute, behind one entry point."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        limits: EffectiveLimits,
        clock: Callable[[], datetime] = utc_now,
        managed_store: ManagedByteStore | None = None,
        model_gate: BoundedModelGate | None = None,
        task_management_unit_of_work: Callable[[], Any] | None = None,
        commitment_management_unit_of_work: Callable[[], Any] | None = None,
        relationship_intelligence_enabled: bool = False,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._limits = _effective_limits(limits)
        self._clock = clock
        #: The managed-document byte store, or `None` in a process that was never
        #: told where managed bytes go. `None` is the default because that is
        #: what an unconfigured `MY_PA_MANAGED_DOCUMENT_ROOT` produces, and a
        #: build with no managed plane must publish no managed capability rather
        #: than publish six a caller cannot reach.
        self._managed_store_or_none = managed_store
        #: Whether this build serves the relationship-intelligence entity plane.
        #: Default `False`, and the default is the point: the five `entities.*`
        #: capabilities read who a person is, and `adapters.mcp.remote` derives
        #: the remote tool profile from `Capability` with no per-capability
        #: exclusion list — so a non-operator read joins the remote surface the
        #: moment it becomes available. Withholding it here is the one mechanism
        #: this repository already proves end to end against a real child
        #: process, and it keeps `capabilities.get`, `tools/list`, and the remote
        #: profile agreeing about what exists.
        self._relationship_intelligence_enabled = relationship_intelligence_enabled
        #: Explicit production composition of the optional proposal plane. The
        #: default gate is disabled; an enabled gate cannot be constructed
        #: without its local provider and canonical Review router.
        self._model_gate = model_gate or BoundedModelGate()
        #: WP-27's application service, held rather than built per request: it is
        #: stateless, takes its ports as arguments, and constructing one per call
        #: would say it held something.
        self._managed = ManagedDocumentService()
        #: WP-TM-02's task management service, held rather than built per request:
        #: it is stateless, takes its own unit-of-work factory as an argument, and
        #: constructing one per call would say it held something. The factory is
        #: optional and defaults to None; if not supplied, task mutation handlers
        #: will raise `InternalError` rather than attempting to use it.
        self._task_management_unit_of_work = task_management_unit_of_work
        self._tasks = (
            TaskManagementService(unit_of_work=task_management_unit_of_work, clock=clock)
            if task_management_unit_of_work is not None
            else None
        )
        self._commitment_management_unit_of_work = commitment_management_unit_of_work
        self._commitments = (
            CommitmentManagementService(
                unit_of_work=commitment_management_unit_of_work, clock=clock
            )
            if commitment_management_unit_of_work is not None
            else None
        )

    @property
    def available_capabilities(self) -> frozenset[Capability]:
        """What this composed process can actually execute.

        `_HANDLERS` is what this build *implements* and is fixed at import. This
        is what it can *serve*, which is smaller whenever a capability needs
        something the composition root did not supply — the six `documents.`
        names in a process with no managed root, and the five `entities.` names
        in one that has not enabled the relationship plane. It is one answer with
        two readers: `capabilities.get` publishes it, and the MCP transport
        publishes the tools derived from it, so a client's tool list and the
        manifest cannot disagree about what exists.
        """
        served = frozenset(_HANDLERS)
        if self._managed_store_or_none is None:
            served -= _MANAGED_CAPABILITIES
        if not self._relationship_intelligence_enabled:
            served -= _ENTITY_CAPABILITIES
        return served

    def invoke(
        self,
        metadata: RequestMetadata,
        command: Command,
        *,
        principal: Principal,
        transport: CaptureTransport = CaptureTransport.LOCAL,
        capability_grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
    ) -> ResponseEnvelope:
        """Execute one request and return the envelope describing what happened.

        `principal` is authenticated context supplied by the composition root.
        `metadata.principal_id` is correlation input and is deliberately not
        consulted: a caller-supplied identity is never trusted alone
        (`docs/specs` section 8.2).

        `transport` is the second thing the composition root supplies and the
        caller cannot (WP-10): how the request reached this process. It defaults
        to `LOCAL`, which is what the loopback gateway, MCP over stdio and the
        CLI all are, and the authenticated remote ingress passes
        `REMOTE_CLIENT`. It is provenance the capture plane stores and it
        authorizes nothing — the whole point of routing a remote submission
        through this method is that it takes the *same* path as a local one, and
        a transport that could change what a request is permitted to do would be
        a second capture path wearing the first one's name.

        `capability_grants` is the third server-derived input. `None` means
        local composition and does not restrict searchable planes.
        A non-`None` set is the authenticated remote grant set and is never
        read from the request payload. `context.prepare` intersects it with
        per-plane read capabilities so a `context.prepare` grant does not
        implicitly search every plane the Principal can read.

        **No exception leaves this method.** The first two handlers classify what
        this layer already understands. The third is a terminal catch, and it is
        deliberate rather than defensive: a `SQLAlchemyError` escaping an
        unwrapped statement carries the statement and its bound parameters, and
        letting one out of here would put the obligation to catch it — and the
        redaction that obligation implies — on every transport that WP-4B writes.
        A response is built in exactly one place, so the failure classification
        has to be in that place too.

        `InternalError` is constructed *outside* the handler, so the exception it
        replaces is not left in its `__context__`. That is the same discipline the
        persistence and provider layers apply, and here it is what keeps a
        rendered traceback of the public error from carrying the driver message
        the catch exists to withhold. Nothing of the original reaches the payload
        either way: `problem_detail` reads a code and a closed token set, and
        there is no path from an exception's text to a `ProblemDetail`.

        `Exception` and not `BaseException`: a `KeyboardInterrupt` or a
        `SystemExit` is the operator stopping the process, and converting that
        into a 500-shaped answer would be this method deciding something it has
        no business deciding.
        """
        correlation_id = issue_identifier(IdKind.CORRELATION)
        started_at = self._clock()
        failure: ApplicationError | None = None
        result: _Result | None = None
        unclassified = False
        try:
            result = self._run(
                metadata,
                command,
                principal=principal,
                correlation_id=correlation_id,
                at=started_at,
                transport=transport,
                capability_grants=capability_grants,
            )
        except ApplicationError as error:
            failure = error
        except PortError as error:
            # A port failure raised outside a translated block — from the shared
            # authorization path's own reads, for instance — still has to reach
            # the caller as a classified public error rather than as a crash.
            failure = _port_failure(error)
        except Exception:
            # Nothing that reaches here has been classified, so nothing about it
            # is safe to report beyond that the request did not complete.
            unclassified = True
        if unclassified:
            failure = InternalError()
        if failure is not None:
            return ResponseEnvelope(
                request_id=metadata.request_id,
                correlation_id=correlation_id,
                completed_at=self._clock(),
                error=problem_detail(failure, correlation_id=correlation_id),
            )
        if result is None:
            raise InternalError()
        return ResponseEnvelope(
            request_id=metadata.request_id,
            correlation_id=correlation_id,
            completed_at=self._clock(),
            result=result.payload,
            disclosure=result.disclosure,
        )

    def _run(
        self,
        metadata: RequestMetadata,
        command: Command,
        *,
        principal: Principal,
        correlation_id: str,
        at: datetime,
        transport: CaptureTransport = CaptureTransport.LOCAL,
        capability_grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
    ) -> _Result:
        """Authorize, then execute, then commit — or refuse and still commit.

        The capability is checked against the command before anything else. The
        two arrive from a transport separately, and a request whose metadata
        declares one capability while its payload performs another would be
        authorized against the declaration; there is no reading of that which is
        a valid request.

        The check runs *inside* the transaction, which it did not before. It is a
        security-relevant refusal — the whole of what it guards is a request
        being authorized as one capability and executed as another — and
        `AGENTS.md` section 5 requires a denied attempt to produce a
        proportionate audit event. Checking it before the transaction opened
        produced none at all, which a reviewer measured. The capability recorded
        is the *declared* one, because that is what authority would have been
        evaluated against.

        Both refusals return out of the block normally rather than raising from
        inside it, and for the same reason: raising would roll the record of the
        refusal back along with everything else.
        """
        mismatch = metadata.capability is not command.capability
        with self._unit_of_work() as unit_of_work:
            if mismatch:
                unit_of_work.audit.record(
                    AuditEvent(
                        audit_id=issue_identifier(IdKind.AUDIT),
                        correlation_id=correlation_id,
                        principal_id=principal.principal_id,
                        capability=metadata.capability,
                        purpose=metadata.purpose,
                        # `failed` rather than `denied`: no policy decision was
                        # reached, so there is no `DenialReason` to name and
                        # inventing one would misreport why the request stopped.
                        outcome=AuditOutcome.FAILED,
                        policy_version=POLICY_VERSION,
                        recorded_at=at,
                    )
                )
            else:
                authorization = authorize(
                    unit_of_work,
                    principal=principal,
                    purpose=metadata.purpose,
                    command=command,
                    correlation_id=correlation_id,
                    request_id=metadata.request_id,
                    at=at,
                    transport=transport,
                    capability_grants=capability_grants,
                )
                if authorization.allowed:
                    return _HANDLERS[command.capability](self, unit_of_work, authorization, command)
        # Reached only after the transaction committed, which is what preserves
        # the audit event recording the refusal.
        if mismatch:
            raise InvalidRequestError(SafeDetail.SUBJECT)
        raise DeniedError()

    # ---- the source and knowledge planes -----------------------------------

    def _capabilities_get(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetCapabilities
    ) -> _Result:
        """What this build supports, derived from what it has wired *and composed*.

        `available_capabilities` rather than `_HANDLERS`: a process with no
        managed root has the six `documents.` handlers compiled in and cannot
        serve one, and publishing a name a caller is then refused for would be
        the manifest describing a different build than the one running.
        """
        manifest = build_capability_manifest(
            implemented=self.available_capabilities, limits=self._limits
        )
        try:
            worker_planes = [
                {
                    "plane": plane.plane,
                    "state": plane.state,
                    "backlog": plane.backlog,
                    "dead_lettered": plane.dead_lettered,
                    "last_heartbeat_at": (
                        None
                        if plane.last_heartbeat_at is None
                        else plane.last_heartbeat_at.isoformat()
                    ),
                }
                for plane in unit_of_work.worker_health.for_principal(
                    authorization.principal.principal_id
                )
            ]
        except NotImplementedError:
            # Older/in-memory compositions have no worker plane. Unknown is not
            # healthy and cannot silently become it.
            worker_planes = [
                {
                    "plane": plane,
                    "state": "unavailable",
                    "backlog": None,
                    "dead_lettered": None,
                    "last_heartbeat_at": None,
                }
                for plane in ("capture", "enrollment")
            ]
        readiness = build_readiness_report(manifest, model_route=self._model_gate.route)
        unhealthy_workers = [
            plane
            for plane in worker_planes
            if plane["state"] == "unavailable"
            or (plane["state"] in {"worker_absent", "worker_stale"} and plane["backlog"])
            or (isinstance(plane["dead_lettered"], int) and plane["dead_lettered"] > 0)
        ]
        if unhealthy_workers:
            readiness = ReadinessReport(
                state=ReadinessState.DEGRADED,
                implemented_capabilities=readiness.implemented_capabilities,
                limitations=(
                    *readiness.limitations,
                    "Worker-plane health is unavailable, stale, absent for queued work, or "
                    "reports dead-lettered work; inspect worker_planes.",
                ),
            )
        return _Result(
            payload={
                "manifest": manifest.to_canonical_dict(),
                "readiness": readiness.to_canonical_dict(),
                "worker_planes": worker_planes,
            },
            disclosure=unenrolled_disclosure(authorization.at),
        )

    def _sources_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListSources
    ) -> _Result:
        """The immediate children of one container, bounded by the page size.

        Immediate children only, and one page of them. Nothing here recurses: a
        caller that wants a subtree asks for one level at a time and decides for
        itself when to stop, so no single request can walk a volume
        (`docs/specs` section 9.2). One row past the page is fetched so that
        truncation is a fact rather than a guess.
        """
        enrollment = self._one_enrollment(authorization, command.source_id, command.enrollment_id)
        provider = self._provider(unit_of_work, command.source_id)
        page_size = self._page_size(command.page_size)
        with _translated():
            children = tuple(
                islice(provider.list_children(command.parent_object_id), page_size + 1)
            )
        truncated = len(children) > page_size
        page = children[:page_size]
        return _Result(
            payload={"objects": [_observed(child) for child in page]},
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("source_provider",),
                source_references=tuple(_reference(child) for child in page),
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=(Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else (),
            ),
        )

    def _sources_metadata(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetSourceMetadata
    ) -> _Result:
        """Normalized metadata for one object, plus what has happened to it.

        The supported operations are listed rather than implied, and the list is
        derived from the object's kind. There is no mutating operation to list,
        because the port that would perform one has no such method.
        """
        enrollment = self._one_enrollment(authorization, command.source_id, command.enrollment_id)
        provider = self._provider(unit_of_work, command.source_id)
        with _translated():
            observed = provider.metadata(command.source_object_id)
            outcome = unit_of_work.knowledge.outcome_for_object(
                enrollment_id=enrollment.enrollment_id,
                source_object_id=command.source_object_id,
            )
        operations = (
            ["metadata", "list_children"]
            if observed.kind is ObjectKind.CONTAINER
            else ["metadata", "fetch"]
        )
        return _Result(
            payload={
                **_observed(observed),
                "supported_operations": operations,
                "status": _state_of_outcome(outcome).value,
            },
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("source_provider",),
                source_references=(_reference(observed),),
            ),
        )

    def _sources_fetch(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: FetchSource
    ) -> _Result:
        """Bounded bytes from one object, or the text they decode to.

        Metadata is read first because that is what binds the observation the
        read is checked against: the provider compares the descriptor it opened
        against the version it last described, and a difference is `conflict`
        rather than stale bytes labelled current. `max_bytes` is the smaller of
        what the caller asked for and what configuration permits, so a request
        cannot widen the ceiling.
        """
        enrollment = self._one_enrollment(authorization, command.source_id, command.enrollment_id)
        provider = self._provider(unit_of_work, command.source_id)
        ceiling = self._limits.max_fetch_bytes
        max_bytes = ceiling if command.max_bytes is None else min(command.max_bytes, ceiling)
        with _translated():
            observed = provider.metadata(command.source_object_id)
            content = provider.fetch(command.source_object_id, max_bytes=max_bytes)

        if command.representation is Representation.RAW_BYTES:
            payload: dict[str, Any] = {
                "representation": Representation.RAW_BYTES.value,
                "version_id": content.version_id,
                "media_type": content.media_type,
                "byte_count": len(content.content),
                "content_base64": base64.b64encode(content.content).decode("ascii"),
                "is_truncated": content.is_truncated,
            }
            trust_level, basis = TrustLevel.SOURCE_ORIGINAL, ("source_provider",)
        else:
            outcome = extract_text(
                source_id=command.source_id,
                source_object_id=command.source_object_id,
                observed_version_id=observed.version_id,
                content_version_id=content.version_id,
                media_type=content.media_type,
                content=content.content,
                observed_at=observed.modified_at,
                # Deliberately not the request clock. `Provenance` refuses a
                # processing time earlier than the observation, and the
                # observation is the object's own modification time, which a
                # fixed or skewed request clock can precede.
                is_truncated=content.is_truncated,
            )
            if outcome.status is ExtractionStatus.UNSUPPORTED:
                # Reported, never coerced into empty text. `application/pdf`
                # arrives here while `P00-OD-003` is open.
                raise UnsupportedError(SafeDetail.MEDIA_TYPE_NOT_EXTRACTABLE)
            if outcome.status is ExtractionStatus.QUARANTINED:
                raise QuarantinedError(SafeDetail.PROCESSING_STOPPED)
            payload = {
                "representation": Representation.NORMALIZED_TEXT.value,
                "version_id": content.version_id,
                "media_type": content.media_type,
                "character_count": outcome.character_count,
                "text": outcome.text,
                "is_truncated": outcome.is_truncated,
            }
            trust_level, basis = TrustLevel.SOURCE_BOUND_DERIVED, ("text_extractor",)

        return _Result(
            payload=payload,
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=trust_level,
                trust_basis=basis,
                source_references=(_reference(observed),),
                truncation=Truncation(
                    is_truncated=content.is_truncated,
                    reason="max_fetch_bytes_reached" if content.is_truncated else None,
                ),
                extra_limitations=(
                    (Limitation.CONTENT_TRUNCATED_AT_FETCH_LIMIT,) if content.is_truncated else ()
                ),
            ),
        )

    def _sources_status(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetSourceStatus
    ) -> _Result:
        """What one subject is doing, for exactly one subject.

        Every branch resolves to an enrollment, because coverage is reported for
        a stated enrollment and never inferred globally (`docs/specs` section
        12), and because `complete_for_scope` is meaningless without the bounded
        scope it is complete for.
        """
        if command.source_id is not None:
            enrollment = self._one_enrollment(authorization, command.source_id, None)
            with _translated():
                source = unit_of_work.sources.source(command.source_id)
            if source is None:
                raise NotFoundError(SafeDetail.SOURCE_ID)
            subject, state = "source", SourceStatusState.CONFIGURED
        elif command.enrollment_id is not None:
            enrollment = self._required_enrollment(authorization, command.enrollment_id)
            counts = self._coverage(unit_of_work, enrollment, authorization.at)
            subject, state = "enrollment", _state_of_coverage(counts.state())
        elif command.operation_id is not None:
            with _translated():
                operation = unit_of_work.operations.operation(
                    command.operation_id, principal_id=authorization.principal.principal_id
                )
            if operation is None:
                raise NotFoundError(SafeDetail.OPERATION_ID)
            enrollment = self._required_enrollment(authorization, operation.enrollment_id)
            subject, state = "operation", operation.state
        else:
            enrollment, state = self._object_status(unit_of_work, authorization, command)
            subject = "object"

        return _Result(
            payload={"subject": subject, "state": state.value},
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("application_state",),
            ),
        )

    def _sources_enroll(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: EnrollSource
    ) -> _Result:
        """Enumerate one bounded grant, persist it, and queue the work it authorizes.

        The enrollment, its enumerated object set, the queued operation, and the
        decision's audit event commit together or not at all: they are one
        transaction, and a partial commit would create work with no authority, no
        measured scope, or no evidence behind it (`module-boundaries.md` section
        10).

        **The enumeration happens here, before the job is queued, and that is the
        decision the rest of the package rests on.** The alternative — the worker
        walks the root — leaves a window between this call returning and the job
        running in which an accepted grant has no measured denominator, so every
        disclosure in that window has to say so, which is the token and the clamp
        this package just deleted plus a *new* token distinguishing "not measured
        yet" from "not measurable". Measuring at acceptance means there is no such
        instant: `record_scope` refuses an empty set and its refusal rolls back
        `accept_enrollment` with it, so `enrollment_objects` is non-empty for
        every stored enrollment by construction rather than by convention.

        A retry — the same idempotency key carrying the same normalized request —
        enumerates nothing and queues nothing. Both are gated on
        `acceptance.created`, so a retry makes no provider call at all; the row
        count would be identical either way because `record_scope` inserts under
        a primary key, which is why the assertion that proves this has to be on a
        recording provider's call log. `enqueue_job` is deliberately not
        idempotent, because two calls are two operations to observe separately,
        so the enrollment's own key is what makes "queue this once" true. The
        response says so with a null operation rather than inventing an
        identifier for work that was never queued.
        """
        with _translated():
            source = unit_of_work.sources.source(command.source_id)
        if source is None:
            raise NotFoundError(SafeDetail.SOURCE_ID)
        if command.depth > self._limits.max_enrollment_depth:
            raise InvalidRequestError(SafeDetail.DEPTH, SafeDetail.MAX_ENROLLMENT_DEPTH)

        request = self._enrollment_request(authorization, command)
        acceptance: Acceptance | None = None
        conflict: ApplicationError | None = None
        with _translated():
            try:
                acceptance = unit_of_work.enrollments.accept(request)
            except EnrollmentConflictError:
                # The key is bound to a materially different normalized request.
                # Which field differs is deliberately not reported: that would
                # describe the stored request to whoever guessed the key. The
                # raise is outside the handler for the usual reason.
                conflict = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        if conflict is not None:
            raise conflict
        if acceptance is None:
            raise InternalError()

        enrollment = acceptance.enrollment
        operation_id: str | None = None
        if acceptance.created:
            # Enumeration happens inside this branch and nowhere above it, so a
            # retry resolves no provider and makes no provider call.
            enumerated = self._enumerate(unit_of_work, enrollment)
            if not enumerated:
                # Refused here rather than left to `record_scope`, which refuses
                # the empty set too. Both roll the transaction back; only this one
                # can say what the caller did wrong. A root that holds no
                # extractable object is a scope the operator named and not a fault
                # of this system, and reporting it as `internal_error` would be
                # the misclassification `docs/specs` section 10 forbids.
                raise InvalidRequestError(SafeDetail.SELECTOR)
            with _translated():
                unit_of_work.enrollments.record_scope(enrollment.enrollment_id, enumerated)
                operation_id = unit_of_work.operations.enqueue(enrollment.enrollment_id)

        counts = self._coverage(
            unit_of_work, enrollment, authorization.at, queued=1 if acceptance.created else 0
        )
        with _translated():
            limitations = unit_of_work.knowledge.limitations(enrollment.enrollment_id)
        return _Result(
            payload={
                "enrollment_id": enrollment.enrollment_id,
                "operation_id": operation_id,
                "created": acceptance.created,
                "selector": enrollment.scope.selector_kind,
                "depth": enrollment.scope.depth,
                "media_types": list(enrollment.media_types),
                "policy_version": enrollment.policy_version,
                "accepted_at": format_rfc3339(enrollment.accepted_at),
            },
            disclosure=disclosure_for(
                enrollment=enrollment,
                counts=counts,
                limitations=limitations,
                classification=source.classification,
                observed_at=authorization.at,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("accepted_enrollment",),
            ),
        )

    def _knowledge_search(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SearchKnowledge
    ) -> _Result:
        """Search one enrollment's extracted text.

        The disclosure is the one the search itself produced. It is built from
        the coverage of the rows the same statement snapshot saw, so rebuilding
        it here from a second read would replace a consistent answer with a
        plausible one.

        Nothing of the query reaches the error either way. `SearchQuery` refuses
        to render itself, every message these constructors raise names the rule
        rather than the value, and the public error carries a code and a field
        name and nothing else.

        **A search over partial coverage says so, and that is the one thing added
        to the envelope here.** A Principal holding another enrollment, or objects
        of a held source that no enrollment enumerates, gets an answer that is
        correct for the enrollment it named and is *not* an answer about
        everything they hold. Without a token there is nothing in the reply that
        distinguishes those two, which is `docs/specs` section 23's named failure:
        a search that silently omits unindexed scope and returns a confident
        answer. `with_corpus_caveat` adds one closed token and sets
        `partial_result`; it changes no count, no state and no scope, because
        nothing here measured a wider scope.

        **It is not a widening of this capability's authorization.** The extra
        read answers about the enrollment set the acting Principal already holds
        and returns a boolean; no row outside `command.enrollment_id` reaches the
        page, the coverage, or the disclosure. The search itself is untouched: the
        envelope below is still the one the search produced, because rebuilding
        the coverage from a second read would replace a consistent answer with a
        plausible one.
        """
        self._required_enrollment(authorization, command.enrollment_id)
        request = self._search_request(command)
        outcome: SearchOutcome | None = None
        failure: ApplicationError | None = None
        with _translated():
            try:
                outcome = unit_of_work.knowledge.search(request, now=authorization.at)
            except SearchCursorError:
                failure = ConflictError(SafeDetail.CURSOR)
            except EmptySearchQueryError:
                # The query normalized to terms but produced no lexemes — a
                # different answer from "the search found nothing", which is what
                # section 9.7 forbids collapsing it into.
                failure = InvalidRequestError(SafeDetail.QUERY)
        if failure is not None:
            raise failure
        if outcome is None:
            raise InternalError()

        with _translated():
            beyond = unit_of_work.knowledge.scope_beyond_enrollment(
                authorization.principal.principal_id, enrollment_id=command.enrollment_id
            )
        disclosure = with_corpus_caveat(outcome.disclosure) if beyond else outcome.disclosure

        return _Result(
            payload={
                "matches": [
                    {
                        "knowledge_id": match.knowledge_id,
                        "label": match.label,
                        "snippet": match.snippet,
                        "rank": match.rank.value,
                        "source_id": match.source_id,
                        "source_object_id": match.source_object_id,
                        "version_id": match.version_id,
                    }
                    for match in outcome.matches
                ]
            },
            disclosure=disclosure,
        )

    def _knowledge_coverage(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetCorpusCoverage,
    ) -> _Result:
        """How much of everything this Principal holds has been covered.

        **The answer this build could not previously give.** Coverage is stated
        per enrollment and never inferred globally, which is right and is also why
        a Principal holding three enrollments and objects outside all of them
        could search, receive a clean disclosure, and never learn that most of
        what they hold was outside the question. This composes the stated
        coverages instead of replacing them: the payload carries each enrollment's
        own counts and state unmerged, and the totals beside them are sums that
        say they are sums.

        **The unknown territory is the point, and it is counts only.** Objects
        inside the held sources that no enrollment enumerates, and enumerated
        objects that have reached no outcome. Neither is ever named — no
        identifier, no locator, no media type — which is `AggregateLimitation`'s
        rule applied to a wider scope, and the reason the payload has no list
        anywhere in it.

        The Principal is `authorization.principal.principal_id`, the one the
        gateway established from its own authenticated context, and never anything
        the request carried. There is nothing else the request could carry:
        `GetCorpusCoverage` has no fields.
        """
        with _translated():
            corpus = unit_of_work.knowledge.corpus(
                authorization.principal.principal_id, observed_at=authorization.at
            )
        return _Result(
            payload={
                "state": corpus.state().value,
                "enrollment_count": corpus.enrollment_count,
                "held_sources": corpus.held_sources,
                "stated_totals": {
                    "eligible": corpus.stated_eligible,
                    "processed": corpus.stated_processed,
                    "quarantined": corpus.stated_quarantined,
                    "unsupported": corpus.stated_unsupported,
                    "are_per_enrollment_sums": corpus.totals_are_per_enrollment_sums,
                },
                "enrollments": [
                    {
                        "enrollment_id": counts.enrollment_id,
                        "state": counts.state().value,
                        "eligible": counts.eligible,
                        "processed": counts.processed,
                        "quarantined": counts.quarantined,
                        "unsupported": counts.unsupported,
                    }
                    for counts in corpus.enrollments
                ],
                "unknown_territory": {
                    "objects_in_held_sources": corpus.objects_in_held_sources,
                    "objects_outside_every_enrollment": corpus.objects_outside_every_enrollment,
                    "objects_awaiting_an_outcome": corpus.objects_awaiting_an_outcome,
                },
            },
            disclosure=corpus_disclosure(corpus),
        )

    def _knowledge_read(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReadKnowledge
    ) -> _Result:
        """One stored record, its provenance, and honest truncation.

        The record is looked up inside the stated grant, so one written under a
        different enrollment is `not_found` — the same answer as one that does
        not exist, which is what section 10 requires.
        """
        enrollment = self._required_enrollment(authorization, command.enrollment_id)
        with _translated():
            record = unit_of_work.knowledge.read(
                command.knowledge_id, enrollment_id=command.enrollment_id
            )
        if record is None:
            raise NotFoundError(SafeDetail.KNOWLEDGE_ID)

        text: str | None = None
        cut = False
        if not command.metadata_only:
            text = record.text
            if command.max_characters is not None and len(text) > command.max_characters:
                text, cut = text[: command.max_characters], True

        provenance = record.provenance
        payload: dict[str, Any] = {
            "knowledge_id": record.knowledge_id,
            "label": label_for_media_type(record.media_type),
            "media_type": record.media_type,
            "character_count": len(record.text),
            "metadata_only": command.metadata_only,
            "is_truncated": record.is_truncated or cut,
            "provenance": {
                "source_id": provenance.source_id,
                "source_object_id": provenance.source_object_id,
                "version_id": provenance.version_id,
                "extractor": provenance.extractor,
                "extractor_version": provenance.extractor_version,
                "trust_level": provenance.trust_level.value,
                "observed_at": format_rfc3339(provenance.observed_at),
                "processed_at": format_rfc3339(provenance.processed_at),
            },
        }
        if text is not None:
            payload["text"] = text

        limitations: tuple[Limitation, ...] = (Limitation.LABEL_IS_MEDIA_TYPE_ONLY,)
        if cut:
            limitations = (*limitations, Limitation.TEXT_TRUNCATED_TO_REQUESTED_MAXIMUM)
        return _Result(
            payload=payload,
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=provenance.trust_level,
                trust_basis=(provenance.extractor,),
                source_references=(
                    SourceReference(
                        source_id=provenance.source_id,
                        source_object_id=provenance.source_object_id,
                        version_id=provenance.version_id,
                    ),
                ),
                truncation=Truncation(
                    is_truncated=cut, reason="max_characters_reached" if cut else None
                ),
                extra_limitations=limitations,
            ),
        )

    # ---- the capture plane -------------------------------------------------

    def _capture_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateCapture
    ) -> _Result:
        """Store one user-authored note as the first version of a new capture."""
        return self._admit(
            unit_of_work,
            authorization,
            capture_id=None,
            text=command.text,
            idempotency_key=command.idempotency_key,
            client_created_at=command.client_created_at,
            occurred_at=command.occurred_at,
            capture_kind=command.capture_kind,
            context_source_object_id=command.context_source_object_id,
            context_source_version_id=command.context_source_version_id,
        )

    def _capture_revise(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReviseCapture
    ) -> _Result:
        """Append a successor version to an existing capture the caller owns.

        `D-72`'s owner-equality refusal is superseded here
        (`PKL-MYPA-D-WP03-001`). Its premise — that identity was a property of
        the serving process, so an owner check would make a capture unrevisable
        across restarts — dissolved when `local_principal` began deriving the
        local operator's identifier from a durable UUID namespace
        (`my_pa.domain.identity.binding`): the same operator now presents the
        same `principal_id` in every process, so `QC-AC-013` stays provable
        across two of them. The check itself lives where the data does — the
        head lookup in the capture store is principal-scoped, so a foreign
        capture is indistinguishable from an absent one and surfaces as
        `not_found` rather than as a `forbidden` that would confirm the
        identifier exists.
        """
        return self._admit(
            unit_of_work,
            authorization,
            capture_id=command.capture_id,
            text=command.text,
            idempotency_key=command.idempotency_key,
            client_created_at=command.client_created_at,
            occurred_at=command.occurred_at,
            capture_kind=CaptureKind.QUICK_NOTE,
            context_source_object_id=None,
            context_source_version_id=None,
        )

    def _capture_read(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReadCapture
    ) -> _Result:
        """One stored version of one capture, exactly as it was written.

        A named version is returned whether or not it is the current one, which
        is `QC-AC-010`'s "independently retrievable": an edit appends, and the
        predecessor stays readable at its own identifier.
        """
        principal_id = authorization.principal.principal_id
        with _translated():
            version = unit_of_work.captures.version(
                command.capture_id, version_id=command.version_id, principal_id=principal_id
            )
            current = unit_of_work.captures.version(command.capture_id, principal_id=principal_id)
        if version is None or current is None:
            raise NotFoundError(SafeDetail.CAPTURE_ID)
        view = _capture_version_view(version, is_current=version.version_id == current.version_id)
        return _Result(
            payload=view.to_canonical_dict(),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CAPTURE_TRUST_BASIS),
        )

    def _capture_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListCaptures
    ) -> _Result:
        """One page of stored captures, newest first, carrying no content.

        Bounded by the same published page size every other listing here uses
        (`D-24`), so `capabilities.get` states the limit a caller will actually
        get. One row past the page is read so that truncation is a fact rather
        than a guess, exactly as `sources.list` does it.
        """
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.captures.captures(
                limit=page_size + 1, principal_id=authorization.principal.principal_id
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={
                "captures": [
                    CaptureListEntry(
                        capture_id=summary.capture_id,
                        owner_principal_id=summary.owner_principal_id,
                        created_at=summary.created_at,
                        version_count=summary.version_count,
                        latest_version_id=summary.latest_version_id,
                        latest_version_number=summary.latest_version_number,
                        latest_recorded_at=summary.latest_recorded_at,
                    ).to_canonical_dict()
                    for summary in page
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_CAPTURE_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _capture_search(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SearchCaptures
    ) -> _Result:
        """Exact lexical search over stored capture text.

        **No enrollment is resolved, and that is the whole difference from
        `_knowledge_search`.** `capture.search` is in `_SCOPELESS` because a
        capture belongs to no configured source and no enrollment; asking
        `authorization.covering(...)` here would be asking for a grant that
        cannot exist, and inventing one would be the fabricated authority
        `_enumerate`'s own docstring refuses.

        **Authorization is capability plus purpose; scope is the caller's own
        captures.** `D-72`'s "no owner condition" is superseded
        (`PKL-MYPA-D-WP03-001`): `capture_text_in_scope` now carries the
        caller's partition as a structural condition, and both counts in the
        totals statement are partitioned the same way, so neither a match nor a
        denominator can leak another principal's existence through this
        endpoint. Capability and purpose still decide *whether* the caller may
        search; the partition decides *what there is* to search.

        **The answer carries no capture text.** `CaptureSearchMatch` has no
        field one could go in — identifiers, a version number, a character
        count, a time — so a search cannot become a second read of content that
        `capture.read` audits under its own capability (`QC-AC-041`). A caller
        therefore cannot see *why* a capture matched, which is a limitation the
        envelope states rather than an omission it hides.

        **Every limitation here is derived from what this search measured.** The
        no-stemming token is the price of the `simple` configuration `D-90`
        chose and is unconditional because the property is; the superseded token
        is emitted only when the two counts the same statement snapshot produced
        actually differ. Neither is built from the query and neither is built
        from any capture's content — which is `QC-AC-042`'s disclosure half:
        captured text cannot suppress a limitation, inflate a count, or alter a
        freshness label, because no path exists from content to any of them.
        """
        page_size = self._page_size(command.page_size)
        request: CaptureSearchRequest | None = None
        failure: ApplicationError | None = None
        try:
            request = CaptureSearchRequest(query=SearchQuery(command.query), limit=page_size)
        except EmptySearchQueryError:
            # The query normalized to terms but yielded no lexemes — a different
            # answer from "the search found nothing", which section 9.7 forbids
            # collapsing it into. Caught before `SearchQueryError` because it is
            # a subclass of it and would otherwise be reported as a malformed
            # query rather than an empty one.
            failure = InvalidRequestError(SafeDetail.QUERY)
        except SearchQueryError:
            failure = InvalidRequestError(SafeDetail.QUERY)
        if failure is not None:
            raise failure
        if request is None:  # pragma: no cover - the branches above are exhaustive
            raise InternalError()

        outcome: CaptureSearchOutcome | None = None
        with _translated():
            outcome = unit_of_work.captures.search(
                request, principal_id=authorization.principal.principal_id
            )
        if outcome is None:  # pragma: no cover - `_translated` raises or the call returns
            raise InternalError()

        limitations: tuple[Limitation, ...] = (Limitation.CAPTURE_SEARCH_DOES_NOT_STEM,)
        if outcome.searchable_versions != outcome.stored_versions:
            limitations = (*limitations, Limitation.CAPTURE_SEARCH_EXCLUDES_SUPERSEDED)
        if outcome.truncated:
            limitations = (*limitations, Limitation.LISTING_HAS_NO_CONTINUATION)
        return _Result(
            payload={
                "matches": [
                    {
                        "capture_id": match.capture_id,
                        "version_id": match.version_id,
                        "version_number": match.version_number,
                        "character_count": match.character_count,
                        "recorded_at": format_rfc3339(match.recorded_at),
                    }
                    for match in outcome.matches
                ],
                "searchable_versions": outcome.searchable_versions,
                "stored_versions": outcome.stored_versions,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_CAPTURE_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=outcome.truncated,
                    reason="page_size_reached" if outcome.truncated else None,
                ),
                extra_limitations=limitations,
            ),
        )

    def _knowledge_reveal(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: RevealSubject
    ) -> _Result:
        """The evidence behind one subject: spans, versions, and the derivation trace.

        **Three answers, and the whole point of the capability is that a caller
        can tell them apart.**

        * The subject is not this Principal's, or is not there at all -> a
          `not_found` error, the same one for both. `CaptureRepository.reveal`
          answers `None` for the two cases because the identifier is compared
          inside a partitioned statement, so a foreign subject is not found
          rather than found-and-refused, and this endpoint cannot be used to
          discover that somebody else's record exists.
        * The scope could not be searched — a subject kind this evidence model
          does not cover, or a version whose derivation has not completed -> a
          **success** whose `state` is `unavailable` and whose envelope carries
          `CoverageState.UNAVAILABLE`, `partial_result`, the
          `EVIDENCE_SCOPE_WAS_NOT_SEARCHED` limitation, and the gap in
          `unavailable_evidence`. Not an error, because nothing failed and a
          retry may well succeed; and never an empty result, because
          `INV-PKL-007` forbids reporting unavailable evidence as empty.
        * Otherwise the rows, with `proposed` and `accepted` in two separate
          arrays.

        **No enrollment is resolved**, for the reason `_capture_search` states:
        the rows belong to no configured source and no enrollment, which is why
        `knowledge.reveal` is in `domain.policy.decision._SCOPELESS`.

        **The answer carries no capture text and no derived value**, and neither
        `RevealSpanView` nor `RevealProposalView` has a field one could go in.
        The offsets and the digest are enough for a holder of the version to
        confirm a citation and are nothing to anyone else, which is what lets a
        Reveal be shown beside an item without becoming a second read of the
        content `capture.read` audits under its own capability.
        """
        with _translated():
            reveal = unit_of_work.captures.reveal(
                command.subject_id, principal_id=authorization.principal.principal_id
            )
        if reveal is None:
            raise NotFoundError(SafeDetail.SUBJECT)
        view = RevealView.of(reveal)
        if reveal.state is EvidenceState.UNAVAILABLE:
            assert reveal.gap is not None  # noqa: S101 - `Reveal` refuses the other shape
            return _Result(
                payload=view.to_canonical_dict(),
                disclosure=unavailable_disclosure(
                    authorization.at,
                    unavailable_evidence=(reveal.gap.value,),
                    trust_basis=_REVEAL_TRUST_BASIS,
                    extra_limitations=(Limitation.EVIDENCE_SPANS_CARRY_NO_QUOTED_TEXT,),
                ),
            )
        return _Result(
            payload=view.to_canonical_dict(),
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_REVEAL_TRUST_BASIS,
                extra_limitations=(Limitation.EVIDENCE_SPANS_CARRY_NO_QUOTED_TEXT,),
            ),
        )

    def _review_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListReviewCases
    ) -> _Result:
        """List review cases without capture or normalized-value content."""
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.reviews.cases(
                limit=page_size + 1, principal_id=authorization.principal.principal_id
            )
        truncated = len(found) > page_size
        return _Result(
            payload={"review_cases": [_review_case_payload(case) for case in found[:page_size]]},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=("review_policy",),
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _review_decide(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: DecideReviewCase
    ) -> _Result:
        """Append one disposition and, for acceptance, its assertion and receipt."""
        decision = None
        conflict = False
        missing = False
        unsupported = False
        with _translated():
            try:
                decision = unit_of_work.reviews.decide(
                    ReviewDecisionRequest(
                        review_case_id=command.review_case_id,
                        expected_review_version=command.expected_review_version,
                        disposition=command.disposition,
                        principal_id=authorization.principal.principal_id,
                        correlation_id=authorization.correlation_id,
                        audit_id=authorization.audit_id,
                        policy_version=authorization.decision.policy_version,
                        decided_at=self._clock(),
                        corrected_value=command.corrected_value,
                    )
                )
            except ReviewConflictError:
                conflict = True
            except ReviewNotFoundError:
                missing = True
            except ReviewUnsupportedError:
                unsupported = True
        if conflict:
            raise ConflictError(SafeDetail.EXPECTED_REVIEW_VERSION)
        if unsupported:
            raise UnsupportedError(SafeDetail.DISPOSITION)
        if missing:
            raise NotFoundError(SafeDetail.REVIEW_CASE_ID)
        if decision is None:
            return _Result(
                payload={"review_case_id": command.review_case_id, "result": "invalidated"},
                disclosure=unenrolled_disclosure(
                    authorization.at,
                    trust_basis=("review_policy", "source_span_validation"),
                ),
            )
        return _Result(
            payload={
                "review_case_id": decision.review_case_id,
                "decision_id": decision.decision_id,
                "review_version": decision.sequence,
                "disposition": decision.disposition.value,
                "proposal_state": decision.proposal_state.value,
                "assertion_id": decision.assertion_id,
                "receipt_id": decision.receipt_id,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=("review_policy", "reviewed_promotion"),
            ),
        )

    def _continuity_pulse(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetPulse
    ) -> _Result:
        """The Principal's why-now list, derived at request time from accepted state.

        **A read that derives, not a listing that was written earlier.** The
        repository selects this Principal's accepted, open commitments, tasks and
        decisions and the obligations standing on the current Frames of the
        Principal's running Situations, and the pure derivation returns the
        subset for which a named why-now condition holds. An accepted object with
        no due moment, no named authority point and no unmet obligation is
        absent, however recently it was written; that absence is the difference
        between this and an activity feed.

        Every item carries its `reason_code`, the `basis_refs` a reader can open
        to check it, a consequence and a next step, so the answer explains itself
        rather than asking to be trusted. Nothing here writes: the derivation
        promotes no state and accepts no review.

        The Principal is `authorization.principal.principal_id` — the one the
        gateway established from its own authenticated context — and never
        anything the request carried.
        """
        with _translated():
            items = unit_of_work.pulse.derive_pulse(
                authorization.principal.principal_id, self._clock()
            )
        return _Result(
            payload={
                "pulse_items": [
                    {
                        "pulse_id": item.pulse_id,
                        "item_type": item.item_type.value,
                        "item_ref": item.item_ref,
                        "reason_code": item.reason_code.value,
                        "reason": item.reason,
                        "basis_refs": list(item.basis_refs),
                        "consequence": item.consequence,
                        "next_step": item.next_step,
                        "attention_rank": item.attention_rank,
                        "generated_at": format_rfc3339(item.generated_at),
                        **(
                            {"subject_title": item.subject_title}
                            if item.subject_title is not None
                            else {}
                        ),
                        **(
                            {"subject_state": item.subject_state}
                            if item.subject_state is not None
                            else {}
                        ),
                        **(
                            {"subject_version": item.subject_version}
                            if item.subject_version is not None
                            else {}
                        ),
                        **(
                            {"subject_priority": item.subject_priority}
                            if item.subject_priority is not None
                            else {}
                        ),
                    }
                    for item in items
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_CONTINUITY_TRUST_BASIS,
            ),
        )

    def _continuity_situations(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListSituations
    ) -> _Result:
        """One bounded page of this Principal's Situations, newest first."""
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.situations.list_situations(authorization.principal.principal_id)
            try:
                continuity = unit_of_work.continuity_read
            except NotImplementedError:
                workspace: dict[str, object] = {}
            else:
                principal_id = authorization.principal.principal_id
                workspace = {
                    "frames": [
                        {
                            "frame_id": frame.frame_id,
                            "situation_id": frame.situation_id,
                            "label": frame.label,
                            "state": frame.state.value,
                            "evidence_refs": list(frame.evidence_refs),
                            "alternatives": list(frame.alternatives),
                            "obligations": list(frame.obligations),
                            "uncertainty": frame.uncertainty,
                            "next_authority": frame.next_authority,
                        }
                        for frame in continuity.frames(principal_id)
                    ],
                    "traces": [
                        {
                            "trace_id": trace.trace_id,
                            "object_id": trace.object_id,
                            "object_type": trace.object_type,
                            "source_events": list(trace.source_events),
                            "gaps": list(trace.gaps),
                        }
                        for trace in continuity.traces(principal_id)
                    ],
                    "commitments": [
                        {
                            "commitment_id": item.commitment_id,
                            "counterparty_person_id": item.counterparty_person_id,
                            "summary": item.summary,
                            "direction": item.direction.value,
                            "state": item.state.value,
                            "due_at": None if item.due_at is None else format_rfc3339(item.due_at),
                            "origin_evidence_ref": item.origin_evidence_ref,
                        }
                        for item in continuity.commitments(principal_id)
                    ],
                    "decisions": [
                        {
                            "decision_id": item.decision_id,
                            "question": item.question,
                            "state": item.state.value,
                            "awaiting_authority_ref": item.awaiting_authority_ref,
                            "origin_evidence_ref": item.origin_evidence_ref,
                        }
                        for item in continuity.decisions(principal_id)
                    ],
                    "tasks": [
                        {
                            "task_id": item.task_id,
                            "title": item.title,
                            "state": item.state.value,
                            "due_at": None if item.due_at is None else format_rfc3339(item.due_at),
                            "origin_evidence_ref": item.origin_evidence_ref,
                        }
                        for item in continuity.tasks(principal_id)
                    ],
                    "relationship_events": [
                        {
                            "event_id": event.event_id,
                            "person_id": event.person_id,
                            "event_type": event.event_type.value,
                            "occurred_at": format_rfc3339(event.occurred_at),
                            "context": event.context,
                            "source_ref": event.source_ref,
                        }
                        for event in continuity.relationship_events(principal_id)
                    ],
                }
        truncated = len(found) > page_size
        return _Result(
            payload={
                "situations": [
                    {
                        "situation_id": situation.situation_id,
                        "title": situation.title,
                        "state": situation.state.value,
                        "description": situation.description,
                        "object_refs": list(situation.object_refs),
                        "opened_at": format_rfc3339(situation.opened_at),
                        "closed_at": (
                            None
                            if situation.closed_at is None
                            else format_rfc3339(situation.closed_at)
                        ),
                        "outcome": situation.outcome,
                    }
                    for situation in found[:page_size]
                ],
                **workspace,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_CONTINUITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _continuity_projects(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListProjects
    ) -> _Result:
        """One bounded page of this Principal's Projects, newest first."""
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.projects.list_projects(authorization.principal.principal_id)
        truncated = len(found) > page_size
        return _Result(
            payload={
                "projects": [
                    {
                        "project_id": project.project_id,
                        "name": project.name,
                        "state": project.state.value,
                        "description": project.description,
                        "participants": list(project.participants),
                        "opened_at": format_rfc3339(project.opened_at),
                        "closed_at": (
                            None if project.closed_at is None else format_rfc3339(project.closed_at)
                        ),
                    }
                    for project in found[:page_size]
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_CONTINUITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _continuity_projects_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateProject
    ) -> _Result:
        """Create one Project from an explicit user instruction."""
        principal_id = authorization.principal.principal_id
        digest = _authoring_digest(
            command.capability.value,
            {"name": command.name, "description": command.description},
        )
        object_id = issue_identifier(IdKind.PROJECT)
        with _translated():
            authoring = unit_of_work.continuity_authoring
            try:
                owned = authoring.reserve(
                    principal_id=principal_id,
                    idempotency_key=command.idempotency_key,
                    capability=command.capability.value,
                    payload_digest=digest,
                    object_id=object_id,
                )
            except AuthoringConflictError:
                raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
            if not owned:
                prior = authoring.recall(principal_id, command.idempotency_key)
                if prior is None:
                    raise InternalError()
                project = unit_of_work.projects.get_project(principal_id, prior.object_id)
                if project is None:
                    raise InternalError()
                return self._project_authoring_result(authorization, project, replayed=True)
            project = authoring.author_project(
                principal_id=authorization.principal.principal_id,
                project_id=object_id,
                name=command.name,
                description=command.description,
            )
        return self._project_authoring_result(authorization, project, replayed=False)

    def _continuity_situations_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateSituation
    ) -> _Result:
        """Open one Situation from an explicit user instruction."""
        principal_id = authorization.principal.principal_id
        digest = _authoring_digest(
            command.capability.value,
            {"title": command.title, "description": command.description},
        )
        object_id = issue_identifier(IdKind.SITUATION)
        with _translated():
            authoring = unit_of_work.continuity_authoring
            try:
                owned = authoring.reserve(
                    principal_id=principal_id,
                    idempotency_key=command.idempotency_key,
                    capability=command.capability.value,
                    payload_digest=digest,
                    object_id=object_id,
                )
            except AuthoringConflictError:
                raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
            if not owned:
                prior = authoring.recall(principal_id, command.idempotency_key)
                if prior is None:
                    raise InternalError()
                situation = unit_of_work.situations.get_situation(principal_id, prior.object_id)
                if situation is None:
                    raise InternalError()
                return self._situation_authoring_result(authorization, situation, replayed=True)
            situation = authoring.author_situation(
                principal_id=authorization.principal.principal_id,
                situation_id=object_id,
                title=command.title,
                description=command.description,
            )
        return self._situation_authoring_result(authorization, situation, replayed=False)

    def _continuity_tasks_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: RecordTask
    ) -> _Result:
        """Record one accepted Task from an explicit user instruction."""
        principal_id = authorization.principal.principal_id
        digest = _authoring_digest(
            command.capability.value,
            {
                "title": command.title,
                "project_id": command.project_id,
                "situation_id": command.situation_id,
                "due_at": None if command.due_at is None else format_rfc3339(command.due_at),
            },
        )
        with _translated():
            if command.project_id is not None and (
                unit_of_work.projects.get_project(principal_id, command.project_id) is None
            ):
                raise NotFoundError(SafeDetail.PROJECT_ID)
            if command.situation_id is not None and (
                unit_of_work.situations.get_situation(principal_id, command.situation_id) is None
            ):
                raise NotFoundError(SafeDetail.SITUATION_ID)
            authoring = unit_of_work.continuity_authoring
            object_id = issue_identifier(IdKind.TASK)
            try:
                owned = authoring.reserve(
                    principal_id=principal_id,
                    idempotency_key=command.idempotency_key,
                    capability=command.capability.value,
                    payload_digest=digest,
                    object_id=object_id,
                )
            except AuthoringConflictError:
                raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
            if not owned:
                prior = authoring.recall(principal_id, command.idempotency_key)
                if prior is None:
                    raise InternalError()
                return _Result(
                    payload={
                        "task_id": prior.object_id,
                        "title": command.title,
                        "state": "open",
                        "evidence_state": "accepted",
                        "acceptance_kind": "direct_principal",
                        "project_id": command.project_id,
                        "situation_id": command.situation_id,
                        "due_at": (
                            None if command.due_at is None else format_rfc3339(command.due_at)
                        ),
                        "replayed": True,
                    },
                    disclosure=unenrolled_disclosure(
                        authorization.at, trust_basis=_CONTINUITY_TRUST_BASIS
                    ),
                )
            task = authoring.author_task(
                principal_id=principal_id,
                task_id=object_id,
                title=command.title,
                origin_evidence_ref=authorization.request_id,
                project_id=command.project_id,
                situation_id=command.situation_id,
                due_at=command.due_at,
            )
        return _Result(
            payload={
                "task_id": task.task_id,
                "title": task.title,
                "state": task.state.value,
                "evidence_state": task.evidence_state.value,
                "acceptance_kind": (
                    task.acceptance_kind.value if task.acceptance_kind is not None else None
                ),
                "project_id": task.project_id,
                "situation_id": task.situation_id,
                "due_at": None if task.due_at is None else format_rfc3339(task.due_at),
                "replayed": False,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CONTINUITY_TRUST_BASIS),
        )

    def _project_authoring_result(
        self, authorization: Authorization, project: Project, *, replayed: bool
    ) -> _Result:
        return _Result(
            payload={
                "project_id": project.project_id,
                "name": project.name,
                "state": project.state.value,
                "description": project.description,
                "replayed": replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CONTINUITY_TRUST_BASIS),
        )

    def _situation_authoring_result(
        self, authorization: Authorization, situation: Situation, *, replayed: bool
    ) -> _Result:
        return _Result(
            payload={
                "situation_id": situation.situation_id,
                "title": situation.title,
                "state": situation.state.value,
                "description": situation.description,
                "replayed": replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CONTINUITY_TRUST_BASIS),
        )

    # ---- the managed-document plane ----------------------------------------
    #
    # Six handlers, and every one of them is the same three lines: resolve the
    # byte store, build the WP-27 command with the Principal the authorization
    # already resolved, and hand both to `ManagedDocumentService`. **No managed
    # rule is restated here.** Expected-version checking, idempotency, the
    # replay pre-read, the write ordering, the partition predicate on every
    # statement and the containment of every byte all stay in WP-27's service,
    # its repository and its store. What this layer adds is the seat: a
    # `documents.` request is authorized, audited and refused by exactly the
    # machinery every other capability meets, which is the whole of what WP-27
    # left for WP-28 to do.
    #
    # `principal_id=authorization.principal.principal_id` is the one thing these
    # handlers say about identity, and it is the only spelling
    # `tests/architecture/test_principal_is_never_caller_supplied.py` claim 3
    # admits. The transport-facing commands have no `principal_id` field at all,
    # so there is nothing a caller could have supplied for this to be confused
    # with.

    def _managed_store(self) -> ManagedByteStore:
        """The composed byte store, or a refusal that this build has no managed plane.

        `unsupported` rather than `internal_error`: a process started with no
        `MY_PA_MANAGED_DOCUMENT_ROOT` has no managed plane, which is a fact about
        the build and not a fault in the request. It is also unreachable through
        a transport — `available_capabilities` withholds every `documents.` name from
        `capabilities.get` and from the MCP tool list — so this is the floor
        under that rather than the gate. Two ways to be told the same true thing,
        and neither is a path that writes bytes somewhere unconfigured.
        """
        store = self._managed_store_or_none
        if store is None:
            raise UnsupportedError()
        return store

    def _documents_create(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CreateManagedDocument,
    ) -> _Result:
        """`documents.create`: the first immutable version of a new managed document."""
        store = self._managed_store()
        with _translated(), _managed_translated():
            receipt = self._managed.create(
                unit_of_work.managed_documents,
                store,
                CreateManagedDocumentCommand(
                    principal_id=authorization.principal.principal_id,
                    title=command.title,
                    media_type=command.media_type,
                    content=command.content,
                    idempotency_key=command.idempotency_key,
                ),
                at=authorization.at,
            )
        return self._managed_receipt(authorization, receipt)

    def _documents_revise(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReviseManagedDocument,
    ) -> _Result:
        """`documents.revise`: append a successor version, refusing a stale expectation."""
        store = self._managed_store()
        with _translated(), _managed_translated():
            receipt = self._managed.revise(
                unit_of_work.managed_documents,
                store,
                ReviseManagedDocumentCommand(
                    principal_id=authorization.principal.principal_id,
                    document_id=command.document_id,
                    expected_version_number=command.expected_version_number,
                    title=command.title,
                    media_type=command.media_type,
                    content=command.content,
                    idempotency_key=command.idempotency_key,
                ),
                at=authorization.at,
            )
        return self._managed_receipt(authorization, receipt)

    def _documents_read(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReadManagedDocument,
    ) -> _Result:
        """`documents.read`: one stored version, with its bytes when they were asked for.

        A document this Principal does not own, one that does not exist, and a
        version identifier belonging to another document are one answer:
        `not_found`, naming the field and no identifier. WP-27's service collapses
        the three so the read cannot map identifiers this Principal may not see,
        and this preserves the collapse rather than re-deriving it.
        """
        store = self._managed_store()
        with _translated(), _managed_translated():
            found = self._managed.read(
                unit_of_work.managed_documents,
                store,
                ReadManagedDocumentCommand(
                    principal_id=authorization.principal.principal_id,
                    document_id=command.document_id,
                    version_id=command.version_id,
                    include_bytes=command.include_bytes,
                ),
            )
        if found is None:
            raise NotFoundError(SafeDetail.DOCUMENT_ID)
        version = found.version
        view = ManagedDocumentVersionView(
            document_id=version.document_id,
            version_id=version.version_id,
            version_number=version.version_number,
            supersedes_version_id=version.supersedes_version_id,
            title=version.title,
            media_type=version.media_type,
            content_sha256=version.content_sha256,
            byte_size=version.byte_size,
            recorded_at=version.recorded_at,
            is_current=found.is_current,
            state=found.state,
            content_base64=(
                None
                if found.content is None
                else base64.b64encode(found.content.bytes_).decode("ascii")
            ),
        )
        return _Result(
            payload={"version": view.to_canonical_dict()},
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_MANAGED_TRUST_BASIS),
        )

    def _documents_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListManagedDocuments,
    ) -> _Result:
        """`documents.list`: one bounded page of this Principal's documents, newest first.

        Bounded by the same published page size every other listing here uses
        (`D-24`), so `capabilities.get` states the limit a caller will actually
        get. One row past the page is read so that truncation is a fact rather
        than a guess.
        """
        page_size = self._page_size(command.limit)
        # Composed or not composed: the plane is one thing. A listing or a
        # lifecycle transition needs no bytes, but answering one in a build
        # with no managed root would be answering about a plane that does not
        # exist — and would make `tools/list` and `tools/call` disagree, since
        # `available_capabilities` withholds all six together.
        self._managed_store()
        with _translated(), _managed_translated():
            found = self._managed.list_documents(
                unit_of_work.managed_documents,
                ListManagedDocumentsCommand(
                    principal_id=authorization.principal.principal_id,
                    limit=page_size + 1,
                    include_archived=command.include_archived,
                ),
            )
        truncated = len(found) > page_size
        return _Result(
            payload={
                "documents": [
                    ManagedDocumentListEntry(
                        document_id=document.document_id,
                        state=document.state,
                        title=document.title,
                        media_type=document.media_type,
                        version_count=document.version_count,
                        latest_version_id=document.latest_version_id,
                        latest_version_number=document.latest_version_number,
                        created_at=document.created_at,
                        latest_recorded_at=document.latest_recorded_at,
                    ).to_canonical_dict()
                    for document in found[:page_size]
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_MANAGED_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    # --- the relationship-intelligence entity plane (WP-RI-05) ---------------
    #
    # Five reads, one purpose, no writes. Each answers from the acting
    # Principal's own partition, so each carries `_ENTITY_TRUST_BASIS` and an
    # unenrolled disclosure: an entity belongs to no `src_…` and no `enr_…`, and
    # naming one would be inventing a grant.

    def _entity_plane(self) -> None:
        """Refuse when this build has not enabled the relationship plane.

        `unsupported` rather than an answer, for the reason `_managed_store`
        gives: a process without `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` has no
        relationship plane, which is a fact about the build and not a fault in
        the request.

        **This is the floor, and it was missing.** `available_capabilities`
        withholds the five `entities.` names, and two readers consult it —
        `capabilities.get` and the MCP tool list. The HTTP transport is not one
        of them: `/v1/{capability}` routes by path segment and `_run` dispatches
        straight from `_HANDLERS`, so every one of the five executed and
        answered with entity rows on a build that reported them as
        `not_implemented`. A manifest describing a different build than the one
        running is exactly what `_capabilities_get` says it exists to prevent,
        and `ops/runbooks/relationship-intelligence.md` told the operator that
        unsetting the variable "withholds all five immediately", which was true
        of publication and false of execution.

        Every handler that reads the plane calls this first, so the refusal does
        not depend on which transport asked.
        """
        if not self._relationship_intelligence_enabled:
            raise UnsupportedError()

    def _entities_search(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SearchEntities
    ) -> _Result:
        """`entities.search`: one bounded page of entities matching a text query.

        One row past the page is fetched and dropped, for the reason
        `_sources_children` does the same: `len(found) == page_size` cannot tell
        a full page from a full page with more behind it, so it reported a
        truncation on a corpus of exactly `page_size` entities and no truncation
        on the last page of a larger one. It also produced neither disclosure,
        because `Truncation` refuses `is_truncated` without a reason -- so the
        one arrangement of rows that made the claim true raised instead of
        answering.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        entity_type = _entity_type_or_refuse(command.entity_type)
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.entities.search(
                principal_id,
                command.query,
                entity_type=entity_type,
                limit=page_size + 1,
                after_entity_id=command.after,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={"entities": [_entity_summary_view(summary) for summary in page]},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                # A real cursor now, so `LISTING_HAS_NO_CONTINUATION` is not
                # issued: it would tell a caller to stop while handing them the
                # means to go on, which is the contradiction
                # `_entities_relationships` names.
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].entity_id if truncated and page else None,
                ),
            ),
        )

    def _entities_get(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetEntity
    ) -> _Result:
        """`entities.get`: one entity, or not found.

        An entity another Principal holds is answered exactly as an absent one,
        for the reason `_tasks_read` states: `principal_id` is part of the lookup
        key, so there is no branch here that could distinguish the two.
        """
        self._entity_plane()
        with _translated():
            entity = unit_of_work.entities.get(
                authorization.principal.principal_id, command.entity_id
            )
        if entity is None:
            raise NotFoundError(SafeDetail.TARGET_ID)
        return _Result(
            payload={"entity": _entity_view(entity)},
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
        )

    def _entities_resolve(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ResolveEntity
    ) -> _Result:
        """`entities.resolve`: which entity a reference names, or why none.

        **Never raises `NotFoundError`.** "I found nobody" and "I found four
        people and will not choose" are different answers, and collapsing either
        into an error would lose the candidates and the warnings a caller needs
        to narrow. Both are `200` with an `outcome` the caller reads first.
        """
        self._entity_plane()
        request = ResolutionRequest(
            raw_reference=command.reference,
            namespace=_namespace_or_refuse(command.namespace),
            entity_type=_entity_type_or_refuse(command.entity_type),
            scope_entity_id=command.scope_entity_id,
            as_of=command.as_of,
            # The moment the question is being asked, as distinct from the
            # moment it asks about. Without it the resolver had to infer whether
            # a corroborating record was current from whether anyone had written
            # an end date on it, which read a live dated contract as over and an
            # unstarted role as in force.
            at=authorization.at,
        )
        with _translated():
            answer = EntityResolutionService(unit_of_work.entities).resolve(
                authorization.principal.principal_id, request
            )
        return _Result(
            payload={"resolution": _resolution_view(answer)},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                # The reason is not optional decoration: `Truncation` refuses
                # `is_truncated` without one, so an answer that actually dropped
                # a candidate raised here instead of disclosing that it had --
                # the one case the field exists for was the one case it failed.
                truncation=Truncation(
                    is_truncated=answer.candidates_were_truncated,
                    reason=(
                        "candidate_limit_reached" if answer.candidates_were_truncated else None
                    ),
                ),
            ),
        )

    def _entities_context(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetEntityContext
    ) -> _Result:
        """`entities.context`: the bounded context card for one entity."""
        self._entity_plane()
        with _translated():
            card = EntityContextService(unit_of_work.entities).card(
                authorization.principal.principal_id,
                command.entity_id,
                assembled_at=authorization.at,
            )
        if card is None:
            raise NotFoundError(SafeDetail.TARGET_ID)
        return _Result(
            payload={"context_card": _context_card_view(card)},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=not card.is_complete,
                    # `Truncation` refuses `is_truncated` without a reason, so the
                    # single arrangement of rows that made the claim true -- a card
                    # that actually dropped something -- was the one arrangement
                    # that raised instead of answering. The bound here is the
                    # card's own per-collection ceiling rather than a page size
                    # the caller chose, and the reason says which.
                    reason=None if card.is_complete else "card_collection_limit_reached",
                ),
            ),
        )

    def _entities_unresolved_mentions(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListUnresolvedMentions,
    ) -> _Result:
        """`entities.unresolved_mentions`: one page of references nothing has placed.

        An unlinked `entity_observations` row *is* the unresolved mention, so
        this is a read of that table filtered to rows no entity claims. It is
        the queue `RI-AC-006` asks to be first-class and searchable rather than
        an absence a reader has to infer.

        **The normalized value is disclosed; the observed value is not.** The
        context card omits both, because a card summarises an entity that has
        already been identified and the raw text is evidence that lives at its
        source. Here the identifying text is the entire point — a queue that
        said only "three mentions could not be placed" would give an operator
        nothing to recognise. So the matchable form goes out, which is the same
        class of datum as a `canonical_name` that `entities.search` already
        returns freely, and the raw lifted text — a name inside a mail envelope,
        with whatever else the envelope carried — does not.

        **Read-only, and it stays that way.** Linking a mention to an entity is
        a governed write and this plane publishes none (`D-RI-21`). A caller can
        see the queue and cannot work it, which the runbook states plainly.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.entities.observations(
                principal_id,
                unresolved_only=True,
                limit=page_size + 1,
                after_observation_id=command.after,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={"mentions": [_unresolved_mention_view(item) for item in page]},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].observation_id if truncated and page else None,
                ),
            ),
        )

    def _entities_relationships(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetEntityRelationships,
    ) -> _Result:
        """`entities.relationships`: one bounded page of an entity's typed edges.

        The entity is read first so an unknown identifier is `not_found` rather
        than an empty edge list -- "this person has no recorded relationships"
        and "there is no such person" are different answers.

        **Depth one was the only bound this handler had.** It returned every row
        the repository returned, and the repository returned every edge, so a
        programme with two thousand people on it answered with two thousand
        edges — against `WP-RI-05`'s "bounded output and pagination" and section
        14.4's rule that a tool schema is bounded. One row past the page proves
        the truncation rather than guessing it from a full page, exactly as
        `_sources_children` and `_entities_search` do.

        **The cursor is issued only when it is real.** `next_cursor` is the last
        edge of *this* page, so a caller that passes it back gets the rows after
        it — `after_relationship_id` is a keyset on the same unique column the
        order is taken on, so nothing shifts between requests. When nothing was
        truncated there is no cursor, and `Truncation` refuses one anyway; and
        because a continuation *is* issued here, `LISTING_HAS_NO_CONTINUATION`
        is not, which would otherwise be the disclosure telling a caller to stop
        while handing them the means to go on.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        with _translated():
            entity = unit_of_work.entities.get(principal_id, command.entity_id)
            if entity is None:
                raise NotFoundError(SafeDetail.TARGET_ID)
            found = unit_of_work.entities.relationships(
                principal_id,
                command.entity_id,
                direction=command.direction or "any",
                limit=page_size + 1,
                after_relationship_id=command.after,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={
                "relationships": [_relationship_view(edge, authorization.at) for edge in page]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].relationship_id if truncated else None,
                ),
            ),
        )

    def _tasks_read(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReadTask
    ) -> _Result:
        """`tasks.read`: one task, exactly as this Principal's own copy of it stands.

        A task belonging to another Principal is answered exactly as one that
        does not exist, for the reason `_documents_read` states for its own
        collapse: `get`'s own docstring on `TaskManagementRepository` is
        explicit that `principal_id` is part of the lookup key, so there is no
        branch here that could distinguish the two even by accident.
        """
        with _translated():
            task = unit_of_work.tasks.get(authorization.principal.principal_id, command.task_id)
        if task is None:
            raise NotFoundError(SafeDetail.TASK_ID)
        return _Result(
            payload={"task": _task_view(task).to_canonical_dict()},
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _tasks_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListTasks
    ) -> _Result:
        """`tasks.list`: one bounded page of this Principal's own tasks, newest first.

        Bounded by the same published page size every other listing here uses
        (`D-24`). One row past the page is read so that truncation is a fact
        rather than a guess, exactly as `_documents_list` does it.
        """
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.tasks.list_tasks(
                authorization.principal.principal_id,
                lifecycle_state=command.lifecycle_state,
                priority=command.priority,
                include_archived=command.include_archived,
                limit=page_size + 1,
            )
        truncated = len(found) > page_size
        entries = [_task_list_entry(task).to_canonical_dict() for task in found[:page_size]]
        return _Result(
            payload={"tasks": entries},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_TASK_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _tasks_search(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SearchTasks
    ) -> _Result:
        """`tasks.search`: one bounded page of this Principal's own tasks whose title matches.

        `SearchTasks.__post_init__` has already refused a blank query, so
        nothing here re-validates it. The match itself is `ILIKE`, executed by
        `TaskManagementRepository.search`'s own PostgreSQL implementation — a
        proportionate lexical match for a short, caller-authored title, and
        never a vector or embedding search, which stays behind an abstraction
        and a benchmark gate under `AGENTS.md` section 4 rather than becoming
        an MCV prerequisite.
        """
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.tasks.search(
                authorization.principal.principal_id, command.query, page_size + 1
            )
        truncated = len(found) > page_size
        entries = [_task_list_entry(task).to_canonical_dict() for task in found[:page_size]]
        return _Result(
            payload={"tasks": entries},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_TASK_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _tasks_history(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetTaskHistory
    ) -> _Result:
        """`tasks.history`: one bounded page of one task's append-only mutation record.

        `not_found` when the named task is absent from this Principal's own
        partition, exactly as `_tasks_read` reports it — checked first and
        explicitly, rather than left to an empty history page, because an
        empty page is also the correct answer for a task that exists but has
        no recorded mutations yet (WP-TM-02's own `CREATE` action always
        writes one row, so this is not reachable for a task created through
        that service, but this method's contract does not depend on that).
        """
        principal_id = authorization.principal.principal_id
        with _translated():
            task = unit_of_work.tasks.get(principal_id, command.task_id)
        if task is None:
            raise NotFoundError(SafeDetail.TASK_ID)
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.tasks.list_history(principal_id, command.task_id, page_size + 1)
        truncated = len(found) > page_size
        return _Result(
            payload={
                "history": [
                    _task_history_view(entry).to_canonical_dict() for entry in found[:page_size]
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_TASK_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _tasks_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateTask
    ) -> _Result:
        """`tasks.create`: create a new task.

        Delegates to `TaskManagementService.create_task`, which handles
        idempotency, optimistic concurrency, and history recording. Returns
        the created task and the history entry that recorded the creation.
        """
        if self._tasks is None:
            raise InternalError()
        principal_id = authorization.principal.principal_id
        from my_pa.domain.task.history import TaskMutationActor

        with _translated():
            receipt = self._tasks.create_task(
                principal_id=principal_id,
                title=command.title,
                origin_evidence_ref=command.origin_evidence_ref,
                actor=TaskMutationActor.PRINCIPAL,
                description=command.description,
                priority=command.priority,
                due_at=command.due_at,
                project_id=command.project_id,
                situation_id=command.situation_id,
                accepted_by_review_decision_id=command.accepted_by_review_decision_id,
                idempotency_key=command.idempotency_key,
                client_context=command.client_context,
            )
        return _Result(
            payload={
                "task": _task_view(receipt.task).to_canonical_dict(),
                "history": _task_history_view(receipt.history).to_canonical_dict(),
                "replayed": receipt.replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _tasks_update(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: UpdateTask
    ) -> _Result:
        """`tasks.update`: modify one task's mutable fields.

        Delegates to `TaskManagementService` methods for each field (update_title,
        set_priority, schedule, defer, archive, unarchive). Handles optimistic
        concurrency via `expected_version` and idempotency via `idempotency_key`.
        Returns the updated task and the history entry that recorded the update.

        **Note:** This implementation applies mutations sequentially, which means
        each mutation uses the version from the previous one. A production
        implementation might batch these into a single atomic operation or use
        a different strategy. For now, this follows the pattern of applying
        mutations one at a time through the service.
        """
        if self._tasks is None:
            raise InternalError()
        principal_id = authorization.principal.principal_id
        from my_pa.application.tasks import TaskVersionConflictError
        from my_pa.domain.task.history import TaskMutationActor

        # Read the current task to determine which fields changed
        with _translated():
            current = unit_of_work.tasks.get(principal_id, command.task_id)
        if current is None:
            raise NotFoundError(SafeDetail.TASK_ID)

        # Track the current version as we apply mutations
        current_version = command.expected_version
        receipt = None

        # Apply mutations in order
        try:
            with _translated():
                if command.title is not None and command.title != current.title:
                    receipt = self._tasks.update_title(
                        principal_id=principal_id,
                        task_id=command.task_id,
                        title=command.title,
                        expected_version=current_version,
                        actor=TaskMutationActor.PRINCIPAL,
                        idempotency_key=command.idempotency_key,
                        client_context=command.client_context,
                    )
                    current_version = receipt.task.version

                if command.description is not None and command.description != current.description:
                    receipt = self._tasks.update_description(
                        principal_id=principal_id,
                        task_id=command.task_id,
                        description=command.description,
                        expected_version=current_version,
                        actor=TaskMutationActor.PRINCIPAL,
                        idempotency_key=command.idempotency_key,
                        client_context=command.client_context,
                    )
                    current_version = receipt.task.version

                if command.priority is not None and command.priority != current.priority:
                    receipt = self._tasks.set_priority(
                        principal_id=principal_id,
                        task_id=command.task_id,
                        priority=command.priority,
                        expected_version=current_version,
                        actor=TaskMutationActor.PRINCIPAL,
                        idempotency_key=command.idempotency_key,
                        client_context=command.client_context,
                    )
                    current_version = receipt.task.version

                if (
                    command.scheduled_at is not None
                    and command.scheduled_at != current.scheduled_at
                ):
                    receipt = self._tasks.schedule(
                        principal_id=principal_id,
                        task_id=command.task_id,
                        scheduled_at=command.scheduled_at,
                        expected_version=current_version,
                        actor=TaskMutationActor.PRINCIPAL,
                        idempotency_key=command.idempotency_key,
                        client_context=command.client_context,
                    )
                    current_version = receipt.task.version

                if (
                    command.deferred_until is not None
                    and command.deferred_until != current.deferred_until
                ):
                    receipt = self._tasks.defer(
                        principal_id=principal_id,
                        task_id=command.task_id,
                        deferred_until=command.deferred_until,
                        expected_version=current_version,
                        actor=TaskMutationActor.PRINCIPAL,
                        idempotency_key=command.idempotency_key,
                        client_context=command.client_context,
                    )
                    current_version = receipt.task.version
        except TaskVersionConflictError:
            raise ConflictError(SafeDetail.TASK_ID) from None

        # If no mutations were applied, return the current task
        if receipt is None:
            receipt_task = current
            # Record a no-op history entry
            from my_pa.domain.task.history import TaskMutationAction, TaskMutationOutcome

            with _translated():
                history = TaskManagementHistoryEntry(
                    history_id=issue_identifier(IdKind.TASK_HISTORY),
                    principal_id=principal_id,
                    task_id=command.task_id,
                    action=TaskMutationAction.UPDATE_TITLE,  # Placeholder
                    actor=TaskMutationActor.PRINCIPAL,
                    outcome=TaskMutationOutcome.NO_OP,
                    before_version=current.version,
                    after_version=current.version,
                    occurred_at=self._clock(),
                    recorded_at=self._clock(),
                    idempotency_key=command.idempotency_key,
                    client_context=command.client_context,
                )
                unit_of_work.tasks.insert_history(history)
        else:
            receipt_task = receipt.task
            history = receipt.history

        return _Result(
            payload={
                "task": _task_view(receipt_task).to_canonical_dict(),
                "history": _task_history_view(history).to_canonical_dict(),
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _tasks_transition(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: TransitionTask
    ) -> _Result:
        """`tasks.transition`: move a task to a new lifecycle state.

        Delegates to `TaskManagementService.transition_lifecycle`, which handles
        terminal-state rules, closure evidence requirements, and optimistic
        concurrency. Returns the transitioned task and the history entry that
        recorded the transition.
        """
        if self._tasks is None:
            raise InternalError()
        principal_id = authorization.principal.principal_id
        from my_pa.application.tasks import (
            IllegalTaskTransitionError,
            TaskNotFoundError,
            TaskVersionConflictError,
        )
        from my_pa.domain.task.history import TaskMutationActor

        try:
            with _translated():
                receipt = self._tasks.transition_lifecycle(
                    principal_id=principal_id,
                    task_id=command.task_id,
                    to_state=command.to_state,
                    expected_version=command.expected_version,
                    actor=TaskMutationActor.PRINCIPAL,
                    closure_evidence_ref=command.closure_evidence_ref,
                    idempotency_key=command.idempotency_key,
                    client_context=command.client_context,
                )
        except IllegalTaskTransitionError as e:
            raise InvalidRequestError(SafeDetail.LIFECYCLE_STATE) from e
        except TaskNotFoundError:
            raise NotFoundError(SafeDetail.TASK_ID) from None
        except TaskVersionConflictError:
            raise ConflictError(SafeDetail.TASK_ID) from None

        return _Result(
            payload={
                "task": _task_view(receipt.task).to_canonical_dict(),
                "history": _task_history_view(receipt.history).to_canonical_dict(),
                "replayed": receipt.replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _tasks_bulk_preview(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: BulkPreviewTasks
    ) -> _Result:
        """`tasks.bulk_preview`: preview changes to multiple tasks without applying them.

        Returns a list of proposed changes, each with the task's current state and
        the state it would have after the mutation. No changes are applied, and the
        transaction is rolled back after the preview is returned.
        """
        # This is a placeholder implementation. Full bulk preview would require
        # parsing the mutations list and simulating each one without committing.
        raise UnsupportedError(SafeDetail.MUTATIONS)

    def _tasks_bulk_confirm(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: BulkConfirmTasks
    ) -> _Result:
        """`tasks.bulk_confirm`: apply previewed changes to multiple tasks atomically.

        Applies all mutations from a prior `BulkPreviewTasks` call in one
        transaction. If any mutation fails, the entire operation is rolled back.
        """
        # This is a placeholder implementation. Full bulk confirm would require
        # looking up the bulk operation and applying all its mutations atomically.
        raise UnsupportedError(SafeDetail.BULK_OPERATION_ID)

    def _commitments_read(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReadCommitment
    ) -> _Result:
        with _translated():
            commitment = unit_of_work.commitments.get(
                authorization.principal.principal_id, command.commitment_id
            )
        if commitment is None:
            raise NotFoundError(SafeDetail.COMMITMENT_ID)
        return _Result(
            payload={"commitment": _commitment_view(commitment).to_canonical_dict()},
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_COMMITMENT_TRUST_BASIS),
        )

    def _commitments_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListCommitments
    ) -> _Result:
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.commitments.list_commitments(
                authorization.principal.principal_id,
                direction=command.direction,
                state=command.state,
                limit=page_size + 1,
            )
        truncated = len(found) > page_size
        entries = [_commitment_list_entry(c).to_canonical_dict() for c in found[:page_size]]
        return _Result(
            payload={"commitments": entries},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_COMMITMENT_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _commitments_waiting_on(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: WaitingOn
    ) -> _Result:
        from my_pa.domain.situation.continuity import CommitmentDirection, CommitmentState
        from my_pa.domain.task.role import TaskRole

        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        with _translated():
            commitments = unit_of_work.commitments.list_commitments(
                principal_id,
                direction=CommitmentDirection.OWED_TO_PRINCIPAL,
                state=CommitmentState.OPEN,
                limit=page_size + 1,
            )
        truncated = len(commitments) > page_size
        entries: list[dict[str, object]] = []
        for c in commitments[:page_size]:
            follow_up_task_id: str | None = None
            follow_up_task_title: str | None = None
            follow_up_task_state: str | None = None
            with _translated():
                tasks = unit_of_work.tasks.list_tasks(
                    principal_id,
                    limit=200,
                )
            for t in tasks:
                if t.commitment_id == c.commitment_id and t.role == TaskRole.FOLLOW_UP:
                    follow_up_task_id = t.task_id
                    follow_up_task_title = t.title
                    follow_up_task_state = t.lifecycle_state.value
                    break
            entries.append(
                WaitingOnEntry(
                    commitment_id=c.commitment_id,
                    title=c.summary,
                    counterparty_person_id=c.counterparty_person_id,
                    due_date=c.due_at.isoformat() if c.due_at is not None else None,
                    state=c.state.value,
                    follow_up_task_id=follow_up_task_id,
                    follow_up_task_title=follow_up_task_title,
                    follow_up_task_state=follow_up_task_state,
                ).to_canonical_dict()
            )
        return _Result(
            payload={"waiting_on": entries},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_COMMITMENT_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _commitments_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateCommitment
    ) -> _Result:
        if self._commitments is None:
            raise InternalError()
        principal_id = authorization.principal.principal_id
        from my_pa.domain.task.history import TaskMutationActor

        with _translated():
            receipt = self._commitments.create_commitment(
                principal_id=principal_id,
                counterparty_person_id=command.counterparty_person_id,
                direction=command.direction,
                summary=command.summary,
                origin_evidence_ref=command.origin_evidence_ref,
                actor=TaskMutationActor.PRINCIPAL,
                due_at=command.due_at,
                project_id=command.project_id,
                situation_id=command.situation_id,
                accepted_by_review_decision_id=command.accepted_by_review_decision_id,
                idempotency_key=command.idempotency_key,
                client_context=command.client_context,
            )
        return _Result(
            payload={
                "commitment": _commitment_view(receipt.commitment).to_canonical_dict(),
                "replayed": receipt.replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_COMMITMENT_TRUST_BASIS),
        )

    def _commitments_close(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CloseCommitment
    ) -> _Result:
        if self._commitments is None:
            raise InternalError()
        principal_id = authorization.principal.principal_id
        from my_pa.application.commitments import (
            CommitmentNotFoundError,
            CommitmentVersionConflictError,
        )
        from my_pa.domain.task.history import TaskMutationActor

        try:
            with _translated():
                receipt = self._commitments.close_commitment(
                    principal_id=principal_id,
                    commitment_id=command.commitment_id,
                    expected_version=command.expected_version,
                    closure_evidence_ref=command.closure_evidence_ref,
                    actor=TaskMutationActor.PRINCIPAL,
                    idempotency_key=command.idempotency_key,
                    client_context=command.client_context,
                )
        except CommitmentNotFoundError:
            raise NotFoundError(SafeDetail.COMMITMENT_ID) from None
        except CommitmentVersionConflictError:
            raise ConflictError(SafeDetail.COMMITMENT_ID) from None
        return _Result(
            payload={
                "commitment": _commitment_view(receipt.commitment).to_canonical_dict(),
                "replayed": receipt.replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_COMMITMENT_TRUST_BASIS),
        )

    def _documents_archive(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ArchiveManagedDocument,
    ) -> _Result:
        """`documents.archive`: withdraw one document from the active set. Destroys nothing."""
        # Composed or not composed: the plane is one thing. A listing or a
        # lifecycle transition needs no bytes, but answering one in a build
        # with no managed root would be answering about a plane that does not
        # exist — and would make `tools/list` and `tools/call` disagree, since
        # `available_capabilities` withholds all six together.
        self._managed_store()
        with _translated(), _managed_translated():
            changed = self._managed.archive(
                unit_of_work.managed_documents,
                ArchiveManagedDocumentCommand(
                    principal_id=authorization.principal.principal_id,
                    document_id=command.document_id,
                ),
            )
        return self._managed_transition(authorization, DocumentState.ARCHIVED, changed=changed)

    def _documents_restore(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: RestoreManagedDocument,
    ) -> _Result:
        """`documents.restore`: return one archived document to the active set."""
        # Composed or not composed: the plane is one thing. A listing or a
        # lifecycle transition needs no bytes, but answering one in a build
        # with no managed root would be answering about a plane that does not
        # exist — and would make `tools/list` and `tools/call` disagree, since
        # `available_capabilities` withholds all six together.
        self._managed_store()
        with _translated(), _managed_translated():
            changed = self._managed.restore(
                unit_of_work.managed_documents,
                RestoreManagedDocumentCommand(
                    principal_id=authorization.principal.principal_id,
                    document_id=command.document_id,
                ),
            )
        return self._managed_transition(authorization, DocumentState.ACTIVE, changed=changed)

    def _managed_receipt(
        self, authorization: Authorization, receipt: ManagedDocumentReceipt
    ) -> _Result:
        """One managed write's receipt, as the contract publishes it."""
        view = ManagedDocumentReceiptView(
            receipt_id=receipt.receipt_id,
            document_id=receipt.document_id,
            version_id=receipt.version_id,
            version_number=receipt.version_number,
            idempotency_key=receipt.idempotency_key,
            content_sha256=receipt.content_sha256,
            byte_size=receipt.byte_size,
            issued_at=receipt.issued_at,
            created=receipt.created,
        )
        return _Result(
            payload={"receipt": view.to_canonical_dict()},
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_MANAGED_TRUST_BASIS),
        )

    def _managed_transition(
        self, authorization: Authorization, state: DocumentState, *, changed: bool
    ) -> _Result:
        """The answer both lifecycle transitions give: the resulting state, and whether it moved.

        `changed=False` is a success and not a refusal. Archiving an archived
        document leaves it archived, which is what the caller asked for; reporting
        a conflict would make an idempotent retry look like a failure.
        """
        return _Result(
            payload={"state": state.value, "changed": changed},
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_MANAGED_TRUST_BASIS),
        )

    def _context_prepare(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: PrepareContext
    ) -> _Result:
        """Assemble a bounded context package from authorized planes.

        The Principal is `authorization.principal.principal_id` — the one the
        gateway established — and never anything the request carried. Enrollments
        are discovered from `authorization.enrollments`; the command does not
        name them. The query is normalized here as a `SearchQuery`, the same way
        `knowledge.search` does it, so a malformed or empty query is
        `invalid_request` with the field token and never the text. Empty evidence
        remains valid: a complete no-match and an unavailable plane are distinct
        coverage answers, not a missing-evidence error.
        """
        query: SearchQuery | None = None
        failure: ApplicationError | None = None
        try:
            query = SearchQuery(command.query)
        except SearchQueryError:
            failure = InvalidRequestError(SafeDetail.QUERY)
        if failure is not None:
            raise failure
        if query is None:
            raise InternalError()
        prepared = ContextPreparationService(
            managed_documents_composed=self._managed_store_or_none is not None,
        ).prepare(unit_of_work, authorization, command, query)
        truncation = Truncation(
            is_truncated=prepared.truncation.is_truncated,
            reason=prepared.truncation.reason,
        )
        return _Result(
            payload=prepared.to_canonical_dict(),
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=("context_policy",),
                truncation=truncation,
            ),
        )

    def _context_feedback(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: RecordContextFeedback,
    ) -> _Result:
        """Record one reversible retrieval preference for the acting Principal.

        The Principal is `authorization.principal.principal_id`. The command
        carries no principal_id. Canonical capture text and continuity titles
        are not in this write path.
        """
        admission = None
        conflict: ApplicationError | None = None
        with _translated():
            try:
                admission = unit_of_work.context_preferences.record(
                    principal_id=authorization.principal.principal_id,
                    action=command.action.value,
                    target_id=command.target_id,
                    idempotency_key=command.idempotency_key,
                    alias=command.alias,
                    source_id=command.source_id,
                    correlation_id=authorization.correlation_id,
                    request_id=authorization.request_id,
                    audit_id=authorization.audit_id,
                    created_at=authorization.at,
                )
            except PreferenceConflictError:
                conflict = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        if conflict is not None:
            raise conflict
        if admission is None:
            raise InternalError()
        current = [
            {
                "action": row.action.value,
                "target_id": row.target_id,
                "alias": row.alias,
                "source_id": row.source_id,
            }
            for row in admission.current
        ]
        return _Result(
            payload={
                "accepted": True,
                "event_id": admission.event.event_id,
                "action": admission.event.action.value,
                "target_id": admission.event.target_id,
                "current": current,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=("context_policy",)),
        )

    def _goodnotes_work(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetGoodNotesWork,
    ) -> _Result:
        """Return immutable page-version work for the acting Principal.

        The Principal is `authorization.principal.principal_id`. The command
        carries no principal_id. Page bytes and live transcription are not in
        this path.
        """
        with _translated():
            work = lookup_work(
                unit_of_work,
                authorization,
                run_id=command.run_id,
                page_version_id=command.page_version_id,
            )
        return _Result(
            payload=work_payload(work),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _goodnotes_content(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetGoodNotesContent,
    ) -> _Result:
        """Return the pinned visual raster for the acting Principal.

        The Principal is `authorization.principal.principal_id`. The command
        carries no principal_id and no path.
        """
        with _translated():
            work, raster = lookup_content(
                unit_of_work,
                authorization,
                run_id=command.run_id,
                page_version_id=command.page_version_id,
                content_sha256=command.content_sha256,
            )
        return _Result(
            payload=content_payload(work, raster),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _goodnotes_propose(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: SubmitGoodNotesProposal,
    ) -> _Result:
        """Admit one semantic proposal. Does not write canonical notes or run-changes.

        The Principal is `authorization.principal.principal_id`. The command
        carries no principal_id. Transcription is data, never instructions.
        """
        with _translated():
            proposal = submit_proposal(unit_of_work, authorization, command)
        return _Result(
            payload=proposal_payload(proposal),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _admit(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        *,
        capture_id: str | None,
        text: str,
        idempotency_key: str,
        client_created_at: datetime | None,
        occurred_at: datetime | None,
        capture_kind: CaptureKind,
        context_source_object_id: str | None,
        context_source_version_id: str | None,
    ) -> _Result:
        """The one write path both `capture.create` and `capture.revise` take.

        **The transaction is the one this method was handed.** `_run` opened it
        before `authorize` ran and the commit is that `with` block's exit, so the
        capture, its version, its receipt, its submission, and its queued
        processing job commit together or not at all without this method
        arranging anything (`QC-AC-034`). The redacted audit event is *not* among
        them: it committed first, on the sink's own connection, and the version
        stores its identifier (`D-34`). A failed audit therefore fails the
        request closed before any of this runs, and a failed work transaction
        leaves an audit event describing an authorization whose work never
        landed, which `D-34` records as the correct direction of the trade.

        **Three clocks, read at three moments.** `authorization.at` is when this
        process received the request, `self._clock()` here is when the admission
        decided, and the store writes `recorded_at` from the server's own clock.
        The two the caller may supply are passed through untouched, including
        when they are absent. Five columns, five origins, no default from one to
        another (`QC-AC-012`).
        """
        content = _capture_content(text)
        request = CaptureAdmissionRequest(
            capture_id=capture_id,
            content=content,
            idempotency_key=idempotency_key,
            request_id=authorization.request_id,
            correlation_id=authorization.correlation_id,
            principal_id=authorization.principal.principal_id,
            audit_id=authorization.audit_id,
            # Fixed rather than requested. `QC-AC-040` requires the default to be
            # private-local with cloud and training false, and a caller-selected
            # classification would be a caller widening its own processing
            # eligibility, which `docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md`
            # forbids: `:56` names the field and defaults it to `private_local`,
            # and `:73` states that "classification changes cannot silently widen
            # processing eligibility". Two lines, not one sentence.
            classification=Classification.PRIVATE_LOCAL,
            processing_policy=ProcessingPolicy.LOCAL_ONLY,
            server_received_at=authorization.at,
            accepted_at=self._clock(),
            client_created_at=client_created_at,
            occurred_at=occurred_at,
            capture_kind=capture_kind,
            context_source_object_id=context_source_object_id,
            context_source_version_id=context_source_version_id,
            # Provenance, not a decision. It arrived on `invoke`'s own parameter
            # from the composition root and reaches the submission row unchanged;
            # nothing between here and the INSERT reads it, and no branch in this
            # method depends on it. That is what makes a remote submission the
            # same transaction rather than a parallel one.
            transport=authorization.transport,
        )
        admission: CaptureAdmission | None = None
        conflict: ApplicationError | None = None
        with _translated():
            try:
                admission = unit_of_work.captures.admit(
                    request, principal_id=authorization.principal.principal_id
                )
            except CaptureConflictError:
                # The key is bound to materially different content. `conflict`,
                # which is one of the eleven public codes; there is no
                # `idempotency_conflict` and inventing one would be an
                # unauthorised expansion of the v1 error set. Which field differs
                # is deliberately not reported: that would describe the stored
                # request to whoever guessed the key. The raise is outside the
                # handler for the usual reason.
                conflict = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        if conflict is not None:
            raise conflict
        if admission is None:
            raise InternalError()

        receipt = admission.receipt
        return _Result(
            payload=CaptureReceiptView(
                receipt_id=receipt.receipt_id,
                capture_id=receipt.capture_id,
                version_id=receipt.version_id,
                version_number=receipt.version_number,
                idempotency_key=receipt.idempotency_key,
                content_sha256=receipt.content_sha256,
                issued_at=receipt.issued_at,
                created=admission.created,
            ).to_canonical_dict(),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CAPTURE_TRUST_BASIS),
        )

    # ---- shared helpers ----------------------------------------------------

    def _page_size(self, requested: int | None) -> int:
        """The page size to use: the caller's, bounded by the published maximum."""
        if requested is None:
            return self._limits.default_page_size
        return min(requested, self._limits.max_page_size)

    def _provider(self, unit_of_work: UnitOfWork, source_id: str) -> SourceProvider:
        """The adapter serving `source_id`, or a truthful unavailability.

        A source that is configured but has no adapter wired is `unavailable`
        rather than `not_found`: the source exists, and saying otherwise would
        report a wiring gap as a fact about the corpus.

        Taken from the unit of work rather than from a constructor argument, and
        `contracts.ports.UnitOfWork.providers` gives the reason: the adapter
        resolves opaque identifiers against `knowledge.source_objects`, so it has
        to read the rows this request's transaction sees, and the identifiers it
        issues have to roll back with it.
        """
        provider = unit_of_work.providers.for_source(source_id)
        if provider is None:
            raise UnavailableError(SafeDetail.SOURCE_ID)
        return provider

    def _enumerate(self, unit_of_work: UnitOfWork, enrollment: Enrollment) -> tuple[str, ...]:
        """The objects `enrollment` authorizes, measured once, at acceptance.

        For an enrollment that named its objects this is those objects: the list
        *is* the authorization, and walking anything would answer a question
        nobody asked. **No provider is resolved on that path**, which is a
        decision rather than an ordering accident: requiring an adapter to
        enumerate a set the request already stated would make `sources.enroll`
        fail for a source whose root is momentarily unreachable, over an answer
        that never depended on the root. `record_scope` still refuses an
        identifier `knowledge.source_objects` has no row for, so the named set is
        checked against the store rather than trusted.

        For a root selector it is the walk, and every bound the walk obeys is
        read off the accepted enrollment rather than restated here —
        `scope.depth` and `max_items`, both of which the domain already refused
        to construct outside their ceilings. There the provider *is* required,
        and a source with no adapter is `unavailable` with the whole transaction
        rolled back: an enrollment nobody can enumerate must not exist.

        **Depth is levels of listing, and the level count is `depth + 1`.**
        `domain.source.enrollment` fixes depth zero as "the named root itself and
        its immediate children — never a walk", so the default enrollment is one
        `list_children` call. Depth one adds the children of those children, and
        so on to `MAX_ENROLLMENT_DEPTH`.

        **Containers are descended and not recorded.** The eligible total is a
        count of objects that could hold extractable content, and a directory
        holds none; counting one would make `processed == eligible` unreachable
        for every enrollment that contains a folder. The table's own docstring
        records the same decision from the schema's side.

        Refuses with `InvalidRequestError(MAX_ITEMS)` at `max_items + 1` objects,
        so the walk stops rather than materialising a scope the enrollment never
        authorized. The refusal rolls the accepting transaction back, so the
        enrollment does not exist rather than existing over a truncated scope.

        The provider reads run inside the enroll transaction, under `D-35`, which
        permits it while the provider is local. This is a new caller of that
        decision and not a reopening of it: enumeration reads no bytes — only
        `iterdir` and `stat` — so it is strictly cheaper than `sources.fetch`,
        which already runs inside the transaction under the same decision. This
        module's own docstring, at "Provider reads happen inside that
        transaction", is the sentence that has to change first if a provider ever
        becomes remote.
        """
        scope = enrollment.scope
        if scope.root_object_id is None:
            return scope.object_ids

        provider = self._provider(unit_of_work, enrollment.source_id)
        found: list[str] = []
        frontier: list[str] = [scope.root_object_id]
        for _ in range(scope.depth + 1):
            if not frontier:
                break
            descend: list[str] = []
            for parent in frontier:
                with _translated():
                    children = tuple(provider.list_children(parent))
                for child in children:
                    # `ENUMERABLE_KINDS` rather than a literal comparison, and
                    # the reason is a second caller rather than style: the corpus
                    # coverage read subtracts exactly these kinds when it counts
                    # what lies outside every enrollment, and two places deciding
                    # what an enrollment can hold is the divergence this package
                    # keeps being blocked for.
                    if child.kind not in ENUMERABLE_KINDS:
                        descend.append(child.source_object_id)
                        continue
                    found.append(child.source_object_id)
                    if len(found) > enrollment.max_items:
                        raise InvalidRequestError(SafeDetail.MAX_ITEMS)
            frontier = descend
        # A symlink inside the root and its target are one object with one
        # identifier (`providers.fixture.list_children`), so the same object can
        # be listed twice under two names. `dict.fromkeys` keeps the first
        # occurrence and the order; `record_scope` would collapse the duplicate
        # against its primary key anyway, but then `max_items` would have been
        # counted against a number the stored set does not have.
        return tuple(dict.fromkeys(found))

    def _one_enrollment(
        self, authorization: Authorization, source_id: str, named: str | None
    ) -> Enrollment:
        """The single grant a source-scoped request runs under.

        A principal may hold more than one enrollment over a source, and the two
        may have different scopes and different coverage. Choosing between them
        would be the guess section 10 forbids, so a request that does not name
        one is `ambiguous_request` and a request that does is answered under
        exactly that grant.
        """
        covering = authorization.covering(source_id)
        if named is not None:
            match = next((e for e in covering if e.enrollment_id == named), None)
            if match is None:
                raise NotFoundError(SafeDetail.ENROLLMENT_ID)
            return match
        if len(covering) > 1:
            raise AmbiguousRequestError(
                SafeDetail.ENROLLMENT_ID, SafeDetail.MULTIPLE_ENROLLMENTS_COVER_THE_SCOPE
            )
        if not covering:
            # The narrowing an index requires. Policy already refused a source
            # outside the principal's enrollments, so nothing reaches this with
            # an empty set; it denies rather than raising an untyped IndexError.
            raise DeniedError()
        return covering[0]

    def _required_enrollment(self, authorization: Authorization, enrollment_id: str) -> Enrollment:
        """The principal's enrollment with this identifier.

        The narrowing an enrollment-scoped handler requires. The shared
        authorization path derives such a request's scope from the principal's
        own enrollments, so one it does not hold was already denied.
        """
        enrollment = authorization.enrollment(enrollment_id)
        if enrollment is None:
            raise NotFoundError(SafeDetail.ENROLLMENT_ID)
        return enrollment

    def _object_status(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetSourceStatus
    ) -> tuple[Enrollment, SourceStatusState]:
        """The grant and the state behind a status request naming one object."""
        object_id = command.source_object_id
        if object_id is None:
            # Unreachable: `GetSourceStatus` refuses to exist without exactly one
            # subject and the caller has excluded the other three.
            raise InternalError()
        with _translated():
            source_id = unit_of_work.sources.source_of_object(object_id)
        if source_id is None:
            raise NotFoundError(SafeDetail.SOURCE_OBJECT_ID)
        enrollment = self._one_enrollment(authorization, source_id, None)
        with _translated():
            outcome = unit_of_work.knowledge.outcome_for_object(
                enrollment_id=enrollment.enrollment_id, source_object_id=object_id
            )
        return enrollment, _state_of_outcome(outcome)

    def _coverage(
        self,
        unit_of_work: UnitOfWork,
        enrollment: Enrollment,
        observed_at: datetime,
        *,
        queued: int = 0,
    ) -> CoverageCounts:
        """Coverage of one enrollment, with the denominator the store measured.

        Nothing about the size of the scope is passed down. The repository reads
        the enumerated object set beside the outcomes it counts, which is what
        makes the reported `eligible` a measurement rather than this layer's
        arithmetic. `queued` is still stated here, because work in flight is a
        fact about the job plane that no count of objects can carry.
        """
        with _translated():
            return unit_of_work.knowledge.coverage(
                enrollment.enrollment_id,
                observed_at=observed_at,
                queued=queued,
            )

    def _disclose(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        enrollment: Enrollment,
        *,
        trust_level: TrustLevel,
        trust_basis: tuple[str, ...],
        source_references: tuple[SourceReference, ...] = (),
        truncation: Truncation = _NO_TRUNCATION,
        extra_limitations: tuple[Limitation, ...] = (),
    ) -> Disclosure:
        """The envelope for a result produced under one grant.

        Every part of it is read: the counts from the rows extraction wrote, the
        limitations from what the last enumeration pass recorded, and the
        classification from the configured source. Nothing here is a constant a
        result could outlive.
        """
        counts = self._coverage(unit_of_work, enrollment, authorization.at)
        with _translated():
            limitations = unit_of_work.knowledge.limitations(enrollment.enrollment_id)
            source = unit_of_work.sources.source(enrollment.source_id)
        if source is None:
            # An enrollment's source is a foreign key; a missing row here is a
            # broken store rather than a request problem.
            raise InternalError()
        return disclosure_for(
            enrollment=enrollment,
            counts=counts,
            limitations=limitations,
            classification=source.classification,
            observed_at=authorization.at,
            trust_level=trust_level,
            trust_basis=trust_basis,
            source_references=source_references,
            truncation=truncation,
            extra_limitations=extra_limitations,
        )

    def _search_request(self, command: SearchKnowledge) -> SearchRequest:
        """Build the domain request, bounded by the published page size."""
        query: SearchQuery | None = None
        request: SearchRequest | None = None
        failure: ApplicationError | None = None
        try:
            query = SearchQuery(command.query)
        except SearchQueryError:
            failure = InvalidRequestError(SafeDetail.QUERY)
        if query is not None:
            try:
                request = SearchRequest(
                    enrollment_id=command.enrollment_id,
                    query=query,
                    page_size=self._page_size(command.page_size),
                    cursor=command.cursor,
                    snippet_words=(
                        DEFAULT_SNIPPET_WORDS
                        if command.snippet_words is None
                        else command.snippet_words
                    ),
                )
            except SearchQueryError:
                failure = InvalidRequestError(SafeDetail.SNIPPET_WORDS)
            except SearchCursorError:
                failure = ConflictError(SafeDetail.CURSOR)
        if failure is not None:
            raise failure
        if request is None:
            raise InternalError()
        return request

    def _enrollment_request(
        self, authorization: Authorization, command: EnrollSource
    ) -> EnrollmentRequest:
        """Build the domain request, reporting which field a refusal was about.

        The bounds are the domain's, enforced on construction, so there is no
        path here that holds an unbounded enrollment and checks it later.
        """
        request: EnrollmentRequest | None = None
        failure: ApplicationError | None = None
        try:
            request = EnrollmentRequest(
                source_id=command.source_id,
                principal_id=authorization.principal.principal_id,
                purpose=authorization.purpose,
                scope=EnrollmentScope(
                    object_ids=command.object_ids,
                    root_object_id=command.root_object_id,
                    depth=command.depth,
                ),
                media_types=command.media_types,
                policy_version=authorization.decision.policy_version,
                idempotency_key=command.idempotency_key,
                max_items=MAX_ENROLLMENT_ITEMS if command.max_items is None else command.max_items,
                max_bytes=MAX_ENROLLMENT_BYTES if command.max_bytes is None else command.max_bytes,
            )
        except EnrollmentBoundsError:
            # The domain message names the field and the limit and never the
            # value, and none of it crosses into the public error either way.
            failure = InvalidRequestError(SafeDetail.SELECTOR)
        if failure is not None:
            raise failure
        if request is None:
            raise InternalError()
        return request


#: The wiring. `capabilities.get` reports availability from these keys, so a
#: capability is available exactly when something here can execute it, and there
#: is no constant to edit at the moment one starts working.
_HANDLERS: Final[Mapping[Capability, Callable[..., _Result]]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: ApplicationService._capabilities_get,
        Capability.SOURCES_LIST: ApplicationService._sources_list,
        Capability.SOURCES_METADATA: ApplicationService._sources_metadata,
        Capability.SOURCES_FETCH: ApplicationService._sources_fetch,
        Capability.SOURCES_STATUS: ApplicationService._sources_status,
        Capability.SOURCES_ENROLL: ApplicationService._sources_enroll,
        Capability.KNOWLEDGE_SEARCH: ApplicationService._knowledge_search,
        Capability.KNOWLEDGE_READ: ApplicationService._knowledge_read,
        Capability.KNOWLEDGE_COVERAGE: ApplicationService._knowledge_coverage,
        Capability.KNOWLEDGE_REVEAL: ApplicationService._knowledge_reveal,
        Capability.CAPTURE_CREATE: ApplicationService._capture_create,
        Capability.CAPTURE_REVISE: ApplicationService._capture_revise,
        Capability.CAPTURE_READ: ApplicationService._capture_read,
        Capability.CAPTURE_LIST: ApplicationService._capture_list,
        Capability.CAPTURE_SEARCH: ApplicationService._capture_search,
        Capability.REVIEW_LIST: ApplicationService._review_list,
        Capability.REVIEW_DECIDE: ApplicationService._review_decide,
        Capability.CONTINUITY_PULSE: ApplicationService._continuity_pulse,
        Capability.CONTINUITY_SITUATIONS: ApplicationService._continuity_situations,
        Capability.CONTINUITY_PROJECTS: ApplicationService._continuity_projects,
        Capability.CONTINUITY_PROJECTS_CREATE: ApplicationService._continuity_projects_create,
        Capability.CONTINUITY_SITUATIONS_CREATE: ApplicationService._continuity_situations_create,
        Capability.CONTINUITY_TASKS_CREATE: ApplicationService._continuity_tasks_create,
        Capability.DOCUMENTS_CREATE: ApplicationService._documents_create,
        Capability.DOCUMENTS_REVISE: ApplicationService._documents_revise,
        Capability.DOCUMENTS_READ: ApplicationService._documents_read,
        Capability.DOCUMENTS_LIST: ApplicationService._documents_list,
        Capability.DOCUMENTS_ARCHIVE: ApplicationService._documents_archive,
        Capability.DOCUMENTS_RESTORE: ApplicationService._documents_restore,
        Capability.TASKS_READ: ApplicationService._tasks_read,
        Capability.TASKS_LIST: ApplicationService._tasks_list,
        Capability.TASKS_SEARCH: ApplicationService._tasks_search,
        Capability.TASKS_HISTORY: ApplicationService._tasks_history,
        Capability.TASKS_CREATE: ApplicationService._tasks_create,
        Capability.TASKS_UPDATE: ApplicationService._tasks_update,
        Capability.TASKS_TRANSITION: ApplicationService._tasks_transition,
        Capability.TASKS_BULK_PREVIEW: ApplicationService._tasks_bulk_preview,
        Capability.TASKS_BULK_CONFIRM: ApplicationService._tasks_bulk_confirm,
        Capability.COMMITMENTS_READ: ApplicationService._commitments_read,
        Capability.COMMITMENTS_LIST: ApplicationService._commitments_list,
        Capability.COMMITMENTS_WAITING_ON: ApplicationService._commitments_waiting_on,
        Capability.COMMITMENTS_CREATE: ApplicationService._commitments_create,
        Capability.COMMITMENTS_CLOSE: ApplicationService._commitments_close,
        Capability.CONTEXT_PREPARE: ApplicationService._context_prepare,
        Capability.CONTEXT_FEEDBACK: ApplicationService._context_feedback,
        Capability.GOODNOTES_WORK: ApplicationService._goodnotes_work,
        Capability.GOODNOTES_CONTENT: ApplicationService._goodnotes_content,
        Capability.GOODNOTES_PROPOSE: ApplicationService._goodnotes_propose,
        Capability.ENTITIES_SEARCH: ApplicationService._entities_search,
        Capability.ENTITIES_GET: ApplicationService._entities_get,
        Capability.ENTITIES_RESOLVE: ApplicationService._entities_resolve,
        Capability.ENTITIES_CONTEXT: ApplicationService._entities_context,
        Capability.ENTITIES_RELATIONSHIPS: ApplicationService._entities_relationships,
        Capability.ENTITIES_UNRESOLVED_MENTIONS: (ApplicationService._entities_unresolved_mentions),
    }
)

#: Which capabilities need a composed byte store. Written out rather than
#: derived from a name prefix, so admitting another is a decision here and not a
#: spelling that happens to start with `documents.`.
#: The entity plane's names, withheld from a process that has not enabled
#: it. Written out rather than derived from the `entities.` prefix, for the
#: reason `_MANAGED_CAPABILITIES` is: admitting another is a decision here and
#: not a spelling that happens to start the right way.
_ENTITY_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
    }
)

_MANAGED_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.DOCUMENTS_CREATE,
        Capability.DOCUMENTS_REVISE,
        Capability.DOCUMENTS_READ,
        Capability.DOCUMENTS_LIST,
        Capability.DOCUMENTS_ARCHIVE,
        Capability.DOCUMENTS_RESTORE,
    }
)
