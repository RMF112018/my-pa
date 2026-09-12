import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, screen } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";

import {
  TASK_COMMENT_ADDED_MESSAGE,
  TASK_DUE_CLEARED_MESSAGE,
  TASK_OPERATION_AMBIGUOUS_MESSAGE,
  TASK_OPERATION_CONFLICT_MESSAGE,
  TASK_OPERATION_FAILURE_MESSAGE,
  useTaskOperations,
  type TaskOperationsOptions,
  type TaskOperationsSeed,
} from "@/components/tasks/use-task-operations";
import {
  TaskRuntimeProvider,
  useTaskRuntime,
} from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import { civilDayEndIso, formatTaskDue, type TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_ID = "tsk_aaaaaaaa11111111";
const CLOCK: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-12" };

const TASK_V2: TaskDetail = {
  task_id: TASK_ID,
  title: "Coordinate review",
  description: null,
  lifecycle_state: "open",
  evidence_state: "accepted",
  origin_kind: "evidence",
  origin_evidence_ref: "cap_origin0001origin0001",
  closure_evidence_ref: null,
  accepted_by_review_decision_id: "rdec_aaaaaaaa11111111",
  acceptance_kind: "review",
  closure_history_id: null,
  version: 2,
  priority: null,
  due_at: null,
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  commitment_id: null,
  role: null,
  project_id: null,
  situation_id: null,
  opened_at: "2026-08-20T12:00:00Z",
  closed_at: null,
  created_at: "2026-08-20T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
};

/** A Work list projection: display only, and deliberately carrying no version. */
const LIST_ROW: TaskRow = {
  task_id: TASK_ID,
  title: "Coordinate review",
  lifecycle_state: "open",
  priority: null,
  due_at: null,
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-08-20T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
};

interface RecordedCall {
  readonly method: string;
  readonly path: string;
  readonly body: Record<string, unknown> | undefined;
}

function ok(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function fail(status: number, extra?: { current?: unknown }): Response {
  return new Response(
    JSON.stringify({ error: { message: "refused", errorClass: "invalid" }, current: extra?.current }),
    { status, headers: { "content-type": "application/json" } },
  );
}

function gate(): { wait: Promise<void>; release: () => void } {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { wait, release };
}

function stubFetch(handlers: {
  detail?: () => Response | Promise<Response>;
  transition?: (body: Record<string, unknown>, index: number) => Response | Promise<Response>;
  patch?: (body: Record<string, unknown>, index: number) => Response | Promise<Response>;
  comments?: (body: Record<string, unknown>, index: number) => Response | Promise<Response>;
}): { calls: RecordedCall[] } {
  const calls: RecordedCall[] = [];
  const counts = { transition: 0, patch: 0, comments: 0 };
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ method, path, body });
    const base = `/api/tasks/${TASK_ID}`;
    if (path === base && method === "GET") {
      return handlers.detail ? handlers.detail() : ok({ task: TASK_V2 });
    }
    if (path === base && method === "PATCH") {
      const index = counts.patch++;
      return handlers.patch
        ? handlers.patch(body ?? {}, index)
        : ok({ task: { ...TASK_V2, version: 3, due_at: (body?.dueAt as string) ?? null } });
    }
    if (path === `${base}/transition` && method === "POST") {
      const index = counts.transition++;
      return handlers.transition
        ? handlers.transition(body ?? {}, index)
        : ok({ task: { ...TASK_V2, version: 3, lifecycle_state: body?.toState } });
    }
    if (path === `${base}/comments` && method === "POST") {
      const index = counts.comments++;
      return handlers.comments ? handlers.comments(body ?? {}, index) : ok({ comment: { comment_id: "c1" } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { calls };
}

function posts(calls: readonly RecordedCall[], suffix: string): RecordedCall[] {
  return calls.filter((call) => call.path.endsWith(suffix) && call.method !== "GET");
}

function renderOperations(
  seed: TaskOperationsSeed,
  options: TaskOperationsOptions = { clock: CLOCK },
) {
  const revalidate = vi.fn();

  function Registrar({ children }: { readonly children: ReactNode }) {
    const runtime = useTaskRuntime();
    useEffect(
      () => runtime.reconciliation.registerActiveTaskQuery("work:today", revalidate),
      [runtime],
    );
    return <>{children}</>;
  }

  const utils = renderHook(
    ({ seed: current }: { seed: TaskOperationsSeed }) => useTaskOperations(current, options),
    {
      initialProps: { seed },
      wrapper: ({ children }: { readonly children: ReactNode }) => (
        <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
          <Registrar>{children}</Registrar>
        </TaskRuntimeProvider>
      ),
    },
  );
  /** Re-render with a different seed, as a surface holding a newer canonical would. */
  const reseed = (next: TaskOperationsSeed) => utils.rerender({ seed: next });
  return { ...utils, revalidate, reseed };
}

/** Region text without the dismiss affordance, so copy can be asserted exactly. */
function feedbackText(): string {
  const text = screen.queryByTestId("mutation-feedback-region")?.textContent ?? "";
  return text.replace(/Dismiss$/, "");
}

/** Let the hook's pre-dispatch microtasks (canonical hold) run without resolving fetch. */
async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("useTaskOperations", () => {
  it("refuses to let a Work list projection authorize a versioned mutation until hydrated", async () => {
    const detailGate = gate();
    const { calls } = stubFetch({
      detail: async () => {
        await detailGate.wait;
        return ok({ task: TASK_V2 });
      },
    });
    const { result } = renderOperations({ taskId: TASK_ID, task: LIST_ROW });

    // A projection without a version is never write authority.
    expect(result.current.canMutate).toBe(false);

    let inFlight!: Promise<void>;
    act(() => {
      inFlight = result.current.changeStatus("waiting");
    });
    await flush();

    // Canonical hydration is still open, so nothing has been written.
    expect(posts(calls, "/transition")).toHaveLength(0);

    await act(async () => {
      detailGate.release();
      await inFlight;
    });

    expect(result.current.canMutate).toBe(true);
    expect(posts(calls, "/transition")).toHaveLength(1);
  });

  it("does not let a versioned list projection skip canonical hydration", async () => {
    /*
      The dangerous case. A Work-list row may carry a `version`, but it is a read
      of some earlier moment, not a claim about the Task now — between the list
      read and the click, someone else may have moved it. Trusting that number
      would send a stale expectedVersion and turn a silent overwrite into a
      coin flip. Only a caller holding the canonical snapshot may vouch for it.
    */
    const reads: string[] = [];
    const writes: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input, init) => {
        const path = String(input);
        const method = (init?.method ?? "GET").toUpperCase();
        if (path === `/api/tasks/${TASK_ID}` && method === "GET") {
          reads.push(path);
          return ok({ task: { ...TASK_V2, version: 9 } });
        }
        if (path.includes("/transition") && method === "POST") {
          writes.push(JSON.parse(String(init?.body)).expectedVersion);
          return ok({ task: { ...TASK_V2, version: 10, lifecycle_state: "waiting" } });
        }
        throw new Error(`unexpected ${method} ${path}`);
      }),
    );

    // A projection that *does* carry a version, and is not declared canonical.
    const { result } = renderOperations({
      taskId: TASK_ID,
      task: { ...LIST_ROW, version: 3 },
    });

    expect(result.current.canMutate).toBe(false);
    await act(async () => {
      await result.current.changeStatus("waiting");
    });

    expect(reads.length).toBeGreaterThan(0);
    // The canonical read's version was sent, never the projection's stale 3.
    expect(writes).toEqual([9]);
  });

  it("sends the expected version the canonical hydrate supplied", async () => {
    const { calls } = stubFetch({ detail: () => ok({ task: { ...TASK_V2, version: 7 } }) });
    const { result } = renderOperations({ taskId: TASK_ID, task: LIST_ROW });

    await act(async () => {
      await result.current.changeStatus("waiting");
    });

    const [write] = posts(calls, "/transition");
    expect(write.body).toMatchObject({ toState: "waiting", expectedVersion: 7 });
    expect(typeof write.body?.idempotencyKey).toBe("string");
  });

  it("projects Status optimistically before the response resolves", async () => {
    const transitionGate = gate();
    stubFetch({
      transition: async (body) => {
        await transitionGate.wait;
        return ok({ task: { ...TASK_V2, version: 3, lifecycle_state: body.toState } });
      },
    });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    let inFlight!: Promise<void>;
    act(() => {
      inFlight = result.current.changeStatus("waiting");
    });
    await flush();

    expect(result.current.status).toEqual({ value: "waiting", optimistic: true });
    expect(result.current.pending).toBe("status");

    await act(async () => {
      transitionGate.release();
      await inFlight;
    });

    // The server Task, not the optimistic projection, is the confirmed authority.
    expect(result.current.status).toEqual({ value: "waiting", optimistic: false });
    expect(result.current.task?.version).toBe(3);
    expect(result.current.pending).toBeNull();
    expect(feedbackText()).toContain("Status changed to Waiting");
  });

  it("rolls Status back to the last confirmed value on definitive failure", async () => {
    stubFetch({ transition: () => fail(400) });
    const { result, revalidate } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    await act(async () => {
      await result.current.changeStatus("blocked");
    });

    expect(result.current.status).toEqual({ value: "open", optimistic: false });
    expect(feedbackText()).toContain(TASK_OPERATION_FAILURE_MESSAGE);
    // A definitive failure changed nothing, so no query is asked to revalidate.
    expect(revalidate).not.toHaveBeenCalled();
  });

  it("surfaces a conflict without any blind retry, and reapplies deliberately", async () => {
    const server = { ...TASK_V2, version: 3, title: "Coordinate review (server)" };
    const { calls } = stubFetch({
      transition: (body, index) =>
        index === 0 ? fail(409, { current: { task: server } }) : ok({ task: { ...server, version: 4, lifecycle_state: body.toState } }),
    });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    await act(async () => {
      await result.current.changeStatus("waiting");
    });

    expect(posts(calls, "/transition")).toHaveLength(1);
    expect(result.current.conflict?.current.version).toBe(3);
    expect(result.current.status).toEqual({ value: "open", optimistic: false });
    expect(feedbackText()).toContain(TASK_OPERATION_CONFLICT_MESSAGE);

    // Intent was preserved: reapply is a NEW attempt against the NEW version.
    await act(async () => {
      await result.current.reapply();
    });

    const writes = posts(calls, "/transition");
    expect(writes).toHaveLength(2);
    expect(writes[1].body).toMatchObject({ toState: "waiting", expectedVersion: 3 });
    expect(writes[1].body?.idempotencyKey).not.toBe(writes[0].body?.idempotencyKey);
    expect(result.current.conflict).toBeNull();
  });

  it("reuses the same idempotency key when retrying an ambiguous attempt", async () => {
    const { calls } = stubFetch({
      transition: (body, index) =>
        index === 0 ? fail(503) : ok({ task: { ...TASK_V2, version: 3, lifecycle_state: body.toState } }),
    });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    await act(async () => {
      await result.current.changeStatus("waiting");
    });

    expect(feedbackText()).toContain(TASK_OPERATION_AMBIGUOUS_MESSAGE);
    expect(posts(calls, "/transition")).toHaveLength(1);

    await act(async () => {
      await result.current.reapply();
    });

    const writes = posts(calls, "/transition");
    expect(writes).toHaveLength(2);
    // Same logical attempt identity: a retry can never be persisted twice.
    expect(writes[1].body?.idempotencyKey).toBe(writes[0].body?.idempotencyKey);
    expect(result.current.status.value).toBe("waiting");
  });

  it("projects Due optimistically and serializes a civil date to civil day end", async () => {
    const patchGate = gate();
    const expected = civilDayEndIso("2026-09-15", "UTC");
    const { calls } = stubFetch({
      patch: async (body) => {
        await patchGate.wait;
        return ok({ task: { ...TASK_V2, version: 3, due_at: body.dueAt as string } });
      },
    });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    let inFlight!: Promise<void>;
    act(() => {
      inFlight = result.current.changeDue("2026-09-15");
    });
    await flush();

    expect(result.current.due).toEqual({ value: expected, optimistic: true });

    await act(async () => {
      patchGate.release();
      await inFlight;
    });

    const [write] = posts(calls, `/api/tasks/${TASK_ID}`);
    expect(write.body).toMatchObject({ dueAt: expected, expectedVersion: 2 });
    expect(result.current.due).toEqual({ value: expected, optimistic: false });
    expect(feedbackText()).toContain(
      `Due date moved to ${formatTaskDue(expected, CLOCK).phrase}`,
    );
  });

  it("clears Due through the landed clear-field contract", async () => {
    const dated = { ...TASK_V2, due_at: "2026-09-13T23:59:59.000Z" };
    const { calls } = stubFetch({ patch: () => ok({ task: { ...dated, version: 3, due_at: null } }) });
    const { result } = renderOperations({ taskId: TASK_ID, task: dated });

    await act(async () => {
      await result.current.changeDue(null);
    });

    const [write] = posts(calls, `/api/tasks/${TASK_ID}`);
    expect(write.body).toMatchObject({ clearFields: ["due_at"], expectedVersion: 2 });
    expect(write.body?.dueAt).toBeUndefined();
    expect(result.current.due).toEqual({ value: null, optimistic: false });
    expect(feedbackText()).toContain(TASK_DUE_CLEARED_MESSAGE);
  });

  it("shows no terminal state for Close until the server Task confirms it", async () => {
    const closeGate = gate();
    stubFetch({
      transition: async (body) => {
        await closeGate.wait;
        return ok({ task: { ...TASK_V2, version: 3, lifecycle_state: body.toState, closed_at: "2026-09-12T10:00:00Z" } });
      },
    });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    let inFlight!: Promise<void>;
    act(() => {
      inFlight = result.current.closeTask();
    });
    await flush();

    // Pessimistic: nothing terminal is projected ahead of the server.
    expect(result.current.status).toEqual({ value: "open", optimistic: false });
    expect(result.current.pending).toBe("close");

    await act(async () => {
      closeGate.release();
      await inFlight;
    });

    expect(result.current.status.value).toBe("completed");
    expect(feedbackText()).toContain(`${TASK_V2.title} closed`);
  });

  it("shows no terminal state for Cancel until the server Task confirms it", async () => {
    const cancelGate = gate();
    stubFetch({
      transition: async (body) => {
        await cancelGate.wait;
        return ok({ task: { ...TASK_V2, version: 3, lifecycle_state: body.toState } });
      },
    });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    let inFlight!: Promise<void>;
    act(() => {
      inFlight = result.current.cancelTask();
    });
    await flush();

    expect(result.current.status).toEqual({ value: "open", optimistic: false });

    await act(async () => {
      cancelGate.release();
      await inFlight;
    });

    expect(result.current.status.value).toBe("cancelled");
    expect(feedbackText()).toContain(`${TASK_V2.title} cancelled`);
  });

  it("appends a comment without an expected version and never bumps the Task version", async () => {
    const { calls } = stubFetch({});
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    await act(async () => {
      await result.current.addComment("Checked with the counterparty");
    });

    const [write] = posts(calls, "/comments");
    expect(write.body).toMatchObject({ body: "Checked with the counterparty" });
    expect(write.body?.expectedVersion).toBeUndefined();
    expect(result.current.pendingComments).toHaveLength(0);
    expect(result.current.task?.version ?? 2).toBe(2);
    expect(feedbackText()).toContain(TASK_COMMENT_ADDED_MESSAGE);
  });

  it("preserves the body of a failed comment", async () => {
    stubFetch({ comments: () => fail(400) });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    await act(async () => {
      await result.current.addComment("Draft that must survive");
    });

    expect(result.current.pendingComments).toEqual([
      expect.objectContaining({ body: "Draft that must survive", state: "failed" }),
    ]);
    expect(feedbackText()).toContain(TASK_OPERATION_FAILURE_MESSAGE);
  });

  it("adopts a newer authoritative version from its surface without being rebuilt", async () => {
    /*
      Task detail writes through two paths: this binder, and its own bounded
      field saves. When a title save advances the canonical version, the binder
      must take that version as its own write authority. The alternative — the
      surface remounting the binder to re-seed it — would also discard whatever
      the binder was holding, including a comment left awaiting retry.
    */
    const expectedVersions: unknown[] = [];
    stubFetch({
      transition: (body) => {
        expectedVersions.push(body.expectedVersion);
        return ok({ task: { ...TASK_V2, version: 99, lifecycle_state: "waiting" } });
      },
    });
    const { result, reseed } = renderOperations({
      taskId: TASK_ID,
      task: TASK_V2,
      authoritative: true,
    });

    // The surface saved a field elsewhere and now holds a newer canonical Task.
    act(() => {
      reseed({
        taskId: TASK_ID,
        task: { ...TASK_V2, version: TASK_V2.version + 1 },
        authoritative: true,
      });
    });

    await act(async () => {
      await result.current.changeStatus("waiting");
    });

    expect(expectedVersions).toEqual([TASK_V2.version + 1]);
  });

  it("reconciles registered active queries exactly once per confirmed mutation", async () => {
    stubFetch({});
    const { result, revalidate } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    await act(async () => {
      await result.current.changeStatus("waiting");
    });

    expect(revalidate).toHaveBeenCalledTimes(1);
  });

  it("never exposes transport detail, versions or evidence in feedback copy", async () => {
    stubFetch({ transition: () => fail(409, { current: { task: { ...TASK_V2, version: 3 } } }) });
    const { result } = renderOperations({ taskId: TASK_ID, task: TASK_V2 });

    await act(async () => {
      await result.current.changeStatus("waiting");
    });

    const text = feedbackText();
    expect(text).toBe(TASK_OPERATION_CONFLICT_MESSAGE);
    expect(text).not.toMatch(/409|version|prin_|rdec_|cap_/i);
  });
});
