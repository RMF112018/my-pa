"""Disposable PostgreSQL proof for remote GoodNotes proposal idempotency stamping."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.commands import DecideReviewCase, SubmitGoodNotesProposal
from my_pa.application.goodnotes_lineage import ObservedNotebookFile
from my_pa.application.goodnotes_orchestrator import (
    DurableNoteRequest,
    GoodNotesDurableNoteOrchestrator,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.capture.review import CorrectionPatch, Disposition
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.goodnotes.liveness import (
    GoodNotesSourceLiveness,
    GoodNotesSourceLivenessReceipt,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIngestionStatus,
    GoodNotesPipelineStage,
    GoodNotesStageStatus,
    issue_stable_id,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
from my_pa.infrastructure.goodnotes.render import production_page_renderer
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.goodnotes_durable_note import PostgresDurableNoteStore
from my_pa.infrastructure.persistence.goodnotes_pull import SqlGoodNotesPullRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.unit.vector_pdf import Rect, vector_pdf

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
WHEN = datetime(2026, 8, 17, 23, 30, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
SOURCE_ROOT = "synthetic-connected-validation-root"
LIMITS = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)
COVER = (Rect(72, 400, 220, 220, 0.15),)
SEMANTIC = "semantic-proposals-without-canonical-note-writes"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _object_id(token: str) -> str:
    return "obj_" + hashlib.sha256(f"object:{token}".encode()).hexdigest()[:24]


def _version_id(token: str) -> str:
    return "ver_" + hashlib.sha256(f"version:{token}".encode()).hexdigest()[:24]


def _source_id(token: str) -> str:
    return "src_" + hashlib.sha256(f"source:{token}".encode()).hexdigest()[:24]


def _request(pdf: bytes, request_id: str) -> DurableNoteRequest:
    return DurableNoteRequest(
        principal_id=A,
        request_id=request_id,
        source_root_id=SOURCE_ROOT,
        source_object_id=_object_id(request_id),
        source_id=_source_id(request_id),
        source_version_id=_version_id(request_id),
        observation=ObservedNotebookFile(
            relative_path=f"Validation/{request_id}.pdf",
            size_bytes=len(pdf),
            sha256=_sha(pdf),
            mtime_ns=1,
            page_count=len(split_admitted_pdf(pdf)),
        ),
        liveness=GoodNotesSourceLivenessReceipt(
            source_root_id=SOURCE_ROOT,
            relative_path=f"Validation/{request_id}.pdf",
            state=GoodNotesSourceLiveness.AVAILABLE,
            checked_at=WHEN,
            maximum_staleness_seconds=300,
            last_seen_at=WHEN,
            current_sha256=_sha(pdf),
            prior_sha256=None,
        ),
        pdf_bytes=pdf,
        notebook_id=issue_stable_id("gnnb", A, request_id),
        label="Synthetic Remote Proposal Test",
        observed_at=WHEN,
    )


def _connected_v2_payload(
    run_id: str, page_version_id: str, content_sha256: str
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "page_version_id": page_version_id,
        "content_sha256": content_sha256,
        "schema_version": "note-unit.v2",
        "analyzer_name": "chatllm-synthetic-validator",
        "analyzer_version": "1.0.0",
        "segments": [
            {
                "kind": "NOTE_UNIT",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.5, "height": 0.2},
                "transcription": None,
                "transcription_status": "UNREADABLE",
                "confidence": {"transcription": 0.0, "classification": 0.6},
                "candidate_tags": ["GENERAL"],
                "ranked_candidates": [],
            }
        ],
        "confidence": {
            "transcription": 0.0,
            "segmentation": 0.85,
            "classification": 0.6,
        },
        "candidate_tags": ["GENERAL"],
        "ranked_candidates": [],
    }


@pytest.fixture
def runtime(engine: Engine) -> Iterator[_Runtime]:
    built = _Runtime(engine)
    try:
        yield built
    finally:
        built.close()


class _Runtime:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.audit_engine = create_database_engine(engine.url.render_as_string(hide_password=False))
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(engine, audit=audit)

        self.service = ApplicationService(unit_of_work=unit_of_work, limits=LIMITS)
        self.principal = Principal(principal_id=A, kind=PrincipalKind.OPERATOR, authenticated=True)

    def close(self) -> None:
        self.audit_engine.dispose()

    def remote_propose(self, payload: dict[str, object]) -> dict[str, object]:
        composed = compose_remote_arguments(
            capability_name=Capability.GOODNOTES_PROPOSE.value,
            arguments={"payload": payload},
            principal=self.principal,
            grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
            clock=lambda: WHEN,
            issue_id=lambda _kind: issue_identifier(IdKind.CORRELATION),
        )
        metadata, command = normalize(Capability.GOODNOTES_PROPOSE.value, composed)
        grants = frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)})
        envelope = self.service.invoke(
            metadata,
            command,
            principal=self.principal,
            transport=CaptureTransport.REMOTE_CLIENT,
            capability_grants=grants,
        )
        body = envelope.to_canonical_dict()
        if body.get("error") is not None:
            raise AssertionError(body["error"])
        result = body["result"]
        assert isinstance(result, dict)
        return result


def _stage_waiting(engine: Engine, request_id: str) -> tuple[str, str, str]:
    pdf = vector_pdf((COVER,))
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        result = GoodNotesDurableNoteOrchestrator(rollout_stage=SEMANTIC).run(
            _request(pdf, request_id),
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
        )
        assert result.waiting_for_proposal is True
        assert result.run.status is GoodNotesIngestionStatus.RUNNING
        stages = {
            row.stage
            for row in store.stages(A, result.run.run_id)
            if row.status is GoodNotesStageStatus.SUCCEEDED
        }
        assert GoodNotesPipelineStage.WAITING_PROPOSAL in stages
        snapshots = store.snapshots_for_run(A, result.run.run_id)
        positions = store.page_positions(A, snapshots[0].snapshot_id)
        version_id = positions[0].page_version_id
        assert version_id is not None
        version = store.page_version(A, version_id)
        assert version is not None
        return result.run.run_id, version_id, version.content_sha256


def _count(connection: object, sql: str, **params: object) -> int:
    return int(connection.execute(text(sql), params).scalar_one())  # type: ignore[union-attr]


def test_remote_goodnotes_proposal_admits_replays_and_refuses_conflicts(
    engine: Engine, runtime: _Runtime
) -> None:
    run_id, page_version_id, content_sha256 = _stage_waiting(engine, "remote-propose-idk-001")
    payload = _connected_v2_payload(run_id, page_version_id, content_sha256)

    with engine.connect() as connection:
        before_proposals = _count(
            connection,
            "SELECT count(*) FROM knowledge.goodnotes_semantic_proposals WHERE principal_id = :p",
            p=A,
        )
        before_changes = _count(
            connection,
            "SELECT count(*) FROM knowledge.goodnotes_run_note_changes WHERE principal_id = :p",
            p=A,
        )
        before_occurrences = _count(
            connection,
            "SELECT count(*) FROM knowledge.goodnotes_note_occurrences WHERE principal_id = :p",
            p=A,
        )
        before_attempts = _count(
            connection,
            "SELECT count(*) FROM knowledge.goodnotes_delivery_attempts WHERE principal_id = :p",
            p=A,
        )

    first = runtime.remote_propose(payload)
    assert first["replayed"] is False
    assert str(first["proposal_id"]).startswith("gnprp_")

    replay = runtime.remote_propose(payload)
    assert replay["replayed"] is True
    assert replay["proposal_id"] == first["proposal_id"]

    with engine.connect() as connection:
        proposals_sql = (
            "SELECT count(*) FROM knowledge.goodnotes_semantic_proposals WHERE principal_id = :p"
        )
        assert _count(connection, proposals_sql, p=A) == before_proposals + 1
        assert (
            _count(
                connection,
                "SELECT count(*) FROM knowledge.goodnotes_run_note_changes WHERE principal_id = :p",
                p=A,
            )
            == before_changes
        )
        assert (
            _count(
                connection,
                "SELECT count(*) FROM knowledge.goodnotes_note_occurrences WHERE principal_id = :p",
                p=A,
            )
            == before_occurrences
        )
        assert (
            _count(
                connection,
                (
                    "SELECT count(*) FROM knowledge.goodnotes_delivery_attempts"
                    " WHERE principal_id = :p"
                ),
                p=A,
            )
            == before_attempts
        )

    composed = compose_remote_arguments(
        capability_name=Capability.GOODNOTES_PROPOSE.value,
        arguments={"payload": payload},
        principal=runtime.principal,
        grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
        clock=lambda: WHEN,
        issue_id=lambda _kind: issue_identifier(IdKind.CORRELATION),
    )
    _metadata, command = normalize(Capability.GOODNOTES_PROPOSE.value, composed)
    assert isinstance(command, SubmitGoodNotesProposal)
    tampered = SubmitGoodNotesProposal(
        run_id=command.run_id,
        page_version_id=command.page_version_id,
        content_sha256=command.content_sha256,
        schema_version=command.schema_version,
        analyzer_name=command.analyzer_name,
        analyzer_version=command.analyzer_version,
        idempotency_key=command.idempotency_key,
        segments=(
            {
                "kind": "NOTE_UNIT",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.5, "height": 0.2},
                "transcription": "changed",
                "transcription_status": "CLEAR",
                "primary_class": "MEETING",
            },
        ),
    )
    envelope = runtime.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=Capability.GOODNOTES_PROPOSE,
            purpose=Purpose.GOODNOTES_PROPOSAL,
            principal_id=A,
            requested_at=WHEN,
        ),
        tampered,
        principal=runtime.principal,
        transport=CaptureTransport.REMOTE_CLIENT,
        capability_grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
    )
    conflict = envelope.to_canonical_dict()
    assert conflict["error"] is not None
    assert conflict["error"]["code"] == "conflict"


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def _date_evidence() -> dict[str, object]:
    def evidence(scope: str, value: str, reference: str) -> dict[str, object]:
        return {"scope": scope, "value": value, "literal": value, "evidence_refs": [reference]}

    return {
        "page_candidates": [
            evidence("PAGE", "2026-09-05", "heading-left"),
            evidence("PAGE", "2026-09-05", "heading-right"),
        ],
        "event_dates": [evidence("EVENT", "2026-09-06", "event-line")],
        "body_dates": [evidence("BODY", "2026-09-07", "body-line")],
    }


@pytest.mark.parametrize("correction", ["omit", "empty", "replace"])
def test_public_date_proposal_review_and_promotion_preserve_accepted_provenance(
    engine: Engine, runtime: _Runtime, correction: str
) -> None:
    run_id, version_id, digest = _stage_waiting(engine, f"date-review-{correction}")
    dates = _date_evidence()
    payload = {**_connected_v2_payload(run_id, version_id, digest), "date_evidence": dates}
    original = runtime.remote_propose(payload)
    assert runtime.remote_propose(payload)["proposal_id"] == original["proposal_id"]
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        cases = repository.semantic_review_cases(A, limit=10)
        case = next(item for item in cases if item.proposal_id == original["proposal_id"])
        before = repository.semantic_proposal_material(A, case.proposal_id)
        assert before is not None and before.payload["date_evidence"] == dates
        assert (
            repository.semantic_proposal_material("prn_bbbbbbbbbbbbbbbbbbbbbbbb", case.proposal_id)
            is None
        )
    patch: dict[str, object] = {"confidence": {"transcription": 0.0, "segmentation": 0.9}}
    expected = dates
    if correction == "empty":
        patch["date_evidence"] = {"page_candidates": [], "event_dates": [], "body_dates": []}
        expected = {}
    elif correction == "replace":
        expected = {
            **dates,
            "page_candidates": [
                {
                    "scope": "PAGE",
                    "value": "2026-09-08",
                    "literal": "September 8",
                    "evidence_refs": ["revised-heading"],
                },
                {
                    "scope": "PAGE",
                    "value": "2026-09-09",
                    "literal": "September 9",
                    "evidence_refs": ["other-heading"],
                },
            ],
        }
        patch["date_evidence"] = expected
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(
            engine, audit=SqlAlchemyAuditSink(runtime.audit_engine), goodnotes_pull_enabled=True
        ),
        limits=LIMITS,
        clock=lambda: WHEN,
        goodnotes_pull_enabled=True,
        goodnotes_pull_cursor_signing_key=b"synthetic-date-test-key" * 2,
    )
    command = DecideReviewCase(
        review_case_id=case.review_case_id,
        expected_review_version=case.review_version,
        disposition=Disposition.CORRECT_AND_ACCEPT,
        correction_patch=CorrectionPatch.of(patch),
    )
    metadata = RequestMetadata(
        request_id=issue_identifier(IdKind.CORRELATION),
        capability=Capability.REVIEW_DECIDE,
        purpose=Purpose.REVIEW_DISPOSITION,
        principal_id=A,
        requested_at=WHEN,
    )
    reviewed = service.invoke(metadata, command, principal=runtime.principal).to_canonical_dict()
    assert reviewed.get("error") is None, reviewed.get("error")
    replay = service.invoke(metadata, command, principal=runtime.principal).to_canonical_dict()
    assert replay.get("error") is None, replay.get("error")
    assert replay["result"]["decision_id"] == reviewed["result"]["decision_id"]
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        material = repository.accepted_semantic_material(A, run_id)
        assert material is not None and len(material) == 1
        assert material[0].payload.get("date_evidence", {}) == expected
        assert repository.semantic_proposal_material(A, case.proposal_id) == before
        repository.record_semantic_promotion(A, run_id)
        assert repository.accepted_semantic_material(A, run_id, require_promoted=True) == material
        assert (
            repository.accepted_semantic_material(
                "prn_bbbbbbbbbbbbbbbbbbbbbbbb", run_id, require_promoted=True
            )
            is None
        )


def test_public_date_change_conflicts_with_existing_request_key(
    engine: Engine, runtime: _Runtime
) -> None:
    run_id, version_id, digest = _stage_waiting(engine, "date-conflicting-key")
    payload = {
        **_connected_v2_payload(run_id, version_id, digest),
        "date_evidence": _date_evidence(),
    }
    runtime.remote_propose(payload)
    composed = compose_remote_arguments(
        capability_name=Capability.GOODNOTES_PROPOSE.value,
        arguments={"payload": payload},
        principal=runtime.principal,
        grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
        clock=lambda: WHEN,
        issue_id=lambda _kind: issue_identifier(IdKind.CORRELATION),
    )
    metadata, command = normalize(Capability.GOODNOTES_PROPOSE.value, composed)
    assert isinstance(command, SubmitGoodNotesProposal)
    changed = replace(command, date_evidence={})
    result = runtime.service.invoke(
        metadata,
        changed,
        principal=runtime.principal,
        transport=CaptureTransport.REMOTE_CLIENT,
        capability_grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
    ).to_canonical_dict()
    assert result["error"] is not None and result["error"]["code"] == "conflict"
