"""The ports the forty-five capability use cases call, and nothing else.

`docs/architecture/module-boundaries.md` section 5.2 puts application ports here
and section 5.3 gives the application the transaction boundary. `AGENTS.md`
section 2 forbids speculative abstraction. Both are satisfied the same way:
every method below is called by a use case that exists today, and no method
exists because a use case might want one later. There is no registry, no
factory, no generic repository, and no extension point. A port with one
implementation and one caller is the point; a port with a method nobody calls
would be the defect.

**What is deliberately not repeated here.** `domain.source.provider.SourceProvider`
already is the read-only source port and is used as it stands. `SourceProviders`
below is not a second one and not a plugin framework: it is the lookup from an
opaque `src_…` to the adapter already constructed for it, which a use case needs
because a capability names a source by identifier and the composition root is
the only thing that may choose an implementation.

**Why the repositories are separate objects rather than one.** They are the four
nouns the capabilities act on — a configured source, an enrollment, a unit of
work in the job plane, and a knowledge record — and each is reached through the
unit of work that owns the transaction they run in. Splitting them is what keeps
each interface small enough to read; merging them would produce the generic
repository this package is required not to have.

**The unit of work is how a use case gets a transaction.** The persistence layer
this wraps is free functions over a `Connection` with the caller owning the
transaction, so something has to own it, and section 5.3 says that something is
the application. `UnitOfWork` is a context manager: leaving the block normally
commits, leaving it by exception rolls back. A use case therefore cannot half
commit an enrollment and its queued work, because it never sees the connection
that would let it.

**Nothing here carries a physical locator.** Every value crossing these
interfaces is an opaque identifier, a closed enum, a bounded count, or a domain
value that has already refused to hold a path. `KnowledgeRecord` carries
extracted text because `knowledge.read` returns it; it is the one value here
that holds source content, and it is bounded by the caller before it is built.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from types import TracebackType

from my_pa.contracts.v1.disclosure import Disclosure
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.capture.proposal import MAX_NORMALIZED_VALUE_CHARACTERS
from my_pa.domain.capture.reveal import Reveal
from my_pa.domain.capture.review import Disposition, ReviewCase, ReviewDecision
from my_pa.domain.capture.submission import CaptureKind, CaptureReceipt, CaptureTransport
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import Provenance
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.context.preference import (
    ContextPreferenceAdmission,
    ContextPreferenceCurrent,
)
from my_pa.domain.context.run import ContextRunRecord
from my_pa.domain.documents.managed import (
    DocumentState,
    LifecycleTransition,
    ManagedDocument,
    ManagedDocumentReceipt,
    ManagedDocumentVersion,
    validate_managed_media_type,
    validate_managed_title,
)
from my_pa.domain.extraction.corpus import CorpusCoverage
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.goodnotes.models import GoodNotesReviewCase
from my_pa.domain.policy.decision import validate_policy_version
from my_pa.domain.relationship.event import RelationshipEvent, RelationshipEventType
from my_pa.domain.relationship.identity import (
    IdentityCandidateSet,
    IdentityObservation,
    IdentityResolution,
    ResolutionAction,
    UnresolvedMention,
)
from my_pa.domain.relationship.profile import OrganizationProfile, PersonProfile
from my_pa.domain.search.query import SearchMatch, SearchQuery, SearchRequest
from my_pa.domain.situation.continuity import (
    ClosureEvidenceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
    ContinuityLifecycleEvent,
    ContinuityObjectKind,
    Decision,
    Task,
)
from my_pa.domain.situation.situation import (
    Frame,
    Project,
    ProjectState,
    PulseItem,
    Situation,
    SituationState,
    Trace,
)
from my_pa.domain.source.enrollment import Enrollment, EnrollmentRequest
from my_pa.domain.source.provider import SourceProvider
from my_pa.domain.source.registry import ConfiguredSource
from my_pa.domain.task.commitment import Commitment as CommitmentAggregate
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry
from my_pa.domain.task.history import TaskHistoryEntry
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskPriority
from my_pa.domain.task.task import Task as TaskAggregate

__all__ = [
    "Acceptance",
    "AuditSink",
    "AuthoringConflictError",
    "AuthoringReceipt",
    "CaptureAdmission",
    "CaptureAdmissionRequest",
    "CaptureRepository",
    "CaptureSearchMatch",
    "CaptureSearchOutcome",
    "CaptureSearchRequest",
    "CaptureSummary",
    "CommitmentManagementRepository",
    "CommitmentManagementUnitOfWork",
    "ContextPreferenceRepository",
    "ContextRunRepository",
    "ContinuityAuthoringRepository",
    "ContinuityReadRepository",
    "ContinuityRepository",
    "EnrollmentRepository",
    "EvidenceUnavailableError",
    "FrameRepository",
    "KnowledgeRecord",
    "KnowledgeRepository",
    "ManagedAdmission",
    "ManagedByteStore",
    "ManagedDocumentRepository",
    "ManagedWriteRequest",
    "Operation",
    "OperationQueue",
    "PortError",
    "ProjectRepository",
    "PulseRepository",
    "RelationshipEventRepository",
    "RelationshipRepository",
    "RepositoryFailureError",
    "ReviewDecisionRequest",
    "ReviewRepository",
    "SearchOutcome",
    "SituationRepository",
    "SourceProviders",
    "SourceRepository",
    "TaskManagementRepository",
    "TaskManagementUnitOfWork",
    "TraceRepository",
    "UnitOfWork",
    "UnknownScopeError",
    "WorkerHealthRepository",
    "WorkerPlaneStatus",
]


class RelationshipRepository(ABC):
    """The governed identity writer and deterministic profile reader.

    There is intentionally no `create_person`, `link_observation`, or `merge`
    method. Canonical state enters only through `apply_resolution`, with the
    exact accepted identity-review decision carried in the resolution value.
    """

    @abstractmethod
    def record_observations(
        self, domain: str, observations: tuple[IdentityObservation, ...]
    ) -> int:
        """Idempotently retain source rows as observations, never people."""

    @abstractmethod
    def open_identity_review(
        self,
        candidates: IdentityCandidateSet,
        action: ResolutionAction,
        *,
        retained_person_id: str | None = None,
        prior_person_id: str | None = None,
    ) -> str:
        """Open one review over an explicit candidate set."""

    @abstractmethod
    def decide_identity_review(
        self,
        review_case_id: str,
        *,
        disposition: str,
        principal_id: str,
        decided_at: datetime,
    ) -> str:
        """Append an accept, reject, or defer decision."""

    @abstractmethod
    def apply_resolution(self, resolution: IdentityResolution, *, display_name: str) -> None:
        """Apply only the exact accepted review, preserving reversible lineage."""

    @abstractmethod
    def direct_merge(self, retained_person_id: str, prior_person_id: str) -> None:
        """Always deny before persistence; present to make the denial test non-vacuous."""

    @abstractmethod
    def profile(self, person_id: str, *, expected_domains: tuple[str, ...]) -> PersonProfile | None:
        """Build a cited profile and timeline over its exact observation set."""

    @abstractmethod
    def organization_profile(self, organization_id: str) -> OrganizationProfile | None:
        """Read time-aware affiliations and their exact observations."""

    @abstractmethod
    def record_source_affiliation(
        self,
        *,
        organization_id: str,
        organization_name: str,
        affiliation_id: str,
        person_id: str,
        observation_id: str,
        role: str | None,
        effective_from: datetime | None,
        effective_to: datetime | None,
    ) -> None:
        """Create organization context only from a governed, linked observation."""

    @abstractmethod
    def record_unresolved_mention(self, mention: UnresolvedMention) -> None:
        """Retain one source-bound unresolved identity without raw mention text."""

    @abstractmethod
    def attach_conversation_participant(
        self,
        conversation_id: str,
        *,
        person_id: str | None = None,
        unresolved_mention_id: str | None = None,
        observation_ids: tuple[str, ...] = (),
    ) -> str:
        """Attach exactly one resolved or unresolved target and exact support."""


class PortError(Exception):
    """A failure an implementation of one of these ports may report.

    These exist because the boundary has to be closed in both directions. A use
    case may not import `infrastructure`, so it cannot catch a SQLAlchemy error,
    an `IsolationLevelError`, or `persistence.search`'s private classes; and an
    adapter may not import `application`, so it cannot raise the public error
    directly. The vocabulary therefore belongs here, where both sides can see
    it, and an adapter's job includes translating into it.

    Each carries nothing. The values that would be worth carrying — a statement,
    a bound parameter, a driver message — are exactly the ones `docs/specs`
    section 10 excludes from a public error, and the classification is the only
    thing the caller can act on.
    """


class UnknownScopeError(PortError):
    """The scope a request names does not exist.

    Distinct from "the search found nothing", which is an answer rather than a
    failure. Section 10 puts this under `not_found`.
    """


class EvidenceUnavailableError(PortError):
    """The backing store could not be read. Conditionally retryable."""


class RepositoryFailureError(PortError):
    """The read failed for a reason that is this system's fault.

    Separated from unavailability because telling a caller to retry a missing
    column would be a lie with a retry budget attached.
    """


@dataclass(frozen=True, slots=True)
class Acceptance:
    """An accepted enrollment, and whether this call is what created it.

    `created` false means the idempotency key was already bound to this exact
    normalized request, so the correct answer is the one the first call got.
    A caller that audits acceptance separately from retry needs to tell them
    apart; one that does not may ignore it.
    """

    enrollment: Enrollment
    created: bool


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    """One stored extraction and the source state it is bound to.

    The provenance is mandatory rather than optional because `docs/specs`
    section 9.8 makes the source, object, and version bindings mandatory: a
    record returned without them would be derived text with no way back to the
    bytes it came from.
    """

    knowledge_id: str
    enrollment_id: str
    media_type: str | None
    text: str
    is_truncated: bool
    provenance: Provenance

    def __post_init__(self) -> None:
        validate_identifier(self.knowledge_id, IdKind.KNOWLEDGE)
        validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """One page of matches and the disclosure that must accompany it.

    The two travel together because section 8.3 makes the envelope mandatory: a
    caller able to hold the matches without the coverage could report "nothing
    found" for a scope that was never indexed.
    """

    matches: tuple[SearchMatch, ...]
    disclosure: Disclosure


@dataclass(frozen=True, slots=True)
class CaptureAdmissionRequest:
    """Everything one admission needs, decided before the transaction opens.

    `capture_id` is `None` for `capture.create` and names an existing capture for
    `capture.revise`, which is the whole difference between the two: one starts a
    chain and the other appends to it.

    **Three of the five timestamps are supplied here and two are not.**
    `server_received_at` is when this process received the request,
    `accepted_at` is when the admission decided, and the store writes
    `recorded_at` from the server's own clock — three different clocks reading at
    three different moments, so the criterion that they stay distinct is a
    property of where they come from rather than of a caller remembering to pass
    three values. `client_created_at` and `occurred_at` are the caller's, and
    both are optional: a transport may supply no device clock and a note may be
    about no particular moment. Neither is defaulted from anything.

    `audit_id` names the audit event that has *already committed*, on the audit
    sink's own connection (`D-34`). The version stores the reference so that a
    stored capture can be tied back to the authorization that admitted it,
    without the audit's durability depending on this transaction.
    """

    capture_id: str | None
    content: CaptureContent
    idempotency_key: str
    request_id: str
    correlation_id: str
    principal_id: str
    audit_id: str
    classification: Classification
    processing_policy: ProcessingPolicy
    server_received_at: datetime
    accepted_at: datetime
    client_created_at: datetime | None = None
    occurred_at: datetime | None = None
    capture_kind: CaptureKind = CaptureKind.QUICK_NOTE
    context_source_object_id: str | None = None
    context_source_version_id: str | None = None
    #: How the submission reached this process, established by the transport and
    #: never stated by the caller (WP-10). It defaults to `LOCAL` because that is
    #: what every path that does not say otherwise is: the loopback gateway, MCP
    #: over stdio, and the CLI are all the composition root's own process
    #: principal. The remote ingress is the one caller that says otherwise, and
    #: it says so through `ApplicationService.invoke`'s own parameter — the same
    #: trust channel the acting `Principal` arrives on — rather than through any
    #: field of any command, payload, or envelope.
    #:
    #: **It is deliberately outside `payload_digest`.** The digest decides
    #: whether a replayed idempotency key carries the same request, and two
    #: submissions of the same note under the same key from the same Principal
    #: are the same request whether one arrived over loopback and the other over
    #: the ingress. Including the transport would turn a device retrying over a
    #: different route into a `409` conflict, which is exactly the failure
    #: `QC-AC-031` exists to prevent.
    transport: CaptureTransport = CaptureTransport.LOCAL

    @property
    def payload_digest(self) -> str:
        """Digest every material admission input without copying source text."""
        canonical = json.dumps(
            {
                "content_sha256": self.content.digest,
                "capture_kind": self.capture_kind.value,
                "context_source_object_id": self.context_source_object_id,
                "context_source_version_id": self.context_source_version_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def __post_init__(self) -> None:
        if not isinstance(self.capture_kind, CaptureKind):
            raise ValueError("an admission names one capture kind")
        if not isinstance(self.transport, CaptureTransport):
            raise ValueError("an admission names one transport")
        if (self.context_source_object_id is None) is not (self.context_source_version_id is None):
            raise ValueError("a launch context names both object and version")
        if self.context_source_object_id is not None:
            context_version_id = self.context_source_version_id
            if context_version_id is None:  # narrowed from the paired-field invariant above
                raise ValueError("a launch context names both object and version")
            validate_identifier(self.context_source_object_id, IdKind.SOURCE_OBJECT)
            validate_identifier(context_version_id, IdKind.VERSION)


@dataclass(frozen=True, slots=True)
class CaptureAdmission:
    """The receipt for an admitted capture, and whether this call created it.

    `created` false means the idempotency key was already bound to byte-identical
    content, so the correct answer is the receipt the first call got — the
    `QC-AC-031` replay. A key bound to different content is a
    `domain.capture.errors.CaptureConflictError` and never a receipt.
    """

    receipt: CaptureReceipt
    created: bool


@dataclass(frozen=True, slots=True)
class CaptureSummary:
    """One capture as a listing sees it: identity, size, and where its chain got to.

    No content and no digest of a version the caller did not ask for. A listing
    that carried text would put every capture's content into one response, which
    is the opposite of what `capture.read` exists to bound.
    """

    capture_id: str
    owner_principal_id: str
    created_at: datetime
    version_count: int
    latest_version_id: str
    latest_version_number: int
    latest_recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.latest_version_id, IdKind.CAPTURE_VERSION)


@dataclass(frozen=True, slots=True)
class CaptureSearchRequest:
    """One `capture.search` request, bounded on construction.

    **No cursor**, and that is the same call `capture.list` makes: a bounded
    page whose truncation is disclosed, rather than a keyset cursor whose
    binding would have to carry a scope a capture does not have. `SearchCursor`
    binds to an enrollment identifier and a `kn_…`, and a capture plane has
    neither.

    `query` is a `SearchQuery`, so the text is normalized once, bounded once,
    and redacts itself in every rendering — the one sensitive string this plane
    carries.
    """

    query: SearchQuery
    limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.query, SearchQuery):
            raise ValueError("a capture search carries a normalized SearchQuery")
        if isinstance(self.limit, bool) or self.limit < 1:
            raise ValueError("a capture search page holds at least one capture")


@dataclass(frozen=True, slots=True)
class CaptureSearchMatch:
    """One capture version whose stored text matched.

    **No text and no snippet, and neither model has a field one could go in.**
    `QC-AC-041` keeps capture content out of the answers a caller sees most
    often, and a search result is one of those; the caller obtains the text
    through `capture.read`, under its own capability and its own audit event.
    `character_count` is the size of what matched, which is a count rather than
    the content.
    """

    capture_id: str
    version_id: str
    version_number: int
    character_count: int
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.version_number < 1:
            raise ValueError("version numbers start at one")
        if self.character_count < 1:
            raise ValueError("a stored capture version carries text")


@dataclass(frozen=True, slots=True)
class CaptureSearchOutcome:
    """One page of capture matches and the counts a disclosure is built from.

    The two counts are read in the page's own snapshot: `searchable_versions` is
    how many versions the search could have returned and `stored_versions` is
    how many exist. Their difference is what a caller is owed when a revised
    capture's earlier version did not match because it is no longer current —
    an absence with a reason, rather than an absence.
    """

    matches: tuple[CaptureSearchMatch, ...]
    searchable_versions: int
    stored_versions: int
    truncated: bool

    def __post_init__(self) -> None:
        if self.searchable_versions < 0 or self.stored_versions < self.searchable_versions:
            raise ValueError("a scope cannot hold more versions than the store does")


class CaptureRepository(ABC):
    """The capture plane, as the five operations the capabilities need.

    **`reveal` is the fifth, and it is here rather than behind a port of its
    own.** It reads captures, versions, spans, proposals, review cases,
    decisions, assertions and receipts — every one of them a row keyed, directly
    or through a foreign key, to a capture this Principal owns. A second port
    would be a second object over the same partition with the same context
    translation, which is the speculative abstraction the module docstring above
    forbids; the honest cost is that this interface is now the widest of the
    five here, and that is stated rather than hidden.

    **No update and no delete, and their absence is the port's contribution to
    `QC-AC-010`.** A method that changed a stored version could not be added here
    without also defeating the `BEFORE UPDATE OR DELETE` trigger the schema
    carries, so the two halves fail independently: the port offers no such call,
    and the server refuses one made anyway.

    **Every operation takes the authenticated Principal as an input** (WP-03,
    `PKL-MYPA-D-WP03-001`, superseding `D-72`). `owner_principal_id` was stored
    on every version because `ADR-003` clause 6 required it and was read back
    without ever deciding anything; under the ratified campaign it decides
    everything: a read, a list, a search, and a revise each answer only within
    the caller's own partition. `D-72`'s argument — identity was process-scoped,
    so owner equality would strand captures across restarts — is dissolved
    rather than overruled: the local operator's identity is now durable
    (`domain.identity.binding`), so the same person holds the same partition
    across restarts. The parameter is `principal_id` as the knowledge schema's
    text vocabulary (`prn_…`) because that is what the rows carry; it is the
    composition root's authenticated Principal and never a request field
    (MU-AC-02).
    """

    @abstractmethod
    def admit(self, request: CaptureAdmissionRequest, *, principal_id: str) -> CaptureAdmission:
        """Store one capture version and everything that commits with it.

        The capture (for a new chain), the version, the receipt, the submission,
        and the queued processing job are written on this transaction's
        connection, so they commit together or not at all. The audit event the
        request's `audit_id` names is not among them: it committed first, on its
        own connection, and this stores the reference (`D-34`).

        Raises `domain.capture.errors.CaptureConflictError` when the idempotency
        key is already bound to different content *by this Principal*, and
        `UnknownScopeError` when `capture_id` names no capture this Principal
        owns — a capture another Principal owns earns the same refusal a
        nonexistent one does, so the answer maps nothing. The request's own
        `principal_id` must equal this parameter and is verified below rather
        than trusted.
        """

    @abstractmethod
    def version(
        self, capture_id: str, *, version_id: str | None = None, principal_id: str
    ) -> CaptureVersion | None:
        """One stored version of `capture_id`, or `None`.

        `version_id` omitted means the current one, which is the greatest version
        number the capture holds. Named, it means exactly that version — a
        superseded predecessor included, which is the "independently
        retrievable" half of `QC-AC-010`. A version of another capture is `None`,
        the same answer as one that does not exist — and a capture another
        Principal owns is `None` too, the third absence with the same face.
        """

    @abstractmethod
    def captures(self, *, limit: int, principal_id: str) -> tuple[CaptureSummary, ...]:
        """One bounded page of the Principal's own captures, newest first."""

    @abstractmethod
    def search(self, request: CaptureSearchRequest, *, principal_id: str) -> CaptureSearchOutcome:
        """One bounded page of capture versions whose stored text matched.

        Exact at word granularity always, and at character granularity where
        the server reports the query as one contiguous run of text: the plane is
        indexed with the `simple` text-search configuration, which neither stems
        nor drops stop words, because `QC-AC-050` asks for *exact* original text
        to be searchable. Which queries get the character-granularity pass is
        decided by PostgreSQL and not by this contract, so a caller's quoting or
        punctuation never removes a capture the index matched. The cost —
        `meetings` does not find `meeting` — is a limitation the caller is told
        about rather than a property it has to discover.

        Independent of enrichment: the index is over
        `capture_versions.content`, which is written by the save, so a capture
        whose processing failed is searchable on the same terms as one whose
        processing succeeded.
        """

    @abstractmethod
    def reveal(self, subject_id: str, *, principal_id: str) -> Reveal | None:
        """The evidence behind one subject, or `None` when there is no subject.

        `None` is the *one* absence with three causes, exactly as `version` has:
        the subject does not exist, the subject belongs to another Principal, or
        the identifier is well formed and names nothing. A caller that could tell
        those apart could enumerate another Principal's records by asking, so it
        cannot.

        A subject kind this build cannot traverse is **not** `None`. It is a
        `Reveal` in the `unavailable` state naming
        `EvidenceGap.SUBJECT_KIND_NOT_COVERED`, because "we do not cover this
        plane" is a fact about this build and says nothing about whether the
        subject exists.
        """


@dataclass(frozen=True, slots=True)
class ReviewDecisionRequest:
    """Everything one review transition needs inside a single transaction."""

    review_case_id: str
    expected_review_version: int
    disposition: Disposition
    principal_id: str
    correlation_id: str
    audit_id: str
    policy_version: str
    decided_at: datetime
    corrected_value: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        validate_policy_version(self.policy_version)
        ensure_utc(self.decided_at)
        if type(self.expected_review_version) is not int or self.expected_review_version < 0:
            raise ValueError("the expected review version is a non-negative integer")
        if not isinstance(self.disposition, Disposition):
            raise ValueError("a review request names one disposition")
        corrected = self.disposition is Disposition.CORRECT_AND_ACCEPT
        if corrected is not (self.corrected_value is not None):
            raise ValueError("a correction value belongs only to correct-and-accept")
        if self.corrected_value is not None and (
            not self.corrected_value.strip()
            or len(self.corrected_value) > MAX_NORMALIZED_VALUE_CHARACTERS
        ):
            raise ValueError("a correction value is bounded and not blank")


class ReviewRepository(ABC):
    """Review cases and the only port capable of canonical promotion."""

    @abstractmethod
    def cases(
        self, *, limit: int, principal_id: str
    ) -> tuple[ReviewCase | GoodNotesReviewCase, ...]:
        """One bounded page for this Principal, oldest case first.

        `principal_id` is the authenticated caller's identifier: the page is
        confined to that Principal's partition, and a case belonging to any
        other Principal is unreachable through this port (MU-AC-04).
        """

    @abstractmethod
    def decide(self, request: ReviewDecisionRequest) -> ReviewDecision | None:
        """Append a disposition; return `None` when evidence was invalidated."""


class SourceRepository(ABC):
    """The configured-source facts a capability needs, and no locator."""

    @abstractmethod
    def source(self, source_id: str) -> ConfiguredSource | None:
        """Return the configured source `source_id` names, or `None`.

        `None` rather than an exception because the caller's next act is to
        report `not_found`, and section 10 requires that answer to be
        indistinguishable from a denial.
        """

    @abstractmethod
    def source_of_object(self, source_object_id: str) -> str | None:
        """Return the `src_…` an object belongs to, or `None`.

        `sources.status` accepts an object as its subject, and the scope that
        request has to be authorized against is the object's source.
        """


class EnrollmentRepository(ABC):
    """Enrollments: the grants that authorize every read this system performs."""

    @abstractmethod
    def for_principal(self, principal_id: str) -> tuple[Enrollment, ...]:
        """Every enrollment held by `principal_id`.

        This is what the shared authorization path evaluates scope against, so
        the authorized set is a stored fact rather than something a caller
        supplies alongside its request.
        """

    @abstractmethod
    def accept(self, request: EnrollmentRequest) -> Acceptance:
        """Accept `request`, or return what its idempotency key is already bound to.

        Raises `domain.source.enrollment.EnrollmentConflictError` when the key
        is bound to a materially different normalized request.
        """

    @abstractmethod
    def record_scope(self, enrollment_id: str, source_object_ids: Iterable[str]) -> int:
        """Record the objects this enrollment authorizes, and return how many.

        Called once, inside the transaction that accepted the enrollment and
        only where that acceptance created it, so a retried request
        re-enumerates nothing. Idempotent by constraint rather than by
        convention: running the same enumeration twice records no second row.

        Raises `UnknownScopeError` when an identifier names no object of this
        enrollment's source, and `ValueError` for an empty set. Both roll the
        accepting transaction back, which is what makes "an enrollment that
        cannot be enumerated does not exist" structural: the alternative is an
        accepted grant with a zero denominator and queued work behind it.
        """


@dataclass(frozen=True, slots=True)
class Operation:
    """One unit of queued work: which grant it belongs to, and where it is.

    The enrollment travels with the state because `sources.status` has to
    authorize a request that names only an operation, and the scope such a
    request runs in is the enrollment's source. Returning both in one call keeps
    that from being two reads whose answers could disagree.
    """

    operation_id: str
    enrollment_id: str
    state: SourceStatusState

    def __post_init__(self) -> None:
        validate_identifier(self.operation_id, IdKind.OPERATION)
        validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)


class OperationQueue(ABC):
    """The application's job plane, as the two operations a capability needs."""

    @abstractmethod
    def enqueue(self, enrollment_id: str) -> str:
        """Queue the work an accepted enrollment implies and return its `op_…`."""

    @abstractmethod
    def operation(self, operation_id: str, *, principal_id: str) -> Operation | None:
        """One of `principal_id`'s operations, or `None` when there is no such job.

        The Principal is a parameter rather than something the operation is
        trusted to carry, so a job queued under one Principal cannot be read
        through another — the same shape `KnowledgeRepository.read` takes for the
        grant. It is required and has no default: a default would make an
        unvisited call site read the whole plane again.

        `None` covers both "no such job" and "not yours", deliberately. Telling
        them apart would let a caller confirm an operation identifier it has no
        authority over.
        """


class KnowledgeRepository(ABC):
    """Coverage, outcomes, search, and the one read of a stored record."""

    @abstractmethod
    def coverage(
        self,
        enrollment_id: str,
        *,
        observed_at: datetime,
        queued: int = 0,
    ) -> CoverageCounts:
        """Coverage of `enrollment_id` at `observed_at`.

        There is no `eligible` parameter. The denominator is the enumerated
        object set the enrollment stores, so it is read beside the numerators
        rather than stated by a caller that would have had to measure it
        somewhere else. `queued` stays the caller's, because work in flight is a
        fact about the job plane and not about the scope.
        """

    @abstractmethod
    def corpus(self, principal_id: str, *, observed_at: datetime) -> CorpusCoverage:
        """Coverage of everything `principal_id` holds, composed from stated facts.

        **A Principal and not a scope, and that is the whole shape of it.** Every
        other method here takes an enrollment, because coverage "is for a stated
        enrollment/snapshot and never inferred globally". This one takes the
        Principal whose enrollments those are, and returns each enrollment's own
        stated coverage unmerged beside the territory none of them reaches. No
        source and no enrollment crosses this boundary, so there is no argument a
        caller could widen: the implementation partitions on
        `enrollments.principal_id` at the query.

        Not a second coverage definition. The per-enrollment members are the
        values `coverage` above returns, so a corpus answer and a status answer
        cannot disagree about one enrollment.
        """

    @abstractmethod
    def scope_beyond_enrollment(self, principal_id: str, *, enrollment_id: str) -> bool:
        """Whether `principal_id` holds scope that `enrollment_id` does not cover.

        **A boolean and not a count, and that is the contract rather than a
        simplification.** Its one caller is `knowledge.search`, which is
        authorized for the enrollment it names and for nothing else; a number
        here would tell that caller the size of a scope its request never
        authorized, which is the side channel the aggregate-limitation rule
        permits only for the scope actually in question. "There is scope outside
        this answer" is what a caller can act on, and it is all of it.

        This does not widen what a search may read. It is asked *beside* the
        search, answers about the enrollment set the acting Principal already
        holds, and reaches no row of any enrollment the search does not name.
        """

    @abstractmethod
    def limitations(self, enrollment_id: str) -> tuple[AggregateLimitation, ...]:
        """The aggregate limitations recorded at the enrollment's latest snapshot.

        Separate from `coverage` because the two ask different questions of the
        same rows: coverage counts every outcome recorded so far, while a
        limitation belongs to the single enumeration pass that observed it.
        """

    @abstractmethod
    def outcome_for_object(
        self, *, enrollment_id: str, source_object_id: str
    ) -> ExtractionStatus | None:
        """What happened to one object under one enrollment, or `None` for nothing yet."""

    @abstractmethod
    def search(self, request: SearchRequest, *, now: datetime) -> SearchOutcome:
        """Search one enrollment's extracted text and disclose what was searched."""

    @abstractmethod
    def read(self, knowledge_id: str, *, enrollment_id: str) -> KnowledgeRecord | None:
        """Return one stored record inside `enrollment_id`'s grant, or `None`.

        The grant is a parameter rather than something the record is trusted to
        carry, so a record written under one enrollment cannot be read through
        another.
        """


class AuditSink(ABC):
    """Where a redacted audit event goes.

    One method, and it takes an `AuditEvent` rather than fields, because that
    type has no place a payload could be put. The redaction is therefore a
    property of what crosses this boundary rather than of how it is called.
    """

    @abstractmethod
    def record(self, event: AuditEvent) -> None:
        """Persist one redacted audit event."""


class ContextRunRepository(ABC):
    """Insert-only persistence of a prepared-context disclosure.

    The record holds identifiers, digests, fingerprints, and policy versions.
    It does not hold the query, conversation_context, or excerpt text. There is
    no read method on this port yet: reconstruction of disclosed references is
    a later reader, and YAGNI keeps this to `record`.
    """

    @abstractmethod
    def record(self, run: ContextRunRecord) -> None:
        """Persist one context run and its items, filtered by `run.principal_id`."""


class PreferenceConflictError(Exception):
    """The same idempotency key was reused with a different preference payload."""


class ContextPreferenceRepository(ABC):
    """Append-only preference events plus the current projection fold.

    Events are never deleted. Reversal appends an opposing event and updates
    the projection in the same transaction. Every method is principal-partitioned.
    """

    @abstractmethod
    def record(
        self,
        *,
        principal_id: str,
        action: str,
        target_id: str,
        idempotency_key: str,
        alias: str | None,
        source_id: str | None,
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> ContextPreferenceAdmission:
        """Append one event, fold the projection, or replay/conflict on the key."""

    @abstractmethod
    def current_for(self, principal_id: str) -> tuple[ContextPreferenceCurrent, ...]:
        """The acting Principal's current projection. Empty when none are set."""


class SourceProviders(ABC):
    """The lookup from a configured source's identity to its read-only adapter.

    Not a registry of provider *kinds* and not a plugin framework: the adapters
    are already constructed by the composition root, and this answers only "which
    one serves this `src_…`". A use case cannot construct an adapter, which is
    what keeps the choice of implementation in the one place allowed to make it.
    """

    @abstractmethod
    def for_source(self, source_id: str) -> SourceProvider | None:
        """The provider serving `source_id`, or `None` when none is configured."""


@dataclass(frozen=True, slots=True)
class WorkerPlaneStatus:
    """Content-free operational state for one Principal's worker plane."""

    plane: str
    state: str
    backlog: int
    dead_lettered: int
    last_heartbeat_at: datetime | None


class WorkerHealthRepository(ABC):
    """Worker liveness and backlog for the authenticated Principal only."""

    @abstractmethod
    def for_principal(self, principal_id: str) -> tuple[WorkerPlaneStatus, ...]:
        """Return both worker planes without identifiers or queued content."""


class AuthoringConflictError(Exception):
    """The same idempotency key was reused with a different payload."""


@dataclass(frozen=True, slots=True)
class AuthoringReceipt:
    """What a prior user-directed continuity write produced for one key."""

    capability: str
    object_id: str
    payload_digest: str


class ContinuityAuthoringRepository(ABC):
    """Idempotent user-directed Project, Situation, and Task writes."""

    @abstractmethod
    def recall(self, principal_id: str, idempotency_key: str) -> AuthoringReceipt | None:
        """The prior receipt for this key, or None if the key is unused."""

    @abstractmethod
    def reserve(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        capability: str,
        payload_digest: str,
        object_id: str,
    ) -> bool:
        """Claim the key before any continuity row is written.

        Returns True when this transaction now owns `object_id` for the key.
        Returns False when the key already exists with the same digest.
        Raises AuthoringConflictError when the key is bound to different content.
        """

    @abstractmethod
    def author_project(
        self,
        *,
        principal_id: str,
        project_id: str,
        name: str,
        description: str | None,
    ) -> Project:
        """Create one Project under a key this transaction already reserved."""

    @abstractmethod
    def author_situation(
        self,
        *,
        principal_id: str,
        situation_id: str,
        title: str,
        description: str | None,
    ) -> Situation:
        """Open one Situation under a key this transaction already reserved."""

    @abstractmethod
    def author_task(
        self,
        *,
        principal_id: str,
        task_id: str,
        title: str,
        origin_evidence_ref: str,
        project_id: str | None = None,
        situation_id: str | None = None,
        due_at: datetime | None = None,
    ) -> Task:
        """Create one accepted Task under a key this transaction already reserved."""


class UnitOfWork(ABC):
    """One transaction, and the repositories that run inside it.

    Leaving the block normally commits; leaving it by exception rolls back. That
    is the whole of the transaction contract, and it is what makes the enrollment
    rule of `module-boundaries.md` section 10 — enrollment, queued work, and
    audit committed together or not at all — a property of the structure rather
    than of the order a use case happens to call things in.
    """

    @abstractmethod
    def __enter__(self) -> UnitOfWork:
        """Begin the transaction and return the unit of work it belongs to."""

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit when the block succeeded, roll back when it did not."""

    @property
    @abstractmethod
    def providers(self) -> SourceProviders:
        """The source providers, inside this transaction.

        Inside, for the reason the four repositories are: a provider resolves an
        `obj_…` against `knowledge.source_objects`, so it has to read the same
        rows under the same snapshot as the coverage reported beside its result,
        and identifiers it issues have to roll back with the work that issued
        them. A provider holding its own connection while a use case holds a work
        connection is the pool cycle `bootstrap.gateway` derives, and it would
        form at exactly five concurrent requests.

        This is a *removal* of a constructor dependency rather than a new
        contract: `ApplicationService` was handed a `SourceProviders` at
        construction and no longer is. It satisfies
        `module-boundaries.md` section 5.2's rule that contracts exist only for a
        current use case because there are four current callers — `sources.list`,
        `sources.metadata`, `sources.fetch`, and the enumeration inside
        `sources.enroll`.
        """

    @property
    @abstractmethod
    def sources(self) -> SourceRepository:
        """Configured sources, inside this transaction."""

    @property
    @abstractmethod
    def enrollments(self) -> EnrollmentRepository:
        """Enrollments, inside this transaction."""

    @property
    @abstractmethod
    def operations(self) -> OperationQueue:
        """The job plane, inside this transaction."""

    @property
    @abstractmethod
    def knowledge(self) -> KnowledgeRepository:
        """Coverage and stored records, inside this transaction."""

    @property
    @abstractmethod
    def captures(self) -> CaptureRepository:
        """The capture plane, inside this transaction.

        Inside, and that is the whole of the durable-first guarantee: the capture,
        its version, its receipt, its submission, and its queued processing job
        are written on the connection this unit of work owns, so a failure
        anywhere in the request leaves none of them.
        """

    @property
    @abstractmethod
    def reviews(self) -> ReviewRepository:
        """The review and promotion plane, inside this transaction."""

    @property
    @abstractmethod
    def situations(self) -> SituationRepository:
        """The Situation plane, inside this transaction.

        Reached by `continuity.situations` (WP-11). Inside for the reason every
        other repository is: the listing has to read the same rows under the same
        snapshot as the disclosure reported beside it.
        """

    @property
    @abstractmethod
    def projects(self) -> ProjectRepository:
        """The Project plane, inside this transaction. Reached by `continuity.projects`."""

    @property
    @abstractmethod
    def pulse(self) -> PulseRepository:
        """The Pulse plane, inside this transaction. Reached by `continuity.pulse`.

        The derivation runs four `SELECT`s and has to see one consistent picture
        of the Principal's accepted continuity; four reads across four
        transactions could rank a commitment that a fifth statement had already
        closed.
        """

    @property
    def continuity_read(self) -> ContinuityReadRepository:
        """Complete accepted continuity read model, inside this transaction.

        Older test doubles intentionally implement only the narrower WP-11 ports;
        the canonical PostgreSQL composition overrides this property. A caller
        must treat the absence as an unavailable optional projection, never as
        an empty authoritative result.
        """
        raise NotImplementedError

    @property
    def continuity_authoring(self) -> ContinuityAuthoringRepository:
        """User-directed continuity writes and their idempotency receipts.

        Optional on older test doubles. Production and the FAST world implement
        it; a caller that meets this default must treat authoring as unsupported.
        """
        raise NotImplementedError

    @property
    def worker_health(self) -> WorkerHealthRepository:
        """Content-free worker readiness inside this transaction.

        Kept optional for older test doubles. Production composition overrides
        it; a caller that meets this default must report health as unavailable,
        never healthy.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def managed_documents(self) -> ManagedDocumentRepository:
        """The managed-document rows, inside this transaction (WP-28).

        **WP-27 deliberately kept this off the unit of work and WP-28 puts it
        on, so the reversal is argued rather than quietly made.** WP-27's reason
        was reach: the managed write plane would sit on the same object every
        read capability already holds. What changed is that the plane now has a
        capability seat, so it is reached the same way every other plane is —
        through `ApplicationService.invoke`, behind `authorize`, inside the one
        transaction a request owns — and a handler that had to open a *second*
        transaction to write a document would put the rows outside the
        transaction whose rollback is what makes a failed request leave nothing.
        Reach is bounded by dispatch, not by which object holds the property:
        `_HANDLERS` gives each capability exactly one handler, and only the
        `documents.` handlers name this.

        **The byte store is still not here, and that is `AGENTS.md` section 4's
        actual line.** It separates source providers from managed-document
        *stores*; this is a repository over `knowledge.managed_documents` and its
        four sibling tables, which is PostgreSQL like every other repository
        above. The store — the thing that writes bytes to a filesystem — is
        composed once at the composition root and handed to `ApplicationService`,
        so a process with no configured managed root has no store, and the
        capabilities it serves are not published at all.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def tasks(self) -> TaskManagementRepository:
        """The task-management rows, inside this transaction (WP-TM-02/03).

        Placed here for the same reason `managed_documents` is: WP-TM-02 gave
        the plane a capability seat of its own for mutation, and WP-TM-03 gives
        it four more for reading, so it is reached the way every other plane
        with a seat is — through `ApplicationService.invoke`, behind
        `authorize`, inside the one transaction a request owns. A handler that
        opened a second transaction to read or write a task would put the rows
        outside the transaction whose rollback is what makes a failed request
        leave nothing.

        `TaskManagementRepository` is the one ABC for both directions: WP-TM-02
        defined the locking write-side methods on it, and WP-TM-03 adds the
        four non-locking read methods alongside them, rather than splitting a
        read-only ABC off. A `list_tasks` or `search` call has no single row to
        lock in the first place — each answers with a page, not a row a
        subsequent write in the same request will touch — so the distinction
        that matters is per-method, not per-object.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def commitments(self) -> CommitmentManagementRepository:
        """The commitment-management rows, inside this transaction (WP-TM-05).

        Placed here for the same reason `tasks` is: WP-TM-05 gives the plane
        capability seats for read and write, so it is reached through
        `ApplicationService.invoke`, behind `authorize`, inside the one
        transaction a request owns.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def context_runs(self) -> ContextRunRepository:
        """Insert-only context-run metadata, inside this transaction.

        Written after packing, in the same unit of work as `context.prepare`, so
        a handler failure rolls the disclosure record back with the request.
        The port has no update or delete: rollback of the capability is revoke
        (AC-KC-037), not a row mutation. Every write is principal-partitioned.
        """

    @property
    @abstractmethod
    def context_preferences(self) -> ContextPreferenceRepository:
        """Append-only retrieval preferences, inside this transaction.

        Written by `context.feedback` and read by `context.prepare`. Events are
        never deleted; the current projection is folded in the same transaction.
        `principal_id` is a parameter on every method and is the authenticated
        caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def audit(self) -> AuditSink:
        """The audit sink, inside this transaction.

        Inside, because an operator-only command whose audit did not commit must
        not have committed either.
        """


# --- WP-06 R5 continuity ports ---------------------------------------------
#
# These ports take explicit descriptive arguments and return domain objects,
# rather than accepting the `application.commands` continuity commands directly.
# The reason is the dependency direction `contracts` sits under: a port may
# reference `domain` and `contracts` and nothing outer, so importing an
# application command here would invert the layering `test_dependency_direction`
# enforces. This is the same shape `RelationshipRepository` and `ReviewRepository`
# already take — the application service unpacks its command and calls the port
# with plain arguments, and the port answers in domain terms.
#
# `principal_id` is a parameter on every method, and it is the authenticated
# caller's partition, not a caller-supplied field: the concrete repository
# stamps every write with it and filters every read by it, so a continuity
# record belonging to another Principal is unreachable through these ports
# (WP-06 acceptance criteria 1, 3, and 4). `PulseRepository.generate_pulse`
# additionally reads only accepted state (criterion 2), which the migration
# pins with `pulse_reads_only_accepted_records`.


class SituationRepository(ABC):
    """Situations: open, close, read one, and list within a Principal's partition."""

    @abstractmethod
    def open_situation(
        self,
        *,
        principal_id: str,
        title: str,
        description: str | None,
        object_refs: tuple[str, ...],
    ) -> Situation:
        """Open one Situation for `principal_id`, issuing its identifier."""

    @abstractmethod
    def close_situation(
        self,
        *,
        principal_id: str,
        situation_id: str,
        outcome: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> Situation:
        """Close one Situation the Principal owns, recording its outcome and evidence.

        Refuses when `situation_id` names no Situation in this Principal's
        partition — a Situation belonging to any other Principal is unreachable.
        Closing never deletes the objects the Situation referenced.

        **`evidence_kind` and `evidence_ref` are required (WP-11)** and are
        appended as a `closed` row in `continuity_lifecycle_events` in the same
        transaction as the state change. An outcome sentence with nothing under
        it is a status field changing with no trace, which is what this pair
        exists to refuse; a blank reference raises rather than closing.
        """

    @abstractmethod
    def get_situation(self, principal_id: str, situation_id: str) -> Situation | None:
        """Return the Situation the Principal owns, or `None`.

        `None` for one that names nothing in this partition, indistinguishable
        from one that names a Situation owned by another Principal.
        """

    @abstractmethod
    def list_situations(
        self, principal_id: str, state_filter: SituationState | None = None
    ) -> tuple[Situation, ...]:
        """One page of this Principal's Situations, newest first."""


class FrameRepository(ABC):
    """Frames: enter one within a Situation, and read a Situation's frames."""

    @abstractmethod
    def enter_frame(
        self,
        *,
        principal_id: str,
        situation_id: str,
        label: str,
        evidence_refs: tuple[str, ...],
        alternatives: tuple[str, ...],
        obligations: tuple[str, ...],
        uncertainty: str | None,
        next_authority: str | None,
    ) -> Frame:
        """Enter one Frame in a Situation the Principal owns.

        Refuses when the Situation is not in this Principal's partition, so a
        Frame can never be attached across the boundary.
        """

    @abstractmethod
    def get_frames(self, principal_id: str, situation_id: str) -> tuple[Frame, ...]:
        """Every Frame of a Situation the Principal owns, newest first."""


class TraceRepository(ABC):
    """Traces: record one derived reconstruction and read it back."""

    @abstractmethod
    def record_trace(
        self,
        *,
        principal_id: str,
        object_id: str,
        object_type: str,
        time_range_start: datetime | None,
        time_range_end: datetime | None,
    ) -> Trace:
        """Record one Trace for `principal_id`. A Trace is a projection, not evidence."""

    @abstractmethod
    def get_trace(self, principal_id: str, trace_id: str) -> Trace | None:
        """Return the Trace the Principal owns, or `None`."""


class ProjectRepository(ABC):
    """Projects: create, read one, list, and link a Situation into one."""

    @abstractmethod
    def add_project(
        self,
        *,
        principal_id: str,
        name: str,
        description: str | None,
        participants: tuple[str, ...],
    ) -> Project:
        """Create one Project for `principal_id`, issuing its identifier."""

    @abstractmethod
    def get_project(self, principal_id: str, project_id: str) -> Project | None:
        """Return the Project the Principal owns, or `None`."""

    @abstractmethod
    def list_projects(
        self, principal_id: str, state_filter: ProjectState | None = None
    ) -> tuple[Project, ...]:
        """One page of this Principal's Projects, newest first."""

    @abstractmethod
    def link_situation(
        self,
        *,
        principal_id: str,
        project_id: str,
        situation_id: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> None:
        """Bind a Situation into a Project, both owned by this Principal.

        Refuses when either the Project or the Situation is not in this
        Principal's partition. Idempotent per (project, situation).
        """


class RelationshipEventRepository(ABC):
    """Relationship-timeline events, with acceptance gating what Today/Pulse read."""

    @abstractmethod
    def record_event(
        self,
        *,
        principal_id: str,
        person_id: str,
        event_type: RelationshipEventType,
        occurred_at: datetime,
        context: str | None,
        accepted: bool,
        source_ref: str | None,
    ) -> RelationshipEvent:
        """Record one event on a Person's timeline for `principal_id`.

        `accepted` defaults to a proposed event elsewhere; recorded as given
        here. A proposed event is never read as an accepted timeline fact.
        """

    @abstractmethod
    def list_events(self, principal_id: str, person_id: str) -> tuple[RelationshipEvent, ...]:
        """Every event on a Person's timeline the Principal owns, newest first.

        Includes proposed and accepted events, clearly distinguished by the
        `accepted` flag, for the relationship briefing.
        """

    @abstractmethod
    def list_accepted_events(self, principal_id: str) -> tuple[RelationshipEvent, ...]:
        """Only the accepted events across this Principal's relationships.

        This is the accepted-timeline read Today and the briefing use: an event
        that has not passed a human disposition never appears here.
        """


class PulseRepository(ABC):
    """Pulse: derived attention recommendations, generated only from accepted state."""

    @abstractmethod
    def generate_pulse(self, principal_id: str) -> tuple[PulseItem, ...]:
        """This Principal's active Pulse items, highest priority first.

        Returns only items with `accepted_only` true — the structural encoding
        of "Today/Pulse read only accepted records" (WP-06 criterion 2), which
        the schema also pins with the CHECK `pulse_reads_only_accepted_records`.
        Dismissed items are excluded.
        """

    @abstractmethod
    def dismiss_pulse_item(self, principal_id: str, pulse_id: str) -> None:
        """Dismiss one Pulse item the Principal owns.

        Refuses when `pulse_id` names no item in this Principal's partition.
        """

    @abstractmethod
    def derive_pulse(self, principal_id: str, now: datetime) -> tuple[PulseItem, ...]:
        """Derive this Principal's Pulse from accepted continuity, at `now`.

        **A read, and only a read.** It selects the Principal's accepted
        commitments, tasks, decisions and framed obligations, hands them to
        `domain.situation.pulse_derivation.derive_pulse`, and returns what comes
        back. It writes no row, promotes no state, and accepts no review — an
        implementation that did any of those would be the automatic consequential
        promotion `QC-AC-020` forbids, arriving through the one path nobody
        audits because it looks like a listing.

        The acceptance filter is a `WHERE evidence_state = 'accepted'` predicate
        on every one of those selects, alongside the `principal_id` predicate, so
        a proposal is excluded by the query rather than by the caller.
        """


# --- Read model for the complete continuity workspace -----------------------


class ContinuityReadRepository(ABC):
    """Principal-scoped accepted read model used by canonical continuity surfaces."""

    @abstractmethod
    def frames(self, principal_id: str) -> tuple[Frame, ...]:
        """All frames owned by the Principal, newest first."""

    @abstractmethod
    def traces(self, principal_id: str) -> tuple[Trace, ...]:
        """All source-linked traces owned by the Principal, newest first."""

    @abstractmethod
    def commitments(self, principal_id: str) -> tuple[Commitment, ...]:
        """Accepted commitments owned by the Principal."""

    @abstractmethod
    def decisions(self, principal_id: str) -> tuple[Decision, ...]:
        """Accepted decisions owned by the Principal."""

    @abstractmethod
    def tasks(self, principal_id: str) -> tuple[Task, ...]:
        """Accepted tasks owned by the Principal."""

    @abstractmethod
    def relationship_events(self, principal_id: str) -> tuple[RelationshipEvent, ...]:
        """Accepted relationship events owned by the Principal."""


# --- WP-11: the continuity objects, their lifecycle, and their associations ---


class ContinuityRepository(ABC):
    """Commitments, Decisions, Tasks, and the append-only record of their lives.

    One port rather than three, because the three objects share exactly one
    lifecycle, one acceptance gate and one association record, and three ports
    over one table family would be three copies of the same four methods. The
    object kind travels as a closed enum, so a caller cannot name a table.

    **Every method takes `principal_id` and it is the authenticated caller's
    partition.** A commitment, decision or task belonging to another Principal is
    answered exactly as an absent one: `None` from a getter, absence from a
    listing, `UnknownScopeError` from a mutation.

    **Proposing and accepting are different methods, and only one of them can
    produce continuity.** `propose_*` writes `evidence_state = 'proposed'` and
    has no parameter that could make it write anything else. `accept` is the only
    path to `'accepted'`, and it requires the identifier of a review decision in
    the caller's own partition whose disposition accepted something — so a
    derivation, an import, or a model cannot promote its own output by calling
    the method it already has.
    """

    @abstractmethod
    def propose_commitment(
        self,
        *,
        principal_id: str,
        counterparty_person_id: str,
        direction: CommitmentDirection,
        summary: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Commitment:
        """Record one proposed social obligation, and its `opened` lifecycle row."""

    @abstractmethod
    def propose_decision(
        self,
        *,
        principal_id: str,
        question: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        awaiting_authority_ref: str | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Decision:
        """Record one proposed decision, and its `opened` lifecycle row."""

    @abstractmethod
    def propose_task(
        self,
        *,
        principal_id: str,
        title: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Task:
        """Record one proposed task, and its `opened` lifecycle row."""

    @abstractmethod
    def accept(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        review_decision_id: str,
    ) -> None:
        """Promote one proposal to accepted continuity, on a review decision.

        `review_decision_id` must name a `capture_review_decisions` row in this
        Principal's partition whose disposition accepted something. Anything else
        — a decision that rejected, a decision belonging to another Principal, a
        well-formed identifier naming nothing — raises `UnknownScopeError` and
        the object stays a proposal.
        """

    @abstractmethod
    def close(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
        occurred_at: datetime,
    ) -> None:
        """Close one object and append the closure evidence, in one transaction.

        The state change and the `closed` lifecycle row are written on the same
        connection inside the caller's transaction, so a closure whose evidence
        did not commit did not close anything. `evidence_ref` must be non-blank;
        the schema refuses the row otherwise.
        """

    @abstractmethod
    def associate(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        project_id: str | None,
        situation_id: str | None,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> None:
        """Bind one object to a Project and/or a Situation, citing the evidence.

        Both ends must be in this Principal's partition. The association is
        recorded twice on purpose: as the object's own `project_id`/`situation_id`
        so a read is one row, and as an `associated` lifecycle row carrying the
        evidence that justified it, so *why* it belongs is reconstructable from
        the append-only record rather than inferred from a column.
        """

    @abstractmethod
    def association_evidence(
        self, principal_id: str, object_id: str
    ) -> tuple[ContinuityLifecycleEvent, ...]:
        """Every `associated` row for one object, oldest first.

        This is the answer to "why does this belong to that project": the rows
        name the evidence, and an object with no association evidence returns
        nothing rather than a guess.
        """

    @abstractmethod
    def lifecycle_events(
        self, principal_id: str, object_id: str
    ) -> tuple[ContinuityLifecycleEvent, ...]:
        """Every lifecycle row for one object, oldest first."""

    @abstractmethod
    def get_commitment(self, principal_id: str, commitment_id: str) -> Commitment | None:
        """One commitment in this Principal's partition, or `None`."""

    @abstractmethod
    def get_decision(self, principal_id: str, decision_id: str) -> Decision | None:
        """One decision in this Principal's partition, or `None`."""

    @abstractmethod
    def get_task(self, principal_id: str, task_id: str) -> Task | None:
        """One task in this Principal's partition, or `None`."""

    @abstractmethod
    def list_commitments(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Commitment, ...]:
        """This Principal's commitments, optionally only the accepted ones."""

    @abstractmethod
    def list_decisions(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Decision, ...]:
        """This Principal's decisions, optionally only the accepted ones."""

    @abstractmethod
    def list_tasks(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Task, ...]:
        """This Principal's tasks, optionally only the accepted ones."""


# --- WP-27 the managed-document plane ---------------------------------------
#
# One port. WP-27 kept it off `UnitOfWork` and WP-28 put it on, once the plane
# acquired a capability seat and began being reached through
# `ApplicationService.invoke` inside the request's own transaction; the property's
# own docstring argues the reversal. The *byte store* is still not on the unit of
# work and is composed at the composition root, which is the separation
# `AGENTS.md` section 4 actually draws — source providers and managed-document
# stores are separate capabilities.
#
# The operator paths (`verify`, `back_up`, `restore_from_backup`) still take the
# repository directly from a connection `apps/cli/managed_documents.py` opens,
# because they are not requests and have no authorization behind them.
#
# `principal_id` is a parameter on every method and it is the authenticated
# caller's partition, never a caller-supplied field: the concrete repository
# stamps every write with it and filters every read by it.


@dataclass(frozen=True, slots=True)
class ManagedWriteRequest:
    """One request to write a managed document version, already normalized.

    **The version identifier is minted by the caller and travels in the request**,
    which is unusual here and is the ordering the transactional boundary requires:
    the bytes have to be on the device under some identifier before the row that
    names them is inserted, so the identifier is issued first and the same value
    reaches both. `application.managed_documents` is the only thing that mints
    one, and the store derives a location from it rather than being told one.

    **No bytes.** The digest and the size are what the row records; the bytes went
    to the byte store, which is the only component that holds them. A request
    value carrying the content would put a document body on an interface that is
    logged, compared, and rendered in test failures.

    `document_id` absent means "create", present means "revise" — a difference in
    the value rather than in a flag, so no request can be ambiguous about which it
    is. `expected_version_number` is required exactly when revising, because a
    revision without one is a blind write.
    """

    document_id: str | None
    expected_version_number: int | None
    version_id: str
    title: str
    media_type: str
    content_sha256: str
    byte_size: int
    idempotency_key: str
    correlation_id: str
    principal_id: str
    server_received_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.document_id is not None:
            validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        if (self.document_id is None) is not (self.expected_version_number is None):
            raise ValueError(
                "a managed revision names the version it expects; a creation names none"
            )
        if self.expected_version_number is not None and self.expected_version_number < 1:
            raise ValueError("an expected managed version number starts at one")
        validate_managed_title(self.title)
        validate_managed_media_type(self.media_type)
        if not self.idempotency_key:
            raise ValueError("a managed write carries an idempotency key")
        if self.byte_size < 1:
            raise ValueError("a managed write carries bytes")
        ensure_utc(self.server_received_at)

    @property
    def payload_digest(self) -> str:
        """What makes a replay decidable without a second copy of the content.

        Every field a caller supplied that could differ between two requests
        carrying one key, and none this layer added: the minted version
        identifier and the correlation identifier are excluded because they
        differ on every attempt by construction, and including either would make
        every retry a conflict.
        """
        payload = {
            "document_id": self.document_id,
            "expected_version_number": self.expected_version_number,
            "title": self.title,
            "media_type": self.media_type,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ManagedAdmission:
    """The outcome of one managed write: the receipt, and whether it is new."""

    receipt: ManagedDocumentReceipt
    created: bool


class ManagedDocumentRepository(ABC):
    """The managed-document plane, inside one transaction.

    Every method is principal-scoped. A document another Principal owns answers
    exactly what a document that does not exist answers, so a refusal cannot be
    used to learn that an identifier names something.
    """

    @abstractmethod
    def admit(self, request: ManagedWriteRequest) -> ManagedAdmission:
        """Admit one managed write, or return the receipt its key is bound to.

        Raises `ManagedDocumentConflictError` when the key is bound to a
        materially different request, `StaleExpectedVersionError` when the named
        expected version is no longer the head, and `UnknownScopeError` when the
        request names no document this Principal owns.
        """

    @abstractmethod
    def replay_for(
        self, idempotency_key: str, payload_digest: str, *, principal_id: str
    ) -> ManagedDocumentReceipt | None:
        """The receipt this Principal's key is already bound to, or `None`.

        Read before bytes are written, so an ordinary replay stores no second
        copy of them. It is an optimisation and never the decision: `admit` still
        relies on the unique constraint, so two concurrent writers that both read
        `None` still produce one version.

        **It takes the digest, and that is not an optimisation.** A lookup on the
        key alone would answer a *conflicting* request — the same key carrying a
        different document — with the original receipt, silently reporting a
        write that never happened as durable. So a key bound to a different
        digest raises `ManagedDocumentConflictError` here, exactly as `admit`
        does when it meets the same case at the unique constraint.
        """

    @abstractmethod
    def version(
        self, document_id: str, *, version_id: str | None = None, principal_id: str
    ) -> ManagedDocumentVersion | None:
        """One stored version of a document this Principal owns, or `None`.

        `version_id` omitted returns the head, which is the greatest version
        number the document holds — read from the rows rather than from a pointer
        column that could disagree with them.
        """

    @abstractmethod
    def versions(
        self, document_id: str, *, principal_id: str
    ) -> tuple[ManagedDocumentVersion, ...]:
        """Every stored version of one document this Principal owns, oldest first."""

    @abstractmethod
    def documents(
        self, *, limit: int, principal_id: str, include_archived: bool = False
    ) -> tuple[ManagedDocument, ...]:
        """One bounded page of this Principal's documents, newest first."""

    @abstractmethod
    def state(self, document_id: str, *, principal_id: str) -> DocumentState | None:
        """Whether a document this Principal owns is active or archived, or `None`."""

    @abstractmethod
    def transition(
        self,
        document_id: str,
        *,
        transition: LifecycleTransition,
        principal_id: str,
        correlation_id: str,
    ) -> bool:
        """Append one lifecycle row, and report whether it changed anything.

        `False` means the document is already in the state the transition would
        produce, and no row is appended — archiving an archived document is a
        no-op rather than a second event. Raises `UnknownScopeError` when the
        identifier names no document this Principal owns.
        """

    @abstractmethod
    def restore_version(self, version: ManagedDocumentVersion, *, principal_id: str) -> None:
        """Insert one version exactly as a backup recorded it.

        The restore path, and the only writer that supplies its own timestamps
        and version numbers. It refuses a version whose owner is not the
        Principal being restored, so a tampered backup cannot move a document
        between partitions.
        """

    @abstractmethod
    def known_version_identifiers(self) -> frozenset[str]:
        """Every managed version identifier the database holds, across Principals.

        **The one unpartitioned read on this plane, and it is unpartitioned on
        purpose.** Its whole subject is the reverse direction — bytes in the store
        that no row claims — and a partitioned answer would report every other
        Principal's objects as orphans, which is how a reclamation deletes live
        data. It returns opaque identifiers and nothing else: no title, no digest,
        no owner, no content. Operator use only, from the reconciliation path.
        """


class ManagedByteStore(ABC):
    """Durable storage for the bytes of managed document versions.

    **No method takes a path, and that absence is the port's whole security
    property.** Every operation names an opaque `mdver_…` or nothing at all; where
    the bytes actually live is derived by the implementation from that identifier.
    A port with a location parameter would put the choice of location on the
    caller, and the caller is where a traversal enters.

    Separate from `SourceProvider` rather than an extension of it, because
    `AGENTS.md` section 4 makes source providers and managed-document stores
    separate capabilities: the source port has no write method and must not gain
    one, and this port has no read of any source.
    """

    @abstractmethod
    def put(self, version_id: str, content: bytes) -> None:
        """Store `content` as the bytes of `version_id`, durably, exactly once.

        Returns only once the bytes and the name that reaches them are on the
        device. A second call for the same identifier raises: bytes are written
        once, and overwriting is the operation this plane does not have.
        """

    @abstractmethod
    def read(self, version_id: str) -> bytes:
        """Return the stored bytes of `version_id`, or raise."""

    @abstractmethod
    def has(self, version_id: str) -> bool:
        """Whether `version_id`'s bytes are present as a plain readable file."""

    @abstractmethod
    def stored_version_ids(self) -> tuple[str, ...]:
        """Every version identifier this store currently holds bytes for."""

    @abstractmethod
    def unreadable_entries(self) -> tuple[str, ...]:
        """Entries in the store that are not well-formed managed version objects."""

    @abstractmethod
    def put_manifest(self, content: bytes) -> None:
        """Store the backup manifest at this store's one fixed artifact location."""

    @abstractmethod
    def read_manifest(self) -> bytes:
        """Return the backup manifest this store holds."""


# --- WP-TM-02: canonical Task mutation, receipts, idempotency, concurrency --
#
# Deliberately **not** a method added to the existing `UnitOfWork` at the time
# this section was written, and deliberately not `ContinuityRepository`.
# `ContinuityRepository` is the WP-11 two-state `Task`'s port, reached by the
# capability dispatcher `ApplicationService.invoke` already serves. Wiring the
# richer `domain.task.task.Task` into that same dispatcher and its shared
# transaction was explicitly deferred past WP-TM-02 — WP-TM-01's own deferral
# note names "wiring the new domain into ... the application-service layer"
# as such — so adding a property to `UnitOfWork` in WP-TM-02 would have reached
# past what that package did and would have forced every existing fake that
# implements `UnitOfWork` to grow a method it had no use for yet.
#
# `TaskManagementUnitOfWork` is therefore its own transaction boundary, over its
# own repository, following the identical shape `UnitOfWork` already
# establishes: a context manager that commits on success and rolls back on
# exception, handing out one repository bound to the connection it opened.
#
# **WP-TM-03 is the wiring that comment deferred, and only the read half of
# it.** This package gives `Capability.TASKS_*` a dispatch seat in
# `ApplicationService.invoke`, which means the read handlers now run inside
# the one shared transaction every other capability's handler already runs
# in — the same argument `managed_documents` recorded for its own reversal of
# WP-27's separation. `UnitOfWork.tasks` below reaches this same
# `TaskManagementRepository`, unchanged in shape; `TaskManagementUnitOfWork`
# is left in place rather than deleted, because WP-TM-02's own mutation
# service (`application.tasks.TaskManagementService`) still opens it directly
# and is not itself reached from `invoke` yet — wiring *mutation* through the
# shared dispatcher remains WP-TM-04's job, not this one's.


class TaskManagementRepository(ABC):
    """`knowledge.tasks` and `knowledge.task_history`, inside one transaction.

    Every method takes `principal_id` and it is the authenticated caller's
    partition, exactly as `ContinuityRepository` states for the two-state
    model: a task belonging to another Principal is answered as an absent one.

    **`get_for_update` is the read every mutation attempt runs first.** Reading
    the row inside the same transaction that will conditionally write it, under
    a row lock the implementation is asked to hold for the rest of the
    transaction, is what keeps the optimistic-concurrency comparison honest
    against a second writer racing between the read and the write — the
    isolation this port asks of its implementation, stated once here rather
    than left to be assumed true of whichever adapter is composed in.
    """

    @abstractmethod
    def get_for_update(self, principal_id: str, task_id: str) -> TaskAggregate | None:
        """One task in this Principal's partition, row-locked for this transaction, or `None`."""

    @abstractmethod
    def insert_task(self, task: TaskAggregate) -> None:
        """Insert one newly created task row."""

    @abstractmethod
    def update_task(self, task: TaskAggregate) -> None:
        """Overwrite the mutable columns of an existing task row with `task`'s values."""

    @abstractmethod
    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskHistoryEntry | None:
        """The one prior mutation receipt recorded under this key, or `None`.

        `task_history_idempotency_key_is_unique_per_principal` is what makes
        this a lookup rather than a search: at most one row can ever match a
        given `(principal_id, idempotency_key)` pair.
        """

    @abstractmethod
    def insert_history(self, entry: TaskHistoryEntry) -> None:
        """Append one mutation receipt. Never updated, never deleted."""

    # --- WP-TM-03: the read plane -------------------------------------------
    #
    # The four methods below answer `tasks.read`/`list`/`search`/`history` and
    # are deliberately **not** locking. `get_for_update` above exists because a
    # mutation attempt has to compare against, and then overwrite, the exact
    # row it locked; none of these four ever writes anything back, so there is
    # nothing for a lock to protect and taking one would only hold other
    # writers behind a request that was only ever going to look.

    @abstractmethod
    def get(self, principal_id: str, task_id: str) -> TaskAggregate | None:
        """One task in this Principal's partition, unlocked, or `None`.

        The read `ReadTask` (`tasks.read`) runs. A task belonging to another
        Principal is answered exactly as an absent one — `principal_id` is
        part of the lookup key, not a filter applied after the fact, so there
        is no code path in which this method can observe that a differently
        owned row exists at all.
        """

    @abstractmethod
    def list_tasks(
        self,
        principal_id: str,
        *,
        lifecycle_state: TaskLifecycleState | None = None,
        priority: TaskPriority | None = None,
        include_archived: bool = False,
        limit: int,
    ) -> tuple[TaskAggregate, ...]:
        """One bounded page of this Principal's own tasks, newest created first.

        `lifecycle_state` and `priority`, when given, are exact matches — a
        structured filter, not the lexical one `search` performs. Archived
        tasks are excluded unless `include_archived` says otherwise, for the
        same reason `ListManagedDocuments` excludes archived documents: a
        caller who wants a withdrawn task back has to ask for it by name.
        """

    @abstractmethod
    def search(self, principal_id: str, query: str, limit: int) -> tuple[TaskAggregate, ...]:
        """One bounded page of this Principal's own tasks whose title matches `query`.

        A case-insensitive substring match against `title`, the one free-text
        field `domain.task.task.Task` carries — `ILIKE`, executed by
        PostgreSQL, and never a vector or embedding search, which stays behind
        an abstraction and a benchmark gate under `AGENTS.md` section 4 rather
        than becoming an MCV prerequisite.
        """

    @abstractmethod
    def list_history(
        self, principal_id: str, task_id: str, limit: int
    ) -> tuple[TaskHistoryEntry, ...]:
        """One bounded page of one task's append-only mutation record, oldest first.

        Ordered the opposite of `list_tasks`, on purpose: a history answers how
        a task got here, and the useful order for that is the one events
        actually happened in. Scoped by `principal_id` in the same lookup-key
        sense `get` is — a history entry for a task belonging to another
        Principal is unreachable, not merely filtered out.
        """


class TaskManagementUnitOfWork(ABC):
    """One transaction over the task-management tables, and the repository inside it.

    The identical shape `UnitOfWork` establishes, held as a separate port for
    the reason given in the section comment above this class.
    """

    @abstractmethod
    def __enter__(self) -> TaskManagementUnitOfWork:
        """Begin the transaction and return the unit of work it belongs to."""

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit when the block succeeded, roll back when it did not."""

    @property
    @abstractmethod
    def tasks(self) -> TaskManagementRepository:
        """The task-management repository, inside this transaction."""


# --- WP-TM-05: Commitment/Waiting-On/Follow-Up -----------------------------
#
# `CommitmentManagementRepository`/`CommitmentManagementUnitOfWork` mirror
# `TaskManagementRepository`/`TaskManagementUnitOfWork` method-for-method,
# over `knowledge.commitments`/`knowledge.commitment_history` instead of
# `knowledge.tasks`/`knowledge.task_history`. There is no `WaitingOn`
# repository here and there will not be one: "what am I waiting on" is a
# derived read the application layer assembles from `list_commitments` and
# `TaskManagementRepository.list_tasks`/`get`, per the operator-approved
# scope's explicit refusal of a separate WaitingOn store.


class CommitmentManagementRepository(ABC):
    """`knowledge.commitments` and `knowledge.commitment_history`, inside one transaction.

    Every method takes `principal_id` and it is the authenticated caller's
    partition, exactly as `TaskManagementRepository` states for the task
    plane: a commitment belonging to another Principal is answered as an
    absent one.
    """

    @abstractmethod
    def get_for_update(self, principal_id: str, commitment_id: str) -> CommitmentAggregate | None:
        """One commitment in this Principal's partition, row-locked for this transaction, or `None`.

        `None` when it is absent from this Principal's partition, exactly as
        `TaskManagementRepository.get_for_update` treats an absent task.
        """

    @abstractmethod
    def get(self, principal_id: str, commitment_id: str) -> CommitmentAggregate | None:
        """One commitment in this Principal's partition, unlocked, or `None`."""

    @abstractmethod
    def list_commitments(
        self,
        principal_id: str,
        *,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
        limit: int,
    ) -> tuple[CommitmentAggregate, ...]:
        """One bounded page of this Principal's own commitments, newest created first.

        `direction` and `state`, when given, are exact matches — the same
        structured-filter shape `TaskManagementRepository.list_tasks` gives
        `lifecycle_state`/`priority`.
        """

    @abstractmethod
    def insert_commitment(self, commitment: CommitmentAggregate) -> None:
        """Insert one newly created commitment row."""

    @abstractmethod
    def update_commitment(self, commitment: CommitmentAggregate) -> None:
        """Overwrite the mutable columns of an existing commitment row with `commitment`'s values.

        The identical shape `TaskManagementRepository.update_task` gives.
        """

    @abstractmethod
    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> CommitmentHistoryEntry | None:
        """The one prior mutation receipt recorded under this key, or `None`."""

    @abstractmethod
    def insert_history(self, entry: CommitmentHistoryEntry) -> None:
        """Append one mutation receipt. Never updated, never deleted."""

    @abstractmethod
    def list_history(
        self, principal_id: str, commitment_id: str, limit: int
    ) -> tuple[CommitmentHistoryEntry, ...]:
        """One bounded page of one commitment's append-only mutation record, oldest first."""


class CommitmentManagementUnitOfWork(ABC):
    """One transaction over the commitment-management tables, and the repository inside it.

    The identical shape `TaskManagementUnitOfWork` establishes.
    """

    @abstractmethod
    def __enter__(self) -> CommitmentManagementUnitOfWork:
        """Begin the transaction and return the unit of work it belongs to."""

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit when the block succeeded, roll back when it did not."""

    @property
    @abstractmethod
    def commitments(self) -> CommitmentManagementRepository:
        """The commitment-management repository, inside this transaction."""
