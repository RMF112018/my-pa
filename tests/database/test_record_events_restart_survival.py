"""WP-RE-08 (Amendment 02 (2)): a Principal's feed survives a restart (RE-AC-104, 105).

Marked `database` and routed to `database-current-head`. A restart is two
application compositions over one database, built one after the other the way
`apps/gateway.py` builds one (`build_gateway_runtime`), the first closed -- its
engines disposed -- before the second is built. Precedent:
`tests/capture/test_owner_is_the_partition.py`.

* **RE-AC-104, the local operator.** Composition 1 writes a capture, revises
  it, creates a Task and comments on it, then lists the feed one event per
  page and keeps the first `next_cursor`. Composition 2 presents the same
  principal (`capture_principal_id(LOCAL_OPERATOR_UUID)`), lists the same events
  in the same order, resumes composition 1's cursor with no conflict, and sees
  a new write after the resumed page.
* **RE-AC-105, an account principal.** Each composition authenticates the same
  synthetic claims through `PrincipalIdentityService` (the
  `identity.user_accounts` resolve-or-create path) and gets the same account
  principal; the same writes and lists run under that principal with unchanged
  remote grants, so `grant_digest` is in the binding and still matches.

Every identity and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from my_pa.application.commands import (
    Command,
    CreateCapture,
    CreateTask,
    CreateTaskComment,
    ListRecordEvents,
    ReviseCapture,
)
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.security.principal_identity import PrincipalIdentityService

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 9, 30, 12, tzinfo=UTC)
TENANT: Final = "11111111-2222-3333-4444-555555555555"
CLAIMS: Final[dict[str, object]] = {
    "tid": TENANT,
    "oid": "cccc0003-0000-0000-0000-000000000003",
    "upn": "synthetic.restart@moss.example",
    "name": "Synthetic Restart",
}
USED: Final = (
    Capability.CAPTURE_CREATE,
    Capability.CAPTURE_REVISE,
    Capability.CAPTURE_READ,
    Capability.TASKS_CREATE,
    Capability.TASKS_READ,
    Capability.TASKS_COMMENTS_CREATE,
    Capability.TASKS_COMMENTS_LIST,
    Capability.RECORD_EVENTS_LIST,
)
GRANTS: Final = frozenset(
    (capability, next(iter(permitted_purposes(capability)))) for capability in USED
)

type Grants = frozenset[tuple[Capability, Purpose | None]] | None
type Invoker = Callable[[Command], dict[str, Any]]


def _invoker(runtime: GatewayRuntime, principal: Principal, grants: Grants) -> Invoker:
    def call(command: Command) -> dict[str, Any]:
        capability: Capability = type(command).capability  # type: ignore[attr-defined]
        response = runtime.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=next(iter(permitted_purposes(capability))),
                principal_id=principal.principal_id,
                requested_at=WHEN,
            ),
            command,
            principal=principal,
            capability_grants=grants,
        )
        assert response.error is None, (type(command).__name__, response.error)
        assert response.result is not None
        return response.result

    return call


def _write(call: Invoker, tag: str) -> None:
    created = call(CreateCapture(text=f"Synthetic restart note {tag}", idempotency_key=f"{tag}-c"))
    call(
        ReviseCapture(
            capture_id=created["capture_id"],
            text=f"Synthetic restart note {tag} revised",
            idempotency_key=f"{tag}-r",
        )
    )
    task = call(
        CreateTask(
            title=f"Synthetic restart task {tag}",
            idempotency_key=f"{tag}-t",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        )
    )
    call(
        CreateTaskComment(
            task_id=task["task"]["task_id"], body=f"Synthetic {tag}", idempotency_key=f"{tag}-m"
        )
    )


def _all_ids(call: Invoker) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None
    while True:
        page = call(ListRecordEvents(page_size=100, cursor=cursor))
        ids.extend(item["event_id"] for item in page["events"])
        cursor = page["next_cursor"]
        if cursor is None:
            return ids


def _survives(
    url: str,
    principal_of: Callable[[GatewayRuntime], Principal],
    grants: Grants,
) -> None:
    first = build_gateway_runtime(Settings(database_url=url))
    try:
        principal_1 = principal_of(first)
        call = _invoker(first, principal_1, grants)
        _write(call, f"restart-{issue_identifier(IdKind.CORRELATION)[-8:]}")
        before = _all_ids(call)
        assert len(before) >= 4
        head = call(ListRecordEvents(page_size=1))
        cursor_1 = head["next_cursor"]
        assert cursor_1 is not None
        assert [item["event_id"] for item in head["events"]] == before[:1]
    finally:
        first.close()

    second = build_gateway_runtime(Settings(database_url=url))
    try:
        principal_2 = principal_of(second)
        assert principal_2.principal_id == principal_1.principal_id
        call = _invoker(second, principal_2, grants)
        assert _all_ids(call) == before
        # The cursor is bound to its page size, so it resumes at `page_size=1`.
        resumed, cursor, watermark = [], cursor_1, None
        while cursor is not None:
            page = call(ListRecordEvents(page_size=1, cursor=cursor))
            resumed.extend(item["event_id"] for item in page["events"])
            cursor, watermark = page["next_cursor"], page["high_watermark_cursor"]
        assert resumed == before[1:]
        _write(call, f"after-{issue_identifier(IdKind.CORRELATION)[-8:]}")
        later = call(ListRecordEvents(page_size=1, cursor=watermark))
        assert len(later["events"]) == 1
        assert later["events"][0]["event_id"] not in set(before)
        assert _all_ids(call)[: len(before)] == before
    finally:
        second.close()


def test_the_local_operator_keeps_its_feed_across_a_restart(disposable_database: str) -> None:
    def local(runtime: GatewayRuntime) -> Principal:
        assert runtime.principal is not None
        assert runtime.principal.principal_id == capture_principal_id(LOCAL_OPERATOR_UUID)
        return runtime.principal

    _survives(disposable_database, local, None)


def test_an_account_principal_keeps_its_feed_across_a_restart(disposable_database: str) -> None:
    identity = PrincipalIdentityService(home_tenant_id=TENANT)

    def account(runtime: GatewayRuntime) -> Principal:
        with runtime.work_engine.begin() as connection:
            authenticated = identity.authenticate(connection, claims=CLAIMS, now=WHEN)
        return Principal(
            principal_id=capture_principal_id(authenticated.account.principal_id),
            kind=PrincipalKind.OPERATOR,
            authenticated=True,
        )

    _survives(disposable_database, account, GRANTS)
