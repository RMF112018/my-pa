"""Seed two open, Principal-scoped review cases for the Review browser suite.

The disposable e2e database has no proposals after migrate-to-head. Capture through
the UI does not synchronously open Review cases, so the Review decision journey
needs rows written by the production writers (admit, span, proposal, open case)
rather than invented frontend fixtures.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text

from my_pa.bootstrap.gateway import local_principal
from my_pa.contracts.ports import CaptureAdmissionRequest
from my_pa.domain.capture.pipeline import PipelineStage, ProcessingState
from my_pa.domain.capture.proposal import (
    Proposal,
    ProposalMethod,
    ProposalState,
    ProposalType,
    RiskClass,
)
from my_pa.domain.capture.span import SourceSpan, SpanRole
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy, digest_of
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.capture import admit_capture
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.proposals import (
    record_proposal,
    record_span,
    record_stage_result,
)
from my_pa.infrastructure.persistence.review import open_review_case

TEXT = "Pour the north slab on Tuesday and confirm the mix design."
COMMITMENT_START = 0
COMMITMENT_END = 22
WHEN = datetime.now(UTC) - timedelta(hours=1)


def _version_of(connection: object, capture_id: str) -> str:
    return str(
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT version_id FROM knowledge.capture_versions WHERE capture_id = :c"),
            {"c": capture_id},
        ).scalar_one()
    )


def _operation_of(connection: object, version_id: str) -> str:
    return str(
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT operation_id FROM knowledge.capture_jobs WHERE version_id = :v"),
            {"v": version_id},
        ).scalar_one()
    )


def _admit(connection: object, principal_id: str, key: str) -> str:
    admission = admit_capture(
        connection,  # type: ignore[arg-type]
        CaptureAdmissionRequest(
            capture_id=None,
            content=CaptureContent(TEXT),
            idempotency_key=key,
            request_id=f"req-{key}",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            principal_id=principal_id,
            audit_id=issue_identifier(IdKind.AUDIT),
            classification=Classification.PRIVATE_LOCAL,
            processing_policy=ProcessingPolicy.LOCAL_ONLY,
            server_received_at=WHEN,
            accepted_at=WHEN,
        ),
        context=capture_context(principal_id),
    )
    return admission.receipt.capture_id


def _complete_derivation(connection: object, version_id: str, *, key: str) -> None:
    completed_at = connection.execute(text("SELECT now()")).scalar_one()  # type: ignore[attr-defined]
    record_stage_result(
        connection,  # type: ignore[arg-type]
        version_id=version_id,
        operation_id=_operation_of(connection, version_id),
        stage=PipelineStage.PERSIST_PROPOSALS,
        pipeline_version="p1",
        stage_config_sha256=digest_of(f"config-{key}"),
        idempotency_key=digest_of(f"stage-{key}"),
        processing_state=ProcessingState.COMPLETE,
        completed_at=completed_at,
    )


def _derive_commitment(connection: object, version_id: str, *, value: str) -> str:
    span = SourceSpan.over(
        TEXT,
        version_id=version_id,
        start_offset=COMMITMENT_START,
        end_offset=COMMITMENT_END,
        span_role=SpanRole.DIRECT,
    )
    span_id = record_span(connection, span)  # type: ignore[arg-type]
    proposal = Proposal(
        proposal_id=issue_identifier(IdKind.PROPOSAL),
        version_id=version_id,
        proposal_type=ProposalType.COMMITMENT,
        state=ProposalState.PROPOSED,
        risk_class=RiskClass.HIGH,
        method=ProposalMethod.DETERMINISTIC_RULE,
        method_version="m1",
        schema_version="s1",
        normalized_value=value,
    )
    return record_proposal(connection, proposal, [span_id])  # type: ignore[arg-type]


def main() -> None:
    database_url = os.environ["MY_PA_DATABASE_URL"]
    principal_id = local_principal().principal_id
    with create_engine(database_url).begin() as connection:
        opened: list[str] = []
        for index, value in enumerate(("pour the north slab", "confirm the mix design"), start=1):
            key = f"e2e-review-{index}"
            capture_id = _admit(connection, principal_id, key)
            version_id = _version_of(connection, capture_id)
            proposal_id = _derive_commitment(connection, version_id, value=value)
            _complete_derivation(connection, version_id, key=key)
            review_case_id = open_review_case(connection, proposal_id)
            if review_case_id is None:
                raise RuntimeError("the seeded commitment proposal did not open a review case")
            opened.append(review_case_id)
        if len(opened) != 2:
            raise RuntimeError("expected two open review cases for the Review browser suite")


if __name__ == "__main__":
    main()
