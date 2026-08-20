"""The unit of work, and the adapters that put the free functions behind ports.

Everything else in this package is statements: a function taking a `Connection`,
with the caller owning the transaction. This is the caller. `SqlAlchemyUnitOfWork`
opens one transaction on `__enter__`, hands out repositories bound to its
connection, and commits or rolls back on `__exit__` — so an application use case
gets a transaction without ever seeing a connection, which is what
`docs/architecture/module-boundaries.md` section 5.3 asks for.

The adapters are thin on purpose. Each method is one call to the function that
already implements it, plus two translations:

**Errors become the port's vocabulary.** An application use case may not import
`infrastructure`, so it cannot catch a `SQLAlchemyError`, an
`IsolationLevelError`, or `persistence.search`'s private classes; and this
package may not import `application`, so it cannot raise the public error. The
translation therefore happens here, into `contracts.ports`, which both sides can
see. `_read` classifies by retryability and nothing else: an unreachable server
is `EvidenceUnavailableError` and conditionally retryable, a missing column is
`RepositoryFailureError` and is not, and neither carries the statement, the
parameters, or the driver's message — a caller told to retry a schema fault
would be given a lie with a retry budget attached, and a caller shown the
statement would be shown the bound query text with it.

**Absence becomes `None`.** `get_source` raises for an identifier that names no
row; the port answers `None`, because the caller's next act is `not_found` and
section 10 requires that answer to be indistinguishable from a refusal.

**The audit sink is held, not built, and it does not run in this transaction.**
It is passed in, because choosing an implementation is a composition root's
decision and not an adapter's. It is *reached* through the unit of work so that
a use case cannot record an audit event outside the request it belongs to — but
`persistence.audit.SqlAlchemyAuditSink` writes on its own connection and commits
before returning, which is what makes an allowed request's audit survive the
rollback of the work that failed (`D-34`). The sink's own module states why a
second connection is the only mechanism that achieves that, and why the audit
committing ahead of the work is the correct direction of `module-boundaries.md`
section 10's rule rather than an exception to it.

The consequence for this class is small and worth naming: `__exit__` commits and
rolls back the *work*, and the audit is already durable by then either way. A
failure to record therefore reaches `__exit__` as an exception and rolls the work
back, which is section 5.6's fail-closed requirement holding by structure.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import datetime
from types import TracebackType
from typing import assert_never

from sqlalchemy import Connection, Engine
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from my_pa.contracts.ports import (
    Acceptance,
    AuditSink,
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureRepository,
    CaptureSearchOutcome,
    CaptureSearchRequest,
    CaptureSummary,
    CommitmentManagementRepository,
    ContextPreferenceRepository,
    ContextRunRepository,
    ContinuityAuthoringRepository,
    ContinuityReadRepository,
    EnrollmentRepository,
    EvidenceUnavailableError,
    GoodNotesSemanticRepository,
    KnowledgeRecord,
    KnowledgeRepository,
    ManagedDocumentRepository,
    Operation,
    OperationQueue,
    ProjectRepository,
    PulseRepository,
    RepositoryFailureError,
    ReviewDecisionRequest,
    ReviewRepository,
    SearchOutcome,
    SituationRepository,
    SourceProviders,
    SourceRepository,
    TaskManagementRepository,
    UnitOfWork,
    UnknownScopeError,
    WorkerHealthRepository,
    WorkerPlaneStatus,
)
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.capture.reveal import Reveal
from my_pa.domain.capture.review import ReviewCase, ReviewDecision
from my_pa.domain.capture.version import CaptureVersion
from my_pa.domain.extraction.corpus import CorpusCoverage
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.goodnotes.models import GoodNotesReviewCase
from my_pa.domain.search.query import SearchRequest
from my_pa.domain.source.enrollment import Enrollment, EnrollmentRequest
from my_pa.domain.source.registry import ConfiguredSource
from my_pa.infrastructure.persistence import IsolationLevelError
from my_pa.infrastructure.persistence.capture import (
    admit_capture,
    capture_page,
    capture_version,
)
from my_pa.infrastructure.persistence.capture_search import search_captures
from my_pa.infrastructure.persistence.commitment_management import SqlCommitmentManagementRepository
from my_pa.infrastructure.persistence.context_preferences import (
    SqlContextPreferenceRepository,
)
from my_pa.infrastructure.persistence.context_runs import SqlContextRunRepository
from my_pa.infrastructure.persistence.continuity_authoring import (
    SqlContinuityAuthoringRepository,
)
from my_pa.infrastructure.persistence.continuity_read import SqlContinuityReadRepository
from my_pa.infrastructure.persistence.enrollment import (
    accept_enrollment,
    enrollments_for_principal,
    record_scope,
)
from my_pa.infrastructure.persistence.extraction import coverage_for
from my_pa.infrastructure.persistence.goodnotes import (
    decide_goodnotes_review,
    goodnotes_review_cases,
    is_goodnotes_review_case,
)
from my_pa.infrastructure.persistence.goodnotes_semantics import SqlGoodNotesSemanticRepository
from my_pa.infrastructure.persistence.intelligence import SqlIntelligenceStore
from my_pa.infrastructure.persistence.jobs import enqueue_job, job_for
from my_pa.infrastructure.persistence.knowledge import (
    corpus_coverage,
    latest_limitations,
    outcome_for_object,
    read_extraction,
    scope_beyond_enrollment,
)
from my_pa.infrastructure.persistence.managed_documents import SqlManagedDocumentRepository
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.registry import (
    UnknownSourceError,
    get_source,
    source_of_object,
)
from my_pa.infrastructure.persistence.reveal import reveal_subject
from my_pa.infrastructure.persistence.review import decide_review, review_cases
from my_pa.infrastructure.persistence.search import (
    SearchInternalError,
    SearchUnavailableError,
    UnknownEnrollmentError,
    search_extractions,
)
from my_pa.infrastructure.persistence.situation_repository import (
    SqlProjectRepository,
    SqlPulseRepository,
    SqlSituationRepository,
)
from my_pa.infrastructure.persistence.tables import JobState
from my_pa.infrastructure.persistence.task_management import SqlTaskManagementRepository
from my_pa.infrastructure.persistence.worker_health import worker_plane_health
from my_pa.infrastructure.providers.registered import RegisteredSourceProviders

__all__ = ["SqlAlchemyUnitOfWork"]


def _read[T](statement: Callable[[], T]) -> T:
    """Run `statement`, converting a store failure into the port's vocabulary.

    The `raise` is outside the handlers, as everywhere else in this package:
    `raise … from None` clears `__cause__` and leaves the original in
    `__context__`, where a rendered traceback shows a `DBAPIError` whose message
    can carry the statement and its bound parameters. Leaving the handler first
    is what actually empties it.
    """
    try:
        return statement()
    except (OperationalError, InterfaceError):
        # The server is unreachable, the connection died, or a statement timeout
        # fired. Conditionally retryable.
        failure: Exception = EvidenceUnavailableError("the store could not be read")
    except (SQLAlchemyError, IsolationLevelError):
        # A missing column, a type error, a row that vanished between two
        # statements. Retrying reads the same rows and fails the same way.
        failure = RepositoryFailureError("the request could not be completed")
    raise failure


def _public_state(state: JobState) -> SourceStatusState:
    """The public status one job state is.

    Written out exhaustively so a new job state cannot be reported as something
    it is not. `succeeded` becomes `complete_for_scope`, which is a claim about
    the bounded enrollment the job carried and never about the physical source.
    """
    match state:
        case JobState.QUEUED:
            return SourceStatusState.QUEUED
        case JobState.RUNNING:
            return SourceStatusState.RUNNING
        case JobState.SUCCEEDED:
            return SourceStatusState.COMPLETE_FOR_SCOPE
        case JobState.FAILED:
            return SourceStatusState.FAILED
    assert_never(state)


class _Sources(SourceRepository):
    """Configured sources, over `persistence.registry`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def source(self, source_id: str) -> ConfiguredSource | None:
        def statement() -> ConfiguredSource | None:
            try:
                return get_source(self._connection, source_id)
            except UnknownSourceError:
                return None

        return _read(statement)

    def source_of_object(self, source_object_id: str) -> str | None:
        return _read(lambda: source_of_object(self._connection, source_object_id))


class _Enrollments(EnrollmentRepository):
    """Enrollments, over `persistence.enrollment`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_principal(self, principal_id: str) -> tuple[Enrollment, ...]:
        return _read(lambda: enrollments_for_principal(self._connection, principal_id))

    def accept(self, request: EnrollmentRequest) -> Acceptance:
        def statement() -> Acceptance:
            # `EnrollmentConflictError` deliberately passes through untranslated.
            # It is an answer about the caller's own idempotency key rather than
            # a failure of the store, and the application already imports the
            # domain type that carries it.
            accepted = accept_enrollment(self._connection, request)
            return Acceptance(enrollment=accepted.enrollment, created=accepted.created)

        return _read(statement)

    def record_scope(self, enrollment_id: str, source_object_ids: Iterable[str]) -> int:
        """Record the enumerated set, letting both of its refusals through.

        `UnknownScopeError` is already the port's own vocabulary — the writer
        raises it directly, because `contracts.ports` is the one package both
        layers may import — so translating it here would mean catching a port
        error to raise the same port error. `ValueError` for an empty set passes
        through untranslated as well, and that is a decision rather than an
        omission: it is an answer about the scope the caller asked for, the
        application refuses the empty enumeration before it reaches this, and
        collapsing it into `RepositoryFailureError` would report an operator's
        empty root as this system being broken.
        """
        return _read(lambda: record_scope(self._connection, enrollment_id, source_object_ids))


class _Operations(OperationQueue):
    """The job plane, over `persistence.jobs`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def enqueue(self, enrollment_id: str) -> str:
        return _read(lambda: enqueue_job(self._connection, enrollment_id))

    def operation(self, operation_id: str, *, principal_id: str) -> Operation | None:
        def statement() -> Operation | None:
            found = job_for(self._connection, operation_id, principal_id=principal_id)
            if found is None:
                return None
            return Operation(
                operation_id=found.operation_id,
                # This queue is the enrollment plane, so the subject is a grant.
                # `persistence.jobs` names the column for what it holds rather
                # than for one plane's use of it, because the capture plane's
                # subject is a version.
                enrollment_id=found.subject_id,
                state=_public_state(found.state),
            )

        return _read(statement)


class _WorkerHealth(WorkerHealthRepository):
    """The two content-free worker-plane reads on this transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_principal(self, principal_id: str) -> tuple[WorkerPlaneStatus, ...]:
        def statement() -> tuple[WorkerPlaneStatus, ...]:
            return tuple(
                WorkerPlaneStatus(
                    plane=health.plane,
                    state=health.state,
                    backlog=health.backlog,
                    dead_lettered=health.dead_lettered,
                    last_heartbeat_at=health.last_heartbeat_at,
                )
                for health in (
                    worker_plane_health(
                        self._connection, principal_id=principal_id, plane_name=plane
                    )
                    for plane in ("capture", "enrollment")
                )
            )

        return _read(statement)


class _Captures(CaptureRepository):
    """The capture plane, over `persistence.capture`.

    Five methods, and none of them writes over a stored version. There is no
    `update` and no `delete` here because there is none in the module below it
    and none the server would accept: `capture_versions` carries a trigger that
    refuses both.

    `search` reaches a second module, `persistence.capture_search`, rather than
    `persistence.capture`: the capture plane's lexical index is its own concern
    with its own configuration and its own scope predicate, and the module that
    writes a capture has no reason to hold either.

    Each method takes the port's `principal_id` and builds the
    `PrincipalContext` here (WP-03), because the port speaks the contracts
    vocabulary — a text identifier — and the guard speaks the persistence one —
    a context with the durable UUID beside it. `capture_context` is the only
    translation between the two, so a Principal that reaches this class at all
    reaches every scoped statement below it identically.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def admit(self, request: CaptureAdmissionRequest, *, principal_id: str) -> CaptureAdmission:
        """Admit one submission, letting both of its refusals through.

        `CaptureConflictError` is a domain type the application already imports
        and is an answer about the caller's own idempotency key rather than a
        failure of the store; translating it into a repository failure would turn
        "this key is bound to something else" into "try again later".
        `UnknownScopeError` is already the port's own vocabulary, so translating
        it here would mean catching a port error to raise the same port error.
        """
        return _read(
            lambda: admit_capture(self._connection, request, context=capture_context(principal_id))
        )

    def version(
        self, capture_id: str, *, version_id: str | None = None, principal_id: str
    ) -> CaptureVersion | None:
        return _read(
            lambda: capture_version(
                self._connection,
                capture_id,
                version_id=version_id,
                context=capture_context(principal_id),
            )
        )

    def captures(self, *, limit: int, principal_id: str) -> tuple[CaptureSummary, ...]:
        return _read(
            lambda: capture_page(
                self._connection, limit=limit, context=capture_context(principal_id)
            )
        )

    def search(self, request: CaptureSearchRequest, *, principal_id: str) -> CaptureSearchOutcome:
        """One page of exact matches over stored capture text.

        **`_read` does not translate this call's failures, and the paragraph that
        used to stand here said it did.** `_read` catches `OperationalError`,
        `InterfaceError`, `SQLAlchemyError` and `IsolationLevelError`.
        `capture_search` does not raise any of them: it converts every failure
        into `CaptureSearchUnavailableError` or `CaptureSearchInternalError`,
        which are plain `Exception` subclasses and appear nowhere in `src/` or
        `apps/` outside the module that defines them. So a failure of this read
        leaves here **as itself** — past the port's vocabulary, into
        `application`, outside section 10's taxonomy and with no envelope.

        `_Extractions.search` is the one that does it properly: it wraps its call
        in an explicit `try` naming `SearchUnavailableError` and
        `SearchInternalError` and maps them to `EvidenceUnavailableError` and
        `RepositoryFailureError`. The asymmetry is the defect. The fix is the
        same shape — this call needs its own translation, not a wider `_read`,
        because widening `_read` to catch two classes from one sibling module
        would make every other repository's failures pass through a handler that
        names them.

        **Recorded rather than fixed, deliberately.** This predates the package
        that wrote this paragraph: it is not a regression that package
        introduced, the redaction work it did is what made the gap legible, and
        closing it changes what `application` receives from `capture.search` —
        a contract change with its own tests and its own review. It is written
        here, at the call site, because no guard can see it: the redaction guards
        are bounded to the two modules that publish a redaction contract, and
        nothing in `tests/security` exercises a failing capture search through
        the unit of work.
        """
        return _read(
            lambda: search_captures(
                self._connection, request, context=capture_context(principal_id)
            )
        )

    def reveal(self, subject_id: str, *, principal_id: str) -> Reveal | None:
        """The evidence behind one subject, read through the same one context.

        `persistence.reveal` rather than `persistence.capture`, for the reason
        `search` reaches `persistence.capture_search`: the traversal spans the
        proposal, review and promotion tables as well as the capture ones, and
        the module that writes a capture has no reason to hold any of them.
        """
        return _read(
            lambda: reveal_subject(
                self._connection, subject_id, context=capture_context(principal_id)
            )
        )


class _Reviews(ReviewRepository):
    """The governed review and promotion plane."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def cases(
        self, *, limit: int, principal_id: str
    ) -> tuple[ReviewCase | GoodNotesReviewCase, ...]:
        def statement() -> tuple[ReviewCase | GoodNotesReviewCase, ...]:
            capture = review_cases(
                self._connection, limit=limit, context=capture_context(principal_id)
            )
            goodnotes = goodnotes_review_cases(
                self._connection, principal_id=principal_id, limit=limit
            )
            combined: list[ReviewCase | GoodNotesReviewCase] = sorted(
                [*capture, *goodnotes],
                key=lambda case: (case.opened_at, case.review_case_id),
            )
            return tuple(combined[:limit])

        return _read(statement)

    def decide(self, request: ReviewDecisionRequest) -> ReviewDecision | None:
        def statement() -> ReviewDecision | None:
            if is_goodnotes_review_case(
                self._connection,
                review_case_id=request.review_case_id,
                principal_id=request.principal_id,
            ):
                return decide_goodnotes_review(self._connection, request)
            return decide_review(self._connection, request)

        return _read(statement)


class _Knowledge(KnowledgeRepository):
    """Coverage, outcomes, search, and the one record read."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def coverage(
        self,
        enrollment_id: str,
        *,
        observed_at: datetime,
        queued: int = 0,
    ) -> CoverageCounts:
        def statement() -> CoverageCounts:
            return coverage_for(
                self._connection,
                enrollment_id,
                observed_at=observed_at,
                queued=queued,
            )

        try:
            return _read(statement)
        except ValueError:
            # `coverage_for` raises through `CoverageCounts` when the counts and
            # the enumerated total disagree about what is in scope. No outcome
            # can produce that any more — every count is restricted to the rows
            # the total counts — so what remains is queued work declared against
            # a scope smaller than it, and outcome rows whose enumerated row has
            # gone. Both are a broken store and this system's fault: retrying
            # reads the same rows and fails the same way. Classified rather than
            # left as an untyped crash, and raised outside the handler so a
            # traceback does not render the frames of a coverage read.
            failure = RepositoryFailureError("the coverage read could not be completed")
        raise failure

    def corpus(self, principal_id: str, *, observed_at: datetime) -> CorpusCoverage:
        """The Principal's whole corpus, translated like every other read here.

        The `ValueError` guard is `coverage`'s and for the same reasons plus one
        of its own: `CorpusCoverage` refuses a composition whose parts contradict
        each other — an enrollment stated twice, more objects outside the
        enrollments than the sources hold, or a state that claims a complete
        corpus while something is outstanding. Each of those is a broken store or
        a broken derivation rather than a request problem, and retrying reads the
        same rows and fails the same way.
        """

        def statement() -> CorpusCoverage:
            return corpus_coverage(self._connection, principal_id, observed_at=observed_at)

        try:
            return _read(statement)
        except ValueError:
            failure = RepositoryFailureError("the corpus coverage read could not be completed")
        raise failure

    def scope_beyond_enrollment(self, principal_id: str, *, enrollment_id: str) -> bool:
        return _read(
            lambda: scope_beyond_enrollment(
                self._connection, principal_id, enrollment_id=enrollment_id
            )
        )

    def limitations(self, enrollment_id: str) -> tuple[AggregateLimitation, ...]:
        return _read(lambda: latest_limitations(self._connection, enrollment_id))

    def outcome_for_object(
        self, *, enrollment_id: str, source_object_id: str
    ) -> ExtractionStatus | None:
        return _read(
            lambda: outcome_for_object(
                self._connection,
                enrollment_id=enrollment_id,
                source_object_id=source_object_id,
            )
        )

    def search(self, request: SearchRequest, *, now: datetime) -> SearchOutcome:
        """Search, translating this module's private failures into the port's.

        `SearchCursorError` and `EmptySearchQueryError` are deliberately not
        translated: they are answers about the caller's request rather than
        failures of the store, they are domain types the application already
        imports, and collapsing them into a repository failure would turn "your
        cursor does not belong to this request" into "try again later".

        **The call runs inside `_read` as well, and that is not belt and braces.**
        `search_extractions` does not classify every failure it can raise:
        `persistence.search._coverage` catches `ValueError` and nothing else, so a
        `SQLAlchemyError` raised by `coverage_for` inside it passes straight
        through — carrying the statement and its bound `enrollment_id`.
        `persistence.search` names that hole in its own module docstring and
        carries it to WP-4, and this is where it is closed: `_read` is the
        translation every other method here already runs through, and this method
        was the one that skipped it. The three `except` clauses sit outside
        `_read` because those types are not `SQLAlchemyError` and pass through it
        untouched.
        """

        def statement() -> SearchOutcome:
            page = search_extractions(self._connection, request, now=now)
            return SearchOutcome(matches=page.matches, disclosure=page.disclosure)

        try:
            return _read(statement)
        except UnknownEnrollmentError:
            failure: Exception = UnknownScopeError("the scope names no enrollment")
        except SearchUnavailableError:
            failure = EvidenceUnavailableError("the lexical index could not be read")
        except SearchInternalError:
            failure = RepositoryFailureError("the search could not be completed")
        raise failure

    def read(self, knowledge_id: str, *, enrollment_id: str) -> KnowledgeRecord | None:
        return _read(
            lambda: read_extraction(self._connection, knowledge_id, enrollment_id=enrollment_id)
        )


class SqlAlchemyUnitOfWork(UnitOfWork):
    """One PostgreSQL transaction, and the repositories that run inside it.

    Not reusable while open and not reentrant: `__enter__` opens one transaction
    and `__exit__` ends it, and asking for a repository outside that window
    raises rather than quietly running an autocommitting statement. A
    composition root hands the application a factory, so each invocation gets
    its own.
    """

    def __init__(self, engine: Engine, *, audit: AuditSink) -> None:
        self._engine = engine
        self._audit = audit
        self._context: AbstractContextManager[Connection] | None = None
        self._connection: Connection | None = None

    def __enter__(self) -> UnitOfWork:
        """Open the transaction, translating a failure to open it.

        Through `_read` like every statement below, and for the same reason.
        Opening is where the connection is actually made, so a server that is
        down fails *here* and not in a repository method — and until WP-4B2a
        this line was the one path out of this class that skipped the
        translation. A `psycopg.OperationalError` escaped as itself, and
        `ApplicationService.invoke`'s terminal catch turned an unreachable
        database into `internal_error`: a caller told the product is broken when
        the truth is that PostgreSQL is not running, which are different things
        to do about it. Nothing leaked either way; the code was wrong, not the
        redaction.

        `Engine.begin()` is a generator-based context manager, so nothing is
        open until `__enter__` runs and a failure inside it leaves nothing to
        close. Neither attribute is assigned when it raises, so a failed open
        leaves this object in the state it started in.
        """
        if self._context is not None:
            raise RuntimeError("this unit of work is already inside a transaction")
        context = self._engine.begin()
        self._connection = _read(context.__enter__)
        self._context = context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        context = self._context
        self._context = None
        self._connection = None
        if context is not None:
            # Commits when the block succeeded and rolls back when it did not.
            # The return value is discarded deliberately: a unit of work that
            # swallowed its caller's exception would commit a failed operation.
            context.__exit__(exc_type, exc, traceback)

    @property
    def _open(self) -> Connection:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return connection

    @property
    def providers(self) -> SourceProviders:
        """The lookup driven by `knowledge.sources`, on this transaction's connection.

        A fresh `RegisteredSourceProviders` per access, like every repository
        above, and bound to the open connection for the reason `contracts.ports`
        gives: an identifier a provider issues belongs to this transaction, and a
        provider that drew its own connection would close the pool cycle
        `bootstrap.gateway` derives.

        What is *not* translated here, stated rather than left to be found:
        `for_source` runs a `SELECT`, and a failure of it escapes as a
        `SQLAlchemyError` rather than as `EvidenceUnavailableError`. Wrapping it
        would mean a decorating implementation of `SourceProviders` whose only
        job is to re-raise, and the failure is already caught and classified by
        `ApplicationService.invoke`'s terminal handler, which discloses nothing
        of it. It reaches a caller as `internal_error` where `unavailable` would
        be the more accurate of the two.
        """
        return RegisteredSourceProviders(self._open)

    @property
    def sources(self) -> SourceRepository:
        return _Sources(self._open)

    @property
    def enrollments(self) -> EnrollmentRepository:
        return _Enrollments(self._open)

    @property
    def operations(self) -> OperationQueue:
        return _Operations(self._open)

    @property
    def knowledge(self) -> KnowledgeRepository:
        return _Knowledge(self._open)

    @property
    def captures(self) -> CaptureRepository:
        return _Captures(self._open)

    @property
    def reviews(self) -> ReviewRepository:
        return _Reviews(self._open)

    @property
    def situations(self) -> SituationRepository:
        return SqlSituationRepository(self._open)

    @property
    def projects(self) -> ProjectRepository:
        return SqlProjectRepository(self._open)

    @property
    def pulse(self) -> PulseRepository:
        return SqlPulseRepository(self._open)

    @property
    def continuity_read(self) -> ContinuityReadRepository:
        return SqlContinuityReadRepository(self._open)

    @property
    def continuity_authoring(self) -> ContinuityAuthoringRepository:
        return SqlContinuityAuthoringRepository(self._open)

    @property
    def worker_health(self) -> WorkerHealthRepository:
        return _WorkerHealth(self._open)

    @property
    def managed_documents(self) -> ManagedDocumentRepository:
        """The managed-document rows, on this transaction's connection (WP-28)."""
        return SqlManagedDocumentRepository(self._open)

    @property
    def tasks(self) -> TaskManagementRepository:
        """The task-management rows, on this transaction's connection (WP-TM-03)."""
        return SqlTaskManagementRepository(self._open)

    @property
    def commitments(self) -> CommitmentManagementRepository:
        """The commitment-management rows, on this transaction's connection (WP-TM-05)."""
        return SqlCommitmentManagementRepository(self._open)

    @property
    def context_runs(self) -> ContextRunRepository:
        """Insert-only context-run metadata, on this transaction's connection."""
        return SqlContextRunRepository(self._open)

    @property
    def context_preferences(self) -> ContextPreferenceRepository:
        """Append-only retrieval preferences, on this transaction's connection."""
        return SqlContextPreferenceRepository(self._open)

    @property
    def goodnotes_semantics(self) -> GoodNotesSemanticRepository:
        """Immutable page-version work and semantic proposal receipts."""
        return SqlGoodNotesSemanticRepository(self._open)

    def intelligence_for(self, principal_id: str) -> SqlIntelligenceStore:
        """Intelligence Artifact store, on this transaction's connection."""
        return SqlIntelligenceStore(self._open, principal_id)

    @property
    def audit(self) -> AuditSink:
        return self._audit
