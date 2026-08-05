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

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import pytest

from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    Acceptance,
    AuditSink,
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureRepository,
    CaptureSearchMatch,
    CaptureSearchOutcome,
    CaptureSearchRequest,
    CaptureSummary,
    EnrollmentRepository,
    KnowledgeRecord,
    KnowledgeRepository,
    Operation,
    OperationQueue,
    PortError,
    ReviewDecisionRequest,
    ReviewRepository,
    SearchOutcome,
    SourceProviders,
    SourceRepository,
    UnitOfWork,
    UnknownScopeError,
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
from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
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
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
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
    review_cases: list[ReviewCase] = field(default_factory=list)
    review_decisions: list[ReviewDecision] = field(default_factory=list)
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
    world: World, providers: FakeProviders, limits: EffectiveLimits = DEFAULT_LIMITS
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


@pytest.fixture
def scene(world: World, fixture_root: Path) -> Scene:
    return Scene(world, fixture_root)
