import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildTaskQueryKey } from "@/lib/task/query-key";
import { TaskReadCoordinator } from "@/lib/task/read-coordinator";
import {
  TaskFreshnessHttpError,
  useTaskFreshness,
} from "@/components/work/use-task-freshness";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, refuse) => {
    resolve = accept;
    reject = refuse;
  });
  return { promise, resolve, reject };
}

const KEY = buildTaskQueryKey({
  mode: "list",
  workView: "today",
  workDate: "2026-09-11",
  timezone: "America/New_York",
  archiveMode: "exclude",
  sessionEpoch: "epoch-1",
});

async function flushMountRead() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("useTaskFreshness", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      get: () => true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads immediately on mount, then polls every 5s without stacking ordinary reads", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const fetcher = vi.fn(async () => "rows");
    const { unmount } = renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
      }),
    );

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    // While a read is in flight, interval ticks must not stack another ordinary fetch.
    const pending = deferred<string>();
    fetcher.mockImplementationOnce(async () => pending.promise);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
    await act(async () => {
      pending.resolve("late");
      await Promise.resolve();
    });

    unmount();
    coordinator.dispose();
  });

  it("stops continuous polling while hidden and resumes immediately on visible", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const fetcher = vi.fn(async () => "rows");
    let visibility: DocumentVisibilityState = "hidden";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibility,
    });

    renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
      }),
    );

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);

    visibility = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    coordinator.dispose();
  });

  it("revalidates immediately on window focus", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const fetcher = vi.fn(async () => "rows");
    renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
      }),
    );

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    coordinator.dispose();
  });

  it("stops continuous polling while offline and resumes immediately on online", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const fetcher = vi.fn(async () => "rows");
    let online = false;
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      get: () => online,
    });

    renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
      }),
    );

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);

    online = true;
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    coordinator.dispose();
  });

  it("cleans up timers and listeners on unmount", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const fetcher = vi.fn(async () => "rows");
    const { unmount } = renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
      }),
    );

    unmount();
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("online"));
      await vi.advanceTimersByTimeAsync(20_000);
    });
    // Mount may have started a read before unmount; no further polls after cleanup.
    expect(fetcher.mock.calls.length).toBeLessThanOrEqual(1);
    coordinator.dispose();
  });

  it("suspends noisy polling after 401", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const notices: string[] = [];
    const fetcher = vi.fn(async () => {
      throw new TaskFreshnessHttpError(401);
    });
    const { result } = renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
        onNotice: (notice) => notices.push(notice.kind),
      }),
    );

    await flushMountRead();
    expect(result.current.suspended).toBe(true);
    expect(notices).toEqual(["auth"]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    // Focus while suspended must not restart noisy polling.
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(notices).toEqual(["auth"]);
    coordinator.dispose();
  });

  it("fail-closed suspends after 403", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const notices: string[] = [];
    const fetcher = vi.fn(async () => {
      throw new TaskFreshnessHttpError(403);
    });
    const { result } = renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
        onNotice: (notice) => notices.push(notice.kind),
      }),
    );

    await flushMountRead();
    expect(result.current.suspended).toBe(true);
    expect(notices).toEqual(["forbidden"]);
    coordinator.dispose();
  });

  it("retains confirmed data, marks stale, backs off, and dedupes 503 notices", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    coordinator.applyConfirmed(KEY, "confirmed");
    const notices: string[] = [];
    let fail = true;
    const fetcher = vi.fn(async () => {
      if (fail) throw new TaskFreshnessHttpError(503);
      return "recovered";
    });
    const { result } = renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
        onNotice: (notice) => notices.push(notice.kind),
      }),
    );

    await flushMountRead();
    expect(result.current.lastConfirmed).toBe("confirmed");
    expect(result.current.freshness).toBe("stale");
    expect(notices).toEqual(["degraded"]);

    await act(async () => {
      await result.current.revalidate("manual");
    });
    expect(notices).toEqual(["degraded"]);

    fail = false;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(result.current.lastConfirmed).toBe("recovered");
    expect(result.current.freshness).toBe("fresh");
    coordinator.dispose();
  });

  it("raises a mutation barrier then revalidates immediately", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const fetcher = vi.fn(async () => "after-mutation");
    const { result } = renderHook(() =>
      useTaskFreshness({
        queryKey: KEY,
        enabled: true,
        coordinator,
        fetcher,
      }),
    );

    await flushMountRead();
    const mountCalls = fetcher.mock.calls.length;

    await act(async () => {
      await result.current.notifyMutationConfirmed("local-confirmed");
    });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("after-mutation");
    expect(fetcher).toHaveBeenCalledTimes(mountCalls + 1);
    expect(coordinator.getSnapshot(KEY)?.mutationBarrier).toBeGreaterThan(0);
    coordinator.dispose();
  });
});
