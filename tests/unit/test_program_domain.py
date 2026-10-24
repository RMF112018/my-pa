"""The pure Program reporting rules (record lineage S4 contract sections 3.1 to 3.3, 5.1).

FAST: no database. The membership rows (worker M2, WP-04A) pin the section 3.1
rule as tables over fetched rows -- the window rule in both modes, the
redirect walk's bound and cycle refusal, the bridge's exactly-one rule and the
completeness precedence -- so the database tests of
`tests/integration/test_program_member_resolver.py` prove the reads feed it
and these prove the rule itself. The reportability and digest rows are added
by the overview package (worker M4).

Every identifier here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.domain.program.membership import (
    BridgeLink,
    EntityNode,
    MemberEdge,
    RedirectFailure,
    RequestedProgram,
    WindowVerdict,
    assemble_membership,
    bridge_outcome,
    completeness,
    walk_redirect,
    window_verdict,
)
from my_pa.domain.program.vocabulary import (
    MAX_REDIRECT_HOPS,
    MembershipMode,
    MemberUnresolvedReason,
    ProgramCompleteness,
)

T: Final = datetime(2026, 10, 24, 12, tzinfo=UTC)
BEFORE: Final = T - timedelta(days=30)
AFTER: Final = T + timedelta(days=30)
CURRENT: Final = MembershipMode.CURRENT
HISTORICAL: Final = MembershipMode.HISTORICAL
MEMBER: Final = WindowVerdict.MEMBER
OUTSIDE: Final = WindowVerdict.OUTSIDE
NO_START: Final = WindowVerdict.START_NOT_RECORDED
NO_END: Final = WindowVerdict.END_NOT_RECORDED


def _edge(
    starts: datetime | None,
    ends: datetime | None,
    state: str = "active",
    *,
    relationship_id: str = "erel_programdomain0001",
    program: str = "ent_programdomaing001",
    member: str = "ent_programdomainb001",
) -> MemberEdge:
    return MemberEdge(
        relationship_id=relationship_id,
        program_entity_id=program,
        member_entity_id=member,
        effective_from=starts,
        effective_to=ends,
        state=state,
    )


def _node(
    entity_id: str,
    entity_type: str = "project",
    *,
    status: str = "active",
    into: str | None = None,
) -> EntityNode:
    return EntityNode(
        entity_id=entity_id,
        entity_type=entity_type,
        status="merged_redirect" if into is not None else status,
        superseded_by_entity_id=into,
    )


#: `(effective_from, effective_to, state) -> (current verdict, historical verdict)`
#: at the instant `T`. Both modes apply the same window; historical mode only
#: separates what the recorded dates can prove.
WINDOW_TABLE: Final = [
    # A dated, open, active edge is a member in both modes.
    ((BEFORE, None, "active"), (MEMBER, MEMBER)),
    # A null start is no obstacle now, and unprovable at an instant.
    ((None, None, "active"), (MEMBER, NO_START)),
    ((None, AFTER, "active"), (MEMBER, NO_START)),
    ((None, AFTER, "ended"), (MEMBER, NO_START)),
    # A start after `T` is outside the window (both non-null comparisons).
    ((AFTER, None, "active"), (OUTSIDE, OUTSIDE)),
    # An end at or before `T` is outside it.
    ((BEFORE, T, "ended"), (OUTSIDE, OUTSIDE)),
    ((BEFORE, T - timedelta(microseconds=1), "active"), (OUTSIDE, OUTSIDE)),
    ((None, BEFORE, "ended"), (OUTSIDE, OUTSIDE)),
    # An `ended` edge whose recorded end is still in the future is a member
    # until that end (R4-F09), and a verified one: both dates are recorded.
    ((BEFORE, AFTER, "ended"), (MEMBER, MEMBER)),
    ((BEFORE, T + timedelta(microseconds=1), "ended"), (MEMBER, MEMBER)),
    # An `ended` edge with no recorded end is not a current member, and
    # historically its end is unprovable.
    ((BEFORE, None, "ended"), (OUTSIDE, NO_END)),
    # A dated closed window around `T`.
    ((BEFORE, AFTER, "active"), (MEMBER, MEMBER)),
    # The start instant itself is inside.
    ((T, None, "active"), (MEMBER, MEMBER)),
]


@pytest.mark.parametrize(("window", "expected"), WINDOW_TABLE)
def test_window_rule_table(
    window: tuple[datetime | None, datetime | None, str],
    expected: tuple[WindowVerdict, WindowVerdict],
) -> None:
    starts, ends, state = window
    edge = _edge(starts, ends, state)
    current, historical = expected
    assert window_verdict(edge, T, CURRENT) is current
    assert window_verdict(edge, T, HISTORICAL) is historical
    # Same window over the recorded dates: outside historically is outside
    # now; the one difference is an `ended` edge with no recorded end, which is
    # not a current member and is historically `end_not_recorded`.
    if historical is OUTSIDE:
        assert current is OUTSIDE
    if current is OUTSIDE and historical is not OUTSIDE:
        assert (ends, state, historical) == (None, "ended", NO_END)
    # A verified historical member is a current member at the same instant.
    if historical is MEMBER:
        assert current is MEMBER


def test_redirect_walk_bounds_and_cycles() -> None:
    # No redirect: the Entity is its own terminal, 0 hops.
    nodes = {"ent_programdomainp001": _node("ent_programdomainp001", "program")}
    walked = walk_redirect("ent_programdomainp001", nodes)
    assert walked.terminal == nodes["ent_programdomainp001"]
    assert walked.hops == 0
    # A chain of exactly MAX_REDIRECT_HOPS hops resolves; one more is too long.
    chain = [f"ent_programdomainc{index:03d}" for index in range(MAX_REDIRECT_HOPS + 2)]
    for limit in (MAX_REDIRECT_HOPS, MAX_REDIRECT_HOPS + 1):
        built = {
            entity: _node(entity, "program", into=chain[index + 1])
            for index, entity in enumerate(chain[:limit])
        }
        built[chain[limit]] = _node(chain[limit], "program")
        walked = walk_redirect(chain[0], built)
        if limit == MAX_REDIRECT_HOPS:
            assert walked.terminal is not None
            assert walked.terminal.entity_id == chain[limit]
            assert walked.hops == MAX_REDIRECT_HOPS
        else:
            assert walked.terminal is None
            assert walked.failure is RedirectFailure.TOO_LONG
    # A revisit is a cycle, never a terminal.
    looped = {
        "ent_programdomaina001": _node("ent_programdomaina001", into="ent_programdomaina002"),
        "ent_programdomaina002": _node("ent_programdomaina002", into="ent_programdomaina003"),
        "ent_programdomaina003": _node("ent_programdomaina003", into="ent_programdomaina001"),
    }
    walked = walk_redirect("ent_programdomaina001", looped)
    assert walked.terminal is None
    assert walked.failure is RedirectFailure.CYCLE
    # An Entity that is not the caller's (not fetched) has no terminal.
    walked = walk_redirect("ent_programdomainz001", looped)
    assert walked.failure is RedirectFailure.MISSING
    # The status of a terminal is whatever it is: only `merged_redirect` is followed.
    archived = {"ent_programdomainr001": _node("ent_programdomainr001", status="archived")}
    walked = walk_redirect("ent_programdomainr001", archived)
    assert walked.terminal is not None
    assert walked.terminal.status == "archived"


@pytest.mark.parametrize(
    ("projects", "expected"),
    [
        ((), MemberUnresolvedReason.BRIDGE_MISSING),
        (("prj_programdomain0001",), "prj_programdomain0001"),
        (("prj_programdomain0001", "prj_programdomain0001"), "prj_programdomain0001"),
        (
            ("prj_programdomain0001", "prj_programdomain0002"),
            MemberUnresolvedReason.BRIDGE_AMBIGUOUS,
        ),
        (
            ("prj_programdomain0002", "prj_programdomain0001", "prj_programdomain0003"),
            MemberUnresolvedReason.BRIDGE_AMBIGUOUS,
        ),
    ],
)
def test_bridge_resolution_counts(
    projects: tuple[str, ...], expected: str | MemberUnresolvedReason
) -> None:
    # Exactly one bound Project, else why there is none; never a choice.
    assert bridge_outcome(projects) == expected
    # The assembled answer names the same outcome for one in-window edge.
    resolution = assemble_membership(
        (RequestedProgram("ent_programdomaing001", "ent_programdomaing001", "active"),),
        (_edge(BEFORE, None),),
        mode=CURRENT,
        at=T,
        source_cutoff_at=T,
        nodes={"ent_programdomainb001": _node("ent_programdomainb001")},
        bridges=[
            BridgeLink("ent_programdomainb001", project, "ent_programdomainb001")
            for project in projects
        ],
        project_states=dict.fromkeys(projects, "active"),
        edge_overflow_program=None,
    )
    (program,) = resolution.programs
    if isinstance(expected, MemberUnresolvedReason):
        assert program.members == ()
        assert [member.reason for member in program.unresolved_members] == [expected]
        assert program.complete_state is ProgramCompleteness.MEMBERSHIP_UNRESOLVED
    else:
        assert program.project_ids == (expected,)
        assert program.unresolved_members == ()
        assert program.qualifiers == (ProgramCompleteness.COMPLETE,)


def test_completeness_precedence() -> None:
    assert completeness([]) == (ProgramCompleteness.COMPLETE, (ProgramCompleteness.COMPLETE,))
    assert completeness([ProgramCompleteness.COMPLETE]) == (
        ProgramCompleteness.COMPLETE,
        (ProgramCompleteness.COMPLETE,),
    )
    every = [
        ProgramCompleteness.RESTRICTED_EVIDENCE,
        ProgramCompleteness.COMPLETE,
        ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        ProgramCompleteness.MEMBERSHIP_UNRESOLVED,
        ProgramCompleteness.TRUNCATED_BUDGET,
    ]
    state, qualifiers = completeness(every)
    assert state is ProgramCompleteness.TRUNCATED_BUDGET
    # `complete` never combines; qualifiers[0] is the state; precedence order.
    assert qualifiers == (
        ProgramCompleteness.TRUNCATED_BUDGET,
        ProgramCompleteness.MEMBERSHIP_UNRESOLVED,
        ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        ProgramCompleteness.RESTRICTED_EVIDENCE,
    )
    assert completeness(
        [
            ProgramCompleteness.RESTRICTED_EVIDENCE,
            ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        ]
    ) == (
        ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
        (
            ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
            ProgramCompleteness.RESTRICTED_EVIDENCE,
        ),
    )
