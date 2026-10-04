import { describe, expect, it, vi } from "vitest";
import { buildResourceKey, type ResourceKey } from "@/lib/workspace/query-key";
import { ResourceCoordinator, type ResourceReadFetcher, type ResourceReadResult, type ResourceQuerySnapshot } from "@/lib/workspace/resource-coordinator";
import type { ForegroundReadCoordinator } from "@/lib/task/use-foreground-revalidation";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((accept, refuse) => { resolve = accept; reject = refuse; });
  return { promise, resolve, reject };
}
const key = (overrides: Partial<ResourceKey> = {}) => buildResourceKey({
  family: "synthetic", mode: "list", sessionEpoch: "session-1", ...overrides,
});
const KEY = key();

describe("ResourceCoordinator read ordering", () => {
  it("deduplicates concurrent reads and passes the resource key/context intact", async () => {
    const coordinator: ForegroundReadCoordinator<string, ResourceKey, ResourceReadFetcher<string>, ResourceReadResult<string>, ResourceQuerySnapshot<string>> = new ResourceCoordinator<string>();
    const pending = deferred<string>();
    const fetcher = vi.fn(async (context) => {
      expect(context).toEqual({ key: KEY, sequence: 1, force: false, signal: expect.any(AbortSignal) });
      return pending.promise;
    });
    const first = coordinator.read(KEY, fetcher, { force: false });
    const second = coordinator.read(KEY, fetcher, { force: false });
    expect(fetcher).toHaveBeenCalledTimes(1);
    pending.resolve("confirmed");
    await expect(first).resolves.toMatchObject({ outcome: "applied", sequence: 1, silent: false });
    await expect(second).resolves.toMatchObject({ outcome: "deduped", data: "confirmed" });
    expect(coordinator.getSnapshot(KEY)).toMatchObject({ lastConfirmed: "confirmed", freshness: "fresh", lastAppliedSequence: 1 });
  });

  it("forced reads abort old transport and reject late data even if it ignores abort", async () => {
    const coordinator = new ResourceCoordinator<string>();
    const pending = deferred<string>();
    let oldSignal!: AbortSignal;
    const old = coordinator.read(KEY, async ({ signal }) => { oldSignal = signal; return pending.promise; });
    await expect(coordinator.read(KEY, async () => "new", { force: true })).resolves.toMatchObject({ outcome: "applied", sequence: 2 });
    expect(oldSignal.aborted).toBe(true);
    pending.resolve("old");
    await expect(old).resolves.toMatchObject({ outcome: "aborted", silent: true });
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("new");
  });

  it.each([false, true])("blocks pre-confirmation completion (failure=%s) without losing authoritative data", async (failure) => {
    const coordinator = new ResourceCoordinator<string>();
    const pending = deferred<string>();
    const read = coordinator.read(KEY, async () => pending.promise);
    coordinator.applyConfirmed(KEY, "authoritative", { at: 123 });
    if (failure) pending.reject(new Error("synthetic failure"));
    else pending.resolve("old");
    await expect(read).resolves.toMatchObject({ outcome: "barrier_blocked", silent: true });
    expect(coordinator.getSnapshot(KEY)).toMatchObject({ lastConfirmed: "authoritative", lastSuccessfulAt: 123, freshness: "fresh", mutationBarrier: 1 });
    await expect(coordinator.read(KEY, async () => "revalidated")).resolves.toMatchObject({ outcome: "applied" });
  });

  it("identity barriers reject matching reads across keys, including keys minted after an earlier barrier", async () => {
    const coordinator = new ResourceCoordinator<string>();
    coordinator.raiseIdentityBarrier("synthetic", "entity-1");
    const detail = key({ mode: "detail", identity: "entity-1" });
    const comments = key({ mode: "comments", identity: "entity-1" });
    const otherIdentity = key({ mode: "detail", identity: "entity-2" });
    const otherFamily = key({ family: "unrelated", identity: "entity-1" });
    const pending = deferred<string>();
    const reads = [detail, comments, otherIdentity, otherFamily, KEY].map((query) => coordinator.read(query, async () => pending.promise));
    expect(coordinator.raiseIdentityBarrier("synthetic", "entity-1")).toBe(2);
    pending.resolve("response");
    const outcomes = (await Promise.all(reads)).map((result) => result.outcome);
    expect(outcomes).toEqual(["barrier_blocked", "barrier_blocked", "applied", "applied", "applied"]);
    expect(coordinator.getSnapshot(detail)?.lastConfirmed).toBeUndefined();
    await expect(coordinator.read(detail, async () => "post-barrier")).resolves.toMatchObject({ outcome: "applied" });
    const newKey = key({ mode: "detail", identity: "entity-1", cursor: "new" });
    await expect(coordinator.read(newKey, async () => "new-key" )).resolves.toMatchObject({ outcome: "applied" });
    const failed = deferred<string>();
    const blockedFailure = coordinator.read(newKey, async () => failed.promise);
    coordinator.raiseIdentityBarrier("synthetic", "entity-1");
    failed.reject(new Error("late synthetic failure"));
    await expect(blockedFailure).resolves.toMatchObject({ outcome: "barrier_blocked", silent: true });
    expect(coordinator.getSnapshot(newKey)?.lastConfirmed).toBe("new-key");
  });

  it("family invalidation counts known entries, retains data, and blocks all earlier reads without fetching", async () => {
    const coordinator = new ResourceCoordinator<string>();
    const detail = key({ mode: "detail", identity: "one" });
    const other = key({ family: "other" });
    coordinator.applyConfirmed(KEY, "rows");
    coordinator.retain(detail);
    coordinator.applyConfirmed(other, "unrelated");
    const pending = deferred<string>();
    const fetcher = vi.fn(async () => pending.promise);
    const reads = [KEY, detail, other].map((query) => coordinator.read(query, fetcher));
    expect(coordinator.invalidateFamily("synthetic")).toBe(2);
    expect(coordinator.invalidateFamily("unknown")).toBe(0);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(coordinator.getSnapshot(KEY)).toMatchObject({ lastConfirmed: "rows", freshness: "stale" });
    pending.resolve("late");
    expect((await Promise.all(reads)).map((result) => result.outcome)).toEqual(["barrier_blocked", "barrier_blocked", "applied"]);
    expect(coordinator.getSnapshot(detail)?.lastConfirmed).toBeUndefined();
  });
});

describe("ResourceCoordinator freshness and lifetime", () => {
  it("never fabricates empty data from first-load failure or a partial success", async () => {
    const coordinator = new ResourceCoordinator<{ rows: string[]; complete: boolean }>();
    const failure = new Error("synthetic failure");
    await expect(coordinator.read(KEY, async () => { throw failure; })).resolves.toMatchObject({ outcome: "failed", error: failure, silent: false });
    expect(coordinator.getSnapshot(KEY)).toMatchObject({ lastConfirmed: undefined, freshness: "unavailable", lastSuccessfulAt: null });
    coordinator.markFresh(KEY);
    expect(coordinator.getSnapshot(KEY)?.freshness).toBe("unavailable");
    const partial = { rows: [], complete: false };
    await coordinator.read(KEY, async () => partial);
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe(partial);
  });

  it("retains confirmed data/timestamp on refresh failure and permits caller freshness policy", async () => {
    const coordinator = new ResourceCoordinator<string>();
    coordinator.applyConfirmed(KEY, "confirmed", { at: 100 });
    await coordinator.read(KEY, async () => { throw new Error("synthetic"); });
    expect(coordinator.getSnapshot(KEY)).toMatchObject({ lastConfirmed: "confirmed", lastSuccessfulAt: 100, freshness: "stale" });
    coordinator.markUnavailable(KEY);
    expect(coordinator.getSnapshot(KEY)?.freshness).toBe("unavailable");
    coordinator.markSuspended(KEY);
    const pending = deferred<string>();
    const read = coordinator.read(KEY, async () => pending.promise);
    expect(coordinator.getSnapshot(KEY)?.freshness).toBe("suspended");
    pending.resolve("new");
    await read;
    coordinator.markStale(KEY);
    coordinator.markFresh(KEY);
    expect(coordinator.getSnapshot(KEY)?.freshness).toBe("fresh");
  });

  it("reclaims empty unowned entries, retains confirmations/barriers, and aborts only when no owner/listener remains", async () => {
    const coordinator = new ResourceCoordinator<string>();
    expect(coordinator.retain(KEY).refCount).toBe(1);
    coordinator.retain(KEY);
    coordinator.release(KEY);
    expect(coordinator.getSnapshot(KEY)?.refCount).toBe(1);
    coordinator.release(KEY);
    coordinator.release(KEY);
    expect(coordinator.getSnapshot(KEY)).toBeUndefined();
    coordinator.applyConfirmed(KEY, "retained");
    coordinator.release(KEY);
    expect(coordinator.getSnapshot(KEY)).toMatchObject({ lastConfirmed: "retained", refCount: 0 });
    const detail = key({ mode: "detail" });
    coordinator.raiseMutationBarrier(detail);
    coordinator.release(detail);
    expect(coordinator.getSnapshot(detail)?.mutationBarrier).toBe(1);
    const pending = deferred<string>();
    let signal!: AbortSignal;
    coordinator.retain(KEY);
    const listener = vi.fn();
    const unsubscribe = coordinator.subscribe(KEY, listener);
    const read = coordinator.read(KEY, async (context) => { signal = context.signal; return pending.promise; });
    coordinator.release(KEY);
    expect(signal.aborted).toBe(false);
    unsubscribe();
    expect(signal.aborted).toBe(true);
    const calls = listener.mock.calls.length;
    pending.resolve("late");
    await expect(read).resolves.toMatchObject({ outcome: "aborted", silent: true });
    expect(listener).toHaveBeenCalledTimes(calls);
    expect(coordinator.getSnapshot(KEY)?.lastConfirmed).toBe("retained");
  });

  it("disposes deterministically, ignores late completions/listeners, and remints an isolated session", async () => {
    const old = new ResourceCoordinator<string>();
    const pending = deferred<string>();
    const listener = vi.fn();
    old.applyConfirmed(KEY, "old-session");
    old.subscribe(KEY, listener);
    const read = old.read(KEY, async () => pending.promise);
    old.raiseIdentityBarrier("synthetic", "one");
    const calls = listener.mock.calls.length;
    old.dispose();
    old.dispose();
    expect(old.isDisposed()).toBe(true);
    expect(old.getSnapshot(KEY)).toBeUndefined();
    expect(() => old.retain(KEY)).toThrow("ResourceCoordinator has been disposed");
    pending.resolve("late");
    await expect(read).resolves.toMatchObject({ outcome: "aborted", silent: true });
    expect(listener).toHaveBeenCalledTimes(calls);
    const current = new ResourceCoordinator<string>();
    const newKey = key({ sessionEpoch: "session-2", identity: "one" });
    expect(current.getSnapshot(KEY)).toBeUndefined();
    expect(current.raiseIdentityBarrier("synthetic", "one")).toBe(1);
    await expect(current.read(newKey, async () => "new-session")).resolves.toMatchObject({ outcome: "applied" });
    expect(old.getSnapshot(newKey)).toBeUndefined();
    current.dispose();
  });
});
