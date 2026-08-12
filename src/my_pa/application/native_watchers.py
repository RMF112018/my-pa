"""Bounded incremental native-source watcher orchestration.

The store is a durable port: scheduling state, cursor/checkpoint and pause state
survive process restart. Source adapters still perform only bounded reads and
admission remains application-mediated through ``NativeSourceController``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from my_pa.application.native_sources import NativeRequestContext, NativeSourceController
from my_pa.contracts.v1.native_sources import NATIVE_SOURCE_MAX_PAGE_SIZE, NativeSourceKind
from my_pa.domain.common.time import ensure_utc

__all__ = ["NativeWatcher", "WatcherHealth", "WatcherState", "WatcherStore"]


class WatcherState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WatcherHealth:
    configuration_id: str
    kind: NativeSourceKind
    state: WatcherState
    last_success_at: datetime | None
    next_due_at: datetime
    consecutive_failures: int
    limitation: str | None = None


@dataclass(frozen=True, slots=True)
class WatcherCheckpoint:
    configuration_id: str
    configuration_revision: int
    kind: NativeSourceKind
    bucket_id: str
    cursor: str | None
    window_start: datetime
    window_end: datetime
    state: WatcherState
    next_due_at: datetime
    consecutive_failures: int = 0


class WatcherStore(Protocol):
    def due(self, now: datetime) -> tuple[WatcherCheckpoint, ...]: ...

    def checkpoint(
        self,
        watcher: WatcherCheckpoint,
        *,
        cursor: str | None,
        next_due_at: datetime,
        succeeded_at: datetime,
    ) -> None: ...

    def fail(
        self, watcher: WatcherCheckpoint, *, next_due_at: datetime, limitation: str
    ) -> None: ...

    def health(self, configuration_id: str) -> tuple[WatcherHealth, ...]: ...


ContextFactory = Callable[[str, datetime], tuple[NativeRequestContext, NativeRequestContext]]


class NativeWatcher:
    """Run due watchers once; the caller owns the bounded scheduling loop."""

    def __init__(
        self,
        *,
        controller: NativeSourceController,
        store: WatcherStore,
        contexts: ContextFactory,
        clock: Callable[[], datetime],
        cadence: timedelta = timedelta(minutes=5),
        overlap: timedelta = timedelta(minutes=10),
        calendar_horizon: timedelta = timedelta(days=90),
    ) -> None:
        if cadence <= timedelta(0) or overlap < timedelta(0) or calendar_horizon <= timedelta(0):
            raise ValueError("watcher cadence and horizon must be bounded")
        self._controller = controller
        self._store = store
        self._contexts = contexts
        self._clock = clock
        self._cadence = cadence
        self._overlap = overlap
        self._calendar_horizon = calendar_horizon

    def run_due_once(self) -> int:
        now = ensure_utc(self._clock())
        completed = 0
        for watcher in self._store.due(now):
            if watcher.state is not WatcherState.ACTIVE:
                continue
            start = watcher.window_start - self._overlap
            end = watcher.window_end
            if watcher.kind is NativeSourceKind.CALENDAR:
                end = min(end, now + self._calendar_horizon)
            request_id = (
                f"watch:{watcher.configuration_id}:{watcher.configuration_revision}:"
                f"{watcher.kind.value}:{int(now.timestamp())}"
            )
            control, admission = self._contexts(request_id, now)
            try:
                page = self._controller.read_and_admit_page(
                    control,
                    admission,
                    configuration_id=watcher.configuration_id,
                    bucket_id=watcher.bucket_id,
                    time_range=(start, end),
                    cursor=watcher.cursor,
                    limit=NATIVE_SOURCE_MAX_PAGE_SIZE,
                )
            except Exception:
                failures = watcher.consecutive_failures + 1
                delay = min(self._cadence * (2 ** min(failures - 1, 6)), timedelta(hours=6))
                self._store.fail(
                    watcher,
                    next_due_at=now + delay,
                    limitation=(
                        "bounded native read or admission failed; source content was not logged"
                    ),
                )
                continue
            self._store.checkpoint(
                watcher,
                cursor=page.next_cursor,
                next_due_at=now + self._cadence,
                succeeded_at=now,
            )
            completed += 1
        return completed

    def health(self, configuration_id: str) -> tuple[WatcherHealth, ...]:
        return self._store.health(configuration_id)
