import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { GlobalLauncher, LauncherPrincipalProvider } from "./global-launcher";

const { navigation, scope, delayed } = vi.hoisted(() => ({
  navigation: { push: vi.fn() },
  scope: { epoch: 0, projectId: null as string | null },
  delayed: { task: null as null | (() => void) },
}));

vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
vi.mock("@/components/shell/project-scope-provider", () => ({
  useProjectScope: () => ({
    epoch: scope.epoch,
    resolution: { scope: scope.projectId ? { kind: "PROJECT", projectId: scope.projectId } : { kind: "ALL" } },
  }),
}));
vi.mock("@/components/shell/command-palette", () => ({
  SearchCommandPanel: ({ initialQuery = "", autoFocus = false, onNavigate }: {
    initialQuery?: string; autoFocus?: boolean; onNavigate?: (href: string) => void;
  }) =>
    <section data-testid="canonical-search-panel">
      <input role="searchbox" aria-label="Search" defaultValue={initialQuery} autoFocus={autoFocus} />
      <div data-testid="search-command-list">Start typing to search.</div>
      <button onClick={() => onNavigate?.("/review")}>Open read result</button>
    </section>,
}));
vi.mock("@/components/shell/capture-dialog", () => ({
  CaptureDialog: ({ open, onClose, onBack, embedded, dispatch, session }: {
    open: boolean;
    onClose: () => void;
    onBack?: () => void;
    embedded?: boolean;
    dispatch: (event: { type: "select_project"; projectId: string } | { type: "edit_draft"; form: "quick_note" | "conversation_log"; text: string }) => void;
    session: { projectId: string | null; form: "quick_note" | "conversation_log"; noteDraft: string; conversationDraft: string };
  }) => open ?
    <section role={embedded ? undefined : "dialog"} aria-label="Capture">
      <span data-testid="capture-project">{session.projectId ?? "No Project"}</span>
      <button onClick={() => dispatch({ type: "select_project", projectId: "prj_capture_explicit" })}>Choose Capture Project</button>
      <textarea aria-label="Capture text" value={session.form === "quick_note" ? session.noteDraft : session.conversationDraft}
        onChange={(event) => dispatch({ type: "edit_draft", form: session.form, text: event.target.value })} />
      <button onClick={onBack}>Back</button>
      <button onClick={onClose}>Close Capture</button>
    </section> : null,
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
    const [title, setTitle] = useState("");
    return open ? <section role="dialog" aria-label="Create task">
      <form data-testid="task-create-sheet"><label>Title<input aria-label="Title" value={title} onChange={(event) => setTitle(event.target.value)} /></label></form>
      <span data-testid="task-project">{context?.projectId ?? "No Project"}</span>
      <button onClick={() => onBack({ projectId: context?.projectId ?? null })} data-testid="task-create-back">Back</button>
      <button onClick={() => onConfirmed(taskReceipt)}>Confirm Task</button>
      <button onClick={() => onOpenChange(false)}>Close Task</button>
    </section> : null;
  },
}));

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

function Harness({ sessionEpoch = "session-a", projectId }: { sessionEpoch?: string; projectId?: string }) {
  const [open, setOpen] = useState(false);
  const [showInvoker, setShowInvoker] = useState(true);
  return <LauncherPrincipalProvider principalId="principal-a" sessionEpoch={sessionEpoch}>
    <main><h1>Today</h1>
      {showInvoker ? <button onClick={() => setOpen(true)}>Invoker</button> : null}
      <button onClick={() => setShowInvoker(false)}>Remove invoker</button>
      <button>Search or create</button>
    </main>
    <GlobalLauncher open={open} onOpenChange={setOpen} projectId={projectId} />
  </LauncherPrincipalProvider>;
}

function openLauncher() {
  fireEvent.click(screen.getByRole("button", { name: "Invoker" }));
  return screen.getByRole("dialog", { name: "Search or create" });
}

function openNew() {
  const launcher = openLauncher();
  fireEvent.click(within(launcher).getByRole("button", { name: "New" }));
  return screen.getByRole("dialog", { name: "Search or create" });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  scope.epoch = 0;
  scope.projectId = null;
  navigation.push.mockClear();
  delayed.task = null;
});

describe("GlobalLauncher hardened contract", () => {
  it("starts with exactly Search and New, focuses Search, and reuses canonical Search without creation rows", () => {
    render(<Harness />);
    const launcher = openLauncher();
    expect(within(launcher).getByRole("group", { name: "Search or New" }).querySelectorAll("button").length).toBe(2);
    expect(within(within(launcher).getByRole("group", { name: "Search or New" })).getAllByRole("button").map((button) => button.textContent?.trim())).toEqual(["Search", "New"]);
    expect(within(launcher).getByRole("button", { name: "Search" })).toHaveFocus();
    fireEvent.click(within(launcher).getByRole("button", { name: "Search" }));
    expect(within(launcher).getByTestId("canonical-search-panel")).toBeInTheDocument();
    expect(within(launcher).getByRole("searchbox", { name: "Search" })).toHaveFocus();
    expect(within(launcher).queryByRole("button", { name: /Create Task|Quick Note|Conversation Log/ })).toBeNull();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("seeds Search from printable initial input and returns through initial before closing", async () => {
    render(<Harness />);
    const launcher = openLauncher();
    fireEvent.keyDown(launcher, { key: "m" });
    expect(within(launcher).getByRole("searchbox", { name: "Search" })).toHaveValue("m");
    expect(within(launcher).getByRole("searchbox", { name: "Search" })).toHaveFocus();
    fireEvent.keyDown(within(launcher).getByRole("searchbox", { name: "Search" }), { key: "Escape" });
    expect(within(launcher).getByRole("button", { name: "Search" })).toHaveFocus();
    fireEvent.keyDown(launcher, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Search or create" })).toBeNull());
  });

  it("offers exactly Create Task, Quick Note, Conversation Log in that order", () => {
    render(<Harness />);
    const launcher = openNew();
    expect(within(within(launcher).getByRole("group", { name: "Create new" })).getAllByRole("button").map((button) => button.textContent?.trim())).toEqual([
      "Create Task", "Quick Note", "Conversation Log",
    ]);
    expect(within(launcher).getByRole("button", { name: "Create Task" })).toHaveFocus();
  });

  it("keeps Task's open-time Project seed independent of Capture's explicit selection", async () => {
    scope.projectId = "prj_seed";
    render(<Harness />);
    fireEvent.click(within(openNew()).getByRole("button", { name: "Quick Note" }));
    fireEvent.click(screen.getByRole("button", { name: "Choose Capture Project" }));
    expect(screen.getByTestId("capture-project")).toHaveTextContent("prj_capture_explicit");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(within(screen.getByRole("group", { name: "Create new" })).getByRole("button", { name: "Create Task" }));
    expect(await screen.findByTestId("task-project")).toHaveTextContent("prj_seed");
  });

  it("defers dirty Search navigation until discard and preserves the draft on Keep editing", async () => {
    render(<Harness />);
    const launcher = openNew();
    fireEvent.click(within(launcher).getByRole("button", { name: "Quick Note" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Capture text" }), { target: { value: "Synthetic unsent draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.keyDown(launcher, { key: "Escape" });
    fireEvent.click(within(launcher).getByRole("button", { name: "Search" }));
    fireEvent.click(within(launcher).getByRole("button", { name: "Open read result" }));
    expect(screen.getByRole("alertdialog", { name: "Discard drafts" })).toHaveTextContent(
      "Discard unsent drafts? Held offline notes are not deleted.",
    );
    expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus();
    expect(navigation.push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByRole("dialog", { name: "Search or create" })).toBeInTheDocument();
    expect(navigation.push).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("searchbox", { name: "Search" }), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    fireEvent.click(screen.getByRole("button", { name: "Quick Note" }));
    expect(screen.getByRole("textbox", { name: "Capture text" })).toHaveValue("Synthetic unsent draft");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.keyDown(launcher, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(screen.getByRole("button", { name: "Open read result" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard drafts" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Search or create" })).toBeNull());
    expect(navigation.push).toHaveBeenCalledExactlyOnceWith("/review");
  });

  it("navigates a clean Search result once without a discard prompt", async () => {
    render(<Harness />);
    const launcher = openLauncher();
    fireEvent.click(within(launcher).getByRole("button", { name: "Search" }));
    fireEvent.click(within(launcher).getByRole("button", { name: "Open read result" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Search or create" })).toBeNull());
    expect(screen.queryByRole("alertdialog", { name: "Discard drafts" })).toBeNull();
    expect(navigation.push).toHaveBeenCalledExactlyOnceWith("/review");
  });

  it("hands off to one canonical Task sheet, returns to New with the same editable draft", async () => {
    scope.projectId = "prj_aaaaaaaa11111111";
    render(<Harness />);
    const launcher = openNew();
    fireEvent.click(within(launcher).getByRole("button", { name: "Create Task" }));
    expect(await screen.findByRole("dialog", { name: "Create task" })).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByTestId("task-project")).toHaveTextContent(scope.projectId);
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Draft task" } });
    fireEvent.click(screen.getByTestId("task-create-back"));
    const returned = screen.getByRole("dialog", { name: "Search or create" });
    expect(within(returned).getByRole("button", { name: "Create Task" })).toHaveFocus();
    fireEvent.click(within(returned).getByRole("button", { name: "Create Task" }));
    expect(await screen.findByRole("textbox", { name: "Title" })).toHaveValue("Draft task");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("keeps controlled Task input intact and prompts on an immediate dirty close", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    fireEvent.click(within(openNew()).getByRole("button", { name: "Create Task" }));
    const title = await screen.findByRole("textbox", { name: "Title" });
    await user.type(title, "Synthetic Task draft");
    expect(title).toHaveValue("Synthetic Task draft");
    await user.click(screen.getByRole("button", { name: "Close Task" }));
    expect(await screen.findByRole("alertdialog", { name: "Discard drafts" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(await screen.findByRole("textbox", { name: "Title" })).toHaveValue("Synthetic Task draft");
  });

  it("returns to the launcher control when a pointer click leaves focus on the body", async () => {
    render(<Harness />);
    expect(document.activeElement).toBe(document.body);
    openLauncher();
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Search or create" }), { key: "Escape" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Search or create" })).toHaveFocus());
  });

  it("closes on Task confirmation, stays on the origin, and offers no Open Task", async () => {
    render(<Harness />);
    fireEvent.click(within(openNew()).getByRole("button", { name: "Create Task" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm Task" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByRole("button", { name: "Open Task" })).toBeNull();
    expect(navigation.push).not.toHaveBeenCalled();
  });

  it("restores the exact invoker and falls back to the stable launcher control", async () => {
    render(<Harness />);
    const invoker = screen.getByRole("button", { name: "Invoker" });
    invoker.focus();
    openLauncher();
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Search or create" }), { key: "Escape" });
    await waitFor(() => expect(invoker).toHaveFocus());
    openLauncher();
    fireEvent.click(screen.getByRole("button", { name: "Remove invoker" }));
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Search or create" }), { key: "Escape" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Search or create" })).toHaveFocus());
  });

  it("ignores an old Task confirmation after the verified session changes", () => {
    const view = render(<Harness />);
    fireEvent.click(within(openNew()).getByRole("button", { name: "Create Task" }));
    const stale = delayed.task;
    view.rerender(<Harness sessionEpoch="session-b" />);
    stale?.();
    expect(screen.queryByRole("button", { name: "Open Task" })).toBeNull();
    expect(navigation.push).not.toHaveBeenCalled();
  });
});
