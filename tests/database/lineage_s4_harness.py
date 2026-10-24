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
  natively, with a follow-up Task, for the `commitments.v2.*` tests (worker M3);
* `S4Runtime.overview` / `linked_issue` / `suspend_issue` and
  `ProgramSeeds.constraint_calendar` / `constraint` / `sync_target` /
  `sync_conflict` / `close_issue` / `legacy_issue_link` -- the
  `programs.overview` facts (worker M4): Issues linked natively, a legacy
  Issue link and a closed Issue by SQL under `session_replication_role =
  replica` (as only SQL can seed them, S4 section 10), Constraints on a
  Project's own calendar, sync targets with a last run in any persisted state;
* `S4Runtime.cycle` / `report` / `commit_report` / `research` / `manifest` /
  `stored_manifest` and `program_reference` -- the Intelligence pipeline and
  its report manifests (worker M5, section 7.4): a cycle, artifacts of every
  stage committed through `reports.commit`, the `reports.manifest` answer and
  the stored row, and the section 5.4 Program reference block of an overview
  answer.

Every identity here is synthetic.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from itertools import count
from typing import Any, Final

from sqlalchemy import Engine, text

from my_pa.application.commands import (
    AddIssueProjectLink,
    BeginIntelligenceCycle,
    CloseCommitment,
    CommitIntelligenceArtifact,
    CreateCommitment,
    CreateSituation,
    CreateTask,
    ReadCommitment,
    ReadIssue,
    ReadProgramOverview,
    ReadReportManifest,
    ResolveProgramMembers,
    UpdateIssue,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.intelligence.catalog import (
    ARTIFACT_KIND_FOR_STAGE,
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    SourceLaneId,
)
from my_pa.domain.program.vocabulary import PROGRAM_REFERENCE_BLOCK_KEY
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.domain.task.role import TaskRole
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
    SqlConstraintManagementRepository,
)
from my_pa.infrastructure.persistence.program_reads import SqlAlchemyProgramReadUnitOfWork
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.lineage_issue_harness import LIMITS, PRINCIPAL
from tests.database.lineage_record_harness import capture
from tests.database.lineage_s2_harness import GATEWAY, REVIEW_DECISION
from tests.database.lineage_s3_read_harness import S3ReadRuntime
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

__all__ = [
    "FOCUS",
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

#: The focus area and source lane of every S4 report test (synthetic).
FOCUS: Final = FocusAreaId.PROJECT_PROGRAM_PULSE
LANE: Final = SourceLaneId.MY_PA

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

    # --- programs.overview (worker M4, section 7.2) ---------------------------

    def overview(self, *program_entity_ids: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """`programs.overview`, which must succeed."""
        return self.ok(ReadProgramOverview(program_entity_ids=program_entity_ids), **kwargs)

    def overview_refused(self, *program_entity_ids: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """`programs.overview`, which must be refused: the error document."""
        return self.refused(ReadProgramOverview(program_entity_ids=program_entity_ids), **kwargs)

    def linked_issue(self, key: str, *project_ids: str, principal_id: str = PRINCIPAL) -> str:
        """A new Issue linked natively (`issues.project_links.add`) to each Project."""
        issue_id = self.issue(f"s4-{key}", principal_id=principal_id)
        for index, project_id in enumerate(project_ids):
            self.ok(
                AddIssueProjectLink(
                    issue_id=issue_id,
                    project_id=project_id,
                    expected_membership_revision=0,
                    idempotency_key=f"s4-plink-{key}-{index}",
                ),
                surface=GATEWAY,
                principal_id=principal_id,
            )
        return issue_id

    def suspend_issue(self, issue_id: str, key: str, *, principal_id: str = PRINCIPAL) -> None:
        """`issues.update` to `suspended` (an outstanding, not closed, Issue)."""
        current = self.ok(ReadIssue(issue_id=issue_id), principal_id=principal_id)["issue"]
        self.ok(
            UpdateIssue(
                issue_id=issue_id,
                expected_version=int(current["version"]),
                idempotency_key=f"s4-suspend-{key}",
                state="suspended",
            ),
            surface=GATEWAY,
            principal_id=principal_id,
        )

    # --- the Intelligence pipeline and its manifests (worker M5, section 7.4) ---

    def cycle(self, key: str, *, principal_id: str = PRINCIPAL) -> str:
        """`reports.begin_cycle` for a synthetic morning cycle: its `cycle_run_id`."""
        written = self.ok(
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date="2026-10-24",
                idempotency_key=f"s4-cycle-{key}",
            ),
            principal_id=principal_id,
        )
        return str(written["cycle_run_id"])

    @staticmethod
    def report(
        cycle_run_id: str,
        stage: IntelligenceStage,
        key: str,
        *,
        dependencies: tuple[str, ...] = (),
        structured_content: dict[str, object] | None = None,
        provenance: tuple[dict[str, object], ...] = (),
        body: str = "Synthetic s4 report body",
        title: str = "Synthetic s4 report",
        supersedes: str | None = None,
        automation_run_id: str | None = None,
        artifact_state: ArtifactState = ArtifactState.PARTIAL,
    ) -> CommitIntelligenceArtifact:
        """A `reports.commit` request of `stage` (focus `FOCUS`; a researcher on `LANE`)."""
        return CommitIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=stage,
            artifact_kind=ARTIFACT_KIND_FOR_STAGE[stage],
            producer_task_id=f"s4-{stage.value}",
            producer_task_name=title,
            automation_platform="abacus_chatllm",
            report_date="2026-10-24",
            title=title,
            body_markdown=body,
            artifact_state=artifact_state,
            schema_version="1",
            idempotency_key=f"s4-report-{key}",
            focus_area_id=None if stage is IntelligenceStage.MORNING_BRIEF else FOCUS,
            source_lane=LANE if stage is IntelligenceStage.RESEARCHER else None,
            automation_run_id=automation_run_id,
            structured_content=structured_content,
            dependency_report_ids=dependencies,
            provenance=provenance,
            supersedes_artifact_id=supersedes,
        )

    def commit_report(self, command: CommitIntelligenceArtifact, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """`reports.commit`, which must succeed: the commit answer."""
        return self.ok(command, **kwargs)

    def research(self, cycle_run_id: str, key: str, *, principal_id: str = PRINCIPAL) -> str:
        """A collector and one researcher over it: the researcher's `report_id`."""
        collector = self.ok(
            self.report(cycle_run_id, IntelligenceStage.COLLECTOR, f"{key}-collector"),
            principal_id=principal_id,
        )
        researcher = self.ok(
            self.report(
                cycle_run_id,
                IntelligenceStage.RESEARCHER,
                f"{key}-researcher",
                dependencies=(str(collector["report_id"]),),
            ),
            principal_id=principal_id,
        )
        return str(researcher["report_id"])

    def manifest(self, report_id: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """`reports.manifest`, which must succeed."""
        return self.ok(ReadReportManifest(report_id=report_id), **kwargs)

    def stored_manifest(self, report_id: str) -> dict[str, Any] | None:
        """The stored manifest row of `report_id`, by SQL (`None`: no row)."""
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM knowledge.intelligence_artifact_manifests "
                        "WHERE artifact_id = :artifact_id"
                    ),
                    {"artifact_id": report_id},
                )
                .mappings()
                .first()
            )
        return None if row is None else dict(row)

    def make_legacy(self, report_id: str) -> None:
        """Remove `report_id`'s manifest, as an artifact committed before the S4 revision has none.

        Under `session_replication_role = replica` (synthetic database only):
        the append-only trigger does not fire there, and nothing else is touched.
        """
        with self.engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "DELETE FROM knowledge.intelligence_artifact_manifests "
                    "WHERE artifact_id = :artifact_id"
                ),
                {"artifact_id": report_id},
            )

    @staticmethod
    def program_reference(overview: dict[str, Any], *program_entity_ids: str) -> dict[str, object]:
        """The section 5.4 block of an overview answer, under its reserved key."""
        return {
            PROGRAM_REFERENCE_BLOCK_KEY: {
                "block_schema_version": 1,
                "program_entity_ids": list(program_entity_ids),
                "overview_sha256": overview["overview_sha256"],
                "source_cutoff_at": overview["source_cutoff_at"],
            }
        }

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

    # --- the overview's Issue, Constraint and sync facts (worker M4) -----------

    def close_issue(self, issue_id: str) -> None:
        """Mark an Issue `closed` by SQL (replica mode: synthetic database only).

        The native close needs a satisfied closure gate; the overview reads
        only the Issue's `state`, so a closed Issue is seeded directly.
        """
        with self._engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "UPDATE knowledge.situations SET state = 'closed', closed_at = :t0 "
                    "WHERE situation_id = :issue_id"
                ),
                {"t0": T0, "issue_id": issue_id},
            )

    def legacy_issue_link(
        self, project_id: str, issue_id: str, *, principal_id: str = PRINCIPAL
    ) -> None:
        """An Issue `project_situations` row with no membership event (S1 section 12 row 3).

        Seeded under `session_replication_role = replica`, as S4 section 10
        states: only a pre-S1 row has this shape.
        """
        with self._engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "INSERT INTO knowledge.project_situations (project_situation_id, project_id, "
                    "situation_id, principal_id, linked_at) VALUES (:link_id, :project_id, "
                    ":issue_id, :principal_id, :t0)"
                ),
                {
                    "link_id": issue_identifier(IdKind.PROJECT_SITUATION),
                    "project_id": project_id,
                    "issue_id": issue_id,
                    "principal_id": principal_id,
                    "t0": T0,
                },
            )

    def constraint_calendar(
        self, project_id: str, timezone_name: str = "UTC", *, principal_id: str = PRINCIPAL
    ) -> str:
        """The Project's Constraint settings (its own calendar) and one Category: its id."""
        category_id = issue_identifier(IdKind.CONSTRAINT_CATEGORY)
        with self._engine.begin() as connection:
            repository = SqlConstraintManagementRepository(connection)
            repository.insert_project_settings(
                principal_id,
                ConstraintProjectSettings(
                    principal_id=principal_id,
                    project_id=project_id,
                    timezone_name=timezone_name,
                    version=1,
                    created_at=T0,
                    updated_at=T0,
                ),
            )
            repository.insert_category(
                principal_id,
                ConstraintCategory(
                    category_id=category_id,
                    principal_id=principal_id,
                    project_id=project_id,
                    prefix=f"P{next(_ORDINALS):05d}",
                    title="Synthetic category",
                    state=ConstraintCategoryState.ACTIVE,
                    created_at=T0,
                    updated_at=T0,
                    display_order=1,
                ),
            )
        return category_id

    def constraint(
        self,
        project_id: str,
        category_id: str,
        *,
        due_date: date | None,
        state: ConstraintLifecycleState = ConstraintLifecycleState.IDENTIFIED,
        in_my_court: bool = True,
        principal_id: str = PRINCIPAL,
    ) -> str:
        """One Constraint of `project_id` (published unless a draft); its id."""
        constraint_id = issue_identifier(IdKind.PROJECT_CONSTRAINT)
        draft = state is ConstraintLifecycleState.DRAFT
        bic = (PartyRef(kind=PartyKind.PRINCIPAL),) if in_my_court else ()
        with self._engine.begin() as connection:
            SqlConstraintManagementRepository(connection).insert_constraint(
                principal_id,
                ProjectConstraint(
                    constraint_id=constraint_id,
                    principal_id=principal_id,
                    lifecycle_state=state,
                    origin=ConstraintOrigin.PRODUCT,
                    record_quality=ConstraintRecordQuality.NORMAL,
                    created_at=T0,
                    updated_at=T0,
                    version=1,
                    project_id=project_id,
                    category_id=category_id,
                    constraint_code=None if draft else f"1.{next(_ORDINALS):04d}",
                    description="Synthetic constraint",
                    date_identified=date(2026, 1, 2),
                    due_date=due_date,
                    bic=bic,
                    published_at=None if draft else T0,
                ),
            )
        return constraint_id

    def sync_target(
        self,
        project_id: str,
        *,
        verified: bool = True,
        last_run_state: str | None = "in_sync",
        principal_id: str = PRINCIPAL,
    ) -> tuple[str, str | None]:
        """A sync target of `project_id` with a last run in `last_run_state`: `(target, run)`.

        `verified=False` leaves `last_verified_at` null; `last_run_state=None`
        records no run (`last_run_id` null).
        """
        target_id = issue_identifier(IdKind.CONSTRAINT_SYNC_TARGET)
        run_id = None if last_run_state is None else issue_identifier(IdKind.CONSTRAINT_SYNC_RUN)
        digest = hashlib.sha256(target_id.encode("ascii")).hexdigest()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.constraint_sync_targets (sync_target_id, principal_id, "
                    "project_id, external_kind, external_identity, normalization_contract_version, "
                    "last_verified_at, last_run_id, version, created_at, updated_at) VALUES "
                    "(:target_id, :principal_id, :project_id, 'excel_workbook', :identity, 'v1', "
                    ":verified_at, :run_id, 1, :t0, :t0)"
                ),
                {
                    "target_id": target_id,
                    "principal_id": principal_id,
                    "project_id": project_id,
                    "identity": f"synthetic-workbook-{target_id}",
                    "verified_at": T0 if verified else None,
                    "run_id": run_id,
                    "t0": T0,
                },
            )
            if run_id is not None:
                connection.execute(
                    text(
                        "INSERT INTO knowledge.constraint_sync_runs (sync_run_id, principal_id, "
                        "project_id, sync_target_id, state, sync_state, lease_token, "
                        "preview_lease_until, preview_idempotency_key, preview_request_digest, "
                        "started_at, finished_at, outcome, created_at, updated_at) VALUES "
                        "(:run_id, :principal_id, :project_id, :target_id, 'applied', :sync_state, "
                        ":digest, :t0, :key, :digest, :t0, :t0, 'applied', :t0, :t0)"
                    ),
                    {
                        "run_id": run_id,
                        "principal_id": principal_id,
                        "project_id": project_id,
                        "target_id": target_id,
                        "sync_state": last_run_state,
                        "digest": digest,
                        "key": f"synthetic_{run_id}",
                        "t0": T0,
                    },
                )
        return target_id, run_id

    def sync_conflict(
        self,
        project_id: str,
        target_id: str,
        run_id: str,
        constraint_id: str,
        *,
        principal_id: str = PRINCIPAL,
    ) -> None:
        """An open sync conflict on one Constraint of `project_id`."""
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.constraint_sync_conflicts (sync_conflict_id, "
                    "principal_id, project_id, sync_target_id, constraint_id, sync_run_id, "
                    "conflict_kind, field_names, state, created_at) VALUES (:conflict_id, "
                    ":principal_id, :project_id, :target_id, :constraint_id, :run_id, "
                    "'both_changed', '[\"description\"]'::jsonb, 'open', :t0)"
                ),
                {
                    "conflict_id": issue_identifier(IdKind.CONSTRAINT_SYNC_CONFLICT),
                    "principal_id": principal_id,
                    "project_id": project_id,
                    "target_id": target_id,
                    "constraint_id": constraint_id,
                    "run_id": run_id,
                    "t0": T0,
                },
            )


#: Distinct synthetic Category prefixes and Constraint codes.
_ORDINALS: Final = count(1)


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
