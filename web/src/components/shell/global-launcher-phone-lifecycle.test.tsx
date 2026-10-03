/** Synthetic integration coverage: real canonical Capture and Search survive phone handoffs. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { GlobalLauncher, LauncherPrincipalProvider } from "./global-launcher";
import { Sheet } from "@/components/ui/sheet";
import { contentSha256 } from "@/lib/capture/receipt";

const PRINCIPAL = "syn-aaaa0001";
const PROJECT = "prj_aaaaaaaa11111111";
const NOTE = "Synthetic phone frozen note";
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/shell/project-scope-provider", () => ({
  useProjectScope: () => ({ epoch: 0, resolution: { scope: { kind: "PROJECT", projectId: "prj_aaaaaaaa11111111" } } }),
}));
vi.mock("@/lib/offline/capture-queue", () => ({ queueCaptureOffline: vi.fn() }));
// Task internals have their own canonical suite. These adapters retain genuine
// Sheet mounting/trap behavior and give the launcher an independent Task draft.
vi.mock("@/components/tasks/task-create-sheet", () => ({
  TaskCreateSheet: ({ open, onOpenChange, onBack, context }: {
    open: boolean; onOpenChange: (open: boolean) => void;
    onBack: (context: { projectId: string | null }) => void; context?: { projectId: string };
  }) => {
    const [title, setTitle] = useState("");
    return <Sheet open={open} onOpenChange={onOpenChange} title="Create task">
      <form data-testid="task-create-sheet">
        <input aria-label="Task draft" value={title} onChange={(event) => setTitle(event.target.value)} />
        <button type="button" data-testid="task-create-back" onClick={() => onBack({ projectId: context?.projectId ?? null })}>Back</button>
      </form>
    </Sheet>;
  },
}));
vi.mock("@/components/tasks/task-compact-sheet", () => ({
  TaskCompactSheet: ({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) =>
    <Sheet open={open} onOpenChange={onOpenChange} title="Task detail"><p>Synthetic Task detail</p></Sheet>,
}));

function Harness({ epoch = "phone-a" }: { epoch?: string }) {
  const [open, setOpen] = useState(false);
  return <LauncherPrincipalProvider principalId={PRINCIPAL} sessionEpoch={epoch}>
    <main><h1>Today</h1><button onClick={() => setOpen(true)}>Search or create</button></main>
    <GlobalLauncher key={epoch} open={open} onOpenChange={setOpen} />
  </LauncherPrincipalProvider>;
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function openNote() {
  fireEvent.click(screen.getByRole("button", { name: "Search or create" }));
  fireEvent.click(screen.getByRole("button", { name: "New" }));
  fireEvent.click(screen.getByRole("button", { name: "Quick Note" }));
  fireEvent.change(screen.getByTestId("capture-field"), { target: { value: NOTE } });
}
async function taskRoundtrip() {
  fireEvent.click(screen.getByTestId("capture-entry-back"));
  fireEvent.click(screen.getByRole("button", { name: "Create Task" }));
  expect(await screen.findByRole("textbox", { name: "Task draft" })).toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  fireEvent.click(screen.getByTestId("task-create-back"));
  fireEvent.click(screen.getByRole("button", { name: "Quick Note" }));
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
}
function interceptCapture(answer: (sent: Record<string, unknown>) => Promise<Response>) {
  const requests: Record<string, unknown>[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).startsWith("/api/capture")) {
      const sent = JSON.parse(String(init?.body)) as Record<string, unknown>;
      requests.push(sent);
      return answer(sent);
    }
    return new Response(JSON.stringify({ projects: [], nextCursor: null }), { status: 200 });
  });
  return requests;
}
function unavailable() {
  return Promise.resolve(new Response(JSON.stringify({ error: { message: "Synthetic service unavailable", errorClass: "unavailable", code: "synthetic_unavailable" } }), { status: 503 }));
}
async function persisted(sent: Record<string, unknown>) {
  return new Response(JSON.stringify({ shape: "backend", status: "persisted", captureKind: sent.captureKind, created: true,
    receipt: { receiptId: "rcpt_aaaaaaaa11111111", captureId: "cap_aaaaaaaa11111111", versionId: "capver_aaaaaaaa11111111", versionNumber: 1,
      idempotencyKey: sent.idempotencyKey, contentSha256: await contentSha256(String(sent.text)), principalId: PRINCIPAL,
      issuedAt: "2026-10-03T12:00:00Z", projectId: sent.projectId ?? null } }), { status: 200 });
}

describe("phone launcher canonical session lifetime", () => {
  it("retries the exact canonical frozen Capture tuple and key after Task roundtrip", async () => {
    const requests = interceptCapture(unavailable);
    render(<Harness />);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByTestId("capture-unavailable");
    expect(requests[0]).toMatchObject({ text: NOTE, captureKind: "quick_note", projectId: PROJECT });
    expect(requests[0].idempotencyKey).toMatch(/^cap-/);
    await taskRoundtrip();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1]).toEqual(requests[0]);
    expect(await screen.findByTestId("capture-unavailable")).toBeInTheDocument();
  });

  it("does not admit a second synthetic record after an attempted edit of an ambiguous Capture", async () => {
    const committed = new Map<string, string>();
    const requests = interceptCapture(async (sent) => {
      const key = String(sent.idempotencyKey);
      if (!committed.has(key)) committed.set(key, `synthetic-record-${committed.size + 1}`);
      // The first write committed, but the client receives an ambiguous response.
      return requests.length === 1 ? unavailable() : persisted(sent);
    });
    render(<Harness />);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByTestId("capture-unavailable");
    const originalRecord = committed.get(String(requests[0].idempotencyKey));
    fireEvent.change(screen.getByTestId("capture-field"), { target: { value: "Synthetic attempted replacement" } });
    expect(screen.getByTestId("capture-field")).toHaveValue(NOTE);
    await taskRoundtrip();
    expect.soft(screen.getByTestId("capture-entry-back")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect.soft(requests[1]).toEqual(requests[0]);
    expect.soft(committed.size).toBe(1);
    expect.soft(committed.get(String(requests[1].idempotencyKey))).toBe(originalRecord);
    await screen.findByTestId("capture-durable");
  });

  it("freezes ambiguous Capture controls and states save uncertainty truthfully", async () => {
    interceptCapture(unavailable);
    render(<Harness />);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const notice = await screen.findByTestId("capture-unavailable");
    expect.soft(screen.getByTestId("capture-field")).toBeDisabled();
    expect.soft(screen.getByTestId("capture-project-select")).toBeDisabled();
    expect.soft(screen.getByTestId("capture-kind-quick_note")).toBeDisabled();
    expect.soft(screen.getByTestId("capture-kind-conversation_log")).toBeDisabled();
    expect.soft(notice).toHaveTextContent("Save unconfirmed");
    expect.soft(notice).toHaveTextContent("the server may have saved this note");
    expect.soft(notice).toHaveTextContent("retrying resubmits the same attempt");
    expect.soft(notice).not.toHaveTextContent("Not saved");
    expect.soft(notice).not.toHaveTextContent("Synthetic service unavailable");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("allows a new edited attempt after a terminal Capture refusal", async () => {
    const requests = interceptCapture(async () => new Response(JSON.stringify({
      error: { errorClass: "validation", code: "synthetic_invalid", message: "Synthetic terminal refusal" },
    }), { status: 422 }));
    render(<Harness />);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByTestId("capture-refused");
    expect(screen.getByTestId("capture-field")).toBeEnabled();
    expect(screen.getByTestId("capture-project-select")).toBeEnabled();
    expect(screen.getByTestId("capture-kind-conversation_log")).toBeEnabled();
    fireEvent.click(screen.getByTestId("capture-kind-conversation_log"));
    fireEvent.change(screen.getByTestId("capture-field"), { target: { value: "Synthetic intentional new attempt" } });
    fireEvent.change(screen.getByTestId("capture-project-select"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1]).toMatchObject({ text: "Synthetic intentional new attempt", captureKind: "conversation_log", projectId: null });
    expect(requests[1].idempotencyKey).not.toBe(requests[0].idempotencyKey);
  });

  it("keeps the pending Capture submit mutex after Task roundtrip", async () => {
    let resolve!: (response: Response) => void;
    const requests = interceptCapture(() => new Promise((done) => { resolve = done; }));
    render(<Harness />);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await taskRoundtrip();
    expect(screen.getByTestId("capture-entry-back")).toHaveFocus();
    const save = screen.getByRole("button", { name: /^(Save|Saving…)$/ });
    fireEvent.click(save);
    expect(requests).toHaveLength(1);
    expect(save).toBeDisabled();
    await act(async () => resolve(await unavailable()));
    expect(await screen.findByTestId("capture-unavailable")).toBeInTheDocument();
  });

  it("applies a late canonical receipt without replacing an unrelated Task draft", async () => {
    let resolve!: (response: Response) => void;
    const requests = interceptCapture(() => new Promise((done) => { resolve = done; }));
    render(<Harness />);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.click(screen.getByTestId("capture-entry-back"));
    fireEvent.click(screen.getByRole("button", { name: "Create Task" }));
    const draft = await screen.findByRole("textbox", { name: "Task draft" });
    fireEvent.change(draft, { target: { value: "Synthetic independent Task" } });
    await act(async () => resolve(await persisted(requests[0])));
    expect(draft).toHaveValue("Synthetic independent Task");
    fireEvent.click(screen.getByTestId("task-create-back"));
    fireEvent.click(screen.getByRole("button", { name: "Quick Note" }));
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveValue(""));
    expect(requests).toHaveLength(1);
  });

  it("ignores an old receipt after verified identity disposal and retains the new draft", async () => {
    let resolve!: (response: Response) => void;
    const requests = interceptCapture(() => new Promise((done) => { resolve = done; }));
    const view = render(<Harness />);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    view.rerender(<Harness epoch="phone-b" />);
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    fireEvent.click(screen.getByRole("button", { name: "Quick Note" }));
    fireEvent.change(screen.getByTestId("capture-field"), { target: { value: "Synthetic new identity draft" } });
    await act(async () => resolve(await persisted(requests[0])));
    expect(screen.getByTestId("capture-field")).toHaveValue("Synthetic new identity draft");
    expect(screen.queryByTestId("capture-saved")).toBeNull();
    expect(requests).toHaveLength(1);
  });

  it("retains real Search query, result node and result focus after Task detail closes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).startsWith("/api/search") ? {
      shape: "backend", query: "Synthetic phone task", hits: [{ domain: "tasks", item: {
        task_id: "tsk_aaaaaaaa11111111", title: "Synthetic phone task", lifecycle_state: "open", priority: null,
        due_at: null, scheduled_at: null, deferred_until: null, archived_at: null,
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", version: 1,
      } }], coverage: [{ domain: "tasks", state: "searched", hitCount: 1 }],
    } : { projects: [], nextCursor: null }), { status: 200 }));
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Search or create" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), { target: { value: "Synthetic phone task" } });
    const group = await screen.findByTestId("search-group-tasks");
    const row = within(group).getByRole("link");
    fireEvent.click(row);
    expect(await screen.findByRole("dialog", { name: "Task detail" })).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    const query = await screen.findByRole("searchbox", { name: "Search" });
    expect(query).toHaveValue("Synthetic phone task");
    expect(row.isConnected).toBe(true);
    expect(screen.getByTestId("search-group-tasks")).toContainElement(row);
    await waitFor(() => expect(row).toHaveFocus());
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
