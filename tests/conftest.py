"""In-memory implementations of the application ports, and a synthetic world.

Application use cases are tested against fakes rather than a database, which is
what the ports are for: `module-boundaries.md` section 11 puts "application use
cases with fakes for source, policy, repositories, jobs, audit, clock, and IDs"
in the unit/contract tier, and the FAST tier is required to be database-free.

What these fakes are and are not:

* They implement the *port*, not the store. `_Knowledge.coverage` counts the
  outcomes recorded in `World` the way `coverage_for` counts the rows it reads —
  by distinct object, with quarantine outranking unsupported outranking
  extracted — so a test that changes an outcome changes the disclosed envelope
  for the same reason a database would. What they cannot prove is that the real
  adapter reads what WP-3 wrote; that claim belongs to the `database` tier in
  `tests/schema/test_persistence_ports.py`, and neither test is sufficient alone.
* They are not lenient. A repository asked for something absent answers `None`,
  and `World.failures` lets a test make one raise the port's own failure, so the
  translation into a public error is exercised rather than assumed.
* `_UnitOfWork` counts commits and rollbacks. That is how the transaction
  claims — a denial commits its audit, a failure rolls the work back — become
  assertions rather than descriptions.

The source provider is *not* faked. `FixtureSourceProvider` over a `tmp_path`
tree is the real adapter, so containment denial, version conflict, and bounded
reads are the real behaviour rather than a stand-in that agrees with the test.
`RecordingProvider` wraps it and records which methods were called, which is how
"nothing here can mutate a source" is proved by what ran rather than by reading
the code.

Everything is synthetic: no real path, no real person, no live source.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import pytest

from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    Acceptance,
    AuditSink,
    EnrollmentRepository,
    KnowledgeRecord,
    KnowledgeRepository,
    Operation,
    OperationQueue,
    PortError,
    SearchOutcome,
    SourceProviders,
    SourceRepository,
    UnitOfWork,
)
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.disclosure import (
    Coverage,
    Disclosure,
    Freshness,
    FreshnessState,
    Scope,
    Trust,
)
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.search.query import RankCategory, SearchMatch, SearchRequest
from my_pa.domain.source.enrollment import (
    Enrollment,
    EnrollmentConflictError,
    EnrollmentRequest,
    EnrollmentScope,
)
from my_pa.domain.source.provider import (
    ObjectKind,
    SourceObject,
    SourceObjectContent,
    SourceProvider,
)
from my_pa.domain.source.registry import ConfiguredSource, SourceProviderKind, issue_identifier
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider

#: One fixed instant, so every disclosure in a test is comparable.
WHEN = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: The limits `D-24` makes the configuration defaults, as the application
#: receives them. Restated here rather than imported from settings, so a test
#: about a *changed* limit changes something the production default does not.
DEFAULT_LIMITS = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


@dataclass
class World:
    """Everything the fake repositories know, in one mutable place."""

    sources: dict[str, ConfiguredSource] = field(default_factory=dict)
    objects: dict[str, str] = field(default_factory=dict)
    enrollments: list[Enrollment] = field(default_factory=list)
    jobs: dict[str, tuple[str, SourceStatusState]] = field(default_factory=dict)
    outcomes: dict[str, dict[str, ExtractionStatus]] = field(default_factory=dict)
    limitations: dict[str, tuple[AggregateLimitation, ...]] = field(default_factory=dict)
    records: dict[tuple[str, str], KnowledgeRecord] = field(default_factory=dict)
    searches: dict[str, SearchOutcome] = field(default_factory=dict)
    #: Fingerprints of accepted enrollment requests, by idempotency key, so the
    #: fake can tell a retry from a conflict the way the unique constraint does.
    keys: dict[str, str] = field(default_factory=dict)
    audit: list[AuditEvent] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0
    #: Port failures a test wants raised, keyed by the method that should raise.
    failures: dict[str, PortError] = field(default_factory=dict)

    def fail(self, method: str) -> None:
        """Raise `World.failures[method]` when it is set."""
        failure = self.failures.get(method)
        if failure is not None:
            raise failure

    def add_source(
        self, *, classification: Classification = Classification.SYNTHETIC_TEST
    ) -> ConfiguredSource:
        source = ConfiguredSource(
            source_id=issue_identifier(IdKind.SOURCE),
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic source",
            classification=classification,
            configured_at=WHEN,
        )
        self.sources[source.source_id] = source
        return source

    def add_enrollment(
        self,
        *,
        source_id: str,
        principal_id: str,
        object_ids: tuple[str, ...] = (),
        root_object_id: str | None = None,
        media_types: tuple[str, ...] = ("text/markdown", "text/plain"),
        accepted_at: datetime = WHEN,
    ) -> Enrollment:
        enrollment = Enrollment(
            enrollment_id=issue_identifier(IdKind.ENROLLMENT),
            source_id=source_id,
            principal_id=principal_id,
            purpose=Purpose.BOUNDED_ENROLLMENT,
            scope=EnrollmentScope(object_ids=object_ids, root_object_id=root_object_id),
            media_types=media_types,
            policy_version="policy-v1",
            request_fingerprint="0" * 64,
            max_items=100,
            max_bytes=1_000_000,
            accepted_at=accepted_at,
        )
        self.enrollments.append(enrollment)
        for object_id in object_ids:
            self.objects[object_id] = source_id
        if root_object_id is not None:
            self.objects[root_object_id] = source_id
        return enrollment

    def record_outcome(
        self, *, enrollment_id: str, source_object_id: str, status: ExtractionStatus
    ) -> None:
        self.outcomes.setdefault(enrollment_id, {})[source_object_id] = status


class _Sources(SourceRepository):
    def __init__(self, world: World) -> None:
        self._world = world

    def source(self, source_id: str) -> ConfiguredSource | None:
        self._world.fail("source")
        return self._world.sources.get(source_id)

    def source_of_object(self, source_object_id: str) -> str | None:
        self._world.fail("source_of_object")
        return self._world.objects.get(source_object_id)


class _Enrollments(EnrollmentRepository):
    def __init__(self, world: World) -> None:
        self._world = world

    def for_principal(self, principal_id: str) -> tuple[Enrollment, ...]:
        self._world.fail("for_principal")
        return tuple(e for e in self._world.enrollments if e.principal_id == principal_id)

    def accept(self, request: EnrollmentRequest) -> Acceptance:
        self._world.fail("accept")
        held = self._world.keys.get(request.idempotency_key)
        if held is not None:
            existing = next(e for e in self._world.enrollments if e.request_fingerprint == held)
            if held != request.fingerprint:
                raise EnrollmentConflictError(existing.enrollment_id)
            return Acceptance(enrollment=existing, created=False)
        enrollment = Enrollment(
            enrollment_id=issue_identifier(IdKind.ENROLLMENT),
            source_id=request.source_id,
            principal_id=request.principal_id,
            purpose=request.purpose,
            scope=request.scope,
            media_types=request.media_types,
            policy_version=request.policy_version,
            request_fingerprint=request.fingerprint,
            max_items=request.max_items,
            max_bytes=request.max_bytes,
            accepted_at=WHEN,
        )
        self._world.enrollments.append(enrollment)
        self._world.keys[request.idempotency_key] = request.fingerprint
        return Acceptance(enrollment=enrollment, created=True)


class _Operations(OperationQueue):
    def __init__(self, world: World) -> None:
        self._world = world

    def enqueue(self, enrollment_id: str) -> str:
        self._world.fail("enqueue")
        operation_id = issue_identifier(IdKind.OPERATION)
        self._world.jobs[operation_id] = (enrollment_id, SourceStatusState.QUEUED)
        return operation_id

    def operation(self, operation_id: str) -> Operation | None:
        self._world.fail("operation")
        found = self._world.jobs.get(operation_id)
        if found is None:
            return None
        enrollment_id, state = found
        return Operation(operation_id=operation_id, enrollment_id=enrollment_id, state=state)


class _Knowledge(KnowledgeRepository):
    def __init__(self, world: World) -> None:
        self._world = world

    def coverage(
        self,
        enrollment_id: str,
        *,
        observed_at: datetime,
        eligible: int | None,
        queued: int = 0,
    ) -> CoverageCounts:
        self._world.fail("coverage")
        outcomes = self._world.outcomes.get(enrollment_id, {})
        processed = sum(1 for s in outcomes.values() if s is ExtractionStatus.EXTRACTED)
        quarantined = sum(1 for s in outcomes.values() if s is ExtractionStatus.QUARANTINED)
        unsupported = sum(1 for s in outcomes.values() if s is ExtractionStatus.UNSUPPORTED)
        total = processed + quarantined + unsupported + queued if eligible is None else eligible
        return CoverageCounts(
            observed_at=observed_at,
            enrollment_id=enrollment_id,
            eligible=total,
            queued=queued,
            processed=processed,
            quarantined=quarantined,
            unsupported=unsupported,
            limitations=self._world.limitations.get(enrollment_id, ()),
        )

    def limitations(self, enrollment_id: str) -> tuple[AggregateLimitation, ...]:
        self._world.fail("limitations")
        return self._world.limitations.get(enrollment_id, ())

    def outcome_for_object(
        self, *, enrollment_id: str, source_object_id: str
    ) -> ExtractionStatus | None:
        self._world.fail("outcome_for_object")
        return self._world.outcomes.get(enrollment_id, {}).get(source_object_id)

    def search(self, request: SearchRequest, *, now: datetime) -> SearchOutcome:
        self._world.fail("search")
        outcome = self._world.searches.get(request.enrollment_id)
        if outcome is None:
            raise KeyError("this test did not stage a search result")
        return outcome

    def read(self, knowledge_id: str, *, enrollment_id: str) -> KnowledgeRecord | None:
        self._world.fail("read")
        return self._world.records.get((enrollment_id, knowledge_id))


class _Audit(AuditSink):
    """The audit port, over a `World`.

    `World.failures["record"]` makes it refuse, which is how the fail-closed rule
    of `module-boundaries.md` section 5.6 becomes a FAST assertion. What this
    cannot show is durability: `World.audit` is a plain list and nothing here
    undoes an append, so an event "survives" a rollback whatever the design is.
    That claim belongs to `tests/schema/test_audit_durability.py`, against a
    server that can actually roll one back.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def record(self, event: AuditEvent) -> None:
        self._world.fail("record")
        self._world.audit.append(event)


class RecordingAudit(AuditSink):
    """An audit sink that keeps its events, for a test to read.

    Separate from `_Audit` because the real unit of work takes a sink as a
    constructor argument and has no `World` to write into. There is no durable
    audit store in this build, so this is what the `database` tier composes with.
    """

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class FakeUnitOfWork(UnitOfWork):
    """One transaction over a `World`, counting how it ended."""

    def __init__(self, world: World) -> None:
        self._world = world
        self._open = False

    def __enter__(self) -> UnitOfWork:
        self._open = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._open = False
        if exc is None:
            self._world.commits += 1
        else:
            self._world.rollbacks += 1

    @property
    def sources(self) -> SourceRepository:
        return _Sources(self._world)

    @property
    def enrollments(self) -> EnrollmentRepository:
        return _Enrollments(self._world)

    @property
    def operations(self) -> OperationQueue:
        return _Operations(self._world)

    @property
    def knowledge(self) -> KnowledgeRepository:
        return _Knowledge(self._world)

    @property
    def audit(self) -> AuditSink:
        return _Audit(self._world)


class RecordingProvider(SourceProvider):
    """A real fixture provider that remembers which of its methods were called.

    The delegation is explicit rather than a `__getattr__` proxy, so the set of
    methods that exist here is the set the port declares — which is the point:
    a mutating call cannot be recorded because there is nothing to call.
    """

    def __init__(self, inner: SourceProvider) -> None:
        self._inner = inner
        self.calls: list[str] = []

    @property
    def source_id(self) -> str:
        return self._inner.source_id

    def list_children(self, parent_object_id: str | None = None) -> Iterator[SourceObject]:
        self.calls.append("list_children")
        return self._inner.list_children(parent_object_id)

    def metadata(self, source_object_id: str) -> SourceObject:
        self.calls.append("metadata")
        return self._inner.metadata(source_object_id)

    def fetch(self, source_object_id: str, *, max_bytes: int) -> SourceObjectContent:
        self.calls.append("fetch")
        return self._inner.fetch(source_object_id, max_bytes=max_bytes)


class FakeProviders(SourceProviders):
    """The lookup from a source identity to the adapter serving it."""

    def __init__(self, providers: dict[str, SourceProvider] | None = None) -> None:
        self.providers: dict[str, SourceProvider] = providers or {}

    def for_source(self, source_id: str) -> SourceProvider | None:
        return self.providers.get(source_id)


def operator(principal_id: str | None = None) -> Principal:
    """An authenticated operator: the only principal this build has."""
    return Principal(
        principal_id=principal_id or issue_identifier(IdKind.PRINCIPAL),
        kind=PrincipalKind.OPERATOR,
        authenticated=True,
    )


def metadata_for(capability: Capability, purpose: Purpose, principal: Principal) -> RequestMetadata:
    """The common request metadata a transport would have parsed."""
    return RequestMetadata(
        request_id=f"req-{capability.value}",
        capability=capability,
        purpose=purpose,
        principal_id=principal.principal_id,
        requested_at=WHEN,
    )


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    """A small synthetic tree: two readable documents, one gated PDF, one folder."""
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "notes.md").write_bytes(b"# Notes\n\nQuarterly revenue review for the north.\n")
    (root / "list.txt").write_bytes(b"pallets, docks, weekday assignments\n")
    (root / "statement.pdf").write_bytes(b"%PDF-1.4\nnot really a pdf\n")
    (root / "folder").mkdir()
    (root / "folder" / "inner.md").write_bytes(b"# Inner\n\nnested note\n")
    return root


def build_provider(root: Path, source_id: str) -> RecordingProvider:
    """A recording provider over a real fixture tree."""
    return RecordingProvider(FixtureSourceProvider(root, source_id))


class Scene:
    """One configured source, one real provider over it, and one enrollment.

    The four fixture entries are looked up by kind and media type rather than by
    name, because a name is exactly what the port refuses to disclose. The
    provider's call log is cleared after the setup listing, so a test's
    assertions are about what the *capability* did.
    """

    def __init__(self, world: World, root: Path) -> None:
        self.world = world
        self.principal = operator()
        self.source = world.add_source()
        self.provider: RecordingProvider = build_provider(root, self.source.source_id)
        children = {
            (child.kind, child.media_type): child for child in self.provider.list_children()
        }
        self.provider.calls.clear()
        self.folder = children[(ObjectKind.CONTAINER, None)]
        self.markdown = children[(ObjectKind.FILE, "text/markdown")]
        self.plain = children[(ObjectKind.FILE, "text/plain")]
        self.pdf = children[(ObjectKind.FILE, "application/pdf")]
        self.enrollment = world.add_enrollment(
            source_id=self.source.source_id,
            principal_id=self.principal.principal_id,
            object_ids=(
                self.folder.source_object_id,
                self.markdown.source_object_id,
                self.plain.source_object_id,
                self.pdf.source_object_id,
            ),
        )
        self.providers = FakeProviders({self.source.source_id: self.provider})


def build_service(
    world: World, providers: FakeProviders, limits: EffectiveLimits = DEFAULT_LIMITS
) -> ApplicationService:
    """The service under test, with a fixed clock and in-memory repositories."""
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        providers=providers,
        limits=limits,
        clock=lambda: WHEN,
    )


def staged_record(scene: Scene, *, text: str) -> KnowledgeRecord:
    """One stored record inside `scene`'s grant, so `knowledge.read` has an answer.

    Beside `staged_search` because it is the same kind of thing: what a
    persistence port would have returned, staged so a use case can be driven
    without a database. `text` is the caller's, because a test about redaction
    needs to plant its own marker in it.
    """
    record = KnowledgeRecord(
        knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        enrollment_id=scene.enrollment.enrollment_id,
        media_type="text/markdown",
        text=text,
        is_truncated=False,
        provenance=Provenance(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
            version_id=scene.markdown.version_id,
            extractor="my_pa.text",
            extractor_version="1",
            observed_at=WHEN,
            processed_at=WHEN,
        ),
    )
    scene.world.records[(scene.enrollment.enrollment_id, record.knowledge_id)] = record
    return record


def staged_search(scene: Scene) -> SearchOutcome:
    """A page the knowledge port hands back, with its own assembled disclosure.

    Stands in for what `persistence.search` returns. The application is required
    to pass this disclosure through unchanged, because it was built from the
    coverage of the rows one statement snapshot saw and rebuilding it would
    replace a consistent answer with a plausible one.
    """
    match = SearchMatch(
        knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        label="Markdown document",
        snippet="quarterly revenue review",
        rank=RankCategory.STRONG,
        source_id=scene.source.source_id,
        source_object_id=scene.markdown.source_object_id,
        version_id=scene.markdown.version_id,
    )
    disclosure = Disclosure(
        scope=Scope(
            source_ids=(scene.source.source_id,),
            enrollment_ids=(scene.enrollment.enrollment_id,),
        ),
        coverage=Coverage(state=CoverageState.PROCESSED, eligible=1, processed=1),
        freshness=Freshness(observed_at=WHEN, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=("lexical_index",)),
        classification=Classification.SYNTHETIC_TEST,
    )
    return SearchOutcome(matches=(match,), disclosure=disclosure)


@pytest.fixture
def scene(world: World, fixture_root: Path) -> Scene:
    return Scene(world, fixture_root)
