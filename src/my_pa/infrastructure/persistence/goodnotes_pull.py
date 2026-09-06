"""Durable Principal/client-bound GoodNotes pull and semantic-review ledgers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import ColumnElement, Select

from my_pa.contracts.ports import (
    GoodNotesPullAssignmentRecord as PullAssignment,
)
from my_pa.contracts.ports import (
    GoodNotesPullCompletionAdmissionValue as PullCompletionAdmission,
)
from my_pa.contracts.ports import (
    GoodNotesPullCompletionConflictError as PullCompletionConflictError,
)
from my_pa.contracts.ports import (
    GoodNotesPullCompletionMaterial as PullCompletionMaterial,
)
from my_pa.contracts.ports import (
    GoodNotesPullCompletionReceiptRecord as PullCompletionReceipt,
)
from my_pa.contracts.ports import (
    GoodNotesPullRepositoryConflictError as PullRepositoryConflictError,
)
from my_pa.contracts.ports import (
    GoodNotesPullStatusRecord as GoodNotesPullStatus,
)
from my_pa.contracts.ports import (
    GoodNotesPullWorkStateRecord as PullWorkState,
)
from my_pa.contracts.ports import (
    GoodNotesSemanticPromotionEvidenceRecord as GoodNotesSemanticPromotionEvidence,
)
from my_pa.contracts.ports import GoodNotesSemanticProposalMaterial, ReviewDecisionRequest
from my_pa.contracts.ports import (
    GoodNotesSemanticReviewConflictError as SemanticReviewConflictError,
)
from my_pa.contracts.ports import (
    GoodNotesSemanticReviewDecisionRecord as SemanticReviewDecision,
)
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    Disposition,
    ReviewConflictError,
    ReviewDecision,
    ReviewNotFoundError,
    ReviewUnsupportedError,
)
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.dates import canonical_date_evidence
from my_pa.domain.goodnotes.models import GoodNotesPageWork, GoodNotesSemanticReviewCase
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    goodnotes_ingestion_run_stages,
    goodnotes_ingestion_runs,
    goodnotes_logical_pages,
    goodnotes_page_positions,
    goodnotes_page_rasters,
    goodnotes_page_versions,
    goodnotes_pull_assignments,
    goodnotes_pull_claims,
    goodnotes_pull_completions,
    goodnotes_pull_sessions,
    goodnotes_semantic_promotion_receipts,
    goodnotes_semantic_proposals,
    goodnotes_semantic_review_decisions,
    goodnotes_source_snapshots,
)

__all__ = ["SqlGoodNotesPullRepository"]


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical_payload(value: object) -> dict[str, object]:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        raise SemanticReviewConflictError from None
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise SemanticReviewConflictError
    return decoded


def _corrected_result_sha256(payload: dict[str, object]) -> str:
    fields = {
        key: payload[key]
        for key in ("segments", "candidate_tags", "ranked_candidates", "confidence")
    }
    dates = canonical_date_evidence(payload.get("date_evidence", {}))
    if dates:
        fields["date_evidence"] = dates
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _semantic_proposal_sha256(
    page_version_id: str,
    schema_version: str,
    analyzer_name: str,
    analyzer_version: str,
    payload: dict[str, object],
) -> str:
    return _digest([page_version_id, schema_version, analyzer_name, analyzer_version, payload])


def _semantic_review_case_id(principal_id: str, proposal_id: str) -> str:
    return f"rvw_{_digest([principal_id, proposal_id])[:24]}"


def _semantic_state(disposition: Disposition | None) -> ProposalState:
    if disposition is None:
        return ProposalState.NEEDS_REVIEW
    return {
        Disposition.ACCEPT: ProposalState.ACCEPTED,
        Disposition.CORRECT_AND_ACCEPT: ProposalState.CORRECTED_ACCEPTED,
        Disposition.REJECT: ProposalState.REJECTED,
        Disposition.DEFER: ProposalState.DEFERRED,
        Disposition.MARK_UNRESOLVED: ProposalState.UNRESOLVED,
        Disposition.REPROCESS: ProposalState.SUPERSEDED,
        Disposition.ESCALATE: ProposalState.NEEDS_REVIEW,
        Disposition.INVALIDATE: ProposalState.INVALIDATED,
    }[disposition]


def _work_key(work: GoodNotesPageWork) -> tuple[str, str, str]:
    return work.run_id, work.page_version_id, work.content_sha256


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


def _assignment_from_row(row: object) -> PullAssignment:
    value = row._mapping  # type: ignore[attr-defined]
    return PullAssignment(
        assignment_id=str(value["assignment_id"]),
        client_id=str(value["client_id"]),
        context_id=str(value["context_id"]),
        attempt=int(value["attempt"]),
        work=GoodNotesPageWork(
            run_id=str(value["run_id"]),
            page_version_id=str(value["page_version_id"]),
            principal_id=str(value["principal_id"]),
            content_sha256=str(value["content_sha256"]),
            logical_page_id=(
                None if value["logical_page_id"] is None else str(value["logical_page_id"])
            ),
            renderer_name=(None if value["renderer_name"] is None else str(value["renderer_name"])),
            renderer_version=(
                None if value["renderer_version"] is None else str(value["renderer_version"])
            ),
            render_profile_version=(
                None
                if value["render_profile_version"] is None
                else str(value["render_profile_version"])
            ),
        ),
    )


class SqlGoodNotesPullRepository:
    """Atomic pull/review operations on one caller-owned PostgreSQL transaction."""

    def __init__(self, connection: Connection, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._connection = connection
        self._clock = clock

    def _lock_run(self, principal_id: str, run_id: str) -> bool:
        return (
            self._connection.execute(
                select(goodnotes_ingestion_runs.c.run_id)
                .where(
                    _mine(goodnotes_ingestion_runs, principal_id),
                    goodnotes_ingestion_runs.c.run_id == run_id,
                )
                .with_for_update()
            ).first()
            is not None
        )

    def _accepted_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[GoodNotesSemanticProposalMaterial, ...], list[dict[str, object]]] | None:
        """Lock the complete immutable page set before consulting Review authority."""
        if not self._lock_run(principal_id, run_id):
            return None
        promoted = (
            self._connection.execute(
                select(goodnotes_semantic_promotion_receipts.c.receipt_id).where(
                    _mine(goodnotes_semantic_promotion_receipts, principal_id),
                    goodnotes_semantic_promotion_receipts.c.run_id == run_id,
                )
            ).first()
            is not None
        )
        ready = self._connection.execute(
            select(goodnotes_ingestion_run_stages.c.status).where(
                _mine(goodnotes_ingestion_run_stages, principal_id),
                goodnotes_ingestion_run_stages.c.run_id == run_id,
                goodnotes_ingestion_run_stages.c.stage == "CONTENT_READY",
            )
        ).scalar_one_or_none()
        if ready != "SUCCEEDED":
            return None
        snapshots = self._connection.execute(
            select(goodnotes_source_snapshots)
            .where(
                _mine(goodnotes_source_snapshots, principal_id),
                goodnotes_source_snapshots.c.run_id == run_id,
            )
            .order_by(goodnotes_source_snapshots.c.snapshot_id)
        ).all()
        if not snapshots:
            return None
        expected: list[dict[str, object]] = []
        for snapshot in snapshots:
            positions = self._connection.execute(
                select(goodnotes_page_positions)
                .where(
                    _mine(goodnotes_page_positions, principal_id),
                    goodnotes_page_positions.c.snapshot_id == snapshot.snapshot_id,
                )
                .order_by(goodnotes_page_positions.c.page_number)
            ).all()
            if [p.page_number for p in positions] != list(range(1, snapshot.page_count + 1)):
                return None
            for position in positions:
                # Lineage distinguishes new ACTIVE pages from AMBIGUOUS pages
                # using logical identity_status: both have UNRESOLVED matching
                # method (goodnotes_lineage.py match_logical_pages). A new page
                # has no prior version. Reject unresolved reuse here and require
                # ACTIVE same-notebook identity plus exact raster proof below.
                if position.page_version_id is None or (
                    position.match_method == "UNRESOLVED"
                    and position.prior_page_version_id is not None
                ):
                    return None
                version = self._connection.execute(
                    select(goodnotes_page_versions).where(
                        _mine(goodnotes_page_versions, principal_id),
                        goodnotes_page_versions.c.page_version_id == position.page_version_id,
                    )
                ).one_or_none()
                raster = self._connection.execute(
                    select(goodnotes_page_rasters).where(
                        _mine(goodnotes_page_rasters, principal_id),
                        goodnotes_page_rasters.c.page_version_id == position.page_version_id,
                        goodnotes_page_rasters.c.run_id == run_id,
                    )
                ).one_or_none()
                logical_status = self._connection.execute(
                    select(goodnotes_logical_pages.c.identity_status).where(
                        _mine(goodnotes_logical_pages, principal_id),
                        goodnotes_logical_pages.c.logical_page_id == position.logical_page_id,
                        goodnotes_logical_pages.c.notebook_id == snapshot.notebook_id,
                    )
                ).scalar_one_or_none()
                if (
                    logical_status is None
                    or (not promoted and logical_status != "ACTIVE")
                    or version is None
                    or raster is None
                    or version.logical_page_id != position.logical_page_id
                    or raster.exact_render_sha256 != version.exact_render_sha256
                    or raster.png_sha256 != hashlib.sha256(bytes(raster.png_bytes)).hexdigest()
                    or raster.renderer_name != version.renderer_name
                    or raster.renderer_version != version.renderer_version
                    or raster.render_profile_version != version.render_profile_version
                ):
                    return None
                expected.append(
                    {
                        "snapshot_id": str(snapshot.snapshot_id),
                        "page_number": int(position.page_number),
                        "logical_page_id": str(position.logical_page_id),
                        "page_version_id": str(position.page_version_id),
                        "content_sha256": str(version.content_sha256),
                        "png_sha256": str(raster.png_sha256),
                    }
                )
        if len(expected) > 10000:
            raise ValueError("GoodNotes promotion page set exceeds its bound")
        proposals = self._connection.execute(
            select(goodnotes_semantic_proposals)
            .where(
                _mine(goodnotes_semantic_proposals, principal_id),
                goodnotes_semantic_proposals.c.run_id == run_id,
            )
            .order_by(goodnotes_semantic_proposals.c.proposal_id)
            .with_for_update()
        ).all()
        if len(proposals) != len(expected):
            return None
        materials: list[GoodNotesSemanticProposalMaterial] = []
        bindings: list[dict[str, object]] = []
        seen: set[str] = set()
        for page in expected:
            matches = [
                p
                for p in proposals
                if p.page_version_id == page["page_version_id"]
                and p.content_sha256 == page["content_sha256"]
            ]
            if len(matches) != 1 or str(matches[0].proposal_id) in seen:
                return None
            proposal = matches[0]
            seen.add(str(proposal.proposal_id))
            payload = _canonical_payload(proposal.payload)
            # payload_sha256 binds the four historical semantic fields plus any
            # nonempty canonical date evidence. The envelope has a separate
            # complete proposal digest.
            # Do not accept multiple digest formats. Review below binds every byte
            # of the original payload, including any envelope metadata.
            if _corrected_result_sha256(payload) != proposal.payload_sha256:
                raise ValueError("GoodNotes original proposal digest mismatch")
            original_digest = _semantic_proposal_sha256(
                str(proposal.page_version_id),
                str(proposal.schema_version),
                str(proposal.analyzer_name),
                str(proposal.analyzer_version),
                payload,
            )
            decision = self._connection.execute(
                select(goodnotes_semantic_review_decisions)
                .where(
                    _mine(goodnotes_semantic_review_decisions, principal_id),
                    goodnotes_semantic_review_decisions.c.run_id == run_id,
                    goodnotes_semantic_review_decisions.c.proposal_id == proposal.proposal_id,
                )
                .order_by(goodnotes_semantic_review_decisions.c.sequence.desc())
                .limit(1)
            ).one_or_none()
            if decision is None or decision.action not in {
                Disposition.ACCEPT.value,
                Disposition.CORRECT_AND_ACCEPT.value,
            }:
                return None
            if decision.proposal_sha256 != original_digest:
                raise ValueError("GoodNotes Review proposal binding mismatch")
            result_digest = str(proposal.payload_sha256)
            if decision.action == Disposition.CORRECT_AND_ACCEPT.value:
                payload = _canonical_payload(decision.corrected_payload)
                result_digest = _corrected_result_sha256(payload)
                if result_digest != decision.corrected_result_sha256:
                    raise ValueError("GoodNotes accepted result digest mismatch")
            materials.append(
                GoodNotesSemanticProposalMaterial(
                    proposal_id=str(proposal.proposal_id),
                    run_id=run_id,
                    page_version_id=str(proposal.page_version_id),
                    content_sha256=str(proposal.content_sha256),
                    schema_version=str(proposal.schema_version),
                    analyzer_name=str(proposal.analyzer_name),
                    analyzer_version=str(proposal.analyzer_version),
                    payload=payload,
                )
            )
            bindings.append(
                {
                    **page,
                    "proposal_id": str(proposal.proposal_id),
                    "proposal_sha256": original_digest,
                    "decision_id": str(decision.decision_id),
                    "sequence": int(decision.sequence),
                    "action": str(decision.action),
                    "result_sha256": result_digest,
                }
            )
        return tuple(materials), bindings

    def accepted_semantic_material(
        self, principal_id: str, run_id: str, *, require_promoted: bool = False
    ) -> tuple[GoodNotesSemanticProposalMaterial, ...] | None:
        accepted = self._accepted_run(principal_id, run_id)
        receipt = self._connection.execute(
            select(goodnotes_semantic_promotion_receipts).where(
                _mine(goodnotes_semantic_promotion_receipts, principal_id),
                goodnotes_semantic_promotion_receipts.c.run_id == run_id,
            )
        ).one_or_none()
        if receipt is not None and (
            accepted is None
            or receipt.binding_sha256 != _digest([principal_id, run_id, accepted[1]])
            or receipt.bindings != accepted[1]
        ):
            raise ValueError("GoodNotes promotion receipt binding mismatch")
        if accepted is None or (require_promoted and receipt is None):
            return None
        return accepted[0]

    def record_semantic_promotion(self, principal_id: str, run_id: str) -> str:
        accepted = self._accepted_run(principal_id, run_id)
        if accepted is None:
            raise ValueError("GoodNotes full run is not eligible for promotion")
        # Check existing immutable authority even on zero-change replays.
        self.accepted_semantic_material(principal_id, run_id)
        binding_digest = _digest([principal_id, run_id, accepted[1]])
        receipt_id = "gnspr_" + binding_digest[:24]
        self._connection.execute(
            pg_insert(goodnotes_semantic_promotion_receipts)
            .values(
                _bound(
                    goodnotes_semantic_promotion_receipts,
                    principal_id,
                    {
                        "run_id": run_id,
                        "receipt_id": receipt_id,
                        "binding_sha256": binding_digest,
                        "bindings": accepted[1],
                        "promoted_at": self._clock(),
                    },
                )
            )
            .on_conflict_do_nothing()
        )
        return receipt_id

    def work_states(self, principal_id: str, client_id: str) -> tuple[PullWorkState, ...]:
        return self._work_states(principal_id, client_id=client_id)

    def _work_states(self, principal_id: str, *, client_id: str) -> tuple[PullWorkState, ...]:
        eligible = (
            select(
                goodnotes_ingestion_runs.c.run_id,
                goodnotes_page_versions.c.page_version_id,
                goodnotes_page_versions.c.principal_id,
                goodnotes_page_versions.c.content_sha256,
                goodnotes_page_versions.c.logical_page_id,
                goodnotes_page_versions.c.renderer_name,
                goodnotes_page_versions.c.renderer_version,
                goodnotes_page_versions.c.render_profile_version,
            )
            .select_from(
                goodnotes_ingestion_runs.join(
                    goodnotes_ingestion_run_stages,
                    _mine(goodnotes_ingestion_run_stages, principal_id)
                    & (goodnotes_ingestion_run_stages.c.run_id == goodnotes_ingestion_runs.c.run_id)
                    & (goodnotes_ingestion_run_stages.c.stage == "CONTENT_READY")
                    & (goodnotes_ingestion_run_stages.c.status == "SUCCEEDED"),
                )
                .join(
                    goodnotes_source_snapshots,
                    _mine(goodnotes_source_snapshots, principal_id)
                    & (goodnotes_source_snapshots.c.run_id == goodnotes_ingestion_runs.c.run_id),
                )
                .join(
                    goodnotes_page_positions,
                    _mine(goodnotes_page_positions, principal_id)
                    & (
                        goodnotes_page_positions.c.snapshot_id
                        == goodnotes_source_snapshots.c.snapshot_id
                    ),
                )
                .join(
                    goodnotes_page_versions,
                    _mine(goodnotes_page_versions, principal_id)
                    & (
                        goodnotes_page_versions.c.page_version_id
                        == goodnotes_page_positions.c.page_version_id
                    ),
                )
                .join(
                    goodnotes_page_rasters,
                    _mine(goodnotes_page_rasters, principal_id)
                    & (
                        goodnotes_page_rasters.c.page_version_id
                        == goodnotes_page_versions.c.page_version_id
                    )
                    & (goodnotes_page_rasters.c.run_id == goodnotes_ingestion_runs.c.run_id),
                )
            )
            .where(_mine(goodnotes_ingestion_runs, principal_id))
            .distinct()
            .order_by(
                goodnotes_ingestion_runs.c.run_id,
                goodnotes_page_versions.c.page_version_id,
                goodnotes_page_versions.c.content_sha256,
            )
        )
        works = tuple(
            GoodNotesPageWork(
                run_id=str(row.run_id),
                page_version_id=str(row.page_version_id),
                principal_id=str(row.principal_id),
                content_sha256=str(row.content_sha256),
                logical_page_id=(None if row.logical_page_id is None else str(row.logical_page_id)),
                renderer_name=None if row.renderer_name is None else str(row.renderer_name),
                renderer_version=(
                    None if row.renderer_version is None else str(row.renderer_version)
                ),
                render_profile_version=(
                    None if row.render_profile_version is None else str(row.render_profile_version)
                ),
            )
            for row in self._connection.execute(eligible)
        )
        assignment_partition = [_mine(goodnotes_pull_assignments, principal_id)]
        completion_partition = [_mine(goodnotes_pull_completions, principal_id)]
        assignment_partition.append(goodnotes_pull_assignments.c.client_id == client_id)
        completion_partition.append(goodnotes_pull_completions.c.client_id == client_id)
        attempt_rows = self._connection.execute(
            select(
                goodnotes_pull_assignments.c.run_id,
                goodnotes_pull_assignments.c.page_version_id,
                goodnotes_pull_assignments.c.content_sha256,
                func.max(goodnotes_pull_assignments.c.attempt).label("attempts"),
            )
            .where(*assignment_partition)
            .group_by(
                goodnotes_pull_assignments.c.run_id,
                goodnotes_pull_assignments.c.page_version_id,
                goodnotes_pull_assignments.c.content_sha256,
            )
        )
        attempts = {
            (str(row.run_id), str(row.page_version_id), str(row.content_sha256)): int(row.attempts)
            for row in attempt_rows
        }
        completed = {
            str(value)
            for value in self._connection.scalars(
                select(goodnotes_pull_completions.c.assignment_id).where(*completion_partition)
            )
        }
        completed_work = {
            (str(row.run_id), str(row.page_version_id), str(row.content_sha256))
            for row in self._connection.execute(
                select(
                    goodnotes_pull_assignments.c.run_id,
                    goodnotes_pull_assignments.c.page_version_id,
                    goodnotes_pull_assignments.c.content_sha256,
                ).where(
                    *assignment_partition,
                    goodnotes_pull_assignments.c.assignment_id.in_(completed),
                )
            )
        }
        latest = {}
        for row in self._connection.execute(
            self._assignment_select()
            .where(*assignment_partition)
            .order_by(goodnotes_pull_assignments.c.attempt)
        ):
            assignment = _assignment_from_row(row)
            latest[_work_key(assignment.work)] = (assignment, row.created_at)
        return tuple(
            PullWorkState(
                work=work,
                attempts=attempts.get(_work_key(work), 0),
                completed=_work_key(work) in completed_work,
                latest_assignment=latest[_work_key(work)][0] if _work_key(work) in latest else None,
                assigned_at=latest[_work_key(work)][1] if _work_key(work) in latest else None,
            )
            for work in works
        )

    def claim_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        assignments: tuple[PullAssignment, ...],
        expected_attempts: tuple[int, ...],
        *,
        max_attempts: int,
        lease_seconds: int,
    ) -> tuple[PullAssignment, ...]:
        now = self.lock_session(
            principal_id,
            client_id,
            context_id,
            max_attempts=max_attempts,
            lease_seconds=lease_seconds,
        )
        fingerprint = _digest(
            [
                principal_id,
                client_id,
                context_id,
                [(item.assignment_id, *_work_key(item.work), item.attempt) for item in assignments],
                expected_attempts,
                max_attempts,
            ]
        )
        claim_id = fingerprint
        try:
            prior = self._connection.execute(
                select(goodnotes_pull_claims).where(
                    _mine(goodnotes_pull_claims, principal_id),
                    goodnotes_pull_claims.c.claim_id == claim_id,
                )
            ).one_or_none()
            if prior is not None:
                if prior.request_fingerprint != fingerprint or prior.assignment_count != len(
                    assignments
                ):
                    raise PullRepositoryConflictError
                return self._assignments_for_claim(principal_id, claim_id)
            if len(assignments) != len(expected_attempts):
                raise PullRepositoryConflictError
            states = {
                _work_key(state.work): state for state in self.work_states(principal_id, client_id)
            }
            for assignment, expected in zip(assignments, expected_attempts, strict=True):
                state = states.get(_work_key(assignment.work))
                if (
                    state is None
                    or state.completed
                    or state.attempts != expected
                    or expected >= max_attempts
                    or (
                        state.assigned_at is not None
                        and now < state.assigned_at + timedelta(seconds=lease_seconds)
                    )
                    or assignment.attempt != expected + 1
                    or assignment.client_id != client_id
                    or assignment.context_id != context_id
                    or assignment.work.principal_id != principal_id
                ):
                    raise PullRepositoryConflictError
            self._connection.execute(
                goodnotes_pull_claims.insert().values(
                    _bound(
                        goodnotes_pull_claims,
                        principal_id,
                        {
                            "claim_id": claim_id,
                            "context_id": context_id,
                            "client_id": client_id,
                            "request_fingerprint": fingerprint,
                            "assignment_count": len(assignments),
                            "created_at": now,
                        },
                    )
                )
            )
            for ordinal, assignment in enumerate(assignments, 1):
                self._connection.execute(
                    goodnotes_pull_assignments.insert().values(
                        _bound(
                            goodnotes_pull_assignments,
                            principal_id,
                            {
                                "assignment_id": assignment.assignment_id,
                                "claim_id": claim_id,
                                "context_id": context_id,
                                "client_id": client_id,
                                "run_id": assignment.work.run_id,
                                "page_version_id": assignment.work.page_version_id,
                                "content_sha256": assignment.work.content_sha256,
                                "attempt": assignment.attempt,
                                "ordinal": ordinal,
                                "created_at": now,
                            },
                        )
                    )
                )
        except PullRepositoryConflictError:
            raise
        except IntegrityError:
            raise PullRepositoryConflictError from None
        return assignments

    def assignment(
        self, principal_id: str, client_id: str, assignment_id: str
    ) -> PullAssignment | None:
        row = self._connection.execute(
            self._assignment_select().where(
                _mine(goodnotes_pull_assignments, principal_id),
                goodnotes_pull_assignments.c.client_id == client_id,
                goodnotes_pull_assignments.c.assignment_id == assignment_id,
            )
        ).one_or_none()
        return None if row is None else _assignment_from_row(row)

    def completion_material(
        self, principal_id: str, client_id: str, assignment_id: str
    ) -> PullCompletionMaterial | None:
        return self._completion_material(
            principal_id,
            client_id,
            assignment_id,
            lock_proposal=False,
            require_promoting_review=False,
        )

    def _completion_material(
        self,
        principal_id: str,
        client_id: str,
        assignment_id: str,
        *,
        lock_proposal: bool,
        require_promoting_review: bool,
    ) -> PullCompletionMaterial | None:
        assignment = self.assignment(principal_id, client_id, assignment_id)
        if assignment is None:
            return None
        proposal_query = select(
            goodnotes_semantic_proposals.c.proposal_id,
            goodnotes_semantic_proposals.c.page_version_id,
            goodnotes_semantic_proposals.c.schema_version,
            goodnotes_semantic_proposals.c.analyzer_name,
            goodnotes_semantic_proposals.c.analyzer_version,
            goodnotes_semantic_proposals.c.payload,
            goodnotes_semantic_proposals.c.payload_sha256,
        ).where(
            _mine(goodnotes_semantic_proposals, principal_id),
            goodnotes_semantic_proposals.c.run_id == assignment.work.run_id,
            goodnotes_semantic_proposals.c.page_version_id == assignment.work.page_version_id,
            goodnotes_semantic_proposals.c.content_sha256 == assignment.work.content_sha256,
        )
        if lock_proposal:
            # Review decisions take this same lock. Holding it through the
            # completion insert makes the latest-decision check and write one
            # serializable critical section without adding another lock table.
            proposal_query = proposal_query.with_for_update()
        proposals = self._connection.execute(proposal_query).all()
        if not proposals:
            return None
        if len(proposals) != 1:
            raise PullRepositoryConflictError
        proposal = proposals[0]
        proposal_sha256 = _semantic_proposal_sha256(
            str(proposal.page_version_id),
            str(proposal.schema_version),
            str(proposal.analyzer_name),
            str(proposal.analyzer_version),
            dict(proposal.payload),
        )
        latest = self._connection.execute(
            select(goodnotes_semantic_review_decisions)
            .where(
                _mine(goodnotes_semantic_review_decisions, principal_id),
                goodnotes_semantic_review_decisions.c.run_id == assignment.work.run_id,
                goodnotes_semantic_review_decisions.c.proposal_id == proposal.proposal_id,
                goodnotes_semantic_review_decisions.c.proposal_sha256 == proposal_sha256,
            )
            .order_by(goodnotes_semantic_review_decisions.c.sequence.desc())
            .limit(1)
        ).one_or_none()
        result_sha256 = str(proposal.payload_sha256)
        if latest is not None and latest.action == Disposition.CORRECT_AND_ACCEPT.value:
            result_sha256 = str(latest.corrected_result_sha256)
        if require_promoting_review and (
            latest is None
            or latest.action not in {Disposition.ACCEPT.value, Disposition.CORRECT_AND_ACCEPT.value}
            or (
                latest.action == Disposition.ACCEPT.value
                and result_sha256 != str(proposal.payload_sha256)
            )
            or (
                latest.action == Disposition.CORRECT_AND_ACCEPT.value
                and (
                    latest.corrected_result_sha256 is None
                    or result_sha256 != str(latest.corrected_result_sha256)
                )
            )
        ):
            raise PullRepositoryConflictError
        return PullCompletionMaterial(
            assignment_id=assignment.assignment_id,
            proposal_id=str(proposal.proposal_id),
            run_id=assignment.work.run_id,
            page_version_id=assignment.work.page_version_id,
            content_sha256=assignment.work.content_sha256,
            proposal_sha256=proposal_sha256,
            result_sha256=result_sha256,
        )

    def semantic_proposal_material(
        self, principal_id: str, proposal_id: str
    ) -> GoodNotesSemanticProposalMaterial | None:
        row = self._connection.execute(
            select(goodnotes_semantic_proposals).where(
                _mine(goodnotes_semantic_proposals, principal_id),
                goodnotes_semantic_proposals.c.proposal_id == proposal_id,
            )
        ).one_or_none()
        if row is None:
            return None
        return GoodNotesSemanticProposalMaterial(
            proposal_id=str(row.proposal_id),
            run_id=str(row.run_id),
            page_version_id=str(row.page_version_id),
            content_sha256=str(row.content_sha256),
            schema_version=str(row.schema_version),
            analyzer_name=str(row.analyzer_name),
            analyzer_version=str(row.analyzer_version),
            payload=_canonical_payload(row.payload),
        )

    def complete_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        admissions: tuple[PullCompletionAdmission, ...],
    ) -> tuple[PullCompletionReceipt, ...]:
        session = self._connection.execute(
            select(goodnotes_pull_sessions)
            .where(
                _mine(goodnotes_pull_sessions, principal_id),
                goodnotes_pull_sessions.c.client_id == client_id,
            )
            .with_for_update()
        ).one_or_none()
        if session is None or session.context_id != context_id:
            raise PullRepositoryConflictError
        for run_id in sorted({item.completion.run_id for item in admissions}):
            if not self._lock_run(principal_id, run_id):
                raise PullRepositoryConflictError
        prior: list[PullCompletionReceipt] = []
        states = {
            _work_key(state.work): state for state in self.work_states(principal_id, client_id)
        }
        for admission in admissions:
            completion = admission.completion
            assignment = self.assignment(principal_id, client_id, completion.assignment_id)
            if (
                assignment is None
                or assignment.context_id != context_id
                or assignment.work.run_id != completion.run_id
                or assignment.work.page_version_id != completion.page_version_id
                or assignment.work.content_sha256 != completion.content_sha256
                or states.get(_work_key(assignment.work)) is None
                or states[_work_key(assignment.work)].attempts != assignment.attempt
            ):
                raise PullRepositoryConflictError
            material = self._completion_material(
                principal_id,
                client_id,
                completion.assignment_id,
                lock_proposal=True,
                require_promoting_review=True,
            )
            if material is None or material.result_sha256 != completion.result_sha256:
                raise PullRepositoryConflictError
            stored = self._completion_for(principal_id, completion.assignment_id)
            keyed = self._completion_for_key(principal_id, client_id, completion.idempotency_key)
            existing = stored or keyed
            if existing is not None:
                if (
                    existing.assignment_id != completion.assignment_id
                    or existing.idempotency_key != completion.idempotency_key
                    or existing.request_fingerprint != admission.request_fingerprint
                    or existing.result_sha256 != completion.result_sha256
                ):
                    raise PullCompletionConflictError
                prior.append(replace(existing, replayed=True))
        if prior:
            if len(prior) != len(admissions):
                raise PullCompletionConflictError
            return tuple(prior)
        now = self._clock()
        receipts: list[PullCompletionReceipt] = []
        try:
            for admission in admissions:
                completion = admission.completion
                receipt = PullCompletionReceipt(
                    completion_id=_digest([principal_id, completion.assignment_id]),
                    assignment_id=completion.assignment_id,
                    idempotency_key=completion.idempotency_key,
                    request_fingerprint=admission.request_fingerprint,
                    result_sha256=completion.result_sha256,
                )
                self._connection.execute(
                    goodnotes_pull_completions.insert().values(
                        _bound(
                            goodnotes_pull_completions,
                            principal_id,
                            {
                                "completion_id": receipt.completion_id,
                                "assignment_id": receipt.assignment_id,
                                "context_id": context_id,
                                "client_id": client_id,
                                "idempotency_key": receipt.idempotency_key,
                                "request_fingerprint": receipt.request_fingerprint,
                                "result_sha256": receipt.result_sha256,
                                "created_at": now,
                            },
                        )
                    )
                )
                receipts.append(receipt)
        except IntegrityError:
            raise PullRepositoryConflictError from None
        return tuple(receipts)

    def status(
        self,
        principal_id: str,
        client_id: str,
        *,
        context_id: str,
        max_attempts: int,
        lease_seconds: int,
    ) -> GoodNotesPullStatus:
        self._validate_policy(max_attempts, lease_seconds)
        session_query = (
            select(goodnotes_pull_sessions)
            .where(
                _mine(goodnotes_pull_sessions, principal_id),
                goodnotes_pull_sessions.c.client_id == client_id,
            )
            .with_for_update()
        )
        session = self._connection.execute(session_query).one_or_none()
        if session is None:
            states = self._work_states(principal_id, client_id=client_id)
            # A creator can commit after the first absent-session lookup. Recheck
            # after reading work so every visible assignment has validated policy.
            session = self._connection.execute(session_query).one_or_none()
        if session is not None and (
            session.context_id != context_id
            or session.max_attempts != max_attempts
            or session.lease_seconds != lease_seconds
        ):
            raise PullRepositoryConflictError
        if session is not None:
            states = self._work_states(principal_id, client_id=client_id)
        now = self._clock()
        expired = {
            _work_key(state.work)
            for state in states
            if state.assigned_at is not None
            and now >= state.assigned_at + timedelta(seconds=lease_seconds)
        }
        return GoodNotesPullStatus(
            pending=sum(
                not state.completed
                and state.attempts < max_attempts
                and (state.attempts == 0 or _work_key(state.work) in expired)
                for state in states
            ),
            assigned=sum(
                not state.completed and state.attempts > 0 and _work_key(state.work) not in expired
                for state in states
            ),
            completed=sum(state.completed for state in states),
            exhausted=sum(
                not state.completed
                and state.attempts >= max_attempts
                and _work_key(state.work) in expired
                for state in states
            ),
        )

    def semantic_review_cases(
        self,
        principal_id: str,
        *,
        limit: int,
        state: ProposalState | None = None,
        after_opened_at: datetime | None = None,
        after_review_case_id: str | None = None,
    ) -> tuple[GoodNotesSemanticReviewCase, ...]:
        if (after_opened_at is None) != (after_review_case_id is None):
            raise SemanticReviewConflictError
        rows = self._connection.execute(
            select(goodnotes_semantic_proposals)
            .where(_mine(goodnotes_semantic_proposals, principal_id))
            .order_by(
                goodnotes_semantic_proposals.c.created_at,
                goodnotes_semantic_proposals.c.proposal_id,
            )
        ).all()
        cases: list[GoodNotesSemanticReviewCase] = []
        for row in rows:
            decisions = self._connection.execute(
                select(
                    goodnotes_semantic_review_decisions.c.sequence,
                    goodnotes_semantic_review_decisions.c.action,
                )
                .where(
                    _mine(goodnotes_semantic_review_decisions, principal_id),
                    goodnotes_semantic_review_decisions.c.proposal_id == row.proposal_id,
                )
                .order_by(goodnotes_semantic_review_decisions.c.sequence)
            ).all()
            latest = None if not decisions else Disposition(str(decisions[-1].action))
            case = GoodNotesSemanticReviewCase(
                review_case_id=_semantic_review_case_id(principal_id, str(row.proposal_id)),
                proposal_id=str(row.proposal_id),
                run_id=str(row.run_id),
                page_version_id=str(row.page_version_id),
                principal_id=principal_id,
                opened_at=row.created_at,
                proposal_state=_semantic_state(latest),
                review_version=0 if not decisions else int(decisions[-1].sequence),
                latest_disposition=latest,
            )
            if state is not None and case.proposal_state is not state:
                continue
            if after_opened_at is not None and (case.opened_at, case.review_case_id) <= (
                after_opened_at,
                after_review_case_id,
            ):
                continue
            cases.append(case)
            if len(cases) == limit:
                break
        return tuple(cases)

    def semantic_review_case(
        self, principal_id: str, review_case_id: str
    ) -> GoodNotesSemanticReviewCase | None:
        # The public case id is a deterministic name over Principal/proposal,
        # not a persisted column. Resolve that exact name from the narrow
        # Principal partition, then issue exact proposal/decision lookups. This
        # avoids the paginated case-list path and its former arbitrary cutoff.
        proposal_ids = self._connection.scalars(
            select(goodnotes_semantic_proposals.c.proposal_id).where(
                _mine(goodnotes_semantic_proposals, principal_id)
            )
        )
        matches = tuple(
            str(proposal_id)
            for proposal_id in proposal_ids
            if _semantic_review_case_id(principal_id, str(proposal_id)) == review_case_id
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise SemanticReviewConflictError
        proposal = self._connection.execute(
            select(goodnotes_semantic_proposals).where(
                _mine(goodnotes_semantic_proposals, principal_id),
                goodnotes_semantic_proposals.c.proposal_id == matches[0],
            )
        ).one_or_none()
        if proposal is None:
            return None
        proposal_sha256 = _semantic_proposal_sha256(
            str(proposal.page_version_id),
            str(proposal.schema_version),
            str(proposal.analyzer_name),
            str(proposal.analyzer_version),
            dict(proposal.payload),
        )
        latest = self._connection.execute(
            select(
                goodnotes_semantic_review_decisions.c.sequence,
                goodnotes_semantic_review_decisions.c.action,
            )
            .where(
                _mine(goodnotes_semantic_review_decisions, principal_id),
                goodnotes_semantic_review_decisions.c.run_id == proposal.run_id,
                goodnotes_semantic_review_decisions.c.proposal_id == proposal.proposal_id,
                goodnotes_semantic_review_decisions.c.proposal_sha256 == proposal_sha256,
            )
            .order_by(goodnotes_semantic_review_decisions.c.sequence.desc())
            .limit(1)
        ).one_or_none()
        disposition = None if latest is None else Disposition(str(latest.action))
        return GoodNotesSemanticReviewCase(
            review_case_id=review_case_id,
            proposal_id=str(proposal.proposal_id),
            run_id=str(proposal.run_id),
            page_version_id=str(proposal.page_version_id),
            principal_id=principal_id,
            opened_at=proposal.created_at,
            proposal_state=_semantic_state(disposition),
            review_version=0 if latest is None else int(latest.sequence),
            latest_disposition=disposition,
        )

    def decide_semantic_review(self, request: ReviewDecisionRequest) -> ReviewDecision:
        if request.disposition is Disposition.CORRECT_AND_ACCEPT and (
            request.semantic_corrected_payload is None
            or request.semantic_corrected_result_sha256 is None
        ):
            raise ReviewUnsupportedError(
                "semantic correction requires validated structured content"
            )
        if request.disposition is not Disposition.CORRECT_AND_ACCEPT and (
            request.semantic_corrected_payload is not None
            or request.semantic_corrected_result_sha256 is not None
        ):
            raise ReviewUnsupportedError("semantic correction content belongs only to correction")
        case = self.semantic_review_case(request.principal_id, request.review_case_id)
        if case is None:
            raise ReviewNotFoundError("the request names no stored review case")
        proposal = self._connection.execute(
            select(goodnotes_semantic_proposals).where(
                _mine(goodnotes_semantic_proposals, request.principal_id),
                goodnotes_semantic_proposals.c.proposal_id == case.proposal_id,
            )
        ).one()
        proposal_sha256 = _semantic_proposal_sha256(
            str(proposal.page_version_id),
            str(proposal.schema_version),
            str(proposal.analyzer_name),
            str(proposal.analyzer_version),
            dict(proposal.payload),
        )
        request_fingerprint = _digest(
            [
                request.principal_id,
                request.review_case_id,
                request.expected_review_version,
                request.disposition.value,
                request.corrected_value,
                request.semantic_corrected_payload,
                request.semantic_corrected_result_sha256,
                request.reason,
            ]
        )
        try:
            recorded = self.record_semantic_review(
                SemanticReviewDecision(
                    decision_id=f"gnsrd_{request_fingerprint[:24]}",
                    principal_id=request.principal_id,
                    run_id=case.run_id,
                    proposal_id=case.proposal_id,
                    proposal_sha256=proposal_sha256,
                    action=request.disposition.value,
                    request_fingerprint=request_fingerprint,
                    decided_at=request.decided_at,
                    corrected_payload=(
                        None
                        if request.semantic_corrected_payload is None
                        else _canonical_payload(request.semantic_corrected_payload)
                    ),
                    corrected_result_sha256=request.semantic_corrected_result_sha256,
                ),
                expected_review_version=request.expected_review_version,
            )
        except SemanticReviewConflictError:
            raise ReviewConflictError("the semantic review changed concurrently") from None
        if recorded.sequence is None:
            raise SemanticReviewConflictError
        return ReviewDecision(
            decision_id=make_identifier(IdKind.REVIEW_DECISION, request_fingerprint[:32]),
            review_case_id=request.review_case_id,
            sequence=recorded.sequence,
            disposition=request.disposition,
            principal_id=request.principal_id,
            correlation_id=request.correlation_id,
            audit_id=request.audit_id,
            decided_at=request.decided_at,
            proposal_state=_semantic_state(request.disposition),
        )

    def record_semantic_review(
        self,
        decision: SemanticReviewDecision,
        *,
        expected_review_version: int | None = None,
    ) -> SemanticReviewDecision:
        if decision.sequence is not None:
            raise SemanticReviewConflictError
        try:
            action = Disposition(decision.action)
        except ValueError:
            raise SemanticReviewConflictError from None
        corrected = action is Disposition.CORRECT_AND_ACCEPT
        if corrected is not (
            decision.corrected_payload is not None and decision.corrected_result_sha256 is not None
        ):
            raise SemanticReviewConflictError
        if corrected:
            canonical_correction = _canonical_payload(decision.corrected_payload)
            if _corrected_result_sha256(canonical_correction) != decision.corrected_result_sha256:
                raise SemanticReviewConflictError
            decision = replace(decision, corrected_payload=canonical_correction)
        if not self._lock_run(decision.principal_id, decision.run_id):
            raise SemanticReviewConflictError
        proposal = self._connection.execute(
            select(goodnotes_semantic_proposals)
            .where(
                _mine(goodnotes_semantic_proposals, decision.principal_id),
                goodnotes_semantic_proposals.c.proposal_id == decision.proposal_id,
            )
            .with_for_update()
        ).one_or_none()
        if proposal is None or proposal.run_id != decision.run_id:
            raise SemanticReviewConflictError
        digest = _semantic_proposal_sha256(
            str(proposal.page_version_id),
            str(proposal.schema_version),
            str(proposal.analyzer_name),
            str(proposal.analyzer_version),
            dict(proposal.payload),
        )
        if digest != decision.proposal_sha256:
            raise SemanticReviewConflictError
        prior = self._semantic_review(decision.principal_id, decision.decision_id)
        by_request = self._connection.execute(
            select(goodnotes_semantic_review_decisions).where(
                _mine(goodnotes_semantic_review_decisions, decision.principal_id),
                goodnotes_semantic_review_decisions.c.request_fingerprint
                == decision.request_fingerprint,
            )
        ).one_or_none()
        existing = prior or by_request
        if existing is not None:
            if any(
                (
                    existing.decision_id != decision.decision_id,
                    existing.run_id != decision.run_id,
                    existing.proposal_id != decision.proposal_id,
                    existing.proposal_sha256 != decision.proposal_sha256,
                    existing.action != action.value,
                    existing.request_fingerprint != decision.request_fingerprint,
                    existing.corrected_payload != decision.corrected_payload,
                    existing.corrected_result_sha256 != decision.corrected_result_sha256,
                )
            ):
                raise SemanticReviewConflictError
            return replace(
                decision,
                action=action.value,
                sequence=int(existing.sequence),
                replayed=True,
            )
        if (
            self._connection.execute(
                select(goodnotes_semantic_promotion_receipts.c.receipt_id).where(
                    _mine(goodnotes_semantic_promotion_receipts, decision.principal_id),
                    goodnotes_semantic_promotion_receipts.c.run_id == decision.run_id,
                )
            ).first()
            is not None
        ):
            raise SemanticReviewConflictError
        review_partition = _mine(goodnotes_semantic_review_decisions, decision.principal_id)
        current_version = int(
            self._connection.scalar(
                select(func.max(goodnotes_semantic_review_decisions.c.sequence)).where(
                    review_partition,
                    goodnotes_semantic_review_decisions.c.run_id == decision.run_id,
                    goodnotes_semantic_review_decisions.c.proposal_id == decision.proposal_id,
                    goodnotes_semantic_review_decisions.c.proposal_sha256
                    == decision.proposal_sha256,
                )
            )
            or 0
        )
        if expected_review_version is not None and current_version != expected_review_version:
            raise SemanticReviewConflictError
        sequence = (
            int(
                self._connection.scalar(
                    select(func.count())
                    .select_from(goodnotes_semantic_review_decisions)
                    .where(
                        review_partition,
                        goodnotes_semantic_review_decisions.c.run_id == decision.run_id,
                        goodnotes_semantic_review_decisions.c.proposal_sha256
                        == decision.proposal_sha256,
                    )
                )
                or 0
            )
            + 1
        )
        try:
            self._connection.execute(
                goodnotes_semantic_review_decisions.insert().values(
                    _bound(
                        goodnotes_semantic_review_decisions,
                        decision.principal_id,
                        {
                            "decision_id": decision.decision_id,
                            "run_id": decision.run_id,
                            "proposal_id": decision.proposal_id,
                            "proposal_sha256": decision.proposal_sha256,
                            "sequence": sequence,
                            "action": action.value,
                            "request_fingerprint": decision.request_fingerprint,
                            "corrected_payload": decision.corrected_payload,
                            "corrected_result_sha256": decision.corrected_result_sha256,
                            "decided_at": decision.decided_at,
                        },
                    )
                )
            )
        except IntegrityError:
            raise SemanticReviewConflictError from None
        return replace(decision, action=action.value, sequence=sequence, replayed=False)

    def semantic_review_evidence(
        self, principal_id: str, run_id: str, proposal_sha256s: tuple[str, ...]
    ) -> tuple[GoodNotesSemanticPromotionEvidence, ...]:
        if len(set(proposal_sha256s)) != len(proposal_sha256s):
            raise SemanticReviewConflictError
        rows = self._connection.execute(
            select(goodnotes_semantic_review_decisions)
            .where(
                _mine(goodnotes_semantic_review_decisions, principal_id),
                goodnotes_semantic_review_decisions.c.run_id == run_id,
                goodnotes_semantic_review_decisions.c.proposal_sha256.in_(proposal_sha256s),
            )
            .order_by(goodnotes_semantic_review_decisions.c.sequence)
        )
        found = {
            str(row.proposal_sha256): GoodNotesSemanticPromotionEvidence(
                principal_id=principal_id,
                run_id=run_id,
                proposal_sha256=str(row.proposal_sha256),
                disposition=Disposition(str(row.action)),
                corrected_payload=(
                    None
                    if row.corrected_payload is None
                    else _canonical_payload(row.corrected_payload)
                ),
                result_sha256=(
                    str(row.corrected_result_sha256)
                    if row.corrected_result_sha256 is not None
                    else None
                ),
            )
            for row in rows
        }
        return tuple(found[digest] for digest in proposal_sha256s if digest in found)

    @staticmethod
    def _validate_policy(max_attempts: object, lease_seconds: object) -> None:
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 10
            or isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or not 60 <= lease_seconds <= 86400
        ):
            raise PullRepositoryConflictError

    def lock_session(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        *,
        max_attempts: int,
        lease_seconds: int,
    ) -> datetime:
        self._validate_policy(max_attempts, lease_seconds)
        self._connection.execute(
            pg_insert(goodnotes_pull_sessions)
            .values(
                _bound(
                    goodnotes_pull_sessions,
                    principal_id,
                    {
                        "context_id": context_id,
                        "client_id": client_id,
                        "max_attempts": max_attempts,
                        "lease_seconds": lease_seconds,
                        "created_at": self._clock(),
                    },
                )
            )
            .on_conflict_do_nothing()
        )
        session = self._connection.execute(
            select(goodnotes_pull_sessions)
            .where(
                _mine(goodnotes_pull_sessions, principal_id),
                goodnotes_pull_sessions.c.client_id == client_id,
            )
            .with_for_update()
        ).one_or_none()
        if (
            session is None
            or session.context_id != context_id
            or session.max_attempts != max_attempts
            or session.lease_seconds != lease_seconds
        ):
            raise PullRepositoryConflictError
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise PullRepositoryConflictError
        return now

    def _assignment_select(self) -> Select[tuple[object, ...]]:
        return select(
            goodnotes_pull_assignments,
            goodnotes_page_versions.c.logical_page_id,
            goodnotes_page_versions.c.renderer_name,
            goodnotes_page_versions.c.renderer_version,
            goodnotes_page_versions.c.render_profile_version,
        ).join(
            goodnotes_page_versions,
            matching_partition_criterion(goodnotes_page_versions, goodnotes_pull_assignments)
            & (
                goodnotes_page_versions.c.page_version_id
                == goodnotes_pull_assignments.c.page_version_id
            ),
        )

    def _assignments_for_claim(
        self, principal_id: str, claim_id: str
    ) -> tuple[PullAssignment, ...]:
        rows = self._connection.execute(
            self._assignment_select()
            .where(
                _mine(goodnotes_pull_assignments, principal_id),
                goodnotes_pull_assignments.c.claim_id == claim_id,
            )
            .order_by(goodnotes_pull_assignments.c.ordinal)
        )
        return tuple(_assignment_from_row(row) for row in rows)

    def _completion_for(
        self, principal_id: str, assignment_id: str
    ) -> PullCompletionReceipt | None:
        row = self._connection.execute(
            select(goodnotes_pull_completions).where(
                _mine(goodnotes_pull_completions, principal_id),
                goodnotes_pull_completions.c.assignment_id == assignment_id,
            )
        ).one_or_none()
        return None if row is None else self._completion_from_row(row)

    def _completion_for_key(
        self, principal_id: str, client_id: str, idempotency_key: str
    ) -> PullCompletionReceipt | None:
        row = self._connection.execute(
            select(goodnotes_pull_completions).where(
                _mine(goodnotes_pull_completions, principal_id),
                goodnotes_pull_completions.c.idempotency_key == idempotency_key,
                goodnotes_pull_completions.c.client_id == client_id,
            )
        ).one_or_none()
        return None if row is None else self._completion_from_row(row)

    @staticmethod
    def _completion_from_row(row: object) -> PullCompletionReceipt:
        value = row._mapping  # type: ignore[attr-defined]
        return PullCompletionReceipt(
            completion_id=str(value["completion_id"]),
            assignment_id=str(value["assignment_id"]),
            idempotency_key=str(value["idempotency_key"]),
            request_fingerprint=str(value["request_fingerprint"]),
            result_sha256=str(value["result_sha256"]),
        )

    def _semantic_review(
        self, principal_id: str, decision_id: str
    ) -> Row[tuple[object, ...]] | None:
        return self._connection.execute(
            select(goodnotes_semantic_review_decisions).where(
                _mine(goodnotes_semantic_review_decisions, principal_id),
                goodnotes_semantic_review_decisions.c.decision_id == decision_id,
            )
        ).one_or_none()
