"""Shared seeds for the record lineage S2 close, reopen and readiness tests.

A helper module, not a test module: pytest does not collect it. It extends the
S1 harnesses (`lineage_issue_harness.LineageRuntime`,
`lineage_record_harness`) with what the closure gate needs: the Constraint
plane composed beside the general unit of work, Work and Constraint members
driven to their native terminal states through their own v1 capabilities, and
the S2 requests (`issues.close`, `issues.reopen`, `issues.memberships.correct`,
and the handoff and composite requests `handoff`, `work_task`,
`work_commitment`).

Every identity and every body here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

from sqlalchemy import Engine, func, insert, select

from my_pa.application.commands import (
    CloseCommitment,
    CloseConstraint,
    CloseIssue,
    CorrectIssueMembership,
    CreateCommitment,
    CreateConstraintCategory,
    CreateIssueWorkCommitment,
    CreateIssueWorkTask,
    CreatePublishedConstraint,
    CreateTask,
    ReadCommitment,
    ReadConstraint,
    ReadIssue,
    ReadIssueClosureReadiness,
    ReadTask,
    RecordIssueHandoff,
    ReopenIssue,
    TransitionTask,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskOriginKind
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import SqlAlchemyConstraintManagementUnitOfWork
from my_pa.infrastructure.persistence.tables import (
    issue_responsibility_events,
    issue_revision_evidence,
    lineage_write_request_links,
    projects,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.lineage_issue_harness import LIMITS, PRINCIPAL, LineageRuntime
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    all_lineage_counts,
    capture,
    capture_anchor,
    meeting,
    membership,
    note_anchor,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

__all__ = [
    "GATEWAY",
    "REVIEW_DECISION",
    "S2Runtime",
    "all_s2_counts",
    "close",
    "correct",
    "handoff",
    "reopen",
    "resolution_anchor",
    "work_commitment",
    "work_task",
]

_T0: Final = datetime(2026, 9, 2, 15, tzinfo=UTC)
#: A synthetic review decision: the only route a v1 Commitment has to
#: `accepted` (S2 contract section 12, D-05, D-17).
REVIEW_DECISION: Final = "rdec_lineages2review0001"

_S2_TABLES: Final = (
    issue_revision_evidence,
    issue_responsibility_events,
    lineage_write_request_links,
)


def all_s2_counts(engine: Engine) -> dict[str, int]:
    """Row counts of every S1 table and the three S2 tables."""
    counts = dict(all_lineage_counts(engine))
    with engine.connect() as connection:
        for table in _S2_TABLES:
            counts[table.name] = int(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
            )
    return counts


class S2Runtime(LineageRuntime):
    """`LineageRuntime` with the Constraint plane composed as well."""

    def __init__(self, url: str, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(url, **kwargs)
        audit = SqlAlchemyAuditSink(self.audit_engine)
        engine = self.engine

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(engine, audit=audit, relationship_memory_enabled=True)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(engine),
            commitment_management_unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(
                engine
            ),
            constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
                engine
            ),
            relationship_intelligence_enabled=True,
            relationship_intelligence_writes_enabled=True,
            relationship_memory_enabled=True,
            lineage_enabled=kwargs.get("lineage_enabled", True),
        )
        self._categories: dict[str, str] = {}

    # --- native members ------------------------------------------------------

    def task(self, key: str, *, principal_id: str = PRINCIPAL) -> str:
        """A direct-Principal Task: natively `accepted` with no review decision."""
        written = self.ok(
            CreateTask(
                title=f"Synthetic task {key}",
                idempotency_key=f"s2-tsk-{key}",
                origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            ),
            principal_id=principal_id,
        )
        return str(written["task"]["task_id"])

    def task_version(self, task_id: str, *, principal_id: str = PRINCIPAL) -> int:
        return int(self.ok(ReadTask(task_id=task_id), principal_id=principal_id)["task"]["version"])

    def transition(
        self, task_id: str, to_state: TaskLifecycleState, key: str, *, principal_id: str = PRINCIPAL
    ) -> int:
        """Move a Task natively; its new `version`."""
        written = self.ok(
            TransitionTask(
                task_id=task_id,
                to_state=to_state,
                expected_version=self.task_version(task_id, principal_id=principal_id),
                idempotency_key=f"s2-tsk-move-{key}",
            ),
            principal_id=principal_id,
        )
        return int(written["task"]["version"])

    def commitment(self, key: str, *, accepted: bool = True, principal_id: str = PRINCIPAL) -> str:
        """A Commitment, `accepted` through the v1 review-decision field unless told not."""
        origin, _, _ = capture(self, f"s2-cmt-origin-{key}", principal_id=principal_id)
        written = self.ok(
            CreateCommitment(
                counterparty_entity_id=seed_counterparty_entity(self.engine, principal_id),
                direction=CommitmentDirection.OWED_TO_PRINCIPAL,
                summary=f"Synthetic commitment {key}",
                origin_evidence_ref=origin,
                idempotency_key=f"s2-cmt-{key}",
                accepted_by_review_decision_id=REVIEW_DECISION if accepted else None,
            ),
            principal_id=principal_id,
        )
        return str(written["commitment"]["commitment_id"])

    def close_commitment(self, commitment_id: str, key: str) -> int:
        current = self.ok(ReadCommitment(commitment_id=commitment_id))["commitment"]
        evidence, _, _ = capture(self, f"s2-cmt-closure-{key}")
        written = self.ok(
            CloseCommitment(
                commitment_id=commitment_id,
                expected_version=int(current["version"]),
                closure_evidence_ref=evidence,
                idempotency_key=f"s2-cmt-close-{key}",
            )
        )
        return int(written["commitment"]["version"])

    def project_with_constraints(self, key: str) -> str:
        """A Project with Constraint settings and one category, seeded natively."""
        project_id = self.project(key)
        with SqlAlchemyConstraintManagementUnitOfWork(self.engine) as uow:
            uow.constraints.insert_project_settings(
                PRINCIPAL,
                ConstraintProjectSettings(
                    principal_id=PRINCIPAL,
                    project_id=project_id,
                    timezone_name="UTC",
                    version=1,
                    created_at=_T0,
                    updated_at=_T0,
                ),
            )
        written = self.ok(
            CreateConstraintCategory(
                project_id=project_id, code_segment="LIN", title=f"Lineage {key}"
            )
        )
        self._categories[project_id] = str(written["category"]["category_id"])
        return project_id

    def constraint(self, project_id: str, key: str) -> str:
        """A published Constraint (`identified`) in `project_id`."""
        written = self.ok(
            CreatePublishedConstraint(
                project_id=project_id,
                category_id=self._categories[project_id],
                description=f"Synthetic constraint {key}",
                date_identified=date(2026, 9, 2),
                due_date=date(2026, 9, 30),
                bic=(PartyRef(kind=PartyKind.PRINCIPAL),),
                responsible=(PartyRef(kind=PartyKind.PRINCIPAL),),
                idempotency_key=f"s2-cst-{key}",
            )
        )
        return str(written["constraint"]["constraint_id"])

    def constraint_version(self, constraint_id: str) -> int:
        return int(self.ok(ReadConstraint(constraint_id=constraint_id))["constraint"]["version"])

    def close_constraint(self, constraint_id: str, key: str) -> int:
        written = self.ok(
            CloseConstraint(
                constraint_id=constraint_id,
                expected_version=self.constraint_version(constraint_id),
                completion_date=date(2026, 9, 20),
                closure_commentary="Synthetic resolution.",
                idempotency_key=f"s2-cst-close-{key}",
            )
        )
        return int(written["constraint"]["version"])

    # --- lineage ---------------------------------------------------------------

    def member(self, issue_id: str, family: str, record_id: str, key: str, role: str) -> str:
        written = self.ok(membership(issue_id, family, record_id, key, role=role), surface=GATEWAY)
        return str(written["membership"]["link_id"])

    def issue_version(self, issue_id: str) -> int:
        return int(self.ok(ReadIssue(issue_id=issue_id))["issue"]["version"])

    def readiness(self, issue_id: str) -> dict[str, Any]:
        return self.ok(ReadIssueClosureReadiness(issue_id=issue_id))

    def commitment_view(self, commitment_id: str, *, principal_id: str = PRINCIPAL) -> Any:  # noqa: ANN401
        """`commitments.read`'s Commitment view."""
        return self.ok(ReadCommitment(commitment_id=commitment_id), principal_id=principal_id)[
            "commitment"
        ]

    def handoff_anchor(self, key: str) -> dict[str, object]:
        """An exact note anchor with role `handoff`."""
        meeting_id, note_id = meeting(self, key)
        return resolution_anchor(meeting_id, note_id, role="handoff")

    def evidence_source(self, key: str) -> tuple[str, str, dict[str, object]]:
        """A Meeting note and an exact `resolution` anchor on it."""
        meeting_id, note_id = meeting(self, key)
        return meeting_id, note_id, resolution_anchor(meeting_id, note_id)


def resolution_anchor(
    meeting_id: str,
    note_id: str,
    *,
    role: str = "resolution",
    passage: str | None = "façade survey",
) -> dict[str, object]:
    """An exact note anchor with `role` (default `resolution`)."""
    return note_anchor(meeting_id, note_id, NOTE_BODY, role=role, passage=passage)


def capture_resolution(capture_id: str, version_id: str) -> dict[str, object]:
    return capture_anchor(capture_id, version_id, NOTE_BODY, role="resolution")


def correct(
    link_id: str,
    revision: int,
    key: str,
    anchors: tuple[dict[str, object], ...],
    *,
    reason: str = "Resolution evidence recorded.",
) -> CorrectIssueMembership:
    return CorrectIssueMembership(
        link_id=link_id,
        expected_revision=revision,
        idempotency_key=f"s2-correct-{key}",
        reason=reason,
        evidence_anchors=anchors,
    )


def close(
    issue_id: str,
    version: int,
    key: str,
    anchors: tuple[dict[str, object], ...],
    *,
    outcome: str = "Resolved.",
) -> CloseIssue:
    return CloseIssue(
        issue_id=issue_id,
        expected_version=version,
        idempotency_key=f"s2-close-{key}",
        outcome=outcome,
        closure_evidence_anchors=anchors,
    )


def reopen(
    issue_id: str,
    version: int,
    key: str,
    *,
    reason: str = "The problem recurred.",
    anchors: tuple[dict[str, object], ...] = (),
) -> ReopenIssue:
    return ReopenIssue(
        issue_id=issue_id,
        expected_version=version,
        idempotency_key=f"s2-reopen-{key}",
        reason=reason,
        evidence_anchors=anchors,
    )


def handoff(
    issue_id: str,
    commitment_id: str,
    side: str,
    effective_at: str,
    key: str,
    anchor: dict[str, object],
    *,
    reason: str = "The next action moved.",
) -> RecordIssueHandoff:
    return RecordIssueHandoff(
        issue_id=issue_id,
        commitment_id=commitment_id,
        from_side=side,
        effective_at=effective_at,
        idempotency_key=f"s2-handoff-{key}",
        reason=reason,
        evidence_anchor=anchor,
    )


def work_task(
    issue_id: str,
    key: str,
    task: dict[str, object] | None = None,
    *,
    membership_anchors: tuple[dict[str, object], ...] = (),
    intents: tuple[dict[str, object], ...] = (),
) -> CreateIssueWorkTask:
    """`issues.work.create_task`; the default Task is a direct-Principal one."""
    return CreateIssueWorkTask(
        issue_id=issue_id,
        idempotency_key=f"s2-work-task-{key}",
        task=task
        if task is not None
        else {"title": f"Synthetic task {key}", "origin_kind": "direct_principal"},
        membership_evidence_anchors=membership_anchors,
        association_intents=intents,
    )


def work_commitment(
    issue_id: str,
    key: str,
    commitment: dict[str, object],
    *,
    membership_anchors: tuple[dict[str, object], ...] = (),
    intents: tuple[dict[str, object], ...] = (),
) -> CreateIssueWorkCommitment:
    return CreateIssueWorkCommitment(
        issue_id=issue_id,
        idempotency_key=f"s2-work-commitment-{key}",
        commitment=commitment,
        membership_evidence_anchors=membership_anchors,
        association_intents=intents,
    )


def insert_project(engine: Engine, principal_id: str, project_id: str) -> None:
    """A bare Project row (for a foreign-Principal fixture)."""
    with engine.begin() as connection:
        connection.execute(
            insert(projects).values(
                project_id=project_id,
                principal_id=principal_id,
                name="Synthetic project",
                state="active",
                participants=[],
                opened_at=_T0,
                created_at=_T0,
                updated_at=_T0,
            )
        )
