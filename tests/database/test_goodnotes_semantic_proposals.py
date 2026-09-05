"""Disposable PostgreSQL proof for GoodNotes semantic proposal receipts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.sql import Executable

from my_pa.application.commands import SubmitGoodNotesProposal
from my_pa.application.goodnotes_semantics import fingerprint_proposal
from my_pa.contracts.ports import GoodNotesProposalAdmission, GoodNotesProposalConflictError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchMethod,
    GoodNotesNotebook,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesSourceSnapshot,
    issue_stable_id,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository
from my_pa.infrastructure.persistence.goodnotes_pull import (
    SqlGoodNotesPullRepository,
    _corrected_result_sha256,
)
from my_pa.infrastructure.persistence.goodnotes_semantics import SqlGoodNotesSemanticRepository

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_semantic_proposals_test"
WHEN = datetime(2026, 8, 16, 19, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST = hashlib.sha256(b"synthetic-goodnotes-page").hexdigest()
FINGERPRINT = "c" * 64


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _notebook(principal_id: str, token: str) -> GoodNotesNotebook:
    return GoodNotesNotebook(
        notebook_id=issue_stable_id("gnnb", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=WHEN,
        label=token,
    )


def _run(principal_id: str, token: str) -> GoodNotesIngestionRun:
    request_id = f"req-{principal_id[-4:]}-{token}"
    return GoodNotesIngestionRun(
        run_id=issue_stable_id("gnrun", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id=request_id,
        idempotency_key=request_id,
        request_fingerprint=FINGERPRINT,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.RUNNING,
    )


def _plant(
    repository: PostgresGoodNotesRepository, principal_id: str, token: str
) -> tuple[str, str]:
    notebook = repository.store_notebook(_notebook(principal_id, token))
    logical = repository.store_logical_page(
        GoodNotesLogicalPage(
            logical_page_id=issue_stable_id("gnlp", principal_id, token),
            principal_id=principal_id,
            notebook_id=notebook.notebook_id,
            created_at=WHEN,
            last_seen_at=WHEN,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
        )
    )
    run = repository.create_run(_run(principal_id, token))
    snapshot = repository.store_snapshot(
        GoodNotesSourceSnapshot(
            snapshot_id=issue_stable_id("gnsnap", principal_id, token),
            principal_id=principal_id,
            notebook_id=notebook.notebook_id,
            source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
            observed_path="Inbox/semantic.pdf",
            raw_sha256=hashlib.sha256(token.encode()).hexdigest(),
            size_bytes=32,
            page_count=1,
            observed_at=WHEN,
            settled_at=WHEN,
            run_id=run.run_id,
        )
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", principal_id, token),
        principal_id=principal_id,
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_number=1,
    )
    version = repository.store_page_version_render(
        page=page,
        version=GoodNotesPageVersion(
            page_version_id=issue_stable_id("gnver", principal_id, token),
            page_id=page.page_id,
            source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
            content_sha256=DIGEST,
            observed_at=WHEN,
            logical_page_id=logical.logical_page_id,
            renderer_name="synthetic",
            renderer_version="1",
            render_profile_version="v1",
        ),
    )
    repository.store_page_position(
        GoodNotesPagePosition(
            principal_id=principal_id,
            snapshot_id=snapshot.snapshot_id,
            page_number=1,
            logical_page_id=logical.logical_page_id,
            created_at=WHEN,
            match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
            page_version_id=version.page_version_id,
        )
    )
    return run.run_id, version.page_version_id


def _command(
    run_id: str, page_version_id: str, *, key: str, transcription: str
) -> SubmitGoodNotesProposal:
    return SubmitGoodNotesProposal(
        run_id=run_id,
        page_version_id=page_version_id,
        content_sha256=DIGEST,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        idempotency_key=key,
        segments=(
            {
                "kind": "NOTE_UNIT",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
                "transcription": transcription,
                "primary_class": "MEETING",
            },
        ),
    )


def _submit(
    semantics: SqlGoodNotesSemanticRepository,
    command: SubmitGoodNotesProposal,
    *,
    principal_id: str,
) -> GoodNotesProposalAdmission:
    fingerprint, payload_digest, body = fingerprint_proposal(command)
    return semantics.submit_proposal(
        principal_id=principal_id,
        run_id=command.run_id,
        page_version_id=command.page_version_id,
        content_sha256=command.content_sha256,
        schema_version=command.schema_version,
        analyzer_name=command.analyzer_name,
        analyzer_version=command.analyzer_version,
        idempotency_key=command.idempotency_key,
        request_fingerprint=fingerprint,
        payload_sha256=payload_digest,
        payload=body,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id=command.idempotency_key,
        audit_id=issue_identifier(IdKind.AUDIT),
        created_at=WHEN,
    )


def _changes(connection: object, principal_id: str) -> int:
    return int(
        connection.execute(  # type: ignore[union-attr]
            text(
                "SELECT count(*) FROM knowledge.goodnotes_run_note_changes "
                "WHERE principal_id = :principal"
            ),
            {"principal": principal_id},
        ).scalar_one()
    )


def test_cross_principal_isolation_exact_replay_and_no_run_note_changes(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_a, page_a = _plant(lineage, A, "semantic-a")
        run_b, page_b = _plant(lineage, B, "semantic-b")
        work_a = semantics.page_work(A, run_a, page_a)
        work_b = semantics.page_work(B, run_b, page_b)
        assert work_a is not None and work_b is not None
        assert work_a.content_sha256 == DIGEST
        assert semantics.page_work(B, run_a, page_a) is None
        assert semantics.page_work(A, run_b, page_b) is None
        assert semantics.page_work(A, run_a, page_b) is None

        before = _changes(connection, A)
        first = _submit(
            semantics,
            _command(run_a, page_a, key="same-key", transcription="one"),
            principal_id=A,
        )
        replay = _submit(
            semantics,
            _command(run_a, page_a, key="same-key", transcription="one"),
            principal_id=A,
        )
        assert first.created is True
        assert replay.created is False
        assert replay.proposal.proposal_id == first.proposal.proposal_id
        assert replay.proposal.replayed is True
        assert _changes(connection, A) == before
        other = _submit(
            semantics,
            _command(run_b, page_b, key="same-key", transcription="one"),
            principal_id=B,
        )
        assert other.created is True
        assert other.proposal.proposal_id != first.proposal.proposal_id
        with pytest.raises(GoodNotesProposalConflictError):
            _submit(
                semantics,
                _command(run_a, page_a, key="same-key", transcription="different"),
                principal_id=A,
            )
        assert _changes(connection, A) == before
        assert _changes(connection, B) == 0


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def test_date_payload_digest_parity_and_historical_empty_replay(engine: Engine) -> None:
    with engine.begin() as connection:
        run_id, page_id = _plant(PostgresGoodNotesRepository(connection), A, "date-parity")
        semantics = SqlGoodNotesSemanticRepository(connection)
        plain = _command(run_id, page_id, key="historical-date-absent", transcription="synthetic")
        empty = replace(
            plain, date_evidence={"page_candidates": [], "event_dates": [], "body_dates": []}
        )
        assert fingerprint_proposal(plain) == fingerprint_proposal(empty)
        original = _submit(semantics, plain, principal_id=A)
        replay = _submit(semantics, empty, principal_id=A)
        assert original.created and not replay.created
        assert replay.proposal.proposal_id == original.proposal.proposal_id
        date_payload: dict[str, object] = {
            "body_dates": [
                {
                    "scope": "BODY",
                    "value": "2026-09-05",
                    "literal": "September 5",
                    "evidence_refs": ["body"],
                    "confidence": 1,
                }
            ],
        }
        dated = replace(plain, idempotency_key="nonempty-date", date_evidence=date_payload)
        fingerprint, digest, body = fingerprint_proposal(dated)
        assert fingerprint != fingerprint_proposal(plain)[0]
        assert digest == _corrected_result_sha256(body)
        assert digest != _corrected_result_sha256(fingerprint_proposal(plain)[2])
        persisted = _submit(semantics, dated, principal_id=A)
        material = SqlGoodNotesPullRepository(connection).semantic_proposal_material(
            A, persisted.proposal.proposal_id
        )
        assert material is not None and material.payload == body
        assert material.payload["date_evidence"] == dated.date_evidence
        with pytest.raises(GoodNotesProposalConflictError):
            _submit(
                semantics, replace(dated, idempotency_key=plain.idempotency_key), principal_id=A
            )
