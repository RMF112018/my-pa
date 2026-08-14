"""Retry after commit does not duplicate a Task."""

from __future__ import annotations

import pytest
from tests.conftest import World, build_service, metadata_for, operator

from my_pa.application.commands import CreateTask
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

pytestmark = pytest.mark.recovery


def test_transport_retry_after_commit_returns_the_original_task() -> None:
    world = World()
    principal = operator()
    service = build_service(world, world.providers)
    command = CreateTask(title="do not duplicate", idempotency_key="retry-after-0001")
    first = service.invoke(
        metadata_for(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING, principal),
        command,
        principal=principal,
    )
    second = service.invoke(
        metadata_for(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING, principal),
        command,
        principal=principal,
    )
    assert first.result["task"]["task_id"] == second.result["task"]["task_id"]
    assert len(world.task_rows) == 1
