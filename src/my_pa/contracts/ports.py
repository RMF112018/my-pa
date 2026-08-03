"""The ports the eight capability use cases call, and nothing else.

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

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType

from my_pa.contracts.v1.disclosure import Disclosure
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.capture.submission import CaptureReceipt
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import Provenance
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.search.query import SearchMatch, SearchRequest
from my_pa.domain.source.enrollment import Enrollment, EnrollmentRequest
from my_pa.domain.source.provider import SourceProvider
from my_pa.domain.source.registry import ConfiguredSource

__all__ = [
    "Acceptance",
    "AuditSink",
    "CaptureAdmission",
    "CaptureAdmissionRequest",
    "CaptureRepository",
    "CaptureSummary",
    "EnrollmentRepository",
    "EvidenceUnavailableError",
    "KnowledgeRecord",
    "KnowledgeRepository",
    "Operation",
    "OperationQueue",
    "PortError",
    "RepositoryFailureError",
    "SearchOutcome",
    "SourceProviders",
    "SourceRepository",
    "UnitOfWork",
    "UnknownScopeError",
]


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


class CaptureRepository(ABC):
    """The capture plane, as the four operations the capabilities need.

    **No update and no delete, and their absence is the port's contribution to
    `QC-AC-010`.** A method that changed a stored version could not be added here
    without also defeating the `BEFORE UPDATE OR DELETE` trigger the schema
    carries, so the two halves fail independently: the port offers no such call,
    and the server refuses one made anyway.

    **Nothing here takes an owning principal as a filter** (`D-72`).
    `owner_principal_id` is stored on every version because `ADR-003` clause 6
    requires it, and read back so a caller can see who wrote one, but it is not
    an input to any lookup. Identity in this build is process-scoped, so
    owner-scoped reads would make a capture unreadable after a restart while
    enforcing a distinction a single-local-principal deployment cannot make.
    """

    @abstractmethod
    def admit(self, request: CaptureAdmissionRequest) -> CaptureAdmission:
        """Store one capture version and everything that commits with it.

        The capture (for a new chain), the version, the receipt, the submission,
        and the queued processing job are written on this transaction's
        connection, so they commit together or not at all. The audit event the
        request's `audit_id` names is not among them: it committed first, on its
        own connection, and this stores the reference (`D-34`).

        Raises `domain.capture.errors.CaptureConflictError` when the idempotency
        key is already bound to different content, and `UnknownScopeError` when
        `capture_id` names no capture.
        """

    @abstractmethod
    def version(self, capture_id: str, *, version_id: str | None = None) -> CaptureVersion | None:
        """One stored version of `capture_id`, or `None`.

        `version_id` omitted means the current one, which is the greatest version
        number the capture holds. Named, it means exactly that version — a
        superseded predecessor included, which is the "independently
        retrievable" half of `QC-AC-010`. A version of another capture is `None`,
        the same answer as one that does not exist.
        """

    @abstractmethod
    def captures(self, *, limit: int) -> tuple[CaptureSummary, ...]:
        """One bounded page of captures, newest first."""


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
    def audit(self) -> AuditSink:
        """The audit sink, inside this transaction.

        Inside, because an operator-only command whose audit did not commit must
        not have committed either.
        """
