import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  TaskDetailView,
  TaskDetailViewConnected,
} from "@/components/work/work-detail";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import {
  TASK_OPERATION_CONFLICT_MESSAGE,
  taskClosedMessage,
} from "@/components/tasks/use-task-operations";
import TaskPage from "@/app/(app)/work/tasks/[taskId]/page";

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

/**
 * Raw version/identity diagnostics belong behind Technical details and nowhere
 * else, so the canonical version is proven there rather than in primary copy.
 */
async function expectCanonicalVersionBehindTechnicalDetails(
  user: ReturnType<typeof userEvent.setup>,
  version: string,
) {
  await user.click(screen.getByText("Technical details"));
  const identity = await screen.findByRole("region", { name: "Identity" });
  expect(within(identity).getByText(version)).toBeTruthy();
}

/**
 * Primary conflict UX states what happened in product language. It never
 * renders a raw version number or any other identity diagnostic: those belong
 * behind Technical details. ("the latest version" as ordinary English is fine;
 * a digit anywhere in this region is not.)
 */
function expectNoVersionNumber(element: HTMLElement) {
  const text = element.textContent ?? "";
  expect(text).not.toMatch(/version\s*\d/i);
  expect(text).not.toMatch(/\d/);
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
    // The newer canonical is exposed by identity, not by version jargon.
    expect(screen.getByText(/title “Coordinate review \(server\)”/)).toBeTruthy();
    expectNoVersionNumber(screen.getByTestId("task-changed-elsewhere"));
    expect(patchCount).toBe(1);
    await expectCanonicalVersionBehindTechnicalDetails(user, "3");

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
    expect(screen.getByRole("button", { name: "Save title" })).toBeDisabled();
    await expectCanonicalVersionBehindTechnicalDetails(user, "3");
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
    expect(screen.queryByDisplayValue("Coordinate review (server)")).toBeNull();
    await expectCanonicalVersionBehindTechnicalDetails(user, "3");
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
    const statusControl = screen.getByTestId("task-status-control");
    expect(statusControl.getAttribute("aria-busy")).toBe("true");
    // The actionable element itself is locked, not merely its container.
    expect(within(statusControl).getByRole("combobox")).toBeDisabled();

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

  it("shows a Status change optimistically before the server confirms it", async () => {
    const user = userEvent.setup();
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    let transitions = 0;
    const fetcher = stubDetailFetch({
      transition: (body) => {
        transitions += 1;
        expect((body as { expectedVersion: number }).expectedVersion).toBe(2);
        return gate;
      },
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    await screen.findByDisplayValue("Coordinate review");
    const statusSelect = within(screen.getByTestId("task-status-control")).getByRole("combobox");
    await user.selectOptions(statusSelect, "in_progress");

    // Still in flight: the new Status is already shown, on the user's authority.
    expect(transitions).toBe(1);
    expect((statusSelect as HTMLSelectElement).value).toBe("in_progress");
    expect(screen.getByTestId("task-status-control").getAttribute("aria-busy")).toBe("true");

    release(json({ task: { ...TASK_V2, lifecycle_state: "in_progress", version: 3 } }));
    await waitFor(() =>
      expect(
        within(screen.getByTestId("task-status-control"))
          .getByRole("combobox")
          .getAttribute("disabled"),
      ).toBeNull(),
    );
    expect(
      (within(screen.getByTestId("task-status-control")).getByRole("combobox") as HTMLSelectElement)
        .value,
    ).toBe("in_progress");
  });

  it("keeps Close pessimistic: no terminal state until the server confirms", async () => {
    const user = userEvent.setup();
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetcher = stubDetailFetch({
      transition: (body) => {
        expect((body as { toState: string }).toState).toBe("completed");
        return gate;
      },
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    await screen.findByDisplayValue("Coordinate review");
    await user.click(screen.getByTestId("task-close-trigger"));
    await user.click(screen.getByTestId("task-close-confirm"));

    // Unconfirmed: the Task is not shown as closed, and Status is not terminal.
    expect(screen.queryByTestId("task-terminal-summary")).toBeNull();
    expect(screen.getByTestId("task-status-control").getAttribute("data-terminal")).toBeNull();
    expect(screen.queryByText("This task is closed.")).toBeNull();

    release(json({ task: { ...TASK_V2, lifecycle_state: "completed", closed_at: "2026-08-24T12:00:00Z", version: 3 } }));
    expect(await screen.findByTestId("task-terminal-summary")).toBeTruthy();
    // Product copy for the confirmed closure comes from the shared binder.
    expect(await screen.findByText(taskClosedMessage(TASK_V2.title))).toBeTruthy();
  });

  it("states an operation conflict in product language with no version number", async () => {
    const user = userEvent.setup();
    const fetcher = stubDetailFetch({
      transition: () => json(null, 409, { current: TASK_V3 }),
    });
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    await screen.findByDisplayValue("Coordinate review");
    const statusSelect = within(screen.getByTestId("task-status-control")).getByRole("combobox");
    await user.selectOptions(statusSelect, "waiting");

    const alert = await screen.findByTestId("task-operation-conflict");
    expect(alert.textContent).toContain(TASK_OPERATION_CONFLICT_MESSAGE);
    expectNoVersionNumber(alert);
    // The optimistic Status was rolled back rather than left asserted.
    expect(
      (within(screen.getByTestId("task-status-control")).getByRole("combobox") as HTMLSelectElement)
        .value,
    ).toBe("open");
    // The raw version the server exposed stays a diagnostic.
    await expectCanonicalVersionBehindTechnicalDetails(user, "3");
  });

  it("binds comments through the shared binder in Activity", async () => {
    const fetcher = stubDetailFetch({});
    vi.stubGlobal("fetch", fetcher);

    render(<TaskDetailView taskId={TASK_V2.task_id} />);
    await screen.findByDisplayValue("Coordinate review");
    // Comments live in Description & Activity, never as a lifecycle form.
    const activity = screen.getByTestId("task-comments");
    expect(within(activity).getByLabelText("Add comment")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Apply transition/i })).toBeNull();
    expect(screen.queryByLabelText(/closure note/i)).toBeNull();
  });
});

describe("standalone Task route", () => {
  it("consumes the AppShell Task runtime rather than a route-local coordinator", async () => {
    const user = userEvent.setup();
    const fetcher = stubDetailFetch({});
    vi.stubGlobal("fetch", fetcher);

    const page = await TaskPage({ params: Promise.resolve({ taskId: TASK_V2.task_id }) });

    // Outside the shell runtime the route cannot mount at all: it owns no
    // coordinator of its own.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(page)).toThrow(/TaskRuntimeProvider/);
    consoleError.mockRestore();
    cleanup();

    render(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        {page}
      </TaskRuntimeProvider>,
    );
    await screen.findByDisplayValue("Coordinate review");

    // Shell-persistent feedback survives on this route: the binder's own copy
    // is published into the shell feedback region.
    const statusSelect = within(screen.getByTestId("task-status-control")).getByRole("combobox");
    await user.selectOptions(statusSelect, "in_progress");
    await waitFor(() => expect(screen.getByTestId("mutation-feedback-region")).toBeTruthy());
    expect(screen.getByText("Status changed to In progress")).toBeTruthy();
  });
});

