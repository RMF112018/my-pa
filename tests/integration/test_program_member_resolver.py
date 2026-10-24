"""AT-018: the exact Program member resolver (record lineage S4 contract sections 3.1, 7.1).

Against PostgreSQL, through `ApplicationService.invoke` with the Program read
pool composed as the gateway composes it. A Program's members are derived
only from typed `member_of` edges and the Project-Entity bridge: redirects are
followed, missing and ambiguous bridges are named and never guessed, a
non-Project member (a nested Program included) is counted and never expanded,
the recorded window decides membership at the evaluation instant, a
historical answer separates what the dates prove from what they do not, the
budgets mark exactly the Programs they cut, and nothing is ever written.

The Entity graph is seeded by direct SQL (`lineage_s4_harness.ProgramSeeds`),
so each test states exactly which rows exist. Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from sqlalchemy import text

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.program.vocabulary import MAX_MEMBER_EDGES, MAX_PROGRAM_PROJECTS
from my_pa.domain.source.registry import issue_identifier
from tests.database.lineage_s4_harness import T0, S4Runtime, membership_tables

pytestmark = pytest.mark.database

#: Recorded instants, all before any snapshot the tests take.
JAN: datetime = T0
MAR: datetime = T0 + timedelta(days=59)
JUN: datetime = T0 + timedelta(days=151)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _instant(value: datetime) -> str:
    return value.isoformat()


def _program(answer: dict[str, Any], index: int = 0) -> dict[str, Any]:
    program = answer["programs"][index]
    assert isinstance(program, dict)
    return program


def _members(program: dict[str, Any]) -> list[str]:
    return [member["project_id"] for member in program["members"]]


def _future(runtime: S4Runtime, days: int) -> datetime:
    """An instant `days` after the database's clock (a recorded end still to come)."""
    with runtime.engine.connect() as connection:
        now = connection.execute(text("SELECT now()")).scalar_one()
    assert isinstance(now, datetime)
    return now + timedelta(days=days)


@dataclass(frozen=True)
class _Fixture:
    """The section 10 AT-018 fixture: Programs G, H and R, and their members."""

    g: str
    h: str
    r: str
    b1: tuple[str, str]
    b2: tuple[str, str]
    b3: tuple[str, str]
    u: tuple[str, str]
    edges: dict[str, str]
    missing_entity: str
    ambiguous_entity: str
    ambiguous_projects: tuple[str, str]


def _fixture(runtime: S4Runtime) -> _Fixture:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    h = seeds.program("Program H")
    r = seeds.program("Program R")
    b1 = seeds.project("Bayfront Tower")
    b2 = seeds.project("Second Street")
    b3 = seeds.project("Third Avenue")
    # U: the same name (canonical and display, and the Project's own name) as
    # B1, and no edge into G.
    u = seeds.project("Bayfront Tower")
    edges = {
        "b1": seeds.edge(b1[1], g, effective_from=JAN),
        "b2": seeds.edge(b2[1], g),
        "b3": seeds.edge(b3[1], g, effective_from=JAN),
        "h_b3": seeds.edge(b3[1], h, effective_from=JAN),
        "h_u": seeds.edge(u[1], h, effective_from=JAN),
    }
    # B3's edge into G is revised later: its recorded start moves to March.
    seeds.revise(edges["b3"], effective_from=MAR, effective_to=None)
    # R is merged into G.
    seeds.merge(r, g)
    # A member whose bridge is missing: a project Entity no Project is bound to.
    missing_entity = seeds.entity("project", "Unbound project")
    edges["missing"] = seeds.edge(missing_entity, g, effective_from=JAN)
    # A member made ambiguous by merging 2 bound Project Entities.
    first = seeds.project("Merged survivor")
    second = seeds.project("Merged away")
    seeds.merge(second[1], first[1])
    edges["ambiguous"] = seeds.edge(first[1], g, effective_from=JAN)
    return _Fixture(
        g=g,
        h=h,
        r=r,
        b1=b1,
        b2=b2,
        b3=b3,
        u=u,
        edges=edges,
        missing_entity=missing_entity,
        ambiguous_entity=first[1],
        ambiguous_projects=(first[0], second[0]),
    )


def test_three_bound_members_resolve_and_an_unrelated_project_never_does(
    runtime: S4Runtime,
) -> None:
    scene = _fixture(runtime)
    answer = runtime.resolve(scene.g)
    program = _program(answer)
    assert answer["mode"] == "current"
    assert answer["membership_record"] == "current"
    assert answer["valid_at"] == answer["source_cutoff_at"]
    assert program["resolved_program_entity_id"] == scene.g
    assert program["redirected"] is False
    assert program["program_status"] == "active"
    assert _members(program) == sorted([scene.b1[0], scene.b2[0], scene.b3[0]])
    assert scene.u[0] not in _members(program)
    by_project = {member["project_id"]: member for member in program["members"]}
    assert by_project[scene.b1[0]] == {
        "project_id": scene.b1[0],
        "project_entity_id": scene.b1[1],
        "member_entity_status": "active",
        "project_state": "active",
        "relationship_ids": [scene.edges["b1"]],
    }
    # The unresolved members are named, never dropped and never guessed.
    assert program["unresolved_members"] == sorted(
        [
            {
                "relationship_id": scene.edges["missing"],
                "member_entity_id": scene.missing_entity,
                "reason": "bridge_missing",
            },
            {
                "relationship_id": scene.edges["ambiguous"],
                "member_entity_id": scene.ambiguous_entity,
                "reason": "bridge_ambiguous",
            },
        ],
        key=lambda item: item["relationship_id"],
    )
    assert program["unverified_members"] == []
    assert program["excluded"] == {"non_project_members": 0, "outside_window": 0}
    assert program["complete_state"] == "membership_unresolved"
    assert program["qualifiers"] == ["membership_unresolved"]
    assert answer["portfolio"] == {"project_ids": _members(program), "overlaps": []}
    assert answer["complete_state"] == "membership_unresolved"


def test_a_same_named_unrelated_project_is_never_a_member(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    b1 = seeds.project("Bayfront Tower")
    u = seeds.project("Bayfront Tower")
    seeds.edge(b1[1], g, effective_from=JAN)
    program = _program(runtime.resolve(g))
    assert _members(program) == [b1[0]]
    assert program["qualifiers"] == ["complete"]
    # U is found exactly when an edge says so, and only into that Program.
    h = seeds.program("Program H")
    seeds.edge(u[1], h, effective_from=JAN)
    answer = runtime.resolve(g, h)
    assert _members(_program(answer, 0)) == [b1[0]]
    assert _members(_program(answer, 1)) == [u[0]]
    assert answer["portfolio"]["overlaps"] == []


def test_a_redirected_program_and_member_resolve_to_the_survivor(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    r = seeds.program("Program R")
    seeds.merge(r, g)
    # The member's edge names an Entity merged into the bound Project Entity.
    project, survivor = seeds.project("Survivor project")
    away = seeds.entity("project", "Merged-away project")
    seeds.merge(away, survivor)
    relationship = seeds.edge(away, g, effective_from=JAN)
    answer = runtime.resolve(r, g)
    redirected, direct = _program(answer, 0), _program(answer, 1)
    assert redirected["program_entity_id"] == r
    assert redirected["resolved_program_entity_id"] == g
    assert redirected["redirected"] is True
    assert direct["program_entity_id"] == g
    assert direct["redirected"] is False
    for program in (redirected, direct):
        assert program["members"] == [
            {
                "project_id": project,
                "project_entity_id": survivor,
                "member_entity_status": "active",
                "project_state": "active",
                "relationship_ids": [relationship],
            }
        ]
        assert program["unresolved_members"] == []
    # One resolved Program: the portfolio holds the Project once, no overlap.
    assert answer["portfolio"] == {"project_ids": [project], "overlaps": []}


def test_a_missing_bridge_is_unresolved_and_named(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    # An unbound project Entity, and a Project whose bridge row is unresolved
    # (it names no Entity, so it is unreachable from the member side).
    unbound = seeds.entity("project", "Unbound project")
    unresolved_project, unresolved_entity = seeds.project("Unresolved bridge", bound=False)
    first = seeds.edge(unbound, g, effective_from=JAN)
    second = seeds.edge(unresolved_entity, g, effective_from=JAN)
    program = _program(runtime.resolve(g))
    assert program["members"] == []
    assert program["unresolved_members"] == sorted(
        [
            {"relationship_id": first, "member_entity_id": unbound, "reason": "bridge_missing"},
            {
                "relationship_id": second,
                "member_entity_id": unresolved_entity,
                "reason": "bridge_missing",
            },
        ],
        key=lambda item: item["relationship_id"],
    )
    assert unresolved_project not in _members(program)
    assert program["complete_state"] == "membership_unresolved"


def test_an_ambiguous_bridge_is_unresolved_never_chosen(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    first = seeds.project("Survivor")
    second = seeds.project("Merged away")
    seeds.merge(second[1], first[1])
    relationship = seeds.edge(first[1], g, effective_from=JAN)
    answer = runtime.resolve(g)
    program = _program(answer)
    assert program["members"] == []
    assert program["unresolved_members"] == [
        {
            "relationship_id": relationship,
            "member_entity_id": first[1],
            "reason": "bridge_ambiguous",
        }
    ]
    # Neither Project is chosen anywhere in the answer.
    assert answer["portfolio"]["project_ids"] == []
    assert program["qualifiers"] == ["membership_unresolved"]


def test_a_non_project_member_is_excluded_and_counted(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    project, entity = seeds.project("Project member")
    organization = seeds.entity("organization", "Organization member")
    person = seeds.entity("person", "Person member")
    seeds.edge(entity, g, effective_from=JAN)
    seeds.edge(organization, g, effective_from=JAN)
    seeds.edge(person, g, effective_from=JAN)
    program = _program(runtime.resolve(g))
    assert _members(program) == [project]
    assert program["excluded"] == {"non_project_members": 2, "outside_window": 0}
    assert program["unresolved_members"] == []
    assert program["qualifiers"] == ["complete"]


def test_membership_outside_its_window_is_excluded(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    inside = seeds.project("Inside")
    ended = seeds.project("Ended in March")
    closed_active = seeds.project("Window closed, still active")
    later = seeds.project("Starts later")
    seeds.edge(inside[1], g, effective_from=JAN)
    seeds.edge(ended[1], g, effective_from=JAN, effective_to=MAR, state="ended")
    seeds.edge(closed_active[1], g, effective_from=JAN, effective_to=MAR)
    seeds.edge(later[1], g, effective_from=_future(runtime, 30))
    program = _program(runtime.resolve(g))
    assert _members(program) == [inside[0]]
    assert program["excluded"] == {"non_project_members": 0, "outside_window": 3}
    # At a `valid_at` inside the recorded windows, the ended ones were members.
    february = MAR - timedelta(days=20)
    historical = _program(runtime.resolve(g, valid_at=_instant(february)))
    assert _members(historical) == sorted([inside[0], ended[0], closed_active[0]])
    assert historical["excluded"]["outside_window"] == 1


def test_a_null_start_date_is_historical_membership_unverified(runtime: S4Runtime) -> None:
    scene = _fixture(runtime)
    # Now, B2's null start is no obstacle: it is a current member.
    assert scene.b2[0] in _members(_program(runtime.resolve(scene.g)))
    # At a `valid_at`, its recorded dates cannot prove membership.
    answer = runtime.resolve(scene.g, valid_at=_instant(JUN))
    program = _program(answer)
    assert answer["mode"] == "historical"
    assert answer["valid_at"] == "2026-06-01T00:00:00.000000Z"
    assert scene.b2[0] not in _members(program)
    assert program["unverified_members"] == [
        {
            "relationship_id": scene.edges["b2"],
            "member_entity_id": scene.b2[1],
            "project_id": scene.b2[0],
            "reason": "start_not_recorded",
        }
    ]
    assert "historical_membership_unverified" in program["qualifiers"]
    assert "historical_membership_unverified" in answer["qualifiers"]


def test_an_ended_edge_without_an_end_is_historical_membership_unverified(
    runtime: S4Runtime,
) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    project, entity = seeds.project("Ended, no recorded end")
    relationship = seeds.edge(entity, g, effective_from=JAN, state="ended")
    # Not a current member: an ended edge with no end is not in force now.
    now = _program(runtime.resolve(g))
    assert now["members"] == []
    assert now["excluded"]["outside_window"] == 1
    # Historically its end is not recorded, so membership at `valid_at` is unproven.
    program = _program(runtime.resolve(g, valid_at=_instant(MAR)))
    assert program["members"] == []
    assert program["unverified_members"] == [
        {
            "relationship_id": relationship,
            "member_entity_id": entity,
            "project_id": project,
            "reason": "end_not_recorded",
        }
    ]
    assert program["complete_state"] == "historical_membership_unverified"


def test_a_dated_edge_is_a_verified_historical_member(runtime: S4Runtime) -> None:
    scene = _fixture(runtime)
    # B1 is dated from January: a verified member in June.
    june = _program(runtime.resolve(scene.g, valid_at=_instant(JUN)))
    assert scene.b1[0] in _members(june)
    assert scene.b3[0] in _members(june)
    # Before its recorded start it is outside the window, not unverified.
    before = _program(runtime.resolve(scene.g, valid_at=_instant(JAN - timedelta(days=1))))
    assert scene.b1[0] not in _members(before)
    assert scene.b1[0] not in [item["project_id"] for item in before["unverified_members"]]
    # B3's edge was revised to start in March: February reads the revised window
    # (the recorded window as it stands now, `membership_record: current`).
    february = runtime.resolve(scene.g, valid_at=_instant(MAR - timedelta(days=20)))
    assert february["membership_record"] == "current"
    assert scene.b3[0] not in _members(_program(february))
    assert scene.b1[0] in _members(_program(february))


def test_overlapping_programs_count_a_project_once_at_portfolio_grain(runtime: S4Runtime) -> None:
    scene = _fixture(runtime)
    answer = runtime.resolve(scene.g, scene.h)
    g, h = _program(answer, 0), _program(answer, 1)
    assert scene.b3[0] in _members(g)
    assert _members(h) == sorted([scene.b3[0], scene.u[0]])
    portfolio = answer["portfolio"]
    assert portfolio["project_ids"] == sorted({*_members(g), *_members(h)})
    assert len(portfolio["project_ids"]) == len(set(portfolio["project_ids"]))
    assert portfolio["project_ids"].count(scene.b3[0]) == 1
    assert portfolio["overlaps"] == [
        {"project_id": scene.b3[0], "program_entity_ids": sorted([scene.g, scene.h])}
    ]


def test_a_non_program_entity_is_invalid_request(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    _project, project_entity = seeds.project("Not a Program")
    organization = seeds.entity("organization", "Not a Program either")
    # A program Entity merged into a project Entity: its terminal is not a Program.
    redirected = seeds.program("Redirected to a project")
    seeds.merge(redirected, project_entity)
    for requested in (project_entity, organization, redirected):
        error = runtime.resolve_refused(requested)
        assert (error["code"], error["safe_details"]) == ("invalid_request", ["program_entity_ids"])


def test_a_redirect_cycle_is_conflict(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    first = seeds.program("Cycle one")
    second = seeds.program("Cycle two")
    seeds.merge(first, second)
    seeds.merge(second, first)
    error = runtime.resolve_refused(first)
    assert (error["code"], error["safe_details"]) == ("conflict", ["program_entity_ids"])
    # A chain one hop longer than the bound is a conflict too; at the bound it resolves.
    chain = [seeds.program(f"Chain {index}") for index in range(10)]
    for away, into in pairwise(chain):
        seeds.merge(away, into)
    assert _program(runtime.resolve(chain[1]))["resolved_program_entity_id"] == chain[-1]
    error = runtime.resolve_refused(chain[0])
    assert (error["code"], error["safe_details"]) == ("conflict", ["program_entity_ids"])


def test_the_edge_budget_answers_truncated_budget(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    members = seeds.entities("organization", MAX_MEMBER_EDGES + 1)
    seeds.edges(members, g)
    answer = runtime.resolve(g)
    program = _program(answer)
    # Exactly the budget was read; nothing after it.
    assert program["excluded"]["non_project_members"] == MAX_MEMBER_EDGES
    assert program["complete_state"] == "truncated_budget"
    assert answer["complete_state"] == "truncated_budget"
    # At the budget itself, nothing is truncated.
    h = seeds.program("Program H")
    seeds.edges(members[:MAX_MEMBER_EDGES], h)
    assert _program(runtime.resolve(h))["qualifiers"] == ["complete"]
    # The Project budget: more than 100 distinct Projects over the request.
    projects = [
        seeds.project(f"Budget project {index}") for index in range(MAX_PROGRAM_PROJECTS + 1)
    ]
    p = seeds.program("Program P")
    seeds.edges([entity for _project, entity in projects], p)
    capped = _program(runtime.resolve(p))
    assert (
        _members(capped) == sorted(project for project, _entity in projects)[:MAX_PROGRAM_PROJECTS]
    )
    assert capped["complete_state"] == "truncated_budget"


def test_a_budget_marks_the_cut_program_later_programs_and_the_portfolio(
    runtime: S4Runtime,
) -> None:
    seeds = runtime.seeds
    first, cut, later = (seeds.program(f"Program {name}") for name in ("one", "two", "three"))
    member, entity = seeds.project("Early member")
    seeds.edge(entity, first, effective_from=JAN)
    seeds.edges(seeds.entities("organization", 9), first)
    seeds.edges(seeds.entities("organization", MAX_MEMBER_EDGES - 5), cut)
    seeds.edges(seeds.entities("organization", 5), later)
    answer = runtime.resolve(first, cut, later)
    one, two, three = (_program(answer, index) for index in range(3))
    assert _members(one) == [member]
    assert one["qualifiers"] == ["complete"]
    assert two["complete_state"] == "truncated_budget"
    assert three["complete_state"] == "truncated_budget"
    # The bound is reached inside the second Program: it read the rest of the
    # budget, and nothing of the third was read.
    assert two["excluded"]["non_project_members"] == MAX_MEMBER_EDGES - 10
    assert three["excluded"]["non_project_members"] == 0
    assert answer["complete_state"] == "truncated_budget"
    # Requested in another order, the cut moves with the request order.
    reordered = runtime.resolve(later, first, cut)
    assert [program["qualifiers"] for program in reordered["programs"]] == [
        ["complete"],
        ["complete"],
        ["truncated_budget"],
    ]


def test_an_edge_ended_with_a_future_end_is_a_member_until_that_end(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    project, entity = seeds.project("Ends next month")
    relationship = seeds.edge(
        entity, g, effective_from=JAN, effective_to=_future(runtime, 30), state="ended"
    )
    program = _program(runtime.resolve(g))
    assert program["members"] == [
        {
            "project_id": project,
            "project_entity_id": entity,
            "member_entity_status": "active",
            "project_state": "active",
            "relationship_ids": [relationship],
        }
    ]
    assert program["excluded"]["outside_window"] == 0
    # Historically, with both dates recorded, it is a verified member.
    historical = _program(runtime.resolve(g, valid_at=_instant(MAR)))
    assert _members(historical) == [project]
    assert historical["unverified_members"] == []


def test_a_nested_program_is_not_expanded(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    nested = seeds.program("Nested Program")
    seeds.edge(nested, g, effective_from=JAN)
    inner, inner_entity = seeds.project("Member of the nested Program")
    seeds.edge(inner_entity, nested, effective_from=JAN)
    program = _program(runtime.resolve(g))
    assert program["members"] == []
    assert program["excluded"] == {"non_project_members": 1, "outside_window": 0}
    # The nested Program is a Program of its own.
    assert _members(_program(runtime.resolve(nested))) == [inner]


def test_a_member_entity_status_is_reported_not_filtered(runtime: S4Runtime) -> None:
    seeds = runtime.seeds
    g = seeds.program("Program G")
    expected: dict[str, str] = {}
    for status in ("active", "inactive", "historical", "archived"):
        entity = seeds.entity("project", f"Status {status}", status=status)
        project = issue_identifier(IdKind.PROJECT)
        seeds.continuity_project(project, f"Status {status} project")
        seeds.link(project, entity)
        seeds.edge(entity, g, effective_from=JAN)
        expected[project] = status
    closed, closed_entity = seeds.project("Closed project", state="closed")
    seeds.edge(closed_entity, g, effective_from=JAN)
    program = _program(runtime.resolve(g))
    statuses = {
        member["project_id"]: member["member_entity_status"] for member in program["members"]
    }
    assert statuses == {**expected, closed: "active"}
    states = {member["project_id"]: member["project_state"] for member in program["members"]}
    assert states[closed] == "closed"
    assert program["qualifiers"] == ["complete"]
    # The Program's own status is admitted and reported too.
    historical_program = seeds.entity("program", "Historical Program", status="historical")
    assert _program(runtime.resolve(historical_program))["program_status"] == "historical"


def test_resolution_writes_nothing(runtime: S4Runtime) -> None:
    scene = _fixture(runtime)
    before = membership_tables(runtime.engine)
    runtime.resolve(scene.g, scene.h, scene.r)
    runtime.resolve(scene.g, valid_at=_instant(JUN))
    runtime.resolve_refused(scene.b1[1])
    assert membership_tables(runtime.engine) == before
    # The snapshot transaction is read-only, and every connection went back.
    assert runtime.program_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
