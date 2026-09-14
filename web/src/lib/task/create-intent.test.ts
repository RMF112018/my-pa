import { afterEach, describe, expect, it, vi } from "vitest";
import { CreateIntentStore, createIntentStore } from "@/lib/task/create-intent";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/**
 * Acceptance traceability: TASK-AC-006, TASK-AC-007, TASK-AC-008, TASK-AC-030,
 * TASK-AC-031, TASK-AC-032.
 *
 * One intent mints one key (006, 008), an ambiguous or retryable transport failure
 * reuses that key rather than minting a second Task (007, 032), the store outlives the
 * form that opened it (030), and a definitive failure preserves the draft (031).
 */
describe("CreateIntentStore", () => {
  it("mints one stable intent and key when a create session opens", () => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => "11111111-1111-4111-8111-111111111111"),
    });
    const store = createIntentStore();
    const session = store.openSession({ title: "Call Sam" });
    expect(session.intentId).toBe("11111111-1111-4111-8111-111111111111");
    expect(session.idempotencyKey).toBe("task-create-11111111-1111-4111-8111-111111111111");
    expect(session.idempotencyKey).toMatch(/^[A-Za-z0-9_-]{8,128}$/);
    expect(session.getPhase()).toBe("draft");
    expect(session.snapshot().dispatching).toBe(false);
  });

  it("refuses a second concurrent dispatch with no second network call", async () => {
    const store = new CreateIntentStore();
    const session = store.openSession({ title: "Ship WP-TUX-02" });
    const gate = deferred<{ task_id: string }>();
    const dispatch = vi.fn(async () => gate.promise);

    const first = session.submit(dispatch);
    const second = await session.submit(dispatch);

    expect(second).toEqual({ refused: true, reason: "create dispatch already in flight" });
    expect(dispatch).toHaveBeenCalledTimes(1);

    gate.resolve({ task_id: "tsk_aaaaaaaa11111111" });
    const outcome = await first;
    expect(outcome).toMatchObject({ refused: false, result: { task_id: "tsk_aaaaaaaa11111111" } });
    expect(session.getPhase()).toBe("confirmed");
  });

  it("retains the same key and frozen request after an ambiguous network failure", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Retain me", priority: "p2" });
    const keys: string[] = [];
    const requests: unknown[] = [];

    await expect(
      session.submit(async ({ request, idempotencyKey }) => {
        keys.push(idempotencyKey);
        requests.push(request);
        throw new TypeError("response lost");
      }),
    ).rejects.toThrow(/response lost/);

    expect(session.getPhase()).toBe("ambiguous");
    expect(session.getFrozenRequest()).toEqual({ title: "Retain me", priority: "p2" });
    expect(session.idempotencyKey).toBe(keys[0]);

    expect(() => session.updateDraft({ title: "Changed" })).toThrow(/blocked while .* ambiguous/);
  });

  it("retries a 503 with the exact same key and frozen request", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Retry me" });
    const keys: string[] = [];
    let attempt = 0;

    await expect(
      session.submit(async ({ request, idempotencyKey }) => {
        keys.push(idempotencyKey);
        attempt += 1;
        if (attempt === 1) {
          const error = Object.assign(new Error("gateway"), { status: 503 });
          throw error;
        }
        return { task_id: "tsk_bbbbbbbb22222222", title: request.title };
      }),
    ).rejects.toMatchObject({ status: 503 });

    expect(session.getPhase()).toBe("ambiguous");
    const frozen = session.getFrozenRequest();

    const retry = await session.retry(async ({ request, idempotencyKey }) => {
      keys.push(idempotencyKey);
      return { task_id: "tsk_bbbbbbbb22222222", title: request.title };
    });

    expect(retry).toMatchObject({ refused: false, result: { task_id: "tsk_bbbbbbbb22222222" } });
    expect(keys[0]).toBe(keys[1]);
    expect(frozen).toEqual({ title: "Retry me" });
    expect(session.getPhase()).toBe("confirmed");
  });

  it("preserves draft on definitive failure and mints a new intent only after material change", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Original", dueAt: "2026-09-12T12:00:00.000Z" });
    const originalKey = session.idempotencyKey;

    await expect(
      session.submit(async () => {
        throw Object.assign(new Error("bad title"), { status: 400, code: "validation" });
      }),
    ).rejects.toMatchObject({ status: 400 });

    expect(session.getPhase()).toBe("failed");
    expect(session.getDraft()).toEqual({ title: "Original", dueAt: "2026-09-12T12:00:00.000Z" });

    // Unchanged draft may reuse the same human intent/key (e.g. after precondition fix).
    const reused = await session.submit(async ({ idempotencyKey }) => {
      expect(idempotencyKey).toBe(originalKey);
      return { task_id: "tsk_reused" };
    });
    expect(reused).toMatchObject({ refused: false, result: { task_id: "tsk_reused" } });
  });

  it("requires a new intent after definitive failure when the draft changes materially", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Original", dueAt: "2026-09-12T12:00:00.000Z" });

    await expect(
      session.submit(async () => {
        throw Object.assign(new Error("bad title"), { status: 400, code: "validation" });
      }),
    ).rejects.toMatchObject({ status: 400 });

    session.updateDraft({ title: "Edited after failure" });
    const materialRefuse = await session.submit(async () => ({ task_id: "x" }));
    expect(materialRefuse).toMatchObject({
      refused: true,
      reason: expect.stringMatching(/new intent/),
    });

    const next = store.replaceAfterMaterialEdit(session, {
      title: "Edited after failure",
      dueAt: "2026-09-12T12:00:00.000Z",
    });
    expect(next.intentId).not.toBe(session.intentId);
    expect(next.idempotencyKey).not.toBe(session.idempotencyKey);
    expect(next.getDraft().title).toBe("Edited after failure");
  });

  it("mints different keys for two deliberate sessions with identical content", () => {
    const store = createIntentStore();
    const a = store.openSession({ title: "Same title", priority: "p1" });
    const b = store.openSession({ title: "Same title", priority: "p1" });
    expect(a.intentId).not.toBe(b.intentId);
    expect(a.idempotencyKey).not.toBe(b.idempotencyKey);
  });

  it("keeps an unresolved intent in the store after the form would unmount", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Survive unmount" });
    const gate = deferred<never>();

    const pending = session.submit(async () => gate.promise);
    // Simulate form unmount: drop local reference only.
    expect(store.getUnresolvedSession()?.intentId).toBe(session.intentId);
    expect(store.getUnresolvedSession()?.getPhase()).toBe("pending");

    gate.reject(Object.assign(new Error("503"), { status: 503 }));
    await expect(pending).rejects.toMatchObject({ status: 503 });
    expect(store.getUnresolvedSession()?.getPhase()).toBe("ambiguous");
    expect(store.getUnresolvedSession()?.idempotencyKey).toBe(session.idempotencyKey);
  });

  it("keeps confirmed phase when reconcile throws after a successful dispatch", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Hook fail" });

    const outcome = await session.submit(
      async () => ({ task_id: "tsk_dddddddd44444444" }),
      {
        reconcile: async () => {
          throw new Error("TaskReadCoordinator has been disposed");
        },
      },
    );

    expect(outcome).toEqual({ refused: false, result: { task_id: "tsk_dddddddd44444444" } });
    expect(session.getPhase()).toBe("confirmed");
    expect(session.isRetired()).toBe(true);
  });

  it("runs confirm then reconcile then feedback before retiring", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Ordered" });
    const order: string[] = [];

    await session.submit(
      async () => {
        order.push("dispatch");
        return { task_id: "tsk_cccccccc33333333" };
      },
      {
        reconcile: async () => {
          order.push("reconcile");
        },
        feedback: async () => {
          order.push("feedback");
        },
      },
    );

    expect(order).toEqual(["dispatch", "reconcile", "feedback"]);
    expect(session.isRetired()).toBe(true);
    expect(session.getPhase()).toBe("confirmed");
  });
});

/**
 * Acceptance traceability: WP02-AC-074.
 *
 * Two independently-mounted create surfaces share one session, so the session must
 * publish snapshot-relevant changes. `subscribe` returns an unsubscribe that leaves
 * no stale listener behind (WP02-AC-074).
 */
describe("CreateIntentSession.subscribe", () => {
  it("notifies a subscriber and stops after unsubscribe", () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Observe me" });
    const listener = vi.fn();

    const unsubscribe = session.subscribe(listener);
    session.updateDraft({ title: "Observed" });
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    session.updateDraft({ title: "After unsubscribe" });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("is safe to unsubscribe twice and retains no stale listener (WP02-AC-074)", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Stale check" });
    const listener = vi.fn();

    const unsubscribe = session.subscribe(listener);
    unsubscribe();
    expect(() => unsubscribe()).not.toThrow();

    session.updateDraft({ title: "Still quiet" });
    await session.submit(async () => ({ task_id: "tsk_stale0000000000" }));
    expect(listener).not.toHaveBeenCalled();
    expect(session.getPhase()).toBe("confirmed");
  });

  it("notifies on draft → pending → confirmed transitions", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Phase walk" });
    const gate = deferred<{ task_id: string }>();
    const phases: string[] = [];

    session.subscribe(() => {
      phases.push(session.snapshot().phase);
    });

    const inFlight = session.submit(async () => gate.promise);
    expect(phases).toContain("pending");

    gate.resolve({ task_id: "tsk_eeeeeeee55555555" });
    await inFlight;

    expect(phases).toContain("confirmed");
    expect(session.getPhase()).toBe("confirmed");
  });

  it("notifies when an ambiguous failure settles", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Ambiguous notify" });
    const phases: string[] = [];
    session.subscribe(() => {
      phases.push(session.snapshot().phase);
    });

    await expect(
      session.submit(async () => {
        throw new TypeError("response lost");
      }),
    ).rejects.toThrow(/response lost/);

    expect(session.getPhase()).toBe("ambiguous");
    expect(phases).toContain("ambiguous");
  });

  it("does not notify when a write leaves snapshot-relevant state unchanged", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "No-op" });
    const listener = vi.fn();
    session.subscribe(listener);

    session.updateDraft({});
    session.updateDraft({ title: "No-op" });
    expect(listener).not.toHaveBeenCalled();

    const gate = deferred<{ task_id: string }>();
    const inFlight = session.submit(async () => gate.promise);
    listener.mockClear();

    // Refused concurrent submit changes nothing.
    const refused = await session.submit(async () => ({ task_id: "never" }));
    expect(refused).toMatchObject({ refused: true });
    expect(listener).not.toHaveBeenCalled();

    gate.resolve({ task_id: "tsk_ffffffff66666666" });
    await inFlight;
  });

  it("keeps notifying other listeners when one throws and leaves the session intact", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Throwing listener" });
    const after = vi.fn();

    session.subscribe(() => {
      throw new Error("listener exploded");
    });
    session.subscribe(after);

    expect(() => session.updateDraft({ title: "Edited" })).not.toThrow();
    expect(after).toHaveBeenCalled();
    expect(session.getDraft().title).toBe("Edited");

    const outcome = await session.submit(async () => ({ task_id: "tsk_99999999aaaaaaaa" }));
    expect(outcome).toMatchObject({ refused: false });
    expect(session.getPhase()).toBe("confirmed");
  });

  it("does not skip a listener that is unsubscribed during notification", () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Reentrant" });
    const second = vi.fn();

    const unsubscribeSecond = () => unsubSecond();
    const first = vi.fn(() => {
      unsubscribeSecond();
    });
    session.subscribe(first);
    const unsubSecond = session.subscribe(second);

    session.updateDraft({ title: "Reentrant edit" });
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);

    session.updateDraft({ title: "Reentrant edit 2" });
    expect(first).toHaveBeenCalledTimes(2);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("notifies on abandon and on retry of an ambiguous intent", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Retry notify" });
    const phases: string[] = [];
    session.subscribe(() => {
      phases.push(session.snapshot().phase);
    });

    await expect(
      session.submit(async () => {
        throw Object.assign(new Error("gateway"), { status: 503 });
      }),
    ).rejects.toMatchObject({ status: 503 });
    expect(phases).toContain("ambiguous");

    phases.length = 0;
    await session.retry(async () => ({ task_id: "tsk_77777777bbbbbbbb" }));
    expect(phases).toContain("pending");
    expect(phases).toContain("confirmed");

    const other = store.openSession({ title: "Abandon notify" });
    const abandonListener = vi.fn();
    other.subscribe(abandonListener);
    other.abandon();
    expect(abandonListener).toHaveBeenCalled();
    expect(other.getPhase()).toBe("abandoned");
  });

  it("notifies when the dispatching projection clears", async () => {
    const store = createIntentStore();
    const session = store.openSession({ title: "Dispatch flag" });
    const dispatching: boolean[] = [];
    session.subscribe(() => {
      dispatching.push(session.snapshot().dispatching);
    });

    await expect(
      session.submit(async () => {
        throw Object.assign(new Error("bad title"), { status: 400, code: "validation" });
      }),
    ).rejects.toMatchObject({ status: 400 });

    expect(dispatching).toContain(true);
    expect(dispatching[dispatching.length - 1]).toBe(false);
    expect(session.snapshot().dispatching).toBe(false);
  });
});
