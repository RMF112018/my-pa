"""`SPEC-AC-001`: three transports, one request, one answer.

The criterion asks that HTTP, MCP, and the CLI produce **byte-equivalent
normalised requests** and semantically identical responses and errors, over all
sixty-five capabilities. There are two ways to prove that and only one of them stays
true, so this file makes the structural claim first and the comparative claim
second.

**Structural: there is one normalisation, and all three call it.** A comparison
of three snapshots proves that three implementations agreed on the day the
snapshots were taken. What actually holds the property is that there is nothing
to disagree: `RequestMetadata` and the sixty-six commands are constructed in exactly
one module, `adapters/normalization.py`, and every transport reaches the
application by handing that module a capability name and a document. The rules
below check both halves by parsing — no transport builds a request value of its
own, and each of the three calls `normalize` and then `invoke`. A transport that
grew a second normalisation fails them whether or not its output happens to
match today.

**Comparative: the same request, sent three ways, normalises to the same pair.**
Structure says the three call one function; it does not say they call it with
equal arguments, and a transport that dropped a field or coerced one would still
pass every rule above. So the pairs are recorded — each transport's own
reference to `normalize` is replaced by a recording wrapper, which is the only
way to see what a transport *built* rather than what it returned — and compared
as bytes: `RequestMetadata` through the contract's own canonical encoding, the
command through its fields.

**And the answers, over all sixty-five fully composed capabilities and ten
refusals.** The default composition exposes fifty-three because the six
managed-document and six Relationship Intelligence capabilities are withheld
without their explicit configuration. Each
transport answers from its own deep copy of the world, so all three see the same
starting state rather than the state the previous one left; without that,
`sources.enroll` alone would make the second and third callers idempotent
retries of the first and the comparison would be measuring an ordering.

Two answers are compared after masking the identifiers the *request minted* —
the correlation identifier of every response, the enrollment and operation a
successful enrollment creates. They are masked positionally rather than dropped,
so an answer that reuses one identifier in two places still has to agree about
that, and an identifier the request supplied is compared literally because it is
not minted. What "semantically identical" excludes is exactly this: the same
request made twice over *one* transport differs by the same fields.
"""

from __future__ import annotations

import ast
import json
import re
from base64 import b64encode
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields as dataclass_fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import (
    WHEN,
    FakeProviders,
    FakeUnitOfWork,
    Scene,
    build_service,
    staged_capture,
    staged_commitment,
    staged_goodnotes_raster,
    staged_goodnotes_work,
    staged_managed_document,
    staged_record,
    staged_review_case,
    staged_search,
    staged_task,
)
from tests.transports import CLI_OPTIONS, CLI_SCOPE_OPTIONS, TRANSPORTS, Answer

import my_pa.adapters.cli.app as cli_module
import my_pa.adapters.http.app as http_module
import my_pa.adapters.mcp.server as mcp_module
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.commands import Command
from my_pa.application.intelligence import begin_cycle, commit_artifact
from my_pa.contracts.ports import KnowledgeRecord
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.proposal import MAX_NORMALIZED_VALUE_CHARACTERS
from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    make_identifier,
    validate_identifier,
)
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.domain.relationship.entity import (
    Entity,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_ITEMS
from my_pa.domain.source.registry import issue_identifier

PACKAGE = Path(cli_module.__file__).resolve().parents[2]
ADAPTERS = PACKAGE / "adapters"

#: Where each transport keeps its reference to `normalize`. `from ... import
#: normalize` binds the function into the importing module, so replacing the
#: name in `adapters.normalization` would replace nothing a transport calls.
#: `test_every_transport_module_that_normalises_is_recorded` checks this list
#: against the tree, so a fourth transport cannot be forgotten here.
NORMALIZE_SITES = (cli_module, http_module, mcp_module)

TRANSPORT_NAMES = frozenset({"http", "mcp", "cli"})
CORRECTED_VALUE_MARKER = "PRIVATE-CORRECTED-VALUE-MARKER"


def a_permitted_purpose(capability: Capability) -> Purpose:
    return sorted(permitted_purposes(capability))[0]


def a_forbidden_purpose(capability: Capability) -> Purpose:
    """A purpose the domain does not permit, derived from the domain's own rule."""
    permitted = permitted_purposes(capability)
    return next(purpose for purpose in sorted(Purpose) if purpose not in permitted)


def document(
    capability: Capability,
    principal_id: str,
    payload: Mapping[str, Any],
    *,
    purpose: Purpose | None = None,
) -> dict[str, Any]:
    """One request, in the shape every transport carries it."""
    return {
        "request_id": f"req-{capability.value}",
        "purpose": (purpose or a_permitted_purpose(capability)).value,
        "principal_id": principal_id,
        "requested_at": "2026-08-02T12:00:00Z",
        "payload": dict(payload),
    }


#: The address the staged person is recorded at, so `entities.resolve` answers
#: `resolved_exact` rather than `not_found`. Synthetic, in a reserved domain: no
#: live address reaches a test.
ENTITY_EMAIL = "parity.person@example.invalid"


def staged_entities(scene: Scene) -> tuple[Entity, Entity]:
    """One person, one organization, and the edge between them.

    Written through the entity repository rather than pushed into `World`
    directly, for the reason `staged_capture` is: the rows are then ones a
    writer can actually reach. One pair per Principal per scene, like
    `staged_task`: a payload table that staged a fresh pair on every call would
    name a different entity each time it was read, and every comparison below
    would be measuring the staging rather than the request.

    Shared with `tests/contract/test_http_transport.py` and
    `tests/security/test_http_negative_evidence.py` rather than repeated in
    each: those files stage their own `KnowledgeRecord` because theirs carries
    their own marker text, and an entity carries none — three copies of one
    staging would only be three things to keep in step.
    """
    principal_id = scene.principal.principal_id
    held = {
        entity.entity_type: entity
        for entity in scene.world.entities
        if entity.principal_id == principal_id
    }
    if EntityType.PERSON in held and EntityType.ORGANIZATION in held:
        return held[EntityType.PERSON], held[EntityType.ORGANIZATION]
    entities = FakeUnitOfWork(scene.world).entities
    person = entities.create(
        principal_id, _entity(principal_id, EntityType.PERSON, "Parity Person")
    )
    organization = entities.create(
        principal_id, _entity(principal_id, EntityType.ORGANIZATION, "Parity Works")
    )
    entities.bind_identifier(
        principal_id,
        person.entity_id,
        ExternalIdentifier(
            identifier_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
            entity_id=person.entity_id,
            namespace=ExternalIdentifierNamespace.EMAIL,
            normalized_value=ENTITY_EMAIL,
            display_value=ENTITY_EMAIL,
            principal_id=principal_id,
            verified=True,
        ),
    )
    entities.record_relationship(
        principal_id,
        EntityRelationship(
            relationship_id=issue_identifier(IdKind.ENTITY_RELATIONSHIP),
            from_entity_id=person.entity_id,
            relationship_type=EntityRelationshipType.WORKS_FOR,
            to_entity_id=organization.entity_id,
            principal_id=principal_id,
        ),
    )
    return person, organization


def _entity(principal_id: str, entity_type: EntityType, display_name: str) -> Entity:
    """One active entity, its canonical name in the form resolution compares."""
    return Entity(
        entity_id=issue_identifier(IdKind.ENTITY),
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=display_name.casefold(),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def payloads_for(scene: Scene, record: KnowledgeRecord) -> dict[Capability, dict[str, Any]]:
    """A payload per capability that the application can actually answer.

    Optional fields are supplied deliberately rather than left out: a transport
    that dropped `max_bytes`, coerced `metadata_only`, or lost `representation`
    would answer identically to one that did not if the request never carried
    them.
    """
    capture = staged_capture(scene)
    review_case = staged_review_case(scene, capture)
    managed_document = staged_managed_document(scene)
    task = staged_task(scene)
    commitment = staged_commitment(scene)
    bulk_mutations = [
        {
            "kind": "update",
            "task_id": task.task_id,
            "expected_version": task.version,
            "values": {"priority": "p1"},
            "clear_fields": [],
        }
    ]
    preview_metadata, preview_command = normalize(
        Capability.TASKS_BULK_PREVIEW.value,
        document(
            Capability.TASKS_BULK_PREVIEW,
            scene.principal.principal_id,
            {
                "mutations": bulk_mutations,
                "idempotency_key": f"parity-task-bulk-setup-v{task.version:04d}",
            },
        ),
    )
    preview = build_service(scene.world, scene.providers).invoke(
        preview_metadata,
        preview_command,
        principal=scene.principal,
    )
    assert preview.error is None and preview.result is not None
    bulk_operation_id = preview.result["bulk_operation_id"]
    assert isinstance(bulk_operation_id, str)
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    at = datetime(2026, 8, 2, 11, tzinfo=UTC)
    cycle_admission = begin_cycle(
        scene.world.intelligence,
        principal_id=scene.principal.principal_id,
        cycle_id=CYCLE_MORNING_INTELLIGENCE,
        business_date=date(2026, 8, 20),
        idempotency_key="parity-cycle-setup",
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
        producer_task_id="parity-setup-collector",
        producer_task_name="Parity setup collector",
        automation_platform="abacus_chatllm",
        automation_run_id=None,
        report_date=date(2026, 8, 20),
        title="Parity setup collector",
        body_markdown="synthetic collector",
        artifact_state=ArtifactState.FINAL,
        schema_version="1",
        idempotency_key="parity-setup-collector",
        at=at,
    )
    assert collector_admission.artifact is not None
    report_id = collector_admission.artifact.artifact_id
    person, organization = staged_entities(scene)
    return {
        Capability.CAPABILITIES_GET: {},
        Capability.SOURCES_LIST: {"source_id": scene.source.source_id, "page_size": 10},
        Capability.SOURCES_METADATA: {
            "source_id": scene.source.source_id,
            "source_object_id": scene.markdown.source_object_id,
        },
        Capability.SOURCES_FETCH: {
            "source_id": scene.source.source_id,
            "source_object_id": scene.markdown.source_object_id,
            "representation": "normalized_text",
            "max_bytes": 4096,
        },
        Capability.SOURCES_STATUS: {"source_id": scene.source.source_id},
        Capability.SOURCES_ENROLL: {
            "source_id": scene.source.source_id,
            "media_types": ["text/markdown"],
            "idempotency_key": "parity-probe-0001",
            "object_ids": [scene.markdown.source_object_id],
            "depth": 0,
        },
        Capability.KNOWLEDGE_SEARCH: {
            "enrollment_id": scene.enrollment.enrollment_id,
            "query": "quarterly",
            "page_size": 10,
        },
        Capability.KNOWLEDGE_READ: {
            "knowledge_id": record.knowledge_id,
            "enrollment_id": scene.enrollment.enrollment_id,
            "metadata_only": False,
        },
        # The capture plane names no source and no enrollment: a capture is a
        # product-owned record under `ADR-003` and belongs to neither. `capture`
        # is staged before the world is copied per transport, so all three see
        # the same stored chain and a revise is the same revise everywhere.
        Capability.CAPTURE_CREATE: {
            "text": "a synthetic parity note",
            "idempotency_key": "parity-capture-0001",
            "client_created_at": "2026-08-02T11:00:00Z",
            "occurred_at": "2026-08-02T10:00:00Z",
        },
        Capability.CAPTURE_REVISE: {
            "capture_id": capture.capture_id,
            "text": "a synthetic parity note, revised",
            "idempotency_key": "parity-capture-revise-0001",
        },
        Capability.CAPTURE_READ: {
            "capture_id": capture.capture_id,
            "version_id": capture.version_id,
        },
        Capability.CAPTURE_LIST: {"page_size": 10},
        Capability.CAPTURE_SEARCH: {"query": "synthetic", "page_size": 10},
        # The staged capture, whose derivation has not run in this world, so
        # every transport answers the same `unavailable` reveal rather than
        # the same empty one — which is the parity claim that matters here.
        Capability.KNOWLEDGE_REVEAL: {"subject_id": capture.capture_id},
        Capability.REVIEW_LIST: {"page_size": 10},
        # The continuity reads: the Pulse takes no payload at all, and the two
        # listings take only a bound. Nothing here names a scope, because
        # continuity belongs to no source.
        Capability.CONTINUITY_PULSE: {},
        Capability.CONTINUITY_SITUATIONS: {"page_size": 10},
        Capability.CONTINUITY_PROJECTS: {"page_size": 10},
        Capability.CONTINUITY_PROJECTS_CREATE: {
            "name": "Parity authoring project",
            "idempotency_key": "parity-project-0001",
        },
        Capability.CONTINUITY_SITUATIONS_CREATE: {
            "title": "Parity authoring situation",
            "idempotency_key": "parity-situation-0001",
        },
        Capability.CONTINUITY_TASKS_CREATE: {
            "title": "Parity authoring task",
            "idempotency_key": "parity-task-0001",
        },
        # The corpus coverage answer has no payload at all: there is no scope to
        # name and no page to bound, because the ranking is the whole answer.
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
            "document_id": managed_document.document_id,
            "expected_version_number": managed_document.version_number,
            "title": "Synthetic parity document, revised",
            "media_type": "text/markdown",
            "content": b64encode(b"# Synthetic parity document, revised").decode("ascii"),
            "idempotency_key": "parity-document-revise-0001",
        },
        Capability.DOCUMENTS_READ: {
            "document_id": managed_document.document_id,
            "version_id": managed_document.version_id,
            "include_bytes": True,
        },
        Capability.DOCUMENTS_LIST: {"limit": 10, "include_archived": True},
        Capability.DOCUMENTS_ARCHIVE: {"document_id": managed_document.document_id},
        Capability.DOCUMENTS_RESTORE: {"document_id": managed_document.document_id},
        # The task-management plane (WP-TM-01..05). `task`/`commitment` are
        # staged before the world is copied per transport, so all three see the
        # same stored rows and a read is the same read everywhere.
        Capability.TASKS_READ: {"task_id": task.task_id},
        Capability.TASKS_LIST: {},
        Capability.TASKS_SEARCH: {"query": "synthetic"},
        Capability.TASKS_HISTORY: {"task_id": task.task_id},
        Capability.TASKS_CREATE: {
            "title": "Parity task-plane task",
            "origin_evidence_ref": "cap_origin0001origin0001",
            "idempotency_key": "parity-task-create-0001",
        },
        Capability.TASKS_UPDATE: {
            "task_id": task.task_id,
            "expected_version": task.version,
            "idempotency_key": "parity-task-update-0001",
            "title": "Parity task-plane task, revised",
        },
        Capability.TASKS_TRANSITION: {
            "task_id": task.task_id,
            "to_state": "in_progress",
            "expected_version": task.version,
            "idempotency_key": "parity-task-transition-0001",
        },
        Capability.TASKS_BULK_PREVIEW: {
            "mutations": bulk_mutations,
            "idempotency_key": "parity-task-bulk-preview-op-0001",
        },
        Capability.TASKS_BULK_CONFIRM: {
            "bulk_operation_id": bulk_operation_id,
            "idempotency_key": "parity-task-bulk-confirm-0001",
            "mutations": bulk_mutations,
        },
        Capability.COMMITMENTS_READ: {"commitment_id": commitment.commitment_id},
        Capability.COMMITMENTS_LIST: {},
        Capability.COMMITMENTS_SEARCH: {"query": "synthetic", "page_size": 10},
        Capability.COMMITMENTS_HISTORY: {
            "commitment_id": commitment.commitment_id,
            "page_size": 10,
        },
        Capability.COMMITMENTS_WAITING_ON: {},
        Capability.COMMITMENTS_CREATE: {
            "counterparty_person_id": commitment.counterparty_person_id,
            "direction": "owed_by_principal",
            "summary": "Parity commitment-plane commitment",
            "origin_evidence_ref": "cap_origin0001origin0001",
            "idempotency_key": "parity-commitment-create-0001",
        },
        Capability.COMMITMENTS_UPDATE: {
            "commitment_id": commitment.commitment_id,
            "expected_version": commitment.version,
            "summary": "Parity commitment-plane commitment, revised",
            "idempotency_key": "parity-commitment-update-0001",
        },
        Capability.COMMITMENTS_CLOSE: {
            "commitment_id": commitment.commitment_id,
            "expected_version": commitment.version,
            "closure_evidence_ref": "cap_origin0001origin0001",
            "idempotency_key": "parity-commitment-close-0001",
        },
        Capability.CONTEXT_PREPARE: {"query": "quarterly"},
        Capability.CONTEXT_FEEDBACK: {
            "action": "pin",
            "target_id": issue_identifier(IdKind.PROJECT),
            "idempotency_key": "parity-feedback-0001",
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
            "idempotency_key": "parity-goodnotes-propose-0001",
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
        Capability.REPORTS_BEGIN_CYCLE: {
            "cycle_id": CYCLE_MORNING_INTELLIGENCE,
            "business_date": "2026-08-20",
            "idempotency_key": "parity-cycle-0001",
        },
        Capability.REPORTS_COMMIT: {
            "cycle_run_id": cycle_run_id,
            "stage": "collector",
            "artifact_kind": "collector_candidates",
            "focus_area_id": "communications",
            "producer_task_id": "parity-collector",
            "producer_task_name": "Parity Collector",
            "automation_platform": "abacus_chatllm",
            "report_date": "2026-08-20",
            "title": "Parity collector",
            "body_markdown": "synthetic collector",
            "artifact_state": "final",
            "schema_version": "1",
            "idempotency_key": "parity-report-commit-0001",
        },
        Capability.REPORTS_RECORD_RUN_STATE: {
            "cycle_run_id": cycle_run_id,
            "stage": "researcher",
            "artifact_kind": "research_context",
            "focus_area_id": "communications",
            "source_lane": "teams",
            "producer_task_id": "parity-researcher",
            "producer_task_name": "Parity Researcher",
            "automation_platform": "abacus_chatllm",
            "report_date": "2026-08-20",
            "state": "failed",
            "idempotency_key": "parity-run-state-0001",
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
        # `organization` are staged before the world is copied per transport, so
        # all three read the same rows and a read is the same read everywhere.
        # Every optional field is supplied for the reason this docstring gives:
        # a transport that dropped `entity_type`, `namespace`, `as_of`, or
        # `direction` would answer identically to one that did not if the
        # request never carried them.
        Capability.ENTITIES_SEARCH: {
            "query": "parity",
            "entity_type": "person",
            "page_size": 10,
        },
        Capability.ENTITIES_GET: {"entity_id": person.entity_id},
        # The reference is the address bound to `person`, stated in its own
        # namespace rather than sniffed, so this resolves rather than answering
        # the `not_found` outcome an unknown reference answers with — which is a
        # `200` either way, and the weaker of the two things to compare.
        Capability.ENTITIES_RESOLVE: {
            "reference": ENTITY_EMAIL,
            "namespace": "email",
            "entity_type": "person",
            "scope_entity_id": organization.entity_id,
            "as_of": "2026-08-02T12:00:00Z",
        },
        Capability.ENTITIES_CONTEXT: {"entity_id": person.entity_id},
        Capability.ENTITIES_RELATIONSHIPS: {
            "entity_id": person.entity_id,
            "direction": "any",
        },
        # No arguments: the queue is every unplaced mention in the Principal's
        # own partition, so there is nothing to name.
        Capability.ENTITIES_UNRESOLVED_MENTIONS: {},
    }


@pytest.fixture
def staged(scene: Scene) -> tuple[Scene, KnowledgeRecord]:
    """A scene with a readable record and a staged search page."""
    record = staged_record(scene, text="quarterly revenue review")
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    return scene, record


def answers_for(
    scene: Scene, capability: str, request: Mapping[str, Any] | None
) -> dict[str, Answer]:
    """Send one request over every transport, each from its own copy of the world.

    The world is deep-copied per transport rather than shared, because three
    callers against one mutable world are three different requests: the second
    `sources.enroll` is an idempotent retry of the first and answers with a null
    operation, which is the application behaving correctly and the comparison
    measuring the wrong thing. The provider is not copied — it is read-only over
    a real fixture tree, which is the point of it.
    """
    answers: dict[str, Answer] = {}
    for build in TRANSPORTS:
        world = deepcopy(scene.world)
        service = build_service(world, FakeProviders({scene.source.source_id: scene.provider}))
        with build(service, scene.principal) as transport:
            answers[transport.name] = transport.send(capability, request)
    assert set(answers) == TRANSPORT_NAMES, f"only {sorted(answers)} answered"
    return answers


# ---- structural: one normalisation, and every transport calls it -------------


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _called(path: Path) -> set[str]:
    """Every name called in `path`, whether bare or as an attribute."""
    tree = _tree(path)
    bare = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    return bare | attributes


#: The request values a second normalisation would have to build. Derived from
#: the command union rather than listed, so a ninth command is covered by having
#: been declared.
REQUEST_VALUES = frozenset(
    {"RequestMetadata", *(member.__name__ for member in Command.__value__.__args__)}
)

#: Pydantic's other two constructors. `RequestMetadata.model_validate(document)`
#: builds one exactly as calling the class does, and `model_construct` builds one
#: while **skipping every validator** — which would be a second normalisation
#: that is not merely a copy of the first but a weaker one.
MODEL_CONSTRUCTORS = frozenset({"model_validate", "model_validate_json", "model_construct"})


def _builds_a_request_value(path: Path) -> set[str]:
    """How `path` constructs a request value, by whatever route.

    A previous version collected call *names* only, and an independent review
    walked past it twice in one plant: `RequestMetadata.model_validate(...)` is
    not a call to `RequestMetadata`, and `import RequestMetadata as _RM; _RM(...)`
    is not a call to that name either. Both built a real second normalisation in
    `adapters/mcp/server.py` while every structural rule here passed.

    So the check resolves the *binding* first — every local name a request value
    was imported under, alias included, which is what made the name check
    evadable — and then flags a call on any of those bindings, plus any of
    pydantic's constructors reached through an attribute on anything at all.
    `model_construct` is on that list and matters most: it builds a model while
    skipping every validator, so it would be a second normalisation that is not
    a copy of the first but a weaker one.

    **Reading is not building, and the line is drawn there deliberately.**
    `adapters/mcp/tools.py` imports `RequestMetadata` to call
    `model_json_schema()` on it, because the tool schema it publishes has to be
    the document `normalize` actually accepts; deriving that from the model is
    the opposite of building a second one. Making the bare import an offence
    would have forced that derivation somewhere worse to satisfy a rule about
    something it does not do.
    """
    tree = _tree(path)
    bindings = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in REQUEST_VALUES
    } | REQUEST_VALUES
    offences: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in bindings:
            offences.add(node.func.id)
        elif isinstance(node.func, ast.Attribute) and node.func.attr in MODEL_CONSTRUCTORS:
            offences.add(f"{node.func.attr}()")
    return offences


def _transport_modules() -> list[Path]:
    """Every adapter module that is not the normalisation itself."""
    return sorted(p for p in ADAPTERS.rglob("*.py") if p != ADAPTERS / "normalization.py")


def test_there_are_three_transports_to_compare() -> None:
    """Guard every rule below: an empty list passes them all."""
    subtrees = {p.relative_to(ADAPTERS).parts[0] for p in _transport_modules()}
    assert subtrees >= TRANSPORT_NAMES, f"only {sorted(subtrees)} exist"
    assert len(REQUEST_VALUES) == 66, f"the command union changed shape: {sorted(REQUEST_VALUES)}"


@pytest.mark.parametrize("path", _transport_modules(), ids=lambda p: str(p.name))
def test_no_transport_builds_a_request_value_of_its_own(path: Path) -> None:
    """`SPEC-AC-001` structurally: there is one place a request is built.

    Parity between three transports is provable rather than sampled only while
    none of them can construct a `RequestMetadata` or a command. A transport
    that could would be a second validation path, and the criterion would fall
    back to "the snapshots agreed when they were taken".
    """
    offending = sorted(_builds_a_request_value(path))
    assert not offending, (
        f"{path.relative_to(PACKAGE)} builds {offending}; requests are normalised in "
        "adapters/normalization.py and nowhere else"
    )


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("called directly", "def go(f: dict) -> object:\n    return RequestMetadata(**f)\n"),
        (
            "called under an alias",
            "from my_pa.contracts.v1.envelope import RequestMetadata as _RM\n\n\n"
            "def go(f: dict) -> object:\n    return _RM(**f)\n",
        ),
        (
            "built by model_validate",
            "from my_pa.contracts.v1.envelope import RequestMetadata\n\n\n"
            "def go(f: dict) -> object:\n    return RequestMetadata.model_validate(f)\n",
        ),
        (
            "built by model_construct, skipping every validator",
            "def go(f: dict, m: object) -> object:\n    return m.model_construct(**f)\n",
        ),
        (
            "a command under an alias",
            "from my_pa.application.commands import ListSources as _LS\n\n\n"
            "def go(f: dict) -> object:\n    return _LS(**f)\n",
        ),
    ],
    ids=lambda value: str(value),
)
def test_the_structural_guard_catches_every_route_to_a_second_normalisation(
    tmp_path: Path, name: str, source: str
) -> None:
    """The four ways a second normalisation can be written, each planted.

    An independent review demonstrated that the first three of these evaded the
    guard entirely — it read call names, and two of these are not calls to a
    name at all. A rule this file's whole structural claim rests on has to be
    checked against the ways round it, not only the obvious one.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(source, encoding="utf-8")
    assert _builds_a_request_value(planted), f"{name} escaped the structural guard"


@pytest.mark.parametrize(
    ("name", "source"),
    [
        (
            "a transport that calls normalize",
            "from my_pa.adapters.normalization import normalize\n\n\n"
            "def go(name: str, document: dict) -> object:\n"
            "    return normalize(name, document)\n",
        ),
        (
            "reading the schema off the model",
            "from my_pa.contracts.v1.envelope import RequestMetadata\n\n\n"
            "def schema() -> dict:\n    return RequestMetadata.model_json_schema()\n",
        ),
        (
            "annotating a value it was handed",
            "from my_pa.contracts.v1.envelope import RequestMetadata\n\n\n"
            "def go(metadata: RequestMetadata) -> str:\n    return metadata.request_id\n",
        ),
    ],
    ids=lambda value: str(value),
)
def test_the_structural_guard_does_not_fire_on_reading_or_annotating(
    tmp_path: Path, name: str, source: str
) -> None:
    """The narrowing is bounded and deliberate: reading a model is not building one.

    Without this, a guard that flagged every mention would pass every planted
    violation above while making the rule unusable, and the next author would
    weaken the rule rather than the code. `adapters/mcp/tools.py` is the real
    instance of the middle case.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(source, encoding="utf-8")
    assert not _builds_a_request_value(planted), f"{name} was wrongly flagged"


@pytest.mark.parametrize("subtree", sorted(TRANSPORT_NAMES))
def test_every_transport_reaches_the_application_through_normalize(subtree: str) -> None:
    """The positive half: a transport that built nothing would pass the rule above."""
    called: set[str] = set()
    for path in sorted((ADAPTERS / subtree).rglob("*.py")):
        called |= _called(path)
    assert "normalize" in called, f"adapters/{subtree} never calls normalize"
    assert "invoke" in called, f"adapters/{subtree} never calls the application"


def test_the_structural_guard_catches_a_planted_normalisation(tmp_path: Path) -> None:
    """Plant the second normalisation the rule exists to forbid."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def build(fields: dict) -> object:\n"
        "    return RequestMetadata(**fields), ListSources(**fields)\n",
        encoding="utf-8",
    )
    assert _called(planted) & REQUEST_VALUES == {"RequestMetadata", "ListSources"}


def test_every_transport_module_that_normalises_is_recorded() -> None:
    """The recording below covers every transport, not the ones a reader remembered."""
    recorded = {Path(module.__file__ or "").resolve() for module in NORMALIZE_SITES}
    calling = {path for path in _transport_modules() if "normalize" in _called(path)}
    assert calling == recorded, f"{sorted(calling ^ recorded)} normalises and is not recorded"


# ---- comparative: the same request normalises to the same pair ---------------

Pair = tuple[RequestMetadata, Command]


@contextmanager
def recording(into: dict[str, list[Pair]], monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Replace each transport's `normalize` with one that records what it built.

    Each module's own binding, because `from ... import normalize` copies the
    function into the importing module and patching the source would patch
    nothing. The wrapper calls the real function and changes no behaviour; what
    it adds is the only view of the pair a transport constructs, which is
    otherwise invisible from outside.
    """
    for module in NORMALIZE_SITES:
        name = module.__name__.split(".")[2]

        def record(capability: str, arguments: Mapping[str, Any], _transport: str = name) -> Pair:
            pair = normalize(capability, arguments)
            into.setdefault(_transport, []).append(pair)
            return pair

        monkeypatch.setattr(module, "normalize", record)
    yield


def as_bytes(pair: Pair) -> tuple[str, str]:
    """One normalised request, rendered so equality is byte equality.

    The metadata through the contract's own canonical encoding — sorted keys,
    fixed separators — and the command through its fields, because a dataclass
    has no serialisation of its own and `repr` omits `SearchKnowledge.query`
    deliberately, which is exactly the field a comparison must not skip.
    """
    metadata, command = pair
    payload = {field.name: getattr(command, field.name) for field in dataclass_fields(command)}
    return metadata.to_canonical_json(), json.dumps(payload, sort_keys=True, default=str)


def normalised_by_each(
    scene: Scene,
    capability: str,
    request: Mapping[str, Any] | None,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, tuple[str, str]]:
    built: dict[str, list[Pair]] = {}
    with recording(built, monkeypatch):
        answers_for(scene, capability, request)
    assert set(built) == TRANSPORT_NAMES, f"only {sorted(built)} normalised anything"
    assert all(len(pairs) == 1 for pairs in built.values()), "a transport normalised twice"
    return {name: as_bytes(pairs[0]) for name, pairs in built.items()}


@pytest.mark.parametrize("capability", list(Capability), ids=lambda c: c.value)
def test_every_capability_normalises_identically_over_all_three_transports(
    capability: Capability,
    staged: tuple[Scene, KnowledgeRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SPEC-AC-001`, the byte-equivalence half, one row per capability."""
    scene, record = staged
    request = document(
        capability, scene.principal.principal_id, payloads_for(scene, record)[capability]
    )
    rendered = normalised_by_each(scene, capability.value, request, monkeypatch)
    distinct = set(rendered.values())
    assert len(distinct) == 1, f"{capability.value} normalised differently: {rendered}"


def test_the_recording_would_have_seen_a_difference(
    staged: tuple[Scene, KnowledgeRecord], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard the comparison: one that could not see a difference always passes.

    A transport is handed a request differing in one envelope field and the
    recorded pairs are required to differ. Without this, the equality above
    would also hold on a harness that recorded one object three times.
    """
    scene, _record = staged
    built: dict[str, list[Pair]] = {}
    plain = document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {})
    other = {**plain, "request_id": "req-a-different-one"}
    assert other != plain, "the control sends the same request twice"
    with recording(built, monkeypatch):
        for index, build in enumerate(TRANSPORTS):
            service = build_service(deepcopy(scene.world), scene.providers)
            with build(service, scene.principal) as transport:
                transport.send(Capability.CAPABILITIES_GET.value, other if index == 0 else plain)
    rendered = {name: as_bytes(pairs[0]) for name, pairs in built.items()}
    assert len(set(rendered.values())) == 2, rendered


# ---- comparative: the same answer --------------------------------------------


def _identifiers(value: Any) -> set[str]:  # noqa: ANN401 - walks a decoded document
    """Every opaque identifier anywhere in a decoded document.

    Recognised by asking the domain rather than by a pattern written here, so
    what counts as an identifier is what the contract says one is.
    """
    if isinstance(value, str):
        try:
            validate_identifier(value)
        except InvalidIdentifierError:
            return set()
        return {value}
    if isinstance(value, dict):
        return {found for item in value.values() for found in _identifiers(item)}
    if isinstance(value, list):
        return {found for item in value for found in _identifiers(item)}
    return set()


def _kind_of(identifier: str) -> str:
    """The kind prefix an identifier declares, as the domain defines it.

    `corr_…` is a correlation identifier and `op_…` is an operation; the domain
    already carries the distinction and this reads it rather than restating it.
    """
    return identifier.partition("_")[0]


def masked(answer: Mapping[str, Any], supplied: set[str]) -> Any:  # noqa: ANN401 - a document
    """The answer with request-minted identifiers replaced by stable placeholders.

    Positional rather than dropped: the placeholder is numbered by order of
    first appearance, so an answer that repeats one identifier in two places
    still has to agree about that. An identifier the *request* carried is left
    alone and compared literally, because it was not minted and a transport that
    returned a different one would be answering about a different subject.

    **The placeholder carries the kind, and leaving it out was a hole.** An
    independent review had one transport swap `correlation_id` with
    `result.operation_id` before returning, and the whole tier stayed green:
    with a purely positional placeholder, exchanging two identifiers that each
    appear once also exchanges their first-appearance order, so the two
    renderings are byte-identical. The mask was erasing the one property that
    made the swap wrong — that a correlation identifier is not an operation
    identifier. Numbering *within* a kind keeps the ordering claim and makes a
    permutation across kinds visible, which is what `corr` and `op` being
    different prefixes already meant.
    """
    minted: dict[str, str] = {}
    counts: dict[str, int] = {}

    def placeholder(identifier: str) -> str:
        kind = _kind_of(identifier)
        counts[kind] = counts.get(kind, 0) + 1
        return f"<minted-{kind}-{counts[kind] - 1}>"

    def walk(value: Any) -> Any:  # noqa: ANN401 - a decoded JSON document
        if isinstance(value, str) and value not in supplied and _identifiers(value):
            if value not in minted:
                minted[value] = placeholder(value)
            return minted[value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(dict(answer))


def assert_same_answer(
    answers: Mapping[str, Answer], request: Mapping[str, Any] | None, where: str
) -> None:
    """Every transport returned the same answer and the same success signal."""
    supplied = _identifiers(dict(request or {}))
    documents = {name: masked(answer.document, supplied) for name, answer in answers.items()}
    first = next(iter(documents.values()))
    for name, body in documents.items():
        assert body == first, (
            f"{where}: {name} answered differently\n{json.dumps(body, indent=1)}\n"
            f"{json.dumps(first, indent=1)}"
        )
    signals = {name: answer.failed for name, answer in answers.items()}
    assert len(set(signals.values())) == 1, f"{where}: transports disagreed on success {signals}"


@pytest.mark.parametrize("capability", list(Capability), ids=lambda c: c.value)
def test_every_capability_answers_identically_over_all_three_transports(
    capability: Capability, staged: tuple[Scene, KnowledgeRecord]
) -> None:
    """`SPEC-AC-001`, the answer half, one row per capability."""
    scene, record = staged
    request = document(
        capability, scene.principal.principal_id, payloads_for(scene, record)[capability]
    )
    answers = answers_for(scene, capability.value, request)
    assert not any(answer.failed for answer in answers.values()), answers
    for name, answer in answers.items():
        assert answer.document["error"] is None, f"{name} refused {capability.value}"
        assert answer.document["request_id"] == request["request_id"]
    assert_same_answer(answers, request, capability.value)


def test_the_mask_hides_a_minted_identifier_and_nothing_else(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    """Guard the mask: one that hid everything would report agreement on anything.

    An enrollment is the case that needs it — the answer carries an enrollment
    and an operation identifier that did not exist when the request was made —
    so the mask must hide those three (with the correlation identifier) and
    leave the source identifier the request supplied alone.
    """
    scene, record = staged
    request = document(
        Capability.SOURCES_ENROLL,
        scene.principal.principal_id,
        payloads_for(scene, record)[Capability.SOURCES_ENROLL],
    )
    answers = answers_for(scene, Capability.SOURCES_ENROLL.value, request)
    supplied = _identifiers(request)
    rendered = json.dumps(masked(answers["http"].document, supplied))
    placeholders = set(re.findall(r"<minted-[a-z]+-\d+>", rendered))
    assert len(placeholders) >= 3, rendered
    # And each names the kind it stands for, so a permutation across kinds is a
    # difference rather than a relabelling.
    assert {"<minted-corr-0>", "<minted-enr-0>", "<minted-op-0>"} <= placeholders, placeholders
    assert scene.source.source_id in rendered, "a supplied identifier was masked"
    assert not _identifiers(json.loads(rendered)) - supplied, "an identifier escaped the mask"


def test_the_mask_does_not_absorb_a_permutation_of_two_identifiers(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    """The hole an independent review found, planted here so it stays closed.

    One transport is made to return the correlation identifier where the
    operation identifier belongs and vice versa. Under the purely positional
    mask this file first shipped, the two renderings were byte-identical — the
    swap also swapped the order of first appearance — and the entire tier passed
    while a transport was returning an operation identifier as a correlation
    identifier. Keying the placeholder on the kind is what makes the exchange a
    difference, and this is what says so.
    """
    scene, record = staged
    request = document(
        Capability.SOURCES_ENROLL,
        scene.principal.principal_id,
        payloads_for(scene, record)[Capability.SOURCES_ENROLL],
    )
    answers = answers_for(scene, Capability.SOURCES_ENROLL.value, request)
    honest = answers["http"].document
    assert honest["correlation_id"] != honest["result"]["operation_id"]

    swapped = deepcopy(honest)
    swapped["correlation_id"] = honest["result"]["operation_id"]
    swapped["result"]["operation_id"] = honest["correlation_id"]
    swapped["error"] = None

    supplied = _identifiers(request)
    assert masked(swapped, supplied) != masked(honest, supplied), (
        "the mask absorbed a permutation: an operation identifier was returned "
        "as a correlation identifier and the rendering did not change"
    )


def test_the_answer_comparison_would_have_seen_a_difference(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    """Guard `assert_same_answer`: one that compared nothing would always pass.

    A result and a denial for the same capability must be reported as different.
    Without this, an assertion that masked too much would report agreement
    between an answer and a refusal.
    """
    scene, _record = staged
    allowed = document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {})
    denied = document(
        Capability.CAPABILITIES_GET,
        scene.principal.principal_id,
        {},
        purpose=a_forbidden_purpose(Capability.CAPABILITIES_GET),
    )
    permitted = answers_for(scene, Capability.CAPABILITIES_GET.value, allowed)
    refused = answers_for(scene, Capability.CAPABILITIES_GET.value, denied)
    mixed = {"allowed": permitted["http"], "denied": refused["mcp"]}
    with pytest.raises(AssertionError):
        assert_same_answer(mixed, allowed, "a control")


#: Requests no transport should be able to answer, and the code each is. The
#: five `P05-SPEC-AC-002` refusals have their own file; these are the ones a
#: *transport* is most able to get wrong, because each is a shape rather than a
#: policy.
REFUSALS: tuple[tuple[str, str, ErrorCode], ...] = (
    ("an unknown capability", "sources.destroy", ErrorCode.INVALID_REQUEST),
    ("no envelope at all", Capability.CAPABILITIES_GET.value, ErrorCode.INVALID_REQUEST),
    ("an unknown payload field", Capability.SOURCES_LIST.value, ErrorCode.INVALID_REQUEST),
    ("an unknown envelope field", Capability.SOURCES_LIST.value, ErrorCode.INVALID_REQUEST),
    ("a malformed identifier", Capability.SOURCES_LIST.value, ErrorCode.INVALID_REQUEST),
    ("two subjects at once", Capability.SOURCES_STATUS.value, ErrorCode.INVALID_REQUEST),
    (
        "a representation that is not one",
        Capability.SOURCES_FETCH.value,
        ErrorCode.INVALID_REQUEST,
    ),
    ("a page size of zero", Capability.SOURCES_LIST.value, ErrorCode.INVALID_REQUEST),
    (
        "an oversized corrected review value",
        Capability.REVIEW_DECIDE.value,
        ErrorCode.INVALID_REQUEST,
    ),
    ("a scope the principal does not hold", Capability.SOURCES_LIST.value, ErrorCode.DENIED),
)


def refusal_requests(scene: Scene) -> dict[str, dict[str, Any] | None]:
    """The document for each named refusal above."""
    principal_id = scene.principal.principal_id
    source_id = scene.source.source_id
    unknown_envelope = document(Capability.SOURCES_LIST, principal_id, {"source_id": source_id})
    unknown_envelope["not_a_field"] = "x"
    return {
        "an unknown capability": document(Capability.SOURCES_LIST, principal_id, {}),
        "no envelope at all": {},
        "an unknown payload field": document(
            Capability.SOURCES_LIST, principal_id, {"source_id": source_id, "nope": 1}
        ),
        "an unknown envelope field": unknown_envelope,
        "a malformed identifier": document(
            Capability.SOURCES_LIST, principal_id, {"source_id": "not-an-identifier"}
        ),
        "two subjects at once": document(
            Capability.SOURCES_STATUS,
            principal_id,
            {"source_id": source_id, "enrollment_id": scene.enrollment.enrollment_id},
        ),
        "a representation that is not one": document(
            Capability.SOURCES_FETCH,
            principal_id,
            {
                "source_id": source_id,
                "source_object_id": scene.markdown.source_object_id,
                "representation": "raw_everything",
            },
        ),
        "a page size of zero": document(
            Capability.SOURCES_LIST, principal_id, {"source_id": source_id, "page_size": 0}
        ),
        "an oversized corrected review value": document(
            Capability.REVIEW_DECIDE,
            principal_id,
            {
                "review_case_id": staged_review_case(scene).review_case_id,
                "expected_review_version": 0,
                "disposition": "correct_and_accept",
                "corrected_value": CORRECTED_VALUE_MARKER + "x" * MAX_NORMALIZED_VALUE_CHARACTERS,
            },
        ),
        "a scope the principal does not hold": document(
            Capability.SOURCES_LIST, principal_id, {"source_id": issue_identifier(IdKind.SOURCE)}
        ),
    }


@pytest.mark.parametrize(("name", "capability", "code"), REFUSALS, ids=lambda value: str(value))
def test_every_refusal_is_the_same_refusal_over_all_three_transports(
    name: str, capability: str, code: ErrorCode, staged: tuple[Scene, KnowledgeRecord]
) -> None:
    """`SPEC-AC-001`'s errors half. A refusal is an answer and must not differ either."""
    scene, _record = staged
    request = refusal_requests(scene)[name]
    answers = answers_for(scene, capability, request)
    assert all(answer.failed for answer in answers.values()), answers
    for transport, answer in answers.items():
        error = answer.document.get("error") or answer.document
        assert error["code"] == code.value, f"{transport} answered {error['code']} for {name}"
        if name == "an oversized corrected review value":
            assert CORRECTED_VALUE_MARKER not in answer.rendered
            assert CORRECTED_VALUE_MARKER not in json.dumps(answer.document)
    assert_same_answer(answers, request, name)


def test_largest_corrected_review_value_is_accepted_with_transport_parity(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    scene, _record = staged
    case = staged_review_case(scene)
    request = document(
        Capability.REVIEW_DECIDE,
        scene.principal.principal_id,
        {
            "review_case_id": case.review_case_id,
            "expected_review_version": 0,
            "disposition": "correct_and_accept",
            "corrected_value": "x" * MAX_NORMALIZED_VALUE_CHARACTERS,
        },
    )
    answers = answers_for(scene, Capability.REVIEW_DECIDE.value, request)
    assert all(not answer.failed for answer in answers.values()), answers
    assert_same_answer(answers, request, "largest corrected review value")


# ---- the one request ceiling -------------------------------------------------


def test_the_request_ceiling_admits_the_largest_request_the_contract_allows() -> None:
    """The derivation, checked against real values rather than trusted.

    Written by WP-4B2a against `adapters/http/app.py` and moved here with the
    constant, unchanged: `MAX_REQUEST_BYTES` restates a bound that is private to
    `domain.common.identifiers`, and a restated constant is a claim. This builds
    an enrollment at the domain's own ceiling — the largest request the contract
    can express — and requires it to fit.

    It belongs beside the parity matrix now because the number is no longer any
    one transport's: it is derived from the contract and all three enforce it.
    """
    longest = make_identifier(IdKind.SOURCE_OBJECT, "a" * 64)
    request = {
        "request_id": "r" * 128,
        "purpose": Purpose.BOUNDED_ENROLLMENT.value,
        "principal_id": issue_identifier(IdKind.PRINCIPAL),
        "requested_at": "2026-08-02T12:00:00Z",
        "payload": {
            "source_id": issue_identifier(IdKind.SOURCE),
            "idempotency_key": "k" * 128,
            "media_types": [f"application/{'x' * 100}" for _ in range(32)],
            "object_ids": [longest for _ in range(MAX_ENROLLMENT_ITEMS)],
        },
    }
    encoded = len(json.dumps(request).encode())
    assert encoded <= MAX_REQUEST_BYTES, (
        f"the largest request the contract allows is {encoded} bytes and the "
        f"transports admit {MAX_REQUEST_BYTES}"
    )
    # And not wastefully larger: a ceiling far above the worst case would bound
    # nothing in practice.
    assert 2 * encoded > MAX_REQUEST_BYTES


def test_the_ceiling_belongs_to_the_normalisation_and_not_to_a_transport() -> None:
    """One number, read from one module, by all three.

    The structural half of the move. A transport that reintroduced a ceiling of
    its own — a literal, or an import from a sibling transport — would still
    pass the derivation above while the three drifted apart, which is exactly
    what `SPEC-AC-001` is about. So the rule is where the name comes from: only
    `adapters/normalization.py` may define it, and every transport that bounds a
    request must import it from there.

    It also removes a structural falsehood. While the constant lived in
    `adapters/http/app.py`, `adapters/mcp` and `adapters/cli` imported it from
    there, which said that deleting the HTTP transport would break the other
    two. It would not have.
    """
    defining = [
        path
        for path in sorted(ADAPTERS.rglob("*.py"))
        if re.search(r"^MAX_REQUEST_BYTES\s*[:=]", path.read_text(encoding="utf-8"), re.M)
    ]
    assert defining == [ADAPTERS / "normalization.py"], (
        f"MAX_REQUEST_BYTES is defined in {[p.name for p in defining]}; the bound is "
        "derived from the contract and has one home"
    )
    bounding = [
        path
        for path in _transport_modules()
        if "MAX_REQUEST_BYTES" in path.read_text(encoding="utf-8")
    ]
    assert len(bounding) == 4, f"only {[p.name for p in bounding]} bound a request"
    for path in bounding:
        source = path.read_text(encoding="utf-8")
        assert "from my_pa.adapters.normalization import" in source, path.name
        assert "adapters.http" not in source, (
            f"{path.relative_to(PACKAGE)} takes a bound from another transport"
        )


def test_no_transport_reaches_into_another_transport() -> None:
    """The general form of the same rule, so the next shared value cannot repeat it.

    `adapters/http`, `adapters/mcp`, and `adapters/cli` are siblings. Anything
    two of them need is either the application's or `normalization.py`'s; one
    importing another is a dependency that says the wrong thing about what can
    be removed.
    """
    for path in _transport_modules():
        subtree = path.relative_to(ADAPTERS).parts[0]
        for other in TRANSPORT_NAMES - {subtree}:
            assert f"my_pa.adapters.{other}" not in path.read_text(encoding="utf-8"), (
                f"{path.relative_to(PACKAGE)} imports the {other} transport"
            )


def test_the_cli_offers_every_option_the_harness_sends() -> None:
    """The parity harness sends every envelope field the CLI accepts.

    Without this, a field the CLI grew would be untested by every comparison in
    this file while all of them stayed green — the request would simply never
    carry it.
    """
    parser = cli_module.build_parser()
    declared = {
        action.option_strings[0]
        for action in parser._actions
        if action.option_strings and action.option_strings[0] not in {"-h", "--help"}
    }
    covered = set(CLI_OPTIONS.values()) | set(CLI_SCOPE_OPTIONS.values()) | {"--payload"}
    assert declared == covered, f"the harness and the CLI disagree on {sorted(declared ^ covered)}"


def test_the_cli_accepts_every_envelope_field_the_contract_declares() -> None:
    """There is no request HTTP can express and the CLI cannot.

    `capability` is the positional argument, which is the same position an HTTP
    path segment and an MCP tool name occupy. Everything else is an option.
    """
    supplied = set(CLI_OPTIONS) | {"scope"}
    assert supplied == set(RequestMetadata.model_fields) - {"capability"}
    scope = RequestMetadata.model_fields["scope"].annotation
    assert scope is not None
    assert set(CLI_SCOPE_OPTIONS) == set(scope.model_fields)


def test_the_world_is_copied_per_transport(staged: tuple[Scene, KnowledgeRecord]) -> None:
    """Guard `answers_for`: a shared world would make the second caller a retry.

    Stated as the thing that would go wrong rather than as an implementation
    detail — with one world, `sources.enroll` answers `created: true` once and
    `created: false` twice, which is the application being right and the
    comparison being about ordering.
    """
    scene, record = staged
    before = len(scene.world.enrollments)
    request = document(
        Capability.SOURCES_ENROLL,
        scene.principal.principal_id,
        payloads_for(scene, record)[Capability.SOURCES_ENROLL],
    )
    answers = answers_for(scene, Capability.SOURCES_ENROLL.value, request)
    assert len(scene.world.enrollments) == before, "a transport wrote into the shared world"
    for name, answer in answers.items():
        assert answer.document["result"]["created"] is True, f"{name} saw another's enrollment"
        assert answer.document["result"]["operation_id"], f"{name} queued nothing"


def test_every_transport_answers_a_world_that_is_not_empty(
    staged: tuple[Scene, KnowledgeRecord],
) -> None:
    """Guard the matrix: sixty-five capabilities answered from an empty world prove little."""
    scene, record = staged
    assert scene.world.enrollments and scene.world.records
    assert set(payloads_for(scene, record)) == set(Capability)
    assert scene.world.sources and scene.world.objects
