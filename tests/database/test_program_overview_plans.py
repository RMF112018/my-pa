"""AT-019 (plans): the overview's statement plan is constant and index-served (S4 sections 4, 6.3).

Record lineage S4 (worker M4). One `programs.overview` issues the section 6.3
statement plan on its Program-pool connection whatever the number of
Programs, Projects and rows: the snapshot query; the Programs with their
redirect chains, the member edges, the bridges and the Project states (4);
the Commitment aggregates, the outstanding Issue pairs, the legacy Issue links
and the sync targets with their last run (4); and the Constraint portfolio
path's settings, overview facts and sync summary (4) -- 13 in all.

Each statement is captured as sent and `EXPLAIN`ed with sequential scans
disabled, so the plan names the index the planner can use: the S4 revision adds
no index (section 4), and these pin that the existing ones serve the reads --
`entity_relationships_by_to_entity` for the member edges,
`a_project_entity_is_linked_once_per_principal` for the bridges, and a
Principal-scoped index under every metric aggregate. Every identity is
synthetic.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Connection, Engine, event, text

from my_pa.application.commands import ReadProgramOverview
from tests.database.lineage_s4_harness import T0, S4Runtime

pytestmark = pytest.mark.database

#: Section 6.3: the statement plan of one overview with every family visible.
OVERVIEW_STATEMENTS: Final = 13


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


@contextmanager
def _captured(engine: Engine) -> Iterator[list[tuple[str, Any]]]:
    """Every statement `engine` sends inside the block, with its parameters."""
    seen: list[tuple[str, Any]] = []

    def record(
        _conn: object, _cursor: object, statement: str, parameters: object, *_: object
    ) -> None:
        seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _program(runtime: S4Runtime, name: str, members: int) -> tuple[str, list[str]]:
    """A Program of `members` Projects, each with a calendar, a target, Commitments,
    Constraints and an Issue link -- so every statement of the plan has rows to read."""
    seeds = runtime.seeds
    program = seeds.program(name)
    projects: list[str] = []
    for index in range(members):
        project_id, entity_id = seeds.project(f"{name} {index}")
        seeds.edge(entity_id, program, effective_from=T0)
        category = seeds.constraint_calendar(project_id)
        seeds.sync_target(project_id)
        seeds.constraint(project_id, category, due_date=T0.date() + timedelta(days=400))
        runtime.work_commitment(f"{name}-{index}", project_id=project_id)
        projects.append(project_id)
    runtime.linked_issue(f"{name}-issue", *projects)
    return program, projects


def _statements(runtime: S4Runtime, *program_ids: str) -> list[tuple[str, Any]]:
    with _captured(runtime.program_engine) as seen:
        envelope = runtime.invoke(ReadProgramOverview(program_entity_ids=program_ids))
    assert envelope.error is None, envelope.error
    return seen


def _plan(runtime: S4Runtime, statement: str, parameters: Any) -> str:  # noqa: ANN401
    with runtime.engine.connect() as connection:
        connection.execute(text("SET enable_seqscan = off"))
        return "\n".join(connection.exec_driver_sql(f"EXPLAIN {statement}", parameters).scalars())


def _one(seen: list[tuple[str, Any]], marker: str) -> tuple[str, Any]:
    found = [item for item in seen if marker in item[0]]
    assert len(found) == 1, (marker, [statement[:80] for statement, _ in seen])
    return found[0]


def test_the_overview_issues_a_constant_number_of_statements(runtime: S4Runtime) -> None:
    small, _small_projects = _program(runtime, "Small", 1)
    large, _large_projects = _program(runtime, "Large", 12)
    other, _other_projects = _program(runtime, "Other", 3)
    counts = {
        "small": len(_statements(runtime, small)),
        "large": len(_statements(runtime, large)),
        "three programs": len(_statements(runtime, small, large, other)),
    }
    assert set(counts.values()) == {OVERVIEW_STATEMENTS}, counts
    # Every one is a read: the snapshot never writes.
    for statement, _parameters in _statements(runtime, large):
        assert statement.lstrip().upper().startswith(("SELECT", "WITH")), statement[:80]


#: Enough synthetic rows of this Principal for the planner's choice to mean
#: something: with a handful of rows every plan is a scan of the Principal
#: index, whatever the statement.
VOLUME: Final = 3000


def _columns(connection: Connection, table: str) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'knowledge' AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"table": table},
        ).scalars()
    )


def _copy(
    connection: Connection, table: str, key: str, value: str, replaced: dict[str, str]
) -> None:
    """`VOLUME` copies of one existing row of `table`, with `replaced` columns rewritten.

    `n` (1..`VOLUME`) is in scope for the replacement expressions.
    """
    columns = _columns(connection, table)
    assert set(replaced) <= set(columns), (table, set(replaced) - set(columns))
    select = ", ".join(replaced.get(column, f"src.{column}") for column in columns)
    connection.execute(
        text(
            f"INSERT INTO knowledge.{table} ({', '.join(columns)}) "  # noqa: S608
            f"SELECT {select} FROM knowledge.{table} src, generate_series(1, :volume) AS n "
            f"WHERE src.{key} = :value"
        ),
        {"volume": VOLUME, "value": value},
    )


def _volume(runtime: S4Runtime, program: str, project_id: str) -> None:
    """`VOLUME` more Projects of this Principal, each bound, a member of one of 100
    other Programs, with a Commitment, an Issue link (and its legacy-shaped row)
    and a sync target -- copies of the scene's own rows, under replica mode (a
    synthetic database only)."""
    with runtime.engine.connect() as connection:
        entity_id = connection.execute(
            text(
                "SELECT project_entity_id FROM knowledge.project_entity_links "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        ).scalar_one()
        relationship_id, commitment_id, event_id, link_id, target_id = connection.execute(
            text(
                "SELECT (SELECT relationship_id FROM knowledge.entity_relationships "
                " WHERE from_entity_id = :entity_id),"
                " (SELECT commitment_id FROM knowledge.commitments "
                " WHERE project_id = :project_id LIMIT 1),"
                " (SELECT membership_event_id FROM knowledge.issue_project_membership_events "
                " WHERE project_id = :project_id LIMIT 1),"
                " (SELECT project_situation_id FROM knowledge.project_situations "
                " WHERE project_id = :project_id LIMIT 1),"
                " (SELECT sync_target_id FROM knowledge.constraint_sync_targets "
                " WHERE project_id = :project_id LIMIT 1)"
            ),
            {"entity_id": entity_id, "project_id": project_id},
        ).one()
    project = "'prj_vol' || lpad(n::text, 8, '0')"
    entity = "'ent_vol' || lpad(n::text, 8, '0')"
    with runtime.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        _copy(
            connection,
            "entities",
            "entity_id",
            entity_id,
            {
                "entity_id": entity,
                "canonical_name": "src.canonical_name || n",
                "display_name": "src.display_name || n",
            },
        )
        _copy(
            connection,
            "entities",
            "entity_id",
            program,
            {
                "entity_id": "'ent_volprog' || lpad(n::text, 8, '0')",
                "canonical_name": "src.canonical_name || n",
                "display_name": "src.display_name || n",
            },
        )
        _copy(
            connection,
            "projects",
            "project_id",
            project_id,
            {"project_id": project, "name": "src.name || n"},
        )
        _copy(
            connection,
            "project_entity_links",
            "project_id",
            project_id,
            {"project_id": project, "project_entity_id": entity},
        )
        _copy(
            connection,
            "entity_relationships",
            "relationship_id",
            relationship_id,
            {
                "relationship_id": "'erel_vol' || lpad(n::text, 8, '0')",
                "from_entity_id": entity,
                "to_entity_id": "'ent_volprog' || lpad((n % 100 + 1)::text, 8, '0')",
            },
        )
        _copy(
            connection,
            "commitments",
            "commitment_id",
            commitment_id,
            {"commitment_id": "'cmt_vol' || lpad(n::text, 8, '0')", "project_id": project},
        )
        _copy(
            connection,
            "issue_project_membership_events",
            "membership_event_id",
            event_id,
            {"membership_event_id": "'ipme_vol' || lpad(n::text, 8, '0')", "project_id": project},
        )
        _copy(
            connection,
            "project_situations",
            "project_situation_id",
            link_id,
            {"project_situation_id": "'psit_vol' || lpad(n::text, 8, '0')", "project_id": project},
        )
        _copy(
            connection,
            "constraint_sync_targets",
            "sync_target_id",
            target_id,
            {
                "sync_target_id": "'csyt_vol' || lpad(n::text, 8, '0')",
                "project_id": project,
                "external_identity": "src.external_identity || n",
                "last_run_id": "NULL",
            },
        )
    with runtime.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for table in (
            "entities",
            "projects",
            "project_entity_links",
            "entity_relationships",
            "commitments",
            "issue_project_membership_events",
            "project_situations",
            "constraint_sync_targets",
            "situations",
        ):
            connection.execute(text(f"ANALYZE knowledge.{table}"))
        for table in ("entity_relationships", "commitments", "constraint_sync_targets"):
            copied = connection.execute(
                text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608
            ).scalar_one()
            assert copied > VOLUME, (table, copied)


_SCAN: Final = re.compile(r"(Seq Scan|Index Scan|Index Only Scan|Bitmap Heap Scan)\b.* on (\w+)")


def _scans(plan: str) -> dict[str, list[tuple[str, str]]]:
    """Per table, each scan node of `plan`: `(node kind, its condition and filter lines)`."""
    lines = plan.splitlines()
    found: dict[str, list[tuple[str, str]]] = {}
    for index, line in enumerate(lines):
        match = _SCAN.search(line)
        if match is None:
            continue
        block: list[str] = []
        for following in lines[index + 1 :]:
            if "->" in following:
                break
            block.append(following)
        found.setdefault(match.group(2), []).append((match.group(1), "\n".join(block)))
    return found


def _scene(runtime: S4Runtime, name: str) -> str:
    program, projects = _program(runtime, name, 3)
    _volume(runtime, program, projects[0])
    return program


def test_membership_reads_use_the_relationship_and_bridge_indexes(runtime: S4Runtime) -> None:
    program = _scene(runtime, "Indexed")
    seen = _statements(runtime, program)
    edges = _plan(runtime, *_one(seen, "knowledge.entity_relationships r"))
    assert "entity_relationships_by_to_entity" in edges, edges
    bridges = _plan(runtime, *_one(seen, "knowledge.project_entity_links l"))
    assert "a_project_entity_is_linked_once_per_principal" in bridges, bridges
    for plan in (edges, bridges):
        assert "Seq Scan" not in plan, plan


#: Each metric statement of the plan, by a fragment only it carries, and the
#: tables its plan must reach through an index, Principal-scoped at that node.
_METRIC_READS: Final = (
    ("FROM knowledge.commitments c", ("commitments",)),
    ("DISTINCT ON (m.project_id, m.issue_id)", ("issue_project_membership_events", "situations")),
    (
        "FROM knowledge.project_situations ps",
        ("project_situations", "issue_project_membership_events"),
    ),
    ("LEFT JOIN knowledge.constraint_sync_targets t", ("constraint_sync_targets",)),
)


def test_metric_reads_are_principal_scoped_aggregates(runtime: S4Runtime) -> None:
    program = _scene(runtime, "Aggregates")
    seen = _statements(runtime, program)
    for marker, tables in _METRIC_READS:
        statement, parameters = _one(seen, marker)
        # One statement for the whole Project set, bound to this Principal.
        assert "principal_id = %(principal_id)s" in statement, marker
        assert "ANY(%(project_ids)s" in statement or "unnest(%(project_ids)s" in statement
        plan = _plan(runtime, statement, parameters)
        assert "Seq Scan" not in plan, (marker, plan)
        scans = _scans(plan)
        for table in tables:
            # Reached through an index, and this Principal's partition applied
            # at that very node (its index condition or its filter).
            assert scans.get(table), (marker, table, plan)
            for kind, conditions in scans[table]:
                assert kind != "Seq Scan", (marker, table, plan)
                assert "principal_id" in conditions, (marker, table, plan)
    # The Commitment aggregate and the legacy-link count are grouped in SQL.
    for marker in ("FROM knowledge.commitments c", "FROM knowledge.project_situations ps"):
        statement, parameters = _one(seen, marker)
        assert "GROUP BY" in statement
        assert "Aggregate" in _plan(runtime, statement, parameters), marker
