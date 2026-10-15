"""Reconcile legacy `unresolved_missing` Project↔Entity bridge rows (WP-MCP-PROJ-05).

`9f2c8a1d4e70` (WP-MCP-PROJ-01) created `knowledge.project_entity_links` and
backfilled every pre-existing Continuity Project with an `unresolved_missing`
row and a null entity id: "Nothing here mints an Entity and nothing joins on a
name" by that revision's own docstring. `continuity.projects.create`'s
`_mint_bound_project_entity`
(`infrastructure.persistence.continuity_authoring.SqlContinuityAuthoringRepository`)
mints a bound Entity for every *new* Project, atomically, but nothing was ever
written to resolve the backfilled rows. Until a caller happens to name a
`project_id` through `entities.participations.create`/`.list`,
`ApplicationService._bound_project_entity_id` correctly refuses with
`ConflictError(SafeDetail.PROJECT_ID)` — that refusal is the right behavior for
an unresolved link, not the defect. The defect is that nothing ever resolves
the link, and this module is that missing step.

**Why this is a Python function, not a pure-SQL migration.** Every other
data-only migration in this chain (`6f6ead27d122`, the closest structural
precedent) is pure `op.execute(...)` SQL with no Python or domain imports, by
deliberate convention — `9f2c8a1d4e70` itself freezes its vocabulary literals
rather than importing domain enums, for the same reason. This reconciliation
cannot follow that convention: it must decide whether two Project names are
"the same" using `normalize_name`
(`my_pa.domain.relationship.normalization`), which is real comparison logic
(Unicode normalization, case folding, punctuation handling) that this task's
own constraints forbid reimplementing in SQL, and it must mint fresh Entity
identifiers using `issue_identifier(IdKind.ENTITY)`
(`my_pa.domain.source.registry`), which is `secrets.token_hex`-backed and has
no SQL equivalent. Importing both from a migration is therefore a deliberate,
narrow exception to the pure-SQL precedent, scoped to exactly the two
functions this reconciliation cannot do without. The function lives here
rather than inside the migration module so it is equally callable from a
future admin capability without duplicating the logic.

**The one invariant this module must never violate: no auto-merge on a name
match.** `_mint_bound_project_entity` already treats an existing
same-canonical-name project-type Entity as a hard error when minting for a
*new* Project (`raise ValueError(...)`), because binding two Projects' worth of
history onto one Entity from a name collision is exactly the false-join this
system is built to avoid elsewhere (see `normalization.py`'s module docstring
for the same bias, stated for People). This reconciliation reuses that
candidate-search shape but cannot raise on a legacy row — the row must survive
reconciliation in *some* resolved state — so it branches instead: zero
candidates mints and binds (safe, because nothing else claims that name);
one or more candidates is left for a human, flagged
`unresolved_ambiguous`, never bound automatically.

**Processing order matters.** Rows are processed one at a time, each with a
fresh candidate query, specifically so two unresolved rows that share a
canonical name in the same run do not both mint: the first row to see zero
candidates mints and binds, and the second row's candidate query then sees
that freshly minted Entity and flags ambiguous rather than minting a
duplicate. A single batched candidate SELECT computed once for the whole run
would miss this and either mint two Entities for one name or silently depend
on dict/set iteration order for correctness; this function does neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.engine import Connection

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.situation.situation import ProjectEntityLinkageState
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import entities, project_entity_links, projects

__all__ = [
    "ReconciliationOutcome",
    "ReconciliationRecord",
    "ReconciliationReport",
    "reconcile_project_entity_links",
]

_CANDIDATE_STATUSES: tuple[str, ...] = (
    EntityStatus.ACTIVE.value,
    EntityStatus.INACTIVE.value,
    EntityStatus.HISTORICAL.value,
)


class ReconciliationOutcome(StrEnum):
    """What happened to one `project_entity_links` row during a reconciliation pass."""

    #: Zero candidates existed; a new project-type Entity was minted and bound.
    MINTED_AND_BOUND = "minted_and_bound"
    #: One or more candidates existed; the row was flagged, never auto-bound.
    FLAGGED_AMBIGUOUS = "flagged_ambiguous"
    #: The row was already `bound`; left untouched.
    ALREADY_BOUND_NOOP = "already_bound_noop"
    #: The row was already `unresolved_ambiguous`; left untouched.
    ALREADY_AMBIGUOUS_NOOP = "already_ambiguous_noop"


@dataclass(frozen=True)
class ReconciliationRecord:
    """One Project's reconciliation outcome, for the register and for tests.

    `detail` carries the minted entity id (one element) for `MINTED_AND_BOUND`,
    the already-bound entity id (one element) for `ALREADY_BOUND_NOOP`, the
    candidate entity ids (one or more) for `FLAGGED_AMBIGUOUS`, and is empty
    for `ALREADY_AMBIGUOUS_NOOP`.
    """

    principal_id: str
    project_id: str
    outcome: ReconciliationOutcome
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciliationReport:
    """Every row a reconciliation pass visited, in processing order."""

    records: tuple[ReconciliationRecord, ...]

    @property
    def minted_count(self) -> int:
        return sum(
            1 for record in self.records if record.outcome is ReconciliationOutcome.MINTED_AND_BOUND
        )

    @property
    def ambiguous_count(self) -> int:
        return sum(
            1
            for record in self.records
            if record.outcome is ReconciliationOutcome.FLAGGED_AMBIGUOUS
        )


def reconcile_project_entity_links(
    connection: Connection, *, principal_id: str | None = None
) -> ReconciliationReport:
    """Resolve every `project_entity_links` row for `principal_id`, or all of them.

    Runs on `connection` as given — callers (a migration's `upgrade()`, or a
    future admin capability inside its own unit of work) own the transaction
    boundary. Idempotent: a row already `bound` or `unresolved_ambiguous` is
    left untouched, so calling this twice on the same connection and data
    produces the same end state the second time, with every record reported
    as one of the two no-op outcomes.
    """
    now = utc_now()
    link_rows_query = select(
        project_entity_links.c.principal_id,
        project_entity_links.c.project_id,
        project_entity_links.c.linkage_state,
        project_entity_links.c.project_entity_id,
    ).order_by(project_entity_links.c.principal_id, project_entity_links.c.project_id)
    if principal_id is not None:
        link_rows_query = link_rows_query.where(
            project_entity_links.c.principal_id == principal_id
        )
    # Listed once, up front, in a deterministic order. Each row is still
    # resolved with a *fresh* candidate query at the time it is processed
    # (not from this snapshot), which is what lets an earlier row's mint
    # become a later row's ambiguous candidate within the same pass.
    rows = connection.execute(link_rows_query).all()
    records = [
        _reconcile_one_row(
            connection,
            principal_id=row.principal_id,
            project_id=row.project_id,
            linkage_state=row.linkage_state,
            existing_entity_id=row.project_entity_id,
            now=now,
        )
        for row in rows
    ]
    return ReconciliationReport(records=tuple(records))


def _reconcile_one_row(
    connection: Connection,
    *,
    principal_id: str,
    project_id: str,
    linkage_state: str,
    existing_entity_id: str | None,
    now: datetime,
) -> ReconciliationRecord:
    if linkage_state == ProjectEntityLinkageState.BOUND.value:
        detail = (existing_entity_id,) if existing_entity_id is not None else ()
        return ReconciliationRecord(
            principal_id, project_id, ReconciliationOutcome.ALREADY_BOUND_NOOP, detail
        )
    if linkage_state == ProjectEntityLinkageState.UNRESOLVED_AMBIGUOUS.value:
        return ReconciliationRecord(
            principal_id, project_id, ReconciliationOutcome.ALREADY_AMBIGUOUS_NOOP
        )
    # Only `unresolved_missing` reaches here; the CHECK
    # `a_project_entity_link_state_is_known` admits no fourth state.
    project_name = connection.execute(
        select(projects.c.name).where(
            projects.c.principal_id == principal_id,
            projects.c.project_id == project_id,
        )
    ).scalar_one()
    canonical_name = normalize_name(project_name)
    candidate_ids = tuple(
        connection.execute(
            select(entities.c.entity_id).where(
                entities.c.principal_id == principal_id,
                entities.c.entity_type == EntityType.PROJECT.value,
                entities.c.canonical_name == canonical_name,
                entities.c.status.in_(_CANDIDATE_STATUSES),
            )
        ).scalars()
    )
    if not candidate_ids:
        entity_id = issue_identifier(IdKind.ENTITY)
        connection.execute(
            entities.insert().values(
                entity_id=entity_id,
                principal_id=principal_id,
                entity_type=EntityType.PROJECT.value,
                canonical_name=canonical_name,
                display_name=project_name,
                status=EntityStatus.ACTIVE.value,
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            project_entity_links.update()
            .where(
                project_entity_links.c.principal_id == principal_id,
                project_entity_links.c.project_id == project_id,
            )
            .values(
                linkage_state=ProjectEntityLinkageState.BOUND.value,
                project_entity_id=entity_id,
                updated_at=now,
            )
        )
        return ReconciliationRecord(
            principal_id, project_id, ReconciliationOutcome.MINTED_AND_BOUND, (entity_id,)
        )
    # One or more candidates: never auto-bind on a name match. Flag for a
    # human to resolve; `project_entity_id` stays NULL, as
    # `a_bound_project_entity_link_names_its_entity` requires for a row that
    # is not `bound`.
    connection.execute(
        project_entity_links.update()
        .where(
            project_entity_links.c.principal_id == principal_id,
            project_entity_links.c.project_id == project_id,
        )
        .values(
            linkage_state=ProjectEntityLinkageState.UNRESOLVED_AMBIGUOUS.value,
            project_entity_id=None,
            updated_at=now,
        )
    )
    return ReconciliationRecord(
        principal_id, project_id, ReconciliationOutcome.FLAGGED_AMBIGUOUS, candidate_ids
    )
