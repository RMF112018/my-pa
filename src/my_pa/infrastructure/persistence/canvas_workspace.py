"""Principal-partitioned product-owned canvas workspace overlays (ADR-003)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from sqlalchemy import Connection, select
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError

from my_pa.contracts.ports import CanvasWorkspaceConflictError, CanvasWorkspaceRecord
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import canvas_workspaces

__all__ = [
    "get_canvas_workspace",
    "insert_canvas_workspace",
    "update_canvas_workspace",
]


def _positions(value: object) -> Mapping[str, Mapping[str, float]]:
    if not isinstance(value, Mapping):
        return MappingProxyType({})
    points: dict[str, Mapping[str, float]] = {}
    for entity_id, point in value.items():
        if not isinstance(entity_id, str) or not isinstance(point, Mapping):
            continue
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, bool) or isinstance(y, bool):
            continue
        if not isinstance(x, int | float) or not isinstance(y, int | float):
            continue
        points[entity_id] = MappingProxyType({"x": float(x), "y": float(y)})
    return MappingProxyType(points)


def _record(row: Row[tuple[object, ...]]) -> CanvasWorkspaceRecord:
    return CanvasWorkspaceRecord(
        principal_id=row.principal_id,
        focus_entity_id=row.focus_entity_id,
        scope_entity_id=row.scope_entity_id,
        version=row.version,
        positions=_positions(row.positions),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _seed(focus_entity_id: str | None, scope_entity_id: str | None) -> tuple[object, object]:
    return (
        canvas_workspaces.c.focus_entity_id.is_not_distinct_from(focus_entity_id),
        canvas_workspaces.c.scope_entity_id.is_not_distinct_from(scope_entity_id),
    )


def get_canvas_workspace(
    connection: Connection,
    principal_id: str,
    focus_entity_id: str | None,
    scope_entity_id: str | None,
) -> CanvasWorkspaceRecord | None:
    """The overlay in `principal_id`'s partition for this seed, or `None`."""
    context = capture_context(principal_id)
    focus_match, scope_match = _seed(focus_entity_id, scope_entity_id)
    row = connection.execute(
        select(canvas_workspaces).where(
            partition_criterion(canvas_workspaces, context),
            focus_match,
            scope_match,
        )
    ).one_or_none()
    return None if row is None else _record(row)


def insert_canvas_workspace(
    connection: Connection, record: CanvasWorkspaceRecord
) -> CanvasWorkspaceRecord:
    """Store the first version of an overlay. Unique-seed races conflict."""
    context = capture_context(record.principal_id)
    values = principal_bound_values(
        {
            "focus_entity_id": record.focus_entity_id,
            "scope_entity_id": record.scope_entity_id,
            "version": record.version,
            "positions": dict(record.positions),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        },
        canvas_workspaces,
        context,
    )
    try:
        connection.execute(canvas_workspaces.insert().values(**values))
    except IntegrityError as error:
        raise CanvasWorkspaceConflictError() from error
    stored = get_canvas_workspace(
        connection,
        record.principal_id,
        record.focus_entity_id,
        record.scope_entity_id,
    )
    if stored is None:
        raise CanvasWorkspaceConflictError()
    return stored


def update_canvas_workspace(
    connection: Connection,
    record: CanvasWorkspaceRecord,
    *,
    expected_version: int,
) -> CanvasWorkspaceRecord:
    """Replace positions when the stored version is still `expected_version`."""
    context = capture_context(record.principal_id)
    focus_match, scope_match = _seed(record.focus_entity_id, record.scope_entity_id)
    result = connection.execute(
        canvas_workspaces.update()
        .where(
            partition_criterion(canvas_workspaces, context),
            focus_match,
            scope_match,
            canvas_workspaces.c.version == expected_version,
        )
        .values(
            version=record.version,
            positions=dict(record.positions),
            updated_at=record.updated_at,
        )
    )
    if result.rowcount != 1:
        raise CanvasWorkspaceConflictError()
    stored = get_canvas_workspace(
        connection,
        record.principal_id,
        record.focus_entity_id,
        record.scope_entity_id,
    )
    if stored is None:
        raise CanvasWorkspaceConflictError()
    return stored
