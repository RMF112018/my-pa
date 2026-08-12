"""The ports the fifteen capability use cases call, and nothing else.

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
from my_pa.domain.capture.review import Disposition, ReviewCase, ReviewDecision
from my_pa.domain.capture.submission import CaptureKind, CaptureReceipt
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import Provenance
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
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

__all__ = [
    "Acceptance",
    "AuditSink",
    "CaptureAdmission",
    "CaptureAdmissionRequest",
    "CaptureRepository",
    "CaptureSearchMatch",
    "CaptureSearchOutcome",
    "CaptureSearchRequest",
    "CaptureSummary",
    "EnrollmentRepository",
    "EvidenceUnavailableError",
    "FrameRepository",
    "KnowledgeRecord",
    "KnowledgeRepository",
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
    "TraceRepository",
    "UnitOfWork",
    "UnknownScopeError",
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
    def cases(self, *, limit: int, principal_id: str) -> tuple[ReviewCase, ...]:
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
    def operation(self, operation_id: str) -> Operation | None:
        """One operation, or `None` when there is no such job."""


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
    def close_situation(self, *, principal_id: str, situation_id: str, outcome: str) -> Situation:
        """Close one Situation the Principal owns, recording its outcome.

        Refuses when `situation_id` names no Situation in this Principal's
        partition — a Situation belonging to any other Principal is unreachable.
        Closing never deletes the objects the Situation referenced.
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
    def link_situation(self, *, principal_id: str, project_id: str, situation_id: str) -> None:
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
