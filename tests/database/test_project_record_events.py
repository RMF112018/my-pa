"""WP-RE-02: Project update and close Record Events on a real database (RE-AC-029/030).

Marked `database` (auto `database_clone`), routed to `database-current-head`.
Through `ApplicationService` on the production SQL units of work:

* **RE-AC-029** -- `continuity.projects.update` commits one event only when
  APPLIED and not replayed: a rename is `updated`; a state-only change is
  `state_changed`; an identical update is still APPLIED (the version advances,
  G1-EM-010) and commits an `updated` event naming only `version`. A replay and a
  committed stale REJECTED receipt commit none and advance no sequence.
* **RE-AC-030** -- `continuity.projects.close` commits one `state_changed` event
  over `{state, closed_at}`.

Every identity here is synthetic.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from my_pa.application.commands import CloseProject, CreateProject, UpdateProject
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.situation.situation import ProjectState
from my_pa.infrastructure.persistence.tables import project_history
from tests.database.test_task_record_events import (
    Runtime,
    assert_gap_free,
    feed,
    next_sequence,
    runtime,
)

__all__ = ["runtime"]

pytestmark = pytest.mark.database


def _project(runtime: Runtime, key: str = "wp02-prj-0001") -> dict[str, Any]:
    return runtime.ok(CreateProject(name=f"Synthetic {key}", idempotency_key=key))


def _update(runtime: Runtime, project_id: str, version: int, key: str, **values: object) -> Any:  # noqa: ANN401
    return runtime.invoke(
        UpdateProject(
            project_id=project_id,
            expected_version=version,
            idempotency_key=key,
            **values,  # type: ignore[arg-type]
        )
    )


def test_a_rename_commits_one_updated_event(runtime: Runtime) -> None:
    project = _project(runtime)
    renamed = _update(runtime, project["project_id"], 1, "wp02-prj-upd-0001", name="Renamed")
    assert renamed.error is None
    event = feed(runtime.work_engine)[-1]
    assert event["record_family"] == "project"
    assert event["record_id"] == project["project_id"]
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["name", "version"]
    assert event["record_version"] == 2
    assert event["source_capability"] == "continuity.projects.update"
    with runtime.work_engine.connect() as connection:
        receipt = connection.execute(
            select(project_history.c.history_id).where(
                project_history.c.project_id == project["project_id"]
            )
        ).scalar_one()
    assert event["source_receipt_id"] == receipt
    assert_gap_free(runtime.work_engine)


def test_a_state_only_update_is_state_changed(runtime: Runtime) -> None:
    project = _project(runtime)
    _update(runtime, project["project_id"], 1, "wp02-prj-hold-0001", state=ProjectState.ON_HOLD)
    event = feed(runtime.work_engine)[-1]
    assert event["event_kind"] == "state_changed"
    assert event["changed_fields"] == ["state", "version"]


def test_an_identical_update_is_applied_and_names_only_the_version(runtime: Runtime) -> None:
    project = _project(runtime)
    same = _update(runtime, project["project_id"], 1, "wp02-prj-same-0001", name=project["name"])
    assert same.error is None and same.result is not None
    assert same.result["version"] == 2
    event = feed(runtime.work_engine)[-1]
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["version"]
    assert event["record_version"] == 2


def test_a_close_commits_one_state_changed_event(runtime: Runtime) -> None:
    project = _project(runtime)
    closed = runtime.invoke(
        CloseProject(
            project_id=project["project_id"],
            expected_version=1,
            idempotency_key="wp02-prj-close-0001",
        )
    )
    assert closed.error is None
    event = feed(runtime.work_engine)[-1]
    assert event["event_kind"] == "state_changed"
    assert event["changed_fields"] == ["closed_at", "state"]
    assert event["source_capability"] == "continuity.projects.close"
    assert event["record_version"] == 2
    assert_gap_free(runtime.work_engine)


def test_a_replay_and_a_committed_rejection_commit_nothing(runtime: Runtime) -> None:
    project = _project(runtime)
    _update(runtime, project["project_id"], 1, "wp02-prj-rep-0001", name="Once")
    before = (feed(runtime.work_engine), next_sequence(runtime.work_engine))
    replay = _update(runtime, project["project_id"], 1, "wp02-prj-rep-0001", name="Once")
    assert replay.error is None and replay.result is not None
    assert replay.result["replayed"] is True
    stale = _update(runtime, project["project_id"], 1, "wp02-prj-rep-0002", name="Stale")
    assert stale.error is not None and stale.error.code is ErrorCode.CONFLICT
    with runtime.work_engine.connect() as connection:
        outcomes = sorted(
            connection.execute(
                select(project_history.c.outcome).where(
                    project_history.c.project_id == project["project_id"]
                )
            ).scalars()
        )
    assert outcomes == ["applied", "rejected"]
    assert (feed(runtime.work_engine), next_sequence(runtime.work_engine)) == before
