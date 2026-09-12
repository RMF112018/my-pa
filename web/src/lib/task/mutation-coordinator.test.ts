import { describe, expect, it, vi } from "vitest";
import { createTaskMutationCoordinator } from "@/lib/task/mutation-coordinator";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("TaskMutationCoordinator", () => {
  it("includes expectedVersion and stable key on versioned mutations", async () => {
    const coordinator = createTaskMutationCoordinator();
    const seen: Array<{ expectedVersion?: number; idempotencyKey: string }> = [];

    const outcome = await coordinator.mutate({
      kind: "status",
      taskId: "tsk_aaaaaaaa11111111",
      expectedVersion: 4,
      idempotencyKey: "task-status:intent-1",
      request: { toState: "in_progress" },
      dispatch: async ({ expectedVersion, idempotencyKey }) => {
        seen.push({ expectedVersion, idempotencyKey });
        return { task_id: "tsk_aaaaaaaa11111111", version: 5, lifecycle_state: "in_progress" };
      },
    });

    expect(outcome.refused).toBe(false);
    expect(seen).toEqual([{ expectedVersion: 4, idempotencyKey: "task-status:intent-1" }]);
    expect(outcome.state.phase).toBe("confirmed");
    expect(outcome.state.expectedVersion).toBe(4);
  });

  it("applies optimistic status then replaces with canonical confirmation", async () => {
    const coordinator = createTaskMutationCoordinator();
    const projections: string[] = [];
    const gate = deferred<{ version: number; lifecycle_state: string }>();

    const pending = coordinator.mutate({
      kind: "status",
      taskId: "tsk_aaaaaaaa11111111",
      expectedVersion: 4,
      idempotencyKey: "task-status:opt-1",
      request: { toState: "in_progress" },
      optimistic: { status: "in_progress" },
      hooks: {
        onOptimistic: (p) => {
          projections.push(`optimistic:${p.status}`);
        },
        reconcile: async (result) => {
          projections.push(`canonical:v${result.version}`);
        },
      },
      dispatch: async () => gate.promise,
    });

    expect(projections).toEqual(["optimistic:in_progress"]);
    expect(coordinator.isTaskLocked("tsk_aaaaaaaa11111111")).toBe(true);

    gate.resolve({ version: 5, lifecycle_state: "in_progress" });
    const outcome = await pending;
    expect(outcome.state.phase).toBe("confirmed");
    expect(projections).toEqual(["optimistic:in_progress", "canonical:v5"]);
    expect(coordinator.isTaskLocked("tsk_aaaaaaaa11111111")).toBe(false);
  });

  it("rolls back optimistic due on definitive failure", async () => {
    const coordinator = createTaskMutationCoordinator();
    const events: string[] = [];

    const outcome = await coordinator.mutate({
      kind: "due",
      taskId: "tsk_aaaaaaaa11111111",
      expectedVersion: 2,
      idempotencyKey: "task-due:1",
      request: { dueAt: "2026-09-20T15:00:00.000Z" },
      draft: { dueAt: "2026-09-20T15:00:00.000Z" },
      optimistic: { dueAt: "2026-09-20T15:00:00.000Z" },
      hooks: {
        onOptimistic: (p) => events.push(`opt:${p.dueAt}`),
        onRollback: () => events.push("rollback"),
      },
      dispatch: async () => {
        throw Object.assign(new Error("invalid due"), { status: 422 });
      },
    });

    expect(outcome.state.phase).toBe("failed");
    expect(outcome.state.error?.subtype).toBe("validation");
    expect(outcome.draft).toEqual({ dueAt: "2026-09-20T15:00:00.000Z" });
    expect(events).toEqual(["opt:2026-09-20T15:00:00.000Z", "rollback"]);
  });

  it("does not mark create or close confirmed before the server result", async () => {
    const coordinator = createTaskMutationCoordinator();
    const createGate = deferred<{ task_id: string }>();
    const closeGate = deferred<{ version: number }>();
    const phases: string[] = [];

    const createPending = coordinator.mutate({
      kind: "create",
      idempotencyKey: "task-create:c1",
      request: { title: "New" },
      hooks: {
        feedback: async (_r, phase) => {
          phases.push(`create:${phase}`);
        },
      },
      dispatch: async () => createGate.promise,
    });
    expect(coordinator.getLatestCreate()?.phase).toBe("pending");
    expect(phases).toEqual([]);

    createGate.resolve({ task_id: "tsk_new" });
    await createPending;
    expect(phases).toEqual(["create:confirmed"]);

    const closePending = coordinator.mutate({
      kind: "close",
      taskId: "tsk_new",
      expectedVersion: 1,
      idempotencyKey: "task-close:1",
      request: { toState: "completed" },
      hooks: {
        feedback: async (_r, phase) => {
          phases.push(`close:${phase}`);
        },
      },
      dispatch: async () => closeGate.promise,
    });
    expect(coordinator.getLatestForTask("tsk_new")?.phase).toBe("pending");
    closeGate.resolve({ version: 2 });
    await closePending;
    expect(phases).toEqual(["create:confirmed", "close:confirmed"]);
  });

  it("serializes versioned mutations on the same Task", async () => {
    const coordinator = createTaskMutationCoordinator();
    const gate = deferred<{ version: number }>();
    const first = coordinator.mutate({
      kind: "status",
      taskId: "tsk_same",
      expectedVersion: 1,
      idempotencyKey: "task-status:a",
      request: { toState: "in_progress" },
      dispatch: async () => gate.promise,
    });

    const second = await coordinator.mutate({
      kind: "due",
      taskId: "tsk_same",
      expectedVersion: 1,
      idempotencyKey: "task-due:a",
      request: { dueAt: "2026-09-21T00:00:00.000Z" },
      dispatch: async () => ({ version: 99 }),
    });

    expect(second.refused).toBe(true);
    expect(second.reason).toMatch(/already in flight/);
    gate.resolve({ version: 2 });
    await first;
  });

  it("allows concurrent mutations on different Task ids", async () => {
    const coordinator = createTaskMutationCoordinator();
    const a = deferred<{ version: number }>();
    const b = deferred<{ version: number }>();
    const started: string[] = [];

    const left = coordinator.mutate({
      kind: "status",
      taskId: "tsk_left",
      expectedVersion: 1,
      idempotencyKey: "task-status:left",
      request: { toState: "in_progress" },
      dispatch: async () => {
        started.push("left");
        return a.promise;
      },
    });
    const right = coordinator.mutate({
      kind: "status",
      taskId: "tsk_right",
      expectedVersion: 3,
      idempotencyKey: "task-status:right",
      request: { toState: "waiting" },
      dispatch: async () => {
        started.push("right");
        return b.promise;
      },
    });

    expect(started.sort()).toEqual(["left", "right"]);
    a.resolve({ version: 2 });
    b.resolve({ version: 4 });
    const [l, r] = await Promise.all([left, right]);
    expect(l.state.phase).toBe("confirmed");
    expect(r.state.phase).toBe("confirmed");
  });

  it("does not serialize comment create with the versioned Task lock", async () => {
    const coordinator = createTaskMutationCoordinator();
    const statusGate = deferred<{ version: number }>();
    const commentGate = deferred<{ comment_id: string }>();

    const status = coordinator.mutate({
      kind: "status",
      taskId: "tsk_comment",
      expectedVersion: 1,
      idempotencyKey: "task-status:c",
      request: { toState: "in_progress" },
      dispatch: async () => statusGate.promise,
    });

    const comment = coordinator.mutate({
      kind: "commentCreate",
      taskId: "tsk_comment",
      idempotencyKey: "task-commentCreate:c",
      request: { body: "note" },
      dispatch: async () => commentGate.promise,
    });

    expect(coordinator.isTaskLocked("tsk_comment")).toBe(true);
    expect(coordinator.isCommentLocked("tsk_comment")).toBe(true);

    commentGate.resolve({ comment_id: "cmt_1" });
    statusGate.resolve({ version: 2 });
    const [s, c] = await Promise.all([status, comment]);
    expect(s.refused).toBe(false);
    expect(c.refused).toBe(false);
  });

  it("on 409 with current enters conflict, preserves draft, and does not auto-resubmit", async () => {
    const coordinator = createTaskMutationCoordinator();
    const dispatch = vi.fn(async () => {
      throw Object.assign(new Error("version changed"), {
        status: 409,
        code: "conflict",
        current: { task_id: "tsk_conflict", version: 9, title: "Server title" },
      });
    });

    const outcome = await coordinator.mutate({
      kind: "update",
      taskId: "tsk_conflict",
      expectedVersion: 8,
      idempotencyKey: "task-update:1",
      request: { title: "Draft title" },
      draft: { title: "Draft title", description: "keep me" },
      dispatch,
    });

    expect(outcome.state.phase).toBe("conflict");
    expect(outcome.state.conflictCurrent).toEqual({
      task_id: "tsk_conflict",
      version: 9,
      title: "Server title",
    });
    expect(outcome.draft).toEqual({ title: "Draft title", description: "keep me" });
    expect(dispatch).toHaveBeenCalledTimes(1);

    const retry = await coordinator.retry(outcome.attemptId);
    expect(retry.refused).toBe(true);
    expect(retry.reason).toMatch(/ambiguous/);
    expect(dispatch).toHaveBeenCalledTimes(1);
  });

  it("retries ambiguous failures with the same idempotency key", async () => {
    const coordinator = createTaskMutationCoordinator();
    const keys: string[] = [];
    let n = 0;

    const first = await coordinator.mutate({
      kind: "status",
      taskId: "tsk_amb",
      expectedVersion: 1,
      idempotencyKey: "task-status:amb",
      request: { toState: "blocked" },
      dispatch: async ({ idempotencyKey }) => {
        keys.push(idempotencyKey);
        n += 1;
        if (n === 1) throw Object.assign(new Error("503"), { status: 503 });
        return { version: 2 };
      },
    });

    expect(first.state.phase).toBe("ambiguous");
    expect(first.state.idempotencyKey).toBe("task-status:amb");

    const second = await coordinator.retry(first.attemptId);
    expect(second.refused).toBe(false);
    expect(second.state.phase).toBe("confirmed");
    expect(keys[0]).toBe(keys[1]);
  });

  it("invokes mutation barrier hooks around dispatch", async () => {
    const coordinator = createTaskMutationCoordinator();
    const barriers: string[] = [];

    await coordinator.mutate({
      kind: "status",
      taskId: "tsk_barrier",
      expectedVersion: 1,
      idempotencyKey: "task-status:b",
      request: { toState: "open" },
      hooks: {
        barriers: {
          onMutationStart: ({ attemptId }) => barriers.push(`start:${attemptId.slice(0, 8)}`),
          onMutationEnd: ({ phase }) => barriers.push(`end:${phase}`),
        },
      },
      dispatch: async () => ({ version: 2 }),
    });

    expect(barriers[0]).toMatch(/^start:/);
    expect(barriers[1]).toBe("end:confirmed");
  });
});
