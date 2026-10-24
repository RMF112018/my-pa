"""The Program metric reads (record lineage S4 contract sections 3.2, 3.3 and 6.3, WP-04B).

Four statements, each Principal-scoped on every table reference it makes and
each one statement whatever the number of Projects (the section 6.3 statement
plan): the Commitment aggregates grouped by Project, the outstanding Issue
`(project_id, issue_id)` pairs whose latest link event is active, the legacy
Issue links per Project (Issue `project_situations` rows with no membership
event, split by the Issue's state), and the sync targets with their last run's
outcome and the Project's open sync conflicts.

They run on the Program read unit of work's connection -- one `REPEATABLE
READ, READ ONLY` snapshot (`program_reads.py`) -- and never write. A statement
cancelled by its `statement_timeout` raises `ProgramReadUnavailableError`
(`unavailable`). They fetch counts and rows and decide nothing: the
reportability rule is the pure `domain.program.reportability`.

**Commitment Project attribution is the native `commitments.project_id`**
(section 3.2) inside this Principal's partition: another Principal's
Commitment storing one of this Principal's Project ids is never counted
(R4-F06). Raw SQL, as `program_membership.py`: the principal-partition guard
(claim 3) checks that every `knowledge.` table reference states its own
`principal_id` against a bound parameter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

from my_pa.contracts.ports import ProgramMetricsRepository, ProgramSyncFacts
from my_pa.domain.program.reportability import MetricId, SyncTarget
from my_pa.infrastructure.persistence.program_membership import program_statement

__all__ = ["SqlProgramMetricsRepository"]

_IDS = ARRAY(Text)

#: Section 3.2: the 7 Commitment metrics per Project in one aggregate. Open or
#: closed and accepted or proposed are the native `state` / `evidence_state`;
#: overdue compares the instant `due_at` with the snapshot's cutoff.
_COMMITMENT_COUNTS: Final = text(
    "SELECT c.project_id,"
    " count(*) FILTER (WHERE c.state = 'open' AND c.evidence_state = 'accepted')"
    " AS commitment_open_accepted,"
    " count(*) FILTER (WHERE c.state = 'open' AND c.evidence_state = 'proposed')"
    " AS commitment_open_proposed,"
    " count(*) FILTER (WHERE c.state = 'closed' AND c.evidence_state = 'proposed')"
    " AS commitment_closed_proposed,"
    " count(*) FILTER (WHERE c.state = 'open' AND c.evidence_state = 'accepted'"
    " AND c.due_at < :cutoff) AS commitment_overdue_accepted,"
    " count(*) FILTER (WHERE c.state = 'open' AND c.evidence_state = 'proposed'"
    " AND c.due_at < :cutoff) AS commitment_overdue_proposed,"
    " count(*) FILTER (WHERE c.state = 'open' AND c.evidence_state = 'accepted'"
    " AND c.due_at IS NULL) AS commitment_unscheduled_accepted,"
    " count(*) FILTER (WHERE c.state = 'open' AND c.evidence_state = 'proposed'"
    " AND c.due_at IS NULL) AS commitment_unscheduled_proposed"
    " FROM knowledge.commitments c"
    " WHERE c.principal_id = :principal_id AND c.state IN ('open', 'closed')"
    " AND c.project_id = ANY(:project_ids)"
    " GROUP BY c.project_id"
).bindparams(
    bindparam("principal_id"),
    bindparam("project_ids", type_=_IDS),
    bindparam("cutoff"),
)

#: Section 3.2 `issue_outstanding`: the `(project, issue)` pairs whose latest
#: membership event is `active`, of an Issue that is `open`, `active` or
#: `suspended` (a suspended Issue is not closed, so it is outstanding).
_OUTSTANDING_ISSUE_LINKS: Final = text(
    "SELECT latest.project_id, latest.issue_id FROM ("
    " SELECT DISTINCT ON (m.project_id, m.issue_id) m.project_id, m.issue_id, m.state"
    " FROM knowledge.issue_project_membership_events m"
    " WHERE m.principal_id = :principal_id AND m.project_id = ANY(:project_ids)"
    " ORDER BY m.project_id, m.issue_id, m.revision_no DESC"
    ") latest JOIN knowledge.situations s"
    " ON s.principal_id = :principal_id AND s.situation_id = latest.issue_id"
    " WHERE latest.state = 'active' AND s.kind = 'issue_workstream'"
    " AND s.state IN ('open', 'active', 'suspended')"
    ' ORDER BY latest.project_id COLLATE "C", latest.issue_id COLLATE "C"'
).bindparams(bindparam("principal_id"), bindparam("project_ids", type_=_IDS))

#: Section 3.3 (R4-F02, R4-F16): Issue-kind `project_situations` rows with no
#: membership event for their triplet, per Project, split by the Issue's state.
_LEGACY_ISSUE_LINKS: Final = text(
    "SELECT ps.project_id,"
    " count(*) FILTER (WHERE s.state IN ('open', 'active', 'suspended')) AS outstanding,"
    " count(*) FILTER (WHERE s.state = 'closed') AS closed"
    " FROM knowledge.project_situations ps JOIN knowledge.situations s"
    " ON s.principal_id = :principal_id AND s.situation_id = ps.situation_id"
    " WHERE ps.principal_id = :principal_id AND ps.project_id = ANY(:project_ids)"
    " AND s.kind = 'issue_workstream'"
    " AND NOT EXISTS (SELECT 1 FROM knowledge.issue_project_membership_events m"
    " WHERE m.principal_id = :principal_id AND m.project_id = ps.project_id"
    " AND m.issue_id = ps.situation_id)"
    " GROUP BY ps.project_id"
).bindparams(bindparam("principal_id"), bindparam("project_ids", type_=_IDS))

#: Section 3.3 (R4-F01): every sync target of each requested Project with the
#: `sync_state` of the run its `last_run_id` names (a run in flight is not
#: consulted), and the Project's open sync conflicts -- one row per target, or
#: one row with no target.
_SYNC_FACTS: Final = text(
    "SELECT wanted.project_id, t.sync_target_id, t.last_verified_at, t.last_run_id,"
    " r.sync_state AS last_run_sync_state,"
    " (SELECT count(*) FROM knowledge.constraint_sync_conflicts c"
    " WHERE c.principal_id = :principal_id AND c.project_id = wanted.project_id"
    " AND c.state = 'open' AND c.constraint_id IS NOT NULL) AS open_conflicts"
    " FROM unnest(:project_ids) AS wanted (project_id)"
    " LEFT JOIN knowledge.constraint_sync_targets t"
    " ON t.principal_id = :principal_id AND t.project_id = wanted.project_id"
    " LEFT JOIN knowledge.constraint_sync_runs r"
    " ON r.principal_id = :principal_id AND r.project_id = t.project_id"
    " AND r.sync_target_id = t.sync_target_id AND r.sync_run_id = t.last_run_id"
    ' ORDER BY wanted.project_id COLLATE "C", t.sync_target_id COLLATE "C"'
).bindparams(bindparam("principal_id"), bindparam("project_ids", type_=_IDS))

#: The 7 Commitment metric columns, in catalogue order.
_COMMITMENT_COLUMNS: Final = (
    MetricId.COMMITMENT_OPEN_ACCEPTED,
    MetricId.COMMITMENT_OPEN_PROPOSED,
    MetricId.COMMITMENT_CLOSED_PROPOSED,
    MetricId.COMMITMENT_OVERDUE_ACCEPTED,
    MetricId.COMMITMENT_OVERDUE_PROPOSED,
    MetricId.COMMITMENT_UNSCHEDULED_ACCEPTED,
    MetricId.COMMITMENT_UNSCHEDULED_PROPOSED,
)


class SqlProgramMetricsRepository(ProgramMetricsRepository):
    """`ProgramMetricsRepository` over one Program read snapshot connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def commitment_counts(
        self, principal_id: str, project_ids: Sequence[str], *, cutoff: datetime
    ) -> Mapping[str, Mapping[MetricId, int]]:
        if not project_ids:
            return {}
        rows = program_statement(
            lambda: self._connection.execute(
                _COMMITMENT_COUNTS,
                {"principal_id": principal_id, "project_ids": list(project_ids), "cutoff": cutoff},
            ).all()
        )
        return {
            row.project_id: {
                metric: int(row._mapping[metric.value]) for metric in _COMMITMENT_COLUMNS
            }
            for row in rows
        }

    def outstanding_issue_links(
        self, principal_id: str, project_ids: Sequence[str]
    ) -> tuple[tuple[str, str], ...]:
        if not project_ids:
            return ()
        rows = program_statement(
            lambda: self._connection.execute(
                _OUTSTANDING_ISSUE_LINKS,
                {"principal_id": principal_id, "project_ids": list(project_ids)},
            ).all()
        )
        return tuple((row.project_id, row.issue_id) for row in rows)

    def legacy_issue_links(
        self, principal_id: str, project_ids: Sequence[str]
    ) -> Mapping[str, tuple[int, int]]:
        if not project_ids:
            return {}
        rows = program_statement(
            lambda: self._connection.execute(
                _LEGACY_ISSUE_LINKS,
                {"principal_id": principal_id, "project_ids": list(project_ids)},
            ).all()
        )
        return {row.project_id: (int(row.outstanding), int(row.closed)) for row in rows}

    def sync_facts(
        self, principal_id: str, project_ids: Sequence[str]
    ) -> Mapping[str, ProgramSyncFacts]:
        if not project_ids:
            return {}
        rows = program_statement(
            lambda: self._connection.execute(
                _SYNC_FACTS,
                {"principal_id": principal_id, "project_ids": sorted(set(project_ids))},
            ).all()
        )
        targets: dict[str, list[SyncTarget]] = {}
        conflicts: dict[str, int] = {}
        verified: dict[str, datetime] = {}
        for row in rows:
            project = row.project_id
            targets.setdefault(project, [])
            conflicts[project] = int(row.open_conflicts)
            if row.sync_target_id is None:
                continue
            targets[project].append(
                SyncTarget(
                    last_verified_at=row.last_verified_at,
                    last_run_id=row.last_run_id,
                    last_run_sync_state=row.last_run_sync_state,
                )
            )
            moment = row.last_verified_at
            if moment is not None:
                verified[project] = max(moment, verified.get(project, moment))
        return {
            project: ProgramSyncFacts(
                targets=tuple(found),
                open_conflicts=conflicts[project],
                last_verified_at=verified.get(project),
            )
            for project, found in targets.items()
        }
