"""WP-RE-03: `constraint_sync.apply` and `constraint_sync.resolve` Record Events (RE-AC-040).

Marked `database` (auto `database_clone`), routed to `database-current-head`.
Both commands go through `ApplicationService` on the production Constraint unit
of work. The synchronization plane's own rows -- the target, the run, its
items, the conflict and the resolution receipt -- are control rows and commit no
Record Event (G1-EM-005); only the canonical Constraint change a sync makes
does, as actor `system` under the request's exact capability.

The run and conflict are seeded directly in the state the preview and
acknowledge steps would have left them in, so the test isolates exactly the
apply and resolve writes. Every identity here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, null, select

from my_pa.application.commands import ApplyConstraintSync, ResolveConstraintSyncConflict
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.project_controls.constraint import ProjectConstraint
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.domain.project_controls.sync import ConstraintSyncResolution
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    constraint_sync_conflicts,
    constraint_sync_resolution_history,
    constraint_sync_run_items,
    constraint_sync_runs,
    constraint_sync_targets,
)
from tests.database.test_constraint_management_service import (
    PRINCIPAL_A,
    PROJECT_A,
    _category,
    _published,
    _service,
)
from tests.database.test_constraint_record_events import (
    REQUESTED_AT,
    ConstraintRuntime,
    runtime,
)
from tests.database.test_task_record_events import assert_gap_free, feed

__all__ = ["runtime"]

pytestmark = pytest.mark.database

LEASE: Final = "a" * 64
PREVIEW_DIGEST: Final = "b" * 64
LEASE_UNTIL: Final = REQUESTED_AT + timedelta(days=30)
T0: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _candidate(record: ProjectConstraint, row_key: str, **changes: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "external_row_key": row_key,
        "constraint_id": record.constraint_id,
        "constraint_code": record.constraint_code,
        "category": record.category_id,
        "description": record.description,
        "date_identified": None
        if record.date_identified is None
        else record.date_identified.isoformat(),
        "status": record.lifecycle_state.value,
        "bic": [],
        "responsible": [],
        "due_date": None if record.due_date is None else record.due_date.isoformat(),
        "reference": record.reference,
        "current_update": record.current_update,
        "completion_date": None,
    }
    candidate.update(changes)
    return candidate


def seed_active_run(engine: Engine) -> tuple[str, str]:
    """A target whose active, leased run is `previewed`: `(target_id, run_id)`."""
    target_id = issue_identifier(IdKind.CONSTRAINT_SYNC_TARGET)
    run_id = issue_identifier(IdKind.CONSTRAINT_SYNC_RUN)
    with engine.begin() as connection:
        connection.execute(
            insert(constraint_sync_targets).values(
                sync_target_id=target_id,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                external_kind="excel_workbook",
                external_identity=f"synthetic-{target_id}",
                normalization_contract_version="v1",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        connection.execute(
            insert(constraint_sync_runs).values(
                sync_run_id=run_id,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                sync_target_id=target_id,
                state="previewed",
                sync_state="external_import_pending",
                lease_token=LEASE,
                preview_lease_until=LEASE_UNTIL,
                preview_digest=PREVIEW_DIGEST,
                preview_idempotency_key=f"preview_{run_id}",
                preview_request_digest="c" * 64,
                started_at=T0,
                created_at=T0,
                updated_at=T0,
            )
        )
        connection.execute(
            constraint_sync_targets.update()
            .where(constraint_sync_targets.c.sync_target_id == target_id)
            .values(active_run_id=run_id, active_run_lease_until=LEASE_UNTIL, last_run_id=run_id)
        )
    return target_id, run_id


def seed_item(
    engine: Engine,
    target_id: str,
    run_id: str,
    record: ProjectConstraint,
    *,
    row_key: str,
    action: str,
    field_names: list[str],
    candidate: dict[str, object] | None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(constraint_sync_run_items).values(
                sync_run_id=run_id,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                sync_target_id=target_id,
                external_row_key=row_key,
                constraint_id=record.constraint_id,
                action=action,
                expected_constraint_version=record.version,
                external_candidate=null() if candidate is None else candidate,
                field_names=field_names,
                response_summary={},
                created_at=T0,
                updated_at=T0,
            )
        )


def _apply(runtime: ConstraintRuntime, target_id: str, run_id: str, key: str) -> Any:  # noqa: ANN401
    return runtime.invoke(
        ApplyConstraintSync(
            project_id=PROJECT_A,
            target_id=target_id,
            run_id=run_id,
            lease_token=LEASE,
            preview_digest=PREVIEW_DIGEST,
            idempotency_key=key,
        )
    )


def test_sync_apply_commits_only_the_canonical_change(runtime: ConstraintRuntime) -> None:
    changed = _published(runtime.engine, _category_id(runtime))
    untouched = _published(runtime.engine, _category_id(runtime, prefix="EEE"))
    target_id, run_id = seed_active_run(runtime.engine)
    seed_item(
        runtime.engine,
        target_id,
        run_id,
        changed,
        row_key="row-1",
        action="merge",
        field_names=["description"],
        candidate=_candidate(changed, "row-1", description="Stamped set received."),
    )
    seed_item(
        runtime.engine,
        target_id,
        run_id,
        untouched,
        row_key="row-2",
        action="no_op",
        field_names=[],
        candidate=None,
    )
    before = len(feed(runtime.engine, PRINCIPAL_A))
    response = _apply(runtime, target_id, run_id, "sync_apply_rcev_0001")
    assert response.error is None, response.error
    events = feed(runtime.engine, PRINCIPAL_A)[before:]
    assert len(events) == 1, events
    (event,) = events
    assert event["record_id"] == changed.constraint_id
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["description"]
    assert event["source_capability"] == "constraint_sync.apply"
    assert event["actor_class"] == "system"
    assert event["correlation_id"] == response.correlation_id
    with runtime.engine.connect() as connection:
        state = connection.execute(
            select(constraint_sync_runs.c.state).where(constraint_sync_runs.c.sync_run_id == run_id)
        ).scalar_one()
    assert state == "applied"  # the control rows were written, with no event
    assert_gap_free(runtime.engine, PRINCIPAL_A)
    replay = _apply(runtime, target_id, run_id, "sync_apply_rcev_0001")
    assert replay.error is None
    assert len(feed(runtime.engine, PRINCIPAL_A)) == before + 1


def _conflict(
    runtime: ConstraintRuntime,
    record: ProjectConstraint,
    field: str,
    candidate: dict[str, object],
    kind: str = "both_changed",
) -> str:
    target_id, run_id = seed_active_run(runtime.engine)
    conflict_id = issue_identifier(IdKind.CONSTRAINT_SYNC_CONFLICT)
    with runtime.engine.begin() as connection:
        connection.execute(
            insert(constraint_sync_conflicts).values(
                sync_conflict_id=conflict_id,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                sync_target_id=target_id,
                constraint_id=record.constraint_id,
                sync_run_id=run_id,
                conflict_kind=kind,
                field_names=[field],
                external_candidate=null() if candidate is None else candidate,
                state="open",
                created_at=T0,
            )
        )
    return conflict_id


def _resolve(
    runtime: ConstraintRuntime,
    conflict_id: str,
    resolution: ConstraintSyncResolution,
    version: int,
    key: str,
    manual_patch: dict[str, object] | None = None,
) -> Any:  # noqa: ANN401
    return runtime.invoke(
        ResolveConstraintSyncConflict(
            project_id=PROJECT_A,
            conflict_id=conflict_id,
            resolution=resolution,
            expected_version=version,
            idempotency_key=key,
            manual_patch=manual_patch,
        )
    )


def test_sync_resolve_accepting_the_external_value_commits_one_event(
    runtime: ConstraintRuntime,
) -> None:
    record = _published(runtime.engine, _category_id(runtime))
    conflict_id = _conflict(
        runtime,
        record,
        "description",
        _candidate(record, "row-9", description="The external description."),
    )
    before = len(feed(runtime.engine, PRINCIPAL_A))
    response = _resolve(
        runtime,
        conflict_id,
        ConstraintSyncResolution.ACCEPT_EXTERNAL,
        record.version,
        "sync_resolve_rcev_0001",
    )
    assert response.error is None, response.error
    (event,) = feed(runtime.engine, PRINCIPAL_A)[before:]
    assert event["record_id"] == record.constraint_id
    assert event["event_kind"] == "updated"
    assert event["source_capability"] == "constraint_sync.resolve"
    assert event["actor_class"] == "system"
    with runtime.engine.connect() as connection:
        resolutions = connection.execute(
            select(constraint_sync_resolution_history.c.resolution_history_id).where(
                constraint_sync_resolution_history.c.sync_conflict_id == conflict_id
            )
        ).all()
    assert len(resolutions) == 1  # the control receipt committed, with no event of its own


def test_sync_resolve_keeping_the_canonical_value_commits_no_event(
    runtime: ConstraintRuntime,
) -> None:
    record = _published(runtime.engine, _category_id(runtime))
    conflict_id = _conflict(
        runtime, record, "description", _candidate(record, "row-8", description="Ignored.")
    )
    before = len(feed(runtime.engine, PRINCIPAL_A))
    response = _resolve(
        runtime,
        conflict_id,
        ConstraintSyncResolution.KEEP_CANONICAL,
        record.version,
        "sync_resolve_rcev_0002",
    )
    assert response.error is None, response.error
    assert len(feed(runtime.engine, PRINCIPAL_A)) == before


def _category_id(runtime: ConstraintRuntime, *, prefix: str = "DDD") -> str:
    return _category(runtime.engine, prefix=prefix)


def test_sync_resolve_by_manual_patch_commits_one_event(runtime: ConstraintRuntime) -> None:
    record = _published(runtime.engine, _category_id(runtime))
    conflict_id = _conflict(
        runtime, record, "reference", _candidate(record, "row-7", reference="EXT-1")
    )
    before = len(feed(runtime.engine, PRINCIPAL_A))
    response = _resolve(
        runtime,
        conflict_id,
        ConstraintSyncResolution.MANUAL_PATCH,
        record.version,
        "sync_resolve_rcev_0003",
        manual_patch={"reference": "RFI-MANUAL"},
    )
    assert response.error is None, response.error
    (event,) = feed(runtime.engine, PRINCIPAL_A)[before:]
    assert event["changed_fields"] == ["reference"]
    assert event["source_capability"] == "constraint_sync.resolve"
    assert event["actor_class"] == "system"


def test_sync_resolve_by_reopen_commits_one_state_changed_event(
    runtime: ConstraintRuntime,
) -> None:
    published = _published(runtime.engine, _category_id(runtime))
    closed = (
        _service(runtime.engine)
        .close(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            completion_date=date(2026, 9, 3),
        )
        .record
    )
    conflict_id = _conflict(
        runtime,
        closed,
        "status",
        _candidate(closed, "row-6", status="in_progress", completion_date=None),
        kind="lifecycle",
    )
    before = len(feed(runtime.engine, PRINCIPAL_A))
    response = _resolve(
        runtime,
        conflict_id,
        ConstraintSyncResolution.REOPEN,
        closed.version,
        "sync_resolve_rcev_0004",
    )
    assert response.error is None, response.error
    (event,) = feed(runtime.engine, PRINCIPAL_A)[before:]
    assert event["record_id"] == closed.constraint_id
    assert event["event_kind"] == "state_changed"
    assert event["source_capability"] == "constraint_sync.resolve"
