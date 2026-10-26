"""The Program member reads (record lineage S4 contract sections 3.1 and 6.3, WP-04A).

Four statements, each Principal-scoped on every table reference it makes and
each one statement whatever the number of Programs, edges or Projects (the
section 6.3 statement plan): the requested Programs with their redirect chains
(one recursive statement), the member edges with their members' redirect chains
(one), the bridges that redirect-resolve to the member Entities (one), and the
member Projects' states (one).

They run on the Program read unit of work's connection -- one `REPEATABLE
READ, READ ONLY` snapshot (`program_reads.py`) -- and never write. A statement
cancelled by its `statement_timeout` raises `ProgramReadUnavailableError`
(`unavailable`). The rule they feed is the pure `domain.program.membership`:
these statements fetch rows and decide nothing, and none of them matches a
name, alias, Organization, address, participation or property.

Raw SQL, because the redirect walks are recursive: the principal-partition
guard (`tests/architecture/test_principal_partition_is_reached_through_the_guard.py`,
claim 3) checks that every `knowledge.` table reference states its own
`principal_id` against a bound parameter.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Final

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import DBAPIError
from sqlalchemy.types import Text

from my_pa.contracts.ports import (
    ProgramMemberEdges,
    ProgramMembershipRepository,
    ProgramReadUnavailableError,
)
from my_pa.domain.program.membership import BridgeLink, EntityNode, MemberEdge

__all__ = ["SqlProgramMembershipRepository", "program_statement"]

#: PostgreSQL's `query_canceled`: a statement that outran `statement_timeout`.
_QUERY_CANCELED: Final = "57014"
#: The `relationship_type` of a Program membership edge.
_MEMBER_OF: Final = "member_of"

_IDS = ARRAY(Text)

#: Step 1: the named Entities of this Principal and every Entity on their
#: redirect chains, at most `max_hops` hops out. A cycle ends at the hop bound.
_ENTITY_CHAINS: Final = text(
    "WITH RECURSIVE chain (entity_id, entity_type, status, superseded_by_entity_id, depth) AS ("
    " SELECT e.entity_id, e.entity_type, e.status, e.superseded_by_entity_id, 0"
    " FROM knowledge.entities e"
    " WHERE e.principal_id = :principal_id AND e.entity_id = ANY(:entity_ids)"
    " UNION ALL"
    " SELECT n.entity_id, n.entity_type, n.status, n.superseded_by_entity_id, c.depth + 1"
    " FROM chain c JOIN knowledge.entities n"
    " ON n.principal_id = :principal_id AND n.entity_id = c.superseded_by_entity_id"
    " WHERE c.status = 'merged_redirect' AND c.depth < :max_hops"
    ") SELECT DISTINCT entity_id, entity_type, status, superseded_by_entity_id FROM chain"
).bindparams(
    bindparam("principal_id"),
    bindparam("entity_ids", type_=_IDS),
    bindparam("max_hops"),
)

#: Step 2 (with step 4's redirect chains): the `member_of` edges into the
#: resolved Programs, not superseded, ordered by the Program's request position
#: then `relationship_id COLLATE "C"`, at most `limit + 1` (the extra row only
#: names the Program in which the budget is reached). The member Entities'
#: chains ride on every row as one uncorrelated aggregate, computed once.
_MEMBER_EDGES: Final = text(
    "WITH RECURSIVE targets (entity_id, position) AS ("
    " SELECT t.entity_id, t.position"
    " FROM unnest(:program_ids) WITH ORDINALITY AS t (entity_id, position)"
    "), edges AS ("
    " SELECT r.relationship_id, r.to_entity_id, r.from_entity_id, r.effective_from,"
    " r.effective_to, r.state, targets.position"
    " FROM targets JOIN knowledge.entity_relationships r"
    " ON r.principal_id = :principal_id AND r.to_entity_id = targets.entity_id"
    " WHERE r.relationship_type = :member_of AND r.state <> 'superseded'"
    ' ORDER BY targets.position, r.relationship_id COLLATE "C"'
    " LIMIT :limit_plus_one"
    "), chain (entity_id, entity_type, status, superseded_by_entity_id, depth) AS ("
    " SELECT e.entity_id, e.entity_type, e.status, e.superseded_by_entity_id, 0"
    " FROM knowledge.entities e"
    " WHERE e.principal_id = :principal_id"
    " AND e.entity_id IN (SELECT edges.from_entity_id FROM edges)"
    " UNION ALL"
    " SELECT n.entity_id, n.entity_type, n.status, n.superseded_by_entity_id, c.depth + 1"
    " FROM chain c JOIN knowledge.entities n"
    " ON n.principal_id = :principal_id AND n.entity_id = c.superseded_by_entity_id"
    " WHERE c.status = 'merged_redirect' AND c.depth < :max_hops"
    ") SELECT edges.relationship_id, edges.to_entity_id, edges.from_entity_id,"
    " edges.effective_from, edges.effective_to, edges.state,"
    " (SELECT jsonb_agg(DISTINCT jsonb_build_array(chain.entity_id, chain.entity_type,"
    " chain.status, chain.superseded_by_entity_id)) FROM chain) AS chain"
    ' FROM edges ORDER BY edges.position, edges.relationship_id COLLATE "C"'
).bindparams(
    bindparam("principal_id"),
    bindparam("program_ids", type_=_IDS),
    bindparam("member_of"),
    bindparam("limit_plus_one"),
    bindparam("max_hops"),
)

#: Step 5: every `bound` bridge row whose Entity is a member terminal `E` or an
#: Entity merged into `E` within `max_hops` redirects (walked backwards from
#: `E`). An unresolved bridge row names no Entity and cannot be reached.
_BRIDGES: Final = text(
    "WITH RECURSIVE aliases (terminal_id, entity_id, depth) AS ("
    " SELECT t.entity_id, t.entity_id, 0 FROM unnest(:entity_ids) AS t (entity_id)"
    " UNION ALL"
    " SELECT a.terminal_id, e.entity_id, a.depth + 1"
    " FROM aliases a JOIN knowledge.entities e"
    " ON e.principal_id = :principal_id AND e.superseded_by_entity_id = a.entity_id"
    " WHERE e.status = 'merged_redirect' AND a.depth < :max_hops"
    ") SELECT DISTINCT a.terminal_id, l.project_id, l.project_entity_id"
    " FROM aliases a JOIN knowledge.project_entity_links l"
    " ON l.principal_id = :principal_id AND l.project_entity_id = a.entity_id"
    " WHERE l.linkage_state = 'bound'"
    " ORDER BY a.terminal_id, l.project_id"
).bindparams(
    bindparam("principal_id"),
    bindparam("entity_ids", type_=_IDS),
    bindparam("max_hops"),
)

#: The member Projects' own state (`project_state` in the answer).
_PROJECT_STATES: Final = text(
    "SELECT p.project_id, p.state FROM knowledge.projects p"
    " WHERE p.principal_id = :principal_id AND p.project_id = ANY(:project_ids)"
).bindparams(bindparam("principal_id"), bindparam("project_ids", type_=_IDS))


def program_statement[ResultT](statement: Callable[[], ResultT]) -> ResultT:
    """Run one Program-read statement; a statement timeout is `ProgramReadUnavailableError`.

    S4 sections 6.3 and 7.5: a statement cancelled by its timeout answers
    `unavailable`. Any other store failure propagates unchanged. The `raise` is
    outside the handler, so the driver error is not left in `__context__`.
    """
    timed_out = False
    try:
        return statement()
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != _QUERY_CANCELED:
            raise
        timed_out = True
    if timed_out:
        raise ProgramReadUnavailableError("statement_timeout")
    raise AssertionError("unreachable")  # pragma: no cover


def _node(values: Sequence[object]) -> EntityNode:
    entity_id, entity_type, status, superseded_by = values
    return EntityNode(
        entity_id=str(entity_id),
        entity_type=str(entity_type),
        status=str(status),
        superseded_by_entity_id=None if superseded_by is None else str(superseded_by),
    )


def _chain(value: object) -> tuple[EntityNode, ...]:
    """The aggregated chain column (`jsonb` arrays), as Entity nodes."""
    if value is None:
        return ()
    rows = json.loads(value) if isinstance(value, str) else value
    if not isinstance(rows, list):
        raise TypeError("a member chain is a JSON array")
    return tuple(_node(row) for row in rows)


class SqlProgramMembershipRepository(ProgramMembershipRepository):
    """`ProgramMembershipRepository` over one Program read snapshot connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def entity_chains(
        self, principal_id: str, entity_ids: Sequence[str], *, max_hops: int
    ) -> tuple[EntityNode, ...]:
        rows = program_statement(
            lambda: self._connection.execute(
                _ENTITY_CHAINS,
                {
                    "principal_id": principal_id,
                    "entity_ids": list(entity_ids),
                    "max_hops": max_hops,
                },
            ).all()
        )
        return tuple(
            _node((row.entity_id, row.entity_type, row.status, row.superseded_by_entity_id))
            for row in rows
        )

    def member_edges(
        self,
        principal_id: str,
        program_entity_ids: Sequence[str],
        *,
        limit: int,
        max_hops: int,
    ) -> ProgramMemberEdges:
        if not program_entity_ids:
            return ProgramMemberEdges(edges=(), overflow_program=None, entities=())
        rows = program_statement(
            lambda: self._connection.execute(
                _MEMBER_EDGES,
                {
                    "principal_id": principal_id,
                    "program_ids": list(program_entity_ids),
                    "member_of": _MEMBER_OF,
                    "limit_plus_one": limit + 1,
                    "max_hops": max_hops,
                },
            ).all()
        )
        edges = tuple(
            MemberEdge(
                relationship_id=row.relationship_id,
                program_entity_id=row.to_entity_id,
                member_entity_id=row.from_entity_id,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                state=row.state,
            )
            for row in rows
        )
        return ProgramMemberEdges(
            edges=edges[:limit],
            overflow_program=edges[limit].program_entity_id if len(edges) > limit else None,
            entities=_chain(rows[0].chain) if rows else (),
        )

    def bridges(
        self, principal_id: str, project_entity_ids: Sequence[str], *, max_hops: int
    ) -> tuple[BridgeLink, ...]:
        if not project_entity_ids:
            return ()
        rows = program_statement(
            lambda: self._connection.execute(
                _BRIDGES,
                {
                    "principal_id": principal_id,
                    "entity_ids": list(project_entity_ids),
                    "max_hops": max_hops,
                },
            ).all()
        )
        return tuple(
            BridgeLink(
                entity_id=row.terminal_id,
                project_id=row.project_id,
                linked_entity_id=row.project_entity_id,
            )
            for row in rows
        )

    def project_states(self, principal_id: str, project_ids: Sequence[str]) -> Mapping[str, str]:
        if not project_ids:
            return {}
        rows = program_statement(
            lambda: self._connection.execute(
                _PROJECT_STATES,
                {"principal_id": principal_id, "project_ids": list(project_ids)},
            ).all()
        )
        return {row.project_id: row.state for row in rows}
