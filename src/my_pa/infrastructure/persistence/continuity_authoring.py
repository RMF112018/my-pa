"""User-directed continuity writes and their idempotency receipts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import (
    AuthoringConflictError,
    AuthoringReceipt,
    ContinuityAuthoringRepository,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.situation.continuity import (
    ClosureEvidenceKind,
    ContinuityAcceptanceKind,
    ContinuityEvidenceState,
    ContinuityObjectKind,
    LifecycleTransition,
    Task,
    TaskState,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.situation_repository import _append_lifecycle_event
from my_pa.infrastructure.persistence.tables import continuity_authoring_submissions, tasks


class SqlContinuityAuthoringRepository(ContinuityAuthoringRepository):
    """Idempotent Project/Situation/Task authoring on one connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def recall(self, principal_id: str, idempotency_key: str) -> AuthoringReceipt | None:
        row = self._connection.execute(
            select(*continuity_authoring_submissions.c).where(
                continuity_authoring_submissions.c.principal_id == principal_id,
                continuity_authoring_submissions.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        return AuthoringReceipt(
            capability=row.capability,
            object_id=row.object_id,
            payload_digest=row.payload_digest,
        )

    def record(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        capability: str,
        payload_digest: str,
        object_id: str,
    ) -> None:
        prior = self.recall(principal_id, idempotency_key)
        if prior is not None:
            if prior.payload_digest != payload_digest or prior.capability != capability:
                raise AuthoringConflictError
            return
        self._connection.execute(
            insert(continuity_authoring_submissions).values(
                principal_id=principal_id,
                idempotency_key=idempotency_key,
                capability=capability,
                payload_digest=payload_digest,
                object_id=object_id,
                created_at=utc_now(),
            )
        )

    def author_task(
        self,
        *,
        principal_id: str,
        title: str,
        origin_evidence_ref: str,
        project_id: str | None = None,
        situation_id: str | None = None,
        due_at: datetime | None = None,
    ) -> Task:
        task_id = issue_identifier(IdKind.TASK)
        now = utc_now()
        self._connection.execute(
            insert(tasks).values(
                task_id=task_id,
                principal_id=principal_id,
                title=title,
                state=TaskState.OPEN.value,
                evidence_state=ContinuityEvidenceState.ACCEPTED.value,
                origin_evidence_ref=origin_evidence_ref,
                project_id=project_id,
                situation_id=situation_id,
                due_at=due_at,
                opened_at=now,
                closed_at=None,
                closure_evidence_ref=None,
                accepted_by_review_decision_id=None,
                acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL.value,
                created_at=now,
                updated_at=now,
            )
        )
        _append_lifecycle_event(
            self._connection,
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.TASK,
            object_id=task_id,
            transition=LifecycleTransition.OPENED,
            evidence_kind=ClosureEvidenceKind.PRINCIPAL_STATEMENT,
            evidence_ref=origin_evidence_ref,
            occurred_at=now,
            recorded_at=now,
        )
        for context in (project_id, situation_id):
            if context is None:
                continue
            _append_lifecycle_event(
                self._connection,
                principal_id=principal_id,
                object_kind=ContinuityObjectKind.TASK,
                object_id=task_id,
                transition=LifecycleTransition.ASSOCIATED,
                evidence_kind=ClosureEvidenceKind.PRINCIPAL_STATEMENT,
                evidence_ref=f"{context}|{origin_evidence_ref}",
                occurred_at=now,
                recorded_at=now,
            )
        return Task(
            task_id=task_id,
            principal_id=principal_id,
            title=title,
            state=TaskState.OPEN,
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            origin_evidence_ref=origin_evidence_ref,
            opened_at=now,
            created_at=now,
            updated_at=now,
            due_at=due_at,
            project_id=project_id,
            situation_id=situation_id,
            acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
        )
