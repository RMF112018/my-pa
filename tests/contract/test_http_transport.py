"""Every capability over a socket, and nothing decided on the way.

Three claims, and they are different in kind.

**Reachability.** Every one of the ninety-seven capabilities is addressable
over HTTP and answers. Parametrised over `Capability` rather than over a list
written here, so a ninety-eighth capability added to the domain arrives as a
failing row instead of as an untested one. Eight of the ninety-seven answer a
well-formed `501 unsupported` rather than a result — `_UNCOMPOSED_CAPABILITIES`,
the plane this harness does not switch on — and one, `tasks.bulk_confirm`,
answers a well-formed `404 not_found`, because a confirm names a preview this
harness never took. `_UNIMPLEMENTED_CAPABILITIES` is empty: WP-FE-03 implemented
the two placeholders it used to hold, and it is kept rather than deleted so the
next placeholder has somewhere to be recorded.

**Verbatim.** The bytes a caller receives are the bytes the envelope serialised
itself to — asserted as byte equality against the envelope the application
actually returned for that request, captured as it was returned. Running the
request a second time and comparing would have been weaker *and* wrong: a
correlation identifier is issued per invocation, and `sources.enroll` answers a
repeat of the same idempotency key with `created: false`, correctly. Recording
the one answer removes both problems and strengthens the claim from "equal after
the fields that differ are removed" to "the same bytes".

**Normalisation is the one validation path.** `normalize` is asserted to build
exactly the pair a hand-written command produces, per capability. This is the
half of `SPEC-AC-001` that HTTP can carry alone; the other half arrives with the
MCP adapter, which calls the same function.

The malformed-input section is separate and states its own rule: a request the
transport could not read is refused as `invalid_request`, with a status HTTP
already has a meaning for, and with nothing of the failure in the body.
"""

from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeCommitmentManagementUnitOfWork,
    FakeProviders,
    FakeTaskManagementUnitOfWork,
    FakeUnitOfWork,
    Scene,
    World,
    build_service,
    metadata_for,
    operator,
    seed_gsqs_b0_workflow,
    staged_capture,
    staged_commitment,
    staged_goodnotes_raster,
    staged_goodnotes_work,
    staged_managed_document,
    staged_review_case,
    staged_search,
    staged_task,
)
from tests.contract.test_transport_parity import (
    ENTITY_EMAIL,
    staged_archived_entity,
    staged_assignment,
    staged_child_records,
    staged_edge,
    staged_entities,
    staged_mention,
)
from tests.wire import Wire, serve

from my_pa.adapters.http import create_http_app
from my_pa.adapters.http.app import _STATUS
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.commands import (
    AddEntityAlias,
    ArchiveEntity,
    ArchiveManagedDocument,
    ArchiveRelationshipMemory,
    BeginIntelligenceCycle,
    BindEntityIdentifier,
    BulkConfirmTasks,
    BulkPreviewTasks,
    CloseCommitment,
    Command,
    CommitIntelligenceArtifact,
    CreateCapture,
    CreateCommitment,
    CreateEntity,
    CreateEntityAssignment,
    CreateEntityRelationship,
    CreateManagedDocument,
    CreateProject,
    CreateRelationshipMemory,
    CreateSituation,
    CreateTask,
    DecideReviewCase,
    EndEntityAssignment,
    EndEntityRelationship,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetCommitmentHistory,
    GetCorpusCoverage,
    GetEntity,
    GetEntityContext,
    GetEntityRelationships,
    GetGoodNotesContent,
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
    ListEntityAliases,
    ListEntityAssignments,
    ListEntityIdentifiers,
    ListEntityObservations,
    ListIntelligenceArtifacts,
    ListManagedDocuments,
    ListProjects,
    ListRelationshipMemories,
    ListReviewCases,
    ListSituations,
    ListSources,
    ListTasks,
    ListUnresolvedMentions,
    ObserveEntityMention,
    PrepareContext,
    ReadCapture,
    ReadCommitment,
    ReadIntelligenceArtifact,
    ReadKnowledge,
    ReadManagedDocument,
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
    RestoreRelationshipMemory,
    RetireEntityAlias,
    RetireEntityIdentifier,
    RevealSubject,
    ReviseCapture,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
    ReviseManagedDocument,
    ReviseRelationshipMemory,
    SearchCaptures,
    SearchCommitments,
    SearchEntities,
    SearchIntelligenceArtifacts,
    SearchKnowledge,
    SearchRelationshipMemories,
    SearchTasks,
    StartGsqsB0,
    SubmitGoodNotesProposal,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
    TransitionTask,
    UpdateCommitment,
    UpdateEntity,
    UpdateTask,
    WaitingOn,
)
from my_pa.application.intelligence import begin_cycle, commit_artifact
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import KnowledgeRecord, WorkCursorError
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.common.provenance import Provenance
from my_pa.domain.context.preference import ContextPreferenceAction
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ResolverSetId,
    SourceLaneId,
)
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    AssignmentType,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    IdentifierState,
)
from my_pa.domain.relationship.governance import (
    ObservationAuthority,
    ObservationKind,
    ResolutionDisposition,
)
from my_pa.domain.relationship.memory import MemoryKind, MemoryLifecycle
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    CommitmentWorkView,
    ContinuityEvidenceState,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import (
    TaskArchiveMode,
    TaskLifecycleState,
    TaskPriority,
    TaskWorkView,
)

ALL_CAPABILITIES = list(Capability)

_UNIMPLEMENTED_CAPABILITIES: frozenset[Capability] = frozenset()

#: The eight `relationship_memory.` names, which are implemented and are refused
#: here for a different reason: `RecordingService` below leaves
#: `relationship_memory_enabled` off, so
#: `ApplicationService._relationship_memory_plane` refuses each of them at the
#: composition floor. A build that turns it on answers them — `FakeUnitOfWork`
#: does carry the repository, and `tests/contract/test_transport_parity.py`
#: reads a staged memory through it over all three transports. Recorded apart
#: from `_UNIMPLEMENTED_CAPABILITIES` rather than folded into it, because
#: "nobody wrote it" and "this process did not turn it on" are different facts
#: and only one of them is about the plane's code.
#: `tests/contract/test_relationship_memory_capabilities.py` is where the
#: plane's answers are proved, against a real database.
#:
#: Reachability for these eight means what it means for every other name here:
#: the name is addressable, the request reaches the handler, and the refusal
#: comes back as this contract's own envelope rather than as a stack trace.
_UNCOMPOSED_CAPABILITIES = frozenset(
    {
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
    }
)

#: Every capability this harness expects a `501 unsupported` from, for either of
#: the two distinct reasons above. Only the second contributes today, because
#: WP-FE-03 implemented the two placeholders the first used to hold.
_UNSUPPORTED_CAPABILITIES = _UNIMPLEMENTED_CAPABILITIES | _UNCOMPOSED_CAPABILITIES

#: The memory the payload table and the command table below both name. Derived
#: from a fixed suffix rather than minted, because the two tables are compared
#: to each other and one that minted a fresh identifier on every call would be
#: comparing two different requests. Nothing is stored under it and nothing here
#: needs anything to be: the build refuses the eight at the composition floor
#: (see `_UNCOMPOSED_CAPABILITIES`), and what these payloads have to do is build
#: the command so `normalize` has a real pair to be compared against a
#: hand-written one.
MEMORY_ID = make_identifier(IdKind.RELATIONSHIP_MEMORY, "httpwire01httpwire01")


def a_permitted_purpose(capability: Capability) -> Purpose:
    """One purpose the domain permits for `capability`, derived from the rule."""
    return sorted(permitted_purposes(capability))[0]


def staged_record(scene: Scene) -> KnowledgeRecord:
    """One stored record, so `knowledge.read` has something to answer with."""
    record = KnowledgeRecord(
        knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        enrollment_id=scene.enrollment.enrollment_id,
        media_type="text/markdown",
        text="quarterly revenue review",
        is_truncated=False,
        provenance=Provenance(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
            version_id=scene.markdown.version_id,
            extractor="my_pa.text",
            extractor_version="1",
            observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            processed_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        ),
    )
    scene.world.records[(scene.enrollment.enrollment_id, record.knowledge_id)] = record
    return record


def payloads_for(scene: Scene, record: KnowledgeRecord) -> dict[Capability, dict[str, Any]]:
    """One well-formed JSON payload per capability, all inside `scene`'s scope.

    The capture payloads name no source and no enrollment, because a capture
    belongs to neither. One is staged first so that `capture.revise` and
    `capture.read` have a chain to append to and to read back.
    """
    capture = staged_capture(scene)
    review_case = staged_review_case(scene, capture)
    document = staged_managed_document(scene)
    task = staged_task(scene)
    commitment = staged_commitment(scene)
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    gsqs_run_id = str(seed_gsqs_b0_workflow(idempotency_key="http-gsqs-start")["run_id"])
    at = datetime(2026, 8, 2, 11, tzinfo=UTC)
    cycle_admission = begin_cycle(
        scene.world.intelligence,
        principal_id=scene.principal.principal_id,
        cycle_id=CYCLE_MORNING_INTELLIGENCE,
        business_date=date(2026, 8, 20),
        idempotency_key="http-cycle-setup",
        at=at,
        automation_platform=None,
        external_orchestration_id=None,
    )
    assert cycle_admission.cycle is not None
    cycle_run_id = cycle_admission.cycle.cycle_run_id
    collector_admission = commit_artifact(
        scene.world.intelligence,
        principal_id=scene.principal.principal_id,
        cycle_run_id=cycle_run_id,
        stage=IntelligenceStage.COLLECTOR,
        artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
        focus_area_id=FocusAreaId.COMMUNICATIONS,
        source_lane=None,
        producer_task_id="http-setup-collector",
        producer_task_name="HTTP setup collector",
        automation_platform="abacus_chatllm",
        automation_run_id=None,
        report_date=date(2026, 8, 20),
        title="HTTP setup collector",
        body_markdown="synthetic collector",
        artifact_state=ArtifactState.FINAL,
        schema_version="1",
        idempotency_key="http-setup-collector",
        at=at,
    )
    assert collector_admission.artifact is not None
    report_id = collector_admission.artifact.artifact_id
    person, organization = staged_entities(scene)
    identifier_id, alias_id = staged_child_records(scene)
    archived = staged_archived_entity(scene)
    # One staged record per directed write: this table is driven in one pass
    # over one scene, and a revise takes a record to version two, so a revise
    # and an end naming one row would leave the second meeting a stale
    # expectation.
    revise_assignment = staged_assignment(scene, "HTTP Revise Role")
    end_assignment = staged_assignment(scene, "HTTP End Role")
    revise_edge = staged_edge(scene, EntityRelationshipType.CONSULTANT_TO)
    end_edge = staged_edge(scene, EntityRelationshipType.REPRESENTS)
    return {
        Capability.CAPABILITIES_GET: {},
        Capability.SOURCES_LIST: {"source_id": scene.source.source_id},
        Capability.SOURCES_METADATA: {
            "source_id": scene.source.source_id,
            "source_object_id": scene.markdown.source_object_id,
        },
        Capability.SOURCES_FETCH: {
            "source_id": scene.source.source_id,
            "source_object_id": scene.markdown.source_object_id,
            "representation": "normalized_text",
        },
        Capability.SOURCES_STATUS: {"source_id": scene.source.source_id},
        Capability.SOURCES_ENROLL: {
            "source_id": scene.source.source_id,
            "media_types": ["text/markdown"],
            "idempotency_key": "http-probe-0001",
            "object_ids": [scene.markdown.source_object_id],
        },
        Capability.KNOWLEDGE_SEARCH: {
            "enrollment_id": scene.enrollment.enrollment_id,
            "query": "revenue",
        },
        Capability.KNOWLEDGE_READ: {
            "knowledge_id": record.knowledge_id,
            "enrollment_id": scene.enrollment.enrollment_id,
        },
        Capability.CAPTURE_CREATE: {
            "text": "a synthetic note",
            "idempotency_key": "http-capture-0001",
        },
        Capability.CAPTURE_REVISE: {
            "capture_id": capture.capture_id,
            "text": "a synthetic note, revised",
            "idempotency_key": "http-capture-revise-0001",
        },
        Capability.CAPTURE_READ: {"capture_id": capture.capture_id},
        Capability.CAPTURE_LIST: {},
        Capability.CAPTURE_SEARCH: {"query": "synthetic"},
        Capability.KNOWLEDGE_REVEAL: {"subject_id": capture.capture_id},
        Capability.REVIEW_LIST: {},
        Capability.CONTINUITY_PULSE: {},
        Capability.CONTINUITY_SITUATIONS: {},
        Capability.CONTINUITY_PROJECTS: {},
        Capability.CONTINUITY_PROJECTS_CREATE: {
            "name": "HTTP authoring project",
            "idempotency_key": "http-project-0001",
        },
        Capability.CONTINUITY_SITUATIONS_CREATE: {
            "title": "HTTP authoring situation",
            "idempotency_key": "http-situation-0001",
        },
        Capability.CONTINUITY_TASKS_CREATE: {
            "title": "HTTP authoring task",
            "idempotency_key": "http-task-0001",
        },
        # The corpus answer takes no payload: its subject is the acting
        # Principal, which no request may state.
        Capability.KNOWLEDGE_COVERAGE: {},
        Capability.REVIEW_DECIDE: {
            "review_case_id": review_case.review_case_id,
            "expected_review_version": 0,
            "disposition": "reject",
        },
        # The managed-document plane (WP-28). `document` is staged before the
        # world is copied per transport, so all three see the same stored chain
        # and a revise is the same revise everywhere. `content` is base64 on the
        # wire — JSON has no byte string — and no payload here carries a
        # `principal_id`, because the commands have no such field: the partition
        # comes from the authorization and cannot be stated.
        Capability.DOCUMENTS_CREATE: {
            "title": "Synthetic parity document",
            "media_type": "text/markdown",
            "content": b64encode(b"# Synthetic parity document").decode("ascii"),
            "idempotency_key": "parity-document-0001",
        },
        Capability.DOCUMENTS_REVISE: {
            "document_id": document.document_id,
            "expected_version_number": document.version_number,
            "title": "Synthetic parity document, revised",
            "media_type": "text/markdown",
            "content": b64encode(b"# Synthetic parity document, revised").decode("ascii"),
            "idempotency_key": "parity-document-revise-0001",
        },
        Capability.DOCUMENTS_READ: {
            "document_id": document.document_id,
            "version_id": document.version_id,
            "include_bytes": True,
        },
        Capability.DOCUMENTS_LIST: {"limit": 10, "include_archived": True},
        Capability.DOCUMENTS_ARCHIVE: {"document_id": document.document_id},
        Capability.DOCUMENTS_RESTORE: {"document_id": document.document_id},
        # The task-management plane (WP-TM-01..05). `task`/`commitment` are
        # staged before the world is copied per transport, so all three see the
        # same stored rows and a read is the same read everywhere.
        Capability.TASKS_READ: {"task_id": task.task_id},
        Capability.TASKS_LIST: {},
        Capability.TASKS_SEARCH: {"query": "synthetic"},
        Capability.TASKS_HISTORY: {"task_id": task.task_id},
        Capability.TASKS_CREATE: {
            "title": "HTTP task-plane task",
            "origin_evidence_ref": "cap_origin0001origin0001",
            "idempotency_key": "http-task-create-0001",
        },
        Capability.TASKS_UPDATE: {
            "task_id": task.task_id,
            "expected_version": task.version,
            "idempotency_key": "http-task-update-0001",
            "title": "HTTP task-plane task, revised",
        },
        Capability.TASKS_TRANSITION: {
            "task_id": task.task_id,
            "to_state": "in_progress",
            "expected_version": task.version,
            "idempotency_key": "http-task-transition-0001",
        },
        Capability.TASKS_BULK_PREVIEW: {
            "mutations": [
                {
                    "kind": "update",
                    "task_id": task.task_id,
                    "expected_version": task.version,
                    "values": {"title": "HTTP task-plane task, bulk-previewed"},
                    "clear_fields": [],
                }
            ],
            "idempotency_key": "http-task-bulk-preview-op-0001",
        },
        Capability.TASKS_BULK_CONFIRM: {
            "bulk_operation_id": issue_identifier(IdKind.BULK_OPERATION),
            "idempotency_key": "http-task-bulk-confirm-0001",
            "mutations": [
                {
                    "kind": "update",
                    "task_id": task.task_id,
                    "expected_version": task.version,
                    "values": {"title": "HTTP task-plane task, bulk-previewed"},
                    "clear_fields": [],
                }
            ],
        },
        Capability.COMMITMENTS_READ: {"commitment_id": commitment.commitment_id},
        Capability.COMMITMENTS_LIST: {},
        Capability.COMMITMENTS_SEARCH: {"query": "synthetic"},
        Capability.COMMITMENTS_HISTORY: {"commitment_id": commitment.commitment_id},
        Capability.COMMITMENTS_WAITING_ON: {},
        Capability.COMMITMENTS_CREATE: {
            "counterparty_person_id": commitment.counterparty_person_id,
            "direction": "owed_by_principal",
            "summary": "HTTP commitment-plane commitment",
            "origin_evidence_ref": "cap_origin0001origin0001",
            "idempotency_key": "http-commitment-create-0001",
        },
        Capability.COMMITMENTS_CLOSE: {
            "commitment_id": commitment.commitment_id,
            "expected_version": commitment.version,
            "closure_evidence_ref": "cap_origin0001origin0001",
            "idempotency_key": "http-commitment-close-0001",
        },
        Capability.COMMITMENTS_UPDATE: {
            "commitment_id": commitment.commitment_id,
            "expected_version": commitment.version,
            "idempotency_key": "http-commitment-update-0001",
            "summary": "HTTP commitment-plane commitment, revised",
        },
        Capability.CONTEXT_PREPARE: {"query": "revenue"},
        Capability.CONTEXT_FEEDBACK: {
            "action": "pin",
            "target_id": issue_identifier(IdKind.PROJECT),
            "idempotency_key": "http-feedback-0001",
        },
        Capability.GOODNOTES_WORK: {
            "run_id": work.run_id,
            "page_version_id": work.page_version_id,
        },
        Capability.GOODNOTES_CONTENT: {
            "run_id": raster.run_id,
            "page_version_id": raster.page_version_id,
            "content_sha256": work.content_sha256,
        },
        Capability.GOODNOTES_PROPOSE: {
            "run_id": work.run_id,
            "page_version_id": work.page_version_id,
            "content_sha256": work.content_sha256,
            "schema_version": "note-unit.v1",
            "analyzer_name": "synthetic",
            "analyzer_version": "1",
            "idempotency_key": "http-goodnotes-propose-0001",
            "segments": [
                {
                    "kind": "NOTE_UNIT",
                    "geometry": {
                        "x_min": 0.1,
                        "y_min": 0.1,
                        "width": 0.2,
                        "height": 0.2,
                    },
                    "transcription": "synthetic note",
                    "primary_class": "MEETING",
                }
            ],
        },
        Capability.GSQS_START: {
            "authorization_id": "synthetic-b0-commissioning",
            "campaign_class": "SYNTHETIC",
            "repetition": 1,
            "idempotency_key": "http-gsqs-start",
        },
        Capability.GSQS_STATUS: {"run_id": gsqs_run_id},
        Capability.REPORTS_BEGIN_CYCLE: {
            "cycle_id": CYCLE_MORNING_INTELLIGENCE,
            "business_date": "2026-08-20",
            "idempotency_key": "http-cycle-0001",
        },
        Capability.REPORTS_COMMIT: {
            "cycle_run_id": cycle_run_id,
            "stage": "collector",
            "artifact_kind": "collector_candidates",
            "focus_area_id": "communications",
            "producer_task_id": "http-collector",
            "producer_task_name": "HTTP Collector",
            "automation_platform": "abacus_chatllm",
            "report_date": "2026-08-20",
            "title": "HTTP collector",
            "body_markdown": "synthetic collector",
            "artifact_state": "final",
            "schema_version": "1",
            "idempotency_key": "http-report-commit-0001",
        },
        Capability.REPORTS_RECORD_RUN_STATE: {
            "cycle_run_id": cycle_run_id,
            "stage": "researcher",
            "artifact_kind": "research_context",
            "focus_area_id": "communications",
            "source_lane": "teams",
            "producer_task_id": "http-researcher",
            "producer_task_name": "HTTP Researcher",
            "automation_platform": "abacus_chatllm",
            "report_date": "2026-08-20",
            "state": "failed",
            "idempotency_key": "http-run-state-0001",
            "failure_code": "source_unavailable",
        },
        Capability.REPORTS_READ: {"report_id": report_id, "include_body": True},
        Capability.REPORTS_LATEST: {
            "cycle_run_id": cycle_run_id,
            "stage": "collector",
            "focus_area_id": "communications",
        },
        Capability.REPORTS_LIST: {"cycle_run_id": cycle_run_id, "page_size": 10},
        Capability.REPORTS_SEARCH: {
            "query": "synthetic",
            "cycle_run_id": cycle_run_id,
            "page_size": 10,
        },
        Capability.REPORTS_RESOLVE_SET: {
            "cycle_run_id": cycle_run_id,
            "set_id": "collectors",
        },
        # The relationship-intelligence entity plane (WP-RI-05). `person` and
        # `organization` are staged once per scene, so the payload table and the
        # command table below name the same two entities rather than each
        # staging a pair of its own.
        Capability.ENTITIES_SEARCH: {"query": "parity"},
        Capability.ENTITIES_GET: {"entity_id": person.entity_id},
        # The reference is the address bound to `person`, stated in its own
        # namespace rather than sniffed, so this answers a resolution rather
        # than the `not_found` outcome an unknown reference answers with — a
        # `200` either way, and the weaker of the two to be reachable by.
        Capability.ENTITIES_RESOLVE: {"reference": ENTITY_EMAIL, "namespace": "email"},
        Capability.ENTITIES_CONTEXT: {"entity_id": person.entity_id},
        Capability.ENTITIES_RELATIONSHIPS: {
            "entity_id": person.entity_id,
            "direction": "any",
        },
        # No arguments: the queue is every unplaced mention in the Principal's
        # own partition, so there is nothing to name.
        Capability.ENTITIES_UNRESOLVED_MENTIONS: {},
        # The entity plane's authoring half (`WP-RI-A-02`), staged so each of the
        # twelve answers rather than refuses: the subject is the same `person`
        # the reads above name, the child records are its staged binding and
        # alias, and the restore names the entity `staged_archived_entity` put
        # into the world already withdrawn. `expected_version` is 1 throughout,
        # which is what a staged row holds.
        Capability.ENTITIES_IDENTIFIERS_LIST: {
            "entity_id": person.entity_id,
            "states": ["active"],
            "page_size": 10,
        },
        Capability.ENTITIES_ALIASES_LIST: {
            "entity_id": person.entity_id,
            "states": ["active"],
            "alias_types": ["nickname"],
            "page_size": 10,
        },
        Capability.ENTITIES_CREATE: {
            "entity_type": "person",
            "display_name": "HTTP Newcomer",
            "aliases": [{"alias_type": "nickname", "display_value": "Newk"}],
            "identifiers": [
                {"namespace": "email", "display_value": "http.newcomer@example.invalid"}
            ],
            "reason": "A synthetic creation.",
            "idempotency_key": "http-entity-create-0001",
        },
        Capability.ENTITIES_UPDATE: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "display_name": "Parity Person",
            "status": "inactive",
            "reason": "A synthetic correction.",
            "idempotency_key": "http-entity-update-0001",
        },
        Capability.ENTITIES_ARCHIVE: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "reason": "A synthetic withdrawal.",
            "idempotency_key": "http-entity-archive-0001",
        },
        Capability.ENTITIES_RESTORE: {
            "entity_id": archived.entity_id,
            "expected_version": archived.version,
            "reason": "A synthetic restoration.",
            "idempotency_key": "http-entity-restore-0001",
        },
        Capability.ENTITIES_IDENTIFIERS_BIND: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "namespace": "teams_user_id",
            "display_value": "http-teams-user",
            "effective_from": "2026-08-02T12:00:00Z",
            "reason": "A synthetic binding.",
            "idempotency_key": "http-entity-bind-0001",
        },
        Capability.ENTITIES_IDENTIFIERS_RETIRE: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "identifier_id": identifier_id,
            "expected_identifier_version": 1,
            "reason": "A synthetic retirement.",
            "idempotency_key": "http-entity-retire-identifier-0001",
        },
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "identifier_id": identifier_id,
            "expected_identifier_version": 1,
            "namespace": "email",
            "display_value": "http.person.new@example.invalid",
            "reason": "A synthetic replacement.",
            "idempotency_key": "http-entity-supersede-identifier-0001",
        },
        Capability.ENTITIES_ALIASES_ADD: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "alias_type": "initials",
            "display_value": "PP",
            "reason": "A synthetic addition.",
            "idempotency_key": "http-entity-add-alias-0001",
        },
        Capability.ENTITIES_ALIASES_RETIRE: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "alias_id": alias_id,
            "expected_alias_version": 1,
            "reason": "A synthetic retirement.",
            "idempotency_key": "http-entity-retire-alias-0001",
        },
        Capability.ENTITIES_ALIASES_SUPERSEDE: {
            "entity_id": person.entity_id,
            "expected_version": 1,
            "alias_id": alias_id,
            "expected_alias_version": 1,
            "alias_type": "nickname",
            "display_value": "HTTP Buddy",
            "reason": "A synthetic correction.",
            "idempotency_key": "http-entity-supersede-alias-0001",
        },
        # The directed-relationship family (WP-RI-A-03). The payloads carry no
        # marker for the reason the six reads above carry none: every field on
        # them is an opaque identifier, a closed vocabulary member or a version,
        # and the freest text a caller may send here -- a `role`, or the `reason`
        # an `end` carries -- is a descriptor of the *record*, not a statement
        # about the person.
        #
        # **Each of the six writes meets a record of its own.** They are driven
        # in one pass over one scene, and a revise takes the version to two, so
        # a revise and an end sharing a staged row would leave the second
        # meeting a stale expectation and answering `conflict` -- a refusal the
        # sweeps here would read as the plane declining to act.
        Capability.ENTITIES_ASSIGNMENTS_LIST: {"entity_id": person.entity_id},
        Capability.ENTITIES_ASSIGNMENTS_CREATE: {
            "entity_id": person.entity_id,
            "expected_entity_version": 1,
            "assignment_type": "team_membership",
            "idempotency_key": "http-assignment-create-0001",
        },
        Capability.ENTITIES_ASSIGNMENTS_REVISE: {
            "assignment_id": revise_assignment,
            "expected_version": 1,
            "role": "Synthetic Revised Role",
            "idempotency_key": "http-assignment-revise-0001",
        },
        Capability.ENTITIES_ASSIGNMENTS_END: {
            "assignment_id": end_assignment,
            "expected_version": 1,
            "reason": "A synthetic withdrawal.",
            "end_now": True,
            "idempotency_key": "http-assignment-end-0001",
        },
        Capability.ENTITIES_RELATIONSHIPS_CREATE: {
            "from_entity_id": person.entity_id,
            "expected_from_version": 1,
            "relationship_type": "member_of",
            "to_entity_id": organization.entity_id,
            "expected_to_version": 1,
            "idempotency_key": "http-relationship-create-0001",
        },
        Capability.ENTITIES_RELATIONSHIPS_REVISE: {
            "relationship_id": revise_edge,
            "expected_version": 1,
            "idempotency_key": "http-relationship-revise-0001",
        },
        Capability.ENTITIES_RELATIONSHIPS_END: {
            "relationship_id": end_edge,
            "expected_version": 1,
            "reason": "A synthetic withdrawal.",
            "end_now": True,
            "idempotency_key": "http-relationship-end-0001",
        },
        # The observation log. No arguments for the same reason: it answers
        # about the Principal's own partition and there is nothing to name.
        Capability.ENTITIES_OBSERVATIONS_LIST: {},
        # `entities.observe` names a **product-owned capture** rather than a
        # source object version. The source-backed authority requires a source
        # object this product has actually read, which would be staging a
        # refusal this payload is not about; `user_authored_statement` is the
        # authority a capture origin admits and `user_statement` is the kind it
        # requires.
        Capability.ENTITIES_OBSERVE: {
            "kind": "user_statement",
            "authority": "user_authored_statement",
            "observed_value": "Parity Person",
            "mention_display_name": "Parity Person",
            "capture_id": "cap_httpobserve0001",
            "capture_version_id": "capver_httpobserve0001",
            "observed_at": "2026-08-02T10:00:00Z",
            "idempotency_key": "http-entities-observe-0001",
        },
        # `defer`, because a disposition that binds an identity would make this
        # row's answer depend on what the resolver found rather than on the
        # transport. The mention is the shared staged one.
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE: {
            "observation_id": staged_mention(scene),
            "expected_resolution_version": 0,
            "disposition": "defer",
            "reason": "there is not enough identity evidence yet",
            "idempotency_key": "http-entities-resolve-0001",
        },
        # The Relationship Memory plane (WP-RM-01). A memory names an Entity, so
        # the subject is the same staged `person` the entity payloads name; the
        # memory itself is `MEMORY_ID`, a derived rather than minted identifier
        # shared with the command table below, because two tables each minting
        # one would compare two different requests. Nothing is stored under it —
        # this build leaves the memory plane off, see
        # `_UNCOMPOSED_CAPABILITIES` — and nothing here needs anything to be:
        # what these payloads have to do is build the command, so that
        # `normalize` has a real pair to be compared against a hand-written one.
        #
        # `kind`, `kinds` and `lifecycle` are sent as their vocabulary strings
        # and `observed_at` as an RFC 3339 string, because that is what a caller
        # sends and the coercion from each to the domain value is
        # `adapters/normalization.py`'s work — which is exactly what the
        # normalisation comparison below is for.
        Capability.RELATIONSHIP_MEMORY_CREATE: {
            "entity_id": person.entity_id,
            "statement": "A synthetic memory-plane note",
            "idempotency_key": "http-memory-create-0001",
            "kind": "personal_detail",
            "observed_at": "2026-08-02T10:00:00Z",
        },
        Capability.RELATIONSHIP_MEMORY_GET: {
            "memory_id": MEMORY_ID,
            "include_statement": True,
        },
        Capability.RELATIONSHIP_MEMORY_LIST: {
            "entity_id": person.entity_id,
            "kinds": ["personal_detail"],
            "lifecycle": "active",
            "page_size": 10,
        },
        Capability.RELATIONSHIP_MEMORY_SEARCH: {"query": "synthetic", "page_size": 10},
        Capability.RELATIONSHIP_MEMORY_HISTORY: {"memory_id": MEMORY_ID, "page_size": 10},
        Capability.RELATIONSHIP_MEMORY_REVISE: {
            "memory_id": MEMORY_ID,
            "expected_version": 1,
            "statement": "A synthetic memory-plane note, revised",
            "idempotency_key": "http-memory-revise-0001",
            "correction_reason": "the contract table revised it",
        },
        Capability.RELATIONSHIP_MEMORY_ARCHIVE: {
            "memory_id": MEMORY_ID,
            "expected_version": 1,
            "idempotency_key": "http-memory-archive-0001",
        },
        Capability.RELATIONSHIP_MEMORY_RESTORE: {
            "memory_id": MEMORY_ID,
            "expected_version": 1,
            "idempotency_key": "http-memory-restore-0001",
        },
    }


def commands_for(
    scene: Scene,
    record: KnowledgeRecord,
    capture_id: str,
    bulk_operation_id: str,
    counterparty_person_id: str,
    feedback_target_id: str,
) -> dict[Capability, Command]:
    """The same requests, written as commands rather than as JSON.

    `capture_id`, `bulk_operation_id`, and `counterparty_person_id` are
    parameters rather than staged or minted here: the payload table and this
    table have to name the *same* capture, bulk operation, and counterparty or
    the comparison below would be between two different requests, and each
    minting its own would guarantee they were.

    Written by hand rather than produced by `normalize`, which is the point: the
    normalisation test below compares the two, and a comparison against the
    function under test would prove only that it agrees with itself.
    """
    document = staged_managed_document(scene)
    task = staged_task(scene)
    commitment = staged_commitment(scene)
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    gsqs_run_id = str(seed_gsqs_b0_workflow(idempotency_key="http-gsqs-start")["run_id"])
    at = datetime(2026, 8, 2, 11, tzinfo=UTC)
    cycle_admission = begin_cycle(
        scene.world.intelligence,
        principal_id=scene.principal.principal_id,
        cycle_id=CYCLE_MORNING_INTELLIGENCE,
        business_date=date(2026, 8, 20),
        idempotency_key="http-cycle-setup",
        at=at,
        automation_platform=None,
        external_orchestration_id=None,
    )
    assert cycle_admission.cycle is not None
    cycle_run_id = cycle_admission.cycle.cycle_run_id
    collector_admission = commit_artifact(
        scene.world.intelligence,
        principal_id=scene.principal.principal_id,
        cycle_run_id=cycle_run_id,
        stage=IntelligenceStage.COLLECTOR,
        artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
        focus_area_id=FocusAreaId.COMMUNICATIONS,
        source_lane=None,
        producer_task_id="http-setup-collector",
        producer_task_name="HTTP setup collector",
        automation_platform="abacus_chatllm",
        automation_run_id=None,
        report_date=date(2026, 8, 20),
        title="HTTP setup collector",
        body_markdown="synthetic collector",
        artifact_state=ArtifactState.FINAL,
        schema_version="1",
        idempotency_key="http-setup-collector",
        at=at,
    )
    assert collector_admission.artifact is not None
    report_id = collector_admission.artifact.artifact_id
    person, organization = staged_entities(scene)
    identifier_id, alias_id = staged_child_records(scene)
    archived = staged_archived_entity(scene)
    # The same staged rows the payload table names, for the reason `person` is
    # the same one: two tables each staging their own would be comparing two
    # different requests. `staged_assignment` and `staged_edge` are memoized per
    # scene per key, so both tables reach the same rows.
    revise_assignment = staged_assignment(scene, "HTTP Revise Role")
    end_assignment = staged_assignment(scene, "HTTP End Role")
    revise_edge = staged_edge(scene, EntityRelationshipType.CONSULTANT_TO)
    end_edge = staged_edge(scene, EntityRelationshipType.REPRESENTS)
    return {
        Capability.CAPABILITIES_GET: GetCapabilities(),
        Capability.SOURCES_LIST: ListSources(source_id=scene.source.source_id),
        Capability.SOURCES_METADATA: GetSourceMetadata(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
        ),
        Capability.SOURCES_FETCH: FetchSource(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
            representation=Representation.NORMALIZED_TEXT,
        ),
        Capability.SOURCES_STATUS: GetSourceStatus(source_id=scene.source.source_id),
        Capability.SOURCES_ENROLL: EnrollSource(
            source_id=scene.source.source_id,
            media_types=("text/markdown",),
            idempotency_key="http-probe-0001",
            object_ids=(scene.markdown.source_object_id,),
        ),
        Capability.KNOWLEDGE_SEARCH: SearchKnowledge(
            enrollment_id=scene.enrollment.enrollment_id, query="revenue"
        ),
        Capability.KNOWLEDGE_READ: ReadKnowledge(
            knowledge_id=record.knowledge_id,
            enrollment_id=scene.enrollment.enrollment_id,
        ),
        Capability.CAPTURE_CREATE: CreateCapture(
            text="a synthetic note",
            idempotency_key="http-capture-0001",
        ),
        Capability.CAPTURE_REVISE: ReviseCapture(
            capture_id=capture_id,
            text="a synthetic note, revised",
            idempotency_key="http-capture-revise-0001",
        ),
        Capability.CAPTURE_READ: ReadCapture(capture_id=capture_id),
        Capability.CAPTURE_LIST: ListCaptures(),
        Capability.CAPTURE_SEARCH: SearchCaptures(query="synthetic"),
        Capability.KNOWLEDGE_REVEAL: RevealSubject(subject_id=capture_id),
        Capability.REVIEW_LIST: ListReviewCases(),
        Capability.CONTINUITY_PULSE: GetPulse(),
        Capability.CONTINUITY_SITUATIONS: ListSituations(),
        Capability.CONTINUITY_PROJECTS: ListProjects(),
        Capability.CONTINUITY_PROJECTS_CREATE: CreateProject(
            name="HTTP authoring project", idempotency_key="http-project-0001"
        ),
        Capability.CONTINUITY_SITUATIONS_CREATE: CreateSituation(
            title="HTTP authoring situation", idempotency_key="http-situation-0001"
        ),
        Capability.CONTINUITY_TASKS_CREATE: RecordTask(
            title="HTTP authoring task", idempotency_key="http-task-0001"
        ),
        Capability.KNOWLEDGE_COVERAGE: GetCorpusCoverage(),
        Capability.REVIEW_DECIDE: DecideReviewCase(
            review_case_id=staged_review_case(scene).review_case_id,
            expected_review_version=0,
            disposition=Disposition.REJECT,
        ),
        Capability.DOCUMENTS_CREATE: CreateManagedDocument(
            title="Synthetic parity document",
            media_type="text/markdown",
            content=b"# Synthetic parity document",
            idempotency_key="parity-document-0001",
        ),
        Capability.DOCUMENTS_REVISE: ReviseManagedDocument(
            document_id=document.document_id,
            expected_version_number=document.version_number,
            title="Synthetic parity document, revised",
            media_type="text/markdown",
            content=b"# Synthetic parity document, revised",
            idempotency_key="parity-document-revise-0001",
        ),
        Capability.DOCUMENTS_READ: ReadManagedDocument(
            document_id=document.document_id,
            version_id=document.version_id,
            include_bytes=True,
        ),
        Capability.DOCUMENTS_LIST: ListManagedDocuments(limit=10, include_archived=True),
        Capability.DOCUMENTS_ARCHIVE: ArchiveManagedDocument(document_id=document.document_id),
        Capability.DOCUMENTS_RESTORE: RestoreManagedDocument(document_id=document.document_id),
        Capability.TASKS_READ: ReadTask(task_id=task.task_id),
        Capability.TASKS_LIST: ListTasks(),
        Capability.TASKS_SEARCH: SearchTasks(query="synthetic"),
        Capability.TASKS_HISTORY: GetTaskHistory(task_id=task.task_id),
        Capability.TASKS_CREATE: CreateTask(
            title="HTTP task-plane task",
            origin_evidence_ref="cap_origin0001origin0001",
            idempotency_key="http-task-create-0001",
        ),
        Capability.TASKS_UPDATE: UpdateTask(
            task_id=task.task_id,
            expected_version=task.version,
            idempotency_key="http-task-update-0001",
            title="HTTP task-plane task, revised",
        ),
        Capability.TASKS_TRANSITION: TransitionTask(
            task_id=task.task_id,
            to_state=TaskLifecycleState.IN_PROGRESS,
            expected_version=task.version,
            idempotency_key="http-task-transition-0001",
        ),
        Capability.TASKS_BULK_PREVIEW: BulkPreviewTasks(
            mutations=(
                {
                    "kind": "update",
                    "task_id": task.task_id,
                    "expected_version": task.version,
                    "values": {"title": "HTTP task-plane task, bulk-previewed"},
                    "clear_fields": [],
                },
            ),
            idempotency_key="http-task-bulk-preview-op-0001",
        ),
        Capability.TASKS_BULK_CONFIRM: BulkConfirmTasks(
            bulk_operation_id=bulk_operation_id,
            idempotency_key="http-task-bulk-confirm-0001",
            mutations=(
                {
                    "kind": "update",
                    "task_id": task.task_id,
                    "expected_version": task.version,
                    "values": {"title": "HTTP task-plane task, bulk-previewed"},
                    "clear_fields": [],
                },
            ),
        ),
        Capability.COMMITMENTS_READ: ReadCommitment(commitment_id=commitment.commitment_id),
        Capability.COMMITMENTS_LIST: ListCommitments(),
        Capability.COMMITMENTS_SEARCH: SearchCommitments(query="synthetic"),
        Capability.COMMITMENTS_HISTORY: GetCommitmentHistory(
            commitment_id=commitment.commitment_id
        ),
        Capability.COMMITMENTS_WAITING_ON: WaitingOn(),
        Capability.COMMITMENTS_CREATE: CreateCommitment(
            counterparty_person_id=counterparty_person_id,
            direction=CommitmentDirection.OWED_BY_PRINCIPAL,
            summary="HTTP commitment-plane commitment",
            origin_evidence_ref="cap_origin0001origin0001",
            idempotency_key="http-commitment-create-0001",
        ),
        Capability.COMMITMENTS_CLOSE: CloseCommitment(
            commitment_id=commitment.commitment_id,
            expected_version=commitment.version,
            closure_evidence_ref="cap_origin0001origin0001",
            idempotency_key="http-commitment-close-0001",
        ),
        Capability.COMMITMENTS_UPDATE: UpdateCommitment(
            commitment_id=commitment.commitment_id,
            expected_version=commitment.version,
            idempotency_key="http-commitment-update-0001",
            summary="HTTP commitment-plane commitment, revised",
        ),
        Capability.CONTEXT_PREPARE: PrepareContext(query="revenue"),
        Capability.CONTEXT_FEEDBACK: RecordContextFeedback(
            action=ContextPreferenceAction.PIN,
            target_id=feedback_target_id,
            idempotency_key="http-feedback-0001",
        ),
        Capability.GOODNOTES_WORK: GetGoodNotesWork(
            run_id=work.run_id,
            page_version_id=work.page_version_id,
        ),
        Capability.GOODNOTES_CONTENT: GetGoodNotesContent(
            run_id=raster.run_id,
            page_version_id=raster.page_version_id,
            content_sha256=work.content_sha256,
        ),
        Capability.GOODNOTES_PROPOSE: SubmitGoodNotesProposal(
            run_id=work.run_id,
            page_version_id=work.page_version_id,
            content_sha256=work.content_sha256,
            schema_version="note-unit.v1",
            analyzer_name="synthetic",
            analyzer_version="1",
            idempotency_key="http-goodnotes-propose-0001",
            segments=(
                {
                    "kind": "NOTE_UNIT",
                    "geometry": {
                        "x_min": 0.1,
                        "y_min": 0.1,
                        "width": 0.2,
                        "height": 0.2,
                    },
                    "transcription": "synthetic note",
                    "primary_class": "MEETING",
                },
            ),
        ),
        Capability.GSQS_START: StartGsqsB0(
            authorization_id="synthetic-b0-commissioning",
            campaign_class="SYNTHETIC",
            repetition=1,
            idempotency_key="http-gsqs-start",
        ),
        Capability.GSQS_STATUS: GetGsqsB0Status(run_id=gsqs_run_id),
        Capability.REPORTS_BEGIN_CYCLE: BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-20",
            idempotency_key="http-cycle-0001",
        ),
        Capability.REPORTS_COMMIT: CommitIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="http-collector",
            producer_task_name="HTTP Collector",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="HTTP collector",
            body_markdown="synthetic collector",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="http-report-commit-0001",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
        Capability.REPORTS_RECORD_RUN_STATE: RecordIntelligenceRunState(
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.RESEARCHER,
            artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
            producer_task_id="http-researcher",
            producer_task_name="HTTP Researcher",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            state=ProducerRunState.FAILED,
            idempotency_key="http-run-state-0001",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            source_lane=SourceLaneId.TEAMS,
            failure_code="source_unavailable",
        ),
        Capability.REPORTS_READ: ReadIntelligenceArtifact(report_id=report_id, include_body=True),
        Capability.REPORTS_LATEST: GetLatestIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.COLLECTOR,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
        Capability.REPORTS_LIST: ListIntelligenceArtifacts(cycle_run_id=cycle_run_id, page_size=10),
        Capability.REPORTS_SEARCH: SearchIntelligenceArtifacts(
            query="synthetic",
            cycle_run_id=cycle_run_id,
            page_size=10,
        ),
        Capability.REPORTS_RESOLVE_SET: ResolveIntelligenceSet(
            cycle_run_id=cycle_run_id,
            set_id=ResolverSetId.COLLECTORS,
        ),
        # The entity plane. `person` is the same staged entity the payload table
        # names, because `staged_entities` answers with the pair already in the
        # world: two tables each staging their own would be comparing two
        # different requests.
        Capability.ENTITIES_SEARCH: SearchEntities(query="parity"),
        Capability.ENTITIES_GET: GetEntity(entity_id=person.entity_id),
        Capability.ENTITIES_RESOLVE: ResolveEntity(reference=ENTITY_EMAIL, namespace="email"),
        Capability.ENTITIES_CONTEXT: GetEntityContext(entity_id=person.entity_id),
        Capability.ENTITIES_RELATIONSHIPS: GetEntityRelationships(
            entity_id=person.entity_id, direction="any"
        ),
        Capability.ENTITIES_UNRESOLVED_MENTIONS: ListUnresolvedMentions(),
        # The entity plane's authoring half, written as the commands the payload
        # table above must normalise to. The vocabulary members and the datetime
        # are spelled here as domain values because that is what the caller's
        # strings have to *become*.
        Capability.ENTITIES_IDENTIFIERS_LIST: ListEntityIdentifiers(
            entity_id=person.entity_id,
            states=(IdentifierState.ACTIVE,),
            page_size=10,
        ),
        Capability.ENTITIES_ALIASES_LIST: ListEntityAliases(
            entity_id=person.entity_id,
            states=(AliasState.ACTIVE,),
            alias_types=(AliasType.NICKNAME,),
            page_size=10,
        ),
        Capability.ENTITIES_CREATE: CreateEntity(
            entity_type=EntityType.PERSON,
            display_name="HTTP Newcomer",
            aliases=({"alias_type": "nickname", "display_value": "Newk"},),
            identifiers=({"namespace": "email", "display_value": "http.newcomer@example.invalid"},),
            reason="A synthetic creation.",
            idempotency_key="http-entity-create-0001",
        ),
        Capability.ENTITIES_UPDATE: UpdateEntity(
            entity_id=person.entity_id,
            expected_version=1,
            display_name="Parity Person",
            status=EntityStatus.INACTIVE,
            reason="A synthetic correction.",
            idempotency_key="http-entity-update-0001",
        ),
        Capability.ENTITIES_ARCHIVE: ArchiveEntity(
            entity_id=person.entity_id,
            expected_version=1,
            reason="A synthetic withdrawal.",
            idempotency_key="http-entity-archive-0001",
        ),
        Capability.ENTITIES_RESTORE: RestoreEntity(
            entity_id=archived.entity_id,
            expected_version=archived.version,
            reason="A synthetic restoration.",
            idempotency_key="http-entity-restore-0001",
        ),
        Capability.ENTITIES_IDENTIFIERS_BIND: BindEntityIdentifier(
            entity_id=person.entity_id,
            expected_version=1,
            namespace=CallerNamespace.TEAMS_USER_ID,
            display_value="http-teams-user",
            effective_from=datetime(2026, 8, 2, 12, tzinfo=UTC),
            reason="A synthetic binding.",
            idempotency_key="http-entity-bind-0001",
        ),
        Capability.ENTITIES_IDENTIFIERS_RETIRE: RetireEntityIdentifier(
            entity_id=person.entity_id,
            expected_version=1,
            identifier_id=identifier_id,
            expected_identifier_version=1,
            reason="A synthetic retirement.",
            idempotency_key="http-entity-retire-identifier-0001",
        ),
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE: SupersedeEntityIdentifier(
            entity_id=person.entity_id,
            expected_version=1,
            identifier_id=identifier_id,
            expected_identifier_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="http.person.new@example.invalid",
            reason="A synthetic replacement.",
            idempotency_key="http-entity-supersede-identifier-0001",
        ),
        Capability.ENTITIES_ALIASES_ADD: AddEntityAlias(
            entity_id=person.entity_id,
            expected_version=1,
            alias_type=AliasType.INITIALS,
            display_value="PP",
            reason="A synthetic addition.",
            idempotency_key="http-entity-add-alias-0001",
        ),
        Capability.ENTITIES_ALIASES_RETIRE: RetireEntityAlias(
            entity_id=person.entity_id,
            expected_version=1,
            alias_id=alias_id,
            expected_alias_version=1,
            reason="A synthetic retirement.",
            idempotency_key="http-entity-retire-alias-0001",
        ),
        Capability.ENTITIES_ALIASES_SUPERSEDE: SupersedeEntityAlias(
            entity_id=person.entity_id,
            expected_version=1,
            alias_id=alias_id,
            expected_alias_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="HTTP Buddy",
            reason="A synthetic correction.",
            idempotency_key="http-entity-supersede-alias-0001",
        ),
        # The directed-relationship family, written as the commands the payload
        # table above must normalise to. `assignment_type` and
        # `relationship_type` are spelled here as domain members because that is
        # what the caller's strings have to *become*: a normalisation that
        # passed `"team_membership"` through unconverted would satisfy a
        # comparison written in strings and fail this one.
        Capability.ENTITIES_ASSIGNMENTS_LIST: ListEntityAssignments(entity_id=person.entity_id),
        Capability.ENTITIES_ASSIGNMENTS_CREATE: CreateEntityAssignment(
            entity_id=person.entity_id,
            expected_entity_version=1,
            assignment_type=AssignmentType.TEAM_MEMBERSHIP,
            idempotency_key="http-assignment-create-0001",
        ),
        Capability.ENTITIES_ASSIGNMENTS_REVISE: ReviseEntityAssignment(
            assignment_id=revise_assignment,
            expected_version=1,
            role="Synthetic Revised Role",
            idempotency_key="http-assignment-revise-0001",
        ),
        Capability.ENTITIES_ASSIGNMENTS_END: EndEntityAssignment(
            assignment_id=end_assignment,
            expected_version=1,
            reason="A synthetic withdrawal.",
            end_now=True,
            idempotency_key="http-assignment-end-0001",
        ),
        Capability.ENTITIES_RELATIONSHIPS_CREATE: CreateEntityRelationship(
            from_entity_id=person.entity_id,
            expected_from_version=1,
            relationship_type=EntityRelationshipType.MEMBER_OF,
            to_entity_id=organization.entity_id,
            expected_to_version=1,
            idempotency_key="http-relationship-create-0001",
        ),
        Capability.ENTITIES_RELATIONSHIPS_REVISE: ReviseEntityRelationship(
            relationship_id=revise_edge,
            expected_version=1,
            idempotency_key="http-relationship-revise-0001",
        ),
        Capability.ENTITIES_RELATIONSHIPS_END: EndEntityRelationship(
            relationship_id=end_edge,
            expected_version=1,
            reason="A synthetic withdrawal.",
            end_now=True,
            idempotency_key="http-relationship-end-0001",
        ),
        Capability.ENTITIES_OBSERVATIONS_LIST: ListEntityObservations(),
        Capability.ENTITIES_OBSERVE: ObserveEntityMention(
            kind=ObservationKind.USER_STATEMENT,
            authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
            observed_value="Parity Person",
            mention_display_name="Parity Person",
            capture_id="cap_httpobserve0001",
            capture_version_id="capver_httpobserve0001",
            observed_at=datetime(2026, 8, 2, 10, tzinfo=UTC),
            idempotency_key="http-entities-observe-0001",
        ),
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE: ResolveUnresolvedMention(
            observation_id=staged_mention(scene),
            expected_resolution_version=0,
            disposition=ResolutionDisposition.DEFER,
            reason="there is not enough identity evidence yet",
            idempotency_key="http-entities-resolve-0001",
        ),
        # The Relationship Memory plane, written as the commands the payload
        # table above must normalise to. The vocabulary members and the datetime
        # are spelled here as domain values because that is what the caller's
        # strings have to *become*: a normalisation that passed `"personal_detail"`
        # or `"2026-08-02T10:00:00Z"` through unconverted would satisfy a
        # comparison written in strings and fail this one.
        Capability.RELATIONSHIP_MEMORY_CREATE: CreateRelationshipMemory(
            entity_id=person.entity_id,
            statement="A synthetic memory-plane note",
            idempotency_key="http-memory-create-0001",
            kind=MemoryKind.PERSONAL_DETAIL,
            observed_at=datetime(2026, 8, 2, 10, tzinfo=UTC),
        ),
        Capability.RELATIONSHIP_MEMORY_GET: GetRelationshipMemory(
            memory_id=MEMORY_ID, include_statement=True
        ),
        Capability.RELATIONSHIP_MEMORY_LIST: ListRelationshipMemories(
            entity_id=person.entity_id,
            kinds=(MemoryKind.PERSONAL_DETAIL,),
            lifecycle=MemoryLifecycle.ACTIVE,
            page_size=10,
        ),
        Capability.RELATIONSHIP_MEMORY_SEARCH: SearchRelationshipMemories(
            query="synthetic", page_size=10
        ),
        Capability.RELATIONSHIP_MEMORY_HISTORY: GetRelationshipMemoryHistory(
            memory_id=MEMORY_ID, page_size=10
        ),
        Capability.RELATIONSHIP_MEMORY_REVISE: ReviseRelationshipMemory(
            memory_id=MEMORY_ID,
            expected_version=1,
            statement="A synthetic memory-plane note, revised",
            idempotency_key="http-memory-revise-0001",
            correction_reason="the contract table revised it",
        ),
        Capability.RELATIONSHIP_MEMORY_ARCHIVE: ArchiveRelationshipMemory(
            memory_id=MEMORY_ID,
            expected_version=1,
            idempotency_key="http-memory-archive-0001",
        ),
        Capability.RELATIONSHIP_MEMORY_RESTORE: RestoreRelationshipMemory(
            memory_id=MEMORY_ID,
            expected_version=1,
            idempotency_key="http-memory-restore-0001",
        ),
    }


def document_for(capability: Capability, scene: Scene, payload: dict[str, Any]) -> dict[str, Any]:
    """The request document: the common envelope, and the payload beside it."""
    return {
        "request_id": f"req-{capability.value}",
        "purpose": a_permitted_purpose(capability).value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-08-02T12:00:00Z",
        "payload": payload,
    }


class RecordingService(ApplicationService):
    """The real service, keeping every envelope it returned.

    A subclass rather than a wrapper because the transport is typed against
    `ApplicationService` and a duck would need a cast; overriding the one public
    method and delegating to it changes no behaviour, which is what makes the
    recorded envelope the same object the caller received.
    """

    def __init__(self, world: World, providers: FakeProviders) -> None:
        # `ApplicationService` takes no `SourceProviders`: the lookup comes from
        # the unit of work, so the adapters go into the `World` the fake reads.
        world.providers = providers
        super().__init__(
            unit_of_work=lambda: FakeUnitOfWork(world),
            limits=DEFAULT_LIMITS,
            clock=lambda: WHEN,
            # The same store the `World` holds, so a document staged into the
            # world and one written through this service are the same bytes.
            managed_store=world.managed_store,
            task_management_unit_of_work=lambda: FakeTaskManagementUnitOfWork(world),
            commitment_management_unit_of_work=lambda: FakeCommitmentManagementUnitOfWork(world),
            # Composed, for the same reason the managed store above is: this
            # suite quantifies over every `Capability` and asserts each is
            # reachable, so a service composed *without* the relationship plane
            # would have it asserting reachability for the `entities.` family
            # its own build withholds. It did exactly that until `_entity_plane`
            # gave that family the floor `documents.` already had -- each member
            # answered `200` here while `capabilities.get` on the same process
            # reported it `not_implemented`, and this suite asserted the `200`.
            relationship_intelligence_enabled=True,
            # And its write half, on exactly the same argument one line up: the
            # eighteen `entities.` writes are withheld by a second switch, so a
            # service composed with the plane and without this one would have
            # this suite asserting reachability for names its own build refuses.
            relationship_intelligence_writes_enabled=True,
        )
        self.envelopes: list[ResponseEnvelope] = []

    def invoke(
        self, metadata: RequestMetadata, command: Command, *, principal: Principal
    ) -> ResponseEnvelope:
        envelope = super().invoke(metadata, command, principal=principal)
        self.envelopes.append(envelope)
        return envelope


@pytest.fixture
def staged(scene: Scene) -> tuple[Scene, KnowledgeRecord]:
    """A scene with a search page and a stored record, so every capability succeeds."""
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    return scene, staged_record(scene)


@pytest.fixture
def service(staged: tuple[Scene, KnowledgeRecord]) -> RecordingService:
    scene, _ = staged
    return RecordingService(scene.world, scene.providers)


@pytest.fixture
def wire(staged: tuple[Scene, KnowledgeRecord], service: RecordingService) -> Iterator[Wire]:
    scene, _ = staged
    with serve(create_http_app(service, principal=scene.principal)) as client:
        yield client


# ---- reachability and verbatim answers --------------------------------------


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_is_reachable_over_http(
    capability: Capability, staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    """Every one of them, addressed by name, answering successfully."""
    scene, record = staged
    payload = payloads_for(scene, record)[capability]
    reply = wire.send(capability.value, document_for(capability, scene, payload))
    envelope = reply.document()
    if capability is Capability.TASKS_BULK_CONFIRM:
        assert reply.status == 404, reply.body
        assert envelope["error"]["code"] == "not_found"
        return
    if capability in _UNSUPPORTED_CAPABILITIES:
        assert reply.status == 501, reply.body
        assert envelope["error"]["code"] == "unsupported"
        assert envelope["request_id"] == f"req-{capability.value}"
        assert envelope["contract_version"] == "v1"
        return
    assert reply.status == 200, reply.body
    assert envelope["error"] is None
    assert envelope["disclosure"] is not None
    assert envelope["request_id"] == f"req-{capability.value}"
    assert envelope["contract_version"] == "v1"


@pytest.mark.parametrize("reference", ["cap_unknown001unknown001", "asrt_unknown01unknown01"])
def test_work_writes_refuse_unknown_or_unaccepted_evidence(
    reference: str, staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    reply = wire.send(
        Capability.TASKS_CREATE.value,
        document_for(
            Capability.TASKS_CREATE,
            scene,
            {
                "title": "Synthetic refused task",
                "origin_evidence_ref": reference,
                "idempotency_key": "evidence-refusal-0001",
            },
        ),
    )
    assert reply.status == 400
    assert reply.document()["error"]["safe_details"] == ["invalid_evidence_reference"]


def test_work_writes_collapse_foreign_evidence_to_the_same_refusal(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    reference = "cap_foreign001foreign001"
    scene.world.work_evidence_refs.add(("prn_foreign001foreign001", reference))
    reply = wire.send(
        Capability.TASKS_CREATE.value,
        document_for(
            Capability.TASKS_CREATE,
            scene,
            {
                "title": "Synthetic refused task",
                "origin_evidence_ref": reference,
                "idempotency_key": "foreign-refusal-0001",
            },
        ),
    )
    assert reply.status == 400
    assert reply.document()["error"]["safe_details"] == ["invalid_evidence_reference"]


def test_commitment_create_refuses_a_superseded_counterparty_without_disclosure(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    commitment = staged_commitment(scene)
    scene.world.current_counterparties.remove(
        (scene.principal.principal_id, commitment.counterparty_person_id)
    )
    reply = wire.send(
        Capability.COMMITMENTS_CREATE.value,
        document_for(
            Capability.COMMITMENTS_CREATE,
            scene,
            {
                "counterparty_person_id": commitment.counterparty_person_id,
                "direction": "owed_to_principal",
                "summary": "Synthetic refused commitment",
                "origin_evidence_ref": "cap_origin0001origin0001",
                "idempotency_key": "superseded-counterparty-refusal-0001",
            },
        ),
    )
    assert reply.status == 404
    assert reply.document()["error"]["code"] == "not_found"
    assert reply.document()["error"]["safe_details"] == ["counterparty_person_id"]


@pytest.mark.parametrize(
    ("capability", "payload_factory"),
    [
        (
            Capability.TASKS_CREATE,
            lambda scene, reference: {
                "title": "Replay survives superseded evidence",
                "origin_evidence_ref": reference,
                "idempotency_key": "task-create-superseded-0001",
            },
        ),
        (
            Capability.TASKS_TRANSITION,
            lambda scene, reference: {
                "task_id": staged_task(scene).task_id,
                "to_state": "completed",
                "expected_version": staged_task(scene).version,
                "closure_evidence_ref": reference,
                "idempotency_key": "task-close-superseded-0001",
            },
        ),
        (
            Capability.COMMITMENTS_CREATE,
            lambda scene, reference: {
                "counterparty_person_id": staged_commitment(scene).counterparty_person_id,
                "direction": "owed_by_principal",
                "summary": "Replay survives superseded evidence",
                "origin_evidence_ref": reference,
                "idempotency_key": "commitment-create-superseded-0001",
            },
        ),
        (
            Capability.COMMITMENTS_CLOSE,
            lambda scene, reference: {
                "commitment_id": staged_commitment(scene).commitment_id,
                "expected_version": staged_commitment(scene).version,
                "closure_evidence_ref": reference,
                "idempotency_key": "commitment-close-superseded-0001",
            },
        ),
    ],
    ids=lambda value: value.value if isinstance(value, Capability) else None,
)
def test_exact_work_replay_precedes_mutable_evidence_eligibility(
    capability: Capability,
    payload_factory: Callable[[Scene, str], dict[str, object]],
    staged: tuple[Scene, KnowledgeRecord],
    wire: Wire,
) -> None:
    scene, _ = staged
    reference = issue_identifier(IdKind.ASSERTION)
    scene.world.work_evidence_refs.add((scene.principal.principal_id, reference))
    payload = payload_factory(scene, reference)

    first = wire.send(capability.value, document_for(capability, scene, payload))
    assert first.status == 200, first.body
    scene.world.work_evidence_refs.remove((scene.principal.principal_id, reference))

    replay = wire.send(capability.value, document_for(capability, scene, payload))
    assert replay.status == 200, replay.body
    assert replay.document()["result"]["replayed"] is True


def test_work_digest_mismatch_conflicts_before_superseded_evidence_lookup(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    reference = issue_identifier(IdKind.ASSERTION)
    scene.world.work_evidence_refs.add((scene.principal.principal_id, reference))
    payload = {
        "title": "Original request",
        "origin_evidence_ref": reference,
        "idempotency_key": "task-create-mismatch-before-evidence-0001",
    }
    assert (
        wire.send(
            Capability.TASKS_CREATE.value,
            document_for(Capability.TASKS_CREATE, scene, payload),
        ).status
        == 200
    )
    scene.world.work_evidence_refs.remove((scene.principal.principal_id, reference))
    payload["title"] = "Different normalized request"

    mismatch = wire.send(
        Capability.TASKS_CREATE.value,
        document_for(Capability.TASKS_CREATE, scene, payload),
    )
    assert mismatch.status == 409
    assert mismatch.document()["error"]["safe_details"] == ["idempotency_key"]


@pytest.mark.parametrize(
    "capability",
    [
        Capability.TASKS_LIST,
        Capability.TASKS_SEARCH,
        Capability.TASKS_HISTORY,
        Capability.COMMITMENTS_LIST,
        Capability.COMMITMENTS_SEARCH,
        Capability.COMMITMENTS_HISTORY,
        Capability.COMMITMENTS_WAITING_ON,
    ],
)
def test_absent_work_cursor_is_one_safe_typed_conflict(
    capability: Capability, staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    task = staged_task(scene)
    commitment = staged_commitment(scene)
    cursor = (
        issue_identifier(IdKind.TASK_HISTORY)
        if capability is Capability.TASKS_HISTORY
        else issue_identifier(IdKind.COMMITMENT_HISTORY)
        if capability is Capability.COMMITMENTS_HISTORY
        else issue_identifier(IdKind.TASK)
        if capability in {Capability.TASKS_LIST, Capability.TASKS_SEARCH}
        else issue_identifier(IdKind.COMMITMENT)
    )
    payload: dict[str, object] = {"after": cursor}
    if capability is Capability.TASKS_SEARCH:
        payload["query"] = "synthetic"
    elif capability is Capability.TASKS_HISTORY:
        payload["task_id"] = task.task_id
    elif capability is Capability.COMMITMENTS_SEARCH:
        payload["query"] = "synthetic"
    elif capability is Capability.COMMITMENTS_HISTORY:
        payload["commitment_id"] = commitment.commitment_id

    reply = wire.send(capability.value, document_for(capability, scene, payload))
    assert reply.status == 409
    assert reply.document()["error"]["safe_details"] == ["cursor"]


def test_waiting_on_returns_only_accepted_commitments(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    proposed = replace(
        staged_commitment(scene),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
    )
    accepted = replace(
        proposed,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        accepted_by_review_decision_id=issue_identifier(IdKind.REVIEW_DECISION),
    )
    scene.world.commitments_v2[:] = [proposed, accepted]

    reply = wire.send(
        Capability.COMMITMENTS_WAITING_ON.value,
        document_for(Capability.COMMITMENTS_WAITING_ON, scene, {}),
    )

    assert reply.status == 200
    rows = reply.document()["result"]["waiting_on"]
    assert [row["commitment_id"] for row in rows] == [accepted.commitment_id]


def test_fake_work_repositories_refuse_foreign_cursor_anchors(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    scene, _ = staged
    task = staged_task(scene)
    commitment = staged_commitment(scene)
    foreign_principal = "prn_foreign001foreign001"
    foreign_task = replace(
        task, task_id=issue_identifier(IdKind.TASK), principal_id=foreign_principal
    )
    foreign_task_history = replace(
        scene.world.task_history_v2[0],
        history_id=issue_identifier(IdKind.TASK_HISTORY),
        task_id=foreign_task.task_id,
        principal_id=foreign_principal,
    )
    foreign_commitment = replace(
        commitment,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        principal_id=foreign_principal,
    )
    foreign_commitment_history = replace(
        scene.world.commitment_history_v2[0],
        history_id=issue_identifier(IdKind.COMMITMENT_HISTORY),
        commitment_id=foreign_commitment.commitment_id,
        principal_id=foreign_principal,
    )
    scene.world.tasks_v2.append(foreign_task)
    scene.world.task_history_v2.append(foreign_task_history)
    scene.world.commitments_v2.append(foreign_commitment)
    scene.world.commitment_history_v2.append(foreign_commitment_history)
    unit_of_work = FakeUnitOfWork(scene.world)

    with pytest.raises(WorkCursorError):
        unit_of_work.tasks.list_tasks(
            scene.principal.principal_id, after=foreign_task.task_id, limit=10
        )
    with pytest.raises(WorkCursorError):
        unit_of_work.tasks.search(
            scene.principal.principal_id, "synthetic", 10, after=foreign_task.task_id
        )
    with pytest.raises(WorkCursorError):
        unit_of_work.tasks.list_history(
            scene.principal.principal_id,
            task.task_id,
            10,
            after=foreign_task_history.history_id,
        )
    with pytest.raises(WorkCursorError):
        unit_of_work.commitments.list_commitments(
            scene.principal.principal_id,
            after=foreign_commitment.commitment_id,
            limit=10,
        )
    with pytest.raises(WorkCursorError):
        unit_of_work.commitments.search(
            scene.principal.principal_id,
            "synthetic",
            10,
            after=foreign_commitment.commitment_id,
        )
    with pytest.raises(WorkCursorError):
        unit_of_work.commitments.list_history(
            scene.principal.principal_id,
            commitment.commitment_id,
            10,
            after=foreign_commitment_history.history_id,
        )


def test_fake_work_cursors_are_bound_to_the_complete_result_predicate(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    scene, _ = staged
    principal_id = scene.principal.principal_id
    task = staged_task(scene)
    task_anchor = replace(
        task,
        task_id=issue_identifier(IdKind.TASK),
        title="needle anchor",
        lifecycle_state=TaskLifecycleState.WAITING,
        priority=TaskPriority.P1,
        created_at=WHEN + timedelta(minutes=2),
        updated_at=WHEN + timedelta(minutes=2),
    )
    task_next = replace(
        task_anchor,
        task_id=issue_identifier(IdKind.TASK),
        title="needle continuation",
        created_at=WHEN + timedelta(minutes=1),
        updated_at=WHEN + timedelta(minutes=1),
    )
    task_wrong_view = replace(
        task_anchor,
        task_id=issue_identifier(IdKind.TASK),
        lifecycle_state=TaskLifecycleState.BLOCKED,
    )
    task_wrong_priority = replace(
        task_anchor,
        task_id=issue_identifier(IdKind.TASK),
        title="priority-only mismatch",
        priority=TaskPriority.P2,
    )
    task_archived = replace(
        task_anchor,
        task_id=issue_identifier(IdKind.TASK),
        archived_at=WHEN,
    )
    task_wrong_query = replace(
        task_anchor,
        task_id=issue_identifier(IdKind.TASK),
        title="different result set",
        created_at=WHEN,
        updated_at=WHEN,
    )
    scene.world.tasks_v2[:] = [
        task_anchor,
        task_next,
        task_wrong_view,
        task_wrong_priority,
        task_archived,
        task_wrong_query,
    ]
    tasks = FakeUnitOfWork(scene.world).tasks

    list_arguments = {
        "work_view": TaskWorkView.WAITING,
        "priority": TaskPriority.P1,
        "archive_mode": TaskArchiveMode.EXCLUDE,
        "limit": 10,
    }
    for cursor in (
        task_wrong_view.task_id,
        task_wrong_priority.task_id,
        task_archived.task_id,
    ):
        with pytest.raises(WorkCursorError):
            tasks.list_tasks(principal_id, after=cursor, **list_arguments)
    with pytest.raises(WorkCursorError):
        tasks.search(
            principal_id,
            "needle",
            after=task_wrong_query.task_id,
            work_view=TaskWorkView.WAITING,
            archive_mode=TaskArchiveMode.EXCLUDE,
            limit=10,
        )
    assert tasks.list_tasks(principal_id, after=task_anchor.task_id, **list_arguments) == (
        task_next,
        task_wrong_query,
    )
    assert tasks.search(
        principal_id,
        "needle",
        after=task_anchor.task_id,
        work_view=TaskWorkView.WAITING,
        archive_mode=TaskArchiveMode.EXCLUDE,
        limit=10,
    ) == (task_next,)

    commitment = staged_commitment(scene)
    commitment_anchor = replace(
        commitment,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        summary="needle anchor",
        due_at=WHEN + timedelta(days=1),
        created_at=WHEN + timedelta(minutes=2),
        updated_at=WHEN + timedelta(minutes=2),
    )
    commitment_next = replace(
        commitment_anchor,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        summary="needle continuation",
        due_at=WHEN + timedelta(days=2),
        created_at=WHEN + timedelta(minutes=1),
        updated_at=WHEN + timedelta(minutes=1),
    )
    commitment_wrong_direction = replace(
        commitment_anchor,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
    )
    commitment_wrong_state = replace(
        commitment_anchor,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        state=CommitmentState.CLOSED,
        closed_at=WHEN,
        closure_evidence_ref="cap_closure0001closure0001",
    )
    commitment_wrong_query = replace(
        commitment_anchor,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        summary="different result set",
    )
    scene.world.commitments_v2[:] = [
        commitment_anchor,
        commitment_next,
        commitment_wrong_direction,
        commitment_wrong_state,
        commitment_wrong_query,
    ]
    commitments = FakeUnitOfWork(scene.world).commitments
    search_arguments = {
        "direction": commitment_anchor.direction,
        "state": CommitmentState.OPEN,
    }
    for cursor in (
        commitment_wrong_direction.commitment_id,
        commitment_wrong_state.commitment_id,
        commitment_wrong_query.commitment_id,
    ):
        with pytest.raises(WorkCursorError):
            commitments.search(
                principal_id,
                "needle",
                10,
                after=cursor,
                **search_arguments,
            )
    assert commitments.search(
        principal_id,
        "needle",
        10,
        after=commitment_anchor.commitment_id,
        **search_arguments,
    ) == (commitment_next,)


def test_work_views_use_trusted_now_civil_bounds_and_stable_cursor_order(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    scene, _ = staged
    principal_id = scene.principal.principal_id
    seed = staged_task(scene)
    day_start = WHEN.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    overdue = replace(
        seed,
        task_id=issue_identifier(IdKind.TASK),
        title="overdue",
        due_at=WHEN - timedelta(minutes=1),
        scheduled_at=WHEN + timedelta(hours=1),
        updated_at=day_start - timedelta(days=7),
    )
    today = replace(
        seed,
        task_id=issue_identifier(IdKind.TASK),
        title="today",
        due_at=WHEN + timedelta(hours=1),
        scheduled_at=None,
        updated_at=day_start - timedelta(days=7),
    )
    due_only = replace(
        seed,
        task_id=issue_identifier(IdKind.TASK),
        title="due only",
        due_at=WHEN + timedelta(hours=2),
        scheduled_at=None,
        updated_at=day_start - timedelta(days=7),
    )
    scheduled = replace(
        seed,
        task_id=issue_identifier(IdKind.TASK),
        title="scheduled",
        due_at=None,
        scheduled_at=WHEN + timedelta(hours=2),
        updated_at=day_start - timedelta(days=7),
    )
    future_with_overdue_due = replace(
        seed,
        task_id=issue_identifier(IdKind.TASK),
        title="future schedule with overdue due",
        due_at=WHEN - timedelta(days=1),
        scheduled_at=day_end + timedelta(hours=1),
        updated_at=day_start - timedelta(days=7),
    )
    recent_first = replace(
        seed,
        task_id=issue_identifier(IdKind.TASK),
        title="recent first",
        updated_at=WHEN,
    )
    recent_second = replace(
        seed,
        task_id=issue_identifier(IdKind.TASK),
        title="recent second",
        updated_at=WHEN - timedelta(days=1),
    )
    scene.world.tasks_v2[:] = [
        overdue,
        today,
        due_only,
        scheduled,
        future_with_overdue_due,
        recent_first,
        recent_second,
    ]
    tasks = FakeUnitOfWork(scene.world).tasks
    bounds = {"work_start": day_start, "work_end": day_end, "work_now": WHEN, "limit": 20}
    assert overdue in tasks.list_tasks(principal_id, work_view=TaskWorkView.OVERDUE, **bounds)
    assert overdue not in tasks.list_tasks(principal_id, work_view=TaskWorkView.TODAY, **bounds)
    assert future_with_overdue_due not in tasks.list_tasks(
        principal_id, work_view=TaskWorkView.UPCOMING, **bounds
    )
    unscheduled = tasks.list_tasks(principal_id, work_view=TaskWorkView.UNSCHEDULED, limit=20)
    assert due_only in unscheduled
    assert scheduled not in unscheduled
    recent_bounds = {
        "work_start": day_start - timedelta(days=6),
        "work_end": day_end,
        "work_now": WHEN,
        "limit": 20,
    }
    recent = tasks.list_tasks(
        principal_id, work_view=TaskWorkView.RECENTLY_UPDATED, **recent_bounds
    )
    assert recent.index(recent_first) < recent.index(recent_second)
    continuation = tasks.list_tasks(
        principal_id,
        work_view=TaskWorkView.RECENTLY_UPDATED,
        after=recent_first.task_id,
        **recent_bounds,
    )
    assert continuation[0] is recent_second

    commitment = staged_commitment(scene)
    due_open = replace(
        commitment,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        due_at=WHEN + timedelta(hours=1),
    )
    due_closed = replace(
        due_open,
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        state=CommitmentState.CLOSED,
        closed_at=WHEN,
        closure_evidence_ref="cap_closure0001closure0001",
    )
    scene.world.commitments_v2[:] = [due_open, due_closed]
    due = FakeUnitOfWork(scene.world).commitments.list_commitments(
        principal_id,
        work_view=CommitmentWorkView.DUE,
        work_start=day_start,
        work_end=day_end,
        limit=20,
    )
    assert due == (due_open,)


def test_bulk_preview_and_confirm_replay_the_original_receipts(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, record = staged
    task = staged_task(scene)
    mutations = [
        {
            "kind": "update",
            "task_id": task.task_id,
            "expected_version": task.version,
            "values": {"priority": "p1"},
            "clear_fields": [],
        }
    ]
    preview_payload = {"mutations": mutations, "idempotency_key": "bulk-replay-preview-0001"}
    first = wire.send(
        Capability.TASKS_BULK_PREVIEW.value,
        document_for(Capability.TASKS_BULK_PREVIEW, scene, preview_payload),
    ).document()["result"]
    replay = wire.send(
        Capability.TASKS_BULK_PREVIEW.value,
        document_for(Capability.TASKS_BULK_PREVIEW, scene, preview_payload),
    ).document()["result"]
    assert replay == {**first, "replayed": True}
    confirm_payload = {
        "bulk_operation_id": first["bulk_operation_id"],
        "idempotency_key": "bulk-replay-confirm-0001",
        "mutations": mutations,
    }
    confirmed = wire.send(
        Capability.TASKS_BULK_CONFIRM.value,
        document_for(Capability.TASKS_BULK_CONFIRM, scene, confirm_payload),
    ).document()["result"]
    confirmed_replay = wire.send(
        Capability.TASKS_BULK_CONFIRM.value,
        document_for(Capability.TASKS_BULK_CONFIRM, scene, confirm_payload),
    ).document()["result"]
    assert confirmed_replay == {**confirmed, "replayed": True}
    assert confirmed["affected"] == 1
    assert len(confirmed["history_ids"]) == 1
    del record


def test_bulk_confirm_key_is_unique_per_principal_across_operations(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    first_task = staged_task(scene)
    second_task = replace(
        first_task,
        task_id=issue_identifier(IdKind.TASK),
        title="a second synthetic task",
    )
    scene.world.tasks_v2.append(second_task)

    previews: list[tuple[dict[str, object], dict[str, object]]] = []
    for index, (task, priority) in enumerate(((first_task, "p1"), (second_task, "p2")), 1):
        mutation = {
            "kind": "update",
            "task_id": task.task_id,
            "expected_version": task.version,
            "values": {"priority": priority},
            "clear_fields": [],
        }
        preview = wire.send(
            Capability.TASKS_BULK_PREVIEW.value,
            document_for(
                Capability.TASKS_BULK_PREVIEW,
                scene,
                {
                    "mutations": [mutation],
                    "idempotency_key": f"bulk-global-preview-{index:04d}",
                },
            ),
        ).document()["result"]
        previews.append((preview, mutation))

    shared_key = "bulk-global-confirm-0001"
    first_preview, first_mutation = previews[0]
    assert (
        wire.send(
            Capability.TASKS_BULK_CONFIRM.value,
            document_for(
                Capability.TASKS_BULK_CONFIRM,
                scene,
                {
                    "bulk_operation_id": first_preview["bulk_operation_id"],
                    "idempotency_key": shared_key,
                    "mutations": [first_mutation],
                },
            ),
        ).status
        == 200
    )
    second_preview, second_mutation = previews[1]
    before = tuple(scene.world.tasks_v2)
    refused = wire.send(
        Capability.TASKS_BULK_CONFIRM.value,
        document_for(
            Capability.TASKS_BULK_CONFIRM,
            scene,
            {
                "bulk_operation_id": second_preview["bulk_operation_id"],
                "idempotency_key": shared_key,
                "mutations": [second_mutation],
            },
        ),
    )
    assert refused.status == 409
    assert refused.document()["error"]["safe_details"] == ["idempotency_key"]
    assert tuple(scene.world.tasks_v2) == before


def test_follow_up_role_without_a_commitment_is_typed_validation(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    scene.world.work_evidence_refs.add((scene.principal.principal_id, "cap_origin0001origin0001"))
    reply = wire.send(
        Capability.TASKS_CREATE.value,
        document_for(
            Capability.TASKS_CREATE,
            scene,
            {
                "title": "synthetic unlinked follow-up",
                "origin_evidence_ref": "cap_origin0001origin0001",
                "role": "follow_up",
                "idempotency_key": "unlinked-follow-up-0001",
            },
        ),
    )
    assert reply.status == 400
    assert reply.document()["error"]["safe_details"] == ["selector"]


def test_task_read_keeps_terminal_history_link_after_a_later_update(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    task = staged_task(scene)
    transitioned = wire.send(
        Capability.TASKS_TRANSITION.value,
        document_for(
            Capability.TASKS_TRANSITION,
            scene,
            {
                "task_id": task.task_id,
                "to_state": "completed",
                "expected_version": task.version,
                "closure_evidence_ref": "cap_origin0001origin0001",
                "idempotency_key": "terminal-history-transition-0001",
            },
        ),
    ).document()["result"]
    closure_history_id = transitioned["history"]["history_id"]
    terminal = transitioned["task"]
    updated = wire.send(
        Capability.TASKS_UPDATE.value,
        document_for(
            Capability.TASKS_UPDATE,
            scene,
            {
                "task_id": task.task_id,
                "expected_version": terminal["version"],
                "priority": "p1",
                "idempotency_key": "terminal-history-update-0001",
            },
        ),
    )
    assert updated.status == 200
    read = wire.send(
        Capability.TASKS_READ.value,
        document_for(Capability.TASKS_READ, scene, {"task_id": task.task_id}),
    ).document()["result"]["task"]
    assert read["closure_history_id"] == closure_history_id


def test_expired_or_drifted_bulk_confirm_writes_no_task_or_history(
    staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    scene, _ = staged
    task = staged_task(scene)
    mutations = [
        {
            "kind": "update",
            "task_id": task.task_id,
            "expected_version": task.version,
            "values": {"priority": "p2"},
            "clear_fields": [],
        }
    ]
    preview = wire.send(
        Capability.TASKS_BULK_PREVIEW.value,
        document_for(
            Capability.TASKS_BULK_PREVIEW,
            scene,
            {"mutations": mutations, "idempotency_key": "bulk-expired-preview-0001"},
        ),
    ).document()["result"]
    key = (scene.principal.principal_id, preview["bulk_operation_id"])
    scene.world.task_bulk_operations[key] = replace(
        scene.world.task_bulk_operations[key], expires_at=WHEN - timedelta(seconds=1)
    )
    before_tasks = tuple(scene.world.tasks_v2)
    before_history = tuple(scene.world.task_history_v2)
    reply = wire.send(
        Capability.TASKS_BULK_CONFIRM.value,
        document_for(
            Capability.TASKS_BULK_CONFIRM,
            scene,
            {
                "bulk_operation_id": preview["bulk_operation_id"],
                "idempotency_key": "bulk-expired-confirm-0001",
                "mutations": mutations,
            },
        ),
    )
    assert reply.status == 409
    assert tuple(scene.world.tasks_v2) == before_tasks
    assert tuple(scene.world.task_history_v2) == before_history

    drift_preview = wire.send(
        Capability.TASKS_BULK_PREVIEW.value,
        document_for(
            Capability.TASKS_BULK_PREVIEW,
            scene,
            {"mutations": mutations, "idempotency_key": "bulk-drift-preview-0001"},
        ),
    ).document()["result"]
    drifted = replace(task, version=task.version + 1, updated_at=WHEN + timedelta(seconds=1))
    scene.world.tasks_v2[:] = [
        drifted if item.task_id == task.task_id else item for item in scene.world.tasks_v2
    ]
    before_drift_confirm = tuple(scene.world.tasks_v2)
    before_drift_history = tuple(scene.world.task_history_v2)
    drift_reply = wire.send(
        Capability.TASKS_BULK_CONFIRM.value,
        document_for(
            Capability.TASKS_BULK_CONFIRM,
            scene,
            {
                "bulk_operation_id": drift_preview["bulk_operation_id"],
                "idempotency_key": "bulk-drift-confirm-0001",
                "mutations": mutations,
            },
        ),
    )
    assert drift_reply.status == 409
    assert tuple(scene.world.tasks_v2) == before_drift_confirm
    assert tuple(scene.world.task_history_v2) == before_drift_history


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_the_body_is_the_envelope_the_application_produced(
    capability: Capability,
    staged: tuple[Scene, KnowledgeRecord],
    service: RecordingService,
    wire: Wire,
) -> None:
    """No reinterpretation: the body is the envelope's own bytes.

    A transport that reshaped a result, added a field, dropped a disclosure, or
    rewrote an error would fail this without anyone having to predict which of
    those it would do.
    """
    scene, record = staged
    payload = payloads_for(scene, record)[capability]
    reply = wire.send(capability.value, document_for(capability, scene, payload))

    assert len(service.envelopes) == 1, "one request reached the application once"
    produced = service.envelopes[0]
    assert reply.body == produced.to_canonical_json()
    if capability is Capability.TASKS_BULK_CONFIRM:
        expected_status = 404
    elif capability in _UNSUPPORTED_CAPABILITIES:
        expected_status = 501
    else:
        expected_status = 200
    assert reply.status == expected_status
    assert produced.correlation_id in reply.body


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_normalisation_builds_the_pair_a_hand_written_request_builds(
    capability: Capability, staged: tuple[Scene, KnowledgeRecord]
) -> None:
    """The one validation path, per capability (`SPEC-AC-001`, HTTP's half)."""
    scene, record = staged
    payloads = payloads_for(scene, record)
    document = document_for(capability, scene, payloads[capability])
    capture_id = str(payloads[Capability.CAPTURE_READ]["capture_id"])
    bulk_operation_id = str(payloads[Capability.TASKS_BULK_CONFIRM]["bulk_operation_id"])
    counterparty_person_id = str(payloads[Capability.COMMITMENTS_CREATE]["counterparty_person_id"])
    feedback_target_id = str(payloads[Capability.CONTEXT_FEEDBACK]["target_id"])
    metadata, command = normalize(capability.value, document)
    assert (
        command
        == commands_for(
            scene,
            record,
            capture_id,
            bulk_operation_id,
            counterparty_person_id,
            feedback_target_id,
        )[capability]
    )
    assert metadata == metadata_for(capability, a_permitted_purpose(capability), scene.principal)
    assert metadata.requested_at == WHEN


def test_a_denied_request_still_returns_the_application_envelope(scene: Scene, wire: Wire) -> None:
    """An error is an answer, and it arrives in the same shape as a result."""
    stranger = operator()
    document = document_for(Capability.SOURCES_LIST, scene, {"source_id": scene.source.source_id})
    document["principal_id"] = stranger.principal_id
    reply = wire.send(Capability.SOURCES_LIST.value, document)
    # The acting principal is the process's, not the document's, so the request
    # is allowed on the scene's own scope: the claimed identity changed nothing.
    assert reply.status == 200, reply.body
    assert reply.document()["error"] is None


def test_a_caller_supplied_identity_is_correlation_and_not_authority(
    scene: Scene, wire: Wire
) -> None:
    """`docs/specs` section 8.2, over the wire.

    A caller naming a principal it is not gets the authority of the process it
    is talking to and no more — here, less: the audit records the acting
    principal, not the claimed one.
    """
    claimed = operator()
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["principal_id"] = claimed.principal_id
    assert wire.send(Capability.CAPABILITIES_GET.value, document).status == 200
    recorded = {event.principal_id for event in scene.world.audit}
    assert recorded == {scene.principal.principal_id}
    assert claimed.principal_id not in recorded


# ---- status is a function of the error code ----------------------------------


def test_the_status_table_covers_every_public_error_code() -> None:
    """A code with no status would be a `KeyError` in front of a caller."""
    assert set(_STATUS) == set(ErrorCode)


def test_a_denial_is_403_and_an_unknown_record_is_404(scene: Scene, wire: Wire) -> None:
    """Two application answers, two statuses, each read from the code."""
    stranger_scope = document_for(
        Capability.SOURCES_LIST, scene, {"source_id": issue_identifier(IdKind.SOURCE)}
    )
    denied = wire.send(Capability.SOURCES_LIST.value, stranger_scope)
    assert denied.status == 403
    assert denied.document()["error"]["code"] == ErrorCode.DENIED.value

    absent = document_for(
        Capability.KNOWLEDGE_READ,
        scene,
        {
            "knowledge_id": issue_identifier(IdKind.KNOWLEDGE),
            "enrollment_id": scene.enrollment.enrollment_id,
        },
    )
    missing = wire.send(Capability.KNOWLEDGE_READ.value, absent)
    assert missing.status == 404
    assert missing.document()["error"]["code"] == ErrorCode.NOT_FOUND.value


def test_a_store_failure_is_503_and_carries_the_applications_code(scene: Scene, wire: Wire) -> None:
    from my_pa.contracts.ports import EvidenceUnavailableError

    scene.world.failures["coverage"] = EvidenceUnavailableError("the store is unreachable")
    reply = wire.send(
        Capability.SOURCES_LIST.value,
        document_for(Capability.SOURCES_LIST, scene, {"source_id": scene.source.source_id}),
    )
    assert reply.status == 503
    assert reply.document()["error"]["code"] == ErrorCode.UNAVAILABLE.value


# ---- malformed input ---------------------------------------------------------


#: Things a failure report leaks when it is assembled from an exception rather
#: than looked up. None of them may appear in a refusal.
INTERNAL_TEXT = (
    "Traceback",
    "TypeError",
    "ValueError",
    "ValidationError",
    "JSONDecodeError",
    "pydantic",
    "starlette",
    "uvicorn",
    "my_pa",
    "line ",
    'File "',
)


def assert_refused(reply: Any, *, status: int = 400) -> None:  # noqa: ANN401 - a `Reply`
    """A refusal: the right code, the right status, and nothing internal."""
    assert reply.status == status, reply.body
    document = reply.document()
    assert document["code"] == ErrorCode.INVALID_REQUEST.value
    assert document["retry"] == "after_correction"
    assert document["safe_details"] == []
    for fragment in INTERNAL_TEXT:
        assert fragment not in reply.rendered(), f"a refusal disclosed {fragment!r}"


def test_a_body_that_is_not_json_is_refused(wire: Wire) -> None:
    assert_refused(wire.send("capabilities.get", raw="{not json at all"))


def test_a_body_that_is_json_but_not_an_object_is_refused(wire: Wire) -> None:
    assert_refused(wire.send("capabilities.get", raw="[1, 2, 3]"))


def test_the_wrong_content_type_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("capabilities.get", document, content_type="text/plain"))


def test_a_missing_content_type_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("capabilities.get", document, content_type=None))


def test_a_json_content_type_with_a_charset_is_accepted(scene: Scene, wire: Wire) -> None:
    """The parameter is not the media type. A control for the two tests above."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    reply = wire.send("capabilities.get", document, content_type="application/json; charset=utf-8")
    assert reply.status == 200, reply.body


def test_an_unknown_capability_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("sources.destroy", document))


def test_an_unbounded_body_is_refused_without_being_read(scene: Scene, wire: Wire) -> None:
    """No declared length, no read. See `_declared_length`."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("capabilities.get", document, omit_content_length=True))


def test_an_oversized_body_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["payload"] = {}
    padding = "x" * MAX_REQUEST_BYTES
    assert_refused(wire.send("capabilities.get", raw=json.dumps({**document, "pad": padding})))


def test_an_unknown_field_in_the_envelope_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["principal"] = "prn_0000000000000000"
    assert_refused(wire.send("capabilities.get", document))


def test_an_unknown_field_in_the_payload_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(
        Capability.SOURCES_LIST, scene, {"source_id": scene.source.source_id, "recurse": True}
    )
    assert_refused(wire.send("sources.list", document))


def test_a_capability_named_in_the_document_as_well_is_refused(scene: Scene, wire: Wire) -> None:
    """Two places to name one capability is one place too many."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["capability"] = "capabilities.get"
    assert_refused(wire.send("capabilities.get", document))


def test_a_payload_that_is_not_an_object_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.SOURCES_LIST, scene, {})
    document["payload"] = ["src_0000000000000000"]
    assert_refused(wire.send("sources.list", document))


def test_a_malformed_identifier_is_refused_with_the_field_it_names(
    scene: Scene, wire: Wire
) -> None:
    """The command's own refusal, carried through unchanged.

    This one *does* carry a `safe_details` token, which is the difference
    between a refusal the transport made and one the application made. The
    transport reports nothing because it has no token it is allowed to report.
    """
    document = document_for(Capability.SOURCES_LIST, scene, {"source_id": "/etc/passwd"})
    reply = wire.send("sources.list", document)
    assert reply.status == 400
    assert reply.document()["code"] == ErrorCode.INVALID_REQUEST.value
    assert reply.document()["safe_details"] == ["source_id"]
    assert "/etc/passwd" not in reply.rendered()


@pytest.mark.parametrize(
    ("capability", "field", "detail"),
    [
        (Capability.ENTITIES_SEARCH, "query", "query"),
        (Capability.ENTITIES_RESOLVE, "reference", "subject"),
        (Capability.TASKS_CREATE, "title", "title"),
    ],
    ids=lambda value: value.value if isinstance(value, Capability) else str(value),
)
def test_a_field_of_the_wrong_type_is_refused_rather_than_crashing(
    staged: tuple[Scene, KnowledgeRecord],
    wire: Wire,
    capability: Capability,
    field: str,
    detail: str,
) -> None:
    """The ninth review's blocking finding, pinned at the wire.

    `{"query": 123}` used to raise `AttributeError` inside the command, which
    `normalization._command` did not convert (it catches `TypeError`) and this
    transport did not render (it caught `ApplicationError`). The caller received
    a bare `500 Internal Server Error` with no envelope, no typed code and no
    correlation identifier — on a build with the entity plane switched off, too,
    because the command is built before the handler's floor is reached.

    Asserted at 400 rather than merely "not 500": the terminal catch added to
    `invoke` would satisfy the weaker claim with an `internal_error` envelope,
    and `internal_error` tells a caller their correction cannot help. The rule
    across the whole command set is
    `tests/architecture/test_commands_check_the_type_before_the_content.py`;
    this is the transport half, and `tasks.create` is here because it carried
    the same defect at the merge base.
    """
    scene, record = staged
    payload = dict(payloads_for(scene, record)[capability])
    payload[field] = 123
    document = document_for(capability, scene, payload)
    reply = wire.send(capability.value, document)
    assert reply.status == 400, reply.body
    assert reply.document()["code"] == ErrorCode.INVALID_REQUEST.value
    assert reply.document()["safe_details"] == [detail]


def test_a_fault_below_normalization_is_still_answered_in_the_envelope(
    scene: Scene, wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The floor under the rule above, measured rather than asserted.

    A command that reads a field before checking its type is one way to raise
    something that is not an `ApplicationError`; it is not the only way. The CLI
    and MCP transports have always carried a terminal `except Exception` and
    this one did not, which is why HTTP was the transport that answered a bare
    `500`. Here `normalize` is replaced with one that raises the same
    `AttributeError` the missing type check used to raise, and the answer is
    required to be this repository's own vocabulary.
    """

    def explode(capability: str, arguments: Any) -> Any:  # noqa: ANN401 - stand-in
        raise AttributeError("'int' object has no attribute 'strip'")

    monkeypatch.setattr("my_pa.adapters.http.app.normalize", explode)
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    reply = wire.send("capabilities.get", document)
    assert reply.status == 500, reply.body
    assert reply.document()["code"] == ErrorCode.INTERNAL_ERROR.value
    assert reply.document()["correlation_id"]
    assert "strip" not in reply.rendered()


def test_a_fault_reading_the_body_is_still_answered_in_the_envelope(
    scene: Scene, wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The body-read block's terminal catch, which shipped unarmed.

    `read_document` classifies `ClientDisconnect`, `TimeoutError` and every
    `ApplicationError`. Anything else escaped, and this route answered a bare
    `500` while the remote-capture route -- whose equivalent block had gained a
    terminal catch one commit earlier -- answered an envelope. The asymmetry a
    commit claimed to have closed had been inverted rather than closed, and
    nothing caught that because neither block's catch had a test.

    `_document` is the seam: its own docstring describes it raising for a
    composition-invariant violation, which is exactly the class that is not an
    `ApplicationError`.
    """

    def erupt(received: bytes) -> Any:  # noqa: ANN401 - stand-in
        raise RuntimeError("a fault reading the body")

    monkeypatch.setattr("my_pa.adapters.http.app._document", erupt)
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    reply = wire.send("capabilities.get", document)
    assert reply.status == 500, reply.body
    assert reply.document()["code"] == ErrorCode.INTERNAL_ERROR.value
    assert reply.document()["correlation_id"]
    assert "fault reading" not in reply.rendered()


def test_an_unknown_path_is_404_and_a_wrong_method_is_405(scene: Scene, wire: Wire) -> None:
    """HTTP's own answers about a URL, in this repository's error vocabulary."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("", document, path="/not/a/capability"), status=404)
    assert_refused(wire.send("capabilities.get", document, method="GET"), status=405)


# ---- the request ceiling -----------------------------------------------------
#
# The derivation of `MAX_REQUEST_BYTES` moved with the constant, to
# `tests/contract/test_transport_parity.py`: WP-4B2b relocated it out of this
# module into `adapters/normalization.py`, because it is derived from the
# largest request the *contract* can express and is enforced by all three
# transports. What stays here is HTTP's own half — that an oversized body is
# refused on the declared length, above.


def test_the_recording_service_records_what_it_returns(
    staged: tuple[Scene, KnowledgeRecord], service: RecordingService
) -> None:
    """Guard the verbatim test: a recorder that recorded nothing would pass it.

    `len(service.envelopes) == 1` is the assertion doing the work there, so a
    recorder that appended a *different* envelope would still satisfy it. This
    requires the recorded object to be the one returned.
    """
    scene, _ = staged
    returned = service.invoke(
        metadata_for(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    )
    assert service.envelopes == [returned]
    assert service.envelopes[0] is returned


def test_the_wire_helper_reaches_a_server_that_is_not_there() -> None:
    """Guard the client: one that swallowed a failure would pass every test."""
    unreachable = Wire(port=1)
    with pytest.raises(OSError):
        unreachable.send("capabilities.get", {})


def test_an_empty_world_still_answers(world: World) -> None:
    """A control for the fixtures above: the app is real without a scene."""
    principal = operator()
    from tests.conftest import FakeProviders

    with serve(
        create_http_app(build_service(world, FakeProviders({})), principal=principal)
    ) as client:
        reply = client.send(
            "capabilities.get",
            {
                "request_id": "req-bare",
                "purpose": Purpose.STATUS_OBSERVATION.value,
                "principal_id": principal.principal_id,
                "requested_at": "2026-08-02T12:00:00Z",
                "payload": {},
            },
        )
    assert reply.status == 200, reply.body
