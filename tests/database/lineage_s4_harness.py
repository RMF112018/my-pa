"""Shared database harness for the record lineage S4 Program-reporting tests.

A helper module, not a test module: pytest does not collect it. It extends the
S3 read harness (`lineage_s3_read_harness.S3ReadRuntime`: a real
`ApplicationService` over PostgreSQL, remote calls with an exact grant set)
with what the Program reads need:

* `S4Runtime` -- the service with `lineage_enabled` and
  `program_reporting_enabled` on and the Program read unit of work composed on
  its **own** engine (S4 contract section 6.3: `statement_timeout` 2000 ms, a
  1 s checkout timeout), as `bootstrap/gateway.py` builds it;
* `ProgramSeeds` -- the Entity graph by direct SQL: Program and Project
  Entities, bound Continuity Projects, `member_of` edges with any recorded
  window and state, and merges (a redirect, without the merge command's
  reparenting, so a test can state exactly which rows exist);
* `S4Runtime.work_commitment` / `close_work_commitment` / `follow_up` /
  `context_situation` / `store_situation` -- Commitments storing any `project_id` and
  `situation_id` (the v1 writer checks only their pattern, S4 D-16), closed
  natively, with a follow-up Task, for the `commitments.v2.*` tests (worker M3).

Every identity here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Engine, text

from my_pa.application.commands import (
    CloseCommitment,
    CreateCommitment,
    CreateSituation,
    CreateTask,
    ReadCommitment,
    ResolveProgramMembers,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.domain.task.role import TaskRole
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import SqlAlchemyConstraintManagementUnitOfWork
from my_pa.infrastructure.persistence.program_reads import SqlAlchemyProgramReadUnitOfWork
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.lineage_issue_harness import LIMITS, PRINCIPAL
from tests.database.lineage_record_harness import capture
from tests.database.lineage_s2_harness import REVIEW_DECISION
from tests.database.lineage_s3_read_harness import S3ReadRuntime
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

__all__ = [
    "PROGRAM_STATEMENT_TIMEOUT_MS",
    "T0",
    "ProgramSeeds",
    "S4Runtime",
    "membership_tables",
]

#: S4 section 6.3: the Program engine's per-statement budget.
PROGRAM_STATEMENT_TIMEOUT_MS: Final = 2000
#: S4 section 6.3: the Program engine's checkout timeout.
PROGRAM_POOL_TIMEOUT_SECONDS: Final = 1
#: A fixed instant well before any snapshot a test takes.
T0: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: The tables a Program membership read reads (and must never write).
_MEMBERSHIP_TABLES: Final = (
    "entities",
    "entity_relationships",
    "project_entity_links",
    "projects",
)


class S4Runtime(S3ReadRuntime):
    """`S3ReadRuntime` with the Program-reporting switch and the Program read pool."""

    def __init__(
        self,
        url: str,
        *,
        lineage_enabled: bool = True,
        program_reporting_enabled: bool = True,
        relationship_intelligence_enabled: bool = True,
        compose_program_reads: bool = True,
        compose_constraints: bool = True,
    ) -> None:
        super().__init__(url, lineage_enabled=lineage_enabled)
        self.program_engine = create_database_engine(
            url,
            statement_timeout_ms=PROGRAM_STATEMENT_TIMEOUT_MS,
            pool_timeout_seconds=PROGRAM_POOL_TIMEOUT_SECONDS,
        )
        audit = SqlAlchemyAuditSink(self.audit_engine)
        engine = self.engine
        program_engine = self.program_engine

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(engine, audit=audit, relationship_memory_enabled=True)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(engine),
            commitment_management_unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(
                engine
            ),
            constraint_management_unit_of_work=(
                (lambda: SqlAlchemyConstraintManagementUnitOfWork(engine))
                if compose_constraints
                else None
            ),
            relationship_intelligence_enabled=relationship_intelligence_enabled,
            relationship_intelligence_writes_enabled=relationship_intelligence_enabled,
            relationship_memory_enabled=True,
            lineage_enabled=lineage_enabled,
            program_reporting_enabled=program_reporting_enabled,
            program_read_unit_of_work=(
                (lambda: SqlAlchemyProgramReadUnitOfWork(program_engine))
                if compose_program_reads
                else None
            ),
        )
        self.seeds = ProgramSeeds(engine)

    def close(self) -> None:
        self.program_engine.dispose()
        super().close()

    def resolve(
        self,
        *program_entity_ids: str,
        valid_at: str | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """`programs.members.resolve`, which must succeed."""
        return self.ok(
            ResolveProgramMembers(program_entity_ids=program_entity_ids, valid_at=valid_at),
            **kwargs,
        )

    # --- Commitments storing references (worker M3, section 7.3) ---------------

    def work_commitment(
        self,
        key: str,
        *,
        project_id: str | None = None,
        situation_id: str | None = None,
        accepted: bool = True,
        direction: CommitmentDirection = CommitmentDirection.OWED_TO_PRINCIPAL,
        due_at: datetime | None = None,
        summary: str | None = None,
        counterparty_entity_id: str | None = None,
        principal_id: str = PRINCIPAL,
    ) -> str:
        """A v1-created Commitment storing `project_id` / `situation_id` as given.

        `accepted` through the v1 review-decision field (the only route, S2
        D-05); otherwise natively `proposed`. Each gets its own counterparty
        unless one is named.
        """
        origin, _, _ = capture(self, f"s4-cmt-origin-{key}", principal_id=principal_id)
        written = self.ok(
            CreateCommitment(
                counterparty_entity_id=(
                    counterparty_entity_id or seed_counterparty_entity(self.engine, principal_id)
                ),
                direction=direction,
                summary=summary or f"Synthetic s4 commitment {key}",
                origin_evidence_ref=origin,
                idempotency_key=f"s4-cmt-{key}",
                due_at=due_at,
                project_id=project_id,
                situation_id=situation_id,
                accepted_by_review_decision_id=REVIEW_DECISION if accepted else None,
            ),
            principal_id=principal_id,
        )
        return str(written["commitment"]["commitment_id"])

    def close_work_commitment(
        self, commitment_id: str, key: str, *, principal_id: str = PRINCIPAL
    ) -> None:
        """`commitments.close` with closure evidence."""
        current = self.ok(ReadCommitment(commitment_id=commitment_id), principal_id=principal_id)
        evidence, _, _ = capture(self, f"s4-cmt-closure-{key}", principal_id=principal_id)
        self.ok(
            CloseCommitment(
                commitment_id=commitment_id,
                expected_version=int(current["commitment"]["version"]),
                closure_evidence_ref=evidence,
                idempotency_key=f"s4-cmt-close-{key}",
            ),
            principal_id=principal_id,
        )

    def store_situation(self, commitment_id: str, situation_id: str) -> None:
        """Store `situation_id` on a Commitment by direct SQL.

        The v1 writers refuse an Issue as a Work `situation_id` (S1 section 8),
        but the column's global foreign key admits one, so a stored row may name
        an Issue (S4 section 6.2, R4-F17); only SQL can seed it.
        """
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge.commitments SET situation_id = :situation_id "
                    "WHERE commitment_id = :commitment_id"
                ),
                {"situation_id": situation_id, "commitment_id": commitment_id},
            )

    def follow_up(self, commitment_id: str, key: str, *, principal_id: str = PRINCIPAL) -> str:
        """A follow-up Task of `commitment_id` (`tasks.create` with the role)."""
        written = self.ok(
            CreateTask(
                title=f"Synthetic s4 follow-up {key}",
                idempotency_key=f"s4-tsk-{key}",
                origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
                commitment_id=commitment_id,
                role=TaskRole.FOLLOW_UP,
            ),
            principal_id=principal_id,
        )
        return str(written["task"]["task_id"])

    def context_situation(self, key: str, *, principal_id: str = PRINCIPAL) -> str:
        """A context Situation (`continuity.situations.create`)."""
        written = self.ok(
            CreateSituation(title=f"Synthetic s4 situation {key}", idempotency_key=f"s4-sit-{key}"),
            principal_id=principal_id,
        )
        return str(written["situation_id"])

    def resolve_refused(
        self,
        *program_entity_ids: str,
        valid_at: str | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """`programs.members.resolve`, which must be refused: the error document."""
        return self.refused(
            ResolveProgramMembers(program_entity_ids=program_entity_ids, valid_at=valid_at),
            **kwargs,
        )


class ProgramSeeds:
    """The Entity graph of the Program tests, written by direct SQL (synthetic only)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def entity(
        self,
        entity_type: str,
        name: str,
        *,
        status: str = "active",
        principal_id: str = PRINCIPAL,
    ) -> str:
        """An Entity of `entity_type` named `name` (canonical and display)."""
        entity_id = issue_identifier(IdKind.ENTITY)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.entities (entity_id, principal_id, entity_type, "
                    "canonical_name, display_name, status, archived_from_status) "
                    "VALUES (:entity_id, :principal_id, :entity_type, :canonical, :display, "
                    ":status, :archived_from)"
                ),
                {
                    "entity_id": entity_id,
                    "principal_id": principal_id,
                    "entity_type": entity_type,
                    "canonical": name.casefold(),
                    "display": name,
                    "status": status,
                    "archived_from": "active" if status == "archived" else None,
                },
            )
        return entity_id

    def program(self, name: str, *, principal_id: str = PRINCIPAL) -> str:
        return self.entity("program", name, principal_id=principal_id)

    def project(
        self,
        name: str,
        *,
        bound: bool = True,
        state: str = "active",
        principal_id: str = PRINCIPAL,
    ) -> tuple[str, str]:
        """A Continuity Project named `name` and its project Entity: `(project_id, entity_id)`.

        Bound by default (the forward-create shape); with `bound=False` the
        Project's bridge row is `unresolved_missing` and names no Entity, and the
        Entity exists unbound.
        """
        project_id = issue_identifier(IdKind.PROJECT)
        entity_id = self.entity("project", name, principal_id=principal_id)
        self.continuity_project(project_id, name, state=state, principal_id=principal_id)
        self.link(project_id, entity_id if bound else None, principal_id=principal_id)
        return project_id, entity_id

    def continuity_project(
        self, project_id: str, name: str, *, state: str = "active", principal_id: str = PRINCIPAL
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.projects (project_id, principal_id, name, state, "
                    "participants, opened_at, closed_at, created_at, updated_at) "
                    "VALUES (:project_id, :principal_id, :name, :state, '[]'::jsonb, :t0, "
                    ":closed_at, :t0, :t0)"
                ),
                {
                    "project_id": project_id,
                    "principal_id": principal_id,
                    "name": name,
                    "state": state,
                    "t0": T0,
                    "closed_at": T0 if state == "closed" else None,
                },
            )

    def link(
        self, project_id: str, entity_id: str | None, *, principal_id: str = PRINCIPAL
    ) -> None:
        """The Project-Entity bridge row: `bound` to `entity_id`, else `unresolved_missing`."""
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.project_entity_links (principal_id, project_id, "
                    "project_entity_id, linkage_state, created_at, updated_at) "
                    "VALUES (:principal_id, :project_id, :entity_id, :state, :t0, :t0)"
                ),
                {
                    "principal_id": principal_id,
                    "project_id": project_id,
                    "entity_id": entity_id,
                    "state": "bound" if entity_id is not None else "unresolved_missing",
                    "t0": T0,
                },
            )

    def edge(
        self,
        member: str,
        program: str,
        *,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
        state: str = "active",
        relationship_type: str = "member_of",
        principal_id: str = PRINCIPAL,
    ) -> str:
        """One directed `member_of` edge (`member -> program`) with the recorded window."""
        relationship_id = issue_identifier(IdKind.ENTITY_RELATIONSHIP)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.entity_relationships (relationship_id, "
                    "from_entity_id, to_entity_id, relationship_type, effective_from, "
                    "effective_to, state, principal_id, ended_at) VALUES (:relationship_id, "
                    ":member, :program, :relationship_type, :effective_from, :effective_to, "
                    ":state, :principal_id, :ended_at)"
                ),
                {
                    "relationship_id": relationship_id,
                    "member": member,
                    "program": program,
                    "relationship_type": relationship_type,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                    "state": state,
                    "principal_id": principal_id,
                    "ended_at": T0 if state != "active" else None,
                },
            )
        return relationship_id

    def edges(self, members: list[str], program: str, *, principal_id: str = PRINCIPAL) -> None:
        """Many active, undated `member_of` edges into `program`, in one statement."""
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.entity_relationships (relationship_id, "
                    "from_entity_id, to_entity_id, relationship_type, state, principal_id) "
                    "VALUES (:relationship_id, :member, :program, 'member_of', 'active', "
                    ":principal_id)"
                ),
                [
                    {
                        "relationship_id": issue_identifier(IdKind.ENTITY_RELATIONSHIP),
                        "member": member,
                        "program": program,
                        "principal_id": principal_id,
                    }
                    for member in members
                ],
            )

    def entities(self, entity_type: str, count: int, *, principal_id: str = PRINCIPAL) -> list[str]:
        """`count` active Entities of one type, in one statement."""
        ids = [issue_identifier(IdKind.ENTITY) for _ in range(count)]
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.entities (entity_id, principal_id, entity_type, "
                    "canonical_name, display_name) VALUES (:entity_id, :principal_id, "
                    ":entity_type, :name, :name)"
                ),
                [
                    {
                        "entity_id": entity_id,
                        "principal_id": principal_id,
                        "entity_type": entity_type,
                        "name": f"synthetic {entity_type} {index}",
                    }
                    for index, entity_id in enumerate(ids)
                ],
            )
        return ids

    def merge(self, away: str, into: str) -> None:
        """Fold `away` into `into` (a redirect only; no edge or bridge is rewritten)."""
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge.entities SET status = 'merged_redirect', "
                    "superseded_by_entity_id = :into, archived_from_status = NULL "
                    "WHERE entity_id = :away"
                ),
                {"away": away, "into": into},
            )

    def revise(
        self,
        relationship_id: str,
        *,
        effective_from: datetime | None,
        effective_to: datetime | None,
    ) -> None:
        """Rewrite an edge's recorded window in place, as `entities.relationships.revise` does."""
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge.entity_relationships SET effective_from = :effective_from, "
                    "effective_to = :effective_to, version = version + 1 "
                    "WHERE relationship_id = :relationship_id"
                ),
                {
                    "relationship_id": relationship_id,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                },
            )


def membership_tables(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table a membership read reads, in a stable order."""
    with engine.connect() as connection:
        return {
            table: [
                tuple(row)
                for row in connection.execute(
                    text(f"SELECT * FROM knowledge.{table} ORDER BY 1, 2")  # noqa: S608
                )
            ]
            for table in _MEMBERSHIP_TABLES
        }
