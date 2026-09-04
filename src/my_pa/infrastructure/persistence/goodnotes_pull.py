"""Durable Principal/client-bound GoodNotes pull and semantic-review ledgers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Select

from my_pa.application.goodnotes_occurrences import (
    GoodNotesSemanticPromotionEvidence,
    semantic_proposal_sha256,
)
from my_pa.application.goodnotes_pull_orchestration import (
    GoodNotesPullStatus,
    PullAssignment,
    PullCompletionAdmission,
    PullCompletionConflictError,
    PullCompletionReceipt,
    PullRepositoryConflictError,
    PullWorkState,
    SemanticReviewConflictError,
    SemanticReviewDecision,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.models import GoodNotesPageWork
from my_pa.infrastructure.persistence.tables import (
    goodnotes_ingestion_run_stages,
    goodnotes_ingestion_runs,
    goodnotes_page_positions,
    goodnotes_page_rasters,
    goodnotes_page_versions,
    goodnotes_pull_assignments,
    goodnotes_pull_claims,
    goodnotes_pull_completions,
    goodnotes_pull_sessions,
    goodnotes_semantic_proposals,
    goodnotes_semantic_review_decisions,
    goodnotes_source_snapshots,
)

__all__ = ["SqlGoodNotesPullRepository"]


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _work_key(work: GoodNotesPageWork) -> tuple[str, str, str]:
    return work.run_id, work.page_version_id, work.content_sha256


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

    def work_states(self, principal_id: str) -> tuple[PullWorkState, ...]:
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
                    (goodnotes_ingestion_run_stages.c.principal_id == principal_id)
                    & (goodnotes_ingestion_run_stages.c.run_id == goodnotes_ingestion_runs.c.run_id)
                    & (goodnotes_ingestion_run_stages.c.stage == "CONTENT_READY")
                    & (goodnotes_ingestion_run_stages.c.status == "SUCCEEDED"),
                )
                .join(
                    goodnotes_source_snapshots,
                    (goodnotes_source_snapshots.c.principal_id == principal_id)
                    & (goodnotes_source_snapshots.c.run_id == goodnotes_ingestion_runs.c.run_id),
                )
                .join(
                    goodnotes_page_positions,
                    (goodnotes_page_positions.c.principal_id == principal_id)
                    & (
                        goodnotes_page_positions.c.snapshot_id
                        == goodnotes_source_snapshots.c.snapshot_id
                    ),
                )
                .join(
                    goodnotes_page_versions,
                    (goodnotes_page_versions.c.principal_id == principal_id)
                    & (
                        goodnotes_page_versions.c.page_version_id
                        == goodnotes_page_positions.c.page_version_id
                    ),
                )
                .join(
                    goodnotes_page_rasters,
                    (goodnotes_page_rasters.c.principal_id == principal_id)
                    & (
                        goodnotes_page_rasters.c.page_version_id
                        == goodnotes_page_versions.c.page_version_id
                    )
                    & (goodnotes_page_rasters.c.run_id == goodnotes_ingestion_runs.c.run_id),
                )
            )
            .where(goodnotes_ingestion_runs.c.principal_id == principal_id)
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
        attempt_rows = self._connection.execute(
            select(
                goodnotes_pull_assignments.c.run_id,
                goodnotes_pull_assignments.c.page_version_id,
                goodnotes_pull_assignments.c.content_sha256,
                func.max(goodnotes_pull_assignments.c.attempt).label("attempts"),
            )
            .where(goodnotes_pull_assignments.c.principal_id == principal_id)
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
                select(goodnotes_pull_completions.c.assignment_id).where(
                    goodnotes_pull_completions.c.principal_id == principal_id
                )
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
                    goodnotes_pull_assignments.c.principal_id == principal_id,
                    goodnotes_pull_assignments.c.assignment_id.in_(completed),
                )
            )
        }
        return tuple(
            PullWorkState(
                work=work,
                attempts=attempts.get(_work_key(work), 0),
                completed=_work_key(work) in completed_work,
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
    ) -> tuple[PullAssignment, ...]:
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
                    goodnotes_pull_claims.c.principal_id == principal_id,
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
            states = {_work_key(state.work): state for state in self.work_states(principal_id)}
            for assignment, expected in zip(assignments, expected_attempts, strict=True):
                state = states.get(_work_key(assignment.work))
                if (
                    state is None
                    or state.completed
                    or state.attempts != expected
                    or expected >= max_attempts
                    or assignment.attempt != expected + 1
                    or assignment.client_id != client_id
                    or assignment.context_id != context_id
                    or assignment.work.principal_id != principal_id
                ):
                    raise PullRepositoryConflictError
            self._ensure_session(principal_id, client_id, context_id, max_attempts)
            now = self._clock()
            self._connection.execute(
                goodnotes_pull_claims.insert().values(
                    principal_id=principal_id,
                    claim_id=claim_id,
                    context_id=context_id,
                    client_id=client_id,
                    request_fingerprint=fingerprint,
                    assignment_count=len(assignments),
                    created_at=now,
                )
            )
            for ordinal, assignment in enumerate(assignments, 1):
                self._connection.execute(
                    goodnotes_pull_assignments.insert().values(
                        principal_id=principal_id,
                        assignment_id=assignment.assignment_id,
                        claim_id=claim_id,
                        context_id=context_id,
                        client_id=client_id,
                        run_id=assignment.work.run_id,
                        page_version_id=assignment.work.page_version_id,
                        content_sha256=assignment.work.content_sha256,
                        attempt=assignment.attempt,
                        ordinal=ordinal,
                        created_at=now,
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
                goodnotes_pull_assignments.c.principal_id == principal_id,
                goodnotes_pull_assignments.c.client_id == client_id,
                goodnotes_pull_assignments.c.assignment_id == assignment_id,
            )
        ).one_or_none()
        return None if row is None else _assignment_from_row(row)

    def complete_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        admissions: tuple[PullCompletionAdmission, ...],
    ) -> tuple[PullCompletionReceipt, ...]:
        prior: list[PullCompletionReceipt] = []
        states = {_work_key(state.work): state for state in self.work_states(principal_id)}
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
            proposal = self._connection.execute(
                select(goodnotes_semantic_proposals.c.proposal_id).where(
                    goodnotes_semantic_proposals.c.principal_id == principal_id,
                    goodnotes_semantic_proposals.c.run_id == completion.run_id,
                    goodnotes_semantic_proposals.c.page_version_id == completion.page_version_id,
                    goodnotes_semantic_proposals.c.content_sha256 == completion.content_sha256,
                    goodnotes_semantic_proposals.c.payload_sha256 == completion.result_sha256,
                )
            ).first()
            if proposal is None:
                raise PullRepositoryConflictError
            stored = self._completion_for(principal_id, completion.assignment_id)
            keyed = self._completion_for_key(principal_id, completion.idempotency_key)
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
                        principal_id=principal_id,
                        completion_id=receipt.completion_id,
                        assignment_id=receipt.assignment_id,
                        context_id=context_id,
                        client_id=client_id,
                        idempotency_key=receipt.idempotency_key,
                        request_fingerprint=receipt.request_fingerprint,
                        result_sha256=receipt.result_sha256,
                        created_at=now,
                    )
                )
                receipts.append(receipt)
        except IntegrityError:
            raise PullRepositoryConflictError from None
        return tuple(receipts)

    def status(self, principal_id: str, client_id: str) -> GoodNotesPullStatus:
        session = self._connection.execute(
            select(goodnotes_pull_sessions.c.max_attempts).where(
                goodnotes_pull_sessions.c.principal_id == principal_id,
                goodnotes_pull_sessions.c.client_id == client_id,
            )
        ).one_or_none()
        states = self.work_states(principal_id)
        maximum = 10 if session is None else int(session.max_attempts)
        return GoodNotesPullStatus(
            pending=sum(not state.completed and state.attempts == 0 for state in states),
            assigned=sum(not state.completed and 0 < state.attempts < maximum for state in states),
            completed=sum(state.completed for state in states),
            exhausted=sum(not state.completed and state.attempts >= maximum for state in states),
        )

    def record_semantic_review(self, decision: SemanticReviewDecision) -> SemanticReviewDecision:
        if decision.sequence is not None:
            raise SemanticReviewConflictError
        try:
            action = Disposition(decision.action)
        except ValueError:
            raise SemanticReviewConflictError from None
        proposal = self._connection.execute(
            select(goodnotes_semantic_proposals)
            .where(
                goodnotes_semantic_proposals.c.principal_id == decision.principal_id,
                goodnotes_semantic_proposals.c.proposal_id == decision.proposal_id,
            )
            .with_for_update()
        ).one_or_none()
        if proposal is None or proposal.run_id != decision.run_id:
            raise SemanticReviewConflictError
        digest = semantic_proposal_sha256(
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
                goodnotes_semantic_review_decisions.c.principal_id == decision.principal_id,
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
                )
            ):
                raise SemanticReviewConflictError
            return replace(
                decision,
                action=action.value,
                sequence=int(existing.sequence),
                replayed=True,
            )
        sequence = (
            int(
                self._connection.scalar(
                    select(func.count())
                    .select_from(goodnotes_semantic_review_decisions)
                    .where(
                        goodnotes_semantic_review_decisions.c.principal_id == decision.principal_id,
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
                    principal_id=decision.principal_id,
                    decision_id=decision.decision_id,
                    run_id=decision.run_id,
                    proposal_id=decision.proposal_id,
                    proposal_sha256=decision.proposal_sha256,
                    sequence=sequence,
                    action=action.value,
                    request_fingerprint=decision.request_fingerprint,
                    decided_at=decision.decided_at,
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
                goodnotes_semantic_review_decisions.c.principal_id == principal_id,
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
            )
            for row in rows
        }
        return tuple(found[digest] for digest in proposal_sha256s if digest in found)

    def _ensure_session(
        self, principal_id: str, client_id: str, context_id: str, max_attempts: int
    ) -> None:
        self._connection.execute(
            pg_insert(goodnotes_pull_sessions)
            .values(
                principal_id=principal_id,
                context_id=context_id,
                client_id=client_id,
                max_attempts=max_attempts,
                created_at=self._clock(),
            )
            .on_conflict_do_nothing(constraint="one_goodnotes_pull_session_per_client")
        )
        session = self._connection.execute(
            select(goodnotes_pull_sessions)
            .where(
                goodnotes_pull_sessions.c.principal_id == principal_id,
                goodnotes_pull_sessions.c.client_id == client_id,
            )
            .with_for_update()
        ).one_or_none()
        if (
            session is None
            or session.context_id != context_id
            or session.max_attempts != max_attempts
        ):
            raise PullRepositoryConflictError

    def _assignment_select(self) -> Select[tuple[object, ...]]:
        return select(
            goodnotes_pull_assignments,
            goodnotes_page_versions.c.logical_page_id,
            goodnotes_page_versions.c.renderer_name,
            goodnotes_page_versions.c.renderer_version,
            goodnotes_page_versions.c.render_profile_version,
        ).join(
            goodnotes_page_versions,
            (goodnotes_page_versions.c.principal_id == goodnotes_pull_assignments.c.principal_id)
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
                goodnotes_pull_assignments.c.principal_id == principal_id,
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
                goodnotes_pull_completions.c.principal_id == principal_id,
                goodnotes_pull_completions.c.assignment_id == assignment_id,
            )
        ).one_or_none()
        return None if row is None else self._completion_from_row(row)

    def _completion_for_key(
        self, principal_id: str, idempotency_key: str
    ) -> PullCompletionReceipt | None:
        row = self._connection.execute(
            select(goodnotes_pull_completions).where(
                goodnotes_pull_completions.c.principal_id == principal_id,
                goodnotes_pull_completions.c.idempotency_key == idempotency_key,
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
                goodnotes_semantic_review_decisions.c.principal_id == principal_id,
                goodnotes_semantic_review_decisions.c.decision_id == decision_id,
            )
        ).one_or_none()
