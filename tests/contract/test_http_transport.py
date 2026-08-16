"""Every capability over a socket, and nothing decided on the way.

Three claims, and they are different in kind.

**Reachability.** Every one of the forty-five capabilities is addressable over HTTP
and answers. Parametrised over `Capability` rather than over a list written
here, so a forty-sixth capability added to the domain arrives as a failing row instead
of as an untested one.

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
from collections.abc import Iterator
from datetime import UTC, datetime
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
    staged_capture,
    staged_commitment,
    staged_managed_document,
    staged_review_case,
    staged_search,
    staged_task,
)
from tests.wire import Wire, serve

from my_pa.adapters.http import create_http_app
from my_pa.adapters.http.app import _STATUS
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.commands import (
    ArchiveManagedDocument,
    BulkConfirmTasks,
    BulkPreviewTasks,
    CloseCommitment,
    Command,
    CreateCapture,
    CreateCommitment,
    CreateManagedDocument,
    CreateProject,
    CreateSituation,
    CreateTask,
    DecideReviewCase,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetCorpusCoverage,
    GetPulse,
    GetSourceMetadata,
    GetSourceStatus,
    GetTaskHistory,
    ListCaptures,
    ListCommitments,
    ListManagedDocuments,
    ListProjects,
    ListReviewCases,
    ListSituations,
    ListSources,
    ListTasks,
    PrepareContext,
    ReadCapture,
    ReadCommitment,
    ReadKnowledge,
    ReadManagedDocument,
    ReadTask,
    RecordContextFeedback,
    RecordTask,
    Representation,
    RestoreManagedDocument,
    RevealSubject,
    ReviseCapture,
    ReviseManagedDocument,
    SearchCaptures,
    SearchKnowledge,
    SearchTasks,
    TransitionTask,
    UpdateTask,
    WaitingOn,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import KnowledgeRecord
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import Provenance
from my_pa.domain.context.preference import ContextPreferenceAction
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskLifecycleState

ALL_CAPABILITIES = list(Capability)

#: `tasks.bulk_preview` and `tasks.bulk_confirm` are wired all the way through
#: `normalize`, but `ApplicationService._tasks_bulk_preview`/`_tasks_bulk_confirm`
#: are documented placeholders that answer `unsupported` unconditionally — the
#: mutation-simulation and atomic-apply logic they would need is its own work
#: package, not a transport concern. Reachability for these two means exactly
#: that: a well-formed `501 unsupported` envelope, never a silent success.
_UNIMPLEMENTED_CAPABILITIES = frozenset(
    {Capability.TASKS_BULK_PREVIEW, Capability.TASKS_BULK_CONFIRM}
)


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
                    "capability": "tasks.update",
                    "task_id": task.task_id,
                    "expected_version": task.version,
                    "idempotency_key": "http-task-bulk-preview-0001",
                    "title": "HTTP task-plane task, bulk-previewed",
                }
            ],
            "idempotency_key": "http-task-bulk-preview-op-0001",
        },
        Capability.TASKS_BULK_CONFIRM: {
            "bulk_operation_id": issue_identifier(IdKind.BULK_OPERATION),
            "idempotency_key": "http-task-bulk-confirm-0001",
        },
        Capability.COMMITMENTS_READ: {"commitment_id": commitment.commitment_id},
        Capability.COMMITMENTS_LIST: {},
        Capability.COMMITMENTS_WAITING_ON: {},
        Capability.COMMITMENTS_CREATE: {
            "counterparty_person_id": issue_identifier(IdKind.PERSON),
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
        Capability.CONTEXT_PREPARE: {"query": "revenue"},
        Capability.CONTEXT_FEEDBACK: {
            "action": "pin",
            "target_id": issue_identifier(IdKind.PROJECT),
            "idempotency_key": "http-feedback-0001",
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
                    "capability": "tasks.update",
                    "task_id": task.task_id,
                    "expected_version": task.version,
                    "idempotency_key": "http-task-bulk-preview-0001",
                    "title": "HTTP task-plane task, bulk-previewed",
                },
            ),
            idempotency_key="http-task-bulk-preview-op-0001",
        ),
        Capability.TASKS_BULK_CONFIRM: BulkConfirmTasks(
            bulk_operation_id=bulk_operation_id,
            idempotency_key="http-task-bulk-confirm-0001",
        ),
        Capability.COMMITMENTS_READ: ReadCommitment(commitment_id=commitment.commitment_id),
        Capability.COMMITMENTS_LIST: ListCommitments(),
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
        Capability.CONTEXT_PREPARE: PrepareContext(query="revenue"),
        Capability.CONTEXT_FEEDBACK: RecordContextFeedback(
            action=ContextPreferenceAction.PIN,
            target_id=feedback_target_id,
            idempotency_key="http-feedback-0001",
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
    if capability in _UNIMPLEMENTED_CAPABILITIES:
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
    assert reply.status == (501 if capability in _UNIMPLEMENTED_CAPABILITIES else 200)
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
