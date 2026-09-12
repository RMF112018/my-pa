/**
 * Capture hands Task creation off; it never captures a Task.
 *
 * The chooser added in front of Capture routes to two different kinds of thing,
 * and the whole risk of that design lives in the difference between them. A note
 * is a capture: a request, an attempt key, and — when the network is gone — an
 * encrypted row in this browser's queue that is replayed as `POST /api/capture`
 * on reconnect. A Task is none of those. If choosing Create Task minted a key,
 * issued a capture, or wrote a queue entry, a Task started here would come back
 * as a note, so every case below asserts the *absence* of capture work as
 * directly as it asserts the presence of the Task sheet.
 *
 * The second invariant is overlay ownership. Capture is a native `<dialog>` and
 * the Task sheet is a Radix sheet; stacking them would leave two focus traps and
 * two Escape owners on screen at once. The shell closes Capture before it opens
 * the sheet, and "the Capture dialog is gone" is asserted rather than assumed.
 *
 * Everything here is synthetic.
 */
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "@/components/shell/app-shell";
import { useTaskRuntime } from "@/components/work/task-runtime-provider";
import type { PrincipalSession } from "@/contracts/identity";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/today",
  useRouter: () => ({ push: navigation.push, refresh: vi.fn() }),
}));

// The offline queue is mocked so the Create Task path can be held to writing
// nothing at all — the real queue is exercised in `capture-offline.test.tsx`.
const offline = vi.hoisted(() => ({
  queueCaptureOffline: vi.fn(),
  drainCaptureQueue: vi.fn(async () => ({
    summary: {},
    counts: { pending: 0, stalled: 0, quarantined: 0, needsReauth: 0 },
  })),
  heldCaptures: vi.fn(async () => []),
  releaseHeldCapture: vi.fn(),
  deleteHeldCapture: vi.fn(),
}));

vi.mock("@/lib/offline/capture-queue", () => offline);

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "11111111-2222-3333-4444-555555555555:aaaa0001-0000-0000-0000-000000000001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

/** Open Capture from the desktop control and return the chooser. */
async function openCapture() {
  const user = userEvent.setup();
  const fetchSpy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("{}", { status: 200 }));
  render(<AppShell principal={PRINCIPAL}>content</AppShell>);
  await user.click(screen.getByTestId("capture-button-desktop"));
  const chooser = await screen.findByTestId("capture-chooser");
  return { user, chooser, fetchSpy };
}

/** Every `/api/capture` call the stub saw, whatever else the shell fetched. */
function captureCalls(fetchSpy: { readonly mock: { readonly calls: readonly unknown[][] } }) {
  return fetchSpy.mock.calls.filter((call) => String(call[0]).includes("/api/capture"));
}

describe("the Capture chooser", () => {
  it("offers exactly Create Task, Quick note and Conversation log", async () => {
    const { chooser } = await openCapture();
    expect(within(chooser).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Create Task",
      "Quick note",
      "Conversation log",
    ]);
  });

  it("routes Quick note into the capture branch the shell already had", async () => {
    const { user, chooser } = await openCapture();
    await user.click(within(chooser).getByText("Quick note"));
    expect(screen.getByTestId("capture-kind-quick_note")).toBeChecked();
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveFocus());
    expect(screen.queryByTestId("task-create-sheet")).toBeNull();
  });

  it("routes Conversation log into the same branch", async () => {
    const { user, chooser } = await openCapture();
    await user.click(within(chooser).getByText("Conversation log"));
    expect(screen.getByTestId("capture-kind-conversation_log")).toBeChecked();
    expect(screen.getByTestId("capture-field")).toBeInTheDocument();
    expect(screen.queryByTestId("task-create-sheet")).toBeNull();
  });
});

describe("Create Task from Capture", () => {
  it("opens the canonical Task sheet and captures nothing on the way", async () => {
    const { user, chooser, fetchSpy } = await openCapture();

    await user.click(within(chooser).getByText("Create Task"));

    // The canonical create surface — the same component Work opens.
    expect(await screen.findByTestId("task-create-sheet")).toBeInTheDocument();
    // Zero capture persistence: no request to the capture route, and nothing
    // written to the device queue that reconnect would replay as a note.
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
    expect(screen.queryByTestId("capture-field")).toBeNull();
    expect(screen.queryByTestId("capture-queued")).toBeNull();
  });

  it("leaves exactly one overlay on screen — Capture is gone, not stacked", async () => {
    const { user, chooser } = await openCapture();
    expect(screen.getByRole("dialog", { name: "Capture" })).toBeInTheDocument();

    await user.click(within(chooser).getByText("Create Task"));

    await screen.findByTestId("task-create-sheet");
    // Capture's native <dialog> is closed, so neither it nor its chooser is
    // exposed any more, and the Task sheet is the only dialog on screen.
    expect(screen.queryByRole("dialog", { name: "Capture" })).toBeNull();
    expect(screen.queryByRole("group", { name: "What are you capturing?" })).toBeNull();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("comes back to the Capture chooser on Back, with no capture made", async () => {
    const { user, chooser, fetchSpy } = await openCapture();
    await user.click(within(chooser).getByText("Create Task"));
    await screen.findByTestId("task-create-sheet");

    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(await screen.findByTestId("capture-chooser")).toBeInTheDocument();
    expect(screen.queryByTestId("task-create-sheet")).toBeNull();
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });

  it("returns focus to the control that opened Capture when the sheet closes", async () => {
    const { user, chooser } = await openCapture();
    const invoker = screen.getByTestId("capture-button-desktop");
    await user.click(within(chooser).getByText("Create Task"));
    await screen.findByTestId("task-create-sheet");

    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await waitFor(() => expect(screen.queryByTestId("task-create-sheet")).toBeNull());
    await waitFor(() => expect(invoker).toHaveFocus());
  });
});

/**
 * A Capture-launched create must reconcile mounted Task queries.
 *
 * Work forwards nothing here: the canonical create notifies the session-scoped
 * runtime seam itself. That is the only reason a Task created from the shell —
 * which Work does not own and cannot see — still appears in a Work list that is
 * already on screen. Wiring reconciliation into each launcher instead would
 * leave exactly this path silently unreconciled, so it is asserted directly.
 */
describe("a Capture-launched create reconciles active Task queries", () => {
  function Probe({ onRevalidate }: { onRevalidate: () => void }) {
    const runtime = useTaskRuntime();
    useEffect(
      () => runtime.reconciliation.registerActiveTaskQuery("probe-work-list", onRevalidate),
      [runtime, onRevalidate],
    );
    return null;
  }

  it("asks a mounted Task query to re-read the server exactly once", async () => {
    const user = userEvent.setup();
    const revalidate = vi.fn();
    const created = {
      task_id: "tsk_cccccccc33333333",
      title: "Synthetic shell task",
      lifecycle_state: "open",
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && String(init?.method).toUpperCase() === "POST") {
        return Response.json({ task: created });
      }
      return new Response("{}", { status: 200 });
    });

    render(
      <AppShell principal={PRINCIPAL}>
        <Probe onRevalidate={revalidate} />
      </AppShell>,
    );

    await user.click(screen.getByTestId("capture-button-desktop"));
    const chooser = await screen.findByTestId("capture-chooser");
    await user.click(within(chooser).getByText("Create Task"));

    const sheet = await screen.findByTestId("task-create-sheet");
    await user.type(within(sheet).getByLabelText("Title"), "Synthetic shell task");
    expect(revalidate).not.toHaveBeenCalled();

    await user.click(within(sheet).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(revalidate).toHaveBeenCalledTimes(1));
    // The Task was created, and nothing was captured on the way.
    expect(
      fetchSpy.mock.calls.some(
        ([input, init]) =>
          String(input) === "/api/tasks" && String(init?.method).toUpperCase() === "POST",
      ),
    ).toBe(true);
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });
});
