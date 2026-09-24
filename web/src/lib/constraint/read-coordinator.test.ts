import { afterEach, describe, expect, it, vi } from "vitest";
import { buildConstraintQueryKey } from "@/lib/constraint/query-key";
import { ConstraintReadCoordinator } from "@/lib/constraint/read-coordinator";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, refuse) => {
    resolve = accept;
    reject = refuse;
  });
  return { promise, resolve, reject };
}

const KEY = buildConstraintQueryKey({
  mode: "list",
  scope: { kind: "PROJECT", projectId: "prj_aaaaaaaa11111111" },
  status: "active",
  sessionKey: "prn_a::session-1",
  scopeEpoch: 0,
});

/** Always-current epoch predicate — the default for every non-epoch test below. */
const ALWAYS_CURRENT = () => true;

function readOptions(overrides: Partial<{ force: boolean; epoch: number; isCurrentEpoch: (e: number) => boolean }> = {}) {
  return { epoch: 0, isCurrentEpoch: ALWAYS_CURRENT, ...overrides };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ConstraintReadCoordinator same-key dedupe", () => {
  it("shares one network read for concurrent ordinary callers", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
    const pending = deferred<string>();
    const fetcher = vi.fn(async ({ signal }: { signal: AbortSignal }) => {
      expect(signal.aborted).toBe(false);
      return pending.promise;
    });

    const first = coordinator.read(KEY, fetcher, readOptions());
    const second = coordinator.read(KEY, fetcher, readOptions());
    expect(fetcher).toHaveBeenCalledTimes(1);

    pending.resolve("rows-v1");
    await expect(first).resolves.toMatchObject({ outcome: "applied", data: "rows-v1", silent: false });
    await expect(second).resolves.toMatchObject({ outcome: "deduped", data: "rows-v1" });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("rows-v1");
    expect(coordinator.getSnapshot(KEY)?.freshness).toBe("fresh");
    coordinator.dispose();
  });
});

describe("ConstraintReadCoordinator supersede", () => {
  it("aborts the previous in-flight read when force=true and applies the newer result", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
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

    const older = coordinator.read(KEY, fetcher, readOptions());
    const newer = coordinator.read(KEY, fetcher, readOptions({ force: true }));
    expect(fetcher).toHaveBeenCalledTimes(2);

    firstPending.resolve("stale");
    secondPending.resolve("fresh");

    await expect(older).resolves.toMatchObject({ outcome: "aborted", silent: true });
    await expect(newer).resolves.toMatchObject({ outcome: "applied", data: "fresh", silent: false });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("fresh");
    coordinator.dispose();
  });
});

/**
 * Acceptance traceability: `PC-CM-FE-AC-059`, `-079` (list/Register and
 * detail canonical read correctness), `-124`/`-126` (confirmed mutation
 * must win over an in-flight pre-mutation read).
 */
describe("ConstraintReadCoordinator mutation barrier", () => {
  it("does not let a pre-mutation poll overwrite confirmed mutation data", async () => {
    const coordinator = new ConstraintReadCoordinator<{ version: number; title: string }>();
    const poll = deferred<{ version: number; title: string }>();
    const fetcher = vi.fn(async () => poll.promise);

    const inFlight = coordinator.read(KEY, fetcher, readOptions());
    expect(fetcher).toHaveBeenCalledTimes(1);

    coordinator.applyConfirmed(
      KEY,
      { version: 2, title: "After mutation" },
      { epoch: 0, isCurrentEpoch: ALWAYS_CURRENT },
    );
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toEqual({ version: 2, title: "After mutation" });
    expect(coordinator.getSnapshot(KEY)?.mutationBarrier).toBeGreaterThan(0);

    poll.resolve({ version: 1, title: "Pre-mutation snapshot" });
    await expect(inFlight).resolves.toMatchObject({ outcome: "barrier_blocked", silent: true });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toEqual({ version: 2, title: "After mutation" });
    coordinator.dispose();
  });

  it("still applies a read that starts after the mutation barrier", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
    coordinator.applyConfirmed(KEY, "confirmed", { epoch: 0, isCurrentEpoch: ALWAYS_CURRENT });
    const result = await coordinator.read(KEY, async () => "revalidated", readOptions());
    expect(result).toMatchObject({ outcome: "applied", data: "revalidated" });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("revalidated");
    coordinator.dispose();
  });
});

describe("ConstraintReadCoordinator cleanup", () => {
  it("aborts orphaned in-flight reads on dispose", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
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

    const inflight = coordinator.read(KEY, fetcher, readOptions());
    coordinator.dispose();
    pending.resolve("late");
    await expect(inflight).resolves.toMatchObject({ outcome: "aborted", silent: true });
  });

  it("does not treat aborted reads as user-visible failures", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
    const pending = deferred<string>();
    const first = coordinator.read(
      KEY,
      async ({ signal }) => {
        await pending.promise;
        if (signal.aborted) {
          const error = new Error("aborted");
          error.name = "AbortError";
          throw error;
        }
        return "old";
      },
      readOptions(),
    );
    const second = coordinator.read(KEY, async () => "new", readOptions({ force: true }));
    pending.resolve("old");
    const aborted = await first;
    expect(aborted.silent).toBe(true);
    expect(aborted.outcome).toBe("aborted");
    await expect(second).resolves.toMatchObject({ outcome: "applied", data: "new" });
    coordinator.dispose();
  });
});

/**
 * Mandatory prove-red obligation (dispatch §4, Artifact 05 SP3.6).
 *
 * "Allow a Project-scope epoch change to apply a prior-epoch read response
 * → runtime stale-epoch test fails." This suite is the fake-clock/multi-
 * epoch test the dispatch requires; its red→green run against a
 * temporarily-stripped epoch guard is recorded verbatim in the Phase-4
 * handoff (§ Stale-epoch prove-red).
 *
 * Acceptance traceability: `PC-CM-FE-AC-124`/`-126` (no stale response may
 * cross the epoch boundary), `PC-CM-UX-AC-015`/`-018`.
 */
describe("ConstraintReadCoordinator SP3.6 stale-epoch suppression", () => {
  it("drops a read response whose captured epoch is no longer current: no canonical overwrite", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
    let currentEpoch = 0;
    const isCurrentEpoch = (epoch: number) => epoch === currentEpoch;
    const pending = deferred<string>();

    // Dispatched under epoch 0.
    const inFlight = coordinator.read(KEY, async () => pending.promise, {
      epoch: 0,
      isCurrentEpoch,
    });

    // The Project scope changes mid-flight — epoch 0 is no longer current.
    currentEpoch = 1;

    pending.resolve("stale-epoch-0-payload");
    const result = await inFlight;

    expect(result.outcome).toBe("stale_epoch");
    expect(result.silent).toBe(true);
    // No canonical-state overwrite: nothing was ever confirmed for this key.
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBeUndefined();
    expect(coordinator.getSnapshot(KEY)?.freshness).not.toBe("fresh");
    coordinator.dispose();
  });

  it("drops a failed response whose captured epoch is no longer current", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
    let currentEpoch = 0;
    const isCurrentEpoch = (epoch: number) => epoch === currentEpoch;
    const pending = deferred<string>();

    const inFlight = coordinator.read(
      KEY,
      async () => {
        await pending.promise;
        throw new Error("late failure under a retired epoch");
      },
      { epoch: 0, isCurrentEpoch },
    );

    currentEpoch = 1;
    pending.resolve("unused");
    const result = await inFlight;

    expect(result.outcome).toBe("stale_epoch");
    expect(result.silent).toBe(true);
    expect(coordinator.getSnapshot(KEY)?.freshness).not.toBe("unavailable");
    coordinator.dispose();
  });

  it("applyConfirmed is a no-op (no barrier raised, no confirmed write) when the epoch is stale", () => {
    const coordinator = new ConstraintReadCoordinator<string>();
    const before = coordinator.getSnapshot(KEY);
    const isCurrentEpoch = () => false;

    const snapshot = coordinator.applyConfirmed(KEY, "should-not-apply", { epoch: 5, isCurrentEpoch });

    expect(snapshot.lastConfirmed).toBeUndefined();
    expect(snapshot.mutationBarrier).toBe(before?.mutationBarrier ?? 0);
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBeUndefined();
    coordinator.dispose();
  });

  it("still applies a response whose captured epoch remains current", async () => {
    const coordinator = new ConstraintReadCoordinator<string>();
    const isCurrentEpoch = (epoch: number) => epoch === 0;

    const result = await coordinator.read(KEY, async () => "fresh-under-epoch-0", {
      epoch: 0,
      isCurrentEpoch,
    });

    expect(result).toMatchObject({ outcome: "applied", data: "fresh-under-epoch-0" });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("fresh-under-epoch-0");
    coordinator.dispose();
  });
});
