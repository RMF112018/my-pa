import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { useTaskRowOperations } from "@/components/tasks/use-task-row-operations";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import type { TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CLOCK: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-12" };

function listRow(id: string): TaskRow {
  return {
    task_id: id,
    title: `Task ${id}`,
    lifecycle_state: "in_progress",
    priority: "p1",
    due_at: "2026-09-13T12:00:00Z",
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-08-20T12:00:00Z",
    updated_at: "2026-08-22T12:00:00Z",
    // Deliberately present and deliberately stale: a projection may carry a
    // version, and it is still never write authority.
    version: 3,
  };
}

function canonical(id: string): TaskDetail {
  return {
    ...listRow(id),
    description: null,
    evidence_state: "accepted",
    origin_kind: "evidence",
    origin_evidence_ref: "cap_origin0001origin0001",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: null,
    closure_history_id: null,
    version: 4,
    commitment_id: null,
    role: null,
    project_id: null,
    situation_id: null,
    opened_at: "2026-08-20T12:00:00Z",
    closed_at: null,
  };
}

function ok(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function stubFetch() {
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    const detail = /^\/api\/tasks\/(tsk_[0-9a-f]+)$/.exec(path);
    if (detail && method === "GET") return ok({ task: canonical(detail[1]) });
    const transition = /^\/api\/tasks\/(tsk_[0-9a-f]+)\/transition$/.exec(path);
    if (transition && method === "POST") {
      return ok({ task: { ...canonical(transition[1]), version: 5, lifecycle_state: body.toState } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function detailGets(fetcher: ReturnType<typeof stubFetch>): string[] {
  return fetcher.mock.calls
    .filter(([, init]) => (init?.method ?? "GET").toUpperCase() === "GET")
    .map(([input]) => String(input))
    .filter((path) => /^\/api\/tasks\/tsk_[0-9a-f]+$/.test(path));
}

interface ProbeProps {
  readonly task: TaskRow;
  readonly onMutationConfirmed?: (input: { taskId: string; kind: string }) => void;
}

/** The smallest possible consumer: a card that is not the List row. */
function Probe({ task, onMutationConfirmed }: ProbeProps): React.JSX.Element {
  const operations = useTaskRowOperations<HTMLDivElement>({
    taskId: task.task_id,
    task,
    clock: CLOCK,
    onMutationConfirmed,
  });
  const { rowRef, handleStatus } = operations;
  return (
    <div ref={rowRef} data-testid={`probe-${task.task_id}`}>
      <button type="button" onClick={() => handleStatus("blocked")}>
        {`Block ${task.title}`}
      </button>
    </div>
  );
}

function renderProbes(ids: readonly string[], onMutationConfirmed?: ProbeProps["onMutationConfirmed"]): void {
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      {ids.map((id) => (
        <Probe key={id} task={listRow(id)} onMutationConfirmed={onMutationConfirmed} />
      ))}
    </TaskRuntimeProvider>,
  );
}

describe("useTaskRowOperations", () => {
  /*
    The no-N+1 contract, guarded where it is now decided.

    The hydrate mode used to be spelled out inside the List row; it is now one
    shared line serving every card surface, so a single edit there would fan a
    collection out into one detail read per card. This is the test that stops it.
  */
  it("reads no Task detail when cards mount", async () => {
    const fetcher = stubFetch();
    renderProbes(["tsk_aaaaaaaa11111111", "tsk_bbbbbbbb22222222", "tsk_cccccccc33333333"]);

    expect(screen.getByTestId("probe-tsk_cccccccc33333333")).toBeTruthy();
    await waitFor(() => expect(detailGets(fetcher)).toEqual([]));
  });

  it("hydrates canonically at the first write, then reports the confirmation", async () => {
    const fetcher = stubFetch();
    const onMutationConfirmed = vi.fn<(input: { taskId: string; kind: string }) => void>();
    renderProbes(["tsk_aaaaaaaa11111111", "tsk_bbbbbbbb22222222"], onMutationConfirmed);

    await userEvent.click(screen.getByRole("button", { name: "Block Task tsk_aaaaaaaa11111111" }));

    await waitFor(() =>
      expect(onMutationConfirmed).toHaveBeenCalledWith({ taskId: "tsk_aaaaaaaa11111111", kind: "status" }),
    );
    // Only the card that was written to paid a detail read.
    expect(detailGets(fetcher)).toEqual(["/api/tasks/tsk_aaaaaaaa11111111"]);
    const sent = fetcher.mock.calls.find(
      ([input, init]) =>
        String(input) === "/api/tasks/tsk_aaaaaaaa11111111/transition" && init?.method === "POST",
    );
    const body = JSON.parse(String(sent?.[1]?.body)) as Record<string, unknown>;
    // The canonical version, never the projection's stale 3.
    expect(body.expectedVersion).toBe(4);
  });
});
