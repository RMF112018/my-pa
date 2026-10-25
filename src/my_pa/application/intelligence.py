"""Canonical Intelligence Artifact application operations.

MCP and a future BFF both reach these functions through `ApplicationService`.
Principal is always the authenticated partition, never a request field.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Final, Protocol
from urllib.parse import urlsplit

from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.intelligence.catalog import (
    ALLOWED_PROVENANCE_URL_SCHEMES,
    ARTIFACT_KIND_FOR_STAGE,
    CYCLE_MORNING_INTELLIGENCE,
    EXPECTED_FOCUS_AREAS,
    MAX_ARTIFACT_BODY_BYTES,
    MAX_CLIENT_REPORT_TYPES,
    MAX_MORNING_BRIEF_DEPENDENCY_COUNT,
    MAX_STRUCTURED_CONTENT_BYTES,
    MIN_SYNTHESIZER_DEPENDENCY_COUNT,
    REQUIRED_DEPENDENCY_COUNT,
    REQUIRED_MEMBERSHIP,
    STAGE_FOR_KIND,
    ArtifactKind,
    ArtifactState,
    CycleState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ProvenanceRelation,
    ReadinessMemberState,
    ReportTypeOrigin,
    ResolverAggregateState,
    ResolverSetId,
    SourceLaneId,
    expected_members,
    parse_artifact_kind,
    validate_stage_coordinates,
)
from my_pa.domain.intelligence.errors import (
    DependencyRejection,
    IntelligenceConflictError,
    IntelligenceCoordinateError,
    IntelligenceDependencyError,
    IntelligenceDigestMismatchError,
    IntelligenceIdempotencyConflictError,
    IntelligenceLimitError,
    IntelligenceStaleReferenceError,
    IntelligenceVersionConflictError,
)
from my_pa.domain.intelligence.models import (
    IntelligenceArtifact,
    IntelligenceCommitReceipt,
    IntelligenceCycleRun,
    IntelligencePipelineDependency,
    IntelligenceProducerRun,
    IntelligenceProvenanceRef,
    IntelligenceReportType,
    MutationAdmission,
    ReportTypeDefinition,
    ReportTypeInsertion,
    builtin_report_type_definitions,
    content_digest,
    content_utf8_bytes,
    fingerprint_payload,
)
from my_pa.domain.intelligence.source_manifest import (
    DependencyDigests,
    LineageReferenceBlock,
    LineageReferenceError,
    ProgramReferenceBlock,
    ProgramReferenceError,
    RecordedManifest,
    build_manifest,
    lineage_reference_block,
    program_reference_block,
    recorded_release_requirement,
    structured_content_sha256,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "InMemoryIntelligenceStore",
    "IntelligenceStore",
    "LineageReferenceRecompute",
    "ProgramReferenceRecompute",
    "ReportTypeRegistration",
    "begin_cycle",
    "commit_artifact",
    "latest_artifact",
    "list_artifacts",
    "read_artifact",
    "record_run_state",
    "register_report_type",
    "registered_report_types",
    "require_registered_kind",
    "resolve_set",
    "search_artifacts",
]


class IntelligenceStore(Protocol):
    """Principal-partitioned storage for cycle, run, artifact, and receipt rows."""

    def get_receipt(
        self, principal_id: str, idempotency_key: str
    ) -> IntelligenceCommitReceipt | None: ...

    def put_receipt(self, receipt: IntelligenceCommitReceipt) -> bool:
        """Insert if the key is free. Return False when the key already exists."""

    def get_cycle(self, principal_id: str, cycle_run_id: str) -> IntelligenceCycleRun | None: ...

    def cycle_for_external_root(
        self, principal_id: str, platform: str, external_root_run_id: str
    ) -> IntelligenceCycleRun | None: ...

    def put_cycle(self, cycle: IntelligenceCycleRun) -> None: ...

    def get_run(self, principal_id: str, run_id: str) -> IntelligenceProducerRun | None: ...

    def put_run(self, run: IntelligenceProducerRun) -> None: ...

    def replace_run(self, run: IntelligenceProducerRun, *, expected_version: int) -> bool: ...

    def run_for_external(
        self,
        principal_id: str,
        platform: str,
        producer_task_id: str,
        automation_run_id: str,
    ) -> IntelligenceProducerRun | None: ...

    def get_artifact(self, principal_id: str, artifact_id: str) -> IntelligenceArtifact | None: ...

    def put_artifact(
        self,
        artifact: IntelligenceArtifact,
        *,
        program_section: Mapping[str, object] | None = None,
        lineage_section: Mapping[str, object] | None = None,
    ) -> None:
        """Insert the artifact and, beside it, its immutable report manifest (S4 7.4).

        `program_section` is the manifest's `ProgramManifestSection`, or `None`;
        `lineage_section` its S3.1 section 7.9 `LineageManifestSection`, or `None`.
        """

    def get_manifest(self, principal_id: str, artifact_id: str) -> RecordedManifest | None:
        """The artifact's stored manifest; `None` for a legacy artifact (S4 7.4)."""

    def mark_superseded(self, principal_id: str, artifact_id: str) -> None: ...

    def current_head(
        self,
        principal_id: str,
        cycle_run_id: str,
        stage: IntelligenceStage,
        artifact_kind: str,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
    ) -> IntelligenceArtifact | None:
        """The current head of `artifact_kind`'s own lineage at the coordinate.

        Heads are per kind: a client kind at a built-in stage has its own head
        and never displaces the built-in one.
        """

    def list_artifacts(
        self,
        principal_id: str,
        *,
        cycle_run_id: str | None,
        stage: IntelligenceStage | None,
        artifact_kind: str | None,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
        report_date: date | None,
        include_superseded: bool,
        limit: int,
        after_committed_at: datetime | None = None,
        after_artifact_id: str | None = None,
        builtin_only: bool = False,
    ) -> tuple[IntelligenceArtifact, ...]:
        """Committed artifacts, newest first.

        `builtin_only` keeps only the five built-in kinds (`ArtifactKind`), so a
        kindless selection never answers with a Principal's client kind.
        """

    def search_artifacts(
        self,
        principal_id: str,
        query: str,
        *,
        cycle_run_id: str | None,
        stage: IntelligenceStage | None,
        artifact_kind: str | None,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
        limit: int,
    ) -> tuple[tuple[IntelligenceArtifact, str], ...]: ...

    def failed_run(
        self,
        principal_id: str,
        cycle_run_id: str,
        stage: IntelligenceStage,
        artifact_kind: str,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
    ) -> IntelligenceProducerRun | None:
        """The latest run of `artifact_kind` at the coordinate."""

    def list_report_types(
        self, principal_id: str, *, stage: IntelligenceStage | None = None
    ) -> tuple[IntelligenceReportType, ...]:
        """The Principal's stored report types, ordered by (stage, kind). Stored rows only."""

    def get_report_type(
        self, principal_id: str, artifact_kind: str
    ) -> IntelligenceReportType | None: ...

    def insert_report_type(
        self, principal_id: str, definition: ReportTypeDefinition, *, created_at: datetime
    ) -> ReportTypeInsertion:
        """Insert unless the kind is registered; an existing row is returned unchanged."""

    def ensure_builtin_report_types(self, principal_id: str, *, created_at: datetime) -> int:
        """Insert any missing built-in row; return how many were inserted."""

    def register_client_report_type(
        self,
        principal_id: str,
        definition: ReportTypeDefinition,
        *,
        created_at: datetime,
        limit: int,
    ) -> ReportTypeInsertion | None:
        """Insert a client kind under a per-Principal registration lock.

        The lookup, the count of client rows and the insert run under one
        lock held to the end of the transaction, so concurrent registrations
        for a Principal serialize and the cap is never exceeded. An existing
        kind is returned unchanged (``inserted`` False) whatever the count;
        ``None`` means the kind is new and ``limit`` client kinds already exist.
        """


#: Record lineage S4 (contract section 7.4): the service's commit-time recompute
#: of a Program reference block, returning the manifest's Program section.
type ProgramReferenceRecompute = Callable[[ProgramReferenceBlock], Mapping[str, object]]
#: Record lineage S3.1 (contract section 7.9): the service's commit-time
#: recompute of a lineage reference block, returning the manifest's lineage section.
type LineageReferenceRecompute = Callable[[LineageReferenceBlock], Mapping[str, object]]


def _now(at: datetime) -> datetime:
    if at.tzinfo is None:
        return at.replace(tzinfo=UTC)
    return at


#: The public token for each dependency refusal reason. A closed mapping, so a
#: reason without a token is a KeyError in tests rather than a silent fallback.
_DEPENDENCY_REASON_DETAIL: Mapping[DependencyRejection, SafeDetail] = {
    DependencyRejection.MISSING: SafeDetail.DEPENDENCY_MISSING,
    DependencyRejection.WRONG_CYCLE: SafeDetail.DEPENDENCY_WRONG_CYCLE,
    DependencyRejection.WRONG_FOCUS: SafeDetail.DEPENDENCY_WRONG_FOCUS,
    DependencyRejection.WRONG_STAGE: SafeDetail.DEPENDENCY_WRONG_STAGE,
    DependencyRejection.DUPLICATE_LANE: SafeDetail.DEPENDENCY_DUPLICATE_LANE,
    DependencyRejection.COUNT: SafeDetail.DEPENDENCY_COUNT,
    DependencyRejection.STALE: SafeDetail.DEPENDENCY_STALE,
    DependencyRejection.PARTIAL_INPUT: SafeDetail.DEPENDENCY_PARTIAL_INPUT,
}


def _translate(error: Exception) -> None:
    if isinstance(error, IntelligenceCoordinateError):
        raise InvalidRequestError(SafeDetail.STAGE) from None
    if isinstance(error, IntelligenceLimitError):
        raise InvalidRequestError(SafeDetail.BODY_MARKDOWN) from None
    if isinstance(error, IntelligenceDigestMismatchError):
        raise InvalidRequestError(SafeDetail.ADVISORY_DIGEST) from None
    if isinstance(error, IntelligenceDependencyError):
        if error.reason is DependencyRejection.PARTIAL_INPUT:
            raise InvalidRequestError(
                SafeDetail.DEPENDENCY_REPORT_IDS,
                SafeDetail.DEPENDENCY_PARTIAL_INPUT,
                SafeDetail.ARTIFACT_STATE,
            ) from None
        if error.reason is not None:
            raise InvalidRequestError(
                SafeDetail.DEPENDENCY_REPORT_IDS, _DEPENDENCY_REASON_DETAIL[error.reason]
            ) from None
        raise InvalidRequestError(SafeDetail.DEPENDENCY_REPORT_IDS) from None
    if isinstance(error, IntelligenceStaleReferenceError):
        if error.reason is not None:
            raise ConflictError(
                SafeDetail.DEPENDENCY_REPORT_IDS, _DEPENDENCY_REASON_DETAIL[error.reason]
            ) from None
        raise ConflictError(SafeDetail.ARTIFACT_ID) from None
    if isinstance(error, IntelligenceIdempotencyConflictError):
        raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
    if isinstance(error, IntelligenceVersionConflictError):
        raise ConflictError(SafeDetail.EXPECTED_VERSION) from None
    if isinstance(error, IntelligenceConflictError):
        raise ConflictError(SafeDetail.CYCLE_RUN_ID) from None
    raise error


# ---- the report type registry ------------------------------------------------
#
# Built-in kinds are authoritative in code and immutable; a Principal's client
# kinds are its own stored rows. A Principal with no stored row still has every
# built-in. Every refusal that lists kinds lists only the acting Principal's own,
# so one Principal's registry never reaches another's error.

#: Pipeline order, the first key of every registry listing.
#: The five built-in kinds' values: what a kindless `reports.latest` considers.
_BUILTIN_KIND_VALUES: Final = frozenset(kind.value for kind in ArtifactKind)

_STAGE_ORDER: Final[Mapping[IntelligenceStage, int]] = {
    stage: position for position, stage in enumerate(IntelligenceStage)
}


@dataclass(frozen=True, slots=True)
class ReportTypeRegistration:
    """The outcome of `reports.types.create`: the stored definition and how it got there."""

    definition: ReportTypeDefinition
    created: bool
    replayed: bool


def registered_report_types(
    store: IntelligenceStore, *, principal_id: str, stage: IntelligenceStage | None = None
) -> tuple[ReportTypeDefinition, ...]:
    """The built-in kinds merged with the Principal's own client kinds.

    Ordered by stage in pipeline order, then the built-in kind before the
    client kinds, then by kind. Stored built-in rows are ignored: the code's
    definitions are the authoritative ones.
    """
    merged = [
        definition
        for definition in builtin_report_type_definitions()
        if stage is None or definition.stage is stage
    ]
    merged.extend(
        row.definition
        for row in store.list_report_types(principal_id, stage=stage)
        if row.definition.origin is ReportTypeOrigin.CLIENT
    )
    merged.sort(
        key=lambda definition: (
            _STAGE_ORDER[definition.stage],
            definition.origin is not ReportTypeOrigin.BUILTIN,
            str(definition.artifact_kind),
        )
    )
    return tuple(merged)


def _kind_refusal(
    store: IntelligenceStore,
    *,
    principal_id: str,
    stage: IntelligenceStage | None,
    mismatch: bool,
) -> InvalidRequestError:
    """`invalid_request` on `artifact_kind`, listing the Principal's kinds for `stage`.

    A kind registered at another stage also names `stage`: the pair disagrees,
    and `stage` is the token that refusal carried before kinds were registered.
    """
    kinds = tuple(
        str(definition.artifact_kind)
        for definition in registered_report_types(store, principal_id=principal_id, stage=stage)
    )
    details = (
        (SafeDetail.STAGE, SafeDetail.ARTIFACT_KIND) if mismatch else (SafeDetail.ARTIFACT_KIND,)
    )
    return InvalidRequestError(*details, allowed_values={SafeDetail.ARTIFACT_KIND: kinds})


def _registered_stage(
    store: IntelligenceStore, *, principal_id: str, artifact_kind: str
) -> tuple[str, IntelligenceStage] | None:
    """The validated kind and the stage it is registered at, or None when unregistered."""
    try:
        kind = parse_artifact_kind(artifact_kind)
    except ValueError:
        return None
    if isinstance(kind, ArtifactKind):
        return kind, STAGE_FOR_KIND[kind]
    row = store.get_report_type(principal_id, kind)
    if row is None or row.definition.origin is not ReportTypeOrigin.CLIENT:
        return None
    return kind, row.definition.stage


def require_registered_kind(
    store: IntelligenceStore,
    *,
    principal_id: str,
    artifact_kind: str,
    stage: IntelligenceStage,
) -> str:
    """`artifact_kind` when the Principal has it registered at `stage`, else a refusal.

    An unregistered kind lists the kinds registered at `stage`; a kind
    registered at another stage lists the same and also names `stage`. A
    built-in kind is registered for every Principal at its own stage.
    """
    registered = _registered_stage(store, principal_id=principal_id, artifact_kind=artifact_kind)
    if registered is None:
        raise _kind_refusal(store, principal_id=principal_id, stage=stage, mismatch=False)
    kind, registered_at = registered
    if registered_at is not stage:
        raise _kind_refusal(store, principal_id=principal_id, stage=stage, mismatch=True)
    return kind


def _registered_filter(
    store: IntelligenceStore,
    *,
    principal_id: str,
    artifact_kind: str | None,
    stage: IntelligenceStage | None,
) -> str | None:
    """A read filter's kind, refused when the Principal has no such kind.

    The listing is narrowed to `stage` when the filter names one. A registered
    kind at another stage is not refused: the filters simply match nothing,
    exactly as two disagreeing built-in filters always have.
    """
    if artifact_kind is None:
        return None
    registered = _registered_stage(store, principal_id=principal_id, artifact_kind=artifact_kind)
    if registered is None:
        raise _kind_refusal(store, principal_id=principal_id, stage=stage, mismatch=False)
    return registered[0]


def register_report_type(
    store: IntelligenceStore,
    *,
    principal_id: str,
    artifact_kind: str,
    stage: IntelligenceStage,
    description: str,
    display_name: str | None,
    at: datetime,
) -> ReportTypeRegistration:
    """Register one client kind for the Principal, or replay an identical one.

    Insert-only. A built-in kind, or a kind already registered with a different
    definition, is a `conflict` on `artifact_kind`; so is a registry already
    holding `MAX_CLIENT_REPORT_TYPES` client kinds (with `max_items`). The
    Principal's built-in rows are ensured first, so the stored registry always
    carries them beside its client rows.
    """
    try:
        kind = parse_artifact_kind(artifact_kind)
    except ValueError:
        raise InvalidRequestError(SafeDetail.ARTIFACT_KIND) from None
    if isinstance(kind, ArtifactKind):
        raise ConflictError(SafeDetail.ARTIFACT_KIND)
    try:
        definition = ReportTypeDefinition(
            artifact_kind=kind,
            stage=stage,
            description=description,
            origin=ReportTypeOrigin.CLIENT,
            display_name=display_name,
        )
    except ValueError:
        raise InvalidRequestError(SafeDetail.PAYLOAD) from None
    when = _now(at)
    store.ensure_builtin_report_types(principal_id, created_at=when)
    # Check-then-insert under the store's per-Principal registration lock, so
    # two concurrent registrations can never both pass the cap.
    insertion = store.register_client_report_type(
        principal_id, definition, created_at=when, limit=MAX_CLIENT_REPORT_TYPES
    )
    if insertion is None:
        raise ConflictError(SafeDetail.ARTIFACT_KIND, SafeDetail.MAX_ITEMS)
    if insertion.inserted:
        return ReportTypeRegistration(definition=definition, created=True, replayed=False)
    existing = insertion.report_type
    if (
        existing.definition.origin is not ReportTypeOrigin.CLIENT
        or existing.definition_fingerprint != definition.fingerprint
    ):
        raise ConflictError(SafeDetail.ARTIFACT_KIND)
    return ReportTypeRegistration(definition=existing.definition, created=False, replayed=True)


def begin_cycle(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_id: str,
    business_date: date,
    idempotency_key: str,
    at: datetime,
    automation_platform: str | None,
    external_orchestration_id: str | None,
) -> MutationAdmission:
    """Create or replay one cycle execution identity."""
    try:
        if cycle_id != CYCLE_MORNING_INTELLIGENCE:
            raise IntelligenceCoordinateError("unknown cycle")
        fingerprint = fingerprint_payload(
            {
                "kind": "cycle_begin",
                "cycle_id": cycle_id,
                "business_date": business_date.isoformat(),
                "automation_platform": automation_platform,
                "external_orchestration_id": external_orchestration_id,
            }
        )
        existing = store.get_receipt(principal_id, idempotency_key)
        if existing is not None:
            if existing.fingerprint_sha256 != fingerprint:
                raise IntelligenceIdempotencyConflictError()
            cycle = store.get_cycle(principal_id, existing.cycle_run_id)
            if cycle is None:
                raise IntelligenceConflictError()
            return MutationAdmission(receipt=existing, created=False, replayed=True, cycle=cycle)
        if external_orchestration_id and automation_platform:
            bound = store.cycle_for_external_root(
                principal_id, automation_platform, external_orchestration_id
            )
            if bound is not None:
                raise IntelligenceConflictError()
        cycle_run_id = issue_identifier(IdKind.INTELLIGENCE_CYCLE_RUN)
        receipt_id = issue_identifier(IdKind.INTELLIGENCE_RECEIPT)
        when = _now(at)
        cycle = IntelligenceCycleRun(
            cycle_run_id=cycle_run_id,
            principal_id=principal_id,
            cycle_id=cycle_id,
            business_date=business_date,
            state=CycleState.OPEN,
            version=1,
            created_at=when,
            started_at=when,
            automation_platform=automation_platform,
            external_root_run_id=external_orchestration_id,
        )
        receipt = IntelligenceCommitReceipt(
            receipt_id=receipt_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            mutation_kind="cycle_begin",
            fingerprint_sha256=fingerprint,
            created_at=when,
            cycle_run_id=cycle_run_id,
        )
        if not store.put_receipt(receipt):
            stored = store.get_receipt(principal_id, idempotency_key)
            if stored is None:
                raise IntelligenceConflictError()
            if stored.fingerprint_sha256 != fingerprint:
                raise IntelligenceIdempotencyConflictError()
            stored_cycle = store.get_cycle(principal_id, stored.cycle_run_id)
            return MutationAdmission(
                receipt=stored, created=False, replayed=True, cycle=stored_cycle
            )
        store.put_cycle(cycle)
        return MutationAdmission(receipt=receipt, created=True, replayed=False, cycle=cycle)
    except Exception as error:
        _translate(error)
        raise


def _parse_provenance(
    rows: Sequence[Mapping[str, object]],
) -> tuple[IntelligenceProvenanceRef, ...]:
    parsed: list[IntelligenceProvenanceRef] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise IntelligenceCoordinateError("provenance")
        system = row.get("source_system")
        ref = row.get("source_ref")
        relation = row.get("relation")
        if not isinstance(system, str) or not isinstance(ref, str) or not isinstance(relation, str):
            raise IntelligenceCoordinateError("provenance")
        if len(system) > 64 or len(ref) > 256:
            raise IntelligenceLimitError("provenance")
        url = row.get("source_href", row.get("source_url"))
        if url is not None:
            if not isinstance(url, str) or len(url) > 512:
                raise IntelligenceLimitError("provenance")
            split = urlsplit(url)
            if split.scheme not in ALLOWED_PROVENANCE_URL_SCHEMES or not split.netloc:
                raise IntelligenceCoordinateError("provenance")
        subject = row.get("evidence_subject_id")
        parsed.append(
            IntelligenceProvenanceRef(
                source_system=system,
                source_ref=ref,
                relation=ProvenanceRelation(relation),
                source_url=url if isinstance(url, str) else None,
                evidence_subject_id=subject if isinstance(subject, str) else None,
            )
        )
    encoded = json.dumps(list(rows), default=str).encode("utf-8")
    if len(encoded) > MAX_STRUCTURED_CONTENT_BYTES:
        raise IntelligenceLimitError("provenance")
    return tuple(parsed)


def _upstream_matches_current_head(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    artifact: IntelligenceArtifact,
) -> bool:
    """Every recorded pipeline parent is that role's current head, recursively.

    Collector-only comparison would leave a Synthesizer current-ready after a
    Researcher rerun, and a Reporter current-ready after a Synthesizer rerun.
    """
    for dependency in artifact.dependencies:
        if dependency.expected_stage is None:
            return False
        # Every dependency is a built-in kind, so its role's head is the built-in one.
        current = store.current_head(
            principal_id,
            cycle_run_id,
            dependency.expected_stage,
            ARTIFACT_KIND_FOR_STAGE[dependency.expected_stage],
            dependency.expected_focus_area_id,
            dependency.expected_source_lane,
        )
        if current is None or current.artifact_id != dependency.upstream_artifact_id:
            return False
        parent = store.get_artifact(principal_id, dependency.upstream_artifact_id)
        if parent is None:
            return False
        if not _upstream_matches_current_head(
            store,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            artifact=parent,
        ):
            return False
    return True


def _member_lineage_is_stale(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    focus_area_id: FocusAreaId | None,
    artifact: IntelligenceArtifact,
) -> bool:
    if artifact.stage is not IntelligenceStage.COLLECTOR and focus_area_id is None:
        return True
    return not _upstream_matches_current_head(
        store,
        principal_id=principal_id,
        cycle_run_id=cycle_run_id,
        artifact=artifact,
    )


#: Resolver ``readiness_reason`` tokens for the sets the shared eligibility
#: predicate decides. Free strings on the wire; distinct so a caller can tell
#: an absent lane from a failed one and a moved upstream from a moved head.
REASON_READY: Final = "ready"
REASON_ELIGIBLE_PARTIAL: Final = "eligible_partial"
REASON_ABSENT: Final = "absent"
REASON_FAILED: Final = "failed"
REASON_PARTIAL_RUN_WITHOUT_ARTIFACT: Final = "partial_run_without_artifact"
REASON_STALE_UPSTREAM: Final = "stale_upstream"
REASON_NOT_CURRENT_HEAD: Final = "not_current_head"
REASON_SUPERSEDED: Final = "superseded"

#: Member states an upstream may be in and still be consumed.
_ELIGIBLE_STATES: Final = frozenset({ReadinessMemberState.READY, ReadinessMemberState.PARTIAL})


@dataclass(frozen=True, slots=True)
class Eligibility:
    """Whether one upstream artifact may be consumed, and why.

    The single answer both ``reports.commit`` (Synthesizer, Reporter and
    Morning Brief dependencies) and ``reports.resolve_set`` (``research_swarm``,
    ``synthesizer_inputs``, ``reporter_input``, ``morning_brief_inputs``) use,
    so the set the resolver calls eligible is exactly the set a commit accepts.
    """

    state: ReadinessMemberState
    reason: str
    artifact: IntelligenceArtifact | None = None
    run: IntelligenceProducerRun | None = None

    @property
    def eligible(self) -> bool:
        return self.state in _ELIGIBLE_STATES


def _collector_dependency(artifact: IntelligenceArtifact) -> str | None:
    return next(
        (
            dependency.upstream_artifact_id
            for dependency in artifact.dependencies
            if dependency.dependency_role == "collector"
        ),
        None,
    )


def artifact_eligibility(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    artifact: IntelligenceArtifact,
) -> Eligibility:
    """The shared eligibility predicate for one existing Researcher, Synthesizer or Reporter.

    Order matters only for the reason reported, never for the verdict:
    superseded, then not its coordinate's current head, then a moved upstream
    (a Researcher's Collector, or any recorded parent of a Synthesizer), then
    partial, then ready.
    """
    if artifact.artifact_state not in {ArtifactState.PARTIAL, ArtifactState.FINAL}:
        return Eligibility(ReadinessMemberState.SUPERSEDED, REASON_SUPERSEDED, artifact)
    head = store.current_head(
        principal_id,
        cycle_run_id,
        artifact.stage,
        artifact.artifact_kind,
        artifact.focus_area_id,
        artifact.source_lane,
    )
    if head is None or head.artifact_id != artifact.artifact_id:
        return Eligibility(ReadinessMemberState.STALE, REASON_NOT_CURRENT_HEAD, artifact)
    if artifact.stage is IntelligenceStage.RESEARCHER:
        collector = store.current_head(
            principal_id,
            cycle_run_id,
            IntelligenceStage.COLLECTOR,
            ArtifactKind.COLLECTOR_CANDIDATES,
            artifact.focus_area_id,
            None,
        )
        if collector is None or _collector_dependency(artifact) != collector.artifact_id:
            return Eligibility(ReadinessMemberState.STALE, REASON_STALE_UPSTREAM, artifact)
    elif _member_lineage_is_stale(
        store,
        principal_id=principal_id,
        cycle_run_id=cycle_run_id,
        focus_area_id=artifact.focus_area_id,
        artifact=artifact,
    ):
        return Eligibility(ReadinessMemberState.STALE, REASON_STALE_UPSTREAM, artifact)
    if artifact.artifact_state is ArtifactState.PARTIAL:
        return Eligibility(ReadinessMemberState.PARTIAL, REASON_ELIGIBLE_PARTIAL, artifact)
    return Eligibility(ReadinessMemberState.READY, REASON_READY, artifact)


def coordinate_eligibility(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    stage: IntelligenceStage,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
) -> Eligibility:
    """The shared predicate at a coordinate: its built-in head, or why there is none.

    Only the stage's built-in kind is ever consumed: a client kind registered at
    the stage is a standalone report with its own lineage, so neither its head
    nor its runs are consulted here. A coordinate with no head is never
    eligible. Its latest run says whether it is ``FAILED`` or ``MISSING``; a
    ``partial`` run with no artifact is ``MISSING`` too, because there is
    nothing to consume.
    """
    kind = ARTIFACT_KIND_FOR_STAGE[stage]
    run = store.failed_run(principal_id, cycle_run_id, stage, kind, focus_area_id, source_lane)
    head = store.current_head(principal_id, cycle_run_id, stage, kind, focus_area_id, source_lane)
    if head is None:
        if run is not None and run.state is ProducerRunState.FAILED:
            return Eligibility(ReadinessMemberState.FAILED, REASON_FAILED, None, run)
        if run is not None and run.state is ProducerRunState.PARTIAL:
            return Eligibility(
                ReadinessMemberState.MISSING, REASON_PARTIAL_RUN_WITHOUT_ARTIFACT, None, run
            )
        return Eligibility(ReadinessMemberState.MISSING, REASON_ABSENT, None, run)
    verdict = artifact_eligibility(
        store, principal_id=principal_id, cycle_run_id=cycle_run_id, artifact=head
    )
    return replace(verdict, run=run)


@dataclass(frozen=True, slots=True)
class MorningBriefGaps:
    """Which expected focus areas a Morning Brief cannot treat as complete.

    ``missing_focus_areas`` have no eligible Reporter (absent, failed, stale,
    superseded); ``partial_focus_areas`` have an eligible but partial one. Both
    are sorted focus-area ids, so the closed vocabulary is all they disclose.
    """

    missing_focus_areas: tuple[FocusAreaId, ...]
    partial_focus_areas: tuple[FocusAreaId, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_focus_areas and not self.partial_focus_areas


def morning_brief_gaps(verdicts: Mapping[FocusAreaId, Eligibility]) -> MorningBriefGaps:
    """The one gap rule both the brief commit and ``morning_brief_inputs`` apply.

    ``verdicts`` maps a focus area to its Reporter's shared-predicate verdict;
    an expected area with no verdict, or an ineligible one, is missing.
    """
    missing: list[FocusAreaId] = []
    partial: list[FocusAreaId] = []
    for area in EXPECTED_FOCUS_AREAS:
        verdict = verdicts.get(area)
        if verdict is None or not verdict.eligible:
            missing.append(area)
        elif verdict.state is ReadinessMemberState.PARTIAL:
            partial.append(area)
    return MorningBriefGaps(
        missing_focus_areas=tuple(sorted(missing, key=lambda area: area.value)),
        partial_focus_areas=tuple(sorted(partial, key=lambda area: area.value)),
    )


def _dependency_error(
    stage: IntelligenceStage, reason: DependencyRejection
) -> IntelligenceDependencyError:
    """The refusal for ``stage``. The Morning Brief keeps its original bare token."""
    if stage is IntelligenceStage.MORNING_BRIEF:
        return IntelligenceDependencyError()
    return IntelligenceDependencyError(reason)


def _require_eligible(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    artifact: IntelligenceArtifact,
) -> Eligibility:
    verdict = artifact_eligibility(
        store, principal_id=principal_id, cycle_run_id=cycle_run_id, artifact=artifact
    )
    if not verdict.eligible:
        raise IntelligenceStaleReferenceError(DependencyRejection.STALE)
    return verdict


def _validate_dependencies(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle: IntelligenceCycleRun,
    stage: IntelligenceStage,
    focus_area_id: FocusAreaId | None,
    dependency_ids: tuple[str, ...],
) -> tuple[tuple[IntelligencePipelineDependency, ...], bool]:
    """Validate named dependencies. Returns the lineage rows and whether any input is partial.

    Synthesizer: one or more Researcher heads of this cycle and focus, at most
    one per lane, each eligible under ``artifact_eligibility``. Reporter:
    exactly the eligible Synthesizer head. Morning Brief: zero to six eligible
    Reporter heads of distinct expected focus areas; any uncovered or partial
    area counts as partial input. Collector and Researcher keep their fixed
    counts.

    The rules are the stage's, whatever kind is committed: a client kind at a
    stage takes exactly the built-in kind's upstream stage, count and
    never-falsely-final rules. Every cited dependency must be the built-in kind
    of its stage; a client-kind artifact is never consumed (bare refusal).
    """
    if stage is IntelligenceStage.SYNTHESIZER:
        if len(dependency_ids) < MIN_SYNTHESIZER_DEPENDENCY_COUNT:
            raise IntelligenceDependencyError(DependencyRejection.COUNT)
    elif stage is IntelligenceStage.MORNING_BRIEF:
        if len(dependency_ids) > MAX_MORNING_BRIEF_DEPENDENCY_COUNT:
            raise _dependency_error(stage, DependencyRejection.COUNT)
    elif len(dependency_ids) != REQUIRED_DEPENDENCY_COUNT[stage]:
        raise _dependency_error(stage, DependencyRejection.COUNT)
    upstreams: list[IntelligenceArtifact] = []
    deps: list[IntelligencePipelineDependency] = []
    for artifact_id in dependency_ids:
        # Principal-scoped: another Principal's id is indistinguishable from none.
        artifact = store.get_artifact(principal_id, artifact_id)
        if artifact is None:
            raise _dependency_error(stage, DependencyRejection.MISSING)
        if artifact.cycle_run_id != cycle.cycle_run_id:
            raise _dependency_error(stage, DependencyRejection.WRONG_CYCLE)
        # Only built-in kinds are ever consumed. A client kind is a standalone
        # report: citing one, at any stage and for any committed kind, is the
        # bare dependency refusal.
        if artifact.artifact_kind != ARTIFACT_KIND_FOR_STAGE[artifact.stage]:
            raise IntelligenceDependencyError()
        upstreams.append(artifact)
    partial_input = False
    if stage is IntelligenceStage.RESEARCHER:
        collector = upstreams[0]
        if collector.stage is not IntelligenceStage.COLLECTOR:
            raise IntelligenceDependencyError(DependencyRejection.WRONG_STAGE)
        if collector.focus_area_id != focus_area_id:
            raise IntelligenceDependencyError(DependencyRejection.WRONG_FOCUS)
        current = store.current_head(
            principal_id,
            cycle.cycle_run_id,
            IntelligenceStage.COLLECTOR,
            ArtifactKind.COLLECTOR_CANDIDATES,
            focus_area_id,
            None,
        )
        if current is None or current.artifact_id != collector.artifact_id:
            raise IntelligenceStaleReferenceError(DependencyRejection.STALE)
        deps.append(
            IntelligencePipelineDependency(
                upstream_artifact_id=collector.artifact_id,
                dependency_role="collector",
                expected_stage=IntelligenceStage.COLLECTOR,
                expected_focus_area_id=focus_area_id,
            )
        )
    elif stage is IntelligenceStage.SYNTHESIZER:
        for item in upstreams:
            if item.stage is not IntelligenceStage.RESEARCHER or item.source_lane is None:
                raise IntelligenceDependencyError(DependencyRejection.WRONG_STAGE)
            if item.focus_area_id != focus_area_id:
                raise IntelligenceDependencyError(DependencyRejection.WRONG_FOCUS)
        lanes = [item.source_lane for item in upstreams]
        if len(set(lanes)) != len(lanes):
            raise IntelligenceDependencyError(DependencyRejection.DUPLICATE_LANE)
        collector_ids: set[str | None] = set()
        for item in upstreams:
            verdict = _require_eligible(
                store, principal_id=principal_id, cycle_run_id=cycle.cycle_run_id, artifact=item
            )
            partial_input = partial_input or verdict.state is ReadinessMemberState.PARTIAL
            collector_ids.add(_collector_dependency(item))
        # Implied by eligibility (every eligible Researcher cites the current
        # Collector head), kept as a defensive check on the single-Collector rule.
        if len(collector_ids) != 1 or None in collector_ids:
            raise IntelligenceStaleReferenceError(DependencyRejection.STALE)
        for item in upstreams:
            lane = item.source_lane
            if lane is None:  # pragma: no cover - refused above
                raise IntelligenceDependencyError(DependencyRejection.WRONG_STAGE)
            deps.append(
                IntelligencePipelineDependency(
                    upstream_artifact_id=item.artifact_id,
                    dependency_role=f"researcher:{lane.value}",
                    expected_stage=IntelligenceStage.RESEARCHER,
                    expected_focus_area_id=focus_area_id,
                    expected_source_lane=lane,
                )
            )
    elif stage is IntelligenceStage.REPORTER:
        synthesizer = upstreams[0]
        if synthesizer.stage is not IntelligenceStage.SYNTHESIZER:
            raise IntelligenceDependencyError(DependencyRejection.WRONG_STAGE)
        if focus_area_id is None or synthesizer.focus_area_id != focus_area_id:
            raise IntelligenceDependencyError(DependencyRejection.WRONG_FOCUS)
        verdict = _require_eligible(
            store,
            principal_id=principal_id,
            cycle_run_id=cycle.cycle_run_id,
            artifact=synthesizer,
        )
        partial_input = verdict.state is ReadinessMemberState.PARTIAL
        deps.append(
            IntelligencePipelineDependency(
                upstream_artifact_id=synthesizer.artifact_id,
                dependency_role="synthesizer",
                expected_stage=IntelligenceStage.SYNTHESIZER,
                expected_focus_area_id=focus_area_id,
            )
        )
    elif stage is IntelligenceStage.MORNING_BRIEF:
        areas = [item.focus_area_id for item in upstreams]
        if len(set(areas)) != len(areas) or not set(areas) <= set(EXPECTED_FOCUS_AREAS):
            raise IntelligenceDependencyError()
        verdicts: dict[FocusAreaId, Eligibility] = {}
        for item in upstreams:
            if item.stage is not IntelligenceStage.REPORTER or item.focus_area_id is None:
                raise IntelligenceDependencyError()
            # Superseded, not the current head, or a moved upstream: refused
            # with the brief's original bare stale token, never downgraded.
            verdict = artifact_eligibility(
                store,
                principal_id=principal_id,
                cycle_run_id=cycle.cycle_run_id,
                artifact=item,
            )
            if not verdict.eligible:
                raise IntelligenceStaleReferenceError()
            verdicts[item.focus_area_id] = verdict
            deps.append(
                IntelligencePipelineDependency(
                    upstream_artifact_id=item.artifact_id,
                    dependency_role=f"reporter:{item.focus_area_id.value}",
                    expected_stage=IntelligenceStage.REPORTER,
                    expected_focus_area_id=item.focus_area_id,
                )
            )
        partial_input = not morning_brief_gaps(verdicts).complete
    return tuple(deps), partial_input


def commit_artifact(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    stage: IntelligenceStage,
    artifact_kind: str,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
    producer_task_id: str,
    producer_task_name: str,
    automation_platform: str,
    automation_run_id: str | None,
    report_date: date,
    title: str,
    body_markdown: str,
    artifact_state: ArtifactState,
    schema_version: str,
    idempotency_key: str,
    at: datetime,
    coverage_start: datetime | None = None,
    coverage_end: datetime | None = None,
    producer_prompt_version: str | None = None,
    structured_content: dict[str, object] | None = None,
    dependency_report_ids: tuple[str, ...] = (),
    provenance: Sequence[Mapping[str, object]] = (),
    supersedes_artifact_id: str | None = None,
    advisory_digest: str | None = None,
    completeness: str | None = None,
    program_reference: ProgramReferenceRecompute | None = None,
    lineage_reference: LineageReferenceRecompute | None = None,
) -> MutationAdmission:
    """Atomically commit a producer run and immutable artifact.

    Record lineage S4 (contract section 7.4). `program_reference` is given
    exactly when the Program plane is admitted (both switches): then a
    `program_overview_ref` block in `structured_content` must have the section
    5.4 shape on a synthesizer, reporter or morning-brief artifact (a pure
    check, before anything is read: `invalid_request` / `structured_content`),
    and -- create path only, after the replay lookup and every remaining
    refusal check, immediately before the first write -- `program_reference`
    recomputes it; the section it returns is bound in the artifact's manifest.
    Without it the key is ordinary structured content.

    Record lineage S3.1 (contract section 7.9), the same way:
    `lineage_reference` is given exactly when `records.lineage.related` is
    served; then a `lineage_context_ref` block must have the section 7.9 shape
    on a synthesizer, reporter or morning-brief artifact (the same pure check)
    and, create path only, `lineage_reference` recomputes it after the Program
    recompute; the section it returns makes the manifest schema 2. Without it
    the key is ordinary structured content.
    """
    try:
        block: ProgramReferenceBlock | None = None
        lineage_block: LineageReferenceBlock | None = None
        if program_reference is not None:
            try:
                block = program_reference_block(structured_content, stage=stage)
            except ProgramReferenceError:
                raise InvalidRequestError(SafeDetail.STRUCTURED_CONTENT) from None
        if lineage_reference is not None:
            try:
                lineage_block = lineage_reference_block(structured_content, stage=stage)
            except LineageReferenceError:
                raise InvalidRequestError(SafeDetail.STRUCTURED_CONTENT) from None
        # First, as before, but inside the translated block: a registry lookup
        # fault is handled exactly like every other store fault of this commit.
        artifact_kind = require_registered_kind(
            store, principal_id=principal_id, artifact_kind=artifact_kind, stage=stage
        )
        try:
            validate_stage_coordinates(
                stage=stage,
                artifact_kind=artifact_kind,
                focus_area_id=focus_area_id,
                source_lane=source_lane,
            )
        except ValueError as error:
            raise IntelligenceCoordinateError() from error
        if (
            isinstance(artifact_kind, ArtifactKind)
            and artifact_kind is not ARTIFACT_KIND_FOR_STAGE[stage]
        ):
            raise IntelligenceCoordinateError()
        if artifact_state not in {ArtifactState.PARTIAL, ArtifactState.FINAL}:
            raise IntelligenceCoordinateError()
        body = content_utf8_bytes(body_markdown)
        if len(body) > MAX_ARTIFACT_BODY_BYTES:
            raise IntelligenceLimitError()
        digest = content_digest(body_markdown)
        if advisory_digest is not None and advisory_digest != digest:
            raise IntelligenceDigestMismatchError()
        if structured_content is not None:
            encoded = json.dumps(structured_content, sort_keys=True, default=str).encode("utf-8")
            if len(encoded) > MAX_STRUCTURED_CONTENT_BYTES:
                raise IntelligenceLimitError()
        refs = _parse_provenance(provenance)
        fingerprint = fingerprint_payload(
            {
                "kind": "artifact_commit",
                "cycle_run_id": cycle_run_id,
                "stage": stage.value,
                "artifact_kind": str(artifact_kind),
                "focus_area_id": None if focus_area_id is None else focus_area_id.value,
                "source_lane": None if source_lane is None else source_lane.value,
                "producer_task_id": producer_task_id,
                "producer_task_name": producer_task_name,
                "automation_platform": automation_platform,
                "automation_run_id": automation_run_id,
                "report_date": report_date.isoformat(),
                "title": title,
                "body_markdown": body_markdown,
                "artifact_state": artifact_state.value,
                "schema_version": schema_version,
                "producer_prompt_version": producer_prompt_version,
                "structured_content": structured_content,
                "dependency_report_ids": list(dependency_report_ids),
                "provenance": list(provenance),
                "supersedes_artifact_id": supersedes_artifact_id,
            }
        )
        existing = store.get_receipt(principal_id, idempotency_key)
        if existing is not None:
            if existing.fingerprint_sha256 != fingerprint:
                raise IntelligenceIdempotencyConflictError()
            artifact = (
                None
                if existing.artifact_id is None
                else store.get_artifact(principal_id, existing.artifact_id)
            )
            run = (
                None
                if existing.producer_run_id is None
                else store.get_run(principal_id, existing.producer_run_id)
            )
            return MutationAdmission(
                receipt=existing, created=False, replayed=True, artifact=artifact, run=run
            )
        cycle = store.get_cycle(principal_id, cycle_run_id)
        if cycle is None:
            raise IntelligenceCoordinateError()
        dependencies, partial_input = _validate_dependencies(
            store,
            principal_id=principal_id,
            cycle=cycle,
            stage=stage,
            focus_area_id=focus_area_id,
            dependency_ids=dependency_report_ids,
        )
        # A Synthesizer, Reporter or Morning Brief built over a partial input is
        # itself partial; for the brief an uncovered expected area is a partial
        # input too. A partial claim over complete inputs stays the producer's
        # choice. Never downgraded silently: a `final` claim is refused.
        if partial_input and artifact_state is not ArtifactState.PARTIAL:
            if stage is IntelligenceStage.MORNING_BRIEF:
                raise InvalidRequestError(SafeDetail.ARTIFACT_STATE)
            raise IntelligenceDependencyError(DependencyRejection.PARTIAL_INPUT)
        if automation_run_id:
            prior = store.run_for_external(
                principal_id, automation_platform, producer_task_id, automation_run_id
            )
            if prior is not None:
                raise IntelligenceConflictError()
        # The head of this kind's own lineage: a client kind never supersedes
        # (or is superseded by) the built-in kind at its stage.
        current = store.current_head(
            principal_id, cycle_run_id, stage, artifact_kind, focus_area_id, source_lane
        )
        if supersedes_artifact_id is not None and (
            current is None or current.artifact_id != supersedes_artifact_id
        ):
            raise IntelligenceStaleReferenceError()
        version = 1 if current is None else current.version + 1
        when = _now(at)
        run_id = issue_identifier(IdKind.INTELLIGENCE_RUN)
        artifact_id = issue_identifier(IdKind.INTELLIGENCE_ARTIFACT)
        receipt_id = issue_identifier(IdKind.INTELLIGENCE_RECEIPT)
        run_state = (
            ProducerRunState.PARTIAL
            if artifact_state is ArtifactState.PARTIAL
            else ProducerRunState.SUCCEEDED
        )
        run = IntelligenceProducerRun(
            run_id=run_id,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            stage=stage,
            artifact_kind=artifact_kind,
            state=run_state,
            version=1,
            producer_task_id=producer_task_id,
            producer_task_name=producer_task_name,
            automation_platform=automation_platform,
            report_date=report_date,
            created_at=when,
            focus_area_id=focus_area_id,
            source_lane=source_lane,
            automation_run_id=automation_run_id,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            started_at=when,
            finished_at=when,
        )
        artifact = IntelligenceArtifact(
            artifact_id=artifact_id,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            producer_run_id=run_id,
            stage=stage,
            artifact_kind=artifact_kind,
            report_date=report_date,
            title=title,
            body_markdown=body_markdown,
            content_sha256=digest,
            content_bytes=len(body),
            artifact_state=artifact_state,
            schema_version=schema_version,
            generated_at=when,
            committed_at=when,
            version=version,
            is_current=True,
            focus_area_id=focus_area_id,
            source_lane=source_lane,
            structured_content=structured_content,
            completeness=completeness,
            producer_prompt_version=producer_prompt_version,
            supersedes_artifact_id=current.artifact_id
            if current is not None
            else supersedes_artifact_id,
            dependencies=dependencies,
            provenance=refs,
        )
        receipt = IntelligenceCommitReceipt(
            receipt_id=receipt_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            mutation_kind="artifact_commit",
            fingerprint_sha256=fingerprint,
            created_at=when,
            cycle_run_id=cycle_run_id,
            producer_run_id=run_id,
            artifact_id=artifact_id,
            content_sha256=digest,
            content_bytes=len(body),
        )
        # S4 section 7.4 step 2: the recompute, after every refusal check and
        # before the first write; it runs on its own Program-pool snapshot and
        # records any failure in the section rather than refusing.
        program_section = (
            None if block is None or program_reference is None else program_reference(block)
        )
        # S3.1 section 7.9: the lineage recompute, at the same point and on the
        # same terms; any failure is recorded in the section, never a refusal.
        lineage_section = (
            None
            if lineage_block is None or lineage_reference is None
            else lineage_reference(lineage_block)
        )
        if not store.put_receipt(receipt):
            stored = store.get_receipt(principal_id, idempotency_key)
            if stored is None or stored.fingerprint_sha256 != fingerprint:
                raise IntelligenceIdempotencyConflictError()
            stored_artifact = (
                None
                if stored.artifact_id is None
                else store.get_artifact(principal_id, stored.artifact_id)
            )
            stored_run = (
                None
                if stored.producer_run_id is None
                else store.get_run(principal_id, stored.producer_run_id)
            )
            return MutationAdmission(
                receipt=stored,
                created=False,
                replayed=True,
                artifact=stored_artifact,
                run=stored_run,
            )
        if current is not None:
            store.mark_superseded(principal_id, current.artifact_id)
        store.put_run(run)
        store.put_artifact(
            artifact, program_section=program_section, lineage_section=lineage_section
        )
        return MutationAdmission(
            receipt=receipt, created=True, replayed=False, artifact=artifact, run=run, cycle=cycle
        )
    except Exception as error:
        _translate(error)
        raise


def record_run_state(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    stage: IntelligenceStage,
    artifact_kind: str,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
    producer_task_id: str,
    producer_task_name: str,
    automation_platform: str,
    automation_run_id: str | None,
    report_date: date,
    state: ProducerRunState,
    idempotency_key: str,
    at: datetime,
    expected_version: int | None,
    failure_code: str | None,
    failure_summary: str | None,
) -> MutationAdmission:
    """Persist running/failed/cancelled without requiring an artifact body.

    ``succeeded`` is admitted only when the exact (cycle, stage, focus, lane)
    coordinate already has a current artifact head. A stored receipt replays
    before that check, so retrying an accepted request still replays.
    """
    try:
        # First, as before, but inside the translated block: a registry lookup
        # fault is handled exactly like every other store fault of this commit.
        artifact_kind = require_registered_kind(
            store, principal_id=principal_id, artifact_kind=artifact_kind, stage=stage
        )
        try:
            validate_stage_coordinates(
                stage=stage,
                artifact_kind=artifact_kind,
                focus_area_id=focus_area_id,
                source_lane=source_lane,
            )
        except ValueError as error:
            raise IntelligenceCoordinateError() from error
        fingerprint = fingerprint_payload(
            {
                "kind": "run_state",
                "cycle_run_id": cycle_run_id,
                "stage": stage.value,
                "artifact_kind": str(artifact_kind),
                "focus_area_id": None if focus_area_id is None else focus_area_id.value,
                "source_lane": None if source_lane is None else source_lane.value,
                "producer_task_id": producer_task_id,
                "state": state.value,
                "automation_run_id": automation_run_id,
                "failure_code": failure_code,
            }
        )
        existing = store.get_receipt(principal_id, idempotency_key)
        if existing is not None:
            if existing.fingerprint_sha256 != fingerprint:
                raise IntelligenceIdempotencyConflictError()
            run = (
                None
                if existing.producer_run_id is None
                else store.get_run(principal_id, existing.producer_run_id)
            )
            return MutationAdmission(receipt=existing, created=False, replayed=True, run=run)
        cycle = store.get_cycle(principal_id, cycle_run_id)
        if cycle is None:
            raise IntelligenceCoordinateError()
        # `succeeded` asserts an artifact exists. Producers commit first (which
        # records its own succeeded run) and may then record `succeeded`; a
        # `succeeded` with nothing committed at this exact coordinate is refused.
        if state is ProducerRunState.SUCCEEDED and (
            store.current_head(
                principal_id, cycle_run_id, stage, artifact_kind, focus_area_id, source_lane
            )
            is None
        ):
            raise InvalidRequestError(SafeDetail.SELECTOR, SafeDetail.RUN_STATE_WITHOUT_ARTIFACT)
        when = _now(at)
        run_id = issue_identifier(IdKind.INTELLIGENCE_RUN)
        receipt_id = issue_identifier(IdKind.INTELLIGENCE_RECEIPT)
        run = IntelligenceProducerRun(
            run_id=run_id,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            stage=stage,
            artifact_kind=artifact_kind,
            state=state,
            version=1 if expected_version is None else expected_version + 1,
            producer_task_id=producer_task_id,
            producer_task_name=producer_task_name,
            automation_platform=automation_platform,
            report_date=report_date,
            created_at=when,
            focus_area_id=focus_area_id,
            source_lane=source_lane,
            automation_run_id=automation_run_id,
            started_at=when,
            finished_at=when
            if state
            in {ProducerRunState.FAILED, ProducerRunState.CANCELLED, ProducerRunState.SUCCEEDED}
            else None,
            failure_code=failure_code,
            failure_summary=failure_summary,
        )
        receipt = IntelligenceCommitReceipt(
            receipt_id=receipt_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            mutation_kind="run_state",
            fingerprint_sha256=fingerprint,
            created_at=when,
            cycle_run_id=cycle_run_id,
            producer_run_id=run_id,
        )
        if not store.put_receipt(receipt):
            stored = store.get_receipt(principal_id, idempotency_key)
            if stored is None or stored.fingerprint_sha256 != fingerprint:
                raise IntelligenceIdempotencyConflictError()
            stored_run = (
                None
                if stored.producer_run_id is None
                else store.get_run(principal_id, stored.producer_run_id)
            )
            return MutationAdmission(receipt=stored, created=False, replayed=True, run=stored_run)
        store.put_run(run)
        return MutationAdmission(
            receipt=receipt, created=True, replayed=False, run=run, cycle=cycle
        )
    except Exception as error:
        _translate(error)
        raise


def read_artifact(
    store: IntelligenceStore, *, principal_id: str, artifact_id: str
) -> IntelligenceArtifact:
    artifact = store.get_artifact(principal_id, artifact_id)
    if artifact is None:
        raise NotFoundError(SafeDetail.ARTIFACT_ID)
    return artifact


def latest_artifact(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    stage: IntelligenceStage | None,
    artifact_kind: str | None,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
    report_date: date | None,
) -> IntelligenceArtifact:
    artifact_kind = _registered_filter(
        store, principal_id=principal_id, artifact_kind=artifact_kind, stage=stage
    )
    if stage is not None and artifact_kind is None:
        # A stage-only latest is the built-in report of that stage, exactly as
        # before client kinds: a client kind is a standalone report and never
        # displaces the built-in head in a read view. Name the kind to read it.
        artifact_kind = ARTIFACT_KIND_FOR_STAGE[stage].value
    # Every other kindless latest -- no stage, or only a focus area, source lane
    # or report date -- also considers the built-in kinds only (operator ruling
    # N1): a client kind is returned only when the call names it.
    builtin_only = artifact_kind is None
    if store.get_cycle(principal_id, cycle_run_id) is None:
        raise NotFoundError(SafeDetail.CYCLE_RUN_ID)
    found = store.list_artifacts(
        principal_id,
        cycle_run_id=cycle_run_id,
        stage=stage,
        artifact_kind=artifact_kind,
        focus_area_id=focus_area_id,
        source_lane=source_lane,
        report_date=report_date,
        include_superseded=False,
        limit=1,
        builtin_only=builtin_only,
    )
    if not found:
        raise NotFoundError(SafeDetail.ARTIFACT_ID)
    return found[0]


def list_artifacts(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str | None,
    stage: IntelligenceStage | None,
    artifact_kind: str | None,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
    report_date: date | None,
    include_superseded: bool,
    page_size: int,
    after_committed_at: datetime | None = None,
    after_artifact_id: str | None = None,
) -> tuple[IntelligenceArtifact, ...]:
    artifact_kind = _registered_filter(
        store, principal_id=principal_id, artifact_kind=artifact_kind, stage=stage
    )
    return store.list_artifacts(
        principal_id,
        cycle_run_id=cycle_run_id,
        stage=stage,
        artifact_kind=artifact_kind,
        focus_area_id=focus_area_id,
        source_lane=source_lane,
        report_date=report_date,
        include_superseded=include_superseded,
        limit=page_size,
        after_committed_at=after_committed_at,
        after_artifact_id=after_artifact_id,
    )


def search_artifacts(
    store: IntelligenceStore,
    *,
    principal_id: str,
    query: str,
    cycle_run_id: str | None,
    stage: IntelligenceStage | None,
    artifact_kind: str | None,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
    page_size: int,
) -> tuple[tuple[IntelligenceArtifact, str], ...]:
    artifact_kind = _registered_filter(
        store, principal_id=principal_id, artifact_kind=artifact_kind, stage=stage
    )
    return store.search_artifacts(
        principal_id,
        query,
        cycle_run_id=cycle_run_id,
        stage=stage,
        artifact_kind=artifact_kind,
        focus_area_id=focus_area_id,
        source_lane=source_lane,
        limit=page_size,
    )


#: Resolver sets whose members the shared eligibility predicate decides.
_ELIGIBILITY_SETS: Final = frozenset(
    {
        ResolverSetId.RESEARCH_SWARM,
        ResolverSetId.SYNTHESIZER_INPUTS,
        ResolverSetId.REPORTER_INPUT,
        ResolverSetId.MORNING_BRIEF_INPUTS,
    }
)


def _member_state(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    set_id: ResolverSetId,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
) -> Eligibility:
    if set_id in {ResolverSetId.RESEARCH_SWARM, ResolverSetId.SYNTHESIZER_INPUTS}:
        return coordinate_eligibility(
            store,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.RESEARCHER,
            focus_area_id=focus_area_id,
            source_lane=source_lane,
        )
    if set_id is ResolverSetId.REPORTER_INPUT:
        return coordinate_eligibility(
            store,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.SYNTHESIZER,
            focus_area_id=focus_area_id,
            source_lane=None,
        )
    if set_id is ResolverSetId.MORNING_BRIEF_INPUTS:
        return coordinate_eligibility(
            store,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.REPORTER,
            focus_area_id=focus_area_id,
            source_lane=None,
        )
    # `collectors`: the original per-member rules.
    stage = IntelligenceStage.COLLECTOR
    area = focus_area_id
    kind = ArtifactKind.COLLECTOR_CANDIDATES
    current = store.current_head(principal_id, cycle_run_id, stage, kind, area, None)
    failed = store.failed_run(principal_id, cycle_run_id, stage, kind, area, None)

    def legacy(state: ReadinessMemberState, artifact: IntelligenceArtifact | None) -> Eligibility:
        return Eligibility(state, state.value.lower(), artifact, failed)

    if current is None:
        if failed is not None and failed.state is ProducerRunState.FAILED:
            return legacy(ReadinessMemberState.FAILED, None)
        if failed is not None and failed.state is ProducerRunState.PARTIAL:
            return legacy(ReadinessMemberState.PARTIAL, None)
        return legacy(ReadinessMemberState.MISSING, None)
    if current.artifact_state is ArtifactState.SUPERSEDED:
        return legacy(ReadinessMemberState.SUPERSEDED, current)
    if current.artifact_state is ArtifactState.PARTIAL:
        return legacy(ReadinessMemberState.PARTIAL, current)
    return legacy(ReadinessMemberState.READY, current)


def resolve_set(
    store: IntelligenceStore,
    *,
    principal_id: str,
    cycle_run_id: str,
    set_id: ResolverSetId,
    focus_area_id: FocusAreaId | None,
) -> dict[str, object]:
    """Resolve one declared set's members and aggregate.

    ``research_swarm``, ``synthesizer_inputs`` and ``reporter_input`` use the
    shared eligibility predicate, so their eligible members (``READY`` or
    ``PARTIAL``) are exactly what ``reports.commit`` accepts. Their aggregate is
    ``BLOCKED`` with no eligible member, ``DEGRADED`` when any eligible member is
    partial, and ``READY`` otherwise; an ineligible optional lane is reported
    and never blocks. ``morning_brief_inputs`` uses the same predicate per
    expected focus area and is never ``BLOCKED``: ``READY`` when every area's
    Reporter is eligible and final, ``DEGRADED`` otherwise, with the uncovered
    and partial areas named in ``missing_focus_areas`` and
    ``partial_focus_areas`` (empty for every other set). ``collectors`` keeps
    the every-member-required rule.
    """
    cycle = store.get_cycle(principal_id, cycle_run_id)
    if cycle is None:
        raise NotFoundError(SafeDetail.CYCLE_RUN_ID)
    needs_focus = set_id in {
        ResolverSetId.RESEARCH_SWARM,
        ResolverSetId.SYNTHESIZER_INPUTS,
        ResolverSetId.REPORTER_INPUT,
    }
    if needs_focus and focus_area_id is None:
        raise InvalidRequestError(SafeDetail.FOCUS_AREA_ID)
    if not needs_focus and focus_area_id is not None:
        raise InvalidRequestError(SafeDetail.FOCUS_AREA_ID)
    try:
        members_spec = expected_members(set_id, focus_area_id=focus_area_id)
    except ValueError:
        raise InvalidRequestError(SafeDetail.SET_ID) from None
    members: list[dict[str, object]] = []
    verdicts: list[Eligibility] = []
    required = REQUIRED_MEMBERSHIP[set_id]
    for key, area, lane in members_spec:
        verdict = _member_state(
            store,
            principal_id=principal_id,
            cycle_run_id=cycle_run_id,
            set_id=set_id,
            focus_area_id=area,
            source_lane=lane,
        )
        verdicts.append(verdict)
        artifact = verdict.artifact
        run = verdict.run
        members.append(
            {
                "member_id": key,
                "focus_area_id": None if area is None else area.value,
                "source_lane": None if lane is None else lane.value,
                "readiness": verdict.state.value,
                "required": required,
                "artifact_id": None if artifact is None else artifact.artifact_id,
                "producer_run_id": run.run_id
                if run is not None
                else None
                if artifact is None
                else artifact.producer_run_id,
                "content_sha256": None if artifact is None else artifact.content_sha256,
                "committed_at": None if artifact is None else artifact.committed_at.isoformat(),
                "readiness_reason": verdict.reason,
            }
        )
    gaps = MorningBriefGaps(missing_focus_areas=(), partial_focus_areas=())
    if set_id is ResolverSetId.MORNING_BRIEF_INPUTS:
        gaps = morning_brief_gaps(
            {
                area: verdict
                for (_, area, _), verdict in zip(members_spec, verdicts, strict=True)
                if area is not None
            }
        )
        aggregate = (
            ResolverAggregateState.READY if gaps.complete else ResolverAggregateState.DEGRADED
        )
    elif set_id in _ELIGIBILITY_SETS:
        eligible = [verdict for verdict in verdicts if verdict.eligible]
        if not eligible:
            aggregate = ResolverAggregateState.BLOCKED
        elif any(verdict.state is ReadinessMemberState.PARTIAL for verdict in eligible):
            aggregate = ResolverAggregateState.DEGRADED
        else:
            aggregate = ResolverAggregateState.READY
    else:
        blocking = required and any(
            verdict.state is not ReadinessMemberState.READY for verdict in verdicts
        )
        if blocking:
            aggregate = ResolverAggregateState.BLOCKED
        elif all(verdict.state is ReadinessMemberState.READY for verdict in verdicts):
            aggregate = ResolverAggregateState.READY
        else:
            aggregate = ResolverAggregateState.DEGRADED
    return {
        "cycle_run_id": cycle.cycle_run_id,
        "cycle_id": cycle.cycle_id,
        "business_date": cycle.business_date.isoformat(),
        "set_id": set_id.value,
        "aggregate": aggregate.value,
        "members": members,
        "missing_focus_areas": [area.value for area in gaps.missing_focus_areas],
        "partial_focus_areas": [area.value for area in gaps.partial_focus_areas],
    }


#: Serializes the FAST-tier store's registry check-then-insert. Module-level,
#: not a field, because worlds holding the store are copied and a lock cannot be.
_IN_MEMORY_REGISTRY_LOCK: Final = threading.Lock()


@dataclass
class InMemoryIntelligenceStore:
    """FAST-tier store. Immutability of bodies is a property of this class not writing them."""

    receipts: dict[tuple[str, str], IntelligenceCommitReceipt] = field(default_factory=dict)
    cycles: dict[tuple[str, str], IntelligenceCycleRun] = field(default_factory=dict)
    runs: dict[tuple[str, str], IntelligenceProducerRun] = field(default_factory=dict)
    artifacts: dict[tuple[str, str], IntelligenceArtifact] = field(default_factory=dict)
    report_types: dict[tuple[str, str], IntelligenceReportType] = field(default_factory=dict)
    #: S4 section 4.1: one manifest per artifact put through `put_artifact`; an
    #: artifact placed in `artifacts` directly is a legacy one.
    manifests: dict[tuple[str, str], RecordedManifest] = field(default_factory=dict)

    def get_receipt(
        self, principal_id: str, idempotency_key: str
    ) -> IntelligenceCommitReceipt | None:
        return self.receipts.get((principal_id, idempotency_key))

    def put_receipt(self, receipt: IntelligenceCommitReceipt) -> bool:
        key = (receipt.principal_id, receipt.idempotency_key)
        if key in self.receipts:
            return False
        self.receipts[key] = receipt
        return True

    def get_cycle(self, principal_id: str, cycle_run_id: str) -> IntelligenceCycleRun | None:
        return self.cycles.get((principal_id, cycle_run_id))

    def cycle_for_external_root(
        self, principal_id: str, platform: str, external_root_run_id: str
    ) -> IntelligenceCycleRun | None:
        for cycle in self.cycles.values():
            if (
                cycle.principal_id == principal_id
                and cycle.automation_platform == platform
                and cycle.external_root_run_id == external_root_run_id
            ):
                return cycle
        return None

    def put_cycle(self, cycle: IntelligenceCycleRun) -> None:
        self.cycles[(cycle.principal_id, cycle.cycle_run_id)] = cycle

    def get_run(self, principal_id: str, run_id: str) -> IntelligenceProducerRun | None:
        return self.runs.get((principal_id, run_id))

    def put_run(self, run: IntelligenceProducerRun) -> None:
        self.runs[(run.principal_id, run.run_id)] = run

    def replace_run(self, run: IntelligenceProducerRun, *, expected_version: int) -> bool:
        stored = self.runs.get((run.principal_id, run.run_id))
        if stored is None or stored.version != expected_version:
            return False
        self.runs[(run.principal_id, run.run_id)] = run
        return True

    def run_for_external(
        self,
        principal_id: str,
        platform: str,
        producer_task_id: str,
        automation_run_id: str,
    ) -> IntelligenceProducerRun | None:
        for run in self.runs.values():
            if (
                run.principal_id == principal_id
                and run.automation_platform == platform
                and run.producer_task_id == producer_task_id
                and run.automation_run_id == automation_run_id
            ):
                return run
        return None

    def get_artifact(self, principal_id: str, artifact_id: str) -> IntelligenceArtifact | None:
        return self.artifacts.get((principal_id, artifact_id))

    def put_artifact(
        self,
        artifact: IntelligenceArtifact,
        *,
        program_section: Mapping[str, object] | None = None,
        lineage_section: Mapping[str, object] | None = None,
    ) -> None:
        """Hold the artifact and build its manifest from the values held (S4 section 5.2).

        Not byte-comparable with the SQL path for a number JSONB renormalizes:
        this store hashes the value it holds.
        """
        key = (artifact.principal_id, artifact.artifact_id)
        self.artifacts[key] = artifact
        digests: list[DependencyDigests] = []
        for dependency in artifact.dependencies:
            upstream_key = (key[0], dependency.upstream_artifact_id)
            upstream = self.artifacts[upstream_key]
            recorded = self.manifests.get(upstream_key)
            digests.append(
                DependencyDigests(
                    report_id=dependency.upstream_artifact_id,
                    dependency_role=dependency.dependency_role,
                    required=dependency.required,
                    content_sha256=upstream.content_sha256,
                    structured_content_sha256=(
                        structured_content_sha256(upstream.structured_content)
                        if recorded is None
                        else recorded.structured_content_sha256
                    ),
                    manifest_sha256=None if recorded is None else recorded.manifest_sha256,
                    release_requirement=(
                        None
                        if recorded is None
                        else recorded_release_requirement(recorded.manifest_canonical)
                    ),
                )
            )
        built = build_manifest(
            artifact,
            stored_structured_content=artifact.structured_content,
            dependencies=digests,
            program=program_section,
            lineage=lineage_section,
        )
        self.manifests[key] = RecordedManifest(
            manifest_schema_version=built.manifest_schema_version,
            manifest_canonical=built.manifest_canonical,
            manifest_sha256=built.manifest_sha256,
            structured_content_sha256=built.structured_content_sha256,
            program_overview_sha256=built.program_overview_sha256,
            program_verification_state=built.program_verification_state,
        )

    def get_manifest(self, principal_id: str, artifact_id: str) -> RecordedManifest | None:
        return self.manifests.get((principal_id, artifact_id))

    def mark_superseded(self, principal_id: str, artifact_id: str) -> None:
        stored = self.artifacts.get((principal_id, artifact_id))
        if stored is None:
            return
        self.artifacts[(principal_id, artifact_id)] = replace(
            stored, is_current=False, artifact_state=ArtifactState.SUPERSEDED
        )

    def current_head(
        self,
        principal_id: str,
        cycle_run_id: str,
        stage: IntelligenceStage,
        artifact_kind: str,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
    ) -> IntelligenceArtifact | None:
        matches = [
            artifact
            for artifact in self.artifacts.values()
            if artifact.principal_id == principal_id
            and artifact.cycle_run_id == cycle_run_id
            and artifact.stage is stage
            and str(artifact.artifact_kind) == str(artifact_kind)
            and artifact.focus_area_id == focus_area_id
            and artifact.source_lane == source_lane
            and artifact.is_current
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: (item.committed_at, item.artifact_id), reverse=True)
        return matches[0]

    def list_artifacts(
        self,
        principal_id: str,
        *,
        cycle_run_id: str | None,
        stage: IntelligenceStage | None,
        artifact_kind: str | None,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
        report_date: date | None,
        include_superseded: bool,
        limit: int,
        after_committed_at: datetime | None = None,
        after_artifact_id: str | None = None,
        builtin_only: bool = False,
    ) -> tuple[IntelligenceArtifact, ...]:
        found = []
        for artifact in self.artifacts.values():
            if artifact.principal_id != principal_id:
                continue
            if cycle_run_id is not None and artifact.cycle_run_id != cycle_run_id:
                continue
            if stage is not None and artifact.stage is not stage:
                continue
            if artifact_kind is not None and artifact.artifact_kind != artifact_kind:
                continue
            if builtin_only and artifact.artifact_kind not in _BUILTIN_KIND_VALUES:
                continue
            if focus_area_id is not None and artifact.focus_area_id != focus_area_id:
                continue
            if source_lane is not None and artifact.source_lane != source_lane:
                continue
            if report_date is not None and artifact.report_date != report_date:
                continue
            if not include_superseded and (
                not artifact.is_current or artifact.artifact_state is ArtifactState.SUPERSEDED
            ):
                continue
            found.append(artifact)
        found.sort(key=lambda item: (item.committed_at, item.artifact_id), reverse=True)
        if after_committed_at is not None and after_artifact_id is not None:
            cursor = (after_committed_at, after_artifact_id)
            found = [
                artifact
                for artifact in found
                if (artifact.committed_at, artifact.artifact_id) < cursor
            ]
        return tuple(found[:limit])

    def search_artifacts(
        self,
        principal_id: str,
        query: str,
        *,
        cycle_run_id: str | None,
        stage: IntelligenceStage | None,
        artifact_kind: str | None,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
        limit: int,
    ) -> tuple[tuple[IntelligenceArtifact, str], ...]:
        needle = query.casefold()
        ranked: list[tuple[int, IntelligenceArtifact]] = []
        for artifact in self.list_artifacts(
            principal_id,
            cycle_run_id=cycle_run_id,
            stage=stage,
            artifact_kind=artifact_kind,
            focus_area_id=focus_area_id,
            source_lane=source_lane,
            report_date=None,
            include_superseded=False,
            limit=10_000,
        ):
            title_hit = needle in artifact.title.casefold()
            body_hit = needle in artifact.body_markdown.casefold()
            if not title_hit and not body_hit:
                continue
            score = 2 if title_hit else 0
            score += 1 if body_hit else 0
            ranked.append((score, artifact))
        ranked.sort(
            key=lambda item: (item[0], item[1].committed_at, item[1].artifact_id), reverse=True
        )
        results: list[tuple[IntelligenceArtifact, str]] = []
        for _score, artifact in ranked[:limit]:
            excerpt_source = (
                artifact.title if needle in artifact.title.casefold() else artifact.body_markdown
            )
            index = excerpt_source.casefold().find(needle)
            start = max(0, index - 40)
            snippet = excerpt_source[start : start + 120]
            results.append((artifact, snippet))
        return tuple(results)

    def failed_run(
        self,
        principal_id: str,
        cycle_run_id: str,
        stage: IntelligenceStage,
        artifact_kind: str,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
    ) -> IntelligenceProducerRun | None:
        matches = [
            run
            for run in self.runs.values()
            if run.principal_id == principal_id
            and run.cycle_run_id == cycle_run_id
            and run.stage is stage
            and str(run.artifact_kind) == str(artifact_kind)
            and run.focus_area_id == focus_area_id
            and run.source_lane == source_lane
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at, reverse=True)
        return matches[0]

    def list_report_types(
        self, principal_id: str, *, stage: IntelligenceStage | None = None
    ) -> tuple[IntelligenceReportType, ...]:
        found = [
            report_type
            for (owner, _kind), report_type in self.report_types.items()
            if owner == principal_id and (stage is None or report_type.definition.stage is stage)
        ]
        found.sort(
            key=lambda item: (item.definition.stage.value, str(item.definition.artifact_kind))
        )
        return tuple(found)

    def get_report_type(
        self, principal_id: str, artifact_kind: str
    ) -> IntelligenceReportType | None:
        return self.report_types.get((principal_id, str(artifact_kind)))

    def insert_report_type(
        self, principal_id: str, definition: ReportTypeDefinition, *, created_at: datetime
    ) -> ReportTypeInsertion:
        key = (principal_id, str(definition.artifact_kind))
        existing = self.report_types.get(key)
        if existing is not None:
            return ReportTypeInsertion(report_type=existing, inserted=False)
        stored = IntelligenceReportType(
            principal_id=principal_id,
            definition=definition,
            definition_fingerprint=definition.fingerprint,
            created_at=created_at,
        )
        self.report_types[key] = stored
        return ReportTypeInsertion(report_type=stored, inserted=True)

    def register_client_report_type(
        self,
        principal_id: str,
        definition: ReportTypeDefinition,
        *,
        created_at: datetime,
        limit: int,
    ) -> ReportTypeInsertion | None:
        with _IN_MEMORY_REGISTRY_LOCK:
            existing = self.report_types.get((principal_id, str(definition.artifact_kind)))
            if existing is not None:
                return ReportTypeInsertion(report_type=existing, inserted=False)
            clients = sum(
                row.definition.origin is ReportTypeOrigin.CLIENT
                for row in self.list_report_types(principal_id)
            )
            if clients >= limit:
                return None
            return self.insert_report_type(principal_id, definition, created_at=created_at)

    def ensure_builtin_report_types(self, principal_id: str, *, created_at: datetime) -> int:
        return sum(
            self.insert_report_type(principal_id, definition, created_at=created_at).inserted
            for definition in builtin_report_type_definitions()
        )
