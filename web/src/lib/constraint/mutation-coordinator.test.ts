import { describe, expect, it, vi } from "vitest";
import {
  categoryCollectionLockKey,
  categoryLockKey,
  constraintLockKey,
  createConstraintMutationCoordinator,
  mintCreateIntentLockKey,
} from "@/lib/constraint/mutation-coordinator";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const ALWAYS_CURRENT = () => true;

function conflictError(current?: unknown) {
  return { status: 409, message: "version mismatch", current };
}

function networkError() {
  return new TypeError("Failed to fetch");
}

/**
 * Acceptance traceability: `PC-CM-FE-AC-045`, `-054`–`-057`, `-066`, `-074`,
 * `-077`, `-125`, `-128`; `PC-CM-UX-AC-016`/`-017`/`-019`.
 */
describe("ConstraintMutationCoordinator locking (SP2, frozen keys)", () => {
  it("serializes every operation on the same Constraint record under one lock key", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const lockKey = constraintLockKey("cst_aaaaaaaa11111111");
    const gate = deferred<{ version: number }>();

    const first = coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { title: "Renamed" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => gate.promise,
    });

    expect(coordinator.isLocked(lockKey)).toBe(true);

    const second = await coordinator.mutate({
      kind: "constraintTransition",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-2",
      expectedVersion: 1,
      request: { toState: "published" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ version: 2 }),
    });
    expect(second.refused).toBe(true);
    expect(second.reason).toMatch(/lock already held/);

    gate.resolve({ version: 2 });
    const firstOutcome = await first;
    expect(firstOutcome.state.phase).toBe("confirmed");
    expect(coordinator.isLocked(lockKey)).toBe(false);
  });

  it("serializes Category record update/deactivate under category:<id>", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const lockKey = categoryLockKey("cat_aaaaaaaa11111111");
    const gate = deferred<unknown>();

    const first = coordinator.mutate({
      kind: "categoryUpdate",
      lockRequest: { kind: "category-record", key: lockKey, projectId: "prj_aaaaaaaa11111111" },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { name: "Site A" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => gate.promise,
    });

    const second = await coordinator.mutate({
      kind: "categoryDeactivate",
      lockRequest: { kind: "category-record", key: lockKey, projectId: "prj_aaaaaaaa11111111" },
      idempotencyKey: "idem-2",
      request: {},
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({}),
    });
    expect(second.refused).toBe(true);

    gate.resolve({ version: 2 });
    await first;
  });

  it("a Category-collection reorder refuses while any Category-record lock for the same Project is unresolved", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const projectId = "prj_aaaaaaaa11111111";
    const recordGate = deferred<unknown>();

    const recordAttempt = coordinator.mutate({
      kind: "categoryUpdate",
      lockRequest: { kind: "category-record", key: categoryLockKey("cat_1"), projectId },
      idempotencyKey: "idem-record",
      expectedVersion: 1,
      request: { name: "Site A" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => recordGate.promise,
    });

    const reorder = await coordinator.mutate({
      kind: "categoryReorder",
      lockRequest: {
        kind: "category-collection",
        key: categoryCollectionLockKey(projectId),
        projectId,
        checkProjectRecordLocks: true,
      },
      idempotencyKey: "idem-reorder",
      expectedVersions: [1, 2, 3],
      request: { orderedCategoryIds: ["cat_1", "cat_2", "cat_3"] },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({}),
    });
    expect(reorder.refused).toBe(true);
    expect(reorder.reason).toMatch(/blocked by outstanding category record lock/);

    recordGate.resolve({ version: 2 });
    await recordAttempt;

    // Once the record lock clears, the same reorder request succeeds.
    const retried = await coordinator.mutate({
      kind: "categoryReorder",
      lockRequest: {
        kind: "category-collection",
        key: categoryCollectionLockKey(projectId),
        projectId,
        checkProjectRecordLocks: true,
      },
      idempotencyKey: "idem-reorder-2",
      expectedVersions: [2, 1, 3],
      request: { orderedCategoryIds: ["cat_2", "cat_1", "cat_3"] },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async ({ expectedVersions }) => ({ expectedVersions }),
    });
    expect(retried.refused).toBe(false);
    expect(retried.state.phase).toBe("confirmed");
  });

  it("a Category-collection create is not blocked by an outstanding record lock (checkProjectRecordLocks unset)", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const projectId = "prj_aaaaaaaa11111111";
    const recordGate = deferred<unknown>();

    coordinator.mutate({
      kind: "categoryUpdate",
      lockRequest: { kind: "category-record", key: categoryLockKey("cat_1"), projectId },
      idempotencyKey: "idem-record",
      expectedVersion: 1,
      request: { name: "Site A" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => recordGate.promise,
    });

    const create = await coordinator.mutate({
      kind: "categoryCreate",
      lockRequest: { kind: "category-collection", key: categoryCollectionLockKey(projectId), projectId },
      idempotencyKey: "idem-create",
      request: { name: "Site B" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ categoryId: "cat_2" }),
    });
    expect(create.refused).toBe(false);
    recordGate.resolve({});
  });

  it("gives one create-intent lock per mounted Create surface instance, with no id-parameter collision", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const surfaceA = mintCreateIntentLockKey("constraint-create");
    const surfaceB = mintCreateIntentLockKey("constraint-create");
    expect(surfaceA).not.toBe(surfaceB);

    const gateA = deferred<unknown>();
    const attemptA = coordinator.mutate({
      kind: "constraintCreate",
      lockRequest: { kind: "create-intent", key: surfaceA },
      idempotencyKey: "idem-a",
      request: { title: "New constraint" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => gateA.promise,
    });

    // A second, concurrently-mounted Create surface has its own key and is unaffected.
    const attemptB = await coordinator.mutate({
      kind: "constraintCreate",
      lockRequest: { kind: "create-intent", key: surfaceB },
      idempotencyKey: "idem-b",
      request: { title: "Another constraint" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ constraintId: "cst_b" }),
    });
    expect(attemptB.refused).toBe(false);

    // But a second attempt against the SAME surface's key is refused.
    const collision = await coordinator.mutate({
      kind: "constraintCreate",
      lockRequest: { kind: "create-intent", key: surfaceA },
      idempotencyKey: "idem-a-2",
      request: { title: "Racing the first" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({}),
    });
    expect(collision.refused).toBe(true);

    gateA.resolve({ constraintId: "cst_a" });
    await attemptA;
  });
});

describe("ConstraintMutationCoordinator ambiguous handling", () => {
  it("keeps an ambiguous attempt's lock held and refuses a second material attempt until retry settles", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const lockKey = constraintLockKey("cst_aaaaaaaa11111111");
    let dispatchAttempts = 0;

    const first = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { title: "Renamed" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => {
        dispatchAttempts += 1;
        if (dispatchAttempts === 1) throw networkError();
        return { version: 2 };
      },
    });
    expect(first.state.phase).toBe("ambiguous");
    expect(coordinator.isLocked(lockKey)).toBe(true);

    const second = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-2",
      expectedVersion: 1,
      request: { title: "A different edit" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ version: 2 }),
    });
    expect(second.refused).toBe(true);

    const retried = await coordinator.retry(first.attemptId, 0, ALWAYS_CURRENT);
    expect(retried.state.phase).toBe("confirmed");
    expect(coordinator.isLocked(lockKey)).toBe(false);
  });

  it("retains the same idempotencyKey across an ambiguous retry (stable request/key)", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const seen: string[] = [];
    let attempt = 0;

    const outcome = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "stable-key-1",
      expectedVersion: 1,
      request: { title: "Renamed" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async ({ idempotencyKey }) => {
        seen.push(idempotencyKey);
        attempt += 1;
        if (attempt === 1) throw networkError();
        return { version: 2 };
      },
    });
    expect(outcome.state.phase).toBe("ambiguous");

    const retried = await coordinator.retry(outcome.attemptId, 0, ALWAYS_CURRENT);
    expect(retried.state.phase).toBe("confirmed");
    expect(seen).toEqual(["stable-key-1", "stable-key-1"]);
  });

  it("explicit abandon releases the lock without treating the attempt as retried", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const lockKey = constraintLockKey("cst_1");

    const outcome = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { title: "Renamed" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => {
        throw networkError();
      },
    });
    expect(outcome.state.phase).toBe("ambiguous");

    const abandoned = coordinator.abandon(outcome.attemptId);
    expect(abandoned).toBe(true);
    expect(coordinator.isLocked(lockKey)).toBe(false);
    expect(coordinator.getState(outcome.attemptId)?.phase).toBe("idle");

    // A fresh mutate() now succeeds without needing retry().
    const fresh = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-2",
      expectedVersion: 1,
      request: { title: "Try again" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ version: 2 }),
    });
    expect(fresh.refused).toBe(false);
  });
});

describe("ConstraintMutationCoordinator conflict handling", () => {
  it("on 409, releases the lock but preserves base/current/attempted for the caller", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const lockKey = constraintLockKey("cst_1");
    const currentFromServer = { constraintId: "cst_1", version: 3, title: "Someone else's edit" };

    const outcome = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { title: "My edit" },
      baseSnapshot: { constraintId: "cst_1", version: 1, title: "Original" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => {
        throw conflictError(currentFromServer);
      },
    });

    expect(outcome.state.phase).toBe("conflict");
    expect(coordinator.isLocked(lockKey)).toBe(false);
    expect(outcome.state.conflict).toEqual({
      base: { constraintId: "cst_1", version: 1, title: "Original" },
      current: currentFromServer,
      attempted: { title: "My edit" },
    });

    // A deliberate reapply is a NEW request/key, not `retry()` on the old attempt.
    const reapply = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-2-after-review",
      expectedVersion: 3,
      request: { title: "My edit, rebased" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ version: 4 }),
    });
    expect(reapply.refused).toBe(false);
    expect(reapply.attemptId).not.toBe(outcome.attemptId);
  });

  it("fetches current state via hooks.fetchCurrent when the 409 body carries none", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const fetchCurrent = vi.fn(async () => ({ constraintId: "cst_1", version: 5 }));

    const outcome = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { title: "My edit" },
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => {
        throw conflictError(undefined);
      },
      hooks: { fetchCurrent },
    });

    expect(fetchCurrent).toHaveBeenCalledTimes(1);
    expect(outcome.state.conflict?.current).toEqual({ constraintId: "cst_1", version: 5 });
  });
});

describe("ConstraintMutationCoordinator hooks", () => {
  it("calls reconcile/feedback/resolveFocus on confirm, and only feedback/resolveFocus (no reconcile) on failure", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const calls: string[] = [];

    await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: {},
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ version: 2 }),
      hooks: {
        reconcile: () => void calls.push("reconcile"),
        feedback: (_r, phase) => void calls.push(`feedback:${phase}`),
        resolveFocus: (_r, phase) => void calls.push(`focus:${phase}`),
      },
    });
    expect(calls).toEqual(["reconcile", "feedback:confirmed", "focus:confirmed"]);

    calls.length = 0;
    await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_2") },
      idempotencyKey: "idem-2",
      expectedVersion: 1,
      request: {},
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => {
        throw { status: 422, message: "invalid" };
      },
      hooks: {
        reconcile: () => void calls.push("reconcile"),
        feedback: (_r, phase) => void calls.push(`feedback:${phase}`),
        resolveFocus: (_r, phase) => void calls.push(`focus:${phase}`),
      },
    });
    expect(calls).toEqual(["feedback:failed", "focus:failed"]);
  });
});

describe("ConstraintMutationCoordinator CanSwitchProjectScope ingredients", () => {
  it("hasPendingOrAmbiguousMutation reflects a pending dispatch and clears on confirm", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const gate = deferred<unknown>();
    expect(coordinator.hasPendingOrAmbiguousMutation()).toBe(false);

    const attempt = coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: {},
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => gate.promise,
    });
    expect(coordinator.hasPendingOrAmbiguousMutation()).toBe(true);

    gate.resolve({ version: 2 });
    await attempt;
    expect(coordinator.hasPendingOrAmbiguousMutation()).toBe(false);
  });

  it("hasPendingOrAmbiguousMutation stays true through an ambiguous outcome", async () => {
    const coordinator = createConstraintMutationCoordinator();
    await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: {},
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => {
        throw networkError();
      },
    });
    expect(coordinator.hasPendingOrAmbiguousMutation()).toBe(true);
  });

  it("hasDirtyAuthoredState reflects registered surfaces", () => {
    const coordinator = createConstraintMutationCoordinator();
    expect(coordinator.hasDirtyAuthoredState()).toBe(false);
    coordinator.reportDirtyState("constraint-authoring:instance-1", true);
    expect(coordinator.hasDirtyAuthoredState()).toBe(true);
    coordinator.reportDirtyState("constraint-authoring:instance-1", false);
    expect(coordinator.hasDirtyAuthoredState()).toBe(false);

    coordinator.reportDirtyState("a", true);
    coordinator.reportDirtyState("b", true);
    coordinator.clearDirtyState("a");
    expect(coordinator.hasDirtyAuthoredState()).toBe(true);
    coordinator.clearDirtyState("b");
    expect(coordinator.hasDirtyAuthoredState()).toBe(false);
  });
});

/**
 * Mandatory prove-red obligation (dispatch §4, Artifact 05 SP3.6).
 *
 * "Allow a Project-scope epoch change to apply a prior-epoch ... mutation
 * response → runtime stale-epoch test fails." This is the multi-epoch test
 * the dispatch requires for the mutation coordinator; its red→green run
 * against a temporarily-stripped epoch guard is recorded verbatim in the
 * Phase-4 handoff (§ Stale-epoch prove-red).
 */
describe("ConstraintMutationCoordinator SP3.6 stale-epoch suppression", () => {
  it("drops a confirming response under a retired epoch: no reconcile, no feedback, no focus resolution", async () => {
    const coordinator = createConstraintMutationCoordinator();
    let currentEpoch = 0;
    const isCurrentEpoch = (epoch: number) => epoch === currentEpoch;
    const gate = deferred<{ version: number }>();
    const calls: string[] = [];

    const attempt = coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { title: "Renamed" },
      epoch: 0,
      isCurrentEpoch,
      dispatch: async () => gate.promise,
      hooks: {
        reconcile: () => void calls.push("reconcile"),
        feedback: (_r, phase) => void calls.push(`feedback:${phase}`),
        resolveFocus: (_r, phase) => void calls.push(`focus:${phase}`),
      },
    });

    // The Project scope changes while the write is in flight.
    currentEpoch = 1;
    gate.resolve({ version: 2 });
    const outcome = await attempt;

    expect(outcome.state.phase).toBe("stale_epoch");
    expect(outcome.epochStale).toBe(true);
    expect(outcome.result).toBeUndefined();
    expect(calls).toEqual([]); // no reconcile, no feedback, no focus resolution
    expect(outcome.state.confirmedResult).toBeUndefined();
    expect(outcome.state.conflict).toBeUndefined();
  });

  it("drops a conflicting (409) response under a retired epoch: no conflict base/current/attempted crosses the boundary", async () => {
    const coordinator = createConstraintMutationCoordinator();
    let currentEpoch = 0;
    const isCurrentEpoch = (epoch: number) => epoch === currentEpoch;
    const gate = deferred<never>();
    const calls: string[] = [];

    const attempt = coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: { title: "Renamed" },
      baseSnapshot: { version: 1 },
      epoch: 0,
      isCurrentEpoch,
      dispatch: async () => gate.promise,
      hooks: {
        feedback: (_r, phase) => void calls.push(`feedback:${phase}`),
        resolveFocus: (_r, phase) => void calls.push(`focus:${phase}`),
      },
    });

    currentEpoch = 1;
    gate.reject(conflictError({ version: 9 }));
    const outcome = await attempt;

    expect(outcome.state.phase).toBe("stale_epoch");
    expect(outcome.state.conflict).toBeUndefined();
    expect(calls).toEqual([]);
  });

  it("still releases the lock on a stale-epoch drop, so the resource is never left deadlocked", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const lockKey = constraintLockKey("cst_1");
    let currentEpoch = 0;
    const isCurrentEpoch = (epoch: number) => epoch === currentEpoch;
    const gate = deferred<{ version: number }>();

    const attempt = coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: lockKey },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: {},
      epoch: 0,
      isCurrentEpoch,
      dispatch: async () => gate.promise,
    });

    currentEpoch = 1;
    gate.resolve({ version: 2 });
    await attempt;

    expect(coordinator.isLocked(lockKey)).toBe(false);
  });

  it("still applies a response whose captured epoch remains current (control case)", async () => {
    const coordinator = createConstraintMutationCoordinator();
    const calls: string[] = [];

    const outcome = await coordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: {},
      epoch: 0,
      isCurrentEpoch: ALWAYS_CURRENT,
      dispatch: async () => ({ version: 2 }),
      hooks: { feedback: (_r, phase) => void calls.push(phase) },
    });

    expect(outcome.state.phase).toBe("confirmed");
    expect(calls).toEqual(["confirmed"]);
  });
});
