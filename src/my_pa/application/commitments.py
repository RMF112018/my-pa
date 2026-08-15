"""`CommitmentManagementService`: the one canonical way to mutate a Commitment.

WP-TM-05. Mirrors `application.tasks.TaskManagementService`'s `_mutate`
transactional/idempotency/optimistic-concurrency/receipt mechanism exactly,
over `domain.task.commitment.Commitment`/`CommitmentHistoryEntry` instead of
`Task`/`TaskHistoryEntry`. See that module's docstring for the full rationale;
it applies here unchanged. Two public mutations only, per the
operator-approved minimal scope: `create_commitment` and `close_commitment`.
There is no `update_commitment` beyond closure here because WP-TM-05 names no
other Commitment mutation a caller needs yet — adding one speculatively is
exactly what `AGENTS.md`'s minimal-implementation rule refuses.

**Closing a Commitment is always an explicit, separate call.** Nothing in
this module, `application.tasks.TaskManagementService`, or
`application.service` ever closes a Commitment as a side effect of completing
a Task or a Follow-Up Task — that is the operator-confirmed constraint
"Completing a Task or Follow-Up Task must NOT silently fulfill or close a
linked Commitment", restated here at the one place a Commitment can actually
be closed.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from my_pa.contracts.ports import CommitmentManagementUnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry, CommitmentMutationAction
from my_pa.domain.task.history import TaskMutationActor, TaskMutationOutcome

__all__ = [
    "CommitmentManagementService",
    "CommitmentMutationReceipt",
    "CommitmentNotFoundError",
    "CommitmentVersionConflictError",
]


class CommitmentNotFoundError(Exception):
    """Raised when a mutation names a `commitment_id` absent from this Principal's partition."""


class CommitmentVersionConflictError(Exception):
    """Raised when `expected_version` does not match the commitment's current version.

    Carries the `CommitmentMutationReceipt` this attempt still produced — the
    `REJECTED` history row is written and committed before this is raised,
    exactly as `TaskVersionConflictError` states for the task plane.
    """

    def __init__(self, receipt: CommitmentMutationReceipt) -> None:
        super().__init__("the commitment's current version does not match expected_version")
        self.receipt = receipt


@dataclass(frozen=True, slots=True)
class CommitmentMutationReceipt:
    """What a mutation attempt returns: the history row it produced, and the commitment now."""

    history: CommitmentHistoryEntry
    commitment: Commitment
    #: `True` when `history` is a prior attempt's receipt, returned unchanged
    #: because the request's `idempotency_key` had already been used.
    replayed: bool = False


class CommitmentManagementService:
    """The one canonical entry point for creating and closing a Commitment."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], CommitmentManagementUnitOfWork],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def create_commitment(
        self,
        *,
        principal_id: str,
        counterparty_person_id: str,
        direction: CommitmentDirection,
        summary: str,
        origin_evidence_ref: str,
        actor: TaskMutationActor,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
        accepted_by_review_decision_id: str | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> CommitmentMutationReceipt:
        """Create a new commitment.

        The direct-acceptance path: pass `accepted_by_review_decision_id`.

        Mirrors `TaskManagementService.create_task`'s exact semantics: passing
        `accepted_by_review_decision_id` creates the commitment already
        `ContinuityEvidenceState.ACCEPTED`, in this one call, under the
        ordinary `CREATE` action. Omit it and the commitment is created
        `PROPOSED` — the proposal-first path AI/source-inferred commitments
        take.
        """

        def change(current: Commitment | None) -> Commitment:
            del current  # a creation attempt never reads an existing row
            now = self._clock()
            evidence_state = (
                ContinuityEvidenceState.ACCEPTED
                if accepted_by_review_decision_id is not None
                else ContinuityEvidenceState.PROPOSED
            )
            return Commitment(
                commitment_id=issue_identifier(IdKind.COMMITMENT),
                principal_id=principal_id,
                counterparty_person_id=counterparty_person_id,
                direction=direction,
                summary=summary,
                state=CommitmentState.OPEN,
                evidence_state=evidence_state,
                origin_evidence_ref=origin_evidence_ref,
                opened_at=now,
                created_at=now,
                updated_at=now,
                due_at=due_at,
                project_id=project_id,
                situation_id=situation_id,
                accepted_by_review_decision_id=accepted_by_review_decision_id,
            )

        return self._mutate(
            principal_id=principal_id,
            commitment_id=None,
            expected_version=None,
            action=CommitmentMutationAction.CREATE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=change,
        )

    def close_commitment(
        self,
        *,
        principal_id: str,
        commitment_id: str,
        expected_version: int,
        closure_evidence_ref: str,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> CommitmentMutationReceipt:
        """Close a commitment. Already-closed is recorded `NO_OP`, not `APPLIED`."""

        def change(current: Commitment) -> Commitment:
            if current.state is CommitmentState.CLOSED:
                return current
            if not (closure_evidence_ref or "").strip():
                raise ValueError("closing a commitment requires the evidence that closed it")
            return dataclasses.replace(
                current,
                state=CommitmentState.CLOSED,
                closed_at=self._clock(),
                closure_evidence_ref=closure_evidence_ref,
            )

        return self._mutate(
            principal_id=principal_id,
            commitment_id=commitment_id,
            expected_version=expected_version,
            action=CommitmentMutationAction.CLOSE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=change,
        )

    def _mutate(
        self,
        *,
        principal_id: str,
        commitment_id: str | None,
        expected_version: int | None,
        action: CommitmentMutationAction,
        actor: TaskMutationActor,
        idempotency_key: str | None,
        client_context: str | None,
        change: Callable[[Commitment], Commitment] | Callable[[Commitment | None], Commitment],
    ) -> CommitmentMutationReceipt:
        """The single transactional mechanism every public method delegates to.

        Identical shape to `TaskManagementService._mutate`; see that method's
        docstring for the full rationale behind the ordering (raises after the
        `with` block, not inside it) and the idempotency/version-conflict/
        no-op handling.
        """
        pending_not_found = False
        pending_conflict: CommitmentMutationReceipt | None = None
        result: CommitmentMutationReceipt | None = None

        with self._unit_of_work() as uow:
            if idempotency_key is not None:
                prior = uow.commitments.find_history_by_idempotency_key(
                    principal_id, idempotency_key
                )
                if prior is not None:
                    prior_commitment = uow.commitments.get_for_update(
                        principal_id, prior.commitment_id
                    )
                    if prior_commitment is None:
                        raise RuntimeError(
                            "a recorded history entry names a commitment that still exists"
                        )
                    result = CommitmentMutationReceipt(
                        history=prior, commitment=prior_commitment, replayed=True
                    )

            if result is None:
                current = (
                    uow.commitments.get_for_update(principal_id, commitment_id)
                    if commitment_id is not None
                    else None
                )
                version_mismatch = (
                    current is not None
                    and expected_version is not None
                    and current.version != expected_version
                )

                if commitment_id is not None and current is None:
                    pending_not_found = True
                elif version_mismatch and current is not None:
                    now = self._clock()
                    rejected_history = self._record(
                        uow=uow,
                        principal_id=principal_id,
                        commitment_id=current.commitment_id,
                        action=action,
                        actor=actor,
                        outcome=TaskMutationOutcome.REJECTED,
                        before_version=current.version,
                        after_version=current.version,
                        occurred_at=now,
                        idempotency_key=idempotency_key,
                        client_context=client_context,
                    )
                    pending_conflict = CommitmentMutationReceipt(
                        history=rejected_history, commitment=current
                    )
                else:
                    proposed = change(current)  # type: ignore[arg-type]
                    now = self._clock()
                    before_version = current.version if current is not None else 0
                    if current is not None and proposed == current:
                        no_op_history = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            commitment_id=current.commitment_id,
                            action=action,
                            actor=actor,
                            outcome=TaskMutationOutcome.NO_OP,
                            before_version=before_version,
                            after_version=before_version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                        )
                        result = CommitmentMutationReceipt(
                            history=no_op_history, commitment=current
                        )
                    else:
                        applied_commitment = dataclasses.replace(
                            proposed, version=before_version + 1, updated_at=now
                        )
                        if current is None:
                            uow.commitments.insert_commitment(applied_commitment)
                        else:
                            uow.commitments.update_commitment(applied_commitment)
                        applied_history = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            commitment_id=applied_commitment.commitment_id,
                            action=action,
                            actor=actor,
                            outcome=TaskMutationOutcome.APPLIED,
                            before_version=before_version,
                            after_version=applied_commitment.version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                        )
                        result = CommitmentMutationReceipt(
                            history=applied_history, commitment=applied_commitment
                        )

        if pending_not_found:
            raise CommitmentNotFoundError(
                f"no commitment {commitment_id!r} in this principal's partition"
            )
        if pending_conflict is not None:
            raise CommitmentVersionConflictError(pending_conflict)
        if result is None:
            raise RuntimeError(
                "unreachable: _mutate exited its transaction with no receipt, conflict, or "
                "not-found"
            )
        return result

    def _record(
        self,
        *,
        uow: CommitmentManagementUnitOfWork,
        principal_id: str,
        commitment_id: str,
        action: CommitmentMutationAction,
        actor: TaskMutationActor,
        outcome: TaskMutationOutcome,
        before_version: int,
        after_version: int,
        occurred_at: datetime,
        idempotency_key: str | None,
        client_context: str | None,
    ) -> CommitmentHistoryEntry:
        entry = CommitmentHistoryEntry(
            history_id=issue_identifier(IdKind.COMMITMENT_HISTORY),
            principal_id=principal_id,
            commitment_id=commitment_id,
            action=action,
            actor=actor,
            outcome=outcome,
            before_version=before_version,
            after_version=after_version,
            occurred_at=occurred_at,
            recorded_at=self._clock(),
            idempotency_key=idempotency_key,
            client_context=client_context,
        )
        uow.commitments.insert_history(entry)
        return entry
