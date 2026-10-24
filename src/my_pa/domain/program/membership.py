"""The exact Program membership rule (record lineage S4 contract section 3.1, WP-04A).

Pure: every function here works over rows a repository has already fetched in
the Program read snapshot, and none reads, writes or grants anything. The rule
it states is the whole of how a Continuity Project becomes a member of a
Program:

* a typed `member_of` edge into the (redirect-resolved) Program Entity,
* inside its **recorded** effective window at the evaluation instant,
* from an Entity that redirect-resolves to a **project**-typed Entity,
* whose Project-Entity bridge names **exactly one** Continuity Project.

Never a name, alias, canonical name, Organization, address, participation or
property match, never a manual Project list, and never a transitive expansion
of a nested Program. Whatever the rule cannot prove is named -- an unresolved
member with its reason, an unverified historical member with its reason, an
excluded edge counted -- and decides the answer's completeness by the section 3
precedence.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.program.vocabulary import (
    MAX_PROGRAM_PROJECTS,
    MAX_REDIRECT_HOPS,
    PROGRAM_COMPLETENESS_PRECEDENCE,
    MembershipMode,
    MemberUnresolvedReason,
    MemberUnverifiedReason,
    ProgramCompleteness,
)

__all__ = [
    "MERGED_REDIRECT",
    "PROGRAM_ENTITY_TYPE",
    "PROJECT_ENTITY_TYPE",
    "BridgeLink",
    "EntityNode",
    "MemberEdge",
    "MembershipResolution",
    "PortfolioOverlap",
    "PortfolioResolution",
    "ProgramMember",
    "ProgramResolution",
    "Redirect",
    "RedirectFailure",
    "RequestedProgram",
    "UnresolvedMember",
    "UnverifiedMember",
    "WindowVerdict",
    "assemble_membership",
    "bridge_outcome",
    "completeness",
    "member_terminals",
    "walk_redirect",
    "window_verdict",
]

#: `entities.status` of an Entity folded into another (`superseded_by_entity_id` set).
MERGED_REDIRECT: Final = "merged_redirect"
#: The `entities.entity_type` a requested Program must resolve to (step 1).
PROGRAM_ENTITY_TYPE: Final = "program"
#: The `entities.entity_type` a member must resolve to (step 4).
PROJECT_ENTITY_TYPE: Final = "project"
#: `entity_relationships.state` of an edge recorded as currently in force.
_ACTIVE_EDGE: Final = "active"


@dataclass(frozen=True, slots=True)
class EntityNode:
    """One `entities` row of the caller, as a redirect walk needs it."""

    entity_id: str
    entity_type: str
    status: str
    superseded_by_entity_id: str | None


@dataclass(frozen=True, slots=True)
class MemberEdge:
    """One `member_of` edge into a resolved Program (`state <> 'superseded'`)."""

    relationship_id: str
    program_entity_id: str
    member_entity_id: str
    effective_from: datetime | None
    effective_to: datetime | None
    state: str


@dataclass(frozen=True, slots=True)
class BridgeLink:
    """One `bound` Project-Entity bridge row whose Entity redirect-resolves to `entity_id`.

    `linked_entity_id` is the Entity the row stores (`entity_id` itself, or an
    Entity merged into it).
    """

    entity_id: str
    project_id: str
    linked_entity_id: str


class RedirectFailure(StrEnum):
    """Why a redirect walk found no terminal Entity (section 3.1 step 1)."""

    #: More than `MAX_REDIRECT_HOPS` hops would be needed.
    TOO_LONG = "too_long"
    #: The chain revisits an Entity.
    CYCLE = "cycle"
    #: An Entity of the chain is not the caller's (or not read).
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class Redirect:
    """The outcome of one redirect walk: a terminal Entity, or why there is none."""

    terminal: EntityNode | None
    failure: RedirectFailure | None
    hops: int


def walk_redirect(
    entity_id: str, nodes: Mapping[str, EntityNode], *, max_hops: int = MAX_REDIRECT_HOPS
) -> Redirect:
    """Follow `superseded_by_entity_id` while the Entity is `merged_redirect`.

    At most `max_hops` hops; a chain that needs more, or revisits an Entity,
    has no terminal. An Entity that is not in `nodes` (absent or another
    Principal's) is `missing`.
    """
    seen: set[str] = set()
    current = entity_id
    hops = 0
    while True:
        node = nodes.get(current)
        if node is None:
            return Redirect(terminal=None, failure=RedirectFailure.MISSING, hops=hops)
        if node.status != MERGED_REDIRECT:
            return Redirect(terminal=node, failure=None, hops=hops)
        seen.add(current)
        following = node.superseded_by_entity_id
        if following is None:
            # Unreachable under the schema's CHECK; read as an unresolvable chain.
            return Redirect(terminal=None, failure=RedirectFailure.MISSING, hops=hops)
        if following in seen:
            return Redirect(terminal=None, failure=RedirectFailure.CYCLE, hops=hops)
        if hops == max_hops:
            return Redirect(terminal=None, failure=RedirectFailure.TOO_LONG, hops=hops)
        hops += 1
        current = following


class WindowVerdict(StrEnum):
    """Where one edge stands against the evaluation instant (section 3.1 step 3)."""

    MEMBER = "member"
    OUTSIDE = "outside_window"
    START_NOT_RECORDED = MemberUnverifiedReason.START_NOT_RECORDED.value
    END_NOT_RECORDED = MemberUnverifiedReason.END_NOT_RECORDED.value


def window_verdict(edge: MemberEdge, at: datetime, mode: MembershipMode) -> WindowVerdict:
    """The section 3.1 step 3 window rule for one edge at instant `at`.

    Both modes apply the same window over the **recorded** dates: a start
    after `at`, or an end at or before `at`, is outside it, and an edge with no
    recorded end is in force only while it is `active` (an `ended` edge with no
    end is not a current member). Current mode admits a null start (the edge is
    recorded as in force now). Historical mode additionally separates what the
    dates prove: a member is verified only with a recorded start and either a
    recorded end or an `active` state; otherwise it is unverified, never a
    member, and no period is invented.
    """
    starts, ends = edge.effective_from, edge.effective_to
    if starts is not None and starts > at:
        return WindowVerdict.OUTSIDE
    if ends is not None and ends <= at:
        return WindowVerdict.OUTSIDE
    if mode is MembershipMode.CURRENT:
        if ends is not None or edge.state == _ACTIVE_EDGE:
            return WindowVerdict.MEMBER
        return WindowVerdict.OUTSIDE
    if starts is None:
        return WindowVerdict.START_NOT_RECORDED
    if ends is None and edge.state != _ACTIVE_EDGE:
        return WindowVerdict.END_NOT_RECORDED
    return WindowVerdict.MEMBER


def bridge_outcome(project_ids: Collection[str]) -> str | MemberUnresolvedReason:
    """Section 3.1 step 5: exactly one bound Project, else why there is none.

    No bound row is `bridge_missing` (an unresolved bridge row names no Entity,
    so it is never reachable from the member side); more than one -- possible
    only through a merge -- is `bridge_ambiguous`, and **no Project is chosen**.
    """
    distinct = set(project_ids)
    if not distinct:
        return MemberUnresolvedReason.BRIDGE_MISSING
    if len(distinct) > 1:
        return MemberUnresolvedReason.BRIDGE_AMBIGUOUS
    return next(iter(distinct))


def completeness(
    applicable: Iterable[ProgramCompleteness],
) -> tuple[ProgramCompleteness, tuple[ProgramCompleteness, ...]]:
    """`(complete_state, qualifiers)` for the applicable codes (section 3, S3 D-36).

    `complete` is the state only when no other code applies, and then it is
    the one qualifier; otherwise every applicable code, in precedence order,
    with `qualifiers[0]` the state.
    """
    codes = set(applicable) - {ProgramCompleteness.COMPLETE}
    if not codes:
        return ProgramCompleteness.COMPLETE, (ProgramCompleteness.COMPLETE,)
    ordered = tuple(code for code in PROGRAM_COMPLETENESS_PRECEDENCE if code in codes)
    return ordered[0], ordered


@dataclass(frozen=True, slots=True)
class RequestedProgram:
    """One requested Program after step 1: its terminal Entity and status."""

    program_entity_id: str
    resolved_program_entity_id: str
    program_status: str

    @property
    def redirected(self) -> bool:
        return self.resolved_program_entity_id != self.program_entity_id


@dataclass(frozen=True, slots=True)
class ProgramMember:
    """One exact member Project of one Program (deduplicated, section 3.1 step 6)."""

    project_id: str
    project_entity_id: str
    member_entity_status: str
    project_state: str
    relationship_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnresolvedMember:
    """An in-window member edge that names no exact Project (steps 4 and 5)."""

    relationship_id: str
    member_entity_id: str
    reason: MemberUnresolvedReason


@dataclass(frozen=True, slots=True)
class UnverifiedMember:
    """A historical edge whose recorded dates cannot prove membership (step 3)."""

    relationship_id: str
    member_entity_id: str
    project_id: str | None
    reason: MemberUnverifiedReason


@dataclass(frozen=True, slots=True)
class ProgramResolution:
    """The members of one requested Program, and what could not be proven."""

    program_entity_id: str
    resolved_program_entity_id: str
    redirected: bool
    program_status: str
    members: tuple[ProgramMember, ...]
    unresolved_members: tuple[UnresolvedMember, ...]
    unverified_members: tuple[UnverifiedMember, ...]
    non_project_members: int
    outside_window: int
    complete_state: ProgramCompleteness
    qualifiers: tuple[ProgramCompleteness, ...]

    @property
    def project_ids(self) -> tuple[str, ...]:
        return tuple(member.project_id for member in self.members)


@dataclass(frozen=True, slots=True)
class PortfolioOverlap:
    """A Project that is a member of more than one resolved Program."""

    project_id: str
    program_entity_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortfolioResolution:
    """Every member Project of the request once, and which ones overlap."""

    project_ids: tuple[str, ...]
    overlaps: tuple[PortfolioOverlap, ...]


@dataclass(frozen=True, slots=True)
class MembershipResolution:
    """One request's membership answer (section 7.1), before presentation."""

    mode: MembershipMode
    valid_at: datetime
    source_cutoff_at: datetime
    programs: tuple[ProgramResolution, ...]
    portfolio: PortfolioResolution
    complete_state: ProgramCompleteness
    qualifiers: tuple[ProgramCompleteness, ...]


def member_terminals(
    edges: Iterable[MemberEdge], nodes: Mapping[str, EntityNode]
) -> tuple[str, ...]:
    """The project-typed terminal Entities the edges' members resolve to (sorted).

    These are the Entities whose bridges step 5 reads.
    """
    terminals: set[str] = set()
    for edge in edges:
        walked = walk_redirect(edge.member_entity_id, nodes)
        if walked.terminal is not None and walked.terminal.entity_type == PROJECT_ENTITY_TYPE:
            terminals.add(walked.terminal.entity_id)
    return tuple(sorted(terminals))


@dataclass(slots=True)
class _Candidates:
    """What steps 3 to 5 found for one resolved Program, before the Project bound."""

    members: dict[str, tuple[str, str, list[str]]]
    unresolved: list[UnresolvedMember]
    unverified: list[UnverifiedMember]
    non_project: int = 0
    outside: int = 0


def _candidates(
    edges: Sequence[MemberEdge],
    *,
    at: datetime,
    mode: MembershipMode,
    nodes: Mapping[str, EntityNode],
    bridges: Mapping[str, Sequence[str]],
) -> _Candidates:
    found = _Candidates(members={}, unresolved=[], unverified=[])
    for edge in edges:
        verdict = window_verdict(edge, at, mode)
        if verdict is WindowVerdict.OUTSIDE:
            found.outside += 1
            continue
        walked = walk_redirect(edge.member_entity_id, nodes)
        terminal = walked.terminal
        if terminal is not None and terminal.entity_type != PROJECT_ENTITY_TYPE:
            # Step 4: a non-Project member, a nested Program included, is
            # counted and never expanded.
            found.non_project += 1
            continue
        outcome: str | MemberUnresolvedReason = (
            MemberUnresolvedReason.REDIRECT_UNRESOLVABLE
            if terminal is None
            else bridge_outcome(bridges.get(terminal.entity_id, ()))
        )
        if verdict is not WindowVerdict.MEMBER:
            found.unverified.append(
                UnverifiedMember(
                    relationship_id=edge.relationship_id,
                    member_entity_id=edge.member_entity_id,
                    project_id=None if isinstance(outcome, MemberUnresolvedReason) else outcome,
                    reason=MemberUnverifiedReason(verdict.value),
                )
            )
            continue
        if terminal is None or isinstance(outcome, MemberUnresolvedReason):
            found.unresolved.append(
                UnresolvedMember(
                    relationship_id=edge.relationship_id,
                    member_entity_id=edge.member_entity_id,
                    reason=(
                        outcome
                        if isinstance(outcome, MemberUnresolvedReason)
                        else MemberUnresolvedReason.REDIRECT_UNRESOLVABLE
                    ),
                )
            )
            continue
        _entity, _status, relationships = found.members.setdefault(
            outcome, (terminal.entity_id, terminal.status, [])
        )
        relationships.append(edge.relationship_id)
    return found


def assemble_membership(
    requested: Sequence[RequestedProgram],
    edges: Sequence[MemberEdge],
    *,
    mode: MembershipMode,
    at: datetime,
    source_cutoff_at: datetime,
    nodes: Mapping[str, EntityNode],
    bridges: Iterable[BridgeLink],
    project_states: Mapping[str, str],
    edge_overflow_program: str | None,
    max_projects: int = MAX_PROGRAM_PROJECTS,
) -> MembershipResolution:
    """Steps 3 to 6 over one request's fetched rows.

    `edges` are the request's member edges in `(terminal program in request
    order, relationship_id)` order, already cut at the edge budget;
    `edge_overflow_program` is the resolved Program of the first edge beyond
    that budget (`None` when the budget was not reached). Programs are
    processed in request order of their resolved Program: the one during
    which the edge or Project budget is reached, and every later one, carry
    `truncated_budget`; earlier ones do not; the portfolio carries it whenever
    any Program does. Members are kept in `project_id` order up to the
    Project budget.
    """
    by_entity: dict[str, list[str]] = {}
    for link in bridges:
        by_entity.setdefault(link.entity_id, []).append(link.project_id)
    edges_by_program: dict[str, list[MemberEdge]] = {}
    for edge in edges:
        edges_by_program.setdefault(edge.program_entity_id, []).append(edge)

    order: list[str] = []
    for program in requested:
        if program.resolved_program_entity_id not in order:
            order.append(program.resolved_program_entity_id)
    cut_at: int | None = (
        None if edge_overflow_program is None else order.index(edge_overflow_program)
    )

    kept: set[str] = set()
    resolved: dict[str, tuple[_Candidates, tuple[ProgramMember, ...]]] = {}
    for position, program_id in enumerate(order):
        found = _candidates(
            edges_by_program.get(program_id, ()),
            at=at,
            mode=mode,
            nodes=nodes,
            bridges=by_entity,
        )
        members: list[ProgramMember] = []
        for project_id in sorted(found.members):
            if project_id not in kept:
                if len(kept) >= max_projects:
                    if cut_at is None or position < cut_at:
                        cut_at = position
                    continue
                kept.add(project_id)
            entity_id, status, relationships = found.members[project_id]
            members.append(
                ProgramMember(
                    project_id=project_id,
                    project_entity_id=entity_id,
                    member_entity_status=status,
                    project_state=project_states[project_id],
                    relationship_ids=tuple(sorted(relationships)),
                )
            )
        resolved[program_id] = (found, tuple(members))

    programs: list[ProgramResolution] = []
    for program in requested:
        program_id = program.resolved_program_entity_id
        found, kept_members = resolved[program_id]
        codes: set[ProgramCompleteness] = set()
        if cut_at is not None and order.index(program_id) >= cut_at:
            codes.add(ProgramCompleteness.TRUNCATED_BUDGET)
        if found.unresolved:
            codes.add(ProgramCompleteness.MEMBERSHIP_UNRESOLVED)
        if found.unverified:
            codes.add(ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED)
        state, qualifiers = completeness(codes)
        programs.append(
            ProgramResolution(
                program_entity_id=program.program_entity_id,
                resolved_program_entity_id=program_id,
                redirected=program.redirected,
                program_status=program.program_status,
                members=kept_members,
                unresolved_members=tuple(
                    sorted(found.unresolved, key=lambda item: item.relationship_id)
                ),
                unverified_members=tuple(
                    sorted(found.unverified, key=lambda item: item.relationship_id)
                ),
                non_project_members=found.non_project,
                outside_window=found.outside,
                complete_state=state,
                qualifiers=qualifiers,
            )
        )

    reached: dict[str, set[str]] = {}
    for program_id in order:
        for member in resolved[program_id][1]:
            reached.setdefault(member.project_id, set()).add(program_id)
    portfolio = PortfolioResolution(
        project_ids=tuple(sorted(reached)),
        overlaps=tuple(
            PortfolioOverlap(project_id=project_id, program_entity_ids=tuple(sorted(programs_of)))
            for project_id, programs_of in sorted(reached.items())
            if len(programs_of) > 1
        ),
    )
    state, qualifiers = completeness(code for program in programs for code in program.qualifiers)
    return MembershipResolution(
        mode=mode,
        valid_at=at,
        source_cutoff_at=source_cutoff_at,
        programs=tuple(programs),
        portfolio=portfolio,
        complete_state=state,
        qualifiers=qualifiers,
    )
