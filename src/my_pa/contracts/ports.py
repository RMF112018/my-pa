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
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType

from my_pa.contracts.v1.disclosure import Disclosure
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.audit.events import AuditEvent
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
        eligible: int | None,
        queued: int = 0,
    ) -> CoverageCounts:
        """Coverage of `enrollment_id` at `observed_at`.

        `eligible` is the enumerated total, or `None` from a caller that has no
        enumeration to quote. `None` is not a convenience: it states that the
        denominator was never measured, which is what stops the derived total
        from being presented as a measured scope.
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
    def audit(self) -> AuditSink:
        """The audit sink, inside this transaction.

        Inside, because an operator-only command whose audit did not commit must
        not have committed either.
        """
