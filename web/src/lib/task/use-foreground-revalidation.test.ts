import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ForegroundRevalidationHttpError,
  useForegroundRevalidation,
  type ForegroundFreshnessStatus,
  type ForegroundReadCoordinator,
  type ForegroundRevalidationNoticeKind,
} from "@/lib/task/use-foreground-revalidation";

/**
 * Controller-level guards for the ONE foreground revalidation policy.
 *
 * These exercise the extracted controller through a deliberately non-Task
 * coordinator: the key is a bare string, proving the policy no longer depends
 * on `TaskQueryKey` or `TaskReadCoordinator`.
 */

type FakeFetcher = () => Promise<string>;

interface FakeSnapshot {
  readonly freshness: ForegroundFreshnessStatus;
  readonly lastConfirmed: string | undefined;
  readonly lastSuccessfulAt: number | null;
}

interface FakeResult {
  readonly outcome: string;
  readonly silent?: boolean;
  readonly error?: unknown;
}

interface FakeEntry {
  freshness: ForegroundFreshnessStatus;
  lastConfirmed: string | undefined;
  lastSuccessfulAt: number | null;
  readonly listeners: Set<(snapshot: FakeSnapshot) => void>;
}

class FakeCoordinator
  implements ForegroundReadCoordinator<string, string, FakeFetcher, FakeResult, FakeSnapshot>
{
  private readonly entries = new Map<string, FakeEntry>();
  readonly reads: Array<{ key: string; force: boolean }> = [];
  readonly barriers: string[] = [];
  readonly confirmedWrites: Array<{ key: string; data: string }> = [];
  retainCount = 0;

  private ensure(key: string): FakeEntry {
    let entry = this.entries.get(key);
    if (!entry) {
      entry = {
        freshness: "idle",
        lastConfirmed: undefined,
        lastSuccessfulAt: null,
        listeners: new Set(),
      };
      this.entries.set(key, entry);
    }
    return entry;
  }

  private emit(entry: FakeEntry): void {
    const snapshot: FakeSnapshot = {
      freshness: entry.freshness,
      lastConfirmed: entry.lastConfirmed,
      lastSuccessfulAt: entry.lastSuccessfulAt,
    };
    for (const listener of entry.listeners) listener(snapshot);
  }

  retain(key: string): unknown {
    this.retainCount += 1;
    return this.ensure(key);
  }

  release(key: string): void {
    this.ensure(key);
    this.retainCount -= 1;
  }

  subscribe(key: string, listener: (snapshot: FakeSnapshot) => void): () => void {
    const entry = this.ensure(key);
    entry.listeners.add(listener);
    this.emit(entry);
    return () => {
      entry.listeners.delete(listener);
    };
  }

  async read(key: string, fetcher: FakeFetcher, options: { readonly force: boolean }): Promise<FakeResult> {
    const entry = this.ensure(key);
    this.reads.push({ key, force: options.force });
    try {
      const data = await fetcher();
      entry.lastConfirmed = data;
      entry.lastSuccessfulAt = Date.now();
      entry.freshness = "fresh";
      this.emit(entry);
      return { outcome: "applied", silent: false };
    } catch (error) {
      // Deliberately NOT "stale": only an explicit markStale() may produce it,
      // so the 503 guard below actually proves markStale was called.
      entry.freshness = "unavailable";
      this.emit(entry);
      return { outcome: "failed", silent: false, error };
    }
  }

  getSnapshot(key: string): FakeSnapshot | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    return {
      freshness: entry.freshness,
      lastConfirmed: entry.lastConfirmed,
      lastSuccessfulAt: entry.lastSuccessfulAt,
    };
  }

  markFresh(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "fresh";
    this.emit(entry);
  }

  markStale(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "stale";
    this.emit(entry);
  }

  markSuspended(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "suspended";
    this.emit(entry);
  }

  applyConfirmed(key: string, data: string): unknown {
    const entry = this.ensure(key);
    entry.lastConfirmed = data;
    this.confirmedWrites.push({ key, data });
    this.emit(entry);
    return entry;
  }

  raiseMutationBarrier(key: string): unknown {
    this.ensure(key);
    this.barriers.push(key);
    return this.barriers.length;
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

async function flushMountRead() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

interface HookProps {
  readonly queryId: string;
  readonly fetcher: FakeFetcher;
  readonly coordinator: FakeCoordinator;
  readonly onNotice?: (kind: ForegroundRevalidationNoticeKind) => void;
}

function render(props: HookProps) {
  return renderHook(
    (current: HookProps) =>
      useForegroundRevalidation<string, string, FakeFetcher, FakeResult, FakeSnapshot>({
        queryId: current.queryId,
        queryKey: current.queryId,
        enabled: true,
        coordinator: current.coordinator,
        fetcher: current.fetcher,
        onNotice: current.onNotice ? (notice) => current.onNotice?.(notice.kind) : undefined,
      }),
    { initialProps: props },
  );
}

let visibility: DocumentVisibilityState = "visible";
let online = true;

describe("useForegroundRevalidation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    visibility = "visible";
    online = true;
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibility,
    });
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      get: () => online,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("polls on a 5s cadence while visible and online, without stacking in-flight reads", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    const { unmount } = render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);

    unmount();
  });

  it("does not stack an ordinary interval read on top of an in-flight read", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    // Put a non-interval read in flight while the 5s interval timer stays armed.
    const pending = deferred<string>();
    fetcher.mockImplementationOnce(async () => pending.promise);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(1);

    // The interval tick lands while that read is still in flight: no second read.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    await act(async () => {
      pending.resolve("late");
      await Promise.resolve();
    });
  });

  it("arms no poll when a read completes while hidden", async () => {
    const coordinator = new FakeCoordinator();
    const pending = deferred<string>();
    const fetcher = vi.fn(async () => pending.promise);
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    visibility = "hidden";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      pending.resolve("rows");
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("arms no poll when a read completes while offline", async () => {
    const coordinator = new FakeCoordinator();
    const pending = deferred<string>();
    const fetcher = vi.fn(async () => pending.promise);
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    online = false;
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
      await Promise.resolve();
    });
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      pending.resolve("rows");
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("revalidates immediately on window focus", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("suspends the timer while hidden and revalidates immediately on hidden→visible", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    visibility = "hidden";
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);
    expect(vi.getTimerCount()).toBe(0);

    visibility = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("suspends the timer while offline and revalidates immediately on online", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    online = false;
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(0);
    expect(vi.getTimerCount()).toBe(0);

    online = true;
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("stops the running timer when the surface goes hidden or offline", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    visibility = "hidden";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    visibility = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    online = false;
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
      await Promise.resolve();
    });
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("walks the 5s → 10s → 30s backoff ladder on repeated transport failure", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => {
      throw new ForegroundRevalidationHttpError(500);
    });
    render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    expect(fetcher).toHaveBeenCalledTimes(1);

    // failure 1 → next attempt after 5s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    // failure 2 → next attempt after 10s, not 5s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);

    // failure 3 → next attempt after 30s, not 10s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(4);

    // failure 4+ → ladder caps at 30s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(29_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(4);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(5);
  });

  it("clears the backoff gate for focus, visibility, online, mutation and manual", async () => {
    const triggers = ["focus", "visibility", "online", "mutation", "manual"] as const;

    for (const trigger of triggers) {
      const coordinator = new FakeCoordinator();
      const fetcher = vi.fn(async () => {
        throw new ForegroundRevalidationHttpError(500);
      });
      const { result, unmount } = render({ queryId: `q-${trigger}`, coordinator, fetcher });

      await flushMountRead();
      expect(fetcher, trigger).toHaveBeenCalledTimes(1);

      // Gate is now closed for 5s: an interval tick 1s later must not fire.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(fetcher, trigger).toHaveBeenCalledTimes(1);

      await act(async () => {
        if (trigger === "focus") {
          window.dispatchEvent(new Event("focus"));
        } else if (trigger === "visibility") {
          visibility = "hidden";
          document.dispatchEvent(new Event("visibilitychange"));
          visibility = "visible";
          document.dispatchEvent(new Event("visibilitychange"));
        } else if (trigger === "online") {
          window.dispatchEvent(new Event("online"));
        } else if (trigger === "mutation") {
          await result.current.notifyMutationConfirmed();
        } else {
          await result.current.revalidate("manual");
        }
        await Promise.resolve();
      });
      expect(fetcher, trigger).toHaveBeenCalledTimes(2);

      unmount();
      vi.clearAllTimers();
    }
  });

  it("suspends after 401 and emits exactly one auth notice", async () => {
    const coordinator = new FakeCoordinator();
    const notices: ForegroundRevalidationNoticeKind[] = [];
    const fetcher = vi.fn(async () => {
      throw new ForegroundRevalidationHttpError(401);
    });
    const { result } = render({
      queryId: "q1",
      coordinator,
      fetcher,
      onNotice: (kind) => notices.push(kind),
    });

    await flushMountRead();
    expect(result.current.suspended).toBe(true);
    expect(notices).toEqual(["auth"]);
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(notices).toEqual(["auth"]);
  });

  it("fail-closed suspends after 403 and emits exactly one forbidden notice", async () => {
    const coordinator = new FakeCoordinator();
    const notices: ForegroundRevalidationNoticeKind[] = [];
    const fetcher = vi.fn(async () => {
      throw new ForegroundRevalidationHttpError(403);
    });
    const { result } = render({
      queryId: "q1",
      coordinator,
      fetcher,
      onNotice: (kind) => notices.push(kind),
    });

    await flushMountRead();
    expect(result.current.suspended).toBe(true);
    expect(notices).toEqual(["forbidden"]);
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(notices).toEqual(["forbidden"]);
  });

  it("marks stale on 503 and emits exactly one degraded notice across repeats", async () => {
    const coordinator = new FakeCoordinator();
    const notices: ForegroundRevalidationNoticeKind[] = [];
    const fetcher = vi.fn(async () => {
      throw new ForegroundRevalidationHttpError(503);
    });
    const { result } = render({
      queryId: "q1",
      coordinator,
      fetcher,
      onNotice: (kind) => notices.push(kind),
    });

    await flushMountRead();
    expect(result.current.suspended).toBe(false);
    expect(result.current.freshness).toBe("stale");
    expect(notices).toEqual(["degraded"]);

    await act(async () => {
      await result.current.revalidate("manual");
    });
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetcher.mock.calls.length).toBeGreaterThan(2);
    expect(notices).toEqual(["degraded"]);
    expect(result.current.freshness).toBe("stale");
  });

  it("resets backoff and notice dedupe when the query identity changes", async () => {
    const coordinator = new FakeCoordinator();
    const notices: ForegroundRevalidationNoticeKind[] = [];
    const fetcher = vi.fn(async () => {
      throw new ForegroundRevalidationHttpError(503);
    });
    const props: HookProps = {
      queryId: "q1",
      coordinator,
      fetcher,
      onNotice: (kind) => notices.push(kind),
    };
    const { rerender } = render(props);

    await flushMountRead();
    // Two failures on "q1": the ladder is at 10s and the notice is deduped.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(notices).toEqual(["degraded"]);

    await act(async () => {
      rerender({ ...props, queryId: "q2" });
      await Promise.resolve();
      await Promise.resolve();
    });
    // Dedupe was reset with the identity.
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(notices).toEqual(["degraded", "degraded"]);

    // Backoff was reset too: the next attempt is 5s away, not 30s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("clears suspension when the query identity changes", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => {
      throw new ForegroundRevalidationHttpError(401);
    });
    const props: HookProps = { queryId: "q1", coordinator, fetcher };
    const { result, rerender } = render(props);

    await flushMountRead();
    expect(result.current.suspended).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      rerender({ ...props, queryId: "q2" });
      await Promise.resolve();
      await Promise.resolve();
    });
    // A new identity is not suspended, and polls again.
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("raises a mutation barrier, or applies confirmed data, then revalidates", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    const { result } = render({ queryId: "q1", coordinator, fetcher });

    await flushMountRead();
    const mountCalls = fetcher.mock.calls.length;

    await act(async () => {
      await result.current.notifyMutationConfirmed();
    });
    expect(coordinator.barriers).toEqual(["q1"]);
    expect(coordinator.confirmedWrites).toEqual([]);
    expect(fetcher).toHaveBeenCalledTimes(mountCalls + 1);

    await act(async () => {
      await result.current.notifyMutationConfirmed("local");
    });
    expect(coordinator.confirmedWrites).toEqual([{ key: "q1", data: "local" }]);
    expect(coordinator.barriers).toEqual(["q1"]);
    expect(fetcher).toHaveBeenCalledTimes(mountCalls + 2);
    // Mutation reads are forced.
    expect(coordinator.reads.at(-1)?.force).toBe(true);
  });

  it("registers with the reconciliation seam without adding a timer, and unregisters on unmount", async () => {
    const coordinator = new FakeCoordinator();
    const fetcher = vi.fn(async () => "rows");
    const registered = new Map<string, () => void | Promise<unknown>>();
    const registerActiveTaskQuery = vi.fn((queryId: string, revalidate: () => void | Promise<unknown>) => {
      registered.set(queryId, revalidate);
      return () => registered.delete(queryId);
    });
    const unregisterActiveTaskQuery = vi.fn((queryId: string) => {
      registered.delete(queryId);
    });

    const plain = render({ queryId: "q1", coordinator, fetcher });
    await flushMountRead();
    const timersWithoutSeam = vi.getTimerCount();
    plain.unmount();

    const seamCoordinator = new FakeCoordinator();
    const reconciliation = { registerActiveTaskQuery, unregisterActiveTaskQuery };
    const seamed = renderHook(() =>
      useForegroundRevalidation<string, string, FakeFetcher, FakeResult, FakeSnapshot>({
        queryId: "q1",
        queryKey: "q1",
        enabled: true,
        coordinator: seamCoordinator,
        fetcher,
        reconciliation,
      }),
    );
    await flushMountRead();
    expect(vi.getTimerCount()).toBe(timersWithoutSeam);
    expect(registerActiveTaskQuery).toHaveBeenCalledTimes(1);
    expect(registered.size).toBe(1);

    const before = fetcher.mock.calls.length;
    const [revalidate] = Array.from(registered.values());
    await act(async () => {
      await revalidate!();
    });
    expect(fetcher).toHaveBeenCalledTimes(before + 1);

    seamed.unmount();
    expect(unregisterActiveTaskQuery).toHaveBeenCalledTimes(1);
    expect(registered.size).toBe(0);
  });
});
