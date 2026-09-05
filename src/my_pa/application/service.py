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
import binascii
import hashlib
import hmac
import json
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from itertools import islice
from types import MappingProxyType
from typing import Any, Final, NoReturn, assert_never, cast
from zoneinfo import ZoneInfo

from my_pa.application.authorization import Authorization, authorize
from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.application.commands import (
    AddEntityAddress,
    AddEntityAlias,
    AddEntityCommunicationMethod,
    AddEntityName,
    ArchiveEntity,
    ArchiveManagedDocument,
    ArchiveManagedDocumentCommand,
    ArchiveRelationshipMemory,
    BeginIntelligenceCycle,
    BindEntityIdentifier,
    BulkConfirmTasks,
    BulkPreviewTasks,
    CloseCommitment,
    Command,
    CommitIntelligenceArtifact,
    CompleteGoodNotesPull,
    CreateCapture,
    CreateCommitment,
    CreateEntity,
    CreateEntityAffiliation,
    CreateEntityAssignment,
    CreateEntityParticipation,
    CreateEntityProposal,
    CreateEntityRelationship,
    CreateManagedDocument,
    CreateManagedDocumentCommand,
    CreateProject,
    CreateRelationshipMemory,
    CreateSituation,
    CreateTask,
    DecideReviewCase,
    EndEntityAffiliation,
    EndEntityAssignment,
    EndEntityParticipation,
    EndEntityRelationship,
    EnrollSource,
    FetchSource,
    GetCanvasWorkspace,
    GetCapabilities,
    GetCommitmentHistory,
    GetCorpusCoverage,
    GetEntity,
    GetEntityContext,
    GetEntityGraph,
    GetEntityIdentityHistory,
    GetEntityProfile,
    GetEntityRelationships,
    GetGoodNotesContent,
    GetGoodNotesPullStatus,
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
    ListEntityAddresses,
    ListEntityAliases,
    ListEntityAssignments,
    ListEntityCommunicationMethods,
    ListEntityIdentifiers,
    ListEntityNames,
    ListEntityObservations,
    ListEntityParticipations,
    ListIntelligenceArtifacts,
    ListManagedDocuments,
    ListManagedDocumentsCommand,
    ListProjects,
    ListRelationshipMemories,
    ListReviewCases,
    ListSituations,
    ListSources,
    ListTasks,
    ListUnresolvedMentions,
    MergeEntities,
    ObserveEntityMention,
    PrepareContext,
    PreviewEntityMerge,
    PreviewEntitySplit,
    ProposeRelationshipMemory,
    PullGoodNotesWork,
    PutCanvasWorkspace,
    ReadCapture,
    ReadCommitment,
    ReadIntelligenceArtifact,
    ReadKnowledge,
    ReadManagedDocument,
    ReadManagedDocumentCommand,
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
    RestoreManagedDocumentCommand,
    RestoreRelationshipMemory,
    RetireEntityAddress,
    RetireEntityAlias,
    RetireEntityCommunicationMethod,
    RetireEntityIdentifier,
    RetireEntityName,
    RevealSubject,
    ReviseCapture,
    ReviseEntityAddress,
    ReviseEntityAffiliation,
    ReviseEntityAssignment,
    ReviseEntityCommunicationMethod,
    ReviseEntityParticipation,
    ReviseEntityRelationship,
    ReviseManagedDocument,
    ReviseManagedDocumentCommand,
    ReviseRelationshipMemory,
    SearchCaptures,
    SearchCommitments,
    SearchEntities,
    SearchIntelligenceArtifacts,
    SearchKnowledge,
    SearchRelationshipMemories,
    SearchTasks,
    SplitEntity,
    StartGsqsB0,
    SubmitGoodNotesProposal,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
    SupersedeEntityName,
    TransitionTask,
    UpdateCommitment,
    UpdateEntity,
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
from my_pa.application.entity_authoring import EntityAuthoringService, NamedValue
from my_pa.application.entity_context import EntityContextService
from my_pa.application.entity_directed import EntityDirectedService
from my_pa.application.entity_family_writes import EntityFamilyWriteService
from my_pa.application.entity_governance import (
    EntityGovernanceService,
    EntityProposalReviewService,
    IdentityCorrectionHandoffState,
    ObserveCommand,
    QuarantinedObservationError,
    ResolutionNotPermittedError,
    ResolveMentionCommand,
    ReviewAuthorityError,
    ReviewedPayloadSource,
    UnknownEntityError,
    UnknownObservationError,
)
from my_pa.application.entity_governance import (
    ProposedEvidence as EntityProposedEvidence,
)
from my_pa.application.entity_reenrichment import (
    TRIGGERS_BY_MUTATION_CAPABILITY,
    ProductionReenrichmentCaller,
    ReenrichmentWorkRepository,
    reenrichment_trigger_for_review_decision,
    register_mutation_reenrichment,
    register_producer_version_observation,
    register_source_version_observation,
)
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
from my_pa.application.goodnotes_gsqs_b0_workflow import (
    WorkflowPorts,
    default_repository_root,
    gsqs_b0_wait_in_process,
    start_workflow,
    status_workflow,
    workflow_root_from_env,
)
from my_pa.application.goodnotes_occurrences import (
    GoodNotesOccurrenceReconciler,
    GoodNotesOccurrenceRepository,
    OccurrenceReconcileBusyError,
)
from my_pa.application.goodnotes_pull_orchestration import (
    ERROR_INVALID_CURSOR,
    ERROR_INVALID_REQUEST,
    MAX_PULL_BATCH_SIZE,
    MAX_PULL_RETRIES,
    AuthenticatedPullContext,
    GoodNotesPullError,
    GoodNotesPullOrchestrator,
    GoodNotesPullRepository,
    PullCompletion,
    PullRequest,
    public_completion_receipts,
    public_pull_batch,
    stamp_authenticated_pull_context,
)
from my_pa.application.goodnotes_semantics import (
    fingerprint_proposal,
    lookup_work,
    proposal_payload,
    submit_proposal,
    work_payload,
)
from my_pa.application.identity_correction import (
    ConflictChoice,
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
    SplitCommand,
    SplitDisposition,
    SplitPreviewCommand,
)
from my_pa.application.identity_history import (
    IdentityHistoryCursorError,
    IdentityHistoryQuery,
    IdentityHistoryService,
)
from my_pa.application.intelligence import (
    begin_cycle,
    commit_artifact,
    latest_artifact,
    list_artifacts,
    read_artifact,
    record_run_state,
    resolve_set,
    search_artifacts,
)
from my_pa.application.managed_documents import ManagedDocumentService
from my_pa.application.model_gate import BoundedModelGate
from my_pa.application.producer_origin import ProducerOriginError, ProducerOriginRegistry
from my_pa.application.relationship_memory import (
    ArchiveMemoryCommand,
    CreateMemoryCommand,
    MemoryProposalOrigin,
    ProposedEvidence,
    ProposeMemoryCommand,
    RelationshipMemoryProposalService,
    RelationshipMemoryService,
    ReviseMemoryCommand,
)
from my_pa.application.tasks import TaskManagementService
from my_pa.contracts.ports import (
    Acceptance,
    AuthoringConflictError,
    BulkIdempotencyConflictError,
    CanvasWorkspaceConflictError,
    CanvasWorkspaceRecord,
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureSearchOutcome,
    CaptureSearchRequest,
    DirectedReceipt,
    EntitiesRepository,
    EntityMutationAdmission,
    EntitySummary,
    EvidenceUnavailableError,
    ManagedByteStore,
    MemoryDetail,
    MemoryListingFacts,
    MemoryPage,
    PortError,
    PreferenceConflictError,
    RelationshipMemoryRepository,
    ReviewDecisionRequest,
    SearchOutcome,
    UnitOfWork,
    UnknownScopeError,
    WorkCursorError,
    WriteRequestConflictError,
    WriteRequestEvidence,
    WriteRequestResult,
)
from my_pa.contracts.v1.canvas_workspace import (
    CanvasPointView,
    CanvasWorkspaceReceiptView,
    CanvasWorkspaceView,
)
from my_pa.contracts.v1.capabilities import EffectiveLimits, ReadinessReport, ReadinessState
from my_pa.contracts.v1.capture import CaptureListEntry, CaptureReceiptView, CaptureVersionView
from my_pa.contracts.v1.commitments import (
    CommitmentHistoryEntryView,
    CommitmentListEntry,
    CommitmentView,
    WaitingOnEntry,
)
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
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.reveal import EvidenceState
from my_pa.domain.capture.review import (
    Disposition,
    EntityProposalReviewCase,
    ReviewCase,
    ReviewConflictError,
    ReviewCorrectionError,
    ReviewDecision,
    ReviewNotFoundError,
    ReviewSubjectKind,
    ReviewUnsupportedError,
)
from my_pa.domain.capture.submission import CaptureKind, CaptureTransport
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
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
from my_pa.domain.goodnotes.models import GoodNotesReviewCase, GoodNotesSemanticReviewCase
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION
from my_pa.domain.relationship.authoring import (
    AmbiguousEntityError,
    ConflictedIdentifierError,
    DuplicateEntityFactError,
    EntityEvidenceError,
    EntityIdempotencyConflictError,
    HistoricalEntityError,
    StaleEntityVersionError,
    UnsettledBindingError,
)
from my_pa.domain.relationship.context_card import EntityContextCard
from my_pa.domain.relationship.entity import (
    ENTITY_PROFILE_COLLECTION_LIMIT,
    Assignment,
    DirectedWriteError,
    DuplicateDirectedFactError,
    Entity,
    EntityAddress,
    EntityAlias,
    EntityCommunicationMethod,
    EntityName,
    EntityOrganizationProfile,
    EntityProfileLimitation,
    EntityProjectParticipation,
    EntityRelationship,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    MergedEndpointError,
    PersonOrganizationAffiliation,
    StaleDirectedVersionError,
)
from my_pa.domain.relationship.governance import (
    IDENTITY_CORRECTION_PROPOSAL_KINDS,
    ActorClass,
    EntityMutationConflictError,
    EntityObservation,
    EntityProposalMethod,
    EvidenceRole,
    ObservationAuthorityError,
    ObservationTimeError,
    StaleResolutionVersionError,
    origin_of,
)
from my_pa.domain.relationship.identity_correction import (
    AmbiguityDisposition,
    IdentityConflict,
)
from my_pa.domain.relationship.memory import (
    EvidenceLinkRole,
    MemoryAdmission,
    MemoryBoundsError,
    MemoryConflictError,
    MemoryKind,
    MemoryKindNotPermittedError,
    MemoryProposalMethod,
    MemoryStructuredValueError,
    MergedSubjectError,
    RelationshipMemory,
    RelationshipMemoryError,
    RelationshipMemoryReviewCase,
    RelationshipMemoryVersion,
    StaleMemoryVersionError,
)
from my_pa.domain.relationship.normalization import NormalizationError
from my_pa.domain.relationship.proposal_payload import EntityProposalPayload, ProposalPayloadError
from my_pa.domain.relationship.reenrichment import (
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
)
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
from my_pa.domain.situation.continuity import CommitmentWorkView
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
from my_pa.domain.task.bulk import TaskBulkOperation
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry
from my_pa.domain.task.history import TaskHistoryEntry as TaskManagementHistoryEntry
from my_pa.domain.task.history import (
    TaskMutationAction,
    TaskMutationActor,
    TaskMutationOutcome,
)
from my_pa.domain.task.lifecycle import (
    TERMINAL_TASK_LIFECYCLE_STATES,
    TaskLifecycleState,
    TaskPriority,
    TaskWorkView,
)
from my_pa.domain.task.role import TaskRole
from my_pa.domain.task.task import Task as TaskManagementTask

__all__ = ["ApplicationService", "published_capabilities"]

#: The absence of truncation, as one shared immutable value. A default argument
#: may not be a constructor call, and a frozen contract model is safe to share.
_NO_TRUNCATION: Final = Truncation()


@dataclass(frozen=True, slots=True)
class _Result:
    """One capability's payload and the envelope that must accompany it."""

    payload: dict[str, Any]
    disclosure: Disclosure
    # Internal mutation evidence for durable re-enrichment registration. This
    # never enters the response envelope. Absence means this invocation did not
    # create a new authoritative mutation (including replay and no-op success).
    reenrichment_cause_id: str | None = None


class _CommitRejectedConflictError(Exception):
    """Carry one verified rejected-only conflict out after the shared UoW commits."""

    def __init__(self, failure: ConflictError) -> None:
        super().__init__("commit verified rejected conflict history")
        self.failure = failure


#: What a memory answer rests on: the Principal's own partition, exactly as the
#: entity plane's does. Not `configured_interface`, which is what a capability
#: description rests on, and not a source provider, which a memory never has.
_MEMORY_TRUST_BASIS: Final = ("principal_partition",)


@contextmanager
def _memory_translated() -> Iterator[None]:
    """Classify the Relationship Memory domain's refusals as public errors.

    Separate from `_translated` because these are domain rules rather than port
    failures, and each maps to a different public class: a stale expectation and
    a duplicate key are both `conflict`, a merged-away subject is a `conflict`
    that also has somewhere to point, and a bad kind, statement or structured
    value is `invalid_request`. `MergedSubjectError` names the canonical entity
    in the safe details rather than in a message, so a caller learns *that* it
    must retarget without the error string carrying an identifier.
    """
    try:
        yield
    except StaleMemoryVersionError:
        raise ConflictError(SafeDetail.EXPECTED_VERSION) from None
    except MemoryConflictError:
        raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
    except MergedSubjectError:
        raise ConflictError(SafeDetail.SUBJECT_ENTITY_ID) from None
    except MemoryKindNotPermittedError:
        raise InvalidRequestError(SafeDetail.MEMORY_KIND) from None
    except MemoryStructuredValueError:
        raise InvalidRequestError(SafeDetail.STRUCTURED_VALUE) from None
    except MemoryBoundsError:
        raise InvalidRequestError(SafeDetail.STATEMENT) from None
    except RelationshipMemoryError:
        raise InvalidRequestError(SafeDetail.SUBJECT) from None


def _memory_links(links: tuple[dict[str, object], ...]) -> tuple[dict[str, str], ...]:
    """The command's context links as the use case takes them."""
    return tuple({key: str(value) for key, value in link.items()} for link in links)


def _memory_kinds(kinds: tuple[MemoryKind, ...] | None) -> frozenset[MemoryKind] | None:
    """The command's kind filter as the repository takes it."""
    return None if kinds is None else frozenset(kinds)


def _memory_summary_view(
    memory: RelationshipMemory, current: MemoryListingFacts, *, include_statement: bool
) -> dict[str, Any]:
    """One memory as a listing discloses it.

    **`authority` and `classification` are unconditional, and `statement` is
    not.** The statement is the note itself and the caller says whether it wants
    it; the other two are metadata about where the note came from and how far it
    may travel, and withholding them would leave a promoted
    `source_backed_assertion` looking exactly like the user's own
    `user_authored_private_note`. The primary reader of this plane is an
    assistant deciding whether it may present a line as something it knows or
    only as something the user once wrote, and that decision is made from
    `authority`. A listing that dropped it made the two indistinguishable —
    which is the distinction ADR-003 exists to preserve — so it is not gated on
    `include_statement` and has no way to be absent.

    `current` is required rather than optional for the same reason. A page
    guarantees one facts record per disclosed memory, so an absent one is a
    repository defect and not a caller's choice; taking `None` here would let
    that defect render as a row with no provenance, which is precisely the
    silent outcome the field exists to prevent.
    """
    view: dict[str, Any] = {
        "memory_id": memory.memory_id,
        "subject_entity_id": memory.subject_entity_id,
        "kind": memory.memory_kind.value,
        "authority": current.authority.value,
        "classification": current.classification.value,
        "lifecycle": memory.lifecycle_state.value,
        "version": memory.version,
        "current_version_number": memory.current_version_number,
        "pinned": memory.pinned,
        "created_at": format_rfc3339(memory.created_at),
        "updated_at": format_rfc3339(memory.updated_at),
    }
    if include_statement:
        view["statement"] = current.statement
    return view


def _memory_version_view(version: RelationshipMemoryVersion) -> dict[str, Any]:
    """One immutable version as history discloses it."""
    return {
        "memory_version_id": version.memory_version_id,
        "version_number": version.version_number,
        "statement": version.statement,
        "statement_sha256": version.statement_sha256,
        "structured_value": version.structured_value,
        "kind": version.memory_kind.value,
        "authority": version.authority.value,
        "classification": version.classification.value,
        "cloud_eligible": version.cloud_eligible,
        "recorded_by": version.created_by_actor.value,
        "recorded_at": format_rfc3339(version.recorded_at),
        "observed_at": _memory_moment(version.observed_at),
        "effective_from": _memory_moment(version.effective_from),
        "effective_to": _memory_moment(version.effective_to),
        "prior_version_id": version.prior_version_id,
        "correction_reason": version.correction_reason,
    }


def _memory_moment(moment: datetime | None) -> str | None:
    """An optional instant, still optional. An unknown time stays unknown."""
    return None if moment is None else format_rfc3339(moment)


def _memory_view(detail: MemoryDetail, *, include_statement: bool) -> dict[str, Any]:
    """One memory as `relationship_memory.get` discloses it.

    Built on the listing view, so `get` gains the same top-level `authority` and
    `classification` a listing now carries. That duplicates two values already
    nested under `current_version`, and the duplication is the point: a caller
    that reads one memory and a caller that reads a page of them read the same
    keys in the same place, so a client cannot be written against a shape that
    only one of the two answers with. The two spellings cannot disagree because
    both are read from this one `current_version`.
    """
    view = _memory_summary_view(
        detail.memory,
        MemoryListingFacts(
            statement=detail.current_version.statement,
            authority=detail.current_version.authority,
            classification=detail.current_version.classification,
        ),
        include_statement=include_statement,
    )
    view["current_version"] = _memory_version_view(detail.current_version)
    if not include_statement:
        view["current_version"].pop("statement")
    view["context_links"] = [
        {
            "target_type": link.target_type.value,
            "target_id": link.target_id,
            "role": link.role.value,
            "authority": link.authority.value,
        }
        for link in detail.context_links
    ]
    view["evidence_count"] = detail.evidence_count
    # Present only when the subject has actually been merged away, so a caller
    # cannot read "the subject is current" from the field's absence *and* from
    # its null — one spelling, one meaning.
    if detail.canonical_entity_id is not None:
        view["canonical_subject_entity_id"] = detail.canonical_entity_id
    return view


_REVIEW_CURSOR_ORDER: Final = "opened_at_asc_review_case_id_asc_v1"
_MAX_REVIEW_CURSOR_CHARACTERS: Final = 512


def _review_cursor_binding(
    *,
    principal_id: str,
    page_size: int,
    subject_kind: ReviewSubjectKind | None,
    state: ProposalState | None,
    entity_id: str | None,
) -> str:
    """Bind a continuation to every input that gives its position meaning."""
    canonical = json.dumps(
        {
            "entity_id": entity_id,
            "order": _REVIEW_CURSOR_ORDER,
            "page_size": page_size,
            "principal_id": principal_id,
            "state": None if state is None else state.value,
            "subject_kind": None if subject_kind is None else subject_kind.value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _encode_review_cursor(*, binding: str, opened_at: datetime, review_case_id: str) -> str:
    """Encode one text-free keyset position using the repository cursor shape."""
    payload = json.dumps(
        {
            "b": binding,
            "o": format_rfc3339(opened_at),
            "r": review_case_id,
            "v": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii").rstrip("=")


def _decode_review_cursor(token: str, *, expected_binding: str) -> tuple[datetime, str] | None:
    """Decode one bound position; every malformed or mismatched token is identical."""
    if not token or len(token) > _MAX_REVIEW_CURSOR_CHARACTERS:
        return None
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = json.loads(
            base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        )
    except (binascii.Error, UnicodeEncodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(decoded, dict) or set(decoded) != {"b", "o", "r", "v"}:
        return None
    binding, opened_value, review_case_id, version = (
        decoded["b"],
        decoded["o"],
        decoded["r"],
        decoded["v"],
    )
    if (
        binding != expected_binding
        or not isinstance(opened_value, str)
        or not isinstance(review_case_id, str)
        or version != 1
    ):
        return None
    try:
        opened_at = datetime.fromisoformat(opened_value)
        if opened_at.tzinfo is None:
            return None
        validate_identifier(review_case_id, IdKind.REVIEW_CASE)
    except (InvalidIdentifierError, ValueError, OverflowError):
        return None
    return opened_at.astimezone(UTC), review_case_id


def _review_case_payload(
    case: ReviewCase
    | GoodNotesReviewCase
    | GoodNotesSemanticReviewCase
    | RelationshipMemoryReviewCase
    | EntityProposalReviewCase,
) -> dict[str, Any]:
    """One review case as the contract may disclose it, whatever its subject kind.

    **No branch discloses the subject's text, and the Relationship Memory branch
    is where that rule had to be decided rather than inherited.** A capture case
    names its capture and version; a GoodNotes case names its region and page
    version; neither hands the reviewer the words. A memory candidate's words are
    the private thing this whole plane exists to protect, and a `sensitivity`
    proposal's are the most protected of them: the accepted form of that
    statement floors at `RESTRICTED_LOCAL`, which `relationship_memory.search`
    excludes by predicate and the context card withholds and merely counts. A
    listing that printed the *proposed* text would disclose, to any caller of
    `review.cases`, exactly the sentence the memory capabilities refuse to
    return — and it would do so on a read that carries no eligibility decision
    to make it with. `RelationshipMemoryReviewCase` therefore has no statement
    field at all, so this is structural and not a formatting choice.

    What the branch does disclose is what a decision needs: which entity the
    candidate is about, what kind of statement it would become, and — once
    accepted — the memory identity it produced, so the reviewer can follow their
    own decision to its result through the memory plane, where classification is
    enforced. Disclosing `proposed_kind` is deliberate: a reviewer asked to
    accept a sensitivity has to know that is what they are accepting.

    **The Entity branch follows the same rule and adds one field to it.** An
    Entity proposal's payload is a producer's assertion about a person — the
    display name a rule inferred, the external address a source claimed — and
    `EntityProposalReviewCase` carries none of it, structurally rather than by
    omission here. What it adds is `method`: `deterministic`, `rule` or
    `local_model`. A reviewer being asked to accept a local model's conclusion
    has to know that is what they are accepting, which is the same argument
    `proposed_kind` makes one branch up and is the whole of section 21.4's
    anti-laundering rule read from the reviewer's side. `escalated` is disclosed
    for the same reason: a case that has been raised to the operator ceiling
    looks identical to one that has not unless the listing says so.
    """
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
            "subject_kind": ReviewSubjectKind.GOODNOTES_REGION.value,
            "region_id": case.region_id,
            "page_version_id": case.page_version_id,
            "confidence": case.confidence,
        }
    if isinstance(case, GoodNotesSemanticReviewCase):
        return {
            **common,
            "subject_kind": ReviewSubjectKind.GOODNOTES_SEMANTIC.value,
            "run_id": case.run_id,
            "page_version_id": case.page_version_id,
        }
    if isinstance(case, RelationshipMemoryReviewCase):
        return {
            **common,
            "subject_kind": ReviewSubjectKind.RELATIONSHIP_MEMORY.value,
            "subject_entity_id": case.subject_entity_id,
            "proposed_kind": case.proposed_kind.value,
            "accepted_memory_id": case.accepted_memory_id,
            "accepted_memory_version_id": case.accepted_memory_version_id,
        }
    if isinstance(case, EntityProposalReviewCase):
        return {
            **common,
            "subject_kind": ReviewSubjectKind.ENTITY_PROPOSAL.value,
            "subject_entity_id": case.target_entity_id,
            "proposed_kind": case.proposed_kind.value,
            "method": case.method.value,
            "escalated": case.escalated,
            "accepted_record_id": case.accepted_record_id,
        }
    return {
        **common,
        "subject_kind": ReviewSubjectKind.CAPTURE_PROPOSAL.value,
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


def _canvas_point_views(
    positions: Mapping[str, Mapping[str, float]],
) -> dict[str, CanvasPointView]:
    return {
        entity_id: CanvasPointView(x=point["x"], y=point["y"])
        for entity_id, point in positions.items()
    }


def _canvas_positions_equal(
    left: Mapping[str, Mapping[str, float]],
    right: Mapping[str, Mapping[str, float]],
) -> bool:
    if set(left) != set(right):
        return False
    return all(
        float(left[key]["x"]) == float(right[key]["x"])
        and float(left[key]["y"]) == float(right[key]["y"])
        for key in left
    )


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
        origin_evidence_ref=task.origin_evidence_ref,
        closure_evidence_ref=task.closure_evidence_ref,
        accepted_by_review_decision_id=task.accepted_by_review_decision_id,
        acceptance_kind=task.acceptance_kind,
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
        scheduled_at=task.scheduled_at,
        deferred_until=task.deferred_until,
        archived_at=task.archived_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        version=task.version,
    )


def _work_window(
    work_date: date, timezone: str, *, recent: bool = False
) -> tuple[datetime, datetime]:
    """Return DST-correct UTC bounds for one civil day or its seven-day lookback."""
    zone = ZoneInfo(timezone)
    first_date = work_date - timedelta(days=6) if recent else work_date
    local_start = datetime.combine(first_date, datetime.min.time(), zone)
    local_end = datetime.combine(work_date + timedelta(days=1), datetime.min.time(), zone)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


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
        direction=commitment.direction.value,
        state=commitment.state.value,
        counterparty_person_id=commitment.counterparty_person_id,
        title=commitment.summary,
        description=None,
        due_date=commitment.due_at.isoformat() if commitment.due_at is not None else None,
        created_at=commitment.created_at.isoformat(),
        updated_at=commitment.updated_at.isoformat(),
        version=commitment.version,
        evidence_state=commitment.evidence_state.value,
        origin_evidence_ref=commitment.origin_evidence_ref,
        closure_evidence_ref=commitment.closure_evidence_ref,
        accepted_by_review_decision_id=commitment.accepted_by_review_decision_id,
        closed_at=commitment.closed_at.isoformat() if commitment.closed_at is not None else None,
    )


def _commitment_list_entry(commitment: Commitment) -> CommitmentListEntry:
    return CommitmentListEntry(
        commitment_id=commitment.commitment_id,
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


_COUNTERPARTY_OPTION_LIMIT: Final = 100


def _counterparty_projection(
    unit_of_work: UnitOfWork, principal_id: str, person_id: str
) -> dict[str, str] | None:
    option = unit_of_work.commitments.counterparty(principal_id, person_id)
    if option is None:
        return None
    return {"person_id": option.person_id, "display_name": option.display_name}


def _counterparty_options(
    unit_of_work: UnitOfWork, principal_id: str
) -> tuple[list[dict[str, str]], bool]:
    found = unit_of_work.commitments.list_counterparties(
        principal_id, limit=_COUNTERPARTY_OPTION_LIMIT + 1
    )
    truncated = len(found) > _COUNTERPARTY_OPTION_LIMIT
    return (
        [
            {"person_id": option.person_id, "display_name": option.display_name}
            for option in found[:_COUNTERPARTY_OPTION_LIMIT]
        ],
        truncated,
    )


def _commitment_public_view(
    unit_of_work: UnitOfWork, principal_id: str, commitment: Commitment
) -> dict[str, object]:
    result = _commitment_view(commitment).to_canonical_dict()
    result["counterparty"] = _counterparty_projection(
        unit_of_work, principal_id, commitment.counterparty_person_id
    )
    return result


def _commitment_public_list_entry(
    unit_of_work: UnitOfWork, principal_id: str, commitment: Commitment
) -> dict[str, object]:
    result = _commitment_list_entry(commitment).to_canonical_dict()
    result["counterparty"] = _counterparty_projection(
        unit_of_work, principal_id, commitment.counterparty_person_id
    )
    return result


def _normalise_bulk_mutations(
    raw_mutations: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], str]:
    """Strictly normalise the bounded bulk vocabulary and hash that exact shape."""
    normalised: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_mutations:
        kind = raw.get("kind")
        task_id = raw.get("task_id")
        expected_version = raw.get("expected_version")
        if kind not in {"update", "transition"} or not isinstance(task_id, str):
            raise InvalidRequestError(SafeDetail.MUTATIONS)
        try:
            validate_identifier(task_id, IdKind.TASK)
        except ValueError:
            raise InvalidRequestError(SafeDetail.MUTATIONS) from None
        if task_id in seen or type(expected_version) is not int or expected_version < 1:
            raise InvalidRequestError(SafeDetail.MUTATIONS)
        seen.add(task_id)
        if kind == "update":
            if set(raw) != {"kind", "task_id", "expected_version", "values", "clear_fields"}:
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            values = raw.get("values")
            clear_fields = raw.get("clear_fields")
            if not isinstance(values, dict) or not isinstance(clear_fields, (list, tuple)):
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            allowed = {
                "title",
                "description",
                "priority",
                "due_at",
                "scheduled_at",
                "deferred_until",
                "commitment_id",
                "role",
                "archived",
            }
            clearable = allowed - {"title", "archived"}
            if not set(values) <= allowed or any(
                not isinstance(item, str) or item not in clearable for item in clear_fields
            ):
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            if set(values) & set(clear_fields) or len(set(clear_fields)) != len(clear_fields):
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            converted: dict[str, object] = {}
            for name, value in values.items():
                if name == "title":
                    if not isinstance(value, str) or not value.strip():
                        raise InvalidRequestError(SafeDetail.MUTATIONS)
                    converted[name] = value.strip()
                elif name == "description":
                    if not isinstance(value, str):
                        raise InvalidRequestError(SafeDetail.MUTATIONS)
                    converted[name] = value
                elif name == "priority":
                    try:
                        converted[name] = TaskPriority(value).value
                    except (TypeError, ValueError):
                        raise InvalidRequestError(SafeDetail.MUTATIONS) from None
                elif name in {"due_at", "scheduled_at", "deferred_until"}:
                    if not isinstance(value, str):
                        raise InvalidRequestError(SafeDetail.MUTATIONS)
                    try:
                        moment = datetime.fromisoformat(value)
                    except ValueError:
                        raise InvalidRequestError(SafeDetail.MUTATIONS) from None
                    if moment.tzinfo is None or moment.utcoffset() is None:
                        raise InvalidRequestError(SafeDetail.MUTATIONS)
                    converted[name] = moment.isoformat()
                elif name == "commitment_id":
                    if not isinstance(value, str):
                        raise InvalidRequestError(SafeDetail.MUTATIONS)
                    try:
                        validate_identifier(value, IdKind.COMMITMENT)
                    except ValueError:
                        raise InvalidRequestError(SafeDetail.MUTATIONS) from None
                    converted[name] = value
                elif name == "role":
                    try:
                        converted[name] = TaskRole(value).value
                    except (TypeError, ValueError):
                        raise InvalidRequestError(SafeDetail.MUTATIONS) from None
                else:
                    if type(value) is not bool:
                        raise InvalidRequestError(SafeDetail.MUTATIONS)
                    converted[name] = value
            if not converted and not clear_fields:
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            normalised.append(
                {
                    "kind": kind,
                    "task_id": task_id,
                    "expected_version": expected_version,
                    "values": converted,
                    "clear_fields": sorted(clear_fields),
                }
            )
        else:
            allowed_keys = {
                "kind",
                "task_id",
                "expected_version",
                "to_state",
                "closure_evidence_ref",
            }
            if not set(raw) <= allowed_keys or "to_state" not in raw:
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            raw_to_state = raw["to_state"]
            if not isinstance(raw_to_state, str):
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            try:
                to_state = TaskLifecycleState(raw_to_state).value
            except (TypeError, ValueError):
                raise InvalidRequestError(SafeDetail.MUTATIONS) from None
            closure = raw.get("closure_evidence_ref")
            if closure is not None and (not isinstance(closure, str) or not closure.strip()):
                raise InvalidRequestError(SafeDetail.MUTATIONS)
            normalised.append(
                {
                    "kind": kind,
                    "task_id": task_id,
                    "expected_version": expected_version,
                    "to_state": to_state,
                    "closure_evidence_ref": closure,
                }
            )
    canonical = json.dumps(normalised, sort_keys=True, separators=(",", ":"))
    return tuple(normalised), hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bulk_candidate(
    task: TaskManagementTask, mutation: dict[str, object], *, now: datetime
) -> TaskManagementTask:
    """Apply one already-normalised bulk item in memory."""
    if mutation["kind"] == "update":
        values = cast(dict[str, object], mutation["values"])
        replacements: dict[str, object] = {}
        for name, value in values.items():
            if name in {"due_at", "scheduled_at", "deferred_until"}:
                replacements[name] = datetime.fromisoformat(str(value))
            elif name == "priority":
                replacements[name] = TaskPriority(str(value))
            elif name == "role":
                replacements[name] = TaskRole(str(value))
            elif name == "archived":
                replacements["archived_at"] = now if value else None
            else:
                replacements[name] = value
        replacements.update(dict.fromkeys(cast(list[str], mutation["clear_fields"])))
        if replacements.get("commitment_id", task.commitment_id) is None:
            replacements["role"] = None
        proposed = replace(task, **replacements)  # type: ignore[arg-type]
    else:
        to_state = TaskLifecycleState(str(mutation["to_state"]))
        unchanged = task.lifecycle_state is to_state
        if task.lifecycle_state in TERMINAL_TASK_LIFECYCLE_STATES and not unchanged:
            raise InvalidRequestError(SafeDetail.MUTATIONS)
        closure = mutation.get("closure_evidence_ref")
        if to_state in TERMINAL_TASK_LIFECYCLE_STATES and not unchanged:
            if not isinstance(closure, str) or not closure.strip():
                raise InvalidRequestError(SafeDetail.INVALID_EVIDENCE_REFERENCE)
            proposed = replace(
                task,
                lifecycle_state=to_state,
                closed_at=now,
                closure_evidence_ref=closure,
            )
        else:
            proposed = replace(task, lifecycle_state=to_state)
    if proposed == task:
        return task
    return replace(proposed, version=task.version + 1, updated_at=now)


def _task_commitment_state(
    task: TaskManagementTask | None,
    *,
    values: dict[str, object],
    clear_fields: frozenset[str] = frozenset(),
) -> tuple[str | None, TaskRole | None]:
    """Resolve the final Task link/role shape before any write is attempted."""
    commitment_id = None if task is None else task.commitment_id
    role = None if task is None else task.role
    if "commitment_id" in clear_fields:
        commitment_id = None
    elif "commitment_id" in values:
        commitment_id = cast(str, values["commitment_id"])
    if "role" in clear_fields:
        role = None
    elif "role" in values:
        raw_role = values["role"]
        role = raw_role if isinstance(raw_role, TaskRole) else TaskRole(str(raw_role))
    if commitment_id is None:
        # Clearing a link clears its dependent role atomically.
        role = None if "commitment_id" in clear_fields else role
    return commitment_id, role


def _validate_task_commitment_state(
    unit_of_work: UnitOfWork,
    principal_id: str,
    commitment_id: str | None,
    role: TaskRole | None,
) -> None:
    """Validate the shared same-Principal Commitment/link invariant."""
    if role is TaskRole.FOLLOW_UP and commitment_id is None:
        raise InvalidRequestError(SafeDetail.SELECTOR)
    if (
        commitment_id is not None
        and unit_of_work.commitments.get(principal_id, commitment_id) is None
    ):
        # The Principal-qualified lookup deliberately collapses foreign and
        # absent Commitments into the same safe result.
        raise NotFoundError(SafeDetail.COMMITMENT_ID)


def _commitment_history_view(entry: CommitmentHistoryEntry) -> CommitmentHistoryEntryView:
    return CommitmentHistoryEntryView(
        history_id=entry.history_id,
        commitment_id=entry.commitment_id,
        action=entry.action.value,
        actor=entry.actor.value,
        outcome=entry.outcome.value,
        before_version=entry.before_version,
        after_version=entry.after_version,
        occurred_at=entry.occurred_at.isoformat(),
        recorded_at=entry.recorded_at.isoformat(),
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


@contextmanager
def _entity_translated() -> Iterator[None]:
    """Classify what the entity plane's paged reads refuse.

    Inside `_translated`, for the same reason `_managed_translated` is: that one
    turns every `UnknownScopeError` into the enrollment-shaped `not_found` most
    capabilities want, and **this plane has no enrollments at all**. An entity
    carries no enrollment a scope could be compared against, which is the whole
    argument for its unenrolled trust basis — so answering `not_found` naming
    `enrollment_id` names a field the request does not have and the plane does
    not model.

    The three paged reads raise `UnknownScopeError` for exactly one reason: a
    cursor that names a record this Principal cannot read. `cursor` is
    therefore what the answer names, and it is the same field the command
    already names when the cursor is *malformed* — so a caller sees one field
    for one problem, differing only in whether the request was badly formed or
    the position was not theirs.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except UnknownScopeError:
        failure = NotFoundError(SafeDetail.CURSOR)
    if failure is not None:
        raise failure


@contextmanager
def _entity_authoring_translated() -> Iterator[None]:
    """Classify what the entity plane's governed writes refuse (WP-RI-A-02).

    Inside `_translated`, for the reason `_entity_translated` is: an
    `UnknownScopeError` from this plane means "no such entity, identifier or
    alias in this partition", and reporting `enrollment_id` for it would name a
    field the request does not have and the plane does not model.

    **Eight refusals, eight tokens, and the tokens are the contract's own.** The
    public code alone cannot separate them -- a stale version, a spent
    idempotency key, a duplicated fact and an address two entities claim are all
    `conflict`, and a caller told only `conflict` has to guess which of four
    different next actions applies. So each carries the stable code the
    completion contract fixes, on the existing `safe_details` mechanism rather
    than as a new `ErrorCode` member.

    **`UnsettledBindingError` is `unavailable`, not `conflict`, and that is the
    distinction this block exists for.** Both it and `ConflictedIdentifierError`
    reach here as `ValueError` subclasses raised by the same method, differing
    until now only by message. One is permanent -- an address that belongs to
    somebody else, which no retry will free -- and the other is a bounded
    retry-exhaustion against a concurrent retirement, where the address may
    already be free. A caller told `conflict` for the second abandons a write
    that would have succeeded; `unavailable` carries retry guidance and says so.

    `NormalizationError` is `invalid_request` and names the field it arrived in:
    a value that cannot be normalized is a value the caller can correct, and it
    is refused before any row is read rather than stored in a form the
    resolver's equality predicate could never match.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except UnknownScopeError:
        failure = NotFoundError(SafeDetail.ENTITY_ID)
    except StaleEntityVersionError:
        failure = ConflictError(SafeDetail.STALE_VERSION)
    except EntityIdempotencyConflictError:
        failure = ConflictError(SafeDetail.IDEMPOTENCY_CONFLICT)
    except ConflictedIdentifierError:
        failure = ConflictError(SafeDetail.CONFLICTED_IDENTIFIER)
    except UnsettledBindingError:
        failure = UnavailableError(SafeDetail.CONCURRENT_RETIREMENT)
    except HistoricalEntityError:
        failure = ConflictError(SafeDetail.HISTORICAL_ENTITY)
    except AmbiguousEntityError:
        failure = AmbiguousRequestError(SafeDetail.AMBIGUOUS_IDENTITY)
    except DuplicateEntityFactError:
        failure = ConflictError(SafeDetail.DUPLICATE_FACT)
    except EntityEvidenceError:
        failure = InvalidRequestError(SafeDetail.EVIDENCE_INVALID)
    except NormalizationError:
        failure = InvalidRequestError(SafeDetail.DISPLAY_VALUE)
    if failure is not None:
        raise failure


@contextmanager
def _directed_translated() -> Iterator[None]:
    """Classify what the entity plane's directed writes refuse.

    Five refusals, four public codes, and none of them is decided here. A stale
    expectation -- of the record's own version or of an endpoint's -- is
    `conflict`, because the caller read something and the world moved. A
    duplicate active semantic key is `conflict` for the same reason and names
    the record family rather than the row, because naming the existing row would
    disclose an identifier the request did not ask for. A merged-away endpoint is
    `conflict` and names the field, so a caller learns *that* it must retarget
    without the message carrying an identifier. Anything else this vocabulary
    raises is a malformed request.

    **The three stale cases share `EXPECTED_VERSION` deliberately.** A caller
    that could tell "your assignment is stale" from "the scope entity is stale"
    would learn, from a refusal, that the scope entity exists -- and it is the
    one endpoint a caller may name without having read it. The detail names the
    field the caller supplied and not which of them was wrong.

    **`UnknownScopeError` is caught here rather than left to
    `_entity_translated`.** That one answers `not_found` naming `cursor`, which
    is right for the three paged reads it was written for and names a field a
    write does not have. A directed write reaches it for three different reasons
    -- an entity, an assignment or edge, or a cited observation outside this
    partition -- and all three answer `not_found` naming `subject`: absent and
    foreign are one answer, and *which* named thing was unreachable is itself
    something a caller could subtract to learn what another Principal holds.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except UnknownScopeError:
        failure = NotFoundError(SafeDetail.SUBJECT)
    except StaleDirectedVersionError:
        failure = ConflictError(SafeDetail.EXPECTED_VERSION)
    except DuplicateDirectedFactError:
        failure = ConflictError(SafeDetail.SUBJECT)
    except MergedEndpointError:
        failure = ConflictError(SafeDetail.ENTITY_ID)
    except DirectedWriteError:
        failure = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
    if failure is not None:
        raise failure


@contextmanager
def _record_family_translated() -> Iterator[None]:
    """The one refusal `RI-ENT-WP-11`'s writes add to the directed vocabulary.

    Stacked *inside* `_directed_translated`, and it carries exactly one clause
    because the rest of what these writes refuse is already that one's. The five
    record families raise `UnknownScopeError` for a row outside this partition
    and `StaleDirectedVersionError` for a version that moved, from the same
    `_refuse_stale_or_absent` the directed writes reach -- so absent-or-foreign
    is `not_found` naming `subject` and a stale expectation is `conflict` naming
    `expected_version`, in one place rather than two that could drift apart.

    What is new is the ledger write. `EntityRecordFamilyService` holds no
    idempotency key, so the key is arbitrated by
    `record_mutation_event`, whose refusal for a key held against a *different*
    request is `EntityMutationConflictError` rather than the
    `DirectedWriteError` the directed plane's own writer raises. Both are the
    same fact about the same table and both answer `conflict` naming
    `idempotency_key`: a caller told anything else would refresh the wrong thing.

    **Not shared with `_entity_governance_translated`, which already classifies
    `EntityMutationConflictError` the same way.** That contextmanager catches
    seven further refusals belonging to the observation, resolution and proposal
    surfaces -- `QuarantinedObservationError`, `ResolutionNotPermittedError`,
    `ProposalPayloadError` and their neighbours -- none of which these writes can
    raise, and stacking it here would put this plane behind a translator whose
    next clause is about a plane it does not touch.

    **What this deliberately does not catch: the driver's own `IntegrityError`
    from a family's active partial unique.** A correction whose successor
    collides with a third active row of the same type and normalized value
    surfaces that today, untranslated, exactly as `EntityRecordFamilyService`'s
    own docstrings say it does out of `record_name`. It is not caught here
    because it cannot be: the application layer holds no `sqlalchemy`, so the
    only place to classify a constraint violation is the persistence adapter --
    the five families' inserts are `RI-ENT-WP-08`'s and are under review, and
    reclassifying their refusals is that package's change to make, not this
    one's. The consequence is stated rather than hidden: such a collision reaches
    `invoke`'s terminal catch and answers `internal_error`, which is the wrong
    class for a conflict a caller could act on, and is recorded as a limitation.
    The one violation `RI-ENT-WP-11` itself introduces -- two writers racing for
    one idempotency key -- *is* classified, by
    `SqlEntityRepository.record_mutation_event`'s
    `_duplicate_translated(_MUTATION_KEY_UNIQUE)`, and arrives here as the
    `DirectedWriteError` the clause above already answers.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except EntityMutationConflictError:
        failure = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
    if failure is not None:
        raise failure


def _named_values(supplied: tuple[dict[str, str], ...], kind_field: str) -> tuple[NamedValue, ...]:
    """The create command's alias and identifier objects as the use case takes them."""
    return tuple(
        NamedValue(kind=item[kind_field], value=item["display_value"]) for item in supplied
    )


def _lifecycle_identifier_view(identifier: ExternalIdentifier) -> dict[str, object]:
    """One binding as `entities.identifiers.list` discloses it.

    Wider than `_identifier_view`, which is the *context card's* shape: this read
    exists so a caller can drive `retire` and `supersede`, and both of those need
    the binding's own version and its state. A listing that withheld either would
    publish a lifecycle a caller could see and not act on.
    """
    return {
        **_identifier_view(identifier),
        "state": identifier.state.value,
        "version": identifier.version,
        "retired_at": _moment_or_none(identifier.retired_at),
        "updated_at": _moment_or_none(identifier.updated_at),
        "superseded_by_identifier_id": identifier.superseded_by_identifier_id,
    }


def _lifecycle_alias_view(alias: EntityAlias) -> dict[str, object]:
    """One recorded name form as `entities.aliases.list` discloses it."""
    return {
        **_alias_view(alias),
        "state": alias.state.value,
        "version": alias.version,
        "retired_at": _moment_or_none(alias.retired_at),
        "updated_at": _moment_or_none(alias.updated_at),
        "superseded_by_alias_id": alias.superseded_by_alias_id,
    }


@contextmanager
def _entity_governance_translated() -> Iterator[None]:
    """Classify what the governed half of the entity plane refuses.

    The contract fixes eight stable problems for this surface, and every one of
    them is expressed as an existing `ErrorCode` plus a `safe_details` token
    rather than as a new code. A twelfth `ErrorCode` member would make every
    reader that switches on the eleven wrong about a plane it has never heard
    of; the token says which rule refused and the code says what class of
    failure it is, which is the division `safe_details` exists for.

    * `ambiguous_identity` -> `ambiguous_request`. It is the one refusal whose
      honest guidance is `after_explicit_choice`: somebody has to say which.
    * `conflicted_identifier`, `historical_entity`, `review_required`,
      `stale_version` and `idempotency_conflict` -> `conflict`. Each is a
      disagreement with state the caller did not see, and `after_refresh` is
      what a caller should actually do about all five.
    * `evidence_invalid` -> `invalid_request`. The request contradicts itself
      or names evidence that does not support what it asked for, and correcting
      it is the caller's own move.
    * `quarantined` -> `quarantined`, which already exists and already carries
      `operator_review`.

    A stale resolution version is reported as `expected_resolution_version` and
    not as `expected_version`: the two are different fields on this surface -- a
    mention carries a resolution version and an entity carries an aggregate one
    -- and a caller told the wrong one would refresh the wrong record.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except StaleResolutionVersionError:
        failure = ConflictError(SafeDetail.EXPECTED_RESOLUTION_VERSION)
    except EntityMutationConflictError:
        failure = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
    except QuarantinedObservationError:
        failure = QuarantinedError(SafeDetail.OBSERVATION_ID)
    except UnknownObservationError:
        failure = NotFoundError(SafeDetail.OBSERVATION_ID)
    except UnknownEntityError:
        failure = NotFoundError(SafeDetail.ENTITY_ID)
    except ResolutionNotPermittedError as refused:
        failure = _resolution_refusal(refused)
    except ObservationTimeError:
        failure = InvalidRequestError(SafeDetail.OBSERVED_AT)
    except ObservationAuthorityError:
        failure = InvalidRequestError(SafeDetail.OBSERVATION_AUTHORITY)
    except ProposalPayloadError:
        # `WP-RI-B-05`. A payload that names a field its kind's command does not
        # take, omits one the kind requires, carries a server-owned name, or
        # proposes a status a caller may not ask for. Every one of those is the
        # caller's own move to correct, so `invalid_request` and not `conflict`
        # -- and the token is `payload` rather than the offending field, because
        # a token per admitted name would restate seventeen schemas in
        # `SafeDetail` and would tell a caller which of its fields the *schema*
        # objected to, which is the one thing a closed vocabulary must not do.
        failure = InvalidRequestError(SafeDetail.PAYLOAD)
    if failure is not None:
        raise failure


#: Which `safe_details` token each resolution refusal names, and which error
#: class carries it. Two mappings rather than one of callables, because a
#: callable table reads as dispatch and this is a translation: the token the
#: domain raised is the token the caller is told, and the class is what decides
#: the status and the retry guidance.
_RESOLUTION_DETAILS: Final[Mapping[str, SafeDetail]] = MappingProxyType(
    {
        "ambiguous_identity": SafeDetail.AMBIGUOUS_IDENTITY,
        "conflicted_identifier": SafeDetail.CONFLICTED_IDENTIFIER,
        "historical_entity": SafeDetail.HISTORICAL_ENTITY,
        "review_required": SafeDetail.REVIEW_REQUIRED,
        "stale_version": SafeDetail.EXPECTED_VERSION,
        "evidence_invalid": SafeDetail.EVIDENCE_INVALID,
    }
)

#: Which of the six are a disagreement with state rather than a malformed
#: request. `ambiguous_identity` is neither and is handled first: it is the one
#: refusal whose honest guidance is "somebody has to say which".
_RESOLUTION_CONFLICTS: Final[frozenset[str]] = frozenset(
    {"conflicted_identifier", "historical_entity", "review_required", "stale_version"}
)


def _resolution_refusal(refused: ResolutionNotPermittedError) -> ApplicationError:
    """The public error one resolution refusal is, derived from its own token.

    An unrecognised token is `invalid_request` rather than an assertion: a
    refusal is already the unhappy path, and a translation table that raised on
    an unfamiliar entry would turn a refusal the caller could act on into an
    `internal_error` they cannot.
    """
    detail = _RESOLUTION_DETAILS.get(refused.detail, SafeDetail.EVIDENCE_INVALID)
    if refused.detail == "ambiguous_identity":
        return AmbiguousRequestError(detail)
    if refused.detail in _RESOLUTION_CONFLICTS:
        return ConflictError(detail)
    return InvalidRequestError(detail)


@contextmanager
def _work_cursor_translated() -> Iterator[None]:
    """Collapse absent and foreign Work anchors into one safe cursor conflict."""
    failure: ApplicationError | None = None
    try:
        yield
    except WorkCursorError:
        failure = ConflictError(SafeDetail.CURSOR)
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
    """One browse row, with the two disambiguators `RI-AC-038` asked for.

    **The five original keys keep their names and their meanings**, because
    this is the single choke point every `entities.search` response passes
    through and renaming one here would break every caller at once. The two
    additions are `EntitySummary`'s own bounded collections, rendered as lists
    because JSON has no tuple; an entity with no current affiliation and no
    current project answers with two empty lists, which is a fact about that
    entity rather than a truncation, so nothing is disclosed about it.

    `tests/contract/test_entity_search_disambiguators.py` holds that
    compatibility claim as a test rather than as this paragraph.
    """
    return {
        "entity_id": summary.entity_id,
        "entity_type": summary.entity_type.value,
        "canonical_name": summary.canonical_name,
        "display_name": summary.display_name,
        "status": summary.status.value,
        "affiliated_organizations": list(summary.affiliated_organizations),
        "project_roles": list(summary.project_roles),
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
        is_current = assignment.state.value == ACTIVE_ASSIGNMENT_STATUS and is_in_force(
            assignment.effective_from, assignment.effective_to, at
        )
    return {
        "assignment_id": assignment.assignment_id,
        # `entity_id` and `version` are here for the reason `_relationship_view`
        # carries `from_entity_id` and `version`: a read that a write is expected
        # to follow has to hand back both halves of what the write needs, and a
        # caller that had to fetch the version separately would be reading a
        # second time and revising against the older of the two answers.
        "entity_id": assignment.entity_id,
        "assignment_type": assignment.assignment_type.value,
        "scope_entity_id": assignment.scope_entity_id,
        "role": assignment.role,
        "discipline": assignment.discipline,
        "responsibility_class": assignment.responsibility_class,
        "status": assignment.state.value,
        "is_current": is_current,
        "effective_from": _moment_or_none(assignment.effective_from),
        "effective_to": _moment_or_none(assignment.effective_to),
        "version": assignment.version,
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
        is_current = edge.state.value == ACTIVE_RELATIONSHIP_STATE and is_in_force(
            edge.effective_from, edge.effective_to, at
        )
    return {
        "relationship_id": edge.relationship_id,
        "is_current": is_current,
        "from_entity_id": edge.from_entity_id,
        "relationship_type": edge.relationship_type.value,
        "to_entity_id": edge.to_entity_id,
        "scope_entity_id": edge.scope_entity_id,
        "state": edge.state.value,
        "effective_from": _moment_or_none(edge.effective_from),
        "effective_to": _moment_or_none(edge.effective_to),
        "version": edge.version,
    }


def _graph_projection_id(entity_id: str, assignment_id: str | None = None) -> str:
    """A deterministic renderer key. Not identity; not canonical."""
    if assignment_id is None:
        return f"gprj_{entity_id}"
    return f"gprj_{entity_id}_{assignment_id}"


def _bounded_graph_edges(
    assignments: tuple[Assignment, ...],
    relationships: tuple[EntityRelationship, ...],
    page_size: int,
) -> tuple[list[Assignment | EntityRelationship], bool]:
    """The unified `edge_id` stream, sliced to `page_size`, plus overflow."""
    merged: list[Assignment | EntityRelationship] = sorted(
        (*assignments, *relationships),
        key=lambda item: (
            item.assignment_id if isinstance(item, Assignment) else item.relationship_id
        ),
    )
    return merged[:page_size], len(merged) > page_size


def _graph_edge_id(item: Assignment | EntityRelationship) -> str:
    return item.assignment_id if isinstance(item, Assignment) else item.relationship_id


def _graph_node(entity: Entity, projection_id: str) -> dict[str, object]:
    return {
        "entity_id": entity.entity_id,
        "projection_id": projection_id,
        "entity_type": entity.entity_type.value,
        "display_label": entity.display_name,
        "status": entity.status.value,
        "superseded_by_entity_id": entity.superseded_by_entity_id,
    }


def _graph_view(
    *,
    entities: tuple[Entity, ...],
    page: list[Assignment | EntityRelationship],
    seed_ids: frozenset[str],
    at: datetime | None,
) -> dict[str, object]:
    """Nodes and edges for one graph page. `people_path` is omitted on purpose."""
    by_id = {entity.entity_id: entity for entity in entities}
    nodes: dict[str, dict[str, object]] = {}
    edges: list[dict[str, object]] = []

    def add_node(entity_id: str, projection_id: str) -> None:
        entity = by_id.get(entity_id)
        if entity is None or projection_id in nodes:
            return
        nodes[projection_id] = _graph_node(entity, projection_id)

    for seed in sorted(seed_ids):
        add_node(seed, _graph_projection_id(seed))
    for item in page:
        if isinstance(item, Assignment):
            if item.scope_entity_id is None:
                continue
            framed = _graph_projection_id(item.entity_id, item.assignment_id)
            add_node(item.entity_id, framed)
            scope_proj = None
            if item.scope_entity_id is not None:
                scope_proj = _graph_projection_id(item.scope_entity_id)
                add_node(item.scope_entity_id, scope_proj)
            viewed = _assignment_view(item, at)
            edges.append(
                {
                    "edge_kind": "assignment",
                    "edge_id": item.assignment_id,
                    "type": viewed["assignment_type"],
                    "from_entity_id": item.entity_id,
                    "to_entity_id": item.scope_entity_id,
                    "from_projection_id": framed,
                    "to_projection_id": scope_proj,
                    "scope_entity_id": item.scope_entity_id,
                    "is_current": viewed["is_current"],
                    "status": viewed["status"],
                    "version": viewed["version"],
                }
            )
            continue
        from_proj = _graph_projection_id(item.from_entity_id)
        to_proj = _graph_projection_id(item.to_entity_id)
        add_node(item.from_entity_id, from_proj)
        add_node(item.to_entity_id, to_proj)
        viewed = _relationship_view(item, at)
        edges.append(
            {
                "edge_kind": "relationship",
                "edge_id": item.relationship_id,
                "type": viewed["relationship_type"],
                "from_entity_id": item.from_entity_id,
                "to_entity_id": item.to_entity_id,
                "from_projection_id": from_proj,
                "to_projection_id": to_proj,
                "scope_entity_id": item.scope_entity_id,
                "is_current": viewed["is_current"],
                "state": viewed["state"],
                "version": viewed["version"],
            }
        )
    edges.sort(key=lambda row: str(row["edge_id"]))
    return {
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": edges,
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
    conclusion. `memories` is the collection that reason was written for: the
    limitation naming a withheld or unread memory plane is above the list it
    qualifies, not below it.

    **A memory summary carries its statement, and an observation does not carry
    its observed value.** The two look like the same decision made differently
    and are not. An observation's value is a name or an address lifted out of
    somebody else's mail, and the card is a summary rather than the evidence --
    `entities.get` on the source object is where that text lives. A memory has no
    evidence behind it to point at: under ADR-003 the committed statement *is*
    the record, the Principal wrote it themselves about a person they chose, and
    a summary of it with the sentence removed would be a list of the fact that
    they had written something. What the card does not carry is the restricted
    memory, and it cannot: `summaries_for_context` never returns one and
    `ContextCardMemory` refuses to hold one.

    Every summary field is read off whichever half owns it -- `pinned` and the
    kind from the aggregate, the statement and its authority, classification and
    applicability window from the version in force -- rather than from a copy
    kept in step by hand.
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
        "memories": [
            {
                "memory_id": held.memory.memory_id,
                "kind": held.memory.memory_kind.value,
                "statement": held.current_version.statement,
                "authority": held.current_version.authority.value,
                "classification": held.current_version.classification.value,
                "pinned": held.memory.pinned,
                "effective_from": _moment_or_none(held.current_version.effective_from),
                "effective_to": _moment_or_none(held.current_version.effective_to),
                "recorded_at": format_rfc3339(held.current_version.recorded_at),
            }
            for held in card.memories
        ],
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
    """One unresolved mention, disclosing the name a writer chose to publish.

    **Neither `observed_value` nor `normalized_value` goes out.** This view used
    to publish the normalized form on the argument that it was the matchable
    datum and therefore the same class of thing as a `canonical_name`. An
    independent review established that the argument does not hold:
    `normalize_name` casefolds and turns punctuation into spaces and removes no
    content, so a writer deriving it from raw text publishes that text with its
    dots turned into spaces, and the result is `is_normalized_name`-true — no
    predicate over the stored string can tell it from a long real name.

    So the disclosure is a column rather than a promise. `mention_display_name`
    is optional and defaults to `None`, which makes forgetting fail *closed*:
    the mention is still listed, still has its source pointers, and simply
    carries no text. Publishing text is an affirmative write into a field whose
    name says what it is for. `f3a8c1d7e592` carries the full argument.
    """
    return {
        "observation_id": observation.observation_id,
        "kind": observation.kind.value,
        "mention_display_name": observation.mention_display_name,
        "source_id": observation.source_id,
        "source_object_id": observation.source_object_id,
        "source_version_id": observation.source_version_id,
        "observed_at": format_rfc3339(observation.observed_at),
        "recorded_at": format_rfc3339(observation.recorded_at),
    }


def _recorded_observation_view(observation: EntityObservation) -> dict[str, object]:
    """One recorded observation, with neither value the source produced.

    Same omission as `_unresolved_mention_view` and for the same reason:
    `normalized_value` is not a redaction of `observed_value` -- `normalize_name`
    casefolds and unpunctuates and removes no content -- so publishing it would
    publish the raw span with its dots turned into spaces, and no predicate over
    the stored string could tell the result from a long real name.

    What this adds over the queue's view is the four columns the queue has no
    use for: `authority` says what standing the claim has, `state` says whether
    it is still usable evidence, `entity_id` says what placed it, and
    `resolution_version` is the value a decision has to state as
    `expected_resolution_version`. That last one is why a caller working the
    queue can page it here: without the version there is nothing to decide
    against.
    """
    return {
        "observation_id": observation.observation_id,
        "kind": observation.kind.value,
        "authority": observation.authority.value,
        "origin": origin_of(observation.source_id).value,
        "state": observation.state.value,
        "state_reason": observation.state_reason,
        "mention_display_name": observation.mention_display_name,
        "source_id": observation.source_id,
        "source_object_id": observation.source_object_id,
        "source_version_id": observation.source_version_id,
        "entity_id": observation.entity_id,
        "superseded_by_observation_id": observation.superseded_by_observation_id,
        "resolution_version": observation.resolution_version,
        "observed_at": format_rfc3339(observation.observed_at),
        "recorded_at": format_rfc3339(observation.recorded_at),
    }


# --- RI-ENT-WP-10: the six record families as the wire sees them -------------
#
# One function per family, beside `_alias_view` and `_identifier_view` and on
# their terms. Three rules hold across all six and are stated once here rather
# than six times below.
#
# **`principal_id` is never emitted.** Every one of these records carries it as
# its partition column, and it is the one field on them that is about the
# caller rather than about the entity. `_entity_view` omits it for the same
# reason and has since the plane's first read.
#
# **Every moment goes out through `format_rfc3339`/`_moment_or_none` and every
# closed vocabulary goes out as `.value`.** A `datetime` rendered by `str()` and
# a `StrEnum` rendered by `str()` both happen to produce something readable,
# which is exactly why a view that did it by accident would stay unnoticed
# until a caller parsed one.
#
# **Nothing here is a judgement about the record.** No field is computed, no
# collection is ordered by anything but its own key, and there is no derived
# figure standing in for a person -- `tests/architecture/
# test_relationship_scoring_surface_is_denied.py` states that prohibition and
# these views add no field it would have to reach.


def _entity_name_view(name: EntityName) -> dict[str, object]:
    """One typed name form, as recorded.

    Both values go out. `display_value` is what a source wrote and
    `normalized_value` is the form resolution compares, and `_entity_view`
    publishes `canonical_name` beside `display_name` for the identical reason:
    a caller debugging why a reference did not resolve needs the form that was
    compared, not only the form that is shown. This is the Principal's own
    record of their own contact returned to the Principal who holds it, which
    is what separates it from an observation's `observed_value` -- that one is
    text lifted out of somebody else's mail and is published nowhere.
    """
    return {
        "entity_name_id": name.entity_name_id,
        "entity_id": name.entity_id,
        "name_type_code": name.name_type_code.value,
        "display_value": name.display_value,
        "normalized_value": name.normalized_value,
        "is_preferred": name.is_preferred,
        "effective_from": _moment_or_none(name.effective_from),
        "effective_to": _moment_or_none(name.effective_to),
        "state": name.state.value,
        "version": name.version,
        "updated_at": _moment_or_none(name.updated_at),
        "retired_at": _moment_or_none(name.retired_at),
        "superseded_by_entity_name_id": name.superseded_by_entity_name_id,
    }


def _entity_address_view(address: EntityAddress) -> dict[str, object]:
    """One address, as recorded, with the components the writer supplied.

    The parsed components are published beside `raw_value` rather than instead
    of it: a component the writer left null is a fact about what was recorded,
    and a view that showed only the parse would make an unparsed address look
    like a missing one.

    There is no geocode here and there is not going to be one. The plane stores
    a postal address a Principal recorded about their own contact; a resolved
    point on the earth is a different class of datum, and
    `tests/architecture/test_relationship_scoring_surface_is_denied.py` denies
    the vocabulary for it outright.
    """
    return {
        "entity_address_id": address.entity_address_id,
        "entity_id": address.entity_id,
        "address_type_code": address.address_type_code.value,
        "raw_value": address.raw_value,
        "normalized_address_value": address.normalized_address_value,
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "region": address.region,
        "postal_code": address.postal_code,
        "country": address.country,
        "label": address.label,
        "is_preferred": address.is_preferred,
        "effective_from": _moment_or_none(address.effective_from),
        "effective_to": _moment_or_none(address.effective_to),
        "state": address.state.value,
        "version": address.version,
        "updated_at": _moment_or_none(address.updated_at),
        "retired_at": _moment_or_none(address.retired_at),
        "superseded_by_entity_address_id": address.superseded_by_entity_address_id,
    }


def _communication_method_view(method: EntityCommunicationMethod) -> dict[str, object]:
    """One communication method, as recorded.

    `verification_status_code` is a lifecycle fact about the channel -- whether
    anybody confirmed it reaches the person -- and not a judgement about the
    person. `linked_external_identifier_id` is published because it is the
    join a caller needs to see that this address and that binding are the same
    channel recorded twice.
    """
    return {
        "communication_method_id": method.communication_method_id,
        "entity_id": method.entity_id,
        "method_type_code": method.method_type_code.value,
        "usage_context_code": method.usage_context_code.value,
        "display_value": method.display_value,
        "normalized_value": method.normalized_value,
        "verification_status_code": method.verification_status_code.value,
        "is_preferred": method.is_preferred,
        "effective_from": _moment_or_none(method.effective_from),
        "effective_to": _moment_or_none(method.effective_to),
        "state": method.state.value,
        "version": method.version,
        "updated_at": _moment_or_none(method.updated_at),
        "retired_at": _moment_or_none(method.retired_at),
        "superseded_by_communication_method_id": method.superseded_by_communication_method_id,
        "linked_external_identifier_id": method.linked_external_identifier_id,
    }


def _participation_view(participation: EntityProjectParticipation) -> dict[str, object]:
    """One project participation, as recorded, from whichever end was asked for.

    Both entity columns go out on every row regardless of which end the caller
    paged from, because a row that named only the far end would leave a reader
    holding two pages unable to say which entity either belonged to.

    The coded and free-text halves of role and discipline are both published.
    A writer that had a code recorded a code, a writer that had only a phrase
    recorded a phrase, and collapsing the two here would make "there is no
    taxonomy entry for this" indistinguishable from "nobody said".
    """
    return {
        "participation_id": participation.participation_id,
        "project_entity_id": participation.project_entity_id,
        "participant_entity_id": participation.participant_entity_id,
        "project_display_name": participation.project_display_name,
        "role_basis_code": participation.role_basis_code.value,
        "stakeholder_side_code": participation.stakeholder_side_code.value,
        "stakeholder_class_code": participation.stakeholder_class_code.value,
        "relationship_status_code": participation.relationship_status_code.value,
        "role_code": participation.role_code,
        "role_text": participation.role_text,
        "discipline_code": participation.discipline_code,
        "discipline_text": participation.discipline_text,
        "scope_text": participation.scope_text,
        "effective_from": _moment_or_none(participation.effective_from),
        "effective_to": _moment_or_none(participation.effective_to),
        "state": participation.state.value,
        "version": participation.version,
        "updated_at": _moment_or_none(participation.updated_at),
        "retired_at": _moment_or_none(participation.retired_at),
        "superseded_by_participation_id": participation.superseded_by_participation_id,
    }


def _affiliation_view(affiliation: PersonOrganizationAffiliation) -> dict[str, object]:
    """One person/organization affiliation, as recorded.

    `organization_entity_id` is nullable and stays nullable here: an
    affiliation whose organization this plane holds no entity for is a real
    recorded state, and a view that dropped the row or invented an identifier
    would report it as an absence.
    """
    return {
        "affiliation_id": affiliation.affiliation_id,
        "person_entity_id": affiliation.person_entity_id,
        "affiliation_type_code": affiliation.affiliation_type_code.value,
        "organization_entity_id": affiliation.organization_entity_id,
        "job_title": affiliation.job_title,
        "effective_from": _moment_or_none(affiliation.effective_from),
        "effective_to": _moment_or_none(affiliation.effective_to),
        "state": affiliation.state.value,
        "version": affiliation.version,
        "updated_at": _moment_or_none(affiliation.updated_at),
        "retired_at": _moment_or_none(affiliation.retired_at),
        "superseded_by_affiliation_id": affiliation.superseded_by_affiliation_id,
    }


def _organization_profile_view(profile: EntityOrganizationProfile) -> dict[str, object]:
    """One organization profile, as recorded.

    No `state` and no `retired_at`, because this family has neither: its
    primary key is `entity_id` itself, so an entity carries at most one row
    here and the row is corrected in place rather than superseded. A view that
    published the temporal columns the other five carry would be describing a
    lifecycle this table does not have.
    """
    return {
        "entity_id": profile.entity_id,
        "organization_kind_code": profile.organization_kind_code.value,
        "legal_identity_status_code": profile.legal_identity_status_code.value,
        "jurisdiction_code": profile.jurisdiction_code,
        "registration_identifier": profile.registration_identifier,
        "version": profile.version,
        "created_at": _moment_or_none(profile.created_at),
        "updated_at": _moment_or_none(profile.updated_at),
    }


def _profile_collection[T](records: list[T]) -> tuple[list[T], bool]:
    """The first `ENTITY_PROFILE_COLLECTION_LIMIT` records, and whether that bit.

    The caller asks the repository for one row past the ceiling and hands the
    whole answer here, which is `application.entity_context._bounded`'s shape
    and its reason: asking for exactly the ceiling and reporting a limitation
    when a full collection came back would claim "there are more addresses than
    this profile carries" for an entity holding exactly twenty-five. The extra
    row turns the claim into an observation -- it either exists or it does not.
    """
    return records[:ENTITY_PROFILE_COLLECTION_LIMIT], len(records) > (
        ENTITY_PROFILE_COLLECTION_LIMIT
    )


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

#: What a governed entity write's receipt rests on.
#: `principal_partition` because every statement behind it carried the
#: authenticated partition, and `user_confirmed_assertion` because that is the
#: authority the mutation ledger recorded — the user was asked, named the version
#: they had read, and answered. Not `user_authored`: an entity is not an ADR-003
#: append-only record, and saying so would claim the wrong custody.
#:
#: **This describes the eighteen Phase A writes, and only them.** Sixteen of
#: those disclose this and two do not, and the split is a property of the
#: ledger rather than a preference. The ten identity, identifier and alias
#: writes and the six directed writes each record `user_confirmed_assertion` as
#: a constant, so their receipts can name it. `entities.observe` records
#: whichever of three authorities its own `authority` field implies — a source
#: observation is `system_deterministic` — and
#: `entities.unresolved_mentions.resolve` records `review_accepted` when a
#: review promotion decided it. Neither can claim a constant it does not always
#: write, so both stay on `_ENTITY_TRUST_BASIS` and disclose only the partition.
#:
#: The fifteen RI-ENT-WP-11 record-family writes are not in that eighteen and
#: do not pass through `_ENTITY_TRUST_BASIS` at all: they answer through
#: `_directed_receipt`, which discloses this authoring basis, and what their
#: ledger rows record is `EntityFamilyWriteService`'s statement to make, not
#: this comment's. Their disclosure is not characterised here. The
#: identity-correction writes are not characterised here either.
_ENTITY_AUTHORING_TRUST_BASIS: Final = ("principal_partition", "user_confirmed_assertion")


#: The identity-correction views, and the two module-level helpers the two
#: handlers share.


def _identity_conflict_view(conflict: IdentityConflict) -> dict[str, object]:
    """One conflict as a caller reads it: what kind, which family, which record.

    No value and no name, for the reason `IdentityEffect`'s own states carry
    none: a merge conflict is a statement about somebody's identity, and the
    record identifier is what an operator needs to decide it.
    """
    return {
        "kind": conflict.kind.value,
        "family": conflict.family.value,
        "record_id": conflict.record_id,
    }


def _merge_idempotency_key(principal_id: str, preview_id: str) -> str:
    """The server's replay identity for one governed merge.

    Over the Principal and the preview, and nothing the caller can vary
    independently of them. A preview is consumable once, so one preview is one
    operation: an identical retry produces this same key and replays, while a
    materially different request naming the same preview produces this same key
    and a different request digest, which is the conflict operator §23 asks for.

    `idk_` and thirty-two hexadecimal characters, the shape
    `adapters.remote_request` derives for the capabilities whose commands carry
    the field. This one's command does not carry it, which is what §26 requires
    of a server-owned field -- so the shape is shared and the *source* is not.
    """
    digest = hashlib.sha256(
        f"{Capability.ENTITIES_MERGE.value}|{principal_id}|{preview_id}".encode()
    ).hexdigest()
    return f"idk_{digest[:32]}"


def _split_idempotency_key(principal_id: str, preview_id: str) -> str:
    """The server-owned replay identity for one governed split preview."""
    digest = hashlib.sha256(
        f"{Capability.ENTITIES_SPLIT.value}|{principal_id}|{preview_id}".encode()
    ).hexdigest()
    return f"idk_{digest[:32]}"


def _relationship_write_digest(command: Command) -> str:
    """Digest only material command fields without persisting their values."""
    return hashlib.sha256(
        json.dumps(
            {"command": type(command).__name__, "material": asdict(command)},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _reserve_relationship_write(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: Command,
) -> tuple[str, WriteRequestResult | None]:
    digest = _relationship_write_digest(command)
    try:
        replayed = unit_of_work.write_requests.reserve(
            authorization.principal.principal_id,
            command.capability.value,
            authorization.request_id,
            digest,
        )
    except WriteRequestConflictError:
        raise ConflictError(SafeDetail.IDEMPOTENCY_CONFLICT) from None
    return digest, replayed


def _complete_relationship_write(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: Command,
    digest: str,
    result: WriteRequestResult,
) -> None:
    unit_of_work.write_requests.complete(
        authorization.principal.principal_id,
        command.capability.value,
        authorization.request_id,
        digest,
        result,
    )


def _register_reenrichment_result(
    repository: ReenrichmentWorkRepository,
    *,
    result: _Result,
    principal_id: str,
    capability: str,
    policy_version: str,
    at: datetime,
) -> None:
    """Register only a handler-attested new mutation, never payload inference."""
    if result.reenrichment_cause_id is None:
        return
    register_mutation_reenrichment(
        repository,
        principal_id=principal_id,
        capability=capability,
        cause_record_id=result.reenrichment_cause_id,
        policy_version=policy_version,
        at=at,
    )


# These handlers register a more precise subject binding directly. The generic
# handler-attested path remains authoritative for every other mapped mutation;
# skipping this closed overlap prevents duplicate Principal-wide work for the
# same mutation while preserving the remote branch's additional callers.
_DIRECT_REENRICHMENT_CAPABILITIES = frozenset(
    {
        "capture.revise",
        "entities.aliases.add",
        "entities.assignments.create",
        "entities.assignments.end",
        "entities.assignments.revise",
        "entities.merge",
        "entities.relationships.create",
        "entities.relationships.end",
        "entities.relationships.revise",
        "entities.split",
        "review.decide",
    }
)


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
        relationship_intelligence_writes_enabled: bool = False,
        relationship_memory_enabled: bool = False,
        relationship_identity_correction_enabled: bool = False,
        relationship_reenrichment_enabled: bool = False,
        producer_origins: ProducerOriginRegistry | None = None,
        gsqs_b0_ports: WorkflowPorts | None = None,
        goodnotes_pull_enabled: bool = False,
        goodnotes_canonical_semantic_writes_enabled: bool = False,
        goodnotes_pull_cursor_signing_key: bytes | None = None,
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
        #: Default `False`, and the default is the point: this family reads who
        #: a person is, and `adapters.mcp.remote` derives
        #: the remote tool profile from `Capability` with no per-capability
        #: exclusion list — so a non-operator read joins the remote surface the
        #: moment it becomes available. Withholding it here is the one mechanism
        #: this repository already proves end to end against a real child
        #: process, and it keeps `capabilities.get`, `tools/list`, and the remote
        #: profile agreeing about what exists.
        self._relationship_intelligence_enabled = relationship_intelligence_enabled
        #: Whether this build serves the entity plane's *write* half. Default
        #: `False`, and independent of the flag above for the reason
        #: `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` exists: reading who a
        #: person is and deciding it are different authorities, and an operator
        #: who wants the first should not have to accept the second. A build that
        #: set this without the plane does not reach here -- `bootstrap.settings`
        #: refuses to start -- so this flag narrows an already-composed plane and
        #: never widens an absent one.
        self._relationship_intelligence_writes_enabled = relationship_intelligence_writes_enabled
        self._relationship_memory_enabled = relationship_memory_enabled
        # The third gate, and it is the narrowest. `_identity_correction_plane`
        # is the floor every one of its handlers asks; `available_capabilities`
        # is what `capabilities.get` and the MCP tool list read. Default `False`
        # for the reason the two above it default `False`: a composition root
        # that has not said the operation is composed gets a process that does
        # not serve it.
        self._relationship_identity_correction_enabled = relationship_identity_correction_enabled
        # Registration is an internal consequence of already-authorized writes,
        # never a separately published capability. Default closed keeps legacy
        # and non-RI compositions from reaching the additive queue.
        self._relationship_reenrichment_enabled = relationship_reenrichment_enabled
        self._gsqs_b0_ports = gsqs_b0_ports
        self._goodnotes_pull_enabled = goodnotes_pull_enabled
        self._goodnotes_canonical_semantic_writes_enabled = (
            goodnotes_canonical_semantic_writes_enabled
        )
        self._goodnotes_pull_cursor_signing_key = goodnotes_pull_cursor_signing_key
        if goodnotes_pull_enabled and goodnotes_pull_cursor_signing_key is None:
            raise ValueError("enabled GoodNotes pull requires a signing key")
        #: Explicit production composition of the optional proposal plane. The
        #: default gate is disabled; an enabled gate cannot be constructed
        #: without its local provider and canonical Review router.
        self._model_gate = model_gate or BoundedModelGate()
        self._producer_origins = producer_origins or ProducerOriginRegistry()
        #: WP-27's application service, held rather than built per request: it is
        #: stateless, takes its ports as arguments, and constructing one per call
        #: would say it held something.
        self._managed = ManagedDocumentService()
        self._memory = RelationshipMemoryService()
        #: WP-RI-A-02's entity authoring service, held for the reason the two
        #: above are: it is stateless and takes its port as an argument.
        self._entity_authoring = EntityAuthoringService()
        #: WP-RI-A-03's directed-write service, held on the same terms: it is
        #: stateless, takes its port as an argument, and constructing one per
        #: call would say it held something.
        self._directed = EntityDirectedService()
        #: `RI-ENT-WP-11`'s record-family writes. Composed unconditionally
        #: beside `_directed`, for the reason that one is: the switches that
        #: decide whether this plane is served are read at the handler, not at
        #: composition, so a service holding the writer and refusing to reach
        #: it is the shape every other gated plane here already has.
        self._family_writes = EntityFamilyWriteService()
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
        names in a process with no managed root, and the fifty-five `entities.` names
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
        # The write half, narrowed separately. Subtracted after the line above
        # rather than folded into it, because the two answer different questions
        # and a build can be in either state: the plane off withholds the
        # whole `entities.` family, and the plane on with writes off withholds
        # `_ENTITY_WRITE_CAPABILITIES` out of it.
        if not self._relationship_intelligence_writes_enabled:
            served -= _ENTITY_WRITE_CAPABILITIES
        # Two conditions, not one. The plane needs its own switch *and* the
        # entity plane, because a memory's subject is an Entity and the
        # repository proves ownership of it by reading `knowledge.entities`.
        if not (self._relationship_intelligence_enabled and self._relationship_memory_enabled):
            served -= _RELATIONSHIP_MEMORY_CAPABILITIES
        # A proposal surface without a trusted server registration would
        # advertise a write every authenticated caller can only be denied.
        # Withhold both producer capabilities when composition has no exact
        # producer identity; per-Principal resolution still fails closed.
        if not self._producer_origins.has_registrations:
            served -= _PRODUCER_CAPABILITIES
        # Governed identity correction, narrowed separately again. Its own switch
        # requires the write switch, which requires the plane switch, and
        # `Settings._check` refuses a process configured otherwise -- so the three
        # subtractions above have already removed these names whenever a lower
        # gate is off, and this line is what a build with every lower gate on still
        # has to pass. Written as its own condition rather than folded into the
        # write subtraction because the two answer different questions and a
        # build can be in either state.
        if not self._relationship_identity_correction_enabled:
            served -= _IDENTITY_CORRECTION_CAPABILITIES
        if not self._goodnotes_pull_enabled:
            served -= _GOODNOTES_PULL_CAPABILITIES
        return served

    def invoke(
        self,
        metadata: RequestMetadata,
        command: Command,
        *,
        principal: Principal,
        transport: CaptureTransport = CaptureTransport.LOCAL,
        capability_grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
        authenticated_client_id: str | None = None,
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
                authenticated_client_id=authenticated_client_id,
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
        authenticated_client_id: str | None = None,
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
        committed_conflict: ConflictError | None = None
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
                    authenticated_client_id=authenticated_client_id,
                )
                if authorization.allowed:
                    try:
                        result = _HANDLERS[command.capability](
                            self, unit_of_work, authorization, command
                        )
                        if (
                            self._relationship_reenrichment_enabled
                            and command.capability.value in TRIGGERS_BY_MUTATION_CAPABILITY
                            and command.capability.value not in _DIRECT_REENRICHMENT_CAPABILITIES
                        ):
                            _register_reenrichment_result(
                                unit_of_work.reenrichment,
                                result=result,
                                principal_id=authorization.principal.principal_id,
                                capability=command.capability.value,
                                policy_version=POLICY_VERSION,
                                at=authorization.at,
                            )
                        return result
                    except _CommitRejectedConflictError as conflict:
                        # The handler raises this marker only after verifying a
                        # REJECTED receipt whose before/after/current versions
                        # are identical. Leaving normally commits that receipt;
                        # no generic ApplicationError receives this treatment.
                        committed_conflict = conflict.failure
        # Reached only after the transaction committed, which is what preserves
        # the audit event recording the refusal.
        if mismatch:
            raise InvalidRequestError(SafeDetail.SUBJECT)
        if committed_conflict is not None:
            raise committed_conflict
        raise DeniedError()

    # ---- the source and knowledge planes -----------------------------------

    @staticmethod
    def _require_work_evidence(unit_of_work: UnitOfWork, principal_id: str, reference: str) -> None:
        """Fail closed unless Work evidence belongs to this Principal.

        The repository performs a metadata-only existence/state check.  This
        layer receives one boolean and therefore cannot accidentally expose
        capture or assertion content in a Work response or error.
        """
        with _translated():
            valid = unit_of_work.captures.accepts_work_evidence_reference(
                reference, principal_id=principal_id
            )
        if not valid:
            raise InvalidRequestError(SafeDetail.INVALID_EVIDENCE_REFERENCE)

    @staticmethod
    def _require_current_counterparty(
        unit_of_work: UnitOfWork, principal_id: str, person_id: str
    ) -> None:
        """Fail closed unless ``person_id`` is current in this Principal's partition.

        The repository intentionally returns the same ``None`` for an absent,
        foreign, or superseded Person.  Preserving that collapse here prevents
        a Commitment write from becoming an identity-enumeration side channel.
        """
        with _translated():
            counterparty = unit_of_work.commitments.counterparty(principal_id, person_id)
        if counterparty is None:
            raise NotFoundError(SafeDetail.COUNTERPARTY_PERSON_ID)

    def _require_commitment_create_eligibility(
        self,
        unit_of_work: UnitOfWork,
        principal_id: str,
        *,
        evidence_ref: str,
        counterparty_person_id: str,
    ) -> None:
        self._require_work_evidence(unit_of_work, principal_id, evidence_ref)
        self._require_current_counterparty(unit_of_work, principal_id, counterparty_person_id)

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
            if observed.version_id != content.version_id:
                raise VersionChangedError

        if self._relationship_reenrichment_enabled:
            register_source_version_observation(
                unit_of_work.reenrichment,
                principal_id=authorization.principal.principal_id,
                source_object_id=observed.source_object_id,
                source_version_id=observed.version_id,
                policy_version=authorization.decision.policy_version,
                at=authorization.at,
            )

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

    def _canvas_workspace_get(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetCanvasWorkspace,
    ) -> _Result:
        """The stored overlay, or an empty overlay when none exists.

        Missing is version 0 with no positions and no timestamp, not `not_found`
        and not an empty graph. The seed entity is not required to exist.
        """
        stored = unit_of_work.canvas_workspaces.get(
            authorization.principal.principal_id,
            command.focus_entity_id,
            command.scope_entity_id,
        )
        if stored is None:
            view = CanvasWorkspaceView(
                focus_entity_id=command.focus_entity_id,
                scope_entity_id=command.scope_entity_id,
                version=0,
                positions={},
                updated_at=None,
            )
        else:
            view = CanvasWorkspaceView(
                focus_entity_id=stored.focus_entity_id,
                scope_entity_id=stored.scope_entity_id,
                version=stored.version,
                positions=_canvas_point_views(stored.positions),
                updated_at=stored.updated_at,
            )
        return _Result(
            payload=view.to_canonical_dict(),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CAPTURE_TRUST_BASIS),
        )

    def _canvas_workspace_put(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: PutCanvasWorkspace,
    ) -> _Result:
        """Create, replay, or conflict on one overlay write.

        `expected_version=0` creates when absent (stored version becomes 1).
        Matching version and equal positions return the existing receipt.
        A mismatch, including expected_version=0 against a stored row with
        different positions, is a conflict and leaves the row untouched.
        """
        principal_id = authorization.principal.principal_id
        stored = unit_of_work.canvas_workspaces.get(
            principal_id, command.focus_entity_id, command.scope_entity_id
        )
        try:
            if stored is None:
                if command.expected_version != 0:
                    raise ConflictError(SafeDetail.STALE_VERSION)
                written = unit_of_work.canvas_workspaces.insert(
                    CanvasWorkspaceRecord(
                        principal_id=principal_id,
                        focus_entity_id=command.focus_entity_id,
                        scope_entity_id=command.scope_entity_id,
                        version=1,
                        positions=command.positions,
                        created_at=authorization.at,
                        updated_at=authorization.at,
                    )
                )
            else:
                if command.expected_version != stored.version:
                    raise ConflictError(SafeDetail.STALE_VERSION)
                if _canvas_positions_equal(command.positions, stored.positions):
                    written = stored
                else:
                    written = unit_of_work.canvas_workspaces.update(
                        CanvasWorkspaceRecord(
                            principal_id=principal_id,
                            focus_entity_id=command.focus_entity_id,
                            scope_entity_id=command.scope_entity_id,
                            version=stored.version + 1,
                            positions=command.positions,
                            created_at=stored.created_at,
                            updated_at=authorization.at,
                        ),
                        expected_version=stored.version,
                    )
        except CanvasWorkspaceConflictError:
            raise ConflictError(SafeDetail.STALE_VERSION) from None
        receipt = CanvasWorkspaceReceiptView(
            focus_entity_id=written.focus_entity_id,
            scope_entity_id=written.scope_entity_id,
            version=written.version,
            positions=_canvas_point_views(written.positions),
            updated_at=written.updated_at,
        )
        return _Result(
            payload=receipt.to_canonical_dict(),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CAPTURE_TRUST_BASIS),
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
        """List review cases without capture, statement or payload content.

        One page across every composed subject kind, narrowed by whichever of the
        three filters the caller stated. The filters go to the port rather than
        being applied to the page after it comes back: a filter applied here
        would return a short page and call it complete, and `entity_id` would
        have made two planes that cannot answer it read everything first.
        """
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        binding = _review_cursor_binding(
            principal_id=principal_id,
            page_size=page_size,
            subject_kind=command.subject_kind,
            state=command.state,
            entity_id=command.entity_id,
        )
        position: tuple[datetime, str] | None = None
        if command.after is not None:
            position = _decode_review_cursor(command.after, expected_binding=binding)
            if position is None:
                raise ConflictError(SafeDetail.CURSOR)
        with _translated():
            found = unit_of_work.reviews.cases(
                limit=page_size + 1,
                principal_id=principal_id,
                subject_kind=command.subject_kind,
                state=command.state,
                entity_id=command.entity_id,
                after_opened_at=None if position is None else position[0],
                after_review_case_id=None if position is None else position[1],
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        next_cursor = (
            _encode_review_cursor(
                binding=binding,
                opened_at=page[-1].opened_at,
                review_case_id=page[-1].review_case_id,
            )
            if truncated and page
            else None
        )
        return _Result(
            payload={"review_cases": [_review_case_payload(case) for case in page]},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=("review_policy",),
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=next_cursor,
                ),
            ),
        )

    def _review_decide(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: DecideReviewCase
    ) -> _Result:
        """Append one disposition and, for acceptance, carry out what it accepted.

        **Which plane decides is decided here, and it is one branch rather than a
        capability of its own.** Three of the four subject kinds are decided inside
        the port, because everything their decision does is SQL. An Entity
        proposal is executed through the canonical Phase A mutation services,
        which live in this layer, so its ordering is
        `EntityProposalReviewService`'s and this routes to it. A caller sees one
        capability, one request shape and one answer either way.

        `decided_by`, the operator declaration and the fresh resolver are all
        server-supplied. There is no field on the command for any of them: a
        caller that could name its own authority would name the one it needed.
        """
        request_digest, replayed = _reserve_relationship_write(unit_of_work, authorization, command)
        if replayed is not None:
            if replayed.result_family == "review_invalidated":
                return _Result(
                    payload={"review_case_id": replayed.result_id, "result": "invalidated"},
                    disclosure=unenrolled_disclosure(
                        authorization.at,
                        trust_basis=("review_policy", "source_span_validation"),
                    ),
                )
            if replayed.result_family != "review_decision":
                raise InternalError()
            replay_payload: dict[str, object] = {
                "review_case_id": replayed.result_secondary_id,
                "decision_id": replayed.result_id,
                "review_version": replayed.result_version,
                "disposition": replayed.result_disposition,
                "proposal_state": replayed.result_state,
                "assertion_id": replayed.result_assertion_id,
                "receipt_id": replayed.receipt_id,
            }
            handoff = self._replayed_identity_handoff(
                unit_of_work,
                authorization.principal.principal_id,
                replayed.result_id,
            )
            if handoff is not None:
                replay_payload["identity_correction_handoff"] = handoff
            return _Result(
                payload=replay_payload,
                disclosure=unenrolled_disclosure(
                    authorization.at,
                    trust_basis=("review_policy", "reviewed_promotion"),
                ),
            )
        request = ReviewDecisionRequest(
            review_case_id=command.review_case_id,
            expected_review_version=command.expected_review_version,
            disposition=command.disposition,
            principal_id=authorization.principal.principal_id,
            correlation_id=authorization.correlation_id,
            audit_id=authorization.audit_id,
            policy_version=authorization.decision.policy_version,
            decided_at=self._clock(),
            corrected_value=command.corrected_value,
            correction_patch=command.correction_patch,
            reason=command.reason,
        )
        decision = None
        conflict = False
        missing = False
        unsupported = False
        denied = False
        invalid = False
        entity_case: EntityProposalReviewCase | None = None
        with _translated(), _entity_governance_translated():
            try:
                pull_repository: GoodNotesPullRepository | None = None
                semantic_case = None
                if self._goodnotes_pull_enabled:
                    pull_repository = cast(GoodNotesPullRepository, unit_of_work.goodnotes_pull)
                    semantic_case = pull_repository.semantic_review_case(
                        request.principal_id, request.review_case_id
                    )
                # Keep the disposition guard readable by the declared branch-split invariant.
                if semantic_case is not None:  # noqa: SIM102
                    if request.disposition is Disposition.CORRECT_AND_ACCEPT:
                        if request.correction_patch is None or request.corrected_value is not None:
                            raise ReviewCorrectionError(
                                "semantic correction is one structured correction patch"
                            )
                        repository = cast(GoodNotesPullRepository, pull_repository)
                        material = repository.semantic_proposal_material(
                            request.principal_id, semantic_case.proposal_id
                        )
                        if material is None:
                            raise ReviewNotFoundError("the semantic proposal is absent")
                        patch = request.correction_patch.as_mapping()
                        allowed_fields = {
                            "segments",
                            "candidate_tags",
                            "ranked_candidates",
                            "confidence",
                            "date_evidence",
                        }
                        if not set(patch) <= allowed_fields:
                            raise ReviewCorrectionError(
                                "semantic correction names only governed payload fields"
                            )
                        corrected = {**material.payload, **patch}
                        try:
                            validated = SubmitGoodNotesProposal(
                                run_id=material.run_id,
                                page_version_id=material.page_version_id,
                                content_sha256=material.content_sha256,
                                schema_version=material.schema_version,
                                analyzer_name=material.analyzer_name,
                                analyzer_version=material.analyzer_version,
                                idempotency_key=material.proposal_id,
                                segments=tuple(corrected.get("segments", ())),
                                candidate_tags=tuple(corrected.get("candidate_tags", ())),
                                ranked_candidates=tuple(corrected.get("ranked_candidates", ())),
                                confidence=corrected.get("confidence"),
                                date_evidence=corrected.get("date_evidence", {}),
                            )
                        except (TypeError, ValueError):
                            raise ReviewCorrectionError(
                                "semantic correction satisfies the canonical proposal contract"
                            ) from None
                        _fingerprint, corrected_result_sha256, corrected_body = (
                            fingerprint_proposal(validated)
                        )
                        request = replace(
                            request,
                            semantic_corrected_payload=corrected_body,
                            semantic_corrected_result_sha256=corrected_result_sha256,
                        )
                entity_case = unit_of_work.reviews.entity_proposal_case(
                    request.principal_id, request.review_case_id
                )
                if entity_case is None:
                    decision = unit_of_work.reviews.decide(
                        request,
                        has_operator_authority=self._operator_authority(authorization),
                    )
                else:
                    decision = self._entity_review(unit_of_work, authorization, request)
            except ReviewConflictError:
                conflict = True
            except ReviewNotFoundError:
                missing = True
            except ReviewUnsupportedError:
                unsupported = True
            except ReviewAuthorityError:
                denied = True
            except ReviewCorrectionError:
                invalid = True
        if conflict:
            raise ConflictError(SafeDetail.EXPECTED_REVIEW_VERSION)
        if unsupported:
            raise UnsupportedError(SafeDetail.DISPOSITION)
        if denied:
            raise DeniedError(SafeDetail.DISPOSITION)
        if invalid:
            raise InvalidRequestError(SafeDetail.CORRECTED_VALUE)
        if missing:
            raise NotFoundError(SafeDetail.REVIEW_CASE_ID)
        if decision is None:
            result = _Result(
                payload={"review_case_id": command.review_case_id, "result": "invalidated"},
                disclosure=unenrolled_disclosure(
                    authorization.at,
                    trust_basis=("review_policy", "source_span_validation"),
                ),
            )
            _complete_relationship_write(
                unit_of_work,
                authorization,
                command,
                request_digest,
                WriteRequestResult(
                    result_family="review_invalidated",
                    result_id=command.review_case_id,
                    result_state="invalidated",
                    audit_id=authorization.audit_id,
                ),
            )
            return result
        response_payload: dict[str, object] = {
            "review_case_id": decision.review_case_id,
            "decision_id": decision.decision_id,
            "review_version": decision.sequence,
            "disposition": decision.disposition.value,
            "proposal_state": decision.proposal_state.value,
            "assertion_id": decision.assertion_id,
            "receipt_id": decision.receipt_id,
        }
        identity_handoff = getattr(decision, "identity_correction_handoff", None)
        if identity_handoff is not None:
            response_payload["identity_correction_handoff"] = {
                "state": identity_handoff.state.value,
                "proposal_id": identity_handoff.proposal_id,
                "proposal_kind": identity_handoff.proposal_kind.value,
                "effective_payload_source": identity_handoff.effective_payload_source.value,
                "effective_payload": identity_handoff.effective_payload.as_mapping(),
            }
        # WP-04 / RI-P3-HIGH-001. This used to register
        # `CONTRADICTION_RESOLUTION` unconditionally, which every
        # `Disposition` member and every `ReviewSubjectKind` value
        # reached -- a deferred GoodNotes region and a rejected alias proposal
        # both filed contradiction work. RI v0.2 section 10.11 scopes a
        # contradiction to conflicting *assertions* a reviewer chooses between,
        # and `TRIGGERS_BY_MUTATION_CAPABILITY` sends only
        # `entities.unresolved_mentions.resolve` there. The predicate is pure,
        # total and tested exhaustively (17 proposal kinds x 8 dispositions) in
        # `tests/unit/test_entity_reenrichment.py`; it reads three closed values
        # the decision already carries and never the proposal payload, which
        # `EntityProposalReviewCase` withholds as a disclosure control.
        trigger = reenrichment_trigger_for_review_decision(
            proposed_kind=None if entity_case is None else entity_case.proposed_kind,
            disposition=decision.disposition,
            proposal_state=decision.proposal_state,
        )
        if trigger is not None:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                trigger,
                decision.decision_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.REVIEW_DECISION,
                        decision.decision_id,
                        str(decision.sequence),
                    ),
                ),
            )
        result = _Result(
            payload=response_payload,
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=("review_policy", "reviewed_promotion"),
            ),
            reenrichment_cause_id=decision.decision_id,
        )
        _complete_relationship_write(
            unit_of_work,
            authorization,
            command,
            request_digest,
            WriteRequestResult(
                result_family="review_decision",
                result_id=decision.decision_id,
                result_secondary_id=decision.review_case_id,
                result_version=decision.sequence,
                result_state=decision.proposal_state.value,
                result_disposition=decision.disposition.value,
                result_assertion_id=decision.assertion_id,
                receipt_id=decision.receipt_id,
                audit_id=authorization.audit_id,
            ),
        )
        return result

    def _replayed_identity_handoff(
        self, unit_of_work: UnitOfWork, principal_id: str, decision_id: str
    ) -> dict[str, object] | None:
        """Reconstruct the original safe handoff from canonical persisted rows."""
        try:
            decision = unit_of_work.reviews.entity_proposal_decision(principal_id, decision_id)
        except NotImplementedError:
            return None
        if decision is None:
            return None
        proposal = unit_of_work.entities.proposal(principal_id, decision.proposal_id)
        if proposal is None or proposal.kind not in IDENTITY_CORRECTION_PROPOSAL_KINDS:
            return None
        corrected = decision.corrected_payload
        effective = (
            proposal.payload
            if corrected is None
            else EntityProposalPayload.of(proposal.kind, corrected.as_mapping())
        )
        source = (
            ReviewedPayloadSource.PROPOSED if corrected is None else ReviewedPayloadSource.CORRECTED
        )
        return {
            "state": IdentityCorrectionHandoffState.OPERATOR_PREVIEW_REQUIRED.value,
            "proposal_id": proposal.proposal_id,
            "proposal_kind": proposal.kind.value,
            "effective_payload_source": source.value,
            "effective_payload": effective.as_mapping(),
        }

    def _entity_review(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        request: ReviewDecisionRequest,
    ) -> ReviewDecision:
        """One Entity proposal decided, with the fresh resolver its kind may need.

        The resolver is built here and run inside this transaction, against the
        state that exists now rather than the state the proposal was filed
        against — the same callable `entities.unresolved_mentions.resolve` builds
        and for the same reason. It is a veto and not a licence: it can refuse a
        binding the world no longer supports and it cannot license one, and a
        `resolve_mention` acceptance arriving without it is refused rather than
        performed unchecked.

        **`has_operator_authority` is the acting context's own declaration, and
        it used to be hard-coded `False`.** The old sentence read "a reviewer
        holding `review.decide` is not thereby an operator", and that is still
        exactly right and is still what happens: `review.decide` is not
        operator-only, so a reviewer who is not the authenticated operator gets
        `False` here and cannot accept an escalated case or a `merge_entities`
        proposal. What the constant also did was make `escalate` a disposition
        with no exit -- it raises a case to the operator ceiling, and nothing
        published could then reach it -- which is a hole in a surface Phase B
        itself publishes rather than a boundary Phase B is keeping.

        Section 15 is preserved and is preserved somewhere else, which is the
        point: acceptance of a `merge_entities` or `split_identity` proposal
        records reviewed intent and lineage and mutates no identity, whatever
        this flag says. Identity mutation is `entities.merge`'s, which is
        operator-only *and* behind its own feature gate. So an operator who
        accepts a merge proposal here has still not merged anything.
        """
        principal_id = authorization.principal.principal_id
        resolver = EntityResolutionService(unit_of_work.entities)

        def resolve_now(
            observation: EntityObservation, refused: frozenset[str], at: datetime
        ) -> EntityResolution:
            return resolver.resolve(
                principal_id,
                ResolutionRequest(
                    raw_reference=observation.observed_value,
                    at=at,
                    refused_entity_ids=refused,
                ),
            )

        return EntityProposalReviewService(unit_of_work.entities, unit_of_work.reviews).decide(
            request,
            decided_by=principal_id,
            has_operator_authority=self._operator_authority(authorization),
            resolve=resolve_now,
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
    # Six reads, one purpose, no writes. Each answers from the acting
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
        withholds the fifty-five `entities.` names, and two readers consult it —
        `capabilities.get` and the MCP tool list. The HTTP transport is not one
        of them: `/v1/{capability}` routes by path segment and `_run` dispatches
        straight from `_HANDLERS`, so every one of the six executed and
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

    def _entity_writes(self) -> None:
        """Refuse when this build has not enabled the entity plane's write half.

        The same floor `_entity_plane` is, one switch narrower, and it exists for
        the same reason that one does: `available_capabilities` withholds the
        thirty-eight entity write names and two readers consult it -- `capabilities.get`
        and the MCP tool list -- while the HTTP transport consults neither. It
        routes by path segment and `_run` dispatches straight from `_HANDLERS`,
        so a build with `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` unset
        would report every write as `not_implemented` and then execute it.

        `unsupported` and not `denied`: a process without the switch has no write
        half, which is a fact about the build and not a fault in the request or
        a shortfall in the caller's authority.

        Every write handler calls this rather than `_entity_plane`, so the
        refusal does not depend on which transport asked, and the plane check is
        made first so a build with neither switch answers for the missing plane
        rather than for the missing half of it.
        """
        self._entity_plane()
        if not self._relationship_intelligence_writes_enabled:
            raise UnsupportedError()

    # ---- the Relationship Memory plane -------------------------------------
    #
    # Nine handlers over two services, and the shape every plane here uses:
    # resolve the gate, build the use-case command with the Principal the
    # authorization already resolved, and hand both to `RelationshipMemoryService`
    # for canonical memory operations or `RelationshipMemoryProposalService` for
    # the candidate producer. No memory rule is restated in this file. Which
    # authority a direct write carries, which classification floor a kind implies,
    # whether a subject may be written to, and how a replay is decided all stay in
    # the services, the repository and the domain, so a second copy here cannot
    # disagree with them.
    #
    # `principal_id=authorization.principal.principal_id` is the only thing these
    # handlers say about identity, and the transport-facing commands have no
    # `principal_id` field at all, so there is nothing a caller could have
    # supplied for it to be confused with.

    def _relationship_memory_plane(self) -> None:
        """Refuse when this build has not enabled the Relationship Memory plane.

        The floor `_entity_plane` documents, for the same reason and against the
        same gap: `available_capabilities` withholds this plane's names from
        `capabilities.get` and from the MCP tool list, and the HTTP transport
        consults neither — it routes by path segment straight into `_HANDLERS`.
        Every handler below calls this first, so the refusal does not depend on
        which transport asked.

        It requires the entity plane too, and that is not belt and braces: a
        memory binds a generalized Entity as its subject, and the repository
        proves the subject belongs to the acting Principal by reading
        `knowledge.entities`. A build serving memories without the plane that
        owns their subjects would be serving writes it cannot validate.
        """
        if not self._relationship_intelligence_enabled or not self._relationship_memory_enabled:
            raise UnsupportedError()

    def _memory_repository(self, unit_of_work: UnitOfWork) -> RelationshipMemoryRepository:
        self._relationship_memory_plane()
        return unit_of_work.relationship_memory

    def _relationship_memory_create(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CreateRelationshipMemory,
    ) -> _Result:
        """`relationship_memory.create`: one direct user-authored memory."""
        repository = self._memory_repository(unit_of_work)
        with _translated(), _memory_translated():
            admission = self._memory.create(
                repository,
                CreateMemoryCommand(
                    principal_id=authorization.principal.principal_id,
                    subject_entity_id=command.entity_id,
                    memory_kind=command.kind,
                    statement=command.statement,
                    structured_value=command.structured_value,
                    context_links=_memory_links(command.context_links),
                    pinned=command.pinned,
                    observed_at=command.observed_at,
                    effective_from=command.effective_from,
                    effective_to=command.effective_to,
                    idempotency_key=command.idempotency_key,
                ),
                at=authorization.at,
            )
        return self._memory_receipt(authorization, admission)

    def _relationship_memory_revise(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReviseRelationshipMemory,
    ) -> _Result:
        """`relationship_memory.revise`: append a successor, refusing a stale expectation."""
        repository = self._memory_repository(unit_of_work)
        principal_id = authorization.principal.principal_id
        with _translated(), _memory_translated():
            existing = self._memory.get(repository, command.memory_id, principal_id=principal_id)
            if existing is None:
                raise NotFoundError(SafeDetail.MEMORY_ID)
            admission = self._memory.revise(
                repository,
                ReviseMemoryCommand(
                    principal_id=principal_id,
                    memory_id=command.memory_id,
                    expected_version=command.expected_version,
                    statement=command.statement,
                    memory_kind=command.kind,
                    structured_value=command.structured_value,
                    context_links=_memory_links(command.context_links),
                    pinned=command.pinned,
                    observed_at=command.observed_at,
                    effective_from=command.effective_from,
                    effective_to=command.effective_to,
                    correction_reason=command.correction_reason,
                    idempotency_key=command.idempotency_key,
                ),
                at=authorization.at,
                current_kind=existing.memory.memory_kind,
            )
        return self._memory_receipt(authorization, admission)

    def _relationship_memory_archive(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ArchiveRelationshipMemory,
    ) -> _Result:
        """`relationship_memory.archive`: withdraw one memory, reversibly."""
        repository = self._memory_repository(unit_of_work)
        with _translated(), _memory_translated():
            admission = self._memory.archive(
                repository,
                ArchiveMemoryCommand(
                    principal_id=authorization.principal.principal_id,
                    memory_id=command.memory_id,
                    expected_version=command.expected_version,
                    idempotency_key=command.idempotency_key,
                ),
                at=authorization.at,
            )
        return self._memory_receipt(authorization, admission)

    def _relationship_memory_restore(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: RestoreRelationshipMemory,
    ) -> _Result:
        """`relationship_memory.restore`: return one archived memory to the current set."""
        repository = self._memory_repository(unit_of_work)
        with _translated(), _memory_translated():
            admission = self._memory.restore(
                repository,
                ArchiveMemoryCommand(
                    principal_id=authorization.principal.principal_id,
                    memory_id=command.memory_id,
                    expected_version=command.expected_version,
                    idempotency_key=command.idempotency_key,
                ),
                at=authorization.at,
            )
        return self._memory_receipt(authorization, admission)

    def _relationship_memory_get(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetRelationshipMemory,
    ) -> _Result:
        """`relationship_memory.get`: one memory, its current version and provenance."""
        repository = self._memory_repository(unit_of_work)
        with _translated(), _memory_translated():
            detail = self._memory.get(
                repository, command.memory_id, principal_id=authorization.principal.principal_id
            )
        if detail is None:
            raise NotFoundError(SafeDetail.MEMORY_ID)
        return _Result(
            payload={"memory": _memory_view(detail, include_statement=command.include_statement)},
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_MEMORY_TRUST_BASIS),
        )

    def _relationship_memory_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListRelationshipMemories,
    ) -> _Result:
        """`relationship_memory.list`: one bounded page of one entity's memories."""
        repository = self._memory_repository(unit_of_work)
        limit = self._page_size(command.page_size)
        with _translated(), _memory_translated():
            page = self._memory.list_for_entity(
                repository,
                principal_id=authorization.principal.principal_id,
                subject_entity_id=command.entity_id,
                limit=limit,
                kinds=_memory_kinds(command.kinds),
                lifecycle=command.lifecycle,
                context_entity_id=command.context_entity_id,
                as_of=command.as_of,
                after_memory_id=command.after,
            )
        return self._memory_page(authorization, page, include_statement=command.include_statement)

    def _relationship_memory_search(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: SearchRelationshipMemories,
    ) -> _Result:
        """`relationship_memory.search`: lexical matches over eligible current memories."""
        repository = self._memory_repository(unit_of_work)
        limit = self._page_size(command.page_size)
        with _translated(), _memory_translated():
            page = self._memory.search(
                repository,
                principal_id=authorization.principal.principal_id,
                query=command.query,
                limit=limit,
                subject_entity_id=command.entity_id,
                kinds=_memory_kinds(command.kinds),
                after_memory_id=command.after,
            )
        return self._memory_page(authorization, page, include_statement=True)

    def _relationship_memory_history(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetRelationshipMemoryHistory,
    ) -> _Result:
        """`relationship_memory.history`: every stored version of one memory."""
        repository = self._memory_repository(unit_of_work)
        limit = self._page_size(command.page_size)
        with _translated(), _memory_translated():
            versions, truncated = self._memory.history(
                repository,
                command.memory_id,
                principal_id=authorization.principal.principal_id,
                limit=limit,
                after_version_id=command.after,
            )
        return _Result(
            payload={
                "memory_id": command.memory_id,
                "versions": [_memory_version_view(version) for version in versions],
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_MEMORY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=versions[-1].memory_version_id if truncated and versions else None,
                ),
            ),
        )

    def _memory_receipt(self, authorization: Authorization, admission: MemoryAdmission) -> _Result:
        """The one shape all four memory writes answer with.

        No statement. A receipt acknowledges that a record is durable, and one
        that echoed the note would put it on a second surface for no gain — the
        caller already has it, and a *replayed* receipt would put an earlier
        caller's text on this one.
        """
        receipt = admission.receipt
        return _Result(
            payload={
                "memory_id": receipt.memory_id,
                "memory_version_id": receipt.memory_version_id,
                "version_number": receipt.version_number,
                "version": receipt.aggregate_version,
                "lifecycle": receipt.lifecycle_state.value,
                "statement_sha256": receipt.statement_sha256,
                "idempotency_key": receipt.idempotency_key,
                "issued_at": format_rfc3339(receipt.issued_at),
                "created": admission.created,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_MEMORY_TRUST_BASIS),
        )

    def _memory_page(
        self, authorization: Authorization, page: MemoryPage, *, include_statement: bool
    ) -> _Result:
        """One page of memories, with truncation and withholding stated separately.

        They are different facts and the envelope keeps them apart: `truncation`
        says the page ran out of room and hands a cursor, and
        `memories_withheld_by_policy` says a classification decision removed
        rows this request was not eligible for. A caller reading only the first
        would take a policy omission for the end of the list.
        """
        limitations = (
            (Limitation.LISTING_HAS_NO_CONTINUATION,)
            if page.is_truncated and not page.memories
            else ()
        )
        return _Result(
            payload={
                "memories": [
                    _memory_summary_view(
                        memory,
                        page.listing_facts[memory.memory_id],
                        include_statement=include_statement,
                    )
                    for memory in page.memories
                ],
                "memories_withheld_by_policy": page.withheld_by_policy,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_MEMORY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=page.is_truncated,
                    reason="page_size_reached" if page.is_truncated else None,
                    next_cursor=(
                        page.memories[-1].memory_id if page.is_truncated and page.memories else None
                    ),
                ),
                extra_limitations=limitations,
            ),
        )

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
        with _translated(), _entity_translated():
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
        """`entities.context`: the bounded context card for one entity.

        **The memory repository is passed only when this build composed the
        plane, and the two switches are read directly rather than through
        `_relationship_memory_plane`.** That helper raises `UnsupportedError`,
        which is the right answer for the nine `relationship_memory.` handlers
        and the wrong one here: `entities.context` is an entity capability, it is
        served by builds that never turned the memory plane on, and refusing it
        for a collection it can honestly decline to speak about would withdraw a
        capability the manifest still publishes.

        Both switches, matching `available_capabilities` exactly, because a
        memory's subject is an Entity whose ownership the memory repository
        proves by reading `knowledge.entities` -- there is no composition in
        which the memory plane is usable without the entity plane, and a
        condition here that disagreed with the one there would compose a
        repository the build does not consider composed.

        `None` is not a quiet degradation: `EntityContextService` turns it into
        `THE_MEMORY_PLANE_IS_UNAVAILABLE` on the card, so a caller reading a
        payload from a build without the plane cannot mistake the empty
        collection for an absence of memories. The property access is guarded by
        that same condition rather than attempted and caught, because
        `UnitOfWork.relationship_memory` *raises* on a unit of work that did not
        compose the plane -- reaching for it first and recovering afterwards
        would make a refusal into control flow.
        """
        self._entity_plane()
        composed = self._relationship_intelligence_enabled and self._relationship_memory_enabled
        memories = unit_of_work.relationship_memory if composed else None
        with _translated():
            card = EntityContextService(unit_of_work.entities, memories).card(
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

        **Neither value the source produced is disclosed.** The context card
        omits both, because a card summarises an entity that has already been
        identified and the raw text is evidence that lives at its source. This
        queue omits both as well, and publishes `mention_display_name` — a
        separate, optional column a writer fills in deliberately.

        That column exists because the obvious design was wrong and shipped.
        This handler used to publish `normalized_value` on the argument that the
        matchable form is the same class of datum as a `canonical_name` that
        `entities.search` already returns freely. It is not: `normalize_name`
        casefolds and turns punctuation into spaces and removes **no content**,
        so `"A. Chen <a.chen@northwind.test>"` becomes
        `"a chen a chen northwind test"` — local part and domain intact, and
        `is_normalized_name`-true, so nothing downstream can tell it from a long
        real name. The mitigation was then a sentence on the port asking writers
        to supply an extracted name. `f3a8c1d7e592` replaced the sentence with a
        column, while the table still held zero rows and the change cost no
        backfill.

        **Forgetting now fails closed.** A writer that fills nothing publishes
        nothing: the mention is still listed, still carries its source pointers,
        and simply has no text beside it. Disclosure is an affirmative write.

        **Read-only, and it stays that way.** Linking a mention to an entity is
        a governed write and this plane publishes none (`D-RI-21`). A caller can
        see the queue and cannot work it, which the runbook states plainly.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        with _translated(), _entity_translated():
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

    def _entities_observations_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListEntityObservations,
    ) -> _Result:
        """`entities.observations.list`: one bounded page of recorded observations.

        The evidence log, where `entities.unresolved_mentions` is the *queue*.
        They read the same table and answer different questions: the queue is
        the subset nothing has placed, and this is everything -- including the
        mentions that were placed, which the queue by definition never shows.
        A caller working the queue needs the first; a caller auditing what this
        plane was told needs the second, and deriving one from the other would
        mean paging the whole table to find the rows that are missing from it.

        **Neither observed value goes out, here or anywhere on this plane.**
        `_observation_view` publishes identifiers, closed vocabulary members,
        versions and the optional disclosed name, exactly as
        `_unresolved_mention_view` does, and it publishes the state and
        authority columns that view has no use for. The rule is one rule: raw
        observed content is evidence that lives at its source.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        with _translated(), _entity_translated():
            found = unit_of_work.entities.observations(
                principal_id,
                command.entity_id,
                unresolved_only=command.unresolved_only,
                limit=page_size + 1,
                after_observation_id=command.after,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={"observations": [_recorded_observation_view(item) for item in page]},
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

    def _entities_observe(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ObserveEntityMention,
    ) -> _Result:
        """`entities.observe`: record what a source said, and create nothing.

        The handler restates no rule. Which authorities an origin admits,
        whether a product-owned capture may claim a source's standing, what the
        normalized form is and what the ledger row looks like all stay in
        `EntityGovernanceService`, so a second copy here cannot disagree with
        them. What this file supplies is the Principal, the clock, the
        correlation and the audit reference the authorization already resolved
        -- and the command has no field for any of them, so there is nothing a
        caller could have sent for them to be confused with.
        """
        self._entity_writes()
        with _translated(), _entity_governance_translated():
            admission = EntityGovernanceService(unit_of_work.entities).ingest(
                ObserveCommand(
                    principal_id=authorization.principal.principal_id,
                    kind=command.kind,
                    authority=command.authority,
                    observed_value=command.observed_value,
                    observed_at=command.observed_at,
                    idempotency_key=command.idempotency_key,
                    mention_display_name=command.mention_display_name,
                    source_id=command.source_id,
                    source_object_id=command.source_object_id,
                    source_version_id=command.source_version_id,
                    capture_id=command.capture_id,
                    capture_version_id=command.capture_version_id,
                    entity_id=command.entity_id,
                    expected_entity_version=command.expected_entity_version,
                ),
                sources=unit_of_work.sources,
                at=authorization.at,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
            )
        return _Result(
            payload={
                "observation_id": admission.observation_id,
                "kind": admission.kind.value,
                "authority": admission.authority.value,
                "origin": admission.origin.value,
                "state": admission.state.value,
                "resolution_version": admission.resolution_version,
                "entity_id": admission.entity_id,
                "recorded_at": format_rfc3339(admission.recorded_at),
                "idempotency_key": admission.idempotency_key,
                "created": admission.created,
                # The ledger row, which is what a receipt is on this plane.
                #
                # **No count is stated here, and the omission is deliberate.**
                # This comment once counted the writes -- "every one of the
                # eighteen" -- from Phase A, when eighteen was the whole entity
                # write surface; the plane has grown since, and the writes it
                # grew by do not all share the shape the sentence claimed. What is stated instead is
                # what each append path says of itself. The ten identity,
                # identifier and alias writes append through
                # `entity_authoring._record_mutation`, the six directed writes
                # through `SqlEntityRepository._append_mutation`, and the fifteen
                # RI-ENT-WP-11 record-family writes through
                # `EntityFamilyWriteService` into `record_mutation_event`; each of
                # those three hands back the row's own `event_id` under this key
                # and leaves the `receipt_id` column null, and each says so in
                # its own docstring. This handler and
                # `entities.unresolved_mentions.resolve` return the row's
                # `event_id` here too. The identity-correction writes
                # (`entities.merge`, `entities.split` and their previews) answer
                # with an `IdentityOperation`'s own `receipt_id`, which is a
                # different shape and is not characterised by this comment.
                "receipt_id": admission.mutation_event_id,
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
        )

    def _entities_unresolved_mentions_resolve(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ResolveUnresolvedMention,
    ) -> _Result:
        """`entities.unresolved_mentions.resolve`: decide one mention, or refuse.

        The fresh resolution is built here and run inside this transaction,
        against the state that exists now rather than the state the queue was
        rendered from. It is handed to the use case as a callable so that module
        cannot reach a second read of the entity plane through it, and so the
        resolver's own request vocabulary stays out of a module whose subject is
        governance.

        `decided_by` is the acting Principal and `ActorClass.USER`, both
        server-supplied. There is no field on the command for either: a caller
        that could name who decided something could name somebody else.
        """
        self._entity_writes()
        principal_id = authorization.principal.principal_id
        resolver = EntityResolutionService(unit_of_work.entities)

        def resolve_now(
            observation: EntityObservation, refused: frozenset[str], at: datetime
        ) -> EntityResolution:
            return resolver.resolve(
                principal_id,
                ResolutionRequest(
                    raw_reference=observation.observed_value,
                    at=at,
                    refused_entity_ids=refused,
                ),
            )

        with _translated(), _entity_governance_translated():
            decided = EntityGovernanceService(unit_of_work.entities).resolve_mention(
                ResolveMentionCommand(
                    principal_id=principal_id,
                    observation_id=command.observation_id,
                    expected_resolution_version=command.expected_resolution_version,
                    disposition=command.disposition,
                    idempotency_key=command.idempotency_key,
                    entity_id=command.entity_id,
                    expected_entity_version=command.expected_entity_version,
                    entity_type=command.entity_type,
                    canonical_name=command.canonical_name,
                    display_name=command.display_name,
                    rejected_entity_id=command.rejected_entity_id,
                    reason=command.reason,
                ),
                resolve=resolve_now,
                at=authorization.at,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                decided_by=principal_id,
                actor_class=ActorClass.USER,
            )
        return _Result(
            payload={
                "decision_id": decided.decision_id,
                "observation_id": decided.observation_id,
                "disposition": decided.disposition.value,
                "resolution_version": decided.resolution_version,
                "entity_id": decided.entity_id,
                "evidence_link_ids": list(decided.evidence_link_ids),
                "decided_at": format_rfc3339(decided.decided_at),
                "idempotency_key": decided.idempotency_key,
                "created": decided.created,
                #: The ledger row, on `entities.observe`'s terms.
                "receipt_id": decided.mutation_event_id,
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
            reenrichment_cause_id=(decided.decision_id if decided.created else None),
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
        with _translated(), _entity_translated():
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
                    next_cursor=page[-1].relationship_id if truncated and page else None,
                ),
            ),
        )

    def _entities_graph(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetEntityGraph,
    ) -> _Result:
        """`entities.graph`: one bounded page of a seeded 1-hop or 2-hop neighborhood.

        Seeds are read first so an unknown or foreign identifier is `not_found`
        naming that field — an empty graph is "this person has no recorded
        neighborhood", not "there is no such person".

        `is_current` is computed only when the caller supplied `as_of`, using
        the same `_assignment_view` / `_relationship_view` rule. The request
        clock is not substituted.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        seeds: list[tuple[str, SafeDetail]] = []
        if command.focus_entity_id is not None:
            seeds.append((command.focus_entity_id, SafeDetail.FOCUS_ENTITY_ID))
        if command.scope_entity_id is not None:
            seeds.append((command.scope_entity_id, SafeDetail.SCOPE_ENTITY_ID))
        seed_ids = frozenset(entity_id for entity_id, _ in seeds)
        with _translated(), _entity_translated():
            for entity_id, detail in seeds:
                if unit_of_work.entities.get(principal_id, entity_id) is None:
                    raise NotFoundError(detail)
            found = unit_of_work.entities.graph_neighborhood(
                principal_id,
                seed_ids,
                hops=command.hops,
                relationship_types=(
                    None
                    if command.relationship_types is None
                    else frozenset(command.relationship_types)
                ),
                limit=page_size + 1,
                after_edge_id=command.after,
            )
        page, truncated = _bounded_graph_edges(found.assignments, found.relationships, page_size)
        last_edge_id = _graph_edge_id(page[-1]) if truncated and page else None
        payload = _graph_view(
            entities=found.entities,
            page=page,
            seed_ids=seed_ids,
            at=command.as_of,
        )
        payload["next_cursor"] = last_edge_id
        return _Result(
            payload=payload,
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=last_edge_id,
                ),
            ),
        )

    # ---- the entity plane's authoring half (WP-RI-A-02) ---------------------
    #
    # Two paged reads and ten writes, over one service. The shape is the one the
    # Relationship Memory handlers use: resolve the gate, hand the use case the
    # Principal the authorization already resolved, and restate no rule. Which
    # duplicate refuses a create, which status a restore returns to, whether a
    # re-bind is a duplicate, and what a stale expectation leaves behind all stay
    # in `application.entity_authoring`, the repository and the domain, so a
    # second copy here cannot disagree with them.
    #
    # `principal_id=authorization.principal.principal_id` is the only thing these
    # handlers say about identity, and the transport commands have no
    # `principal_id` field at all, so there is nothing a caller could have
    # supplied for it to be confused with.

    def _entities_identifiers_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListEntityIdentifiers,
    ) -> _Result:
        """`entities.identifiers.list`: one bounded page of an entity's bindings.

        The entity is read first so an unknown identifier is `not_found` naming
        `entity_id` rather than `cursor` -- `_entity_translated` maps every
        `UnknownScopeError` on this plane to the cursor, which is right for the
        one thing the paged reads refuse and wrong for the entity itself. "There
        is no such person" and "that position is not yours" are different
        answers and a caller can act on only one of them.
        """
        self._entity_plane()
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        with _translated():
            if unit_of_work.entities.get(principal_id, command.entity_id) is None:
                raise NotFoundError(SafeDetail.ENTITY_ID)
        with _translated(), _entity_translated():
            page = unit_of_work.entities.identifier_page(
                command.entity_id,
                principal_id=principal_id,
                limit=page_size,
                states=None if command.states is None else frozenset(command.states),
                namespaces=None if command.namespaces is None else frozenset(command.namespaces),
                after_identifier_id=command.after,
            )
        return _Result(
            payload={
                "entity_id": command.entity_id,
                "identifiers": [_lifecycle_identifier_view(record) for record in page.records],
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=page.is_truncated,
                    reason="page_size_reached" if page.is_truncated else None,
                    next_cursor=(
                        page.records[-1].identifier_id
                        if page.is_truncated and page.records
                        else None
                    ),
                ),
            ),
        )

    def _entities_aliases_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListEntityAliases,
    ) -> _Result:
        """`entities.aliases.list`: one bounded page of an entity's recorded names.

        The entity is read first, for the reason `_entities_identifiers_list`
        states beside its own read.
        """
        self._entity_plane()
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        with _translated():
            if unit_of_work.entities.get(principal_id, command.entity_id) is None:
                raise NotFoundError(SafeDetail.ENTITY_ID)
        with _translated(), _entity_translated():
            page = unit_of_work.entities.alias_page(
                command.entity_id,
                principal_id=principal_id,
                limit=page_size,
                states=None if command.states is None else frozenset(command.states),
                alias_types=(
                    None if command.alias_types is None else frozenset(command.alias_types)
                ),
                after_alias_id=command.after,
            )
        return _Result(
            payload={
                "entity_id": command.entity_id,
                "aliases": [_lifecycle_alias_view(record) for record in page.records],
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=page.is_truncated,
                    reason="page_size_reached" if page.is_truncated else None,
                    next_cursor=(
                        page.records[-1].alias_id if page.is_truncated and page.records else None
                    ),
                ),
            ),
        )

    # ---- RI-ENT-WP-10: the record families' read surface --------------------
    #
    # One composite and four pages. All five read through `unit_of_work.entities`
    # after `self._entity_plane()` -- the read gate -- and never through
    # `self._entity_repository`, which is the *write* gate: routing a read
    # through it would withhold these five from every build that composed the
    # plane without turning writes on, which is the composition the runbook
    # calls the ordinary one.
    #
    # Every one of the five reads the entity first, so an unknown identifier is
    # `not_found` rather than an empty collection. "Nothing is recorded about
    # this person" and "there is no such person" are different answers and a
    # caller can act on only one of them -- the argument `_entities_relationships`
    # makes beside its own read, and these five make it the same way.

    def _entities_profile(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetEntityProfile
    ) -> _Result:
        """`entities.profile`: everything on file about one entity, bounded per collection.

        **A new capability rather than a widening of `entities.context`.** That
        card is a fixed set of keys existing callers already parse, and adding
        collections to it would change a response none of them asked to change.
        The two answer different questions off different tables: the card
        summarises who this is out of aliases, identifiers, assignments, edges,
        observations and memories, and this returns what is recorded out of the
        six entity-bound record families.

        **Bounded like the card, not like the pages.** Each collection is read
        one row past `ENTITY_PROFILE_COLLECTION_LIMIT`, so an overflow is
        observed rather than inferred from a collection that happened to be
        full, and each overflow names itself: a caller told only "something was
        truncated" would have to page all four families to find out which. No
        cursor is issued, and that is deliberate -- a cursor into an assembly of
        seven collections would have to mean seven positions at once. The four
        `entities.*.list` capabilities are the continuation, one family each.

        `partial_result` is not set here. `unenrolled_disclosure` derives it,
        and a handler that also set it would be a second statement of one fact.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        fetch = ENTITY_PROFILE_COLLECTION_LIMIT + 1
        entity_id = command.entity_id
        with _translated(), _entity_translated():
            entity = unit_of_work.entities.get(principal_id, entity_id)
            if entity is None:
                raise NotFoundError(SafeDetail.TARGET_ID)
            entities = unit_of_work.entities
            organization_profile = entities.organization_profile(principal_id, entity_id)
            names, more_names = _profile_collection(
                entities.names(principal_id, entity_id, limit=fetch)
            )
            addresses, more_addresses = _profile_collection(
                entities.addresses(principal_id, entity_id, limit=fetch)
            )
            methods, more_methods = _profile_collection(
                entities.communication_methods(principal_id, entity_id, limit=fetch)
            )
            as_project, more_as_project = _profile_collection(
                entities.project_participations_as_project(principal_id, entity_id, limit=fetch)
            )
            as_participant, more_as_participant = _profile_collection(
                entities.project_participations_as_participant(principal_id, entity_id, limit=fetch)
            )
            as_person, more_as_person = _profile_collection(
                entities.person_organization_affiliations_as_person(
                    principal_id, entity_id, limit=fetch
                )
            )
            as_organization, more_as_organization = _profile_collection(
                entities.person_organization_affiliations_as_organization(
                    principal_id, entity_id, limit=fetch
                )
            )
        limitations = [
            limitation
            for overflowed, limitation in (
                (more_names, EntityProfileLimitation.MORE_NAMES_THAN_THIS_PROFILE_CARRIES),
                (
                    more_addresses,
                    EntityProfileLimitation.MORE_ADDRESSES_THAN_THIS_PROFILE_CARRIES,
                ),
                (
                    more_methods,
                    EntityProfileLimitation.MORE_COMMUNICATION_METHODS_THAN_THIS_PROFILE_CARRIES,
                ),
                (
                    more_as_project,
                    EntityProfileLimitation.MORE_PARTICIPATIONS_AS_PROJECT_THAN_THIS_PROFILE_CARRIES,
                ),
                (
                    more_as_participant,
                    EntityProfileLimitation.MORE_PARTICIPATIONS_AS_PARTICIPANT_THAN_THIS_PROFILE_CARRIES,
                ),
                (
                    more_as_person,
                    EntityProfileLimitation.MORE_AFFILIATIONS_AS_PERSON_THAN_THIS_PROFILE_CARRIES,
                ),
                (
                    more_as_organization,
                    EntityProfileLimitation.MORE_AFFILIATIONS_AS_ORGANIZATION_THAN_THIS_PROFILE_CARRIES,
                ),
            )
            if overflowed
        ]
        is_complete = not limitations
        return _Result(
            payload={
                "profile": {
                    # Limitations and completeness before the records, per
                    # `RI-AC-013`: what was left out belongs above the list it
                    # qualifies, not appended after a reader has already drawn
                    # a conclusion from it.
                    "entity": _entity_view(entity),
                    "assembled_at": format_rfc3339(authorization.at),
                    "limitations": [limitation.value for limitation in limitations],
                    "is_complete": is_complete,
                    "organization_profile": (
                        None
                        if organization_profile is None
                        else _organization_profile_view(organization_profile)
                    ),
                    "names": [_entity_name_view(record) for record in names],
                    "addresses": [_entity_address_view(record) for record in addresses],
                    "communication_methods": [
                        _communication_method_view(record) for record in methods
                    ],
                    "participations_as_project": [
                        _participation_view(record) for record in as_project
                    ],
                    "participations_as_participant": [
                        _participation_view(record) for record in as_participant
                    ],
                    "affiliations_as_person": [_affiliation_view(record) for record in as_person],
                    "affiliations_as_organization": [
                        _affiliation_view(record) for record in as_organization
                    ],
                }
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=not is_complete,
                    # `Truncation` refuses `is_truncated` without a reason. The
                    # bound is this answer's own per-collection ceiling rather
                    # than a page size the caller chose, and the reason says so
                    # -- exactly as `entities.context` distinguishes its card
                    # ceiling from a page.
                    reason=None if is_complete else "profile_collection_limit_reached",
                ),
            ),
        )

    def _entities_names_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListEntityNames
    ) -> _Result:
        """`entities.names.list`: one bounded page of an entity's typed name forms.

        The continuation for the collection `entities.profile` bounds. The
        overflow flag comes off `EntityChildPage` rather than being re-derived
        from the length of the page, which is `_entities_identifiers_list`'s
        idiom: the repository read one row past the ceiling and already knows.
        """
        self._entity_plane()
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        with _translated():
            if unit_of_work.entities.get(principal_id, command.entity_id) is None:
                raise NotFoundError(SafeDetail.TARGET_ID)
        with _translated(), _entity_translated():
            page = unit_of_work.entities.name_page(
                command.entity_id,
                principal_id=principal_id,
                limit=page_size,
                after_entity_name_id=command.after,
            )
        return _Result(
            payload={
                "entity_id": command.entity_id,
                "names": [_entity_name_view(record) for record in page.records],
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=page.is_truncated,
                    reason="page_size_reached" if page.is_truncated else None,
                    next_cursor=(
                        page.records[-1].entity_name_id
                        if page.is_truncated and page.records
                        else None
                    ),
                ),
            ),
        )

    def _entities_addresses_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListEntityAddresses
    ) -> _Result:
        """`entities.addresses.list`: one bounded page of an entity's addresses.

        `_entities_names_list`'s contract over the address family.
        """
        self._entity_plane()
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        with _translated():
            if unit_of_work.entities.get(principal_id, command.entity_id) is None:
                raise NotFoundError(SafeDetail.TARGET_ID)
        with _translated(), _entity_translated():
            page = unit_of_work.entities.address_page(
                command.entity_id,
                principal_id=principal_id,
                limit=page_size,
                after_entity_address_id=command.after,
            )
        return _Result(
            payload={
                "entity_id": command.entity_id,
                "addresses": [_entity_address_view(record) for record in page.records],
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=page.is_truncated,
                    reason="page_size_reached" if page.is_truncated else None,
                    next_cursor=(
                        page.records[-1].entity_address_id
                        if page.is_truncated and page.records
                        else None
                    ),
                ),
            ),
        )

    def _entities_communication_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListEntityCommunicationMethods,
    ) -> _Result:
        """`entities.communication.list`: one bounded page of an entity's channels.

        `_entities_names_list`'s contract over the communication family.
        """
        self._entity_plane()
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        with _translated():
            if unit_of_work.entities.get(principal_id, command.entity_id) is None:
                raise NotFoundError(SafeDetail.TARGET_ID)
        with _translated(), _entity_translated():
            page = unit_of_work.entities.communication_method_page(
                command.entity_id,
                principal_id=principal_id,
                limit=page_size,
                after_communication_method_id=command.after,
            )
        return _Result(
            payload={
                "entity_id": command.entity_id,
                "communication_methods": [
                    _communication_method_view(record) for record in page.records
                ],
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=page.is_truncated,
                    reason="page_size_reached" if page.is_truncated else None,
                    next_cursor=(
                        page.records[-1].communication_method_id
                        if page.is_truncated and page.records
                        else None
                    ),
                ),
            ),
        )

    def _entities_participations_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListEntityParticipations,
    ) -> _Result:
        """`entities.participations.list`: one bounded page from one end of the relation.

        `_entities_names_list`'s contract over the participation family, plus
        the end the caller stated. `perspective` is echoed in the payload
        beside `entity_id` because the two together are what the page is about:
        a caller holding two pages of participations and no perspective on
        either cannot tell which one lists the projects and which lists the
        people.
        """
        self._entity_plane()
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        with _translated():
            if unit_of_work.entities.get(principal_id, command.entity_id) is None:
                raise NotFoundError(SafeDetail.TARGET_ID)
        with _translated(), _entity_translated():
            page = unit_of_work.entities.participation_page(
                command.entity_id,
                principal_id=principal_id,
                perspective=command.perspective,
                limit=page_size,
                after_participation_id=command.after,
            )
        return _Result(
            payload={
                "entity_id": command.entity_id,
                "perspective": command.perspective,
                "participations": [_participation_view(record) for record in page.records],
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=page.is_truncated,
                    reason="page_size_reached" if page.is_truncated else None,
                    next_cursor=(
                        page.records[-1].participation_id
                        if page.is_truncated and page.records
                        else None
                    ),
                ),
            ),
        )

    # --- RI-ENT-WP-11: the record families' writes -------------------------
    #
    # One handler per capability and one shape for all of them: take the port
    # through the *write* gate, translate what the plane refuses, hand the
    # command to `EntityFamilyWriteService`, and answer with `_directed_receipt`.
    # The receipt shape is shared with the directed writes deliberately -- both
    # planes answer with the mutation-ledger row they wrote, and a second
    # payload shape for the same fact would be a second thing to keep true.
    #
    # `_entity_repository` and not `_entity_plane`: these write, so both the
    # plane switch and the write switch apply, which is what that method exists
    # to check once rather than at every call site.
    #
    # **No re-enrichment is registered by any of them, and that is a decision
    # rather than an omission.** `ReenrichmentSubjectKind` has no member for a
    # name, an address, a communication method, a participation or an
    # affiliation, and `_SUBJECT_ID_KINDS` maps every member it does have to an
    # `IdKind`, so a direct caller here could not name the subject it changed.
    # The generic path is the alternative and it is worse: an entry in
    # `TRIGGERS_BY_MUTATION_CAPABILITY` would register Principal-wide work for
    # every one of these writes under a trigger that belongs to a different
    # record family -- `NEW_ALIAS` when no alias row was written, or
    # `ROLE_OR_ORGANIZATION_CHANGE` when no assignment was. Naming a trigger for
    # a change it does not describe is the shape
    # `TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND` records seven absences for. Widening
    # the subject vocabulary belongs to the re-enrichment package.

    def _entities_names_add(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: AddEntityName
    ) -> _Result:
        """`entities.names.add`: record one typed name form for an entity."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.add_name(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_names_supersede(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SupersedeEntityName
    ) -> _Result:
        """`entities.names.supersede`: replace one recorded name with its successor.

        A supersession and never an edit. The receipt names the successor in
        `record_id` and the predecessor in `superseded_id`, so a caller can read
        both back.
        """
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.supersede_name(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_names_retire(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: RetireEntityName
    ) -> _Result:
        """`entities.names.retire`: withdraw one recorded name, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.retire_name(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_addresses_add(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: AddEntityAddress
    ) -> _Result:
        """`entities.addresses.add`: record one typed address for an entity."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.add_address(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_addresses_revise(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReviseEntityAddress
    ) -> _Result:
        """`entities.addresses.revise`: replace one recorded address with its successor.

        A supersession and never an edit, exactly as `entities.names.supersede`
        is; the audit's two spellings name one act.
        """
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.revise_address(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_addresses_retire(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: RetireEntityAddress
    ) -> _Result:
        """`entities.addresses.retire`: withdraw one recorded address, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.retire_address(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_communication_add(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: AddEntityCommunicationMethod,
    ) -> _Result:
        """`entities.communication.add`: record one contact channel for an entity."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.add_communication_method(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_communication_revise(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReviseEntityCommunicationMethod,
    ) -> _Result:
        """`entities.communication.revise`: replace one contact channel with its successor.

        A supersession and never an edit, exactly as `entities.names.supersede`
        is; the audit's two spellings name one act.
        """
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.revise_communication_method(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_communication_retire(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: RetireEntityCommunicationMethod,
    ) -> _Result:
        """`entities.communication.retire`: withdraw one contact channel, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.retire_communication_method(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_participations_create(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CreateEntityParticipation,
    ) -> _Result:
        """`entities.participations.create`: record one participation on one project."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.create_participation(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_participations_revise(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReviseEntityParticipation,
    ) -> _Result:
        """`entities.participations.revise`: replace one participation with its successor.

        A supersession and never an edit, exactly as `entities.names.supersede`
        is; the audit's two spellings name one act.
        """
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.revise_participation(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_participations_end(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: EndEntityParticipation,
    ) -> _Result:
        """`entities.participations.end`: withdraw one participation, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.end_participation(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_affiliations_create(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CreateEntityAffiliation,
    ) -> _Result:
        """`entities.affiliations.create`: record one person's affiliation."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.create_affiliation(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_affiliations_revise(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReviseEntityAffiliation,
    ) -> _Result:
        """`entities.affiliations.revise`: replace one affiliation with its successor.

        A supersession and never an edit, exactly as `entities.names.supersede`
        is; the audit's two spellings name one act.
        """
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.revise_affiliation(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_affiliations_end(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: EndEntityAffiliation,
    ) -> _Result:
        """`entities.affiliations.end`: withdraw one affiliation, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated(), _record_family_translated():
            receipt = self._family_writes.end_affiliation(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateEntity
    ) -> _Result:
        """`entities.create`: one entity, or a refusal naming why one already exists."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.create(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_type=command.entity_type,
                display_name=command.display_name,
                aliases=_named_values(command.aliases, "alias_type"),
                identifiers=_named_values(command.identifiers, "namespace"),
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_update(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: UpdateEntity
    ) -> _Result:
        """`entities.update`: correct a name, a matched name, or a status."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.update(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                display_name=command.display_name,
                canonical_name=command.canonical_name,
                status=command.status,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_archive(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ArchiveEntity
    ) -> _Result:
        """`entities.archive`: withdraw one entity, recording what to restore it to."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.archive(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_restore(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: RestoreEntity
    ) -> _Result:
        """`entities.restore`: return one archived entity to the status it held."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.restore(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_identifiers_bind(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: BindEntityIdentifier,
    ) -> _Result:
        """`entities.identifiers.bind`: record one address as this entity's identity."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.bind_identifier(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                namespace=command.namespace,
                display_value=command.display_value,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                evidence=command.evidence,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_identifiers_retire(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: RetireEntityIdentifier,
    ) -> _Result:
        """`entities.identifiers.retire`: withdraw one binding, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.retire_identifier(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                identifier_id=command.identifier_id,
                expected_identifier_version=command.expected_identifier_version,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_identifiers_supersede(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: SupersedeEntityIdentifier,
    ) -> _Result:
        """`entities.identifiers.supersede`: replace one binding, atomically."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.supersede_identifier(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                identifier_id=command.identifier_id,
                expected_identifier_version=command.expected_identifier_version,
                namespace=command.namespace,
                display_value=command.display_value,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                evidence=command.evidence,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_aliases_add(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: AddEntityAlias
    ) -> _Result:
        """`entities.aliases.add`: record one more name this entity goes by."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.add_alias(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                alias_type=command.alias_type,
                display_value=command.display_value,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                evidence=command.evidence,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        receipt = admission.receipt
        if admission.created and receipt.child_id is not None and receipt.child_version is not None:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.NEW_ALIAS,
                receipt.event_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.ENTITY,
                        receipt.entity_id,
                        str(receipt.entity_version),
                    ),
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.ALIAS,
                        receipt.child_id,
                        str(receipt.child_version),
                    ),
                ),
            )
        return self._entity_receipt(authorization, admission)

    def _entities_aliases_retire(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: RetireEntityAlias
    ) -> _Result:
        """`entities.aliases.retire`: withdraw one name form, keeping it matchable."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.retire_alias(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                alias_id=command.alias_id,
                expected_alias_version=command.expected_alias_version,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entities_aliases_supersede(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: SupersedeEntityAlias,
    ) -> _Result:
        """`entities.aliases.supersede`: correct one name form, naming the successor."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _entity_authoring_translated():
            admission = self._entity_authoring.supersede_alias(
                repository,
                principal_id=authorization.principal.principal_id,
                entity_id=command.entity_id,
                expected_version=command.expected_version,
                alias_id=command.alias_id,
                expected_alias_version=command.expected_alias_version,
                alias_type=command.alias_type,
                display_value=command.display_value,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                evidence=command.evidence,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
                correlation_id=authorization.correlation_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        return self._entity_receipt(authorization, admission)

    def _entity_repository(self, unit_of_work: UnitOfWork) -> EntitiesRepository:
        """The entity port, behind the two gates every *writing* handler shares.

        `_entity_writes` and not `_entity_plane`: the sixteen handlers that ask
        for the port through this method all write, so both switches are checked
        here rather than sixteen times. The reads reach `unit_of_work.entities`
        directly after their own `_entity_plane()` call, which is the gate that
        applies to them and the only one that does.
        """
        self._entity_writes()
        return unit_of_work.entities

    def _register_reenrichment(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        trigger: ReenrichmentTrigger,
        cause: str,
        subjects: tuple[ReenrichmentSubject, ...],
    ) -> None:
        try:
            repository = unit_of_work.reenrichment
        except NotImplementedError:
            # Compatibility for older isolated test doubles. Production's
            # SqlAlchemyUnitOfWork always composes the durable repository.
            return
        caller = ProductionReenrichmentCaller(
            repository,
            principal_id=authorization.principal.principal_id,
            policy_version=authorization.decision.policy_version,
        )
        caller.register(trigger, cause, subjects, at=authorization.at)

    def _entity_receipt(
        self, authorization: Authorization, admission: EntityMutationAdmission
    ) -> _Result:
        """The one shape all ten entity writes answer with.

        **No name and no address.** A receipt acknowledges that a record is
        durable; echoing what was written would put a person's mailbox on a
        second surface for no gain, since the caller already has it — and a
        *replayed* receipt would put an earlier caller's value on this one.

        `idempotent_replay` is stated rather than left to be inferred from
        versions. A client whose response was lost retries, gets this, and has to
        know whether its retry wrote anything; comparing versions cannot answer
        that, because a concurrent writer could have advanced them either way.
        """
        receipt = admission.receipt
        return _Result(
            payload={
                "record_id": receipt.record_id,
                "record_family": receipt.record_family.value,
                "entity_id": receipt.entity_id,
                "entity_version": receipt.entity_version,
                "lifecycle_state": receipt.entity_status.value,
                "child_id": receipt.child_id,
                "child_version": receipt.child_version,
                "child_state": receipt.child_state,
                "superseded_ids": list(receipt.superseded_ids),
                "evidence_refs": list(receipt.evidence_link_ids),
                "receipt_id": receipt.event_id,
                "audit_id": authorization.audit_id,
                "idempotent_replay": not admission.created,
                "canonical_entity_id": receipt.canonical_entity_id,
            },
            disclosure=unenrolled_disclosure(
                authorization.at, trust_basis=_ENTITY_AUTHORING_TRUST_BASIS
            ),
            reenrichment_cause_id=(receipt.event_id if admission.created else None),
        )

    # ---- the directed-relationship family (WP-RI-A-03) ---------------------
    #
    # One read and six writes over `entity_assignments` and
    # `entity_relationships`. Every one of them calls `_entity_plane()` first,
    # for the reason that method's docstring gives: `available_capabilities`
    # withholds these names from `capabilities.get` and from the MCP tool list,
    # and the HTTP transport consults neither -- it routes by path segment
    # straight into `_HANDLERS`.
    #
    # No directed-write rule is restated in this file. Which duplicates are
    # refused, which version guard applies, what a replay returns and what the
    # ledger records all stay in `EntityDirectedService`, the repository and the
    # schema, so a second copy here cannot disagree with them.
    #
    # `principal_id=authorization.principal.principal_id` is the only thing these
    # handlers say about identity, and the commands have no `principal_id` field
    # at all, so there is nothing a caller could have supplied for it to be
    # confused with.

    def _entities_assignments_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListEntityAssignments,
    ) -> _Result:
        """`entities.assignments.list`: one bounded page of an entity's assignments.

        The entity is read first so an unknown identifier is `not_found` rather
        than an empty page -- "this person holds no assignments" and "there is no
        such person" are different answers, and `_entities_relationships` draws
        the same distinction for the same reason.

        One row past the page is fetched and dropped, so a corpus of exactly
        `page_size` rows is not reported as truncated and the last page of a
        larger one is not reported as complete.
        """
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        with _translated(), _entity_translated():
            entity = unit_of_work.entities.get(principal_id, command.entity_id)
            if entity is None:
                raise NotFoundError(SafeDetail.ENTITY_ID)
            found = unit_of_work.entities.assignments_page(
                principal_id,
                command.entity_id,
                active_only=command.active_only,
                limit=page_size + 1,
                after_assignment_id=command.after,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={
                "assignments": [
                    _assignment_view(assignment, authorization.at) for assignment in page
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_ENTITY_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].assignment_id if truncated and page else None,
                ),
            ),
        )

    def _entities_assignments_create(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CreateEntityAssignment,
    ) -> _Result:
        """`entities.assignments.create`: one new typed assignment."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated():
            receipt = self._directed.create_assignment(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        if not receipt.replayed:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
                receipt.mutation_event_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.ASSIGNMENT,
                        receipt.record_id,
                        str(receipt.version),
                    ),
                ),
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_assignments_revise(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReviseEntityAssignment,
    ) -> _Result:
        """`entities.assignments.revise`: correct what an assignment describes."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated():
            receipt = self._directed.revise_assignment(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        if not receipt.replayed:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
                receipt.mutation_event_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.ASSIGNMENT, receipt.record_id, str(receipt.version)
                    ),
                ),
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_assignments_end(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: EndEntityAssignment,
    ) -> _Result:
        """`entities.assignments.end`: withdraw one assignment, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated():
            receipt = self._directed.end_assignment(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        if not receipt.replayed:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
                receipt.mutation_event_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.ASSIGNMENT, receipt.record_id, str(receipt.version)
                    ),
                ),
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_relationships_create(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CreateEntityRelationship,
    ) -> _Result:
        """`entities.relationships.create`: assert one directed edge, and only one."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated():
            receipt = self._directed.create_relationship(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        if not receipt.replayed:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
                receipt.mutation_event_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.RELATIONSHIP,
                        receipt.record_id,
                        str(receipt.version),
                    ),
                ),
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_relationships_revise(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReviseEntityRelationship,
    ) -> _Result:
        """`entities.relationships.revise`: correct when an edge applies."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated():
            receipt = self._directed.revise_relationship(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        if not receipt.replayed:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
                receipt.mutation_event_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.RELATIONSHIP,
                        receipt.record_id,
                        str(receipt.version),
                    ),
                ),
            )
        return self._directed_receipt(authorization, receipt)

    def _entities_relationships_end(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: EndEntityRelationship,
    ) -> _Result:
        """`entities.relationships.end`: withdraw one directed edge, keeping the row."""
        repository = self._entity_repository(unit_of_work)
        with _translated(), _directed_translated():
            receipt = self._directed.end_relationship(
                repository,
                command,
                principal_id=authorization.principal.principal_id,
                audit_id=authorization.audit_id,
                at=authorization.at,
            )
        if not receipt.replayed:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
                receipt.mutation_event_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.RELATIONSHIP,
                        receipt.record_id,
                        str(receipt.version),
                    ),
                ),
            )
        return self._directed_receipt(authorization, receipt)

    def _directed_receipt(self, authorization: Authorization, receipt: DirectedReceipt) -> _Result:
        """The one shape every directed write and every record-family write answers with.

        Both groups return through here: the directed writes --
        `entities.create` and the assignment and relationship `revise`/`end`
        handlers -- and the record-family handlers above them. The shape is
        shared deliberately: both planes answer with the mutation-ledger row
        they wrote, and a second payload shape for the same fact would be a
        second thing to keep true. No count of callers is stated. This line
        once said "all six", which was true of the directed group alone and
        wrong of the method, because the record-family handlers had joined it
        without the sentence moving -- the same drift the entity-plane prose
        guard exists for, one level down from the write set it derives.

        Every field the completion contract asks a mutation to return: the
        record it touched, the version it now stands at, the lifecycle state it
        is in, the receipt, the audit identifier, and whether this call did the
        work or found it already done.

        `superseded_id` is present and null on every answer rather than absent.
        This package's `end` moves a record to `ended` and names no successor --
        `superseded` is the correction path and nothing here writes it -- so the
        honest answer is a stated null, and a caller reading the field gets one
        rather than a key error and a retry.

        `replayed` is not a warning and is not a limitation. A retry that finds
        its work already done succeeded; saying so in the payload is what lets a
        caller tell "I did this" from "this was already done", and both are
        successes.
        """
        return _Result(
            payload={
                "record_id": receipt.record_id,
                "record_family": receipt.record_family.value,
                "prior_version": receipt.prior_version,
                "version": receipt.version,
                "state": receipt.state,
                "receipt_id": receipt.mutation_event_id,
                "audit_id": receipt.audit_id,
                "idempotency_key": receipt.idempotency_key,
                "superseded_id": receipt.superseded_id,
                "evidence_refs": list(receipt.evidence_refs),
                "replayed": receipt.replayed,
                "issued_at": format_rfc3339(receipt.issued_at),
            },
            disclosure=unenrolled_disclosure(
                authorization.at, trust_basis=_ENTITY_AUTHORING_TRUST_BASIS
            ),
            reenrichment_cause_id=(receipt.mutation_event_id if not receipt.replayed else None),
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
        task_payload = _task_view(task).to_canonical_dict()
        if task.closure_evidence_ref is not None:
            with _translated():
                closure = unit_of_work.tasks.latest_applied_terminal_history(
                    authorization.principal.principal_id, command.task_id
                )
            task_payload["closure_history_id"] = None if closure is None else closure.history_id
        return _Result(
            payload={"task": task_payload},
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
        work_start: datetime | None = None
        work_end: datetime | None = None
        if command.work_view is not None and command.work_date is not None:
            work_start, work_end = _work_window(
                command.work_date,
                command.timezone or "UTC",
                recent=command.work_view is TaskWorkView.RECENTLY_UPDATED,
            )
        with _work_cursor_translated(), _translated():
            found = unit_of_work.tasks.list_tasks(
                authorization.principal.principal_id,
                lifecycle_state=command.lifecycle_state,
                priority=command.priority,
                archive_mode=command.archive_mode,
                after=command.after,
                work_view=command.work_view,
                work_start=work_start,
                work_end=work_end,
                work_now=authorization.at,
                limit=page_size + 1,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        entries = [_task_list_entry(task).to_canonical_dict() for task in page]
        return _Result(
            payload={"tasks": entries},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_TASK_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].task_id if truncated and page else None,
                ),
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
        work_start: datetime | None = None
        work_end: datetime | None = None
        if command.work_view is not None and command.work_date is not None:
            work_start, work_end = _work_window(
                command.work_date,
                command.timezone or "UTC",
                recent=command.work_view is TaskWorkView.RECENTLY_UPDATED,
            )
        with _work_cursor_translated(), _translated():
            found = unit_of_work.tasks.search(
                authorization.principal.principal_id,
                command.query,
                page_size + 1,
                after=command.after,
                archive_mode=command.archive_mode,
                work_view=command.work_view,
                work_start=work_start,
                work_end=work_end,
                work_now=authorization.at,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        entries = [_task_list_entry(task).to_canonical_dict() for task in page]
        return _Result(
            payload={"tasks": entries},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_TASK_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].task_id if truncated and page else None,
                ),
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
        with _work_cursor_translated(), _translated():
            if command.after is None:
                found = unit_of_work.tasks.list_history(
                    principal_id, command.task_id, page_size + 1
                )
            else:
                found = unit_of_work.tasks.list_history(
                    principal_id, command.task_id, page_size + 1, after=command.after
                )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={"history": [_task_history_view(entry).to_canonical_dict() for entry in page]},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_TASK_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].history_id if truncated and page else None,
                ),
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
        _validate_task_commitment_state(
            unit_of_work, principal_id, command.commitment_id, command.role
        )
        from my_pa.application.tasks import TaskIdempotencyConflictError
        from my_pa.domain.task.history import TaskMutationActor

        try:
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
                    commitment_id=command.commitment_id,
                    role=command.role,
                    active_uow=unit_of_work,
                    validate_first_write=lambda: self._require_work_evidence(
                        unit_of_work, principal_id, command.origin_evidence_ref
                    ),
                )
        except TaskIdempotencyConflictError:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
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

        Builds one bounded patch and delegates once to
        `TaskManagementService.update_task`. Expected-version checking, digest-
        bound idempotency, Task replacement, and its single history receipt are
        atomic in the shared Work unit of work.
        """
        if self._tasks is None:
            raise InternalError()
        principal_id = authorization.principal.principal_id
        from my_pa.application.tasks import (
            TaskIdempotencyConflictError,
            TaskNotFoundError,
            TaskVersionConflictError,
        )
        from my_pa.domain.task.history import TaskMutationActor

        values: dict[str, object] = {}
        for field_name in (
            "title",
            "description",
            "priority",
            "due_at",
            "scheduled_at",
            "deferred_until",
            "commitment_id",
            "role",
        ):
            value = getattr(command, field_name)
            if value is not None:
                values[field_name] = value
        if command.archived is not None:
            values["archived_at"] = self._clock() if command.archived else None
        current = unit_of_work.tasks.get(principal_id, command.task_id)
        if current is None:
            raise NotFoundError(SafeDetail.TASK_ID)
        commitment_id, role = _task_commitment_state(
            current, values=values, clear_fields=frozenset(command.clear_fields)
        )
        _validate_task_commitment_state(unit_of_work, principal_id, commitment_id, role)
        try:
            with _translated():
                receipt = self._tasks.update_task(
                    principal_id=principal_id,
                    task_id=command.task_id,
                    expected_version=command.expected_version,
                    actor=TaskMutationActor.PRINCIPAL,
                    values=values,
                    clear_fields=frozenset(command.clear_fields),
                    idempotency_key=command.idempotency_key,
                    client_context=command.client_context,
                    active_uow=unit_of_work,
                )
        except TaskNotFoundError:
            raise NotFoundError(SafeDetail.TASK_ID) from None
        except TaskIdempotencyConflictError:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
        except TaskVersionConflictError as conflict:
            receipt = conflict.receipt
            current = unit_of_work.tasks.get(principal_id, command.task_id)
            if (
                receipt.history.outcome.value != "rejected"
                or receipt.history.before_version != receipt.history.after_version
                or current != receipt.task
                or current.version != receipt.history.before_version
            ):
                raise InternalError() from None
            raise _CommitRejectedConflictError(ConflictError(SafeDetail.TASK_ID)) from None

        return _Result(
            payload={
                "task": _task_view(receipt.task).to_canonical_dict(),
                "history": _task_history_view(receipt.history).to_canonical_dict(),
                "replayed": receipt.replayed,
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
            TaskIdempotencyConflictError,
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
                    active_uow=unit_of_work,
                    validate_first_write=(
                        None
                        if command.closure_evidence_ref is None
                        else lambda: self._require_work_evidence(
                            unit_of_work, principal_id, command.closure_evidence_ref or ""
                        )
                    ),
                )
        except IllegalTaskTransitionError as e:
            raise InvalidRequestError(SafeDetail.LIFECYCLE_STATE) from e
        except TaskNotFoundError:
            raise NotFoundError(SafeDetail.TASK_ID) from None
        except TaskVersionConflictError as conflict:
            receipt = conflict.receipt
            current = unit_of_work.tasks.get(principal_id, command.task_id)
            if (
                receipt.history.outcome.value != "rejected"
                or receipt.history.before_version != receipt.history.after_version
                or current != receipt.task
                or current.version != receipt.history.before_version
            ):
                raise InternalError() from None
            raise _CommitRejectedConflictError(ConflictError(SafeDetail.TASK_ID)) from None
        except TaskIdempotencyConflictError:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None

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
        """Validate and persist a content-free, fifteen-minute preview receipt."""
        principal_id = authorization.principal.principal_id
        mutations, digest = _normalise_bulk_mutations(command.mutations)
        prior = unit_of_work.tasks.find_bulk_by_preview_key(principal_id, command.idempotency_key)
        if prior is not None:
            if prior.request_digest != digest:
                raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
            return _Result(
                payload={
                    "bulk_operation_id": prior.bulk_operation_id,
                    "expires_at": prior.expires_at.isoformat(),
                    "affected": prior.preview_affected,
                    "no_op": prior.preview_no_op,
                    "rejected": 0,
                    "replayed": True,
                },
                disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
            )

        candidates: list[TaskManagementTask] = []
        for mutation in mutations:
            task = unit_of_work.tasks.get(principal_id, str(mutation["task_id"]))
            if task is None:
                raise NotFoundError(SafeDetail.TASK_ID)
            if task.version != cast(int, mutation["expected_version"]):
                raise ConflictError(SafeDetail.TASK_ID)
            values = cast(dict[str, object], mutation.get("values", {}))
            clear_fields = frozenset(cast(list[str], mutation.get("clear_fields", [])))
            commitment_id, role = _task_commitment_state(
                task, values=values, clear_fields=clear_fields
            )
            _validate_task_commitment_state(unit_of_work, principal_id, commitment_id, role)
            closure = mutation.get("closure_evidence_ref")
            if closure is not None:
                self._require_work_evidence(unit_of_work, principal_id, str(closure))
            candidates.append(_bulk_candidate(task, mutation, now=authorization.at))

        affected = sum(
            candidate.version > cast(int, mutation["expected_version"])
            for mutation, candidate in zip(mutations, candidates, strict=True)
        )
        operation = TaskBulkOperation(
            bulk_operation_id=issue_identifier(IdKind.BULK_OPERATION),
            principal_id=principal_id,
            preview_idempotency_key=command.idempotency_key,
            request_digest=digest,
            previewed_at=authorization.at,
            expires_at=authorization.at + timedelta(minutes=15),
            preview_affected=affected,
            preview_no_op=len(mutations) - affected,
        )
        try:
            unit_of_work.tasks.insert_bulk(operation)
        except BulkIdempotencyConflictError:
            # The outer UnitOfWork sees this exception and rolls back the
            # failed PostgreSQL transaction.  No query is attempted on the
            # aborted connection, and preview has made no Task writes.
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
        return _Result(
            payload={
                "bulk_operation_id": operation.bulk_operation_id,
                "expires_at": operation.expires_at.isoformat(),
                "affected": affected,
                "no_op": len(mutations) - affected,
                "rejected": 0,
                "replayed": False,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _tasks_bulk_confirm(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: BulkConfirmTasks
    ) -> _Result:
        """Apply an exact preview resubmission under the outer Work transaction."""
        principal_id = authorization.principal.principal_id
        mutations, digest = _normalise_bulk_mutations(command.mutations)
        prior_confirmation = unit_of_work.tasks.find_bulk_by_confirm_key(
            principal_id, command.idempotency_key
        )
        if prior_confirmation is not None:
            if (
                prior_confirmation.bulk_operation_id != command.bulk_operation_id
                or prior_confirmation.request_digest != digest
                or prior_confirmation.confirmed_at is None
            ):
                raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
            return _Result(
                payload={
                    "bulk_operation_id": prior_confirmation.bulk_operation_id,
                    "affected": prior_confirmation.affected,
                    "no_op": prior_confirmation.no_op,
                    "rejected": prior_confirmation.rejected,
                    "history_ids": list(prior_confirmation.history_ids),
                    "replayed": True,
                },
                disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
            )
        operation = unit_of_work.tasks.get_bulk_for_update(principal_id, command.bulk_operation_id)
        if operation is None:
            raise NotFoundError(SafeDetail.BULK_OPERATION_ID)
        if operation.request_digest != digest:
            raise ConflictError(SafeDetail.MUTATIONS)
        if operation.confirmed_at is not None:
            if operation.confirm_idempotency_key != command.idempotency_key:
                raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
            return _Result(
                payload={
                    "bulk_operation_id": operation.bulk_operation_id,
                    "affected": operation.affected,
                    "no_op": operation.no_op,
                    "rejected": operation.rejected,
                    "history_ids": list(operation.history_ids),
                    "replayed": True,
                },
                disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
            )
        if authorization.at >= operation.expires_at:
            raise ConflictError(SafeDetail.BULK_OPERATION_ID)

        by_id = {str(mutation["task_id"]): mutation for mutation in mutations}
        locked: dict[str, TaskManagementTask] = {}
        for task_id in sorted(by_id):
            task = unit_of_work.tasks.get_for_update(principal_id, task_id)
            if task is None:
                raise NotFoundError(SafeDetail.TASK_ID)
            mutation = by_id[task_id]
            if task.version != cast(int, mutation["expected_version"]):
                raise ConflictError(SafeDetail.TASK_ID)
            values = cast(dict[str, object], mutation.get("values", {}))
            clear_fields = frozenset(cast(list[str], mutation.get("clear_fields", [])))
            commitment_id, role = _task_commitment_state(
                task, values=values, clear_fields=clear_fields
            )
            _validate_task_commitment_state(unit_of_work, principal_id, commitment_id, role)
            closure = mutation.get("closure_evidence_ref")
            if closure is not None:
                self._require_work_evidence(unit_of_work, principal_id, str(closure))
            locked[task_id] = task

        history_ids: list[str] = []
        affected = 0
        no_op = 0
        for mutation in mutations:
            current = locked[str(mutation["task_id"])]
            candidate = _bulk_candidate(current, mutation, now=authorization.at)
            applied = candidate.version > current.version
            if applied:
                unit_of_work.tasks.update_task(candidate)
                affected += 1
            else:
                no_op += 1
            history = TaskManagementHistoryEntry(
                history_id=issue_identifier(IdKind.TASK_HISTORY),
                principal_id=principal_id,
                task_id=current.task_id,
                action=(
                    TaskMutationAction.UPDATE
                    if mutation["kind"] == "update"
                    else TaskMutationAction.TRANSITION_LIFECYCLE
                ),
                actor=TaskMutationActor.PRINCIPAL,
                outcome=(TaskMutationOutcome.APPLIED if applied else TaskMutationOutcome.NO_OP),
                before_version=current.version,
                after_version=candidate.version,
                occurred_at=authorization.at,
                recorded_at=self._clock(),
                request_digest=digest,
                bulk_operation_id=operation.bulk_operation_id,
            )
            unit_of_work.tasks.insert_history(history)
            history_ids.append(history.history_id)

        confirmed = replace(
            operation,
            confirmed_at=authorization.at,
            confirm_idempotency_key=command.idempotency_key,
            affected=affected,
            no_op=no_op,
            rejected=0,
            history_ids=tuple(history_ids),
        )
        try:
            unit_of_work.tasks.confirm_bulk(confirmed)
        except BulkIdempotencyConflictError:
            # Task/history changes above share this transaction.  The typed
            # conflict must escape the handler so the outer UnitOfWork rolls
            # all of them back with the losing unique-key claim.
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
        return _Result(
            payload={
                "bulk_operation_id": confirmed.bulk_operation_id,
                "affected": affected,
                "no_op": no_op,
                "rejected": 0,
                "history_ids": history_ids,
                "replayed": False,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _commitments_read(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReadCommitment
    ) -> _Result:
        principal_id = authorization.principal.principal_id
        with _translated():
            commitment = unit_of_work.commitments.get(principal_id, command.commitment_id)
        if commitment is None:
            raise NotFoundError(SafeDetail.COMMITMENT_ID)
        with _translated():
            public = _commitment_public_view(unit_of_work, principal_id, commitment)
            follow_up = unit_of_work.tasks.get_follow_up_for_commitment(
                principal_id, command.commitment_id
            )
            counterparty_options, counterparty_options_truncated = _counterparty_options(
                unit_of_work, principal_id
            )
        return _Result(
            payload={
                "commitment": public,
                "follow_up_task": (
                    None if follow_up is None else _task_list_entry(follow_up).to_canonical_dict()
                ),
                "counterparty_options": counterparty_options,
                "counterparty_options_truncated": counterparty_options_truncated,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_COMMITMENT_TRUST_BASIS),
        )

    def _commitments_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListCommitments
    ) -> _Result:
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        work_start: datetime | None = None
        work_end: datetime | None = None
        if command.work_view is not None and command.work_date is not None:
            work_start, work_end = _work_window(
                command.work_date,
                command.timezone or "UTC",
                recent=command.work_view is CommitmentWorkView.RECENTLY_UPDATED,
            )
        with _work_cursor_translated(), _translated():
            if command.after is None:
                found = unit_of_work.commitments.list_commitments(
                    principal_id,
                    direction=command.direction,
                    state=command.state,
                    work_view=command.work_view,
                    work_start=work_start,
                    work_end=work_end,
                    limit=page_size + 1,
                )
            else:
                found = unit_of_work.commitments.list_commitments(
                    principal_id,
                    direction=command.direction,
                    state=command.state,
                    work_view=command.work_view,
                    work_start=work_start,
                    work_end=work_end,
                    after=command.after,
                    limit=page_size + 1,
                )
        truncated = len(found) > page_size
        page = found[:page_size]
        with _translated():
            entries = [_commitment_public_list_entry(unit_of_work, principal_id, c) for c in page]
            counterparty_options, counterparty_options_truncated = _counterparty_options(
                unit_of_work, principal_id
            )
        return _Result(
            payload={
                "commitments": entries,
                "counterparty_options": counterparty_options,
                "counterparty_options_truncated": counterparty_options_truncated,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_COMMITMENT_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].commitment_id if truncated and page else None,
                ),
            ),
        )

    def _commitments_search(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SearchCommitments
    ) -> _Result:
        page_size = self._page_size(command.page_size)
        principal_id = authorization.principal.principal_id
        work_start: datetime | None = None
        work_end: datetime | None = None
        if command.work_view is not None and command.work_date is not None:
            work_start, work_end = _work_window(
                command.work_date,
                command.timezone or "UTC",
                recent=command.work_view is CommitmentWorkView.RECENTLY_UPDATED,
            )
        with _work_cursor_translated(), _translated():
            found = unit_of_work.commitments.search(
                principal_id,
                command.query,
                page_size + 1,
                after=command.after,
                direction=command.direction,
                state=command.state,
                work_view=command.work_view,
                work_start=work_start,
                work_end=work_end,
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        with _translated():
            entries = [
                _commitment_public_list_entry(unit_of_work, principal_id, item) for item in page
            ]
            counterparty_options, counterparty_options_truncated = _counterparty_options(
                unit_of_work, principal_id
            )
        return _Result(
            payload={
                "commitments": entries,
                "counterparty_options": counterparty_options,
                "counterparty_options_truncated": counterparty_options_truncated,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_COMMITMENT_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].commitment_id if truncated and page else None,
                ),
            ),
        )

    def _commitments_history(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetCommitmentHistory,
    ) -> _Result:
        principal_id = authorization.principal.principal_id
        with _translated():
            commitment = unit_of_work.commitments.get(principal_id, command.commitment_id)
        if commitment is None:
            raise NotFoundError(SafeDetail.COMMITMENT_ID)
        page_size = self._page_size(command.page_size)
        with _work_cursor_translated(), _translated():
            found = unit_of_work.commitments.list_history(
                principal_id, command.commitment_id, page_size + 1, after=command.after
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={
                "history": [_commitment_history_view(item).to_canonical_dict() for item in page]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_COMMITMENT_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].history_id if truncated and page else None,
                ),
            ),
        )

    def _commitments_waiting_on(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: WaitingOn
    ) -> _Result:
        from my_pa.domain.situation.continuity import (
            CommitmentDirection,
            CommitmentState,
            ContinuityEvidenceState,
        )

        principal_id = authorization.principal.principal_id
        page_size = self._page_size(command.page_size)
        with _work_cursor_translated(), _translated():
            commitments = unit_of_work.commitments.list_commitments(
                principal_id,
                direction=CommitmentDirection.OWED_TO_PRINCIPAL,
                state=CommitmentState.OPEN,
                evidence_state=ContinuityEvidenceState.ACCEPTED,
                after=command.after,
                limit=page_size + 1,
            )
        truncated = len(commitments) > page_size
        entries: list[dict[str, object]] = []
        for c in commitments[:page_size]:
            follow_up_task_id: str | None = None
            follow_up_task_title: str | None = None
            follow_up_task_state: str | None = None
            with _translated():
                follow_up = unit_of_work.tasks.get_follow_up_for_commitment(
                    principal_id, c.commitment_id
                )
            if follow_up is not None:
                follow_up_task_id = follow_up.task_id
                follow_up_task_title = follow_up.title
                follow_up_task_state = follow_up.lifecycle_state.value
            entry = WaitingOnEntry(
                commitment_id=c.commitment_id,
                title=c.summary,
                counterparty_person_id=c.counterparty_person_id,
                due_date=c.due_at.isoformat() if c.due_at is not None else None,
                state=c.state.value,
                follow_up_task_id=follow_up_task_id,
                follow_up_task_title=follow_up_task_title,
                follow_up_task_state=follow_up_task_state,
            ).to_canonical_dict()
            with _translated():
                entry["counterparty"] = _counterparty_projection(
                    unit_of_work, principal_id, c.counterparty_person_id
                )
            entries.append(entry)
        return _Result(
            payload={"waiting_on": entries},
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_COMMITMENT_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=(commitments[page_size - 1].commitment_id if truncated else None),
                ),
            ),
        )

    def _commitments_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateCommitment
    ) -> _Result:
        if self._commitments is None:
            raise InternalError()
        principal_id = authorization.principal.principal_id
        from my_pa.application.commitments import CommitmentIdempotencyConflictError
        from my_pa.domain.task.history import TaskMutationActor

        try:
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
                    active_uow=unit_of_work,
                    validate_first_write=lambda: self._require_commitment_create_eligibility(
                        unit_of_work,
                        principal_id,
                        evidence_ref=command.origin_evidence_ref,
                        counterparty_person_id=command.counterparty_person_id,
                    ),
                )
        except CommitmentIdempotencyConflictError:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
        with _translated():
            public = _commitment_public_view(unit_of_work, principal_id, receipt.commitment)
        return _Result(
            payload={
                "commitment": public,
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
            CommitmentIdempotencyConflictError,
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
                    active_uow=unit_of_work,
                    validate_first_write=lambda: self._require_work_evidence(
                        unit_of_work, principal_id, command.closure_evidence_ref
                    ),
                )
        except CommitmentNotFoundError:
            raise NotFoundError(SafeDetail.COMMITMENT_ID) from None
        except CommitmentVersionConflictError as conflict:
            receipt = conflict.receipt
            current = unit_of_work.commitments.get(principal_id, command.commitment_id)
            if (
                receipt.history.outcome.value != "rejected"
                or receipt.history.before_version != receipt.history.after_version
                or current != receipt.commitment
                or current.version != receipt.history.before_version
            ):
                raise InternalError() from None
            raise _CommitRejectedConflictError(ConflictError(SafeDetail.COMMITMENT_ID)) from None
        except CommitmentIdempotencyConflictError:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
        with _translated():
            public = _commitment_public_view(unit_of_work, principal_id, receipt.commitment)
        return _Result(
            payload={
                "commitment": public,
                "replayed": receipt.replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_COMMITMENT_TRUST_BASIS),
        )

    def _commitments_update(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: UpdateCommitment
    ) -> _Result:
        if self._commitments is None:
            raise InternalError()
        from my_pa.application.commitments import (
            CommitmentIdempotencyConflictError,
            CommitmentNotFoundError,
            CommitmentVersionConflictError,
        )
        from my_pa.domain.task.history import TaskMutationActor

        principal_id = authorization.principal.principal_id
        values: dict[str, object] = {}
        if command.summary is not None:
            values["summary"] = command.summary
        if command.due_at is not None:
            values["due_at"] = command.due_at
        if command.counterparty_person_id is not None:
            values["counterparty_person_id"] = command.counterparty_person_id
        try:
            with _translated():
                receipt = self._commitments.update_commitment(
                    principal_id=principal_id,
                    commitment_id=command.commitment_id,
                    expected_version=command.expected_version,
                    actor=TaskMutationActor.PRINCIPAL,
                    values=values,
                    clear_due_at=command.clear_due_at,
                    idempotency_key=command.idempotency_key,
                    client_context=command.client_context,
                    active_uow=unit_of_work,
                    validate_first_write=(
                        None
                        if command.counterparty_person_id is None
                        else lambda: self._require_current_counterparty(
                            unit_of_work, principal_id, command.counterparty_person_id or ""
                        )
                    ),
                )
        except CommitmentNotFoundError:
            raise NotFoundError(SafeDetail.COMMITMENT_ID) from None
        except CommitmentVersionConflictError as conflict:
            receipt = conflict.receipt
            current = unit_of_work.commitments.get(principal_id, command.commitment_id)
            if (
                receipt.history.outcome.value != "rejected"
                or receipt.history.before_version != receipt.history.after_version
                or current != receipt.commitment
                or current.version != receipt.history.before_version
            ):
                raise InternalError() from None
            raise _CommitRejectedConflictError(ConflictError(SafeDetail.COMMITMENT_ID)) from None
        except CommitmentIdempotencyConflictError:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
        with _translated():
            public = _commitment_public_view(unit_of_work, principal_id, receipt.commitment)
        return _Result(
            payload={
                "commitment": public,
                "history": _commitment_history_view(receipt.history).to_canonical_dict(),
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
            reenrichment_cause_id=(admission.event.event_id if admission.created else None),
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

    def _goodnotes_pull_plane(
        self, unit_of_work: UnitOfWork, authorization: Authorization
    ) -> tuple[GoodNotesPullRepository, AuthenticatedPullContext]:
        if not self._goodnotes_pull_enabled or authorization.authenticated_client_id is None:
            raise UnsupportedError()
        try:
            repository = cast(GoodNotesPullRepository, unit_of_work.goodnotes_pull)
        except NotImplementedError:
            raise UnsupportedError() from None
        key = self._goodnotes_pull_cursor_signing_key
        if key is None:
            raise UnsupportedError()
        principal_id = authorization.principal.principal_id
        client_id = authorization.authenticated_client_id
        context_id = hmac.new(
            key,
            b"goodnotes-pull-context-v1\0"
            + principal_id.encode("utf-8")
            + b"\0"
            + client_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        context = stamp_authenticated_pull_context(
            principal=authorization.principal,
            client_id=client_id,
            context_id=context_id,
        )
        return repository, context

    @staticmethod
    def _raise_goodnotes_pull(error: GoodNotesPullError) -> NoReturn:
        if error.code in {ERROR_INVALID_REQUEST, ERROR_INVALID_CURSOR}:
            raise InvalidRequestError() from None
        raise ConflictError() from None

    def _goodnotes_pull(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: PullGoodNotesWork,
    ) -> _Result:
        repository, context = self._goodnotes_pull_plane(unit_of_work, authorization)
        try:
            batch = GoodNotesPullOrchestrator(
                repository=repository,
                max_batch_size=MAX_PULL_BATCH_SIZE,
                max_attempts=MAX_PULL_RETRIES,
                cursor_signing_key=cast(bytes, self._goodnotes_pull_cursor_signing_key),
            ).discover(
                context,
                PullRequest(batch_size=command.batch_size, cursor=command.cursor),
            )
        except GoodNotesPullError as error:
            self._raise_goodnotes_pull(error)
        return _Result(
            payload=asdict(public_pull_batch(batch)),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _goodnotes_complete(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CompleteGoodNotesPull,
    ) -> _Result:
        repository, context = self._goodnotes_pull_plane(unit_of_work, authorization)
        principal_id = authorization.principal.principal_id
        client_id = cast(str, authorization.authenticated_client_id)
        completions: list[PullCompletion] = []
        try:
            for assignment_id in command.assignment_ids:
                material = repository.completion_material(principal_id, client_id, assignment_id)
                if material is None:
                    raise GoodNotesPullError("STALE_ASSIGNMENT")
                evidence = repository.semantic_review_evidence(
                    principal_id, material.run_id, (material.proposal_sha256,)
                )
                if (
                    len(evidence) != 1
                    or evidence[0].proposal_sha256 != material.proposal_sha256
                    or evidence[0].disposition
                    not in {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}
                    or (
                        evidence[0].disposition is Disposition.CORRECT_AND_ACCEPT
                        and evidence[0].result_sha256 != material.result_sha256
                    )
                ):
                    raise GoodNotesPullError("COMPLETION_CONFLICT")
                completions.append(
                    PullCompletion(
                        assignment_id=material.assignment_id,
                        run_id=material.run_id,
                        page_version_id=material.page_version_id,
                        content_sha256=material.content_sha256,
                        result_sha256=material.result_sha256,
                        idempotency_key=material.assignment_id,
                    )
                )
            receipts = GoodNotesPullOrchestrator(
                repository=repository,
                max_batch_size=MAX_PULL_BATCH_SIZE,
                max_attempts=MAX_PULL_RETRIES,
                cursor_signing_key=cast(bytes, self._goodnotes_pull_cursor_signing_key),
            ).complete(context, tuple(completions))
            if self._goodnotes_canonical_semantic_writes_enabled:
                store = cast(GoodNotesOccurrenceRepository, unit_of_work.goodnotes_durable_notes)
                for run_id in sorted({item.run_id for item in completions}):
                    if store.accepted_semantic_material(principal_id, run_id) is None:
                        continue
                    GoodNotesOccurrenceReconciler().reconcile(
                        principal_id, run_id, repository=store, clock=self._clock
                    )
        except GoodNotesPullError as error:
            self._raise_goodnotes_pull(error)
        except (ValueError, NotImplementedError, OccurrenceReconcileBusyError):
            raise ConflictError() from None
        return _Result(
            payload={
                "completions": [asdict(item) for item in public_completion_receipts(receipts)]
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _goodnotes_status(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetGoodNotesPullStatus,
    ) -> _Result:
        del command
        repository, _context = self._goodnotes_pull_plane(unit_of_work, authorization)
        status = repository.status(
            authorization.principal.principal_id,
            cast(str, authorization.authenticated_client_id),
        )
        return _Result(
            payload=asdict(status),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _gsqs_start(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: StartGsqsB0,
    ) -> _Result:
        """Start or reuse one synthetic B0 repetition. Real handwriting is denied."""
        del unit_of_work
        payload = start_workflow(
            workflow_root=workflow_root_from_env(),
            repository_root=default_repository_root(),
            authorization_id=command.authorization_id,
            campaign_class=command.campaign_class,
            repetition=command.repetition,
            idempotency_key=command.idempotency_key,
            python=sys.executable,
            ports=self._gsqs_b0_ports,
            wait=gsqs_b0_wait_in_process(self._gsqs_b0_ports),
        )
        return _Result(
            payload=payload,
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_TASK_TRUST_BASIS),
        )

    def _gsqs_status(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetGsqsB0Status,
    ) -> _Result:
        """Return durable B0 workflow status. No rasters, gold, or credentials."""
        del unit_of_work
        payload = status_workflow(
            workflow_root=workflow_root_from_env(),
            run_id=command.run_id,
        )
        return _Result(
            payload=payload,
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
        if capture_id is not None and admission.created:
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION,
                receipt.receipt_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.CAPTURE,
                        receipt.capture_id,
                        str(receipt.version_number),
                    ),
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.CAPTURE_VERSION,
                        receipt.version_id,
                        str(receipt.version_number),
                    ),
                ),
            )
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
            reenrichment_cause_id=(receipt.receipt_id if admission.created else None),
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

    def _intelligence_store(self, unit_of_work: UnitOfWork, authorization: Authorization) -> object:
        return unit_of_work.intelligence_for(authorization.principal.principal_id)

    def _reports_begin_cycle(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: BeginIntelligenceCycle,
    ) -> _Result:
        admission = begin_cycle(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            cycle_id=command.cycle_id,
            business_date=date.fromisoformat(command.business_date),
            idempotency_key=command.idempotency_key,
            at=authorization.at,
            automation_platform=command.automation_platform,
            external_orchestration_id=command.external_orchestration_id,
        )
        cycle = admission.cycle
        if cycle is None:
            raise InternalError()
        return _Result(
            payload={
                "receipt_id": admission.receipt.receipt_id,
                "cycle_run_id": cycle.cycle_run_id,
                "cycle_id": cycle.cycle_id,
                "business_date": cycle.business_date.isoformat(),
                "state": cycle.state.value,
                "created": admission.created,
                "replayed": admission.replayed,
                "created_at": format_rfc3339(cycle.created_at),
            },
            disclosure=unenrolled_disclosure(authorization.at),
        )

    def _reports_commit(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CommitIntelligenceArtifact,
    ) -> _Result:
        admission = commit_artifact(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            cycle_run_id=command.cycle_run_id,
            stage=command.stage,
            artifact_kind=command.artifact_kind,
            focus_area_id=command.focus_area_id,
            source_lane=command.source_lane,
            producer_task_id=command.producer_task_id,
            producer_task_name=command.producer_task_name,
            automation_platform=command.automation_platform,
            automation_run_id=command.automation_run_id,
            report_date=date.fromisoformat(command.report_date),
            title=command.title,
            body_markdown=command.body_markdown,
            artifact_state=command.artifact_state,
            schema_version=command.schema_version,
            idempotency_key=command.idempotency_key,
            at=authorization.at,
            coverage_start=command.coverage_start,
            coverage_end=command.coverage_end,
            producer_prompt_version=command.producer_prompt_version,
            structured_content=command.structured_content,
            dependency_report_ids=command.dependency_report_ids,
            provenance=command.provenance,
            supersedes_artifact_id=command.supersedes_artifact_id,
            advisory_digest=command.advisory_digest,
            completeness=command.completeness,
        )
        artifact = admission.artifact
        if artifact is None:
            raise InternalError()
        return _Result(
            payload={
                "receipt_id": admission.receipt.receipt_id,
                "report_id": artifact.artifact_id,
                "report_run_id": artifact.producer_run_id,
                "cycle_run_id": artifact.cycle_run_id,
                "focus_area_id": None
                if artifact.focus_area_id is None
                else artifact.focus_area_id.value,
                "stage": artifact.stage.value,
                "artifact_kind": artifact.artifact_kind.value,
                "source_lane": None if artifact.source_lane is None else artifact.source_lane.value,
                "report_date": artifact.report_date.isoformat(),
                "artifact_state": artifact.artifact_state.value,
                "content_sha256": artifact.content_sha256,
                "content_bytes": artifact.content_bytes,
                "committed_at": format_rfc3339(artifact.committed_at),
                "version": artifact.version,
                "supersedes_report_id": artifact.supersedes_artifact_id,
                "created": admission.created,
                "replayed": admission.replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at),
        )

    def _reports_record_run_state(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: RecordIntelligenceRunState,
    ) -> _Result:
        admission = record_run_state(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            cycle_run_id=command.cycle_run_id,
            stage=command.stage,
            artifact_kind=command.artifact_kind,
            focus_area_id=command.focus_area_id,
            source_lane=command.source_lane,
            producer_task_id=command.producer_task_id,
            producer_task_name=command.producer_task_name,
            automation_platform=command.automation_platform,
            automation_run_id=command.automation_run_id,
            report_date=date.fromisoformat(command.report_date),
            state=command.state,
            idempotency_key=command.idempotency_key,
            at=authorization.at,
            expected_version=command.expected_version,
            failure_code=command.failure_code,
            failure_summary=command.failure_summary,
        )
        run = admission.run
        if run is None:
            raise InternalError()
        return _Result(
            payload={
                "receipt_id": admission.receipt.receipt_id,
                "report_run_id": run.run_id,
                "cycle_run_id": run.cycle_run_id,
                "state": run.state.value,
                "version": run.version,
                "created": admission.created,
                "replayed": admission.replayed,
            },
            disclosure=unenrolled_disclosure(authorization.at),
        )

    def _reports_read(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ReadIntelligenceArtifact,
    ) -> _Result:
        artifact = read_artifact(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            artifact_id=command.report_id,
        )
        payload: dict[str, Any] = {
            "report_id": artifact.artifact_id,
            "report_run_id": artifact.producer_run_id,
            "cycle_run_id": artifact.cycle_run_id,
            "focus_area_id": None
            if artifact.focus_area_id is None
            else artifact.focus_area_id.value,
            "stage": artifact.stage.value,
            "artifact_kind": artifact.artifact_kind.value,
            "source_lane": None if artifact.source_lane is None else artifact.source_lane.value,
            "report_date": artifact.report_date.isoformat(),
            "title": artifact.title,
            "artifact_state": artifact.artifact_state.value,
            "content_sha256": artifact.content_sha256,
            "content_bytes": artifact.content_bytes,
            "committed_at": format_rfc3339(artifact.committed_at),
            "version": artifact.version,
            "supersedes_report_id": artifact.supersedes_artifact_id,
            "dependency_report_ids": [
                dependency.upstream_artifact_id for dependency in artifact.dependencies
            ],
            "provenance": [
                {
                    "source_system": ref.source_system,
                    "source_ref": ref.source_ref,
                    "relation": ref.relation.value,
                    "source_url": ref.source_url,
                }
                for ref in artifact.provenance
            ],
        }
        if command.include_body:
            payload["body_markdown"] = artifact.body_markdown
        if artifact.structured_content is not None:
            payload["structured_content"] = artifact.structured_content
        return _Result(payload=payload, disclosure=unenrolled_disclosure(authorization.at))

    def _reports_latest(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetLatestIntelligenceArtifact,
    ) -> _Result:
        artifact = latest_artifact(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            cycle_run_id=command.cycle_run_id,
            stage=command.stage,
            artifact_kind=command.artifact_kind,
            focus_area_id=command.focus_area_id,
            source_lane=command.source_lane,
            report_date=None
            if command.report_date is None
            else date.fromisoformat(command.report_date),
        )
        return _Result(
            payload={
                "report_id": artifact.artifact_id,
                "cycle_run_id": artifact.cycle_run_id,
                "stage": artifact.stage.value,
                "artifact_kind": artifact.artifact_kind.value,
                "focus_area_id": None
                if artifact.focus_area_id is None
                else artifact.focus_area_id.value,
                "source_lane": None if artifact.source_lane is None else artifact.source_lane.value,
                "content_sha256": artifact.content_sha256,
                "artifact_state": artifact.artifact_state.value,
            },
            disclosure=unenrolled_disclosure(authorization.at),
        )

    def _reports_list(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ListIntelligenceArtifacts,
    ) -> _Result:
        page_size = self._page_size(command.page_size)
        after_committed_at = None
        after_artifact_id = None
        if command.cursor is not None:
            try:
                cursor_artifact = read_artifact(
                    self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
                    principal_id=authorization.principal.principal_id,
                    artifact_id=command.cursor,
                )
            except NotFoundError:
                raise InvalidRequestError(SafeDetail.CURSOR) from None
            after_committed_at = cursor_artifact.committed_at
            after_artifact_id = cursor_artifact.artifact_id
        found = list_artifacts(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            cycle_run_id=command.cycle_run_id,
            stage=command.stage,
            artifact_kind=command.artifact_kind,
            focus_area_id=command.focus_area_id,
            source_lane=command.source_lane,
            report_date=None
            if command.report_date is None
            else date.fromisoformat(command.report_date),
            include_superseded=command.include_superseded,
            page_size=page_size + 1,
            after_committed_at=after_committed_at,
            after_artifact_id=after_artifact_id,
        )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={
                "items": [
                    {
                        "report_id": artifact.artifact_id,
                        "cycle_run_id": artifact.cycle_run_id,
                        "stage": artifact.stage.value,
                        "artifact_kind": artifact.artifact_kind.value,
                        "focus_area_id": None
                        if artifact.focus_area_id is None
                        else artifact.focus_area_id.value,
                        "source_lane": None
                        if artifact.source_lane is None
                        else artifact.source_lane.value,
                        "title": artifact.title,
                        "content_sha256": artifact.content_sha256,
                        "artifact_state": artifact.artifact_state.value,
                    }
                    for artifact in page
                ],
                "next_cursor": page[-1].artifact_id if truncated and page else None,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                    next_cursor=page[-1].artifact_id if truncated and page else None,
                ),
            ),
        )

    def _reports_search(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: SearchIntelligenceArtifacts,
    ) -> _Result:
        page_size = self._page_size(command.page_size)
        found = search_artifacts(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            query=command.query,
            cycle_run_id=command.cycle_run_id,
            stage=command.stage,
            artifact_kind=command.artifact_kind,
            focus_area_id=command.focus_area_id,
            source_lane=command.source_lane,
            page_size=page_size,
        )
        return _Result(
            payload={
                "items": [
                    {
                        "report_id": artifact.artifact_id,
                        "title": artifact.title,
                        "snippet": snippet,
                        "cycle_run_id": artifact.cycle_run_id,
                        "stage": artifact.stage.value,
                        "artifact_kind": artifact.artifact_kind.value,
                    }
                    for artifact, snippet in found
                ]
            },
            disclosure=unenrolled_disclosure(authorization.at),
        )

    def _reports_resolve_set(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ResolveIntelligenceSet,
    ) -> _Result:
        payload = resolve_set(
            self._intelligence_store(unit_of_work, authorization),  # type: ignore[arg-type]
            principal_id=authorization.principal.principal_id,
            cycle_run_id=command.cycle_run_id,
            set_id=command.set_id,
            focus_area_id=command.focus_area_id,
        )
        return _Result(payload=payload, disclosure=unenrolled_disclosure(authorization.at))

    # ---- WP-RI-B: producers and governed identity correction ----------------
    #
    # Six handlers, and every rule they enforce lives somewhere else. Which
    # payload fields a proposal kind admits, what a dedupe digest is over, what a
    # candidate memory's classification floor is, what identity correction blocks
    # on and what its effect ledger records are all `EntityGovernanceService`',
    # `RelationshipMemoryProposalService`'s and `IdentityCorrectionService`'s, so
    # a second copy here could not disagree with them.
    #
    # What this file supplies is the four things a caller may not: the Principal,
    # the clock, the correlation and audit references the authorization already
    # resolved, and -- for the two producer paths -- the proposal method. None of
    # the six commands has a field for any of them.

    #: Producer provenance is injected by composition and keyed by the exact
    #: authenticated Principal. Commands carry no origin fields. An unregistered
    #: producer is refused, and a local-model registration must name the exact
    #: model and version.
    def _proposal_origin(
        self, authorization: Authorization
    ) -> tuple[EntityProposalMethod, str, str | None, str | None]:
        """What the server will record as having produced an entity proposal.

        The only input is the server-created authorization. The immutable
        registry resolves its authenticated Principal; no command field can
        select or alter provenance.
        """
        try:
            origin = self._producer_origins.resolve(authorization.principal)
        except ProducerOriginError:
            raise DeniedError() from None
        return (
            EntityProposalMethod(origin.method),
            origin.method_version,
            origin.model_id,
            origin.model_version,
        )

    def _memory_proposal_origin(self, authorization: Authorization) -> MemoryProposalOrigin:
        """What the server will record as having produced a candidate memory.

        Uses the same immutable Principal registration as entity proposals.
        """
        try:
            origin = self._producer_origins.resolve(authorization.principal)
        except ProducerOriginError:
            raise DeniedError() from None
        return MemoryProposalOrigin(
            method=MemoryProposalMethod(origin.method),
            method_version=origin.method_version,
            model_id=origin.model_id,
            model_version=origin.model_version,
        )

    def _operator_authority(self, authorization: Authorization) -> bool:
        """Whether the acting context is the authenticated operator.

        **The one place a handler reads `is_operator`, and it decides nothing.**
        Whether an operator-only capability may run at all was decided by
        `domain.policy.decision.evaluate`, which denies every non-operator caller
        of a member of `_OPERATOR_ONLY` before a handler exists. What this reports
        is the authenticated fact, to services whose own rules are the decision:
        `IdentityCorrectionService` refuses without it and
        `EntityProposalReviewService` refuses an escalated case without it.

        Derived rather than passed as `True` at the merge call sites, and the
        difference is load-bearing rather than stylistic. A hard-coded `True`
        would be correct today and would silently stop being correct the moment
        `entities.merge` left `_OPERATOR_ONLY` -- which is exactly the mutation
        operator §30 requires a test to catch. Derived, the code fails closed
        under that mutation and the service's own refusal becomes reachable
        instead of dead.
        """
        return authorization.principal.is_operator

    def _identity_correction_plane(self) -> None:
        """Refuse when this build has not enabled governed identity correction.

        The same floor `_entity_writes` is, one switch narrower, and it exists for
        the same reason: `available_capabilities` withholds governed merge and
        split, and two readers consult it -- `capabilities.get` and the MCP tool
        list -- while the HTTP transport consults neither, routing by path segment
        straight into `_HANDLERS`.

        `_entity_writes()` first, so a build that turned this on without the
        gates below it refuses on the lowest one that is off rather than on this
        one. `Settings._check` refuses that configuration at startup, so the
        ordering here is what holds for a process composed some other way -- a
        test double, an embedded build -- rather than a second copy of a rule the
        settings already enforce.

        `unsupported` and not `denied`: a process without the switch has no
        governed identity correction, which is a fact about the build. Who may
        call it is the separate question `_OPERATOR_ONLY` answers, and a caller
        without operator authority is denied by policy before reaching here.
        """
        self._entity_writes()
        if not self._relationship_identity_correction_enabled:
            raise UnsupportedError()

    def _entities_proposals_create(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: CreateEntityProposal,
    ) -> _Result:
        """`entities.proposals.create`: ask for a change, and perform none.

        The producer's whole write surface on this plane. What comes back says
        what was recorded, what it will need before it can be accepted, and
        whether this request created it or found the same thing already open,
        plus the server-minted canonical review case and its initial version.

        **The receipt is the audit event, not a mutation ledger row.**
        `entities.proposals.create` writes no `entity_mutation_events` row and
        should not: `MutationRecordFamily` enumerates the canonical record classes
        this plane can mutate, and its own docstring is what a proposal is not --
        a proposal changes nothing, so a family for it would make the ledger a log
        of requests as well as of facts. Every capability already writes an
        `audit_events` row before its handler runs, and `authorization.audit_id`
        is that row. So the contract's audit/receipt field is `audit_id`, which is
        the same field every non-mutating capability answers with, and no enum
        gains a member that contradicts its own definition.
        """
        self._entity_writes()
        request_digest, replayed = _reserve_relationship_write(unit_of_work, authorization, command)
        if replayed is not None:
            if replayed.result_family != "entity_proposal":
                raise InternalError()
            return _Result(
                payload={
                    "proposal_id": replayed.result_id,
                    "proposal_version": replayed.result_version,
                    "kind": replayed.result_subtype,
                    "state": replayed.result_state,
                    "review_requirement": replayed.result_requirement,
                    "review_case_id": replayed.result_secondary_id,
                    "review_version": 0,
                    "dedupe_sha256": replayed.result_digest,
                    "evidence_refs": [
                        {
                            "role": link.role,
                            **(
                                {"entity_observation_id": link.entity_observation_id}
                                if link.entity_observation_id is not None
                                else {"capture_span_id": link.capture_span_id}
                                if link.capture_span_id is not None
                                else {"knowledge_id": link.knowledge_id}
                            ),
                        }
                        for link in replayed.evidence
                    ],
                    "proposed_at": format_rfc3339(cast("datetime", replayed.result_at)),
                    "created": replayed.result_created,
                    "audit_id": replayed.audit_id,
                },
                disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
            )
        method, method_version, model_id, model_version = self._proposal_origin(authorization)
        with _translated(), _entity_governance_translated():
            admission = EntityGovernanceService(unit_of_work.entities).propose(
                authorization.principal.principal_id,
                kind=command.kind,
                payload=cast("Mapping[str, str | bool]", command.payload),
                observation_ids=(),
                proposed_by=authorization.principal.principal_id,
                method=method,
                method_version=method_version,
                at=authorization.at,
                evidence=tuple(
                    EntityProposedEvidence(
                        role=EvidenceRole(entry["role"]),
                        entity_observation_id=entry.get("entity_observation_id"),
                        capture_span_id=entry.get("capture_span_id"),
                        knowledge_id=entry.get("knowledge_id"),
                    )
                    for entry in command.evidence
                ),
                expected_target_version=command.expected_target_version,
                model_id=model_id,
                model_version=model_version,
            )
            stored_evidence = unit_of_work.entities.proposal_evidence_links(
                authorization.principal.principal_id, admission.proposal_id
            )
        evidence_refs = [
            {
                "role": link.role.value,
                **(
                    {"entity_observation_id": link.entity_observation_id}
                    if link.entity_observation_id is not None
                    else {"capture_span_id": link.capture_span_id}
                    if link.capture_span_id is not None
                    else {"knowledge_id": cast(str, link.knowledge_id)}
                ),
            }
            for link in stored_evidence
        ]
        result = _Result(
            payload={
                "proposal_id": admission.proposal_id,
                "proposal_version": 1,
                "kind": admission.kind.value,
                "state": admission.state.value,
                "review_requirement": admission.requirement.value,
                "review_case_id": admission.review_case_id,
                "review_version": admission.review_version,
                "dedupe_sha256": admission.dedupe_sha256,
                "evidence_refs": evidence_refs,
                "proposed_at": format_rfc3339(admission.proposed_at),
                "created": admission.created,
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
        )
        if self._relationship_reenrichment_enabled and admission.created:
            register_producer_version_observation(
                unit_of_work.reenrichment,
                principal_id=authorization.principal.principal_id,
                proposal_id=admission.proposal_id,
                proposal_version=admission.state.value,
                method=method.value,
                method_version=method_version,
                model_id=model_id,
                model_version=model_version,
                policy_version=authorization.decision.policy_version,
                at=authorization.at,
            )
        _complete_relationship_write(
            unit_of_work,
            authorization,
            command,
            request_digest,
            WriteRequestResult(
                result_family="entity_proposal",
                result_id=admission.proposal_id,
                result_secondary_id=admission.review_case_id,
                result_version=1,
                result_state=admission.state.value,
                result_subtype=admission.kind.value,
                result_requirement=admission.requirement.value,
                result_at=admission.proposed_at,
                result_digest=admission.dedupe_sha256,
                result_created=admission.created,
                audit_id=authorization.audit_id,
                evidence=tuple(
                    WriteRequestEvidence(
                        sequence=link.sequence,
                        role=link.role.value,
                        entity_observation_id=link.entity_observation_id,
                        capture_span_id=link.capture_span_id,
                        knowledge_id=link.knowledge_id,
                    )
                    for link in stored_evidence
                ),
            ),
        )
        return result

    def _relationship_memory_propose(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: ProposeRelationshipMemory,
    ) -> _Result:
        """`relationship_memory.propose`: raise a candidate, and never a memory.

        The subject is read through the entity plane's own Principal-scoped port
        before anything else, which is what keeps a foreign subject
        indistinguishable from an absent one: a caller that cannot read the entity
        gets `None` and the same `not_found`, and never learns which of the two it
        was. `RelationshipMemoryProposalService` re-checks the subject's Principal
        as defence in depth; the scoped read is the first line.

        **The receipt carries no statement**, because `MemoryProposalReceipt` has
        no statement field. A `sensitivity` candidate floors at
        `restricted_local` and the read plane withholds restricted statements from
        search; handing the proposed words back through a producer's receipt would
        be a second channel for exactly the text the accepted form is withheld on.
        """
        self._relationship_memory_plane()
        request_digest, replayed = _reserve_relationship_write(unit_of_work, authorization, command)
        if replayed is not None:
            if replayed.result_family != "memory_proposal":
                raise InternalError()
            return _Result(
                payload={
                    "memory_proposal_id": replayed.result_id,
                    "review_case_id": replayed.result_secondary_id,
                    "subject_entity_id": command.entity_id,
                    "kind": replayed.result_subtype,
                    "state": replayed.result_state,
                    "classification": replayed.result_classification,
                    "method": replayed.result_method,
                    "proposed_at": format_rfc3339(cast("datetime", replayed.result_at)),
                    "evidence_count": replayed.result_count,
                    "dedupe_sha256": replayed.result_digest,
                    "created": replayed.result_created,
                    "audit_id": replayed.audit_id,
                },
                disclosure=unenrolled_disclosure(authorization.at, trust_basis=_MEMORY_TRUST_BASIS),
            )
        principal_id = authorization.principal.principal_id
        with _translated(), _memory_translated(), _entity_translated():
            subject = unit_of_work.entities.get(principal_id, command.entity_id)
            if subject is None:
                raise NotFoundError(SafeDetail.SUBJECT_ENTITY_ID)
            receipt = RelationshipMemoryProposalService().propose(
                unit_of_work.relationship_memory_proposals,
                ProposeMemoryCommand(
                    principal_id=principal_id,
                    subject_entity_id=command.entity_id,
                    expected_subject_version=command.expected_entity_version,
                    memory_kind=command.kind,
                    statement=command.statement,
                    structured_value=command.structured_value,
                    context_links=_memory_links(command.context_links),
                    evidence=tuple(
                        ProposedEvidence(
                            role=EvidenceLinkRole(entry["role"]),
                            entity_observation_id=entry.get("entity_observation_id"),
                            capture_span_id=entry.get("capture_span_id"),
                            knowledge_id=entry.get("knowledge_id"),
                        )
                        for entry in command.evidence
                    ),
                ),
                subject=subject,
                origin=self._memory_proposal_origin(authorization),
                at=authorization.at,
            )
        result = _Result(
            payload={
                "memory_proposal_id": receipt.memory_proposal_id,
                "review_case_id": receipt.review_case_id,
                "subject_entity_id": receipt.subject_entity_id,
                "kind": receipt.proposed_kind.value,
                "state": receipt.state.value,
                "classification": receipt.classification.value,
                "method": receipt.method.value,
                "proposed_at": format_rfc3339(receipt.proposed_at),
                "evidence_count": receipt.evidence_count,
                "dedupe_sha256": receipt.dedupe_sha256,
                "created": receipt.created,
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_MEMORY_TRUST_BASIS),
        )
        _complete_relationship_write(
            unit_of_work,
            authorization,
            command,
            request_digest,
            WriteRequestResult(
                result_family="memory_proposal",
                result_id=receipt.memory_proposal_id,
                result_secondary_id=receipt.review_case_id,
                result_state=receipt.state.value,
                result_subtype=receipt.proposed_kind.value,
                result_classification=receipt.classification.value,
                result_method=receipt.method.value,
                result_at=receipt.proposed_at,
                result_count=receipt.evidence_count,
                result_digest=receipt.dedupe_sha256,
                result_created=receipt.created,
                audit_id=authorization.audit_id,
            ),
        )
        return result

    def _entities_merge_preview(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: PreviewEntityMerge,
    ) -> _Result:
        """`entities.merge.preview`: what a merge would do, bound and stored.

        **No error translation.** `IdentityCorrectionService` raises
        `application.errors` types directly, with the `SafeDetail` decided where
        the failure is understood, which is `errors.py`'s own stated rule.
        Wrapping this call in a `_..._translated()` context manager would
        re-classify decisions that layer already made -- turning, for instance, a
        deliberate `PREVIEW_STALE` into whatever the wrapper maps a conflict to.
        The two producer handlers above wrap, because the services they call raise
        domain errors; this one does not, because the service it calls does not.
        """
        self._identity_correction_plane()
        report = IdentityCorrectionService(
            unit_of_work.entities, unit_of_work.relationship_memory
        ).preview(
            MergePreviewCommand(
                principal_id=authorization.principal.principal_id,
                survivor_entity_id=command.survivor_entity_id,
                expected_survivor_version=command.expected_survivor_version,
                merged_away=tuple(
                    (str(entry["entity_id"]), cast("int", entry["expected_version"]))
                    for entry in command.merged_away
                ),
                reason=command.reason,
                evidence_refs=command.evidence_refs,
            ),
            at=authorization.at,
            requested_by=authorization.principal.principal_id,
            actor_class=ActorClass.USER,
            has_operator_authority=self._operator_authority(authorization),
        )
        preview = report.preview
        return _Result(
            payload={
                "preview_id": preview.preview_id,
                "preview_token": preview.preview_digest,
                "conflict_digest": preview.conflict_digest,
                "plan_digest": preview.plan_digest,
                "expires_at": format_rfc3339(preview.expires_at),
                "affected_groups": [
                    {
                        "family": group.family.value,
                        "disposition": group.disposition.value,
                        "record_count": group.record_count,
                    }
                    for group in report.groups
                ],
                "blockers": [_identity_conflict_view(item) for item in report.blockers],
                "conflicts": [_identity_conflict_view(item) for item in report.conflicts],
                "required_choices": list(report.required_choices),
                "projected_effects": [
                    {
                        "family": draft.family.value,
                        "record_id": draft.record_id,
                        "kind": draft.kind.value,
                    }
                    for draft in report.projected_effects
                ],
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
        )

    def _entities_merge(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: MergeEntities,
    ) -> _Result:
        """`entities.merge`: perform the merge the preview described, or refuse.

        **The idempotency key is derived here and never sent.** Operator §23 keeps
        it out of a remote caller's hands and §26 makes it server-owned, and
        `REMOTE_OWNED_PAYLOAD_FIELDS` refuses one that arrives anyway -- but
        something still has to choose it. It is derived from the capability, the
        Principal and the preview, which is the operation's identity: a preview is
        consumable once, so one preview is one operation. An identical retry
        therefore produces the same key and replays; a materially different
        request against the same preview produces the same key and a different
        request digest, which is the conflict §23 asks for. Deriving it here
        rather than at the remote boundary is what makes that true on local MCP,
        remote MCP and HTTP alike instead of on one transport.

        **The preview token is not this key**, which §23 states as a rule: the
        digest says "the world is still what I was shown" and the key says "this
        is the request I already made". The key is over the preview *identifier*,
        which the caller cannot forge into another operation's -- a preview it
        does not own is refused as absent before the key is consulted.

        No error translation, for the reason `_entities_merge_preview` gives.
        """
        self._identity_correction_plane()
        principal_id = authorization.principal.principal_id
        receipt = IdentityCorrectionService(
            unit_of_work.entities, unit_of_work.relationship_memory
        ).apply(
            MergeCommand(
                principal_id=principal_id,
                preview_id=command.preview_id,
                preview_digest=command.preview_digest,
                idempotency_key=_merge_idempotency_key(principal_id, command.preview_id),
                reason=command.reason,
                evidence_refs=command.evidence_refs,
                choices=tuple(
                    sorted(
                        (str(entry["record_id"]), ConflictChoice(entry["choice"]))
                        for entry in command.choices
                    )
                ),
            ),
            at=authorization.at,
            correlation_id=authorization.correlation_id,
            audit_id=authorization.audit_id,
            performed_by=principal_id,
            actor_class=ActorClass.USER,
            has_operator_authority=self._operator_authority(authorization),
        )
        operation = receipt.operation
        if not receipt.replayed:
            if operation.effects_digest is None:  # pragma: no cover - completed operation invariant
                raise InternalError()
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.CORRECTED_IDENTITY,
                operation.identity_operation_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.IDENTITY_OPERATION,
                        operation.identity_operation_id,
                        operation.effects_digest,
                    ),
                ),
            )
        return _Result(
            payload={
                "identity_operation_id": operation.identity_operation_id,
                "state": operation.state.value,
                "survivor_entity_id": operation.survivor_entity_id,
                "merged_entity_ids": list(operation.merged_entity_ids),
                "preview_id": operation.preview_id,
                "completed_at": (
                    None
                    if operation.completed_at is None
                    else format_rfc3339(operation.completed_at)
                ),
                "replayed": receipt.replayed,
                "effects": [
                    {
                        "effect_id": effect.effect_id,
                        "sequence": effect.sequence,
                        "family": effect.family.value,
                        "record_id": effect.record_id,
                        "kind": effect.kind.value,
                    }
                    for effect in receipt.effects
                ],
                "receipt_id": operation.receipt_id,
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
            reenrichment_cause_id=(
                operation.identity_operation_id if not receipt.replayed else None
            ),
        )

    def _entities_identity_history(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: GetEntityIdentityHistory,
    ) -> _Result:
        """`entities.identity_history`: one bounded authoritative ledger page."""
        self._entity_plane()
        principal_id = authorization.principal.principal_id
        with _translated():
            entity = unit_of_work.entities.get(principal_id, command.entity_id)
        if entity is None:
            raise NotFoundError(SafeDetail.TARGET_ID)
        repository = cast("IdentityHistoryQuery", unit_of_work.identity_history)
        try:
            page = IdentityHistoryService().history(
                repository,
                principal_id=principal_id,
                entity_id=command.entity_id,
                page_size=command.page_size,
                after=command.after,
            )
        except IdentityHistoryCursorError:
            raise InvalidRequestError(SafeDetail.CURSOR) from None
        return _Result(
            payload={
                "entity_id": page.entity_id,
                "entries": [
                    {
                        "history_id": entry.history_id,
                        "occurred_at": format_rfc3339(entry.occurred_at),
                        "source": entry.source.value,
                        "operation": entry.operation.value,
                        "involved_entity_ids": list(entry.involved_entity_ids),
                        "changes": [
                            {
                                "family": change.family,
                                "record_id": change.record_id,
                                "effect_kind": change.effect_kind,
                                "before_state": change.before_state,
                                "after_state": change.after_state,
                            }
                            for change in entry.changes
                        ],
                        "actor_class": entry.actor_class,
                        "actor_id": entry.actor_id,
                        "authority": entry.authority,
                        "correlation_id": entry.correlation_id,
                        "audit_id": entry.audit_id,
                        "reason": entry.reason,
                        # Governed lineage. Both are opaque identifiers, and
                        # both are null on the sources that have no governed
                        # operation behind them.
                        "source_identity_operation_id": entry.source_identity_operation_id,
                        "receipt_id": entry.receipt_id,
                    }
                    for entry in page.entries
                ],
                "is_truncated": page.is_truncated,
                "next_cursor": page.next_cursor,
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
        )

    def _entities_split_preview(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: PreviewEntitySplit,
    ) -> _Result:
        """`entities.split.preview`: persist the exact inverse plan for one merge."""
        self._identity_correction_plane()
        report = IdentityCorrectionService(
            unit_of_work.entities, unit_of_work.relationship_memory
        ).split_preview(
            SplitPreviewCommand(
                principal_id=authorization.principal.principal_id,
                source_identity_operation_id=command.source_identity_operation_id,
                reason=command.reason,
                evidence_refs=command.evidence_refs,
            ),
            at=authorization.at,
            requested_by=authorization.principal.principal_id,
            actor_class=ActorClass.USER,
            has_operator_authority=self._operator_authority(authorization),
        )
        preview = report.preview
        return _Result(
            payload={
                "preview_id": preview.preview_id,
                "preview_token": preview.preview_digest,
                "plan_digest": preview.plan_digest,
                "source_identity_operation_id": report.source_operation.identity_operation_id,
                "expires_at": format_rfc3339(preview.expires_at),
                "projected_effects": [
                    {
                        "family": draft.family.value,
                        "record_id": draft.record_id,
                        "kind": draft.kind.value,
                    }
                    for draft in report.projected_effects
                ],
                # The questions this preview could not answer for itself, each
                # with the answers it admits. `entities.split` refuses until
                # every one of them carries exactly one; a record that is absent
                # from here is one the merge ledger proves, and it is restored
                # without an operator ever choosing anything about it.
                "ambiguities": [
                    {
                        "ambiguity_id": ambiguity.ambiguity_id,
                        "record_family": ambiguity.record_family.value,
                        "record_id": ambiguity.record_id,
                        "ambiguity_reason": ambiguity.reason,
                        "allowed_dispositions": list(ambiguity.allowed_dispositions),
                        "allowed_target_entity_ids": list(ambiguity.allowed_target_entity_ids),
                        "evidence_summary": dict(ambiguity.evidence_summary),
                    }
                    for ambiguity in report.ambiguities
                ],
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
        )

    def _entities_split(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: SplitEntity,
    ) -> _Result:
        """`entities.split`: consume one exact preview and append its inverse."""
        self._identity_correction_plane()
        principal_id = authorization.principal.principal_id
        receipt = IdentityCorrectionService(
            unit_of_work.entities, unit_of_work.relationship_memory
        ).split_apply(
            SplitCommand(
                principal_id=principal_id,
                preview_id=command.preview_id,
                preview_digest=command.preview_digest,
                idempotency_key=_split_idempotency_key(principal_id, command.preview_id),
                reason=command.reason,
                evidence_refs=command.evidence_refs,
                dispositions=tuple(
                    SplitDisposition(
                        ambiguity_id=str(entry["ambiguity_id"]),
                        disposition=AmbiguityDisposition(entry["disposition"]),
                        target_entity_id=(
                            None
                            if entry.get("target_entity_id") is None
                            else str(entry["target_entity_id"])
                        ),
                    )
                    for entry in command.dispositions
                ),
            ),
            at=authorization.at,
            correlation_id=authorization.correlation_id,
            audit_id=authorization.audit_id,
            performed_by=principal_id,
            actor_class=ActorClass.USER,
            has_operator_authority=self._operator_authority(authorization),
        )
        operation = receipt.operation
        if not receipt.replayed:
            if operation.effects_digest is None:  # pragma: no cover - completed operation invariant
                raise InternalError()
            self._register_reenrichment(
                unit_of_work,
                authorization,
                ReenrichmentTrigger.CORRECTED_IDENTITY,
                operation.identity_operation_id,
                (
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.IDENTITY_OPERATION,
                        operation.identity_operation_id,
                        operation.effects_digest,
                    ),
                ),
            )
        return _Result(
            payload={
                "identity_operation_id": operation.identity_operation_id,
                "state": operation.state.value,
                "source_identity_operation_id": operation.source_identity_operation_id,
                "survivor_entity_id": operation.survivor_entity_id,
                "restored_entity_ids": list(operation.merged_entity_ids),
                "preview_id": operation.preview_id,
                "completed_at": (
                    None
                    if operation.completed_at is None
                    else format_rfc3339(operation.completed_at)
                ),
                "replayed": receipt.replayed,
                "effects": [
                    {
                        "effect_id": effect.effect_id,
                        "sequence": effect.sequence,
                        "family": effect.family.value,
                        "record_id": effect.record_id,
                        "kind": effect.kind.value,
                    }
                    for effect in receipt.effects
                ],
                "receipt_id": operation.receipt_id,
                "audit_id": authorization.audit_id,
            },
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_ENTITY_TRUST_BASIS),
            reenrichment_cause_id=(
                operation.identity_operation_id if not receipt.replayed else None
            ),
        )


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
        Capability.CANVAS_WORKSPACE_GET: ApplicationService._canvas_workspace_get,
        Capability.CANVAS_WORKSPACE_PUT: ApplicationService._canvas_workspace_put,
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
        Capability.COMMITMENTS_SEARCH: ApplicationService._commitments_search,
        Capability.COMMITMENTS_HISTORY: ApplicationService._commitments_history,
        Capability.COMMITMENTS_WAITING_ON: ApplicationService._commitments_waiting_on,
        Capability.COMMITMENTS_CREATE: ApplicationService._commitments_create,
        Capability.COMMITMENTS_UPDATE: ApplicationService._commitments_update,
        Capability.COMMITMENTS_CLOSE: ApplicationService._commitments_close,
        Capability.CONTEXT_PREPARE: ApplicationService._context_prepare,
        Capability.CONTEXT_FEEDBACK: ApplicationService._context_feedback,
        Capability.GOODNOTES_WORK: ApplicationService._goodnotes_work,
        Capability.GOODNOTES_CONTENT: ApplicationService._goodnotes_content,
        Capability.GOODNOTES_PROPOSE: ApplicationService._goodnotes_propose,
        Capability.GOODNOTES_PULL: ApplicationService._goodnotes_pull,
        Capability.GOODNOTES_COMPLETE: ApplicationService._goodnotes_complete,
        Capability.GOODNOTES_STATUS: ApplicationService._goodnotes_status,
        Capability.GSQS_START: ApplicationService._gsqs_start,
        Capability.GSQS_STATUS: ApplicationService._gsqs_status,
        Capability.REPORTS_BEGIN_CYCLE: ApplicationService._reports_begin_cycle,
        Capability.REPORTS_COMMIT: ApplicationService._reports_commit,
        Capability.REPORTS_RECORD_RUN_STATE: ApplicationService._reports_record_run_state,
        Capability.REPORTS_READ: ApplicationService._reports_read,
        Capability.REPORTS_LATEST: ApplicationService._reports_latest,
        Capability.REPORTS_LIST: ApplicationService._reports_list,
        Capability.REPORTS_SEARCH: ApplicationService._reports_search,
        Capability.REPORTS_RESOLVE_SET: ApplicationService._reports_resolve_set,
        Capability.ENTITIES_SEARCH: ApplicationService._entities_search,
        Capability.ENTITIES_GET: ApplicationService._entities_get,
        Capability.ENTITIES_RESOLVE: ApplicationService._entities_resolve,
        Capability.ENTITIES_CONTEXT: ApplicationService._entities_context,
        Capability.ENTITIES_RELATIONSHIPS: ApplicationService._entities_relationships,
        Capability.ENTITIES_GRAPH: ApplicationService._entities_graph,
        Capability.ENTITIES_UNRESOLVED_MENTIONS: (ApplicationService._entities_unresolved_mentions),
        Capability.ENTITIES_IDENTIFIERS_LIST: ApplicationService._entities_identifiers_list,
        Capability.ENTITIES_ALIASES_LIST: ApplicationService._entities_aliases_list,
        Capability.ENTITIES_PROFILE: ApplicationService._entities_profile,
        Capability.ENTITIES_NAMES_LIST: ApplicationService._entities_names_list,
        Capability.ENTITIES_ADDRESSES_LIST: ApplicationService._entities_addresses_list,
        Capability.ENTITIES_COMMUNICATION_LIST: ApplicationService._entities_communication_list,
        Capability.ENTITIES_PARTICIPATIONS_LIST: (ApplicationService._entities_participations_list),
        Capability.ENTITIES_NAMES_ADD: ApplicationService._entities_names_add,
        Capability.ENTITIES_NAMES_SUPERSEDE: ApplicationService._entities_names_supersede,
        Capability.ENTITIES_NAMES_RETIRE: ApplicationService._entities_names_retire,
        Capability.ENTITIES_ADDRESSES_ADD: ApplicationService._entities_addresses_add,
        Capability.ENTITIES_ADDRESSES_REVISE: ApplicationService._entities_addresses_revise,
        Capability.ENTITIES_ADDRESSES_RETIRE: ApplicationService._entities_addresses_retire,
        Capability.ENTITIES_COMMUNICATION_ADD: ApplicationService._entities_communication_add,
        Capability.ENTITIES_COMMUNICATION_REVISE: ApplicationService._entities_communication_revise,
        Capability.ENTITIES_COMMUNICATION_RETIRE: ApplicationService._entities_communication_retire,
        Capability.ENTITIES_PARTICIPATIONS_CREATE: (
            ApplicationService._entities_participations_create
        ),
        Capability.ENTITIES_PARTICIPATIONS_REVISE: (
            ApplicationService._entities_participations_revise
        ),
        Capability.ENTITIES_PARTICIPATIONS_END: ApplicationService._entities_participations_end,
        Capability.ENTITIES_AFFILIATIONS_CREATE: (ApplicationService._entities_affiliations_create),
        Capability.ENTITIES_AFFILIATIONS_REVISE: (ApplicationService._entities_affiliations_revise),
        Capability.ENTITIES_AFFILIATIONS_END: ApplicationService._entities_affiliations_end,
        Capability.ENTITIES_CREATE: ApplicationService._entities_create,
        Capability.ENTITIES_UPDATE: ApplicationService._entities_update,
        Capability.ENTITIES_ARCHIVE: ApplicationService._entities_archive,
        Capability.ENTITIES_RESTORE: ApplicationService._entities_restore,
        Capability.ENTITIES_IDENTIFIERS_BIND: ApplicationService._entities_identifiers_bind,
        Capability.ENTITIES_IDENTIFIERS_RETIRE: ApplicationService._entities_identifiers_retire,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE: (
            ApplicationService._entities_identifiers_supersede
        ),
        Capability.ENTITIES_ALIASES_ADD: ApplicationService._entities_aliases_add,
        Capability.ENTITIES_ALIASES_RETIRE: ApplicationService._entities_aliases_retire,
        Capability.ENTITIES_ALIASES_SUPERSEDE: ApplicationService._entities_aliases_supersede,
        Capability.ENTITIES_ASSIGNMENTS_LIST: ApplicationService._entities_assignments_list,
        Capability.ENTITIES_ASSIGNMENTS_CREATE: ApplicationService._entities_assignments_create,
        Capability.ENTITIES_ASSIGNMENTS_REVISE: ApplicationService._entities_assignments_revise,
        Capability.ENTITIES_ASSIGNMENTS_END: ApplicationService._entities_assignments_end,
        Capability.ENTITIES_RELATIONSHIPS_CREATE: (
            ApplicationService._entities_relationships_create
        ),
        Capability.ENTITIES_RELATIONSHIPS_REVISE: (
            ApplicationService._entities_relationships_revise
        ),
        Capability.ENTITIES_RELATIONSHIPS_END: ApplicationService._entities_relationships_end,
        Capability.ENTITIES_OBSERVATIONS_LIST: ApplicationService._entities_observations_list,
        Capability.ENTITIES_OBSERVE: ApplicationService._entities_observe,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE: (
            ApplicationService._entities_unresolved_mentions_resolve
        ),
        Capability.ENTITIES_PROPOSALS_CREATE: ApplicationService._entities_proposals_create,
        Capability.ENTITIES_MERGE_PREVIEW: ApplicationService._entities_merge_preview,
        Capability.ENTITIES_MERGE: ApplicationService._entities_merge,
        Capability.ENTITIES_IDENTITY_HISTORY: ApplicationService._entities_identity_history,
        Capability.ENTITIES_SPLIT_PREVIEW: ApplicationService._entities_split_preview,
        Capability.ENTITIES_SPLIT: ApplicationService._entities_split,
        Capability.RELATIONSHIP_MEMORY_CREATE: ApplicationService._relationship_memory_create,
        Capability.RELATIONSHIP_MEMORY_GET: ApplicationService._relationship_memory_get,
        Capability.RELATIONSHIP_MEMORY_LIST: ApplicationService._relationship_memory_list,
        Capability.RELATIONSHIP_MEMORY_SEARCH: ApplicationService._relationship_memory_search,
        Capability.RELATIONSHIP_MEMORY_HISTORY: ApplicationService._relationship_memory_history,
        Capability.RELATIONSHIP_MEMORY_REVISE: ApplicationService._relationship_memory_revise,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE: ApplicationService._relationship_memory_archive,
        Capability.RELATIONSHIP_MEMORY_RESTORE: ApplicationService._relationship_memory_restore,
        Capability.RELATIONSHIP_MEMORY_PROPOSE: ApplicationService._relationship_memory_propose,
    }
)

_GOODNOTES_PULL_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.GOODNOTES_PULL,
        Capability.GOODNOTES_COMPLETE,
        Capability.GOODNOTES_STATUS,
    }
)


def published_capabilities(
    service: ApplicationService, *, authenticated_client_present: bool
) -> frozenset[Capability]:
    """Return runtime publication after the server-owned client-context gate."""
    served = service.available_capabilities
    if not authenticated_client_present:
        served -= _GOODNOTES_PULL_CAPABILITIES
    return served


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
        Capability.ENTITIES_IDENTIFIERS_LIST,
        Capability.ENTITIES_ALIASES_LIST,
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ASSIGNMENTS_LIST,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_OBSERVATIONS_LIST,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_IDENTITY_HISTORY,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
        # `RI-ENT-WP-10`'s five reads. Here and deliberately not in
        # `_ENTITY_WRITE_CAPABILITIES`: they read the six record families and
        # write none of them, so the write switch narrows nothing about them
        # and the plane switch withholds them like every other `entities.` name.
        Capability.ENTITIES_PROFILE,
        Capability.ENTITIES_NAMES_LIST,
        Capability.ENTITIES_ADDRESSES_LIST,
        Capability.ENTITIES_COMMUNICATION_LIST,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        Capability.ENTITIES_GRAPH,
        # `RI-ENT-WP-11`'s record-family writes. Here *and* in
        # `_ENTITY_WRITE_CAPABILITIES` below: turning the plane off withholds
        # them like every other `entities.` name, and the write switch narrows
        # the already-composed plane a second time.
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_COMMUNICATION_ADD,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
        Capability.ENTITIES_PARTICIPATIONS_CREATE,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_AFFILIATIONS_CREATE,
        Capability.ENTITIES_AFFILIATIONS_REVISE,
        Capability.ENTITIES_AFFILIATIONS_END,
    }
)

#: The write half of the `entities.` plane, withheld from a process that has
#: not set `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED`. A subset of
#: `_ENTITY_CAPABILITIES` rather than a separate family: turning the plane off
#: withholds these too, and the write switch narrows an already-composed plane.
#:
#: Written out rather than derived from the purpose map, for the reason
#: `_ENTITY_CAPABILITIES` is written out: admitting another write is a decision
#: made here, not a spelling that happens to carry a write purpose. The
#: derivation is still made, in
#: `tests/contract/test_entity_write_gate.py`, which compares this set against
#: the capabilities whose permitted purposes are write purposes -- so the two
#: cannot disagree, and neither one is the only statement of the fact.
_ENTITY_WRITE_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        # Phase B added the proposal write and merge preview/apply; final identity
        # recovery added split preview/apply. The producer inserts a proposal row,
        # both previews insert control rows, and merge/split rewrite canonical rows
        # -- so a build with the plane on and writes off serves none of the five,
        # which `test_entity_write_gate` derives from the purpose map and compares
        # against this set.
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
        # `RI-ENT-WP-11`. Each inserts, supersedes or retires a row in one of
        # the five Entity-bound record families and appends the mutation-ledger
        # row that accounts for it, so a build with the plane on and writes off
        # serves none of them -- which `test_entity_write_gate` derives from the
        # purpose map rather than reading off this set.
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_COMMUNICATION_ADD,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
        Capability.ENTITIES_PARTICIPATIONS_CREATE,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_AFFILIATIONS_CREATE,
        Capability.ENTITIES_AFFILIATIONS_REVISE,
        Capability.ENTITIES_AFFILIATIONS_END,
    }
)

#: Governed identity correction, withheld from a process that has not set
#: `MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED`. A subset of
#: `_ENTITY_WRITE_CAPABILITIES` and therefore of `_ENTITY_CAPABILITIES`: this is
#: a third narrowing of an already-narrowed plane, not a family of its own.
#:
#: Four rather than two. Merge and split each publish their preview beside apply:
#: the operator boundary covers inspecting the exact identities and inverse plan
#: as well as performing either transition, so a build cannot expose an inspection
#: while withholding only its corresponding act.
_IDENTITY_CORRECTION_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    }
)

_PRODUCER_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
    }
)

#: The Relationship Memory plane's names, withheld from a process that has not
#: enabled it. Written out rather than derived from the `relationship_memory.`
#: prefix, for the reason `_MANAGED_CAPABILITIES` and `_ENTITY_CAPABILITIES` are:
#: admitting another is a decision here and not a spelling that happens to start
#: the right way.
_RELATIONSHIP_MEMORY_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        # The producer path is composed on exactly the same conjunction as the
        # other eight, and on no further switch. It writes, so the question was
        # whether
        # to gate it behind `relationship_intelligence_writes_enabled` as well;
        # the answer is no, because `relationship_memory.create` -- which writes
        # an *accepted* memory -- is not gated on it either, and gating the
        # weaker act more tightly than the stronger one would be a rule nobody
        # could explain to an operator.
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
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
