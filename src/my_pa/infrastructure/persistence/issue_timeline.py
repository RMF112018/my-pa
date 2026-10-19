"""The record lineage S3 Issue timeline, behind `contracts.ports.IssueTimelineRepository`.

S3 contract section 7.3. This module holds the unit of work's seam for the
timeline reads (the lineage plane and the native plane through the Record Event
reader's own predicate); the reads themselves land with the timeline work
package (S3 section 9, L4). Reads take no locks.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

from my_pa.contracts.ports import IssueTimelineRepository

__all__ = ["SqlIssueTimelineRepository"]


class SqlIssueTimelineRepository(IssueTimelineRepository):
    """`IssueTimelineRepository`, over the general unit of work's `Connection`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
