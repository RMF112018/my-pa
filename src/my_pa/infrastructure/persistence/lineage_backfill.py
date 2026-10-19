"""The record lineage S3 backfill ledger, behind `contracts.ports.LineageBackfillRepository`.

S3 contract sections 4.2 and 8.3. This module holds the unit of work's seam for
the dry run's guarded ledger (`lineage_backfill_runs`, `lineage_backfill_items`)
and its one-statement enumeration over `knowledge.lineage_backfill_source_digest`;
the plan and report operations land with the backfill work package (S3 section
9, L5). Nothing here writes a link, a fact or a commit mark.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

from my_pa.contracts.ports import LineageBackfillRepository

__all__ = ["SqlLineageBackfillRepository"]


class SqlLineageBackfillRepository(LineageBackfillRepository):
    """`LineageBackfillRepository`, over the general unit of work's `Connection`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
