import { afterEach, describe, expect, it, vi } from "vitest";
import { buildTaskQueryKey } from "@/lib/task/query-key";
import { TaskReadCoordinator } from "@/lib/task/read-coordinator";

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

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TaskReadCoordinator same-key dedupe", () => {
  it("shares one network read for concurrent ordinary callers", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const pending = deferred<string>();
    const fetcher = vi.fn(async ({ signal }: { signal: AbortSignal }) => {
      expect(signal.aborted).toBe(false);
      return pending.promise;
    });

    const first = coordinator.read(KEY, fetcher);
    const second = coordinator.read(KEY, fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);

    pending.resolve("rows-v1");
    await expect(first).resolves.toMatchObject({ outcome: "applied", data: "rows-v1", silent: false });
    await expect(second).resolves.toMatchObject({ outcome: "deduped", data: "rows-v1" });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("rows-v1");
    expect(coordinator.getSnapshot(KEY)?.freshness).toBe("fresh");
    coordinator.dispose();
  });
});

describe("TaskReadCoordinator supersede", () => {
  it("aborts the previous in-flight read when force=true and applies the newer result", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const firstPending = deferred<string>();
    const secondPending = deferred<string>();
    let calls = 0;
    const fetcher = vi.fn(async ({ signal }: { signal: AbortSignal }) => {
      calls += 1;
      if (calls === 1) {
        await firstPending.promise;
        if (signal.aborted) {
          const error = new Error("aborted");
          error.name = "AbortError";
          throw error;
        }
        return "stale";
      }
      return secondPending.promise;
    });

    const older = coordinator.read(KEY, fetcher);
    const newer = coordinator.read(KEY, fetcher, { force: true });
    expect(fetcher).toHaveBeenCalledTimes(2);

    firstPending.resolve("stale");
    secondPending.resolve("fresh");

    await expect(older).resolves.toMatchObject({ outcome: "aborted", silent: true });
    await expect(newer).resolves.toMatchObject({ outcome: "applied", data: "fresh", silent: false });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("fresh");
    coordinator.dispose();
  });
});

describe("TaskReadCoordinator mutation barrier", () => {
  it("does not let a pre-mutation poll overwrite confirmed mutation data", async () => {
    const coordinator = new TaskReadCoordinator<{ version: number; title: string }>();
    const poll = deferred<{ version: number; title: string }>();
    const fetcher = vi.fn(async () => poll.promise);

    const inFlight = coordinator.read(KEY, fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);

    coordinator.applyConfirmed(KEY, { version: 2, title: "After mutation" });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toEqual({ version: 2, title: "After mutation" });
    expect(coordinator.getSnapshot(KEY)?.mutationBarrier).toBeGreaterThan(0);

    poll.resolve({ version: 1, title: "Pre-mutation snapshot" });
    await expect(inFlight).resolves.toMatchObject({ outcome: "barrier_blocked", silent: true });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toEqual({ version: 2, title: "After mutation" });
    coordinator.dispose();
  });

  it("still applies a read that starts after the mutation barrier", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    coordinator.applyConfirmed(KEY, "confirmed");
    const result = await coordinator.read(KEY, async () => "revalidated");
    expect(result).toMatchObject({ outcome: "applied", data: "revalidated" });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("revalidated");
    coordinator.dispose();
  });
});

describe("TaskReadCoordinator cleanup", () => {
  it("aborts orphaned in-flight reads on dispose", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const pending = deferred<string>();
    const fetcher = vi.fn(async ({ signal }: { signal: AbortSignal }) => {
      await pending.promise;
      if (signal.aborted) {
        const error = new Error("aborted");
        error.name = "AbortError";
        throw error;
      }
      return "late";
    });

    const inflight = coordinator.read(KEY, fetcher);
    coordinator.dispose();
    pending.resolve("late");
    await expect(inflight).resolves.toMatchObject({ outcome: "aborted", silent: true });
  });

  it("does not treat aborted reads as user-visible failures", async () => {
    const coordinator = new TaskReadCoordinator<string>();
    const pending = deferred<string>();
    const first = coordinator.read(KEY, async ({ signal }) => {
      await pending.promise;
      if (signal.aborted) {
        const error = new Error("aborted");
        error.name = "AbortError";
        throw error;
      }
      return "old";
    });
    const second = coordinator.read(KEY, async () => "new", { force: true });
    pending.resolve("old");
    const aborted = await first;
    expect(aborted.silent).toBe(true);
    expect(aborted.outcome).toBe("aborted");
    await expect(second).resolves.toMatchObject({ outcome: "applied", data: "new" });
    coordinator.dispose();
  });
});
