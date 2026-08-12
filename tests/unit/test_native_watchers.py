from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from my_pa.application.native_watchers import (
    NativeWatcher,
    WatcherCheckpoint,
    WatcherHealth,
    WatcherState,
)
from my_pa.contracts.v1.native_sources import NATIVE_SOURCE_MAX_PAGE_SIZE, NativeSourceKind

NOW = datetime(2026, 8, 12, 14, tzinfo=UTC)


class MemoryStore:
    def __init__(self, checkpoints: tuple[WatcherCheckpoint, ...]) -> None:
        self.checkpoints = checkpoints
        self.successes: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []

    def due(self, now: datetime) -> tuple[WatcherCheckpoint, ...]:
        return tuple(item for item in self.checkpoints if item.next_due_at <= now)

    def checkpoint(self, watcher: WatcherCheckpoint, **values: Any) -> None:  # noqa: ANN401
        self.successes.append({"watcher": watcher, **values})

    def fail(self, watcher: WatcherCheckpoint, **values: Any) -> None:  # noqa: ANN401
        self.failures.append({"watcher": watcher, **values})

    def health(self, configuration_id: str) -> tuple[WatcherHealth, ...]:
        return ()


class Controller:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def read_and_admit_page(
        self,
        *contexts: object,
        **values: object,
    ) -> object:
        self.calls.append(values)
        if self.fail:
            raise RuntimeError("synthetic failure")
        return type("Receipt", (), {"next_cursor": "cursor-2"})()


def _checkpoint(
    kind: NativeSourceKind = NativeSourceKind.CALENDAR,
    *,
    state: WatcherState = WatcherState.ACTIVE,
    failures: int = 0,
) -> WatcherCheckpoint:
    return WatcherCheckpoint(
        configuration_id="ncfg_0000000000000001",
        configuration_revision=3,
        kind=kind,
        bucket_id="nbkt_0000000000000001",
        cursor="cursor-1",
        window_start=NOW - timedelta(days=1),
        window_end=NOW + timedelta(days=365),
        state=state,
        next_due_at=NOW,
        consecutive_failures=failures,
    )


def _watcher(store: MemoryStore, controller: Controller) -> NativeWatcher:
    return NativeWatcher(
        controller=controller,  # type: ignore[arg-type]
        store=store,
        contexts=lambda request_id, now: (object(), object()),  # type: ignore[arg-type,return-value]
        clock=lambda: NOW,
    )


def test_calendar_watcher_bounds_overlap_horizon_and_advances_cursor() -> None:
    store = MemoryStore((_checkpoint(),))
    controller = Controller()

    assert _watcher(store, controller).run_due_once() == 1

    call = controller.calls[0]
    assert call["time_range"] == (
        NOW - timedelta(days=1, minutes=10),
        NOW + timedelta(days=90),
    )
    assert call["cursor"] == "cursor-1"
    assert call["limit"] == NATIVE_SOURCE_MAX_PAGE_SIZE
    assert store.successes[0]["cursor"] == "cursor-2"
    assert store.successes[0]["next_due_at"] == NOW + timedelta(minutes=5)


def test_paused_watcher_is_not_read_or_advanced() -> None:
    store = MemoryStore((_checkpoint(state=WatcherState.PAUSED),))
    controller = Controller()

    assert _watcher(store, controller).run_due_once() == 0
    assert controller.calls == []
    assert store.successes == []


def test_failure_is_content_free_and_exponentially_backed_off() -> None:
    store = MemoryStore((_checkpoint(failures=3),))
    controller = Controller(fail=True)

    assert _watcher(store, controller).run_due_once() == 0

    failure = store.failures[0]
    assert failure["next_due_at"] == NOW + timedelta(minutes=40)
    assert "content" in failure["limitation"]
    assert "synthetic failure" not in failure["limitation"]
