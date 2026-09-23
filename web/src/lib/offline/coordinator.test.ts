/**
 * T08 — the queue lock (C06).
 *
 * Two behaviours carry the weight: an exclusive name that a second caller cannot
 * enter, and a missing API that refuses rather than degrading. Both are checked
 * against the real coordinator; the Web Locks implementation underneath is a
 * controllable stand-in, because jsdom has none and the browser-level proof of
 * two real tabs belongs to the Playwright lane.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CAPTURE_QUEUE_LOCK_NAME,
  CaptureQueueUnavailableError,
  captureQueueLockSupported,
  withCaptureQueueLock,
} from "@/lib/offline/coordinator";
import { installTestWebLocks, removeWebLocks } from "@/lib/offline/testing/web-locks";

const restores: Array<() => void> = [];

afterEach(() => {
  while (restores.length) restores.pop()!();
});

function withLocks() {
  const locks = installTestWebLocks();
  restores.push(() => locks.restore());
  return locks;
}

describe("holding the lock", () => {
  it("runs the operation and returns its value", async () => {
    withLocks();
    await expect(withCaptureQueueLock(async () => "done")).resolves.toBe("done");
  });

  it("releases the lock when the operation settles, including on a throw", async () => {
    const locks = withLocks();
    await withCaptureQueueLock(async () => {
      expect(locks.held.has(CAPTURE_QUEUE_LOCK_NAME)).toBe(true);
    });
    expect(locks.held.has(CAPTURE_QUEUE_LOCK_NAME)).toBe(false);

    await expect(
      withCaptureQueueLock(async () => {
        throw new Error("synthetic failure");
      }),
    ).rejects.toThrow("synthetic failure");
    expect(locks.held.has(CAPTURE_QUEUE_LOCK_NAME)).toBe(false);

    // And the next caller can still take it.
    await expect(withCaptureQueueLock(async () => "after")).resolves.toBe("after");
  });

  it("asks for the one exclusive name, with ifAvailable and no steal or signal", async () => {
    const locks = withLocks();
    const manager = (globalThis as unknown as {
      navigator: { locks: { request: (...args: unknown[]) => Promise<unknown> } };
    }).navigator.locks;
    const calls: unknown[][] = [];
    const real = manager.request.bind(manager);
    manager.request = (...args: unknown[]) => {
      calls.push(args);
      return real(...args);
    };
    await withCaptureQueueLock(async () => undefined);
    const [name, options] = (calls[0] ?? []) as [string, Record<string, unknown>];
    expect(name).toBe(CAPTURE_QUEUE_LOCK_NAME);
    expect(options).toEqual({ mode: "exclusive", ifAvailable: true });
    expect(options).not.toHaveProperty("steal");
    expect(options).not.toHaveProperty("signal");
    expect(locks.held.has(CAPTURE_QUEUE_LOCK_NAME)).toBe(false);
  });
});

describe("a lock held elsewhere is busy, and busy does nothing at all", () => {
  it("refuses with busy and never invokes the callback", async () => {
    const locks = withLocks();
    const release = locks.hold(CAPTURE_QUEUE_LOCK_NAME);
    const operation = vi.fn(async () => "should not run");

    await expect(withCaptureQueueLock(operation)).rejects.toMatchObject({
      name: "CaptureQueueUnavailableError",
      reason: "busy",
    });
    expect(operation).not.toHaveBeenCalled();

    release();
    await expect(withCaptureQueueLock(operation)).resolves.toBe("should not run");
    expect(operation).toHaveBeenCalledTimes(1);
  });

  it("does not wait for the holder to finish", async () => {
    const locks = withLocks();
    locks.hold(CAPTURE_QUEUE_LOCK_NAME);
    // No timers, no pending promise: an `ifAvailable` request that queued would
    // hang a drain behind another tab's stalled network attempt.
    await expect(withCaptureQueueLock(async () => "x")).rejects.toBeInstanceOf(
      CaptureQueueUnavailableError,
    );
  });
});

describe("no Web Locks API is a refusal, not a fallback", () => {
  it("reports the API as unsupported", () => {
    restores.push(removeWebLocks());
    expect(captureQueueLockSupported()).toBe(false);
  });

  it("refuses with locks_unavailable and never invokes the callback", async () => {
    restores.push(removeWebLocks());
    const operation = vi.fn(async () => "should not run");

    await expect(withCaptureQueueLock(operation)).rejects.toMatchObject({
      name: "CaptureQueueUnavailableError",
      reason: "locks_unavailable",
    });
    expect(operation).not.toHaveBeenCalled();
  });

  it("does not fall back to a per-tab flag that would admit a second caller", async () => {
    restores.push(removeWebLocks());
    const operation = vi.fn(async () => "x");
    await expect(withCaptureQueueLock(operation)).rejects.toBeInstanceOf(
      CaptureQueueUnavailableError,
    );
    await expect(withCaptureQueueLock(operation)).rejects.toBeInstanceOf(
      CaptureQueueUnavailableError,
    );
    expect(operation).not.toHaveBeenCalled();
  });
});

describe("nesting", () => {
  it("a second acquisition from inside the callback is busy rather than reentrant", async () => {
    withLocks();
    const inner = vi.fn(async () => "inner");
    const outcome = await withCaptureQueueLock(async () => {
      // Web Locks are not reentrant. This asserts the shape rather than
      // endorsing it: public locked operations must never call each other, and
      // this is what it looks like when they do.
      await expect(withCaptureQueueLock(inner)).rejects.toMatchObject({ reason: "busy" });
      return "outer";
    });
    expect(outcome).toBe("outer");
    expect(inner).not.toHaveBeenCalled();
  });
});
