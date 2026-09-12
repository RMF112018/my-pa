import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  TaskDetailView,
  TaskDetailViewConnected,
} from "@/components/work/work-detail";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_V2 = {
  task_id: "tsk_aaaaaaaa11111111",
  title: "Coordinate review",
  description: null,
  lifecycle_state: "open",
  evidence_state: "accepted",
  origin_kind: "evidence" as const,
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

const TASK_V3 = {
  ...TASK_V2,
  title: "Coordinate review (server)",
  version: 3,
  updated_at: "2026-08-23T12:00:00Z",
};

function json(data: unknown, status = 200, extra?: { current?: unknown }) {
  const body =
    status >= 400
      ? {
          error: { message: status === 409 ? "version conflict" : "failed", code: "conflict" },
          current: extra?.current,
        }
      : data;
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stubDetailFetch(handlers: {
  task?: () => unknown;
  patch?: (body: unknown) => Response | Promise<Response>;
  transition?: (body: unknown) => Response | Promise<Response>;
}) {
  const taskFactory = handlers.task ?? (() => ({ task: TASK_V2 }));
  return vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/history")) return json({ history: [] });
    if (path.includes("/comments")) return json({ comments: [] });
    if (path === "/api/commitments?pageSize=100") return json({ commitments: [] });
    if (path === `/api/tasks/${TASK_V2.task_id}` && method === "GET") {
      return json(taskFactory());
    }
    if (path === `/api/tasks/${TASK_V2.task_id}` && method === "PATCH") {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (handlers.patch) return handlers.patch(body);
      return json({ task: { ...TASK_V2, version: TASK_V2.version + 1, title: body.title } });
    }
    if (path === `/api/tasks/${TASK_V2.task_id}/transition` && method === "POST") {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (handlers.transition) return handlers.transition(body);
      return json({ task: { ...TASK_V2, lifecycle_state: body.toState, version: TASK_V2.version + 1 } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
}

describe("TaskDetailView authoritative draft / conflict", () => {
  it("preserves draft on 409 with current and does not auto-resubmit", async () => {
    const user = userEvent.setup();
    let patchCount = 0;
    const fetcher = stubDetailFetch({
      patch: (body) => {
        patchCount += 1;
        expect((body as { expectedVersion: number }).expectedVersion).toBe(2);
        return json(null, 409, { current: TASK_V3 });
      },
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    const title = await screen.findByDisplayValue("Coordinate review");
    await user.clear(title);
    await user.type(title, "My dirty title");
    await user.click(screen.getByRole("button", { name: "Save title" }));

    expect(await screen.findByTestId("task-changed-elsewhere")).toBeTruthy();
    expect(screen.getAllByText(/This task changed elsewhere/).length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue("My dirty title")).toBeTruthy();
    expect(screen.getByText(/Canonical version 3/)).toBeTruthy();
    expect(screen.getByText(/title “Coordinate review \(server\)”/)).toBeTruthy();
    expect(patchCount).toBe(1);

    // Blind save stays locked — no second request without deliberate reapply.
    expect(screen.getByRole("button", { name: "Save title" })).toBeDisabled();
    expect(patchCount).toBe(1);
  });

  it("preserves draft on 409 without current after follow-up read", async () => {
    const user = userEvent.setup();
    let getCount = 0;
    const fetcher = stubDetailFetch({
      task: () => {
        getCount += 1;
        // First loads are v2; post-conflict fetchCurrent returns v3.
        return { task: getCount <= 1 ? TASK_V2 : TASK_V3 };
      },
      patch: () => json(null, 409),
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    const title = await screen.findByDisplayValue("Coordinate review");
    await user.clear(title);
    await user.type(title, "Kept draft title");
    await user.click(screen.getByRole("button", { name: "Save title" }));

    expect(await screen.findByTestId("task-changed-elsewhere")).toBeTruthy();
    expect(screen.getByDisplayValue("Kept draft title")).toBeTruthy();
    expect(screen.getByText(/Canonical version 3/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save title" })).toBeDisabled();
  });

  it("keeps a dirty title when a newer canonical arrives via refresh", async () => {
    const user = userEvent.setup();
    let version = 2;
    const fetcher = stubDetailFetch({
      task: () => ({ task: version === 2 ? TASK_V2 : TASK_V3 }),
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    const title = await screen.findByDisplayValue("Coordinate review");
    await user.clear(title);
    await user.type(title, "Local unsaved title");

    version = 3;
    await user.click(screen.getByTestId("task-detail-refresh"));

    expect(await screen.findByTestId("task-changed-elsewhere")).toBeTruthy();
    expect(screen.getByDisplayValue("Local unsaved title")).toBeTruthy();
    expect(screen.getByText(/Canonical version 3/)).toBeTruthy();
    expect(screen.queryByDisplayValue("Coordinate review (server)")).toBeNull();
  });

  it("does not silently reset the draft and requires deliberate reapply after conflict", async () => {
    const user = userEvent.setup();
    const keys: string[] = [];
    let patchCount = 0;
    const fetcher = stubDetailFetch({
      patch: (body) => {
        patchCount += 1;
        keys.push(String((body as { idempotencyKey: string }).idempotencyKey));
        if (patchCount === 1) return json(null, 409, { current: TASK_V3 });
        expect((body as { expectedVersion: number }).expectedVersion).toBe(3);
        return json({ task: { ...TASK_V3, title: (body as { title: string }).title, version: 4 } });
      },
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    const title = await screen.findByDisplayValue("Coordinate review");
    await user.clear(title);
    await user.type(title, "Proposed title");
    await user.click(screen.getByRole("button", { name: "Save title" }));

    expect(await screen.findByDisplayValue("Proposed title")).toBeTruthy();
    const reapply = await screen.findByRole("button", { name: /Reapply my change to the latest version/ });
    await user.click(reapply);

    await waitFor(() => expect(patchCount).toBe(2));
    expect(keys[0]).not.toBe(keys[1]);
    expect(screen.queryByTestId("task-changed-elsewhere")).toBeNull();
    expect(screen.getByDisplayValue("Proposed title")).toBeTruthy();
  });

  it("marks mutation controls pending / aria-busy while a save is in flight", async () => {
    const user = userEvent.setup();
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetcher = stubDetailFetch({
      patch: () => gate,
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    const pendingTitle = await screen.findByDisplayValue("Coordinate review");
    await user.type(pendingTitle, " now");
    await user.click(screen.getByRole("button", { name: "Save title" }));

    const save = await screen.findByRole("button", { name: /Save title/ });
    expect(save.getAttribute("aria-busy")).toBe("true");
    expect(save).toBeDisabled();
    expect(screen.getByTestId("task-status-control").getAttribute("aria-busy")).toBe("true");

    release(json({ task: { ...TASK_V2, version: 3 } }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save title" }).getAttribute("aria-busy")).toBeNull());
  });

  it("routes mutations through the shared TaskRuntimeProvider coordinator when connected", async () => {
    const user = userEvent.setup();
    const fetcher = stubDetailFetch({});
    vi.stubGlobal("fetch", fetcher);

    render(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <TaskDetailViewConnected taskId={TASK_V2.task_id} />
      </TaskRuntimeProvider>,
    );

    const connectedTitle = await screen.findByDisplayValue("Coordinate review");
    await user.type(connectedTitle, " again");
    await user.click(screen.getByRole("button", { name: "Save title" }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([input, init]) =>
            String(input) === `/api/tasks/${TASK_V2.task_id}` && String(init?.method).toUpperCase() === "PATCH",
        ),
      ).toBe(true),
    );
  });
});
