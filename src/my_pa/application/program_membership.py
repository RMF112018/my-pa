"""`programs.members.resolve` (record lineage S4 contract sections 3.1, 6.2 and 7.1, WP-04A).

The exact Continuity Projects of 1..10 Program Entities, from **one**
`REPEATABLE READ, READ ONLY` snapshot on the Program read pool (section 6.3):
the snapshot's first query, then the requested Programs with their redirect
chains, the member edges with their members' chains, the bridges and the
member Projects' states -- 5 statements whatever the size of the request. The
rule is the pure `domain.program.membership`; this module orders the reads,
refuses what section 7.5 refuses, and presents the answer.

`resolve_membership_in` is the same resolution inside an already-open Program
read unit of work, for `programs.overview` (section 7.2), which reads its
metrics in the same snapshot.

**Visibility (section 6.2).** A local caller sees every family of its
Principal. A remote caller sees a family only while it holds a grant, for one
of its purposes, on one of the family's reads (`PROGRAM_FAMILY_READS`); both
Program reads need `entity` **and** `project`, and without them every
requested Program answers `not_found` / `program_entity_ids`, exactly as an
absent or foreign one -- before anything is read.

Nothing here writes: the snapshot transaction is read-only and rolled back.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import ProgramReadUnitOfWork, ProgramSnapshot
from my_pa.contracts.v1.programs import ProgramMembershipView
from my_pa.domain.identity.operation import Capability, granted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.program.membership import (
    PROGRAM_ENTITY_TYPE,
    MembershipResolution,
    RequestedProgram,
    assemble_membership,
    member_terminals,
    walk_redirect,
)
from my_pa.domain.program.vocabulary import (
    MAX_MEMBER_EDGES,
    MAX_REDIRECT_HOPS,
    PROGRAM_FAMILY_READS,
    MembershipMode,
    ProgramFamily,
)

__all__ = [
    "PROGRAM_ROOT_FAMILIES",
    "program_families",
    "resolve_membership_in",
    "resolve_program_members",
]

type Grants = frozenset[tuple[Capability, Purpose | None]]

#: Section 6.2: both Program reads need these 2 families to see any Program.
PROGRAM_ROOT_FAMILIES: frozenset[ProgramFamily] = frozenset(
    {ProgramFamily.ENTITY, ProgramFamily.PROJECT}
)


def program_families(grants: Grants | None) -> frozenset[ProgramFamily]:
    """The section 6.2 families a caller sees: all locally, by grant remotely.

    A remote caller sees a family while it holds a grant, for one of that
    read's permitted purposes, on one of the family's reads; a grant for a
    purpose the read does not permit admits nothing.
    """
    if grants is None:
        return frozenset(ProgramFamily)
    return frozenset(
        family
        for family, reads in PROGRAM_FAMILY_READS.items()
        if any(granted_purposes(Capability(read), grants) for read in sorted(reads))
    )


def _requested(
    unit_of_work: ProgramReadUnitOfWork, principal_id: str, program_entity_ids: Sequence[str]
) -> tuple[RequestedProgram, ...]:
    """Step 1: each requested Program of this Principal, redirect-resolved, in request order.

    Absent and foreign answer alike (`not_found`); a chain longer than
    `MAX_REDIRECT_HOPS` or a cycle is `conflict`; a terminal that is not
    program-typed is `invalid_request`. The first refusal in request order
    answers.
    """
    nodes = {
        node.entity_id: node
        for node in unit_of_work.program_membership.entity_chains(
            principal_id, program_entity_ids, max_hops=MAX_REDIRECT_HOPS
        )
    }
    requested: list[RequestedProgram] = []
    for entity_id in program_entity_ids:
        if entity_id not in nodes:
            raise NotFoundError(SafeDetail.PROGRAM_ENTITY_IDS)
        walked = walk_redirect(entity_id, nodes)
        if walked.terminal is None:
            # Too long or cyclic; a chain Entity outside the partition is
            # unreachable under the principal-composite redirect key.
            raise ConflictError(SafeDetail.PROGRAM_ENTITY_IDS)
        if walked.terminal.entity_type != PROGRAM_ENTITY_TYPE:
            raise InvalidRequestError(SafeDetail.PROGRAM_ENTITY_IDS)
        requested.append(
            RequestedProgram(
                program_entity_id=entity_id,
                resolved_program_entity_id=walked.terminal.entity_id,
                program_status=walked.terminal.status,
            )
        )
    return tuple(requested)


def resolve_membership_in(
    unit_of_work: ProgramReadUnitOfWork,
    principal_id: str,
    program_entity_ids: Sequence[str],
    *,
    valid_at: datetime | None = None,
) -> tuple[ProgramSnapshot, MembershipResolution]:
    """Sections 3.1 and 3.4 inside an open Program read unit of work.

    Takes the snapshot (its first query) if it is not taken yet. Current mode
    without `valid_at` (the evaluation instant is `source_cutoff_at`);
    historical mode with it, which must not be after `source_cutoff_at`
    (`invalid_request` / `valid_at`). The caller has already applied the
    section 6.2 root-family rule.
    """
    snapshot = unit_of_work.snapshot(principal_id)
    cutoff = snapshot.source_cutoff_at
    if valid_at is not None and valid_at > cutoff:
        raise InvalidRequestError(SafeDetail.VALID_AT)
    mode = MembershipMode.CURRENT if valid_at is None else MembershipMode.HISTORICAL
    at = cutoff if valid_at is None else valid_at

    requested = _requested(unit_of_work, principal_id, program_entity_ids)
    order: list[str] = []
    for program in requested:
        if program.resolved_program_entity_id not in order:
            order.append(program.resolved_program_entity_id)

    repository = unit_of_work.program_membership
    fetched = repository.member_edges(
        principal_id, order, limit=MAX_MEMBER_EDGES, max_hops=MAX_REDIRECT_HOPS
    )
    nodes = {node.entity_id: node for node in fetched.entities}
    terminals = member_terminals(fetched.edges, nodes)
    bridges = repository.bridges(principal_id, terminals, max_hops=MAX_REDIRECT_HOPS)
    project_ids = sorted({link.project_id for link in bridges})
    project_states = repository.project_states(principal_id, project_ids)
    resolution = assemble_membership(
        requested,
        fetched.edges,
        mode=mode,
        at=at,
        source_cutoff_at=cutoff,
        nodes=nodes,
        bridges=bridges,
        project_states=project_states,
        edge_overflow_program=fetched.overflow_program,
    )
    return snapshot, resolution


def resolve_program_members(
    unit_of_work_factory: Callable[[], ProgramReadUnitOfWork],
    principal_id: str,
    program_entity_ids: Sequence[str],
    *,
    valid_at: datetime | None,
    families: frozenset[ProgramFamily],
) -> ProgramMembershipView:
    """`programs.members.resolve` (section 7.1), on its own Program read snapshot.

    A caller that does not see both the `entity` and the `project` family sees
    no Program: `not_found` / `program_entity_ids`, before any read.
    """
    if not families >= PROGRAM_ROOT_FAMILIES:
        raise NotFoundError(SafeDetail.PROGRAM_ENTITY_IDS)
    with unit_of_work_factory() as unit_of_work:
        _snapshot, resolution = resolve_membership_in(
            unit_of_work, principal_id, program_entity_ids, valid_at=valid_at
        )
        return ProgramMembershipView.of(resolution)
