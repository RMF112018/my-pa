"""WP-RE-08 (Amendment 02 (4)): after a grant change, re-list from the start (RE-AC-107).

Marked `database` and routed to `database-current-head`. One Principal holds
`task`, `capture` and `task_comment` events; a remote caller lists them under
changing grants through the production `ApplicationService`:

1. under G1 (the list grant plus `tasks.read`, `capture.read`,
   `tasks.comments.list`) it pages with a cursor;
2. **narrowed** to G2 = G1 - `capture.read`: the G1 cursor is
   `conflict(cursor)`, and a list from the start returns every `task` and
   `task_comment` event and no `capture` event;
3. **restored** to G1: a G2 cursor is `conflict(cursor)`, and a list from the
   start returns the full history -- every capture event written before the
   narrowing, none lost;
4. **widened** by a second read of a visible family (`tasks.list`): the visible
   set is unchanged, but `grant_digest` is not, so the G1 cursor is
   `conflict(cursor)`.

The committed row count and the allocator's `next_sequence` never move:
nothing was deleted or re-keyed. Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import func, select

from my_pa.application.commands import (
    Command,
    CreateCapture,
    CreateTask,
    CreateTaskComment,
    ListRecordEvents,
    ReviseCapture,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.tables import record_events
from tests.database.test_task_record_events import Runtime, next_sequence

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 9, 30, 12, tzinfo=UTC)

type Grants = frozenset[tuple[Capability, Purpose | None]]


def grants(*capabilities: Capability) -> Grants:
    return frozenset(
        (capability, next(iter(permitted_purposes(capability)))) for capability in capabilities
    )


G1: Final = grants(
    Capability.RECORD_EVENTS_LIST,
    Capability.TASKS_READ,
    Capability.CAPTURE_READ,
    Capability.TASKS_COMMENTS_LIST,
)
G2: Final = G1 - grants(Capability.CAPTURE_READ)
WIDENED: Final = G1 | grants(Capability.TASKS_LIST)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _list(
    runtime: Runtime, principal: str, granted: Grants, cursor: str | None = None
) -> ResponseEnvelope:
    return runtime.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=Capability.RECORD_EVENTS_LIST,
            purpose=Purpose.RECORD_EVENT_READ,
            principal_id=principal,
            requested_at=WHEN,
        ),
        ListRecordEvents(page_size=2, cursor=cursor),
        principal=Principal(
            principal_id=principal, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
        capability_grants=granted,
    )


def _ok(response: ResponseEnvelope) -> dict[str, Any]:
    assert response.error is None, response.error
    assert response.result is not None
    return response.result


def _conflict(response: ResponseEnvelope) -> None:
    assert response.error is not None
    assert response.error.code is ErrorCode.CONFLICT
    assert response.error.safe_details == ("cursor",)


def _everything(runtime: Runtime, principal: str, granted: Grants) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        page = _ok(_list(runtime, principal, granted, cursor))
        seen.extend((item["record_family"], item["event_id"]) for item in page["events"])
        cursor = page["next_cursor"]
        if cursor is None:
            return seen


def _stored(runtime: Runtime, principal: str) -> tuple[int, int | None]:
    with runtime.work_engine.connect() as connection:
        count = connection.execute(
            select(func.count()).where(record_events.c.principal_id == principal)
        ).scalar_one()
    return int(count), next_sequence(runtime.work_engine, principal)


def _seed(runtime: Runtime, principal: str) -> None:
    def ok(command: Command) -> dict[str, Any]:
        return runtime.ok(command, principal_id=principal)

    capture = ok(CreateCapture(text="Synthetic grant-change note", idempotency_key="wp08-gc-c"))
    ok(
        ReviseCapture(
            capture_id=capture["capture_id"],
            text="Synthetic grant-change note revised",
            idempotency_key="wp08-gc-r",
        )
    )
    task = ok(
        CreateTask(
            title="Synthetic grant-change task",
            idempotency_key="wp08-gc-t",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        )
    )
    ok(
        CreateTaskComment(
            task_id=task["task"]["task_id"], body="Synthetic", idempotency_key="wp08-gc-m"
        )
    )


def test_a_grant_change_invalidates_the_cursor_and_a_relist_sees_current_history(
    runtime: Runtime,
) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    _seed(runtime, principal)
    stored = _stored(runtime, principal)
    full = _everything(runtime, principal, G1)
    assert sorted({family for family, _ in full}) == ["capture", "task", "task_comment"]
    assert [family for family, _ in full].count("capture") == 2

    # 1. A G1 cursor.
    first = _ok(_list(runtime, principal, G1))
    g1_cursor = first["next_cursor"]
    assert g1_cursor is not None

    # 2. Narrowed: the cursor conflicts; a relist has no capture event.
    _conflict(_list(runtime, principal, G2, g1_cursor))
    narrowed = _everything(runtime, principal, G2)
    assert narrowed == [(family, event) for family, event in full if family != "capture"]
    # Two visible events fit one page; its high-watermark cursor is still bound.
    g2_cursor = _ok(_list(runtime, principal, G2))["high_watermark_cursor"]
    assert g2_cursor is not None

    # 3. Restored: a G2 cursor conflicts; a relist returns the full history.
    _conflict(_list(runtime, principal, G1, g2_cursor))
    assert _everything(runtime, principal, G1) == full

    # 4. Widened by a second read of a visible family: same set, new digest, conflict.
    widened = _ok(_list(runtime, principal, WIDENED))
    assert widened["visible_families"] == first["visible_families"]
    _conflict(_list(runtime, principal, WIDENED, g1_cursor))

    # Nothing was deleted or re-keyed at any point.
    assert _stored(runtime, principal) == stored
