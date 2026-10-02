import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { GlobalLauncher, LauncherPrincipalProvider, type CaptureReceipt } from "./global-launcher";

const { navigation, scope } = vi.hoisted(() => ({
  navigation: { push: vi.fn() },
  scope: { epoch: 0, projectId: null as string | null },
}));
const delayed = vi.hoisted(() => ({ capture: null as null | (() => void), task: null as null | (() => void) }));

vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
vi.mock("@/components/shell/project-scope-provider", () => ({
  useProjectScope: () => ({
    epoch: scope.epoch,
    resolution: { scope: scope.projectId ? { kind: "PROJECT", projectId: scope.projectId } : { kind: "ALL" } },
  }),
}));

// These are the already-owned creator boundaries. Their real forms and transport
// are exercised in the browser spec; here a callback can be delayed or malformed.
vi.mock("@/components/shell/capture-dialog", () => ({
  CaptureDialog: ({ open, onClose, onCreateTask, onConfirmed, session }: {
    open: boolean;
    onClose: () => void;
    onCreateTask: (projectId: string | null) => void;
    onConfirmed: (receipt: CaptureReceipt) => void;
    session: { projectId: string | null };
  }) => {
    delayed.capture = () => onConfirmed(captureReceipt);
    return open ? <section role="dialog" aria-label="Capture">
    <button onClick={() => onCreateTask(session.projectId)}>Create Task</button>
    <button onClick={() => onConfirmed(captureReceipt)}>Confirm Capture</button>
    <button onClick={onClose}>Close Capture</button>
  </section> : null;
  },
}));
vi.mock("@/components/tasks/task-create-sheet", () => ({
  TaskCreateSheet: ({ open, onOpenChange, onBack, onConfirmed, context }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onBack: (context: { projectId: string | null }) => void;
    onConfirmed: (receipt: unknown) => void;
    context?: { projectId?: string };
  }) => {
    delayed.task = () => onConfirmed(taskReceipt);
    return open ? <section role="dialog" aria-label="Create task">
    <form data-testid="task-create-sheet"><label>Title<input aria-label="Title" /></label></form>
    <span data-testid="task-project">{context?.projectId ?? "No Project"}</span>
    <button onClick={() => onBack({ projectId: context?.projectId ?? null })}>Back to Capture</button>
    <button onClick={() => onConfirmed(taskReceipt)}>Confirm Task</button>
    <button onClick={() => onConfirmed({ ...taskReceipt, replayed: "yes" })}>Malformed Task</button>
    <button onClick={() => onOpenChange(false)}>Close Task</button>
  </section> : null;
  },
}));

const captureReceipt: CaptureReceipt = {
  shape: "backend", status: "persisted", captureKind: "quick_note", created: true,
  receipt: {
    receiptId: "receipt-1", captureId: "capture-1", versionId: "version-1",
    versionNumber: 1, idempotencyKey: "test-key", contentSha256: "test-digest",
    principalId: "principal-a", issuedAt: "2026-10-02T12:00:00.000Z", projectId: null,
  },
};
const at = "2026-08-09T12:00:00.000Z";
const taskReceipt = {
  task: {
    task_id: "tsk_aaaaaaaa11111111", title: "Synthetic task", description: null,
    lifecycle_state: "open", evidence_state: "accepted", origin_kind: "evidence",
    origin_evidence_ref: "cap_aaaaaaaa11111111", closure_evidence_ref: null,
    accepted_by_review_decision_id: null, acceptance_kind: "direct_principal",
    closure_history_id: null, version: 1, priority: null, due_at: null,
    scheduled_at: null, deferred_until: null, archived_at: null, project_id: null,
    situation_id: null, recurrence_id: null, opened_at: at, closed_at: null,
    created_at: at, updated_at: at, commitment_id: null, role: null,
  },
  history: {
    history_id: "thst_bbbbbbbb22222222", task_id: "tsk_aaaaaaaa11111111",
    action: "create", actor: "principal", outcome: "applied", before_version: 0,
    after_version: 1, occurred_at: at, recorded_at: at,
  }, replayed: false,
};

function Harness({ initialMode, onConfirmed = vi.fn(), sessionEpoch = "session-a", projectId }: {
  initialMode?: "capture" | "task";
  onConfirmed?: (receipt: unknown) => void;
  sessionEpoch?: string;
  projectId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [showInvoker, setShowInvoker] = useState(true);
  return <LauncherPrincipalProvider principalId="principal-a" sessionEpoch={sessionEpoch}>
    <main><h1>Today</h1>{showInvoker ? <button onClick={() => setOpen(true)}>New</button> : null}
      <button onClick={() => setShowInvoker(false)}>Remove New</button></main>
    <GlobalLauncher open={open} onOpenChange={setOpen} initialMode={initialMode}
      projectId={projectId} onConfirmed={onConfirmed} />
  </LauncherPrincipalProvider>;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  scope.epoch = 0;
  scope.projectId = null;
  navigation.push.mockClear();
  delayed.capture = null;
  delayed.task = null;
});

describe("GlobalLauncher public contract", () => {
  it("forwards an existing Capture ack and only a decodable Task receipt, then offers Open Task", async () => {
    const confirmed = vi.fn();
    render(<Harness onConfirmed={confirmed} />);
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Confirm Capture" }));
    expect(confirmed).toHaveBeenCalledWith(captureReceipt);
    fireEvent.click(screen.getByRole("button", { name: "Create Task" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Malformed Task" }));
    expect(confirmed).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Confirm Task" }));
    expect(confirmed).toHaveBeenCalledTimes(2);
    expect(confirmed.mock.calls[1]?.[0]).toMatchObject({ task: { task_id: "tsk_aaaaaaaa11111111" } });
    expect(screen.getByRole("dialog", { name: "Task created" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Task" }));
    expect(navigation.push).toHaveBeenCalledWith("/work/tasks/tsk_aaaaaaaa11111111");
  });

  it("starts directly in Task with one visible modal and returns to Capture", async () => {
    scope.projectId = "prj_aaaaaaaa11111111";
    render(<Harness initialMode="task" />);
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "Create task" })).toBeInTheDocument();
    expect(screen.getByTestId("task-project")).toHaveTextContent(scope.projectId);
    fireEvent.click(screen.getByRole("button", { name: "Back to Capture" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "Capture" })).toBeInTheDocument();
  });

  it("guards an unsent Task draft from Escape dismissal and restores its invoker", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<Harness initialMode="task" />);
    const newButton = screen.getByRole("button", { name: "New" });
    newButton.focus(); fireEvent.click(newButton);
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Unsent" } });
    fireEvent.click(screen.getByRole("button", { name: "Close Task" }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog", { name: "Create task" })).toBeInTheDocument();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Close Task" }));
    await waitFor(() => expect(newButton).toHaveFocus());
  });

  it("keeps offline Task unavailable while offering Capture", async () => {
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    render(<Harness initialMode="task" />);
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.getByRole("dialog", { name: "Create Task" })).toHaveTextContent("requires a connection");
    expect(screen.queryByTestId("task-create-sheet")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Quick Capture" }));
    expect(screen.getByRole("dialog", { name: "Capture" })).toBeInTheDocument();
  });

  it("keeps Capture open when the offline Task dialog emits its controlled close event", async () => {
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    render(<Harness initialMode="task" />);
    const invoker = screen.getByRole("button", { name: "New" });
    invoker.focus();
    fireEvent.click(invoker);
    const offlineTask = screen.getByRole("dialog", { name: "Create Task" });
    fireEvent.click(screen.getByRole("button", { name: "Quick Capture" }));
    // Browsers emit this native event after the controlled dialog closes.
    // jsdom's fallback removes `open` without emitting it.
    fireEvent(offlineTask, new Event("close"));
    expect(screen.getByRole("dialog", { name: "Capture" })).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Close Capture" }));
    await waitFor(() => expect(invoker).toHaveFocus());
  });

  it("still dismisses the active offline Task dialog and restores its invoker", async () => {
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    render(<Harness initialMode="task" />);
    const invoker = screen.getByRole("button", { name: "New" });
    invoker.focus();
    fireEvent.click(invoker);
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(invoker).toHaveFocus());
  });

  it("ignores delayed creator callbacks after the verified session changes", () => {
    const confirmed = vi.fn();
    const view = render(<Harness onConfirmed={confirmed} />);
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    const oldCapture = delayed.capture;
    fireEvent.click(screen.getByRole("button", { name: "Create Task" }));
    const oldTask = delayed.task;
    view.rerender(<Harness onConfirmed={confirmed} sessionEpoch="session-b" />);
    oldCapture?.();
    oldTask?.();
    expect(confirmed).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Task created" })).toBeNull();
  });

  it("returns focus to a surviving main heading when the invoking action disappears", async () => {
    render(<Harness />);
    const invoker = screen.getByRole("button", { name: "New" });
    invoker.focus(); fireEvent.click(invoker);
    fireEvent.click(screen.getByRole("button", { name: "Remove New" }));
    fireEvent.click(screen.getByRole("button", { name: "Close Capture" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Today" })).toHaveFocus());
  });
});
