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
