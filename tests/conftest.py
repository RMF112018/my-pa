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

import hashlib
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final

import pytest

from my_pa.application.commands import CreateManagedDocumentCommand
from my_pa.application.commitments import CommitmentManagementService
from my_pa.application.intelligence import InMemoryIntelligenceStore
from my_pa.application.managed_documents import ManagedDocumentService
from my_pa.application.service import ApplicationService
from my_pa.application.tasks import TaskManagementService
from my_pa.contracts.ports import (
    Acceptance,
    AuditSink,
    AuthoringConflictError,
    AuthoringReceipt,
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureRepository,
    CaptureSearchMatch,
    CaptureSearchOutcome,
    CaptureSearchRequest,
    CaptureSummary,
    CommitmentManagementRepository,
    CommitmentManagementUnitOfWork,
    ContextPreferenceRepository,
    ContextRunRepository,
    ContinuityAuthoringRepository,
    EnrollmentRepository,
    EntitiesRepository,
    EntitySummary,
    GoodNotesProposalAdmission,
    GoodNotesProposalConflictError,
    GoodNotesSemanticRepository,
    KnowledgeRecord,
    KnowledgeRepository,
    ManagedAdmission,
    ManagedByteStore,
    ManagedDocumentRepository,
    ManagedWriteRequest,
    Operation,
    OperationQueue,
    PortError,
    PreferenceConflictError,
    ProjectRepository,
    PulseRepository,
    ReviewDecisionRequest,
    ReviewRepository,
    SearchOutcome,
    SituationRepository,
    SourceProviders,
    SourceRepository,
    TaskManagementRepository,
    TaskManagementUnitOfWork,
    UnitOfWork,
    UnknownScopeError,
    WorkCursorError,
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
from my_pa.domain.capture.errors import CaptureConflictError
from my_pa.domain.capture.pipeline import ProcessingState
from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.capture.reveal import (
    EvidenceGap,
    EvidenceState,
    Reveal,
    RevealedAssertion,
    RevealedProposal,
    RevealedSpan,
    RevealedVersion,
    RevealSubjectKind,
)
from my_pa.domain.capture.review import (
    Disposition,
    ReviewCase,
    ReviewConflictError,
    ReviewDecision,
    ReviewNotFoundError,
    ReviewUnsupportedError,
)
from my_pa.domain.capture.submission import CaptureReceipt
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, parse_identifier, validate_identifier
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.common.time import utc_now
from my_pa.domain.context.preference import (
    ContextPreferenceAction,
    ContextPreferenceAdmission,
    ContextPreferenceCurrent,
    ContextPreferenceEvent,
    preference_class_for,
)
from my_pa.domain.context.run import ContextRunRecord
from my_pa.domain.documents.managed import (
    DocumentState,
    LifecycleTransition,
    ManagedDocument,
    ManagedDocumentConflictError,
    ManagedDocumentReceipt,
    ManagedDocumentVersion,
    StaleExpectedVersionError,
)
from my_pa.domain.extraction.corpus import CorpusCoverage
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.goodnotes.models import (
    GoodNotesPageRaster,
    GoodNotesPageWork,
    GoodNotesSemanticProposal,
    issue_stable_id,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.domain.relationship.entity import (
    Assignment,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.governance import (
    EntityMergeRecord,
    EntityObservation,
    EntityProposal,
    EntityProposalState,
)
from my_pa.domain.relationship.normalization import (
    is_normalized_identifier,
    is_normalized_name,
)
from my_pa.domain.search.query import RankCategory, SearchMatch, SearchRequest
from my_pa.domain.situation.continuity import (
    ClosureEvidenceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityAcceptanceKind,
    ContinuityEvidenceState,
    TaskState,
)
from my_pa.domain.situation.continuity import Decision as ContinuityDecision
from my_pa.domain.situation.continuity import Task as ContinuityTask
from my_pa.domain.situation.pulse_derivation import FramedObligation, derive_pulse
from my_pa.domain.situation.situation import (
    Project,
    ProjectState,
    PulseItem,
    Situation,
    SituationState,
)
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
from my_pa.domain.task.bulk import TaskBulkOperation
from my_pa.domain.task.commitment import Commitment as CommitmentV2
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry
from my_pa.domain.task.history import TaskHistoryEntry, TaskMutationActor
from my_pa.domain.task.lifecycle import (
    TaskArchiveMode,
    TaskLifecycleState,
    TaskPriority,
    TaskWorkView,
)
from my_pa.domain.task.role import TaskRole
from my_pa.domain.task.task import Task as TaskV2
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider

# Operational scripts execute with this directory on sys.path. Architecture
# tests import them by file path and reproduce that same import environment.
OPS_NAS = str(Path(__file__).resolve().parents[1] / "ops/nas")
if OPS_NAS not in sys.path:
    sys.path.insert(0, OPS_NAS)

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


#: The two subject prefixes the evidence model can be walked back from, written
#: out here rather than imported from `infrastructure.persistence.reveal`: a fake
#: that read the implementation's own map would agree with it however that map
#: changed, which is the one thing a fake must not do.
_REVEALABLE: Final[dict[IdKind, RevealSubjectKind]] = {
    IdKind.CAPTURE: RevealSubjectKind.CAPTURE,
    IdKind.ASSERTION: RevealSubjectKind.ASSERTION,
}


def _revealable_kind(subject_id: str) -> RevealSubjectKind | None:
    """The subject kind this identifier names, or `None` for one not covered."""
    kind, _ = parse_identifier(subject_id)
    return _REVEALABLE.get(kind)


def _evidence_state(
    versions: tuple[RevealedVersion, ...],
    spans: tuple[RevealedSpan, ...],
    proposed: tuple[RevealedProposal, ...],
    accepted: tuple[RevealedAssertion, ...],
) -> tuple[EvidenceState, EvidenceGap | None]:
    """Which of the three answers the rows in hand support, in the same order.

    Evidence first, then the derivation gap, then `no_evidence` — restated here
    rather than imported for the reason `_REVEALABLE` is restated: a fake that
    called the implementation's own decision would agree with it by
    construction, and the ordering is exactly what the tests are about.
    """
    if spans or proposed or accepted:
        return EvidenceState.EVIDENCE, None
    if not all(version.derivation_is_complete for version in versions):
        return EvidenceState.UNAVAILABLE, EvidenceGap.DERIVATION_HAS_NOT_COMPLETED
    return EvidenceState.NO_EVIDENCE, None


@dataclass
class World:
    """Everything the fake repositories know, in one mutable place."""

    sources: dict[str, ConfiguredSource] = field(default_factory=dict)
    objects: dict[str, str] = field(default_factory=dict)
    enrollments: list[Enrollment] = field(default_factory=list)
    #: The enumerated object set of each enrollment, which is what
    #: `record_scope` writes and what `coverage`'s denominator counts. Empty for
    #: an enrollment nothing enumerated, which the real writer refuses to create.
    scopes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: The adapters `UnitOfWork.providers` answers with. Held here rather than
    #: on the service, because the real lookup is bound to the transaction.
    providers: SourceProviders = field(default_factory=lambda: FakeProviders())
    jobs: dict[str, tuple[str, SourceStatusState]] = field(default_factory=dict)
    outcomes: dict[str, dict[str, ExtractionStatus]] = field(default_factory=dict)
    limitations: dict[str, tuple[AggregateLimitation, ...]] = field(default_factory=dict)
    records: dict[tuple[str, str], KnowledgeRecord] = field(default_factory=dict)
    searches: dict[str, SearchOutcome] = field(default_factory=dict)
    #: Fingerprints of accepted enrollment requests, by idempotency key, so the
    #: fake can tell a retry from a conflict the way the unique constraint does.
    keys: dict[str, str] = field(default_factory=dict)
    #: The capture plane. `captures` is identity only — no current-version
    #: pointer and no lifecycle column, because the table has neither — and the
    #: current version is derived from `capture_versions` exactly as the writer
    #: derives it. `capture_keys` is the fake's stand-in for the unique index on
    #: `capture_submissions (principal_id, idempotency_key)` — per-principal
    #: since `PKL-MYPA-D-WP03-001`, so the same key held by two principals is two
    #: independent admissions and never a replay; a fake that decided that some
    #: other way would let a test prove a behaviour the constraint does not give.
    captures: dict[str, tuple[str, datetime]] = field(default_factory=dict)
    capture_versions: list[CaptureVersion] = field(default_factory=list)
    capture_receipts: dict[str, CaptureReceipt] = field(default_factory=dict)
    capture_keys: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    #: Metadata-only synthetic evidence authority used by Work mutation tests.
    #: Values are partitioned exactly like the production metadata query.
    work_evidence_refs: set[tuple[str, str]] = field(default_factory=set)
    #: Every admission request the store was *asked* to perform, in order, whether
    #: it was created, replayed, or refused. Recorded rather than derived from the
    #: rows above because two claims need the request itself: which transport the
    #: composition root vouched for (WP-10 records it on the submission), and
    #: whether a refused transport request reached the store at all — a question
    #: "no version was written" cannot answer, since a replay writes none either.
    capture_admissions: list[CaptureAdmissionRequest] = field(default_factory=list)
    #: The evidence plane, as the three collections a reveal traverses. Keyed by
    #: `version_id` because that is what the rows are keyed by: a span is
    #: measured against a version, a proposal is derived from one, and an
    #: assertion is promoted from a proposal on one. `derivation_states` is the
    #: `capture_stage_results` row for the proposal-persisting stage, absent when
    #: that stage has not run — which is the distinction the fake exists to make
    #: reachable, since "no evidence" and "the derivation has not finished" are
    #: the same empty collections and different answers.
    capture_spans: dict[str, tuple[RevealedSpan, ...]] = field(default_factory=dict)
    capture_proposals: dict[str, tuple[RevealedProposal, ...]] = field(default_factory=dict)
    capture_assertions: dict[str, tuple[RevealedAssertion, ...]] = field(default_factory=dict)
    derivation_states: dict[str, ProcessingState] = field(default_factory=dict)
    review_cases: list[ReviewCase] = field(default_factory=list)
    review_decisions: list[ReviewDecision] = field(default_factory=list)
    #: The managed-document plane (WP-27, reachable behind a capability seat since
    #: WP-28). Flat lists for the reason the continuity ones are: this fake's only
    #: job is the partition predicate and the version chain, and a list a filter
    #: runs over is the clearest place to see one missing. `managed_keys` stands
    #: in for the unique index on `managed_document_submissions
    #: (owner_principal_id, idempotency_key)` — per-Principal, so the same key
    #: held by two Principals is two independent admissions and never a replay.
    #:
    #: **What this fake cannot prove, stated where it is built.** There is no
    #: `BEFORE UPDATE OR DELETE` trigger on a Python list, so immutability is a
    #: property of this class not writing and never of the storage; and there is
    #: no unique constraint, so two concurrent writers producing one version is
    #: not demonstrable here. Both claims belong to `tests/database`, against a
    #: server that actually refuses.
    managed_documents: list[ManagedDocument] = field(default_factory=list)
    managed_versions: list[ManagedDocumentVersion] = field(default_factory=list)
    managed_keys: dict[tuple[str, str], tuple[str, ManagedDocumentReceipt]] = field(
        default_factory=dict
    )
    managed_states: dict[str, DocumentState] = field(default_factory=dict)
    #: Where the managed bytes are. On the `World` rather than on the service so
    #: that a test staging a document and the service reading one are looking at
    #: the same objects, and so a deep copy of the world (which is how the parity
    #: suite gives each transport its own) copies the bytes with the rows.
    managed_store: ManagedByteStore = field(default_factory=lambda: _ManagedBytes())
    #: The continuity plane (WP-11). Held as flat lists because the fake's whole
    #: job is the partition predicate, and a list a filter runs over is the
    #: clearest place to see one missing. `commitments`, `continuity_tasks` and
    #: `continuity_decisions` feed the Pulse *derivation*, which the fake runs
    #: through the same pure function the SQL repository runs — so a test cannot
    #: pass here against a derivation the store would not reproduce.
    situations: list[Situation] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    project_situations: list[tuple[str, str, str, str]] = field(default_factory=list)
    commitments: list[Commitment] = field(default_factory=list)
    continuity_tasks: list[ContinuityTask] = field(default_factory=list)
    continuity_decisions: list[ContinuityDecision] = field(default_factory=list)
    authoring_keys: dict[tuple[str, str], AuthoringReceipt] = field(default_factory=dict)
    framed_obligations: list[FramedObligation] = field(default_factory=list)
    #: The WP-TM-01/02 task-management plane's own rows (WP-TM-03 reads them).
    #: Named `tasks_v2`/`task_history_v2` rather than `tasks`/`task_history`,
    #: which would collide with nothing declared on `World` today but would
    #: read as though it were the same plane `continuity_tasks` above already
    #: names — it is not: `domain.task.task.Task` is the richer per-task model
    #: WP-TM-01's own module docstring describes as growing deliberately apart
    #: from `situation.continuity.Task`'s two-state shape, over the same
    #: `knowledge.tasks` row but reached through a different repository. Flat
    #: lists for the same reason every other plane on `World` is one: the
    #: fake's whole job is the partition predicate, and a list a filter runs
    #: over is the clearest place to see one missing.
    tasks_v2: list[TaskV2] = field(default_factory=list)
    task_history_v2: list[TaskHistoryEntry] = field(default_factory=list)
    task_bulk_operations: dict[tuple[str, str], TaskBulkOperation] = field(default_factory=dict)
    commitments_v2: list[CommitmentV2] = field(default_factory=list)
    commitment_history_v2: list[CommitmentHistoryEntry] = field(default_factory=list)
    dismissed_pulse_ids: set[str] = field(default_factory=set)
    audit: list[AuditEvent] = field(default_factory=list)
    #: Insert-only context-run metadata. The fake cannot prove the server
    #: trigger; that belongs to the schema tier. What it can prove is that the
    #: application wrote identifiers and digests and never the query or excerpt.
    context_runs: list[ContextRunRecord] = field(default_factory=list)
    preference_events: list[ContextPreferenceEvent] = field(default_factory=list)
    preference_current: dict[tuple[str, str, str], ContextPreferenceCurrent] = field(
        default_factory=dict
    )
    preference_keys: dict[tuple[str, str], str] = field(default_factory=dict)
    goodnotes_work: dict[tuple[str, str, str], GoodNotesPageWork] = field(default_factory=dict)
    goodnotes_proposals: dict[tuple[str, str], GoodNotesSemanticProposal] = field(
        default_factory=dict
    )
    goodnotes_rasters: dict[tuple[str, str], GoodNotesPageRaster] = field(default_factory=dict)
    intelligence: InMemoryIntelligenceStore = field(default_factory=InMemoryIntelligenceStore)
    #: The relationship-intelligence entity plane. Flat lists for the reason
    #: every other plane on `World` is one: the fake's whole job is the
    #: partition predicate, and a list a filter runs over is the clearest place
    #: to see one missing.
    #:
    #: **What this fake cannot prove.** There is no CHECK constraint on a
    #: Python list, so the closed-set, effective-dating, and redirect
    #: invariants are proved by the domain dataclasses here and by the server
    #: in `tests/database` — never by this class. What it can prove is that a
    #: read filters by Principal first and that a write refuses an entity
    #: reference the acting Principal does not hold, which is the cross-
    #: partition false join the plane exists to avoid.
    entities: list[Entity] = field(default_factory=list)
    entity_identifiers: list[ExternalIdentifier] = field(default_factory=list)
    entity_aliases: list[EntityAlias] = field(default_factory=list)
    entity_observations: list[EntityObservation] = field(default_factory=list)
    entity_proposals: list[EntityProposal] = field(default_factory=list)
    entity_merges: list[EntityMergeRecord] = field(default_factory=list)
    entity_assignments: list[Assignment] = field(default_factory=list)
    entity_relationships: list[EntityRelationship] = field(default_factory=list)
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
        # An accepted enrollment holds an enumerated set, because `record_scope`
        # refuses an empty one and its refusal rolls the acceptance back. A named
        # selector enumerates to what it named; a root selector's set is whatever
        # the test walking it recorded, and `scope_of` is how a test states one.
        self.scopes[enrollment.enrollment_id] = object_ids
        return enrollment

    def scope_of(self, enrollment_id: str, source_object_ids: tuple[str, ...]) -> None:
        """State the enumerated object set of an already-added enrollment.

        For a root selector, whose set is what the walk found rather than what
        the request named. Without it the fake reports `eligible == 0`, which is
        the state the real writer refuses to create.
        """
        self.scopes[enrollment_id] = source_object_ids

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

    def record_scope(self, enrollment_id: str, source_object_ids: Iterable[str]) -> int:
        """Record the enumerated set, refusing an empty one as the writer does.

        The refusal is the fake's, not decoration: `persistence.enrollment`
        raises `ValueError` for an empty set so that an unmeasurable enrollment
        rolls back rather than existing with a zero denominator, and a fake that
        accepted one would let a test prove a state the store cannot hold.
        """
        self._world.fail("record_scope")
        wanted = tuple(dict.fromkeys(source_object_ids))
        if not wanted:
            raise ValueError("an enrollment authorizes at least one object")
        held = self._world.scopes.get(enrollment_id, ())
        self._world.scopes[enrollment_id] = tuple(dict.fromkeys((*held, *wanted)))
        return len(self._world.scopes[enrollment_id])


class _Operations(OperationQueue):
    def __init__(self, world: World) -> None:
        self._world = world

    def enqueue(self, enrollment_id: str) -> str:
        self._world.fail("enqueue")
        operation_id = issue_identifier(IdKind.OPERATION)
        self._world.jobs[operation_id] = (enrollment_id, SourceStatusState.QUEUED)
        return operation_id

    def operation(self, operation_id: str, *, principal_id: str) -> Operation | None:
        self._world.fail("operation")
        found = self._world.jobs.get(operation_id)
        if found is None:
            return None
        enrollment_id, state = found
        # The queue is partitioned by Principal (WP-04), and the fake derives
        # that partition the way the schema does — transitively, through the
        # enrollment the job is about — rather than storing a second copy of it.
        # A job belonging to another Principal is `None` here for the same
        # reason the real statement's partition predicate matches no row, and it
        # is the same `None` an unknown operation gives.
        owner = next((e for e in self._world.enrollments if e.enrollment_id == enrollment_id), None)
        if owner is None or owner.principal_id != principal_id:
            return None
        return Operation(operation_id=operation_id, enrollment_id=enrollment_id, state=state)


class _Knowledge(KnowledgeRepository):
    def __init__(self, world: World) -> None:
        self._world = world

    def coverage(
        self,
        enrollment_id: str,
        *,
        observed_at: datetime,
        queued: int = 0,
    ) -> CoverageCounts:
        """Count the outcomes, over the denominator the enumerated set gives.

        `eligible` is `len(World.scopes[enrollment_id])`, which is what
        `coverage_for` reads out of `knowledge.enrollment_objects` rather than
        anything a caller states — the parameter is gone from the port. Only
        outcomes for objects in that set are counted, because
        `authorized_object` is membership of exactly those rows, so a test that
        records an outcome for an object outside the scope sees it excluded here
        for the same reason the database would exclude it.
        """
        self._world.fail("coverage")
        scope = self._world.scopes.get(enrollment_id, ())
        outcomes = {
            object_id: status
            for object_id, status in self._world.outcomes.get(enrollment_id, {}).items()
            if object_id in scope
        }
        processed = sum(1 for s in outcomes.values() if s is ExtractionStatus.EXTRACTED)
        quarantined = sum(1 for s in outcomes.values() if s is ExtractionStatus.QUARANTINED)
        unsupported = sum(1 for s in outcomes.values() if s is ExtractionStatus.UNSUPPORTED)
        return CoverageCounts(
            observed_at=observed_at,
            enrollment_id=enrollment_id,
            eligible=len(scope),
            queued=queued,
            processed=processed,
            quarantined=quarantined,
            unsupported=unsupported,
            limitations=self._world.limitations.get(enrollment_id, ()),
        )

    def corpus(self, principal_id: str, *, observed_at: datetime) -> CorpusCoverage:
        """Compose this Principal's stated coverages, and count what none of them reach.

        The members come from `self.coverage`, not from a second walk of the
        world, for the reason the SQL repository composes `coverage_for`: a fake
        that computed a corpus its own way could let a test pass against
        arithmetic the store would not reproduce.

        Two honest differences from the store, stated rather than glossed. The
        world's `objects` carry no kind, so `ENUMERABLE_KINDS` has nothing to
        filter here — a container is not a thing this fake can hold. And
        `objects_awaiting_an_outcome` counts distinct object identifiers across
        every held enrollment, which is exactly what the `count(distinct …)` in
        `corpus_coverage` counts.
        """
        self._world.fail("corpus")
        held = tuple(
            sorted(
                enrollment.enrollment_id
                for enrollment in self._world.enrollments
                if enrollment.principal_id == principal_id
            )
        )
        if not held:
            return CorpusCoverage(observed_at=observed_at, principal_id=principal_id)
        sources = {
            enrollment.source_id
            for enrollment in self._world.enrollments
            if enrollment.principal_id == principal_id
        }
        in_sources = {
            object_id
            for object_id, source_id in self._world.objects.items()
            if source_id in sources
        }
        enumerated = {
            object_id for enrollment in held for object_id in self._world.scopes.get(enrollment, ())
        }
        awaiting = {
            object_id
            for enrollment in held
            for object_id in self._world.scopes.get(enrollment, ())
            if self._world.outcomes.get(enrollment, {}).get(object_id) is None
        }
        return CorpusCoverage(
            observed_at=observed_at,
            principal_id=principal_id,
            enrollments=tuple(
                self.coverage(enrollment, observed_at=observed_at) for enrollment in held
            ),
            held_sources=len(sources),
            objects_in_held_sources=len(in_sources),
            objects_outside_every_enrollment=len(in_sources - enumerated),
            objects_awaiting_an_outcome=len(awaiting),
        )

    def scope_beyond_enrollment(self, principal_id: str, *, enrollment_id: str) -> bool:
        """Whether this Principal holds scope the named enrollment does not cover.

        The store's two conditions, reproduced rather than approximated: another
        enrollment of the same Principal, or an object of a held source that no
        enrollment of theirs enumerates.
        """
        self._world.fail("scope_beyond_enrollment")
        mine = [e for e in self._world.enrollments if e.principal_id == principal_id]
        if any(e.enrollment_id != enrollment_id for e in mine):
            return True
        enumerated = {
            object_id
            for enrollment in mine
            for object_id in self._world.scopes.get(enrollment.enrollment_id, ())
        }
        sources = {e.source_id for e in mine}
        return any(
            object_id not in enumerated
            for object_id, source_id in self._world.objects.items()
            if source_id in sources
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


class _Captures(CaptureRepository):
    """The capture plane, over a `World`.

    Three methods, and no update or delete — which is not restraint but the port:
    there is no such method to implement. What this fake *cannot* prove is that a
    stored version is immutable against a writer that does not go through the
    port, because a Python list has no trigger. That claim belongs to the
    `database` tier, against a server that actually refuses the `UPDATE`.

    The idempotency rule is reproduced rather than approximated: a key already
    held by *this principal* with the same payload digest returns the stored
    receipt and creates nothing, and a key so held with a different digest
    raises. Those are the two answers the unique index on
    `capture_submissions (principal_id, idempotency_key)` produces
    (`PKL-MYPA-D-WP03-001`), so a test about `QC-AC-031`/`QC-AC-032` at this
    tier is about the same rule the store enforces. Every read is partitioned
    by the caller's `principal_id` the way `partition_criterion` partitions the
    store's, so a foreign capture is indistinguishable from an absent one here
    too.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def admit(self, request: CaptureAdmissionRequest, *, principal_id: str) -> CaptureAdmission:
        self._world.fail("admit")
        self._world.capture_admissions.append(request)
        if request.principal_id != principal_id:
            # The same refusal the store makes: admission is bound to the
            # authenticated principal, never to one the payload carries
            # (MU-AC-02).
            raise CallerSuppliedPrincipalError("principal_id")
        held = self._world.capture_keys.get((principal_id, request.idempotency_key))
        if held is not None:
            digest, receipt_id = held
            if digest != request.payload_digest:
                raise CaptureConflictError("the idempotency key is bound to different content")
            return CaptureAdmission(receipt=self._world.capture_receipts[receipt_id], created=False)

        if request.capture_id is None:
            capture_id = issue_identifier(IdKind.CAPTURE)
            self._world.captures[capture_id] = (request.principal_id, request.accepted_at)
            number, supersedes = 1, None
        else:
            capture_id = request.capture_id
            head = self._head(capture_id, principal_id=principal_id)
            if head is None:
                raise UnknownScopeError("the request names no stored capture")
            number, supersedes = head.version_number + 1, head.version_id

        version = CaptureVersion(
            version_id=issue_identifier(IdKind.CAPTURE_VERSION),
            capture_id=capture_id,
            version_number=number,
            supersedes_version_id=supersedes,
            content=request.content,
            owner_principal_id=request.principal_id,
            classification=request.classification,
            processing_policy=request.processing_policy,
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            audit_id=request.audit_id,
            client_created_at=request.client_created_at,
            server_received_at=request.server_received_at,
            occurred_at=request.occurred_at,
            accepted_at=request.accepted_at,
            # The store writes this from the server's own clock, which is a third
            # reading; here it is the accepted moment, because a fake has no
            # server clock to be different from. A test that needs the five to
            # differ needs the `database` tier.
            recorded_at=request.accepted_at,
        )
        self._world.capture_versions.append(version)
        receipt = CaptureReceipt(
            receipt_id=issue_identifier(IdKind.RECEIPT),
            capture_id=capture_id,
            version_id=version.version_id,
            version_number=number,
            idempotency_key=request.idempotency_key,
            content_sha256=request.content.digest,
            issued_at=request.accepted_at,
        )
        self._world.capture_receipts[receipt.receipt_id] = receipt
        self._world.capture_keys[(principal_id, request.idempotency_key)] = (
            request.payload_digest,
            receipt.receipt_id,
        )
        return CaptureAdmission(receipt=receipt, created=True)

    def version(
        self, capture_id: str, *, version_id: str | None = None, principal_id: str
    ) -> CaptureVersion | None:
        self._world.fail("capture_version")
        if version_id is None:
            return self._head(capture_id, principal_id=principal_id)
        return next(
            (
                version
                for version in self._world.capture_versions
                if version.capture_id == capture_id
                and version.version_id == version_id
                and version.owner_principal_id == principal_id
            ),
            None,
        )

    def accepts_work_evidence_reference(self, reference: str, *, principal_id: str) -> bool:
        return (principal_id, reference) in self._world.work_evidence_refs

    def captures(self, *, limit: int, principal_id: str) -> tuple[CaptureSummary, ...]:
        self._world.fail("capture_page")
        summaries: list[CaptureSummary] = []
        for capture_id, (owner, created_at) in self._world.captures.items():
            if owner != principal_id:
                continue
            head = self._head(capture_id, principal_id=principal_id)
            if head is None:
                continue
            summaries.append(
                CaptureSummary(
                    capture_id=capture_id,
                    owner_principal_id=owner,
                    created_at=created_at,
                    version_count=sum(
                        1 for v in self._world.capture_versions if v.capture_id == capture_id
                    ),
                    latest_version_id=head.version_id,
                    latest_version_number=head.version_number,
                    latest_recorded_at=head.recorded_at,
                )
            )
        summaries.sort(key=lambda s: (s.created_at, s.capture_id), reverse=True)
        return tuple(summaries[:limit])

    def search(self, request: CaptureSearchRequest, *, principal_id: str) -> CaptureSearchOutcome:
        """Exact match over the versions this world holds.

        A whole-word containment test over the stored text, which is what the
        `simple` text-search configuration does at word granularity — no
        stemming and no stop-word removal, so `run` does not find `running` here
        either. What this fake **cannot** prove is that the server's plane
        behaves the same way: the configuration, the functional index, and the
        `strpos` confirmation are properties of PostgreSQL, and
        `tests/search_quality/test_capture_search.py` and
        `tests/search_quality/test_exact_confirmation_matrix.py` are where they
        are asserted against one — the second because the confirmation's
        agreement with the predicate is a per-query-form property that no
        example can stand in for. This exists so the application layer's
        limitation
        arithmetic and its no-content answer are provable on FAST.

        The scope is the same three conditions `capture_text_in_scope` applies:
        owned by the caller (`PKL-MYPA-D-WP03-001`), not superseded, and
        acknowledged by a receipt. Reproduced rather than approximated, for the
        reason the idempotency rule above is — and both counts below are taken
        over the caller's partition, exactly as `totals_statement` takes them,
        so the denominators cannot leak another principal's volume.
        """
        self._world.fail("capture_search")
        mine = [
            version
            for version in self._world.capture_versions
            if version.owner_principal_id == principal_id
        ]
        superseded = {
            version.supersedes_version_id
            for version in mine
            if version.supersedes_version_id is not None
        }
        acknowledged = {receipt.version_id for receipt in self._world.capture_receipts.values()}
        in_scope = [
            version
            for version in mine
            if version.version_id not in superseded and version.version_id in acknowledged
        ]
        terms = request.query.text.split()
        found = [
            version
            for version in in_scope
            if terms and all(term in version.content.text.lower().split() for term in terms)
        ]
        found.sort(key=lambda version: (version.recorded_at, version.version_id), reverse=True)
        return CaptureSearchOutcome(
            matches=tuple(
                CaptureSearchMatch(
                    capture_id=version.capture_id,
                    version_id=version.version_id,
                    version_number=version.version_number,
                    character_count=version.content.character_count,
                    recorded_at=version.recorded_at,
                )
                for version in found[: request.limit]
            ),
            searchable_versions=len(in_scope),
            stored_versions=len(mine),
            truncated=len(found) > request.limit,
        )

    def reveal(self, subject_id: str, *, principal_id: str) -> Reveal | None:
        """The evidence behind one subject, reproducing the rule and not the SQL.

        Three rules, each reproduced rather than approximated, because each is
        one this tier is meant to prove:

        * a subject kind outside the covered two is an `unavailable` reveal and
          never `None`, so "we do not cover that plane" cannot arrive as "no such
          thing";
        * a capture this principal does not own is `None`, the same value an
          absent one yields, so a foreign identifier maps nothing;
        * the state is decided from the rows in hand by the same three-way test
          the store's traversal applies — evidence first, then the derivation
          gap, and `no_evidence` only for a scope whose every version finished.

        What this fake **cannot** prove is that the real statements are scoped at
        the query rather than filtered afterwards. That claim is a property of
        the SQL and belongs to `tests/database/test_reveal_isolation.py`, against
        a server.
        """
        self._world.fail("reveal")
        kind = _revealable_kind(subject_id)
        if kind is None:
            return Reveal(
                subject_id=subject_id,
                subject_kind=None,
                state=EvidenceState.UNAVAILABLE,
                gap=EvidenceGap.SUBJECT_KIND_NOT_COVERED,
            )
        if kind is RevealSubjectKind.ASSERTION:
            return self._reveal_assertion(subject_id, principal_id=principal_id)
        owner = self._world.captures.get(subject_id, (None, None))[0]
        if owner != principal_id:
            return None
        versions = self._revealed_versions(subject_id, principal_id=principal_id)
        version_ids = [version.version_id for version in versions]
        spans = tuple(
            span
            for version_id in version_ids
            for span in self._world.capture_spans.get(version_id, ())
        )
        proposed = tuple(
            proposal
            for version_id in version_ids
            for proposal in self._world.capture_proposals.get(version_id, ())
        )
        accepted = tuple(
            assertion
            for version_id in version_ids
            for assertion in self._world.capture_assertions.get(version_id, ())
        )
        state, gap = _evidence_state(versions, spans, proposed, accepted)
        return Reveal(
            subject_id=subject_id,
            subject_kind=kind,
            state=state,
            gap=gap,
            capture_id=subject_id,
            versions=versions,
            spans=spans,
            proposed=proposed,
            accepted=accepted,
        )

    def _reveal_assertion(self, assertion_id: str, *, principal_id: str) -> Reveal | None:
        """One accepted record and what it rests on, inside the caller's partition."""
        for version in self._world.capture_versions:
            if version.owner_principal_id != principal_id:
                continue
            for assertion in self._world.capture_assertions.get(version.version_id, ()):
                if assertion.assertion_id != assertion_id:
                    continue
                cited = set(assertion.span_ids)
                versions = self._revealed_versions(version.capture_id, principal_id=principal_id)
                return Reveal(
                    subject_id=assertion_id,
                    subject_kind=RevealSubjectKind.ASSERTION,
                    state=EvidenceState.EVIDENCE,
                    capture_id=version.capture_id,
                    versions=tuple(
                        candidate
                        for candidate in versions
                        if candidate.version_id == version.version_id
                    ),
                    spans=tuple(
                        span
                        for span in self._world.capture_spans.get(version.version_id, ())
                        if span.span_id in cited
                    ),
                    proposed=tuple(
                        proposal
                        for proposal in self._world.capture_proposals.get(version.version_id, ())
                        if proposal.proposal_id == assertion.proposal_id
                    ),
                    accepted=(assertion,),
                )
        return None

    def _revealed_versions(
        self, capture_id: str, *, principal_id: str
    ) -> tuple[RevealedVersion, ...]:
        """The caller's own versions of one capture, with their derivation state."""
        mine = sorted(
            (
                version
                for version in self._world.capture_versions
                if version.capture_id == capture_id and version.owner_principal_id == principal_id
            ),
            key=lambda version: version.version_number,
        )
        latest = mine[-1].version_number if mine else None
        return tuple(
            RevealedVersion(
                version_id=version.version_id,
                capture_id=capture_id,
                version_number=version.version_number,
                is_current=version.version_number == latest,
                content_sha256=version.content.digest,
                recorded_at=version.recorded_at,
                derivation_state=self._world.derivation_states.get(version.version_id),
            )
            for version in mine
        )

    def _head(self, capture_id: str, *, principal_id: str) -> CaptureVersion | None:
        """The greatest version number the caller's capture holds, derived not stored.

        Scoped to the caller's partition, because this is what decides whether a
        revision finds a head to succeed: a foreign capture yields `None` here
        and therefore `UnknownScopeError` above, the same shape an absent
        capture yields (`PKL-MYPA-D-WP03-001`).
        """
        held = [
            v
            for v in self._world.capture_versions
            if v.capture_id == capture_id and v.owner_principal_id == principal_id
        ]
        return max(held, key=lambda v: v.version_number) if held else None


class _Reviews(ReviewRepository):
    def __init__(self, world: World) -> None:
        self._world = world

    def cases(self, *, limit: int, principal_id: str) -> tuple[ReviewCase, ...]:
        self._world.fail("review_cases")
        owned = {
            version.capture_id
            for version in self._world.capture_versions
            if version.owner_principal_id == principal_id
        }
        confined = [case for case in self._world.review_cases if case.capture_id in owned]
        return tuple(confined[:limit])

    def decide(self, request: ReviewDecisionRequest) -> ReviewDecision | None:
        self._world.fail("review_decide")
        case = next(
            (
                item
                for item in self._world.review_cases
                if item.review_case_id == request.review_case_id
            ),
            None,
        )
        if case is None:
            raise ReviewNotFoundError("the request names no stored review case")
        if any(
            decision.review_case_id == request.review_case_id
            and decision.disposition in {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}
            and decision.assertion_id is not None
            and decision.receipt_id is not None
            for decision in self._world.review_decisions
        ):
            raise ReviewConflictError("an accepted review case is terminal")
        current = sum(
            decision.review_case_id == request.review_case_id
            for decision in self._world.review_decisions
        )
        if current != request.expected_review_version:
            raise ReviewConflictError("the expected review version is stale")
        state = {
            "accept": ProposalState.ACCEPTED,
            "correct_and_accept": ProposalState.CORRECTED_ACCEPTED,
            "reject": ProposalState.REJECTED,
            "defer": ProposalState.DEFERRED,
            "mark_unresolved": ProposalState.UNRESOLVED,
        }.get(request.disposition.value)
        if state is None:
            raise ReviewUnsupportedError("the disposition has no route")
        accepted = state in {ProposalState.ACCEPTED, ProposalState.CORRECTED_ACCEPTED}
        decision = ReviewDecision(
            decision_id=issue_identifier(IdKind.REVIEW_DECISION),
            review_case_id=request.review_case_id,
            sequence=current + 1,
            disposition=request.disposition,
            principal_id=request.principal_id,
            correlation_id=request.correlation_id,
            audit_id=request.audit_id,
            decided_at=request.decided_at,
            proposal_state=state,
            assertion_id=issue_identifier(IdKind.ASSERTION) if accepted else None,
            receipt_id=issue_identifier(IdKind.RECEIPT) if accepted else None,
            normalized_value=request.corrected_value,
        )
        self._world.review_decisions.append(decision)
        index = self._world.review_cases.index(case)
        self._world.review_cases[index] = replace(
            case,
            proposal_state=state,
            review_version=decision.sequence,
            latest_disposition=request.disposition,
        )
        return decision


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


class _ContextRuns(ContextRunRepository):
    """Insert-only context-run metadata over a `World`."""

    def __init__(self, world: World) -> None:
        self._world = world

    def record(self, run: ContextRunRecord) -> None:
        self._world.fail("context_runs")
        self._world.context_runs.append(run)


class _ContextPreferences(ContextPreferenceRepository):
    """Append-only preference events and current projection over a `World`."""

    def __init__(self, world: World) -> None:
        self._world = world

    def current_for(self, principal_id: str) -> tuple[ContextPreferenceCurrent, ...]:
        self._world.fail("context_preferences")
        found = [
            row for key, row in self._world.preference_current.items() if key[0] == principal_id
        ]
        return tuple(sorted(found, key=lambda row: (row.target_id, row.preference_class.value)))

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
        created_at: object,
    ) -> ContextPreferenceAdmission:
        self._world.fail("context_preferences")
        held = self._world.preference_keys.get((principal_id, idempotency_key))
        if held is not None:
            prior = next(event for event in self._world.preference_events if event.event_id == held)
            if (
                prior.action.value != action
                or prior.target_id != target_id
                or prior.alias != alias
                or prior.source_id != source_id
            ):
                raise PreferenceConflictError("the idempotency key is bound to a different request")
            return ContextPreferenceAdmission(
                event=prior,
                current=self._current_for_target(principal_id, target_id),
                created=False,
            )
        event = ContextPreferenceEvent(
            event_id=issue_identifier(IdKind.CONTEXT_PREFERENCE_EVENT),
            principal_id=principal_id,
            action=ContextPreferenceAction(action),
            target_id=target_id,
            idempotency_key=idempotency_key,
            event_number=sum(
                1 for item in self._world.preference_events if item.principal_id == principal_id
            )
            + 1,
            created_at=created_at,  # type: ignore[arg-type]
            correlation_id=correlation_id,
            request_id=request_id,
            alias=alias,
            source_id=source_id,
            audit_id=audit_id,
        )
        self._world.preference_events.append(event)
        self._world.preference_keys[(principal_id, idempotency_key)] = event.event_id
        self._fold(event)
        return ContextPreferenceAdmission(
            event=event,
            current=self._current_for_target(principal_id, target_id),
            created=True,
        )

    def _current_for_target(
        self, principal_id: str, target_id: str
    ) -> tuple[ContextPreferenceCurrent, ...]:
        found = [
            row
            for (owner, target, _slot), row in self._world.preference_current.items()
            if owner == principal_id and target == target_id
        ]
        return tuple(sorted(found, key=lambda row: row.preference_class.value))

    def _fold(self, event: ContextPreferenceEvent) -> None:
        slot = preference_class_for(event.action)
        if event.action is ContextPreferenceAction.CLEAR or slot is None:
            for key in [
                key
                for key in self._world.preference_current
                if key[0] == event.principal_id and key[1] == event.target_id
            ]:
                del self._world.preference_current[key]
            return
        key = (event.principal_id, event.target_id, slot.value)
        if event.action in {
            ContextPreferenceAction.UNPIN,
            ContextPreferenceAction.REMOVE_ALIAS,
            ContextPreferenceAction.DEPREFER_SOURCE,
        }:
            self._world.preference_current.pop(key, None)
            return
        self._world.preference_current[key] = ContextPreferenceCurrent(
            principal_id=event.principal_id,
            target_id=event.target_id,
            preference_class=slot,
            action=event.action,
            event_id=event.event_id,
            alias=event.alias,
            source_id=event.source_id,
        )


class _GoodNotesSemantics(GoodNotesSemanticRepository):
    """Page-version work and insert-only proposal receipts over a `World`."""

    def __init__(self, world: World) -> None:
        self._world = world

    def page_work(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageWork | None:
        self._world.fail("goodnotes_semantics")
        return self._world.goodnotes_work.get((principal_id, run_id, page_version_id))

    def page_raster(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageRaster | None:
        self._world.fail("goodnotes_semantics")
        raster = self._world.goodnotes_rasters.get((principal_id, page_version_id))
        if raster is None or raster.run_id != run_id:
            return None
        return raster

    def submit_proposal(
        self,
        *,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        content_sha256: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        idempotency_key: str,
        request_fingerprint: str,
        payload_sha256: str,
        payload: dict[str, object],
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: object,
    ) -> GoodNotesProposalAdmission:
        del payload, correlation_id, request_id, audit_id
        self._world.fail("goodnotes_semantics")
        held = self._world.goodnotes_proposals.get((principal_id, idempotency_key))
        if held is not None:
            if held.request_fingerprint != request_fingerprint:
                raise GoodNotesProposalConflictError(
                    "the idempotency key is bound to a different request"
                )
            return GoodNotesProposalAdmission(
                proposal=replace(held, replayed=True),
                created=False,
            )
        proposal = GoodNotesSemanticProposal(
            proposal_id=issue_stable_id(
                "gnprp", principal_id, idempotency_key, request_fingerprint
            ),
            principal_id=principal_id,
            run_id=run_id,
            page_version_id=page_version_id,
            content_sha256=content_sha256,
            schema_version=schema_version,
            analyzer_name=analyzer_name,
            analyzer_version=analyzer_version,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            payload_sha256=payload_sha256,
            created_at=created_at,  # type: ignore[arg-type]
            replayed=False,
        )
        self._world.goodnotes_proposals[(principal_id, idempotency_key)] = proposal
        return GoodNotesProposalAdmission(proposal=proposal, created=True)


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


class _ManagedBytes(ManagedByteStore):
    """Managed version bytes in a dict, for the transports that need a plane.

    **Deliberately not a fake of containment.** `FilesystemManagedByteStore` is
    where a path is resolved, refused, and proved to lie under the managed root,
    and none of that is imitated here — there is no path in this class at all,
    which is the honest position for a dict: a fake that grew a `_root` attribute
    would let a containment test pass against something that never touched a
    filesystem. Containment is proved in `tests/architecture` structurally and in
    `tests/database` against the real store under a temporary directory.

    What this *does* preserve is the two behaviours the application depends on:
    bytes are written once — a second `put` for the same identifier raises, as
    `O_CREAT|O_EXCL` does — and a read of an unstored identifier raises rather
    than answering empty.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.manifest: bytes | None = None

    def put(self, version_id: str, content: bytes) -> None:
        if version_id in self.objects:
            raise FileExistsError("the managed object already exists")
        self.objects[version_id] = bytes(content)

    def read(self, version_id: str) -> bytes:
        stored = self.objects.get(version_id)
        if stored is None:
            raise FileNotFoundError("the managed object is not stored")
        return stored

    def has(self, version_id: str) -> bool:
        return version_id in self.objects

    def stored_version_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.objects))

    def unreadable_entries(self) -> tuple[str, ...]:
        return ()

    def put_manifest(self, content: bytes) -> None:
        self.manifest = bytes(content)

    def read_manifest(self) -> bytes:
        if self.manifest is None:
            raise FileNotFoundError("no manifest is stored")
        return self.manifest


class _ManagedDocuments(ManagedDocumentRepository):
    """The managed-document plane over a `World`, partition predicate written out.

    Every method takes `principal_id` and every one of them filters on it, in the
    same shape the SQL repository does: a document another Principal owns answers
    exactly what a document that does not exist answers, so no method here can be
    used to learn that an identifier names something.

    Written out rather than delegated to a helper for a reason WP-23 bought: a
    partition predicate factored into one place is a predicate one caller can
    forget to use, and this fake exists so a missing filter is visible.

    See `World`'s own comment for the two things a list cannot demonstrate —
    trigger-enforced immutability and a unique constraint under concurrency —
    both of which are proved in `tests/database` against a real server.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def admit(self, request: ManagedWriteRequest) -> ManagedAdmission:
        key = (request.principal_id, request.idempotency_key)
        bound = self._world.managed_keys.get(key)
        if bound is not None:
            digest, receipt = bound
            if digest != request.payload_digest:
                raise ManagedDocumentConflictError(
                    "the idempotency key is bound to a different request"
                )
            return ManagedAdmission(receipt=receipt, created=False)

        if request.document_id is None:
            document_id = issue_identifier(IdKind.MANAGED_DOCUMENT)
            previous: ManagedDocumentVersion | None = None
            number = 1
        else:
            document_id = request.document_id
            previous = self.version(document_id, principal_id=request.principal_id)
            if previous is None:
                raise UnknownScopeError("the request names no stored managed document")
            if previous.version_number != request.expected_version_number:
                raise StaleExpectedVersionError("the expected version is not this document's head")
            number = previous.version_number + 1

        version = ManagedDocumentVersion(
            version_id=request.version_id,
            document_id=document_id,
            version_number=number,
            supersedes_version_id=None if previous is None else previous.version_id,
            owner_principal_id=request.principal_id,
            title=request.title,
            media_type=request.media_type,
            content_sha256=request.content_sha256,
            byte_size=request.byte_size,
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            recorded_at=request.server_received_at,
        )
        self._world.managed_versions.append(version)
        if previous is None:
            self._world.managed_states[document_id] = DocumentState.ACTIVE
        receipt = ManagedDocumentReceipt(
            receipt_id=issue_identifier(IdKind.MANAGED_RECEIPT),
            document_id=document_id,
            version_id=version.version_id,
            version_number=version.version_number,
            idempotency_key=request.idempotency_key,
            content_sha256=request.content_sha256,
            byte_size=request.byte_size,
            issued_at=request.server_received_at,
            created=True,
        )
        self._world.managed_keys[key] = (request.payload_digest, receipt)
        return ManagedAdmission(receipt=receipt, created=True)

    def replay_for(
        self, idempotency_key: str, payload_digest: str, *, principal_id: str
    ) -> ManagedDocumentReceipt | None:
        bound = self._world.managed_keys.get((principal_id, idempotency_key))
        if bound is None:
            return None
        digest, receipt = bound
        if digest != payload_digest:
            raise ManagedDocumentConflictError(
                "the idempotency key is bound to a different request"
            )
        # `created=False`: a replay stored nothing new, and a caller retrying
        # after a lost response has to be able to tell.
        return replace(receipt, created=False)

    def _owned(self, document_id: str, principal_id: str) -> list[ManagedDocumentVersion]:
        return sorted(
            (
                row
                for row in self._world.managed_versions
                if row.document_id == document_id and row.owner_principal_id == principal_id
            ),
            key=lambda row: row.version_number,
        )

    def version(
        self, document_id: str, *, version_id: str | None = None, principal_id: str
    ) -> ManagedDocumentVersion | None:
        owned = self._owned(document_id, principal_id)
        if not owned:
            return None
        if version_id is None:
            return owned[-1]
        return next((row for row in owned if row.version_id == version_id), None)

    def versions(
        self, document_id: str, *, principal_id: str
    ) -> tuple[ManagedDocumentVersion, ...]:
        return tuple(self._owned(document_id, principal_id))

    def documents(
        self, *, limit: int, principal_id: str, include_archived: bool = False
    ) -> tuple[ManagedDocument, ...]:
        if limit < 1:
            raise ValueError("a page holds at least one managed document")
        found: list[ManagedDocument] = []
        for document_id in {
            row.document_id
            for row in self._world.managed_versions
            if row.owner_principal_id == principal_id
        }:
            owned = self._owned(document_id, principal_id)
            state = self._world.managed_states.get(document_id, DocumentState.ACTIVE)
            if state is DocumentState.ARCHIVED and not include_archived:
                continue
            head = owned[-1]
            found.append(
                ManagedDocument(
                    document_id=document_id,
                    owner_principal_id=principal_id,
                    state=state,
                    title=head.title,
                    media_type=head.media_type,
                    version_count=len(owned),
                    latest_version_id=head.version_id,
                    latest_version_number=head.version_number,
                    created_at=owned[0].recorded_at,
                    latest_recorded_at=head.recorded_at,
                )
            )
        found.sort(key=lambda row: (row.latest_recorded_at, row.document_id), reverse=True)
        return tuple(found[:limit])

    def state(self, document_id: str, *, principal_id: str) -> DocumentState | None:
        if not self._owned(document_id, principal_id):
            return None
        return self._world.managed_states.get(document_id, DocumentState.ACTIVE)

    def transition(
        self,
        document_id: str,
        *,
        transition: LifecycleTransition,
        principal_id: str,
        correlation_id: str,
    ) -> bool:
        current = self.state(document_id, principal_id=principal_id)
        if current is None:
            raise UnknownScopeError("the request names no stored managed document")
        wanted = (
            DocumentState.ARCHIVED
            if transition is LifecycleTransition.ARCHIVED
            else DocumentState.ACTIVE
        )
        self._world.managed_states[document_id] = wanted
        return current is not wanted

    def restore_version(self, version: ManagedDocumentVersion, *, principal_id: str) -> None:
        if version.owner_principal_id != principal_id:
            raise UnknownScopeError("the request names no stored managed document")
        if any(row.version_id == version.version_id for row in self._world.managed_versions):
            return
        self._world.managed_versions.append(version)
        self._world.managed_states.setdefault(version.document_id, DocumentState.ACTIVE)

    def known_version_identifiers(self) -> frozenset[str]:
        return frozenset(row.version_id for row in self._world.managed_versions)


class _TasksRead(TaskManagementRepository):
    """The WP-TM-03 read plane over `World.tasks_v2`/`task_history_v2`.

    Only the four read methods below are exercised through `FakeUnitOfWork`
    (WP-TM-03 wires `UnitOfWork.tasks` to reads only, the way WP-TM-04's own
    mutation wiring is deferred); the four write/lock methods
    `TaskManagementRepository` also declares are implemented here purely so
    this class remains a complete ABC, and raise if a test somehow reaches
    them — a signal that a test is exercising mutation through the wrong seam,
    since WP-TM-02's own `TaskManagementService`/`TaskManagementUnitOfWork`
    fakes (`tests/unit/test_task_management_service.py`) are what a mutation
    test should use instead.

    Every read method filters by `principal_id` first, exactly as
    `_ManagedDocuments` above filters by owner: a task belonging to another
    Principal is answered exactly as an absent one, never distinguished from
    "no such task at all".
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, task_id: str) -> TaskV2 | None:
        return self.get(principal_id, task_id)

    def insert_task(self, task: TaskV2) -> None:
        self._world.tasks_v2.append(task)

    def update_task(self, task: TaskV2) -> None:
        self._world.tasks_v2[:] = [
            task if existing.task_id == task.task_id else existing
            for existing in self._world.tasks_v2
        ]

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskHistoryEntry | None:
        return next(
            (
                entry
                for entry in self._world.task_history_v2
                if entry.principal_id == principal_id and entry.idempotency_key == idempotency_key
            ),
            None,
        )

    def insert_history(self, entry: TaskHistoryEntry) -> None:
        self._world.task_history_v2.append(entry)

    def find_bulk_by_preview_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskBulkOperation | None:
        return next(
            (
                operation
                for (owner, _), operation in self._world.task_bulk_operations.items()
                if owner == principal_id and operation.preview_idempotency_key == idempotency_key
            ),
            None,
        )

    def find_bulk_by_confirm_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskBulkOperation | None:
        return next(
            (
                operation
                for (owner, _), operation in self._world.task_bulk_operations.items()
                if owner == principal_id and operation.confirm_idempotency_key == idempotency_key
            ),
            None,
        )

    def get_bulk_for_update(
        self, principal_id: str, bulk_operation_id: str
    ) -> TaskBulkOperation | None:
        return self._world.task_bulk_operations.get((principal_id, bulk_operation_id))

    def insert_bulk(self, operation: TaskBulkOperation) -> None:
        self._world.task_bulk_operations[
            (
                operation.principal_id,
                operation.bulk_operation_id,
            )
        ] = operation

    def confirm_bulk(self, operation: TaskBulkOperation) -> None:
        self.insert_bulk(operation)

    def get(self, principal_id: str, task_id: str) -> TaskV2 | None:
        return next(
            (
                task
                for task in self._world.tasks_v2
                if task.principal_id == principal_id and task.task_id == task_id
            ),
            None,
        )

    def list_tasks(
        self,
        principal_id: str,
        *,
        lifecycle_state: TaskLifecycleState | None = None,
        priority: TaskPriority | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        after: str | None = None,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        limit: int,
    ) -> tuple[TaskV2, ...]:
        owned = [task for task in self._world.tasks_v2 if task.principal_id == principal_id]
        if lifecycle_state is not None:
            owned = [task for task in owned if task.lifecycle_state is lifecycle_state]
        if priority is not None:
            owned = [task for task in owned if task.priority is priority]
        if archive_mode is TaskArchiveMode.EXCLUDE:
            owned = [task for task in owned if task.archived_at is None]
        else:
            owned = [task for task in owned if task.archived_at is not None]

        def effective(task: TaskV2) -> datetime | None:
            due_or_scheduled = min(
                (value for value in (task.due_at, task.scheduled_at) if value), default=None
            )
            return max(
                (value for value in (due_or_scheduled, task.deferred_until) if value),
                default=None,
            )

        if work_view is TaskWorkView.TODAY:
            owned = [
                task
                for task in owned
                if task.lifecycle_state
                not in {TaskLifecycleState.COMPLETED, TaskLifecycleState.CANCELLED}
                and (moment := effective(task)) is not None
                and work_end is not None
                and moment < work_end
            ]
        elif work_view is TaskWorkView.UPCOMING:
            owned = [
                task
                for task in owned
                if task.lifecycle_state
                not in {TaskLifecycleState.COMPLETED, TaskLifecycleState.CANCELLED}
                and (moment := effective(task)) is not None
                and work_end is not None
                and moment >= work_end
            ]
        elif work_view is TaskWorkView.WAITING:
            owned = [task for task in owned if task.lifecycle_state is TaskLifecycleState.WAITING]
        elif work_view is TaskWorkView.BLOCKED:
            owned = [task for task in owned if task.lifecycle_state is TaskLifecycleState.BLOCKED]
        elif work_view is TaskWorkView.ALL_OPEN:
            owned = [
                task
                for task in owned
                if task.lifecycle_state
                in {
                    TaskLifecycleState.OPEN,
                    TaskLifecycleState.IN_PROGRESS,
                    TaskLifecycleState.WAITING,
                    TaskLifecycleState.BLOCKED,
                }
            ]
        elif work_view is TaskWorkView.COMPLETED:
            owned = [
                task
                for task in owned
                if task.lifecycle_state
                in {TaskLifecycleState.COMPLETED, TaskLifecycleState.CANCELLED}
            ]
        ordered = sorted(owned, key=lambda task: (task.created_at, task.task_id), reverse=True)
        # `reverse=True` sorts `task_id` descending alongside `created_at`, which
        # is not what the real `ORDER BY created_at DESC, task_id ASC` does for
        # two rows sharing one `created_at`. No test in this fake's suite pins two
        # rows to the same instant deliberately for that reason; the real
        # tie-break is proved against PostgreSQL in `tests/database`.
        if after is not None:
            if not any(task.task_id == after for task in owned):
                raise WorkCursorError
            ordered = ordered[
                next(
                    (index + 1 for index, task in enumerate(ordered) if task.task_id == after),
                    len(ordered),
                ) :
            ]
        return tuple(ordered[:limit])

    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
    ) -> tuple[TaskV2, ...]:
        needle = query.casefold()
        owned = list(
            self.list_tasks(
                principal_id,
                archive_mode=archive_mode,
                work_view=work_view,
                work_start=work_start,
                work_end=work_end,
                limit=len(self._world.tasks_v2) + 1,
            )
        )
        ordered = [task for task in owned if needle in task.title.casefold()]
        if after is not None:
            if not any(task.task_id == after for task in ordered):
                raise WorkCursorError
            ordered = ordered[
                next(
                    (index + 1 for index, task in enumerate(ordered) if task.task_id == after),
                    len(ordered),
                ) :
            ]
        return tuple(ordered[:limit])

    def list_history(
        self,
        principal_id: str,
        task_id: str,
        limit: int,
        *,
        after: str | None = None,
    ) -> tuple[TaskHistoryEntry, ...]:
        owned = [
            entry
            for entry in self._world.task_history_v2
            if entry.principal_id == principal_id and entry.task_id == task_id
        ]
        ordered = sorted(owned, key=lambda entry: (entry.recorded_at, entry.history_id))
        if after is not None:
            if not any(entry.history_id == after for entry in owned):
                raise WorkCursorError
            ordered = ordered[
                next(
                    (index + 1 for index, entry in enumerate(ordered) if entry.history_id == after),
                    len(ordered),
                ) :
            ]
        return tuple(ordered[:limit])

    def latest_applied_terminal_history(
        self, principal_id: str, task_id: str
    ) -> TaskHistoryEntry | None:
        matching = [
            entry
            for entry in self._world.task_history_v2
            if entry.principal_id == principal_id
            and entry.task_id == task_id
            and entry.action.value == "transition_lifecycle"
            and entry.outcome.value == "applied"
        ]
        return max(matching, key=lambda entry: (entry.recorded_at, entry.history_id), default=None)

    def get_follow_up_for_commitment(self, principal_id: str, commitment_id: str) -> TaskV2 | None:
        candidates = [
            task
            for task in self._world.tasks_v2
            if task.principal_id == principal_id
            and task.commitment_id == commitment_id
            and task.role is TaskRole.FOLLOW_UP
        ]
        return next(
            iter(sorted(candidates, key=lambda task: (-task.created_at.timestamp(), task.task_id))),
            None,
        )


class _CommitmentsRead(CommitmentManagementRepository):
    """The WP-TM-05 read plane over `World.commitments_v2`/`commitment_history_v2`.

    Only the read methods are exercised through `FakeUnitOfWork`; the write
    methods raise so that a test reaching them signals it is exercising
    mutation through the wrong seam — the same pattern `_TasksRead` uses.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, commitment_id: str) -> CommitmentV2 | None:
        return self.get(principal_id, commitment_id)

    def get(self, principal_id: str, commitment_id: str) -> CommitmentV2 | None:
        return next(
            (
                c
                for c in self._world.commitments_v2
                if c.principal_id == principal_id and c.commitment_id == commitment_id
            ),
            None,
        )

    def list_commitments(
        self,
        principal_id: str,
        *,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
        evidence_state: ContinuityEvidenceState | None = None,
        after: str | None = None,
        limit: int,
    ) -> tuple[CommitmentV2, ...]:
        owned = [c for c in self._world.commitments_v2 if c.principal_id == principal_id]
        if direction is not None:
            owned = [c for c in owned if c.direction is direction]
        if state is not None:
            owned = [c for c in owned if c.state is state]
        if evidence_state is not None:
            owned = [c for c in owned if c.evidence_state is evidence_state]
        ordered = sorted(
            owned,
            key=lambda c: (
                c.due_at is None,
                c.due_at or datetime.max.replace(tzinfo=UTC),
                -c.created_at.timestamp(),
                c.commitment_id,
            ),
        )
        if after is not None:
            if not any(commitment.commitment_id == after for commitment in owned):
                raise WorkCursorError
            ordered = ordered[
                next(
                    (
                        index + 1
                        for index, commitment in enumerate(ordered)
                        if commitment.commitment_id == after
                    ),
                    len(ordered),
                ) :
            ]
        return tuple(ordered[:limit])

    def insert_commitment(self, commitment: CommitmentV2) -> None:
        self._world.commitments_v2.append(commitment)

    def update_commitment(self, commitment: CommitmentV2) -> None:
        self._world.commitments_v2[:] = [
            commitment if existing.commitment_id == commitment.commitment_id else existing
            for existing in self._world.commitments_v2
        ]

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> CommitmentHistoryEntry | None:
        return next(
            (
                entry
                for entry in self._world.commitment_history_v2
                if entry.principal_id == principal_id and entry.idempotency_key == idempotency_key
            ),
            None,
        )

    def insert_history(self, entry: CommitmentHistoryEntry) -> None:
        self._world.commitment_history_v2.append(entry)

    def list_history(
        self,
        principal_id: str,
        commitment_id: str,
        limit: int,
        *,
        after: str | None = None,
    ) -> tuple[CommitmentHistoryEntry, ...]:
        owned = [
            entry
            for entry in self._world.commitment_history_v2
            if entry.principal_id == principal_id and entry.commitment_id == commitment_id
        ]
        ordered = sorted(owned, key=lambda entry: (entry.recorded_at, entry.history_id))
        if after is not None:
            if not any(entry.history_id == after for entry in owned):
                raise WorkCursorError
            ordered = ordered[
                next(
                    (index + 1 for index, entry in enumerate(ordered) if entry.history_id == after),
                    len(ordered),
                ) :
            ]
        return tuple(ordered[:limit])

    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
    ) -> tuple[CommitmentV2, ...]:
        needle = query.casefold()
        owned = [
            commitment
            for commitment in self._world.commitments_v2
            if commitment.principal_id == principal_id and needle in commitment.summary.casefold()
        ]
        if direction is not None:
            owned = [item for item in owned if item.direction is direction]
        if state is not None:
            owned = [item for item in owned if item.state is state]
        ordered = sorted(
            owned,
            key=lambda item: (
                item.due_at is None,
                item.due_at or datetime.max.replace(tzinfo=UTC),
                -item.created_at.timestamp(),
                item.commitment_id,
            ),
        )
        if after is not None:
            if not any(item.commitment_id == after for item in owned):
                raise WorkCursorError
            ordered = ordered[
                next(
                    (
                        index + 1
                        for index, item in enumerate(ordered)
                        if item.commitment_id == after
                    ),
                    len(ordered),
                ) :
            ]
        return tuple(ordered[:limit])


class _TasksWrite(TaskManagementRepository):
    """The WP-TM-04 write plane over `World.tasks_v2`/`task_history_v2`.

    A second repository over the same lists `_TasksRead` reads, rather than one
    repository serving both: `TaskManagementUnitOfWork.tasks` and
    `UnitOfWork.tasks` are two different ports with two different contracts —
    the write plane's own optimistic-concurrency and idempotency methods versus
    the read plane's list/search/history methods — and a class that implemented
    both would be answering to two callers who never call the same method.
    Sharing the world rather than sharing the class is what makes a task
    `TaskManagementService` creates visible to `UnitOfWork.tasks` afterwards.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, task_id: str) -> TaskV2 | None:
        return next(
            (
                task
                for task in self._world.tasks_v2
                if task.principal_id == principal_id and task.task_id == task_id
            ),
            None,
        )

    def get(self, principal_id: str, task_id: str) -> TaskV2 | None:
        return self.get_for_update(principal_id, task_id)

    def insert_task(self, task: TaskV2) -> None:
        self._world.tasks_v2.append(task)

    def update_task(self, task: TaskV2) -> None:
        self._world.tasks_v2[:] = [
            task if existing.task_id == task.task_id else existing
            for existing in self._world.tasks_v2
        ]

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskHistoryEntry | None:
        return next(
            (
                entry
                for entry in self._world.task_history_v2
                if entry.principal_id == principal_id and entry.idempotency_key == idempotency_key
            ),
            None,
        )

    def insert_history(self, entry: TaskHistoryEntry) -> None:
        self._world.task_history_v2.append(entry)

    def list_tasks(
        self,
        principal_id: str,
        *,
        lifecycle_state: TaskLifecycleState | None = None,
        priority: TaskPriority | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        after: str | None = None,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        limit: int,
    ) -> tuple[TaskV2, ...]:
        raise NotImplementedError("the write plane's fake does not serve list reads")

    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
    ) -> tuple[TaskV2, ...]:
        raise NotImplementedError("the write plane's fake does not serve search")

    def list_history(
        self,
        principal_id: str,
        task_id: str,
        limit: int,
        *,
        after: str | None = None,
    ) -> tuple[TaskHistoryEntry, ...]:
        raise NotImplementedError("the write plane's fake does not serve history reads")

    def latest_applied_terminal_history(
        self, principal_id: str, task_id: str
    ) -> TaskHistoryEntry | None:
        raise NotImplementedError("the write plane's fake does not serve history reads")


class FakeTaskManagementUnitOfWork(TaskManagementUnitOfWork):
    def __init__(self, world: World) -> None:
        self._world = world

    def __enter__(self) -> TaskManagementUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass

    @property
    def tasks(self) -> TaskManagementRepository:
        return _TasksWrite(self._world)


class _CommitmentsWrite(CommitmentManagementRepository):
    """The WP-TM-05 write plane over `World.commitments_v2`/`commitment_history_v2`.

    The identical split from the read plane that `_TasksWrite` gives, and for
    the identical reason: `CommitmentManagementUnitOfWork.commitments` is a
    different port from `UnitOfWork.commitments`, sharing the world rather than
    the class.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def get_for_update(self, principal_id: str, commitment_id: str) -> CommitmentV2 | None:
        return next(
            (
                commitment
                for commitment in self._world.commitments_v2
                if commitment.principal_id == principal_id
                and commitment.commitment_id == commitment_id
            ),
            None,
        )

    def get(self, principal_id: str, commitment_id: str) -> CommitmentV2 | None:
        return self.get_for_update(principal_id, commitment_id)

    def list_commitments(
        self,
        principal_id: str,
        *,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
        evidence_state: ContinuityEvidenceState | None = None,
        after: str | None = None,
        limit: int,
    ) -> tuple[CommitmentV2, ...]:
        del after, evidence_state
        raise NotImplementedError("the write plane's fake does not serve list reads")

    def insert_commitment(self, commitment: CommitmentV2) -> None:
        self._world.commitments_v2.append(commitment)

    def update_commitment(self, commitment: CommitmentV2) -> None:
        self._world.commitments_v2[:] = [
            commitment if existing.commitment_id == commitment.commitment_id else existing
            for existing in self._world.commitments_v2
        ]

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> CommitmentHistoryEntry | None:
        return next(
            (
                entry
                for entry in self._world.commitment_history_v2
                if entry.principal_id == principal_id and entry.idempotency_key == idempotency_key
            ),
            None,
        )

    def insert_history(self, entry: CommitmentHistoryEntry) -> None:
        self._world.commitment_history_v2.append(entry)

    def list_history(
        self,
        principal_id: str,
        commitment_id: str,
        limit: int,
        *,
        after: str | None = None,
    ) -> tuple[CommitmentHistoryEntry, ...]:
        raise NotImplementedError("the write plane's fake does not serve history reads")


class FakeCommitmentManagementUnitOfWork(CommitmentManagementUnitOfWork):
    def __init__(self, world: World) -> None:
        self._world = world

    def __enter__(self) -> CommitmentManagementUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass

    @property
    def commitments(self) -> CommitmentManagementRepository:
        return _CommitmentsWrite(self._world)


class _Situations(SituationRepository):
    """Situations over the `World`, with the partition predicate written out.

    The predicate is the point: every method adds `principal_id == <caller>`, so
    a Situation another Principal owns is answered exactly as an absent one.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def open_situation(
        self,
        *,
        principal_id: str,
        title: str,
        description: str | None,
        object_refs: tuple[str, ...],
    ) -> Situation:
        now = utc_now()
        situation = Situation(
            situation_id=issue_identifier(IdKind.SITUATION),
            principal_id=principal_id,
            title=title,
            state=SituationState.OPEN,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
            object_refs=tuple(object_refs),
        )
        self._world.situations.append(situation)
        return situation

    def close_situation(
        self,
        *,
        principal_id: str,
        situation_id: str,
        outcome: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> Situation:
        if not evidence_ref.strip():
            raise ValueError("closing a situation records the evidence that closed it")
        current = self.get_situation(principal_id, situation_id)
        if current is None:
            raise UnknownScopeError
        now = utc_now()
        closed = Situation(
            situation_id=current.situation_id,
            principal_id=current.principal_id,
            title=current.title,
            state=SituationState.CLOSED,
            opened_at=current.opened_at,
            created_at=current.created_at,
            updated_at=now,
            description=current.description,
            object_refs=current.object_refs,
            closed_at=now,
            outcome=outcome,
        )
        self._world.situations[self._world.situations.index(current)] = closed
        return closed

    def get_situation(self, principal_id: str, situation_id: str) -> Situation | None:
        return next(
            (
                row
                for row in self._world.situations
                if row.situation_id == situation_id and row.principal_id == principal_id
            ),
            None,
        )

    def list_situations(
        self, principal_id: str, state_filter: SituationState | None = None
    ) -> tuple[Situation, ...]:
        self._world.fail("list_situations")
        rows = [row for row in self._world.situations if row.principal_id == principal_id]
        if state_filter is not None:
            rows = [row for row in rows if row.state is state_filter]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return tuple(rows)


class _Projects(ProjectRepository):
    """Projects and the Project-Situation link, partitioned like everything else."""

    def __init__(self, world: World) -> None:
        self._world = world

    def add_project(
        self,
        *,
        principal_id: str,
        name: str,
        description: str | None,
        participants: tuple[str, ...],
    ) -> Project:
        now = utc_now()
        project = Project(
            project_id=issue_identifier(IdKind.PROJECT),
            principal_id=principal_id,
            name=name,
            state=ProjectState.ACTIVE,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
            participants=tuple(participants),
        )
        self._world.projects.append(project)
        return project

    def get_project(self, principal_id: str, project_id: str) -> Project | None:
        return next(
            (
                row
                for row in self._world.projects
                if row.project_id == project_id and row.principal_id == principal_id
            ),
            None,
        )

    def list_projects(
        self, principal_id: str, state_filter: ProjectState | None = None
    ) -> tuple[Project, ...]:
        rows = [row for row in self._world.projects if row.principal_id == principal_id]
        if state_filter is not None:
            rows = [row for row in rows if row.state is state_filter]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return tuple(rows)

    def link_situation(
        self,
        *,
        principal_id: str,
        project_id: str,
        situation_id: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> None:
        if not evidence_ref.strip():
            raise ValueError("linking a situation to a project records the evidence for it")
        project = self.get_project(principal_id, project_id)
        situation = _Situations(self._world).get_situation(principal_id, situation_id)
        if project is None or situation is None:
            raise UnknownScopeError
        link = (principal_id, project_id, situation_id, evidence_ref)
        if link not in self._world.project_situations:
            self._world.project_situations.append(link)


class _ContinuityAuthoring(ContinuityAuthoringRepository):
    """Idempotent user-directed continuity writes over a `World`."""

    def __init__(self, world: World) -> None:
        self._world = world

    def recall(self, principal_id: str, idempotency_key: str) -> AuthoringReceipt | None:
        return self._world.authoring_keys.get((principal_id, idempotency_key))

    def reserve(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        capability: str,
        payload_digest: str,
        object_id: str,
    ) -> bool:
        prior = self.recall(principal_id, idempotency_key)
        if prior is not None:
            if prior.payload_digest != payload_digest or prior.capability != capability:
                raise AuthoringConflictError
            return False
        self._world.authoring_keys[(principal_id, idempotency_key)] = AuthoringReceipt(
            capability=capability,
            object_id=object_id,
            payload_digest=payload_digest,
        )
        return True

    def author_project(
        self,
        *,
        principal_id: str,
        project_id: str,
        name: str,
        description: str | None,
    ) -> Project:
        now = utc_now()
        project = Project(
            project_id=project_id,
            principal_id=principal_id,
            name=name,
            state=ProjectState.ACTIVE,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
        )
        self._world.projects.append(project)
        return project

    def author_situation(
        self,
        *,
        principal_id: str,
        situation_id: str,
        title: str,
        description: str | None,
    ) -> Situation:
        now = utc_now()
        situation = Situation(
            situation_id=situation_id,
            principal_id=principal_id,
            title=title,
            state=SituationState.OPEN,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
        )
        self._world.situations.append(situation)
        return situation

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
    ) -> ContinuityTask:
        now = utc_now()
        task = ContinuityTask(
            task_id=task_id,
            principal_id=principal_id,
            title=title,
            state=TaskState.OPEN,
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            origin_evidence_ref=origin_evidence_ref,
            opened_at=now,
            created_at=now,
            updated_at=now,
            due_at=due_at,
            project_id=project_id,
            situation_id=situation_id,
            acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
        )
        self._world.continuity_tasks.append(task)
        return task


class _Pulse(PulseRepository):
    """The Pulse over the `World`: stored items, and the real derivation.

    `derive_pulse` runs the *production* pure function over the Principal's
    accepted, open continuity, so a test cannot pass here against a ranking the
    store would not reproduce. The accepted-only filter is written out below for
    the same reason the SQL writes it as a `WHERE` clause: it is the property
    under test, not a convenience.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    def generate_pulse(self, principal_id: str) -> tuple[PulseItem, ...]:
        return ()

    def dismiss_pulse_item(self, principal_id: str, pulse_id: str) -> None:
        self._world.dismissed_pulse_ids.add(pulse_id)

    def derive_pulse(self, principal_id: str, now: datetime) -> tuple[PulseItem, ...]:
        return derive_pulse(
            principal_id=principal_id,
            now=now,
            commitments=[
                row
                for row in self._world.commitments
                if row.principal_id == principal_id
                and row.evidence_state is ContinuityEvidenceState.ACCEPTED
            ],
            tasks=[
                row
                for row in self._world.continuity_tasks
                if row.principal_id == principal_id
                and row.evidence_state is ContinuityEvidenceState.ACCEPTED
            ],
            decisions=[
                row
                for row in self._world.continuity_decisions
                if row.principal_id == principal_id
                and row.evidence_state is ContinuityEvidenceState.ACCEPTED
            ],
            obligations=tuple(self._world.framed_obligations),
            dismissed_pulse_ids=frozenset(self._world.dismissed_pulse_ids),
        )


class _Entities(EntitiesRepository):
    """The entity plane over `World`, partition-first.

    Every method takes `principal_id` and applies it before anything else, so
    an entity belonging to another Principal is answered exactly as an absent
    one. The write methods repeat the SQL repository's entity-reference guard
    rather than trusting the caller: in the real schema those columns are
    foreign keys that span every Principal, so "the row exists" and "the row is
    mine" are different questions, and only the second one is safe.
    """

    def __init__(self, world: World) -> None:
        self._world = world

    # --- guards ----------------------------------------------------------

    def _mine(self, principal_id: str, entity_id: str) -> Entity | None:
        return next(
            (
                entity
                for entity in self._world.entities
                if entity.entity_id == entity_id and entity.principal_id == principal_id
            ),
            None,
        )

    def _require_own(self, principal_id: str, *entity_ids: str | None) -> None:
        for entity_id in entity_ids:
            if entity_id is not None and self._mine(principal_id, entity_id) is None:
                raise UnknownScopeError("an entity operation names an entity outside this scope")

    # --- reads -----------------------------------------------------------

    def search(
        self,
        principal_id: str,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 50,
        *,
        after_entity_id: str | None = None,
    ) -> list[EntitySummary]:
        self._world.fail("entities.search")
        # Parity with `SqlEntityRepository.search`, which calls
        # `_require_row_limit`. This clamped a non-positive limit to fifty while
        # the double's five other bounded reads refused one — so the single read
        # that guard's own docstring is written about was the one place the fake
        # and the server disagreed about what a caller may ask for.
        _refuse_empty_limit(limit)
        for entity in self._world.entities:
            if entity.principal_id == principal_id:
                # The rule `SqlEntityRepository._row_to_summary` enforces:
                # refuse to serve a stored name the resolver's equality
                # predicate could never match. The fake holds real `Entity`
                # records, so this can only fire on one assembled around the
                # constructor -- which is exactly what an adversarial test does.
                #
                # **Deliberately stricter than the server, and this said
                # "parity" until the ninth review measured it.** The server
                # reaches its mapper only for the rows a page actually returns,
                # so an unnormalized row outside the page does not stop a search
                # there; here the sweep is over the whole partition, so one
                # unnormalized row anywhere refuses every search. Stricter is
                # the safe direction for a fake -- it cannot hide a defect --
                # but a test asserting "search refuses while any unnormalized
                # row exists" would pass here and be false of production.
                # Carried in the plan's section 5 rather than narrowed, because
                # narrowing it would weaken the one place this rule is cheap to
                # enforce.
                _refuse_unnormalized_name(entity.canonical_name)
        needle = query.casefold()
        matched = [
            entity
            for entity in self._world.entities
            if entity.principal_id == principal_id
            and (entity_type is None or entity.entity_type is entity_type)
            and (
                needle in entity.canonical_name.casefold()
                or needle in entity.display_name.casefold()
            )
        ]
        matched.sort(key=lambda entity: (entity.canonical_name, entity.entity_id))
        # Mirrors `SqlEntityRepository.search`'s keyset: the cursor names the
        # last entity of the previous page, and its position in *this* read's
        # `(canonical_name, entity_id)` order is what the rows come after. Held
        # here as well, because a fake that paged differently would let a unit
        # test assert a walk the server does not perform.
        if after_entity_id is not None:
            position = next(
                (
                    (entity.canonical_name, entity.entity_id)
                    for entity in self._world.entities
                    if entity.principal_id == principal_id and entity.entity_id == after_entity_id
                ),
                None,
            )
            if position is None:
                raise UnknownScopeError("a search cursor names an entity in this scope")
            matched = [
                entity for entity in matched if (entity.canonical_name, entity.entity_id) > position
            ]
        return [
            EntitySummary(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                display_name=entity.display_name,
                status=entity.status,
            )
            for entity in matched[:limit]
        ]

    def get(self, principal_id: str, entity_id: str) -> Entity | None:
        self._world.fail("entities.get")
        return self._mine(principal_id, entity_id)

    def external_identifiers(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[ExternalIdentifier]:
        self._world.fail("entities.external_identifiers")
        _refuse_empty_limit(limit)
        found = sorted(
            (
                identifier
                for identifier in self._world.entity_identifiers
                if identifier.principal_id == principal_id and identifier.entity_id == entity_id
            ),
            key=lambda identifier: identifier.identifier_id,
        )
        return found if limit is None else found[:limit]

    def aliases(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[EntityAlias]:
        self._world.fail("entities.aliases")
        _refuse_empty_limit(limit)
        found = sorted(
            (
                alias
                for alias in self._world.entity_aliases
                if alias.principal_id == principal_id and alias.entity_id == entity_id
            ),
            key=lambda alias: alias.alias_id,
        )
        return found if limit is None else found[:limit]

    def entities_by_identifier(
        self,
        principal_id: str,
        namespace: ExternalIdentifierNamespace,
        normalized_value: str,
    ) -> list[tuple[Entity, ExternalIdentifier]]:
        self._world.fail("entities.entities_by_identifier")
        matched = [
            (entity, identifier)
            for identifier in self._world.entity_identifiers
            if identifier.principal_id == principal_id
            and identifier.namespace is namespace
            and identifier.normalized_value == normalized_value
            and (entity := self._mine(principal_id, identifier.entity_id)) is not None
        ]
        return sorted(matched, key=lambda pair: pair[0].entity_id)

    def entities_by_alias(
        self, principal_id: str, normalized_value: str
    ) -> list[tuple[Entity, EntityAlias]]:
        self._world.fail("entities.entities_by_alias")
        matched = [
            (entity, alias)
            for alias in self._world.entity_aliases
            if alias.principal_id == principal_id
            and alias.normalized_value == normalized_value
            and (entity := self._mine(principal_id, alias.entity_id)) is not None
        ]
        return sorted(matched, key=lambda pair: (pair[0].entity_id, pair[1].alias_id))

    def entities_by_canonical_name(self, principal_id: str, normalized_value: str) -> list[Entity]:
        self._world.fail("entities.entities_by_canonical_name")
        return sorted(
            (
                entity
                for entity in self._world.entities
                if entity.principal_id == principal_id and entity.canonical_name == normalized_value
            ),
            key=lambda entity: entity.entity_id,
        )

    def assignments(
        self,
        principal_id: str,
        entity_id: str,
        active_only: bool = True,
        *,
        limit: int | None = None,
    ) -> list[Assignment]:
        self._world.fail("entities.assignments")
        _refuse_empty_limit(limit)
        found = sorted(
            (
                assignment
                for assignment in self._world.entity_assignments
                if assignment.principal_id == principal_id
                and assignment.entity_id == entity_id
                and (not active_only or assignment.status == "active")
            ),
            key=lambda assignment: assignment.assignment_id,
        )
        return found if limit is None else found[:limit]

    def relationships(
        self,
        principal_id: str,
        entity_id: str,
        direction: str = "any",
        *,
        limit: int | None = None,
        after_relationship_id: str | None = None,
    ) -> list[EntityRelationship]:
        self._world.fail("entities.relationships")
        if direction not in ("any", "outgoing", "incoming"):
            raise ValueError("an entity relationship direction is any, outgoing, or incoming")
        _refuse_empty_limit(limit)
        if after_relationship_id is not None:
            validate_identifier(after_relationship_id, IdKind.ENTITY_RELATIONSHIP)
            # Refused here too, because the server refuses it. A fake that
            # emptied the page instead would let a unit test assert a
            # continuation the database does not perform.
            if not any(
                relationship.principal_id == principal_id
                and relationship.relationship_id == after_relationship_id
                for relationship in self._world.entity_relationships
            ):
                raise UnknownScopeError("a relationship cursor names an edge in this scope")
        found = sorted(
            (
                relationship
                for relationship in self._world.entity_relationships
                if relationship.principal_id == principal_id
                and _touches(relationship, entity_id, direction)
                # Strictly after, matching the SQL keyset exactly. `>=` here
                # would re-serve the last edge of the previous page, and a test
                # written against this fake would then prove a continuation
                # semantics the database does not implement.
                and (
                    after_relationship_id is None
                    or relationship.relationship_id > after_relationship_id
                )
            ),
            key=lambda relationship: relationship.relationship_id,
        )
        return found if limit is None else found[:limit]

    # --- writes ----------------------------------------------------------

    def create(self, principal_id: str, entity: Entity) -> Entity:
        self._world.fail("entities.create")
        if entity.principal_id != principal_id:
            raise ValueError("an entity belongs to the acting Principal")
        _refuse_unnormalized_name(entity.canonical_name)
        held = self._mine(entity.principal_id, entity.entity_id)
        if held is not None:
            if held != entity:
                raise ValueError("an entity identifier cannot be rebound to different values")
            return held
        self._require_own(entity.principal_id, entity.superseded_by_entity_id)
        _refuse_taken_identifier(
            next(
                (held for held in self._world.entities if held.entity_id == entity.entity_id),
                None,
            ),
            entity.entity_id,
            "an entity",
        )
        self._world.entities.append(entity)
        return entity

    def bind_identifier(
        self, principal_id: str, entity_id: str, identifier: ExternalIdentifier
    ) -> None:
        self._world.fail("entities.bind_identifier")
        if identifier.entity_id != entity_id:
            raise ValueError("an external identifier binds to the entity it names")
        if identifier.principal_id != principal_id:
            raise ValueError("an external identifier belongs to the acting Principal")
        if not is_normalized_identifier(identifier.namespace, identifier.normalized_value):
            raise ValueError("an external identifier is stored in the form resolution compares in")
        self._require_own(principal_id, entity_id)
        natural_key = (identifier.entity_id, identifier.namespace, identifier.normalized_value)
        for held in self._world.entity_identifiers:
            if (held.entity_id, held.namespace, held.normalized_value) == natural_key:
                return
        _refuse_taken_identifier(
            next(
                (
                    held
                    for held in self._world.entity_identifiers
                    if held.identifier_id == identifier.identifier_id
                ),
                None,
            ),
            identifier.identifier_id,
            "an external identifier",
        )
        self._world.entity_identifiers.append(identifier)

    def record_alias(self, principal_id: str, alias: EntityAlias) -> None:
        self._world.fail("entities.record_alias")
        if alias.principal_id != principal_id:
            raise ValueError("an alias belongs to the acting Principal")
        _refuse_unnormalized_name(alias.normalized_value)
        self._require_own(principal_id, alias.entity_id)
        natural_key = (alias.entity_id, alias.alias_type, alias.normalized_value)
        for held in self._world.entity_aliases:
            if (held.entity_id, held.alias_type, held.normalized_value) == natural_key:
                return
        _refuse_taken_identifier(
            next(
                (held for held in self._world.entity_aliases if held.alias_id == alias.alias_id),
                None,
            ),
            alias.alias_id,
            "an alias",
        )
        self._world.entity_aliases.append(alias)

    # --- WP-RI-06 governance ----------------------------------------------

    def record_observation(self, principal_id: str, observation: EntityObservation) -> None:
        # Parity with `SqlEntityRepository.record_observation`, which refuses an
        # unnormalized value. Without this the fake accepted what the database
        # rejects, so a unit test could store a raw mail envelope here and be
        # cited as evidence that the queue serves such a row.
        _refuse_unnormalized_name(observation.normalized_value)
        self._world.fail("entities.record_observation")
        if observation.principal_id != principal_id:
            raise ValueError("an observation belongs to the acting Principal")
        if observation.entity_id is not None:
            self._require_own(principal_id, observation.entity_id)
        # Partitioned, because `SqlEntityRepository` partitions it. Without the
        # predicate the collision read finds another Principal's row and either
        # tells this caller their own identifier is bound to different values --
        # a verdict computed from a partition they cannot see -- or silently
        # accepts their write as a duplicate of it. `tests/database/
        # test_entity_governance.py` names that comparison as the defect the
        # server was corrected away from, so a fake without it lets a unit test
        # prove the opposite of what the server does.
        for held in self._world.entity_observations:
            if (
                held.observation_id == observation.observation_id
                and held.principal_id == principal_id
            ):
                if held != observation:
                    raise ValueError(
                        "an observation identifier cannot be rebound to different values"
                    )
                return
        _refuse_taken_identifier(
            next(
                (
                    held
                    for held in self._world.entity_observations
                    if held.observation_id == observation.observation_id
                ),
                None,
            ),
            observation.observation_id,
            "an observation",
        )
        self._world.entity_observations.append(observation)

    def observations(
        self,
        principal_id: str,
        entity_id: str | None = None,
        *,
        unresolved_only: bool = False,
        limit: int | None = None,
        after_observation_id: str | None = None,
    ) -> list[EntityObservation]:
        self._world.fail("entities.observations")
        _refuse_empty_limit(limit)
        found = sorted(
            (
                observation
                for observation in self._world.entity_observations
                if observation.principal_id == principal_id
                and (entity_id is None or observation.entity_id == entity_id)
                and (not unresolved_only or observation.entity_id is None)
            ),
            key=lambda observation: observation.observation_id,
        )
        # Mirrors the SQL keyset: the cursor is the primary key the order is
        # taken on, so a fake that paged differently would let a unit test
        # assert a walk the server does not perform.
        if after_observation_id is not None:
            if not any(
                observation.principal_id == principal_id
                and observation.observation_id == after_observation_id
                for observation in self._world.entity_observations
            ):
                raise UnknownScopeError("an observation cursor names an observation in this scope")
            found = [
                observation
                for observation in found
                if observation.observation_id > after_observation_id
            ]
        return found if limit is None else found[:limit]

    def link_observation(self, principal_id: str, observation_id: str, entity_id: str) -> None:
        self._world.fail("entities.link_observation")
        self._require_own(principal_id, entity_id)
        for index, held in enumerate(self._world.entity_observations):
            if held.observation_id == observation_id and held.principal_id == principal_id:
                self._world.entity_observations[index] = replace(held, entity_id=entity_id)
                return
        raise UnknownScopeError("an observation link names an observation outside this scope")

    def record_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        self._world.fail("entities.record_proposal")
        if proposal.principal_id != principal_id:
            raise ValueError("a proposal belongs to the acting Principal")
        # Partitioned, because `SqlEntityRepository` partitions it. Without the
        # predicate the collision read finds another Principal's row and either
        # tells this caller their own identifier is bound to different values --
        # a verdict computed from a partition they cannot see -- or silently
        # accepts their write as a duplicate of it. `tests/database/
        # test_entity_governance.py` names that comparison as the defect the
        # server was corrected away from, so a fake without it lets a unit test
        # prove the opposite of what the server does.
        for held in self._world.entity_proposals:
            if held.proposal_id == proposal.proposal_id and held.principal_id == principal_id:
                if held != proposal:
                    raise ValueError("a proposal identifier cannot be rebound to different values")
                return
        _refuse_taken_identifier(
            next(
                (
                    held
                    for held in self._world.entity_proposals
                    if held.proposal_id == proposal.proposal_id
                ),
                None,
            ),
            proposal.proposal_id,
            "a proposal",
        )
        self._world.entity_proposals.append(proposal)

    def proposal(self, principal_id: str, proposal_id: str) -> EntityProposal | None:
        self._world.fail("entities.proposal")
        return next(
            (
                held
                for held in self._world.entity_proposals
                if held.proposal_id == proposal_id and held.principal_id == principal_id
            ),
            None,
        )

    def proposals(
        self, principal_id: str, state: EntityProposalState | None = None
    ) -> list[EntityProposal]:
        self._world.fail("entities.proposals")
        return sorted(
            (
                held
                for held in self._world.entity_proposals
                if held.principal_id == principal_id and (state is None or held.state is state)
            ),
            key=lambda held: held.proposal_id,
        )

    def decide_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        self._world.fail("entities.decide_proposal")
        if proposal.principal_id != principal_id:
            raise ValueError("a proposal belongs to the acting Principal")
        for index, held in enumerate(self._world.entity_proposals):
            if held.proposal_id == proposal.proposal_id and held.principal_id == principal_id:
                # Mirrors the SQL `state = 'proposed'` predicate. Without it a
                # unit test could assert the repository's one-time-decision rule
                # against a fake that has no such rule and pass, which is the
                # hazard `redirect_entity` names two methods above.
                if held.state is not EntityProposalState.PROPOSED:
                    raise UnknownScopeError("a decision names an open proposal in this scope")
                self._world.entity_proposals[index] = proposal
                return
        raise UnknownScopeError("a decision names an open proposal in this scope")

    def record_merge(self, principal_id: str, record: EntityMergeRecord) -> None:
        self._world.fail("entities.record_merge")
        if record.principal_id != principal_id:
            raise ValueError("a merge record belongs to the acting Principal")
        self._require_own(principal_id, record.retained_entity_id, record.merged_entity_id)
        # Mirrors the SQL partition check on the cited proposal: a record naming
        # another Principal's proposal presents their decision as this
        # Principal's own.
        if not any(
            held.proposal_id == record.proposal_id and held.principal_id == principal_id
            for held in self._world.entity_proposals
        ):
            raise UnknownScopeError("a merge record cites a proposal in this scope")
        # **Deliberately NOT partitioned, and it was for one commit.** Every
        # other collision read on this plane mirrors a partitioned read in
        # `SqlEntityRepository`; this one mirrors nothing, because the server
        # performs no `merged_entity_id` lookup at all. The rule is carried by a
        # *global* `UNIQUE` on `entity_merge_records.merged_entity_id`
        # (`persistence/tables.py`, whose own comment reads "an entity is merged
        # away once"). Adding a Principal predicate here narrowed a global
        # constraint to a per-Principal one with nothing global left behind it,
        # so the fake accepted a merge the database refuses -- measured by the
        # tenth review as a regression against the commit before it.
        if any(
            held.merged_entity_id == record.merged_entity_id for held in self._world.entity_merges
        ):
            raise ValueError("an entity is merged away once")
        _refuse_taken_identifier(
            next(
                (held for held in self._world.entity_merges if held.merge_id == record.merge_id),
                None,
            ),
            record.merge_id,
            "a merge record",
        )
        self._world.entity_merges.append(record)

    def merges(self, principal_id: str, entity_id: str | None = None) -> list[EntityMergeRecord]:
        self._world.fail("entities.merges")
        return sorted(
            (
                held
                for held in self._world.entity_merges
                if held.principal_id == principal_id
                and (
                    entity_id is None
                    or entity_id in (held.retained_entity_id, held.merged_entity_id)
                )
            ),
            key=lambda held: held.merge_id,
        )

    def redirect_entity(
        self, principal_id: str, merged_entity_id: str, retained_entity_id: str
    ) -> None:
        self._world.fail("entities.redirect_entity")
        self._require_own(principal_id, merged_entity_id, retained_entity_id)
        if merged_entity_id == retained_entity_id:
            raise ValueError("an entity cannot be merged into itself")
        # Mirrors `SqlEntityRepository.redirect_entity`. Held here as well
        # because a fake that permitted the cycle would let a unit test assert
        # the refusal and pass without one.
        survivor = self.get(principal_id, retained_entity_id)
        if survivor is None or survivor.status is EntityStatus.MERGED_REDIRECT:
            raise ValueError("an entity is merged into one that is still current")
        if any(
            held.principal_id == principal_id and held.superseded_by_entity_id == merged_entity_id
            for held in self._world.entities
        ):
            raise ValueError("an entity that others redirect to is not merged away")
        merged = self.get(principal_id, merged_entity_id)
        if merged is not None and merged.status is EntityStatus.MERGED_REDIRECT:
            raise ValueError("an entity that is already merged away is not merged again")
        for index, held in enumerate(self._world.entities):
            if held.entity_id == merged_entity_id and held.principal_id == principal_id:
                self._world.entities[index] = replace(
                    held,
                    status=EntityStatus.MERGED_REDIRECT,
                    superseded_by_entity_id=retained_entity_id,
                )
                return
        raise UnknownScopeError("a redirect names an entity outside this scope")

    def record_assignment(self, principal_id: str, assignment: Assignment) -> None:
        self._world.fail("entities.record_assignment")
        if assignment.principal_id != principal_id:
            raise ValueError("an assignment belongs to the acting Principal")
        self._require_own(principal_id, assignment.entity_id, assignment.scope_entity_id)
        # Partitioned, because `SqlEntityRepository` partitions it. Without the
        # predicate the collision read finds another Principal's row and either
        # tells this caller their own identifier is bound to different values --
        # a verdict computed from a partition they cannot see -- or silently
        # accepts their write as a duplicate of it. `tests/database/
        # test_entity_governance.py` names that comparison as the defect the
        # server was corrected away from, so a fake without it lets a unit test
        # prove the opposite of what the server does.
        for held in self._world.entity_assignments:
            if held.assignment_id == assignment.assignment_id and held.principal_id == principal_id:
                if held != assignment:
                    raise ValueError(
                        "an assignment identifier cannot be rebound to different values"
                    )
                return
        _refuse_taken_identifier(
            next(
                (
                    held
                    for held in self._world.entity_assignments
                    if held.assignment_id == assignment.assignment_id
                ),
                None,
            ),
            assignment.assignment_id,
            "an assignment",
        )
        self._world.entity_assignments.append(assignment)

    def record_relationship(self, principal_id: str, rel: EntityRelationship) -> None:
        self._world.fail("entities.record_relationship")
        if rel.principal_id != principal_id:
            raise ValueError("an entity relationship belongs to the acting Principal")
        self._require_own(principal_id, rel.from_entity_id, rel.to_entity_id, rel.scope_entity_id)
        # Partitioned, because `SqlEntityRepository` partitions it. Without the
        # predicate the collision read finds another Principal's row and either
        # tells this caller their own identifier is bound to different values --
        # a verdict computed from a partition they cannot see -- or silently
        # accepts their write as a duplicate of it. `tests/database/
        # test_entity_governance.py` names that comparison as the defect the
        # server was corrected away from, so a fake without it lets a unit test
        # prove the opposite of what the server does.
        for held in self._world.entity_relationships:
            if held.relationship_id == rel.relationship_id and held.principal_id == principal_id:
                if held != rel:
                    raise ValueError(
                        "an entity relationship identifier cannot be rebound to different values"
                    )
                return
        _refuse_taken_identifier(
            next(
                (
                    held
                    for held in self._world.entity_relationships
                    if held.relationship_id == rel.relationship_id
                ),
                None,
            ),
            rel.relationship_id,
            "an entity relationship",
        )
        self._world.entity_relationships.append(rel)


def _refuse_taken_identifier(held: object, identifier: str, noun: str) -> None:
    """Refuse an identifier some other partition already holds, as the server does.

    Every table on this plane keys on a *global* primary key, so an identifier
    another Principal holds is unavailable to this one -- the server answers
    `IntegrityError`.

    **Eight writes introduce an identifier and all eight carry this.** The tenth
    review found it on four of them while this docstring asserted it of all, and
    measured the fake accepting duplicate `entity_id`, `identifier_id`,
    `alias_id` and `merge_id` values the server refuses. The correction then said
    "four of nine", which the eleventh review measured as wrong by one -- a
    miscount inside the sentence recording a miscount. The plane has eight
    tables and this helper has eight call sites.

    The collision reads above are partitioned, matching
    `SqlEntityRepository`, which is what decides *on whose evidence* a write is
    judged; this is the separate rule that decides whether the key is free at
    all. Without it, partitioning those reads would have made the fake accept a
    duplicate key the database refuses, and a unit test could then prove two
    Principals may hold one observation identifier.
    """
    if held is not None:
        raise ValueError(f"{noun} identifier is already taken: {identifier}")


def _refuse_unnormalized_name(value: str) -> None:
    """Refuse a name not in the form resolution compares in, as `persistence.entity` does.

    The SQL repository checks this at its own write boundary rather than
    trusting the record it was handed (`RI-PR135-MAJOR-002`), so a fake that
    accepted what the database refuses would let a unit test prove that a
    backfill can store a row the resolver cannot match.
    """
    if not is_normalized_name(value):
        raise ValueError("an entity name is stored in the form resolution compares in")


def _refuse_empty_limit(limit: int | None) -> None:
    """Refuse a row limit that asks for nothing, as `persistence.entity` does.

    Parity with the SQL repository is the whole point of this fake, and a limit
    it accepted where the database refuses would let a unit test prove that an
    empty page is a legitimate answer to a bounded read. It is not: an empty
    page reads as "nothing is recorded", which is the one thing a bound must
    never say by accident.
    """
    if limit is not None and limit < 1:
        raise ValueError("an entity row limit asks for at least one row")


def _touches(relationship: EntityRelationship, entity_id: str, direction: str) -> bool:
    """Whether one edge answers a directed enumeration for `entity_id`."""
    if direction == "outgoing":
        return relationship.from_entity_id == entity_id
    if direction == "incoming":
        return relationship.to_entity_id == entity_id
    return entity_id in (relationship.from_entity_id, relationship.to_entity_id)


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
    def providers(self) -> SourceProviders:
        return self._world.providers

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
    def captures(self) -> CaptureRepository:
        return _Captures(self._world)

    @property
    def reviews(self) -> ReviewRepository:
        return _Reviews(self._world)

    @property
    def situations(self) -> SituationRepository:
        return _Situations(self._world)

    @property
    def projects(self) -> ProjectRepository:
        return _Projects(self._world)

    @property
    def pulse(self) -> PulseRepository:
        return _Pulse(self._world)

    @property
    def continuity_authoring(self) -> ContinuityAuthoringRepository:
        return _ContinuityAuthoring(self._world)

    @property
    def managed_documents(self) -> ManagedDocumentRepository:
        """The managed-document plane over this `World` (WP-28)."""
        return _ManagedDocuments(self._world)

    @property
    def tasks(self) -> TaskManagementRepository:
        """The task-management read plane over this `World` (WP-TM-03)."""
        return _TasksRead(self._world)

    @property
    def commitments(self) -> CommitmentManagementRepository:
        """The commitment-management read plane over this `World` (WP-TM-05)."""
        return _CommitmentsRead(self._world)

    @property
    def context_runs(self) -> ContextRunRepository:
        """Insert-only context-run metadata over this `World`."""
        return _ContextRuns(self._world)

    @property
    def context_preferences(self) -> ContextPreferenceRepository:
        """Append-only retrieval preferences over this `World`."""
        return _ContextPreferences(self._world)

    @property
    def goodnotes_semantics(self) -> GoodNotesSemanticRepository:
        """Immutable page-version work and semantic proposal receipts over this `World`."""
        return _GoodNotesSemantics(self._world)

    def intelligence_for(self, principal_id: str) -> InMemoryIntelligenceStore:
        return self._world.intelligence

    @property
    def entities(self) -> EntitiesRepository:
        """The relationship-intelligence entity plane over this `World`."""
        return _Entities(self._world)

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
    """The lookup from a source identity to the adapter serving it.

    `lookups` records every identifier a use case *asked* about, which is one
    step earlier than `RecordingProvider.calls`. The distinction matters for the
    capture plane: a capture path that resolved a provider and then called
    nothing on it would leave `calls` empty and would still have reached for a
    source, and `ADR-003` clause 5 is a claim about reaching rather than about
    what was reached for.
    """

    def __init__(self, providers: dict[str, SourceProvider] | None = None) -> None:
        self.providers: dict[str, SourceProvider] = providers or {}
        self.lookups: list[str] = []

    def for_source(self, source_id: str) -> SourceProvider | None:
        self.lookups.append(source_id)
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
    world: World,
    providers: FakeProviders,
    limits: EffectiveLimits = DEFAULT_LIMITS,
    managed_store: ManagedByteStore | None = None,
    relationship_intelligence_enabled: bool = True,
) -> ApplicationService:
    """The service under test, with a fixed clock and in-memory repositories.

    `providers` is still a parameter and is no longer passed to the service.
    `ApplicationService` takes no `SourceProviders` any more — the lookup comes
    from the unit of work, because a provider resolves identifiers against rows
    the same transaction has to see — so the adapters go into the `World` the
    fake unit of work reads. Keeping the parameter is what lets a test say which
    adapters exist without knowing where the port hangs.
    """
    world.providers = providers
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        limits=limits,
        clock=lambda: WHEN,
        # Composed by default, because a service composed *without* one publishes
        # a smaller capability set — and a suite that quantifies over `Capability`
        # would then be quantifying over names its own service refuses. A test
        # about the unconfigured build passes `None` explicitly and says so.
        managed_store=world.managed_store if managed_store is None else managed_store,
        # Wired by the same default reasoning: an `ApplicationService` composed
        # without these publishes no task/commitment mutation capability, and a
        # suite that quantifies over `Capability` would be quantifying over
        # names its own service refuses.
        task_management_unit_of_work=lambda: FakeTaskManagementUnitOfWork(world),
        commitment_management_unit_of_work=lambda: FakeCommitmentManagementUnitOfWork(world),
        # Enabled by the same default reasoning: the six `entities.` names are
        # withheld from a build that has not turned the plane on, and a suite
        # that quantifies over `Capability` would be quantifying over names its
        # own service refuses. A test about the *withheld* build passes `False`
        # explicitly and says so — `tests/contract/test_mcp_transport` is the one
        # that does, against a real child process.
        relationship_intelligence_enabled=relationship_intelligence_enabled,
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


def staged_capture(scene: Scene, *, text: str = "a synthetic note") -> CaptureVersion:
    """One stored capture inside `scene`'s world, so `capture.read` has an answer.

    Written through the port rather than pushed into `World` directly, so the
    version number, the supersession link, and the receipt are the ones the
    admission produces. A test that staged the rows by hand could stage a state
    the writer cannot reach.
    """
    unit_of_work = FakeUnitOfWork(scene.world)
    admission = unit_of_work.captures.admit(
        CaptureAdmissionRequest(
            capture_id=None,
            content=CaptureContent(text),
            idempotency_key=f"staged-capture-{len(scene.world.capture_keys)}",
            request_id="req-staged-capture",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            principal_id=scene.principal.principal_id,
            audit_id=issue_identifier(IdKind.AUDIT),
            classification=Classification.PRIVATE_LOCAL,
            processing_policy=ProcessingPolicy.LOCAL_ONLY,
            server_received_at=WHEN,
            accepted_at=WHEN,
        ),
        principal_id=scene.principal.principal_id,
    )
    stored = unit_of_work.captures.version(
        admission.receipt.capture_id,
        version_id=admission.receipt.version_id,
        principal_id=scene.principal.principal_id,
    )
    assert stored is not None
    return stored


def staged_situation(
    scene: Scene, *, title: str = "quarterly planning", description: str | None = None
) -> Situation:
    """One stored Situation inside `scene`'s world, written through the port."""
    unit_of_work = FakeUnitOfWork(scene.world)
    return unit_of_work.situations.open_situation(
        principal_id=scene.principal.principal_id,
        title=title,
        description=description,
        object_refs=(),
    )


def staged_project(
    scene: Scene, *, name: str = "quarterly program", description: str | None = None
) -> Project:
    """One stored Project inside `scene`'s world, written through the port."""
    unit_of_work = FakeUnitOfWork(scene.world)
    return unit_of_work.projects.add_project(
        principal_id=scene.principal.principal_id,
        name=name,
        description=description,
        participants=(),
    )


def staged_managed_document(
    scene: Scene,
    *,
    title: str = "Synthetic managed note",
    body: bytes = b"# Synthetic managed note",
) -> ManagedDocumentReceipt:
    """One stored managed document inside `scene`'s world, so the reads have an answer.

    Written through `ManagedDocumentService` and the fake ports rather than
    pushed into `World` directly, for the reason `staged_capture` is: the version
    number, the supersession link and the receipt are then the ones an admission
    produces, and a test cannot stage a state the writer cannot reach.

    The Principal is `scene.principal`'s and is passed as the resolved partition,
    which is the same thing `ApplicationService`'s handlers pass.

    One per scene, like `staged_review_case`: a payload table and a command table
    that each staged their own would be naming two different documents, and the
    comparison between them would then be measuring the staging rather than the
    request.
    """
    for (owner, key), (_, receipt) in scene.world.managed_keys.items():
        if owner == scene.principal.principal_id and key.startswith("staged-managed-"):
            return receipt
    unit_of_work = FakeUnitOfWork(scene.world)
    store = scene.world.managed_store
    return ManagedDocumentService().create(
        unit_of_work.managed_documents,
        store,
        CreateManagedDocumentCommand(
            principal_id=scene.principal.principal_id,
            title=title,
            media_type="text/markdown",
            content=body,
            idempotency_key=f"staged-managed-{len(scene.world.managed_keys)}",
        ),
    )


def staged_review_case(scene: Scene, capture: CaptureVersion | None = None) -> ReviewCase:
    """One open consequential case, using identifiers every review command accepts."""
    if scene.world.review_cases:
        return scene.world.review_cases[0]
    version = capture or staged_capture(scene)
    case = ReviewCase(
        review_case_id=issue_identifier(IdKind.REVIEW_CASE),
        proposal_id=issue_identifier(IdKind.PROPOSAL),
        capture_id=version.capture_id,
        version_id=version.version_id,
        principal_id=version.owner_principal_id,
        proposal_type=ProposalType.COMMITMENT,
        proposal_state=ProposalState.NEEDS_REVIEW,
        risk_class=RiskClass.MODERATE,
        opened_at=WHEN,
    )
    scene.world.review_cases.append(case)
    return case


def staged_task(scene: Scene, *, title: str = "a synthetic task") -> TaskV2:
    """One stored task inside `scene`'s world, so `tasks.read` and its siblings answer.

    Written through `TaskManagementService`, the same reasoning `staged_capture`
    gives: the version number and the history entry are then the ones a real
    creation produces, and a test cannot stage a state the service cannot reach.

    One per Principal per scene, like `staged_managed_document`: a payload table
    and a command table that each staged their own would be naming two different
    tasks, and the comparison between them would then be measuring the staging
    rather than the request.
    """
    existing = next(
        (t for t in scene.world.tasks_v2 if t.principal_id == scene.principal.principal_id),
        None,
    )
    if existing is not None:
        return existing
    scene.world.work_evidence_refs.add((scene.principal.principal_id, "cap_origin0001origin0001"))
    service = TaskManagementService(unit_of_work=lambda: FakeTaskManagementUnitOfWork(scene.world))
    receipt = service.create_task(
        principal_id=scene.principal.principal_id,
        title=title,
        origin_evidence_ref="cap_origin0001origin0001",
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=f"staged-task-{len(scene.world.tasks_v2)}",
    )
    return receipt.task


def staged_commitment(
    scene: Scene,
    *,
    counterparty_person_id: str | None = None,
    summary: str = "a synthetic commitment",
) -> CommitmentV2:
    """One stored commitment inside `scene`'s world, so the reads have an answer.

    Written through `CommitmentManagementService`, for the identical reason
    `staged_task` is, including the one-per-Principal-per-scene caching.
    """
    existing = next(
        (c for c in scene.world.commitments_v2 if c.principal_id == scene.principal.principal_id),
        None,
    )
    if existing is not None:
        return existing
    scene.world.work_evidence_refs.add((scene.principal.principal_id, "cap_origin0001origin0001"))
    receipt = CommitmentManagementService(
        unit_of_work=lambda: FakeCommitmentManagementUnitOfWork(scene.world)
    ).create_commitment(
        principal_id=scene.principal.principal_id,
        counterparty_person_id=counterparty_person_id or issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary=summary,
        origin_evidence_ref="cap_origin0001origin0001",
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=f"staged-commitment-{len(scene.world.commitments_v2)}",
    )
    return receipt.commitment


def staged_goodnotes_work(scene: Scene) -> GoodNotesPageWork:
    """One synthetic page-version handle so `goodnotes.work` and `.propose` answer.

    One per Principal per scene, like `staged_task`: a payload table and a
    command table that each staged their own would be naming two different
    versions. The digest is of synthetic bytes, never live personal content.
    """
    existing = next(
        (
            work
            for work in scene.world.goodnotes_work.values()
            if work.principal_id == scene.principal.principal_id
        ),
        None,
    )
    if existing is not None:
        return existing
    principal_id = scene.principal.principal_id
    work = GoodNotesPageWork(
        run_id=issue_stable_id("gnrun", principal_id, "staged-work"),
        page_version_id=issue_stable_id("gnver", principal_id, "staged-work"),
        principal_id=principal_id,
        content_sha256=hashlib.sha256(b"synthetic-goodnotes-page").hexdigest(),
        logical_page_id=issue_stable_id("gnlp", principal_id, "staged-work"),
        renderer_name="synthetic",
        renderer_version="1",
        render_profile_version="v1",
    )
    scene.world.goodnotes_work[(principal_id, work.run_id, work.page_version_id)] = work
    return work


def _staged_gray_png() -> bytes:
    """One-pixel grayscale PNG. Synthetic, never live handwriting."""
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")

    ihdr = (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff", 9))
        + chunk(b"IEND", b"")
    )


def staged_goodnotes_raster(scene: Scene) -> GoodNotesPageRaster:
    """One synthetic pinned raster so `goodnotes.content` answers."""
    work = staged_goodnotes_work(scene)
    existing = scene.world.goodnotes_rasters.get((work.principal_id, work.page_version_id))
    if existing is not None:
        return existing
    png = _staged_gray_png()
    raster = GoodNotesPageRaster(
        principal_id=work.principal_id,
        page_version_id=work.page_version_id,
        run_id=work.run_id,
        exact_render_sha256=hashlib.sha256(b"synthetic-goodnotes-raster").hexdigest(),
        png_sha256=hashlib.sha256(png).hexdigest(),
        byte_length=len(png),
        png_bytes=png,
        renderer_name="synthetic",
        renderer_version="1",
        render_profile_version="v1",
        created_at=WHEN,
    )
    scene.world.goodnotes_rasters[(work.principal_id, work.page_version_id)] = raster
    return raster


@pytest.fixture
def scene(world: World, fixture_root: Path) -> Scene:
    return Scene(world, fixture_root)
