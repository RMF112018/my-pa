"""T-12 (WP-RE-02): Project create commits the Project and its bound Entity (RE-AC-028).

Marked `database` (auto `database_clone`: the race below uses two connections),
routed to `database-current-head`.

* One `continuity.projects.create` commits exactly two events, in one allocator
  batch (consecutive sequence numbers): the Project `created`, then the bound
  project-type Entity `created`, whose `causation_event_id` names the Project
  event -- the NOT DEFERRABLE same-Principal reference is satisfied inside the
  batch. Neither names a receipt (both creates are unledgered, G1-EM-008).
* A replay commits nothing.
* Two concurrent creates of the same name: every create that commits, commits
  exactly its own pair, in its own batch, and a create that is refused commits
  none. (The transaction matrix expected the race to leave one pair. On this
  tree the bound-Entity name claim is an unlocked read with no unique index
  behind it, so both creates can commit; that is a pre-existing canonical gap,
  reported rather than changed here, and the feed invariant is stated against
  what actually commits.)

Every identity here is synthetic.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Final

import pytest
from sqlalchemy import select

from my_pa.application.commands import CreateProject
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.infrastructure.persistence.tables import project_entity_links, projects
from tests.database.test_task_record_events import (
    Runtime,
    assert_gap_free,
    feed,
    next_sequence,
    runtime,
)

__all__ = ["runtime"]

pytestmark = pytest.mark.database

JOIN_TIMEOUT_SECONDS: Final = 60.0


def test_a_create_commits_the_project_then_its_bound_entity_in_one_batch(
    runtime: Runtime,
) -> None:
    created = runtime.ok(CreateProject(name="Synthetic harbour", idempotency_key="wp02-pc-0001"))
    project_event, entity_event = feed(runtime.work_engine)
    with runtime.work_engine.connect() as connection:
        entity_id = connection.execute(
            select(project_entity_links.c.project_entity_id).where(
                project_entity_links.c.project_id == created["project_id"]
            )
        ).scalar_one()
    assert project_event["record_family"] == "project"
    assert project_event["record_id"] == created["project_id"]
    assert project_event["event_kind"] == "created"
    assert project_event["record_version"] == 1
    assert project_event["changed_fields"] == ["name", "opened_at", "state"]
    assert entity_event["record_family"] == "entity"
    assert entity_event["record_id"] == entity_id
    assert entity_event["event_kind"] == "created"
    assert entity_event["record_version"] == 1
    assert entity_event["causation_event_id"] == project_event["event_id"]
    assert project_event["causation_event_id"] is None
    assert project_event["source_receipt_id"] is None
    assert entity_event["source_receipt_id"] is None
    assert {project_event["source_capability"], entity_event["source_capability"]} == {
        "continuity.projects.create"
    }
    assert project_event["correlation_id"] == entity_event["correlation_id"]
    assert entity_event["sequence_number"] == project_event["sequence_number"] + 1
    assert_gap_free(runtime.work_engine)


def test_a_replayed_create_commits_nothing(runtime: Runtime) -> None:
    runtime.ok(CreateProject(name="Synthetic quay", idempotency_key="wp02-pc-rep-0001"))
    before = (feed(runtime.work_engine), next_sequence(runtime.work_engine))
    replay = runtime.ok(CreateProject(name="Synthetic quay", idempotency_key="wp02-pc-rep-0001"))
    assert replay["replayed"] is True
    assert (feed(runtime.work_engine), next_sequence(runtime.work_engine)) == before


def test_concurrent_creates_of_one_name_commit_one_pair_per_committed_create(
    runtime: Runtime,
) -> None:
    barrier = threading.Barrier(2, timeout=JOIN_TIMEOUT_SECONDS)

    def create(key: str) -> ResponseEnvelope:
        barrier.wait()
        return runtime.invoke(CreateProject(name="Contested name", idempotency_key=key))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [
            future.result(timeout=JOIN_TIMEOUT_SECONDS)
            for future in [pool.submit(create, f"wp02-pc-race-{index}") for index in (1, 2)]
        ]
    winners = [outcome.result for outcome in outcomes if outcome.error is None]
    assert winners, [outcome.error for outcome in outcomes]
    with runtime.work_engine.connect() as connection:
        stored = set(connection.execute(select(projects.c.project_id)).scalars())
    assert stored == {str(winner["project_id"]) for winner in winners if winner is not None}
    events = feed(runtime.work_engine)
    assert len(events) == 2 * len(stored)
    for project_event, entity_event in zip(events[::2], events[1::2], strict=True):
        assert project_event["record_family"] == "project"
        assert project_event["record_id"] in stored
        assert entity_event["record_family"] == "entity"
        assert entity_event["causation_event_id"] == project_event["event_id"]
        assert entity_event["sequence_number"] == project_event["sequence_number"] + 1
    assert {event["record_id"] for event in events[::2]} == stored
    assert_gap_free(runtime.work_engine)
