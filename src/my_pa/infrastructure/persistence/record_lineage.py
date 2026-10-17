"""Record lineage persistence, Slice S1 (S1 contract sections 4.2 and 9).

`record_link_heads` is a derived projection with no in-place repair: its
trigger admits only the next revision and refuses every delete. What makes it
trustworthy is that it can be rebuilt. `rebuild_link_heads` derives every head
of one Principal from the immutable roots and revisions alone -- the latest
revision of each root, its lifecycle state, and the root's normalized
identity -- and reads nothing from `record_link_heads`, so comparing the two is
a real parity check rather than a read of the table against itself. A mismatch
is a defect to report, never something to rewrite: repair is an operator-gated
migration.

Read-only and lock-free (section 6.2: reads take no locks). Every statement is
Principal-scoped through `principal_scope`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.engine import Connection

from my_pa.domain.lineage.vocabulary import LinkLifecycleState
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    matching_partition_criterion,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import record_link_revisions, record_links

__all__ = ["LinkHeadRow", "rebuild_link_heads"]


@dataclass(frozen=True, slots=True)
class LinkHeadRow:
    """One `record_link_heads` row, as stored or as rebuilt."""

    principal_id: str
    link_id: str
    revision_no: int
    lifecycle_state: LinkLifecycleState
    normalized_identity: str


def rebuild_link_heads(
    connection: Connection, context: PrincipalContext | None
) -> tuple[LinkHeadRow, ...]:
    """Every head of the context's Principal, derived from roots and revisions.

    Ordered by `link_id`. A root with no revision yields no head, as the head
    table would hold none for it.
    """
    statement = principal_scoped(
        select(
            record_links.c.principal_id,
            record_links.c.link_id,
            record_links.c.normalized_identity,
            record_link_revisions.c.revision_no,
            record_link_revisions.c.lifecycle_state,
        )
        .select_from(record_links)
        .join(
            record_link_revisions,
            and_(
                matching_partition_criterion(record_links, record_link_revisions),
                record_link_revisions.c.link_id == record_links.c.link_id,
            ),
        )
        .order_by(record_links.c.link_id, record_link_revisions.c.revision_no),
        record_links,
        context,
    )
    latest: dict[str, LinkHeadRow] = {}
    for row in connection.execute(statement):
        latest[row.link_id] = LinkHeadRow(
            principal_id=row.principal_id,
            link_id=row.link_id,
            revision_no=row.revision_no,
            lifecycle_state=LinkLifecycleState(row.lifecycle_state),
            normalized_identity=row.normalized_identity,
        )
    return tuple(latest[link_id] for link_id in sorted(latest))
