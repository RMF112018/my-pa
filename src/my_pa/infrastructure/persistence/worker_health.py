"""Content-free worker heartbeat and backlog health reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, ENROLLMENT_JOBS, JobPlane
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import JobState, worker_heartbeats


@dataclass(frozen=True, slots=True)
class WorkerPlaneHealth:
    plane: str
    state: str
    backlog: int
    dead_lettered: int
    last_heartbeat_at: datetime | None


def record_worker_heartbeat(
    connection: Connection,
    *,
    owner: str,
    principal_id: str,
    plane: str,
    stopped: bool = False,
) -> None:
    validate_identifier(principal_id, IdKind.PRINCIPAL)
    # `reenrichment` is admitted here and not in `worker_plane_health` below: the
    # re-enrichment worker reports liveness like the other two, and its backlog
    # lives in its own table rather than in a `JobPlane`, so the read below has
    # nothing to answer for it and says so by refusing rather than by returning a
    # zero backlog that would read as "idle".
    if plane not in {"capture", "enrollment", "reenrichment"}:
        raise ValueError("unknown worker plane")
    context = capture_context(principal_id)
    statement = insert(worker_heartbeats).values(
        principal_bound_values(
            {
                "worker_owner": owner,
                "plane": plane,
                "stopped_at": func.now() if stopped else None,
            },
            worker_heartbeats,
            context,
        )
    )
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[
                worker_heartbeats.c.worker_owner,
                worker_heartbeats.c.principal_id,
            ],
            set_={
                "heartbeat_at": func.now(),
                "stopped_at": func.now() if stopped else None,
            },
        )
    )


def worker_plane_health(
    connection: Connection,
    *,
    principal_id: str,
    plane_name: str,
    stale_after: timedelta = timedelta(minutes=6),
) -> WorkerPlaneHealth:
    validate_identifier(principal_id, IdKind.PRINCIPAL)
    planes: dict[str, JobPlane] = {"capture": CAPTURE_JOBS, "enrollment": ENROLLMENT_JOBS}
    if plane_name not in planes:
        raise ValueError("unknown worker plane")
    plane = planes[plane_name]
    mine = partition_criterion(plane.table, capture_context(principal_id))
    backlog = int(
        connection.scalar(
            select(func.count())
            .select_from(plane.table)
            .where(mine, plane.table.c.state.in_([JobState.QUEUED.value, JobState.RUNNING.value]))
        )
        or 0
    )
    dead = int(
        connection.scalar(
            select(func.count())
            .select_from(plane.table)
            .where(mine, plane.table.c.state == JobState.FAILED.value)
        )
        or 0
    )
    context = capture_context(principal_id)
    heartbeat = connection.execute(
        select(worker_heartbeats.c.heartbeat_at, worker_heartbeats.c.stopped_at)
        .where(
            partition_criterion(worker_heartbeats, context),
            worker_heartbeats.c.plane == plane_name,
        )
        .order_by(worker_heartbeats.c.heartbeat_at.desc())
        .limit(1)
    ).one_or_none()
    last = None if heartbeat is None else heartbeat.heartbeat_at
    if backlog == 0:
        state = "idle_or_not_required"
    elif heartbeat is None or heartbeat.stopped_at is not None:
        state = "worker_absent"
    elif last is None or datetime.now(last.tzinfo) - last > stale_after:
        state = "worker_stale"
    else:
        state = "working"
    return WorkerPlaneHealth(plane_name, state, backlog, dead, last)
