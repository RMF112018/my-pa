/**
 * The unified launcher hands Task creation to the canonical Task sheet; it
 * never captures a Task.
 *
 * The New menu routes to two different kinds of thing,
 * and the whole risk of that design lives in the difference between them. A note
 * is a capture: a request, an attempt key, and — when the network is gone — an
 * encrypted row in this browser's queue that is replayed as `POST /api/capture`
 * on reconnect. A Task is none of those. If choosing Create Task minted a key,
 * issued a capture, or wrote a queue entry, a Task started here would come back
 * as a note, so every case below asserts the *absence* of capture work as
 * directly as it asserts the presence of the Task sheet.
 *
 * The second invariant is overlay ownership. The launcher is a native
 * `<dialog>` and the Task sheet is a Radix sheet; stacking them would leave two
 * focus traps and two Escape owners. The launcher trap closes before the sheet
 * opens, and that transition is asserted rather than assumed.
 *
 * Everything here is synthetic.
 */
import { useEffect } from "react";
import { taskCreateResponse } from "@/lib/task/testing/task-mutation-fixture";
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
  // Counts without a replay: the indicator's refresh path.
  heldCaptureCounts: vi.fn(async () => ({
    pending: 0,
    stalled: 0,
    quarantined: 0,
    needsReauth: 0,
    heldBytes: 0,
  })),
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
const SESSION_EPOCH = "test-session-binding";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

/** Traverse the real shell control through Initial → New. */
async function openNew() {
  const user = userEvent.setup();
  const fetchSpy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("{}", { status: 200 }));
  render(<AppShell principal={PRINCIPAL} sessionEpoch={SESSION_EPOCH}>content</AppShell>);
  const invoker = screen.getByTestId("launcher-button-desktop");
  await user.click(invoker);
  const launcher = await screen.findByRole("dialog", { name: "Search or create" });
  expect(within(launcher).getByRole("button", { name: "Search" })).toHaveFocus();
  await user.click(within(launcher).getByRole("button", { name: "New" }));
  const menu = await screen.findByRole("group", { name: "Create new" });
  return { user, launcher, menu, invoker, fetchSpy };
}

/** Every `/api/capture` call the stub saw, whatever else the shell fetched. */
function captureCalls(fetchSpy: { readonly mock: { readonly calls: readonly unknown[][] } }) {
  return fetchSpy.mock.calls.filter((call) => String(call[0]).includes("/api/capture"));
}

describe("the unified launcher New menu", () => {
  it("offers exactly Create Task, Quick Note and Conversation Log", async () => {
    const { menu } = await openNew();
    expect(within(menu).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Create Task",
      "Quick Note",
      "Conversation Log",
    ]);
  });

  it("routes Quick Note into the canonical Capture composition", async () => {
    const { user, menu, fetchSpy } = await openNew();
    await user.click(within(menu).getByRole("button", { name: "Quick Note" }));
    expect(screen.getByTestId("capture-kind-quick_note")).toBeChecked();
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveFocus());
    expect(screen.queryByTestId("task-create-sheet")).toBeNull();
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });

  it("routes Conversation Log into the canonical Capture composition", async () => {
    const { user, menu, fetchSpy } = await openNew();
    await user.click(within(menu).getByRole("button", { name: "Conversation Log" }));
    expect(screen.getByTestId("capture-kind-conversation_log")).toBeChecked();
    expect(screen.getByTestId("capture-field")).toBeInTheDocument();
    expect(screen.queryByTestId("task-create-sheet")).toBeNull();
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });
});

describe("Create Task from the unified launcher", () => {
  it("opens the canonical Task sheet and captures nothing on the way", async () => {
    const { user, menu, fetchSpy } = await openNew();

    await user.click(within(menu).getByRole("button", { name: "Create Task" }));

    // The canonical create surface — the same component Work opens.
    expect(await screen.findByTestId("task-create-sheet")).toBeInTheDocument();
    // Zero capture persistence: no request to the capture route, and nothing
    // written to the device queue that reconnect would replay as a note.
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
    expect(screen.queryByTestId("capture-field")).toBeNull();
    expect(screen.queryByTestId("capture-queued")).toBeNull();
  });

  it("leaves exactly one active overlay after the launcher trap closes", async () => {
    const { user, menu, launcher } = await openNew();
    expect(launcher).toBeInTheDocument();

    await user.click(within(menu).getByRole("button", { name: "Create Task" }));

    await screen.findByTestId("task-create-sheet");
    // The launcher trap is closed before the Task sheet becomes active.
    expect(screen.queryByRole("dialog", { name: "Search or create" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Create new" })).toBeNull();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("comes back to New on Back with the same Task draft and no capture made", async () => {
    const { user, menu, fetchSpy } = await openNew();
    await user.click(within(menu).getByRole("button", { name: "Create Task" }));
    await screen.findByTestId("task-create-sheet");
    await user.type(screen.getByRole("textbox", { name: "Title" }), "Synthetic draft stays here");

    await user.click(screen.getByTestId("task-create-back"));

    const reopened = await screen.findByRole("group", { name: "Create new" });
    expect(screen.queryByTestId("task-create-sheet")).toBeNull();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await user.click(within(reopened).getByRole("button", { name: "Create Task" }));
    expect(await screen.findByRole("textbox", { name: "Title" })).toHaveValue("Synthetic draft stays here");
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });

  it("puts focus on Create Task in reopened New after Back", async () => {
    // WP02-AC-020. Returning to New is not the same as being able to
    // carry on from it: Back dismisses a focus-trapping sheet, and if focus fell
    // to the body a keyboard or screen-reader Principal would be dropped out of
    // the flow they are still in the middle of.
    const { user, menu } = await openNew();
    await user.click(within(menu).getByRole("button", { name: "Create Task" }));
    await screen.findByTestId("task-create-sheet");

    await user.click(screen.getByTestId("task-create-back"));

    const reopened = await screen.findByRole("group", { name: "Create new" });
    await waitFor(() => {
      const active = document.activeElement;
      expect(active).not.toBe(document.body);
      expect(within(reopened).getByRole("button", { name: "Create Task" })).toHaveFocus();
    });
  });

  it("returns focus to the exact shell launcher invoker when the sheet closes", async () => {
    const { user, menu, invoker, fetchSpy } = await openNew();
    await user.click(within(menu).getByRole("button", { name: "Create Task" }));
    await screen.findByTestId("task-create-sheet");

    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await waitFor(() => expect(screen.queryByTestId("task-create-sheet")).toBeNull());
    await waitFor(() => expect(invoker).toHaveFocus());
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });

  it("uses the stable shell launcher fallback when the exact invoker disappears", async () => {
    const { user, menu, invoker, fetchSpy } = await openNew();
    await user.click(within(menu).getByRole("button", { name: "Create Task" }));
    await screen.findByTestId("task-create-sheet");
    invoker.remove();

    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await waitFor(() => expect(screen.queryByTestId("task-create-sheet")).toBeNull());
    await waitFor(() => expect(screen.getByTestId("launcher-button-mobile")).toHaveFocus());
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });
});

/**
 * A launcher-created Task must reconcile mounted Task queries.
 *
 * Work forwards nothing here: the canonical create notifies the session-scoped
 * runtime seam itself. That is the only reason a Task created from the shell —
 * which Work does not own and cannot see — still appears in a Work list that is
 * already on screen. Wiring reconciliation into each launcher instead would
 * leave exactly this path silently unreconciled, so it is asserted directly.
 */
describe("a launcher-created Task reconciles active Task queries", () => {
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
        return Response.json(taskCreateResponse({ taskId: created.task_id, title: created.title }));
      }
      return new Response("{}", { status: 200 });
    });

    render(
      <AppShell principal={PRINCIPAL} sessionEpoch={SESSION_EPOCH}>
        <Probe onRevalidate={revalidate} />
      </AppShell>,
    );

    await user.click(screen.getByTestId("launcher-button-desktop"));
    const launcher = await screen.findByRole("dialog", { name: "Search or create" });
    await user.click(within(launcher).getByRole("button", { name: "New" }));
    const menu = await screen.findByRole("group", { name: "Create new" });
    await user.click(within(menu).getByRole("button", { name: "Create Task" }));

    const sheet = await screen.findByTestId("task-create-sheet");
    await user.type(within(sheet).getByLabelText("Title"), "Synthetic shell task");
    expect(revalidate).not.toHaveBeenCalled();

    await user.click(within(sheet).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(revalidate).toHaveBeenCalledTimes(1));
    // The Task was created, and nothing was captured on the way.
    expect(fetchSpy.mock.calls.filter(
      ([input, init]) =>
        String(input) === "/api/tasks" && String(init?.method).toUpperCase() === "POST",
    )).toHaveLength(1);
    expect(captureCalls(fetchSpy)).toHaveLength(0);
    expect(offline.queueCaptureOffline).not.toHaveBeenCalled();
  });
});
