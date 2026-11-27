"""Exclude precisely marked fixture identities from ordinary persistence queries."""

from typing import cast

from sqlalchemy import ColumnElement, Table, and_, exists

from my_pa.infrastructure.persistence.principal_scope import capture_context, partition_criterion
from my_pa.infrastructure.persistence.tables import smoke_fixture_retirements

# Children carry the same Principal-partitioned identity as the fixture root.
# A dedicated series and scenario versions are also marked when their roots retire.
_FIXTURE_KEYS = (
    "message_id",
    "ingest_source_id",
    "series_id",
    "publication_id",
    "scenario_id",
    "version_id",
    "origin_publication_id",
    "origin_version_id",
    "intake_series_id",
    "intake_publication_id",
    "target_series_id",
    "resulting_publication_id",
)


def visible_fixture_partition(table: Table, principal_id: str) -> ColumnElement[bool]:
    context = capture_context(principal_id)
    partition = partition_criterion(table, context)
    root = getattr(table, "original", table)
    if not root.name.startswith(("communication_", "ingest_", "schedule_")):
        return partition
    keys = [table.c[key] for key in _FIXTURE_KEYS if key in table.c]
    if not keys:
        return partition
    retired = smoke_fixture_retirements.alias()
    return and_(
        partition,
        ~exists()
        .where(
            partition_criterion(cast(Table, retired), context),
            retired.c.record_id.in_(keys),
        )
        .correlate(table),
    )
