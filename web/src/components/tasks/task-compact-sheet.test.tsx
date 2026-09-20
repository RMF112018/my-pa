import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * WP07 — diagnostic presentation follows the global policy. The product default
 * is OFF; this file sets the mode each test actually means.
 */
const { diagnostics } = vi.hoisted(() => ({ diagnostics: { enabled: true } }));
vi.mock("@/components/diagnostics/diagnostics-provider", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/diagnostics/diagnostics-provider")>();
  return {
    ...actual,
    // Both must be replaced: `WhenDiagnostics` closes over the real hook in its
    // own module scope, so overriding only the exported hook would leave the
    // guard reading the unmocked policy.
    useDiagnosticsEnabled: () => diagnostics.enabled,
    WhenDiagnostics: ({ children }: { children: React.ReactNode }) =>
      diagnostics.enabled ? children : null,
  };
});
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskCompactSheet } from "@/components/tasks/task-compact-sheet";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskRow } from "@/contracts/work";

afterEach(() => {
  diagnostics.enabled = true;
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_ID = "tsk_aaaaaaaa11111111";

const SEED: TaskRow = {
  task_id: TASK_ID,
  title: "Coordinate the review",
  lifecycle_state: "in_progress",
  priority: "p2",
  due_at: null,
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-08-20T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
  // Deliberately no version: a list row carries no mutation authority.
};

const CANONICAL: TaskDetail = {
  ...SEED,
  version: 7,
  description: "Confirm the revised scope with the reviewer.",
  evidence_state: "accepted",
  origin_kind: "direct_principal",
  origin_evidence_ref: null,
  closure_evidence_ref: null,
  accepted_by_review_decision_id: null,
  acceptance_kind: null,
  closure_history_id: null,
  commitment_id: null,
  role: null,
  project_id: null,
  situation_id: null,
  opened_at: "2026-08-20T12:00:00Z",
  closed_at: null,
};

const TERMINAL: TaskDetail = {
  ...CANONICAL,
  lifecycle_state: "completed",
  closed_at: "2026-08-24T12:00:00Z",
};

function contextHandlers(path: string) {
  if (path.startsWith("/api/projects/")) return Response.json({ project: { name: "Linked project" } });
  if (path === "/api/situations") return Response.json({ situations: [] });
  if (/^\/api\/commitments\/[^/?]+$/.test(path)) {
    return Response.json({ commitment: { title: "Linked commitment" } });
  }
  return null;
}

/** A canonical read that only resolves when the test releases it. */
function gatedFetch(canonical: TaskDetail = CANONICAL) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.includes("/comments")) return Response.json({ comments: [] });
    if (path.includes("/history")) return Response.json({ history: [] });
    if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
    const context = contextHandlers(path);
    if (context) return context;
    if (path === `/api/tasks/${TASK_ID}`) {
      await gate;
      return Response.json({ task: canonical });
    }
    throw new Error(`unexpected request: ${path}`);
  });
  return { fetcher, release };
}

function renderSheet(
  seed: TaskRow | null,
  onOpenChange = vi.fn(),
): { onOpenChange: ReturnType<typeof vi.fn> } {
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <TaskCompactSheet taskId={TASK_ID} open onOpenChange={onOpenChange} seed={seed} />
    </TaskRuntimeProvider>,
  );
  return { onOpenChange };
}

function visualHeadings(name: string) {
  return screen.getAllByRole("heading", { name }).filter((heading) => !heading.classList.contains("sr-only"));
}

function expectNoEagerCommitmentList(fetcher: ReturnType<typeof vi.fn<typeof fetch>>) {
  expect(
    fetcher.mock.calls.some(([input]) => String(input) === "/api/commitments?pageSize=100"),
  ).toBe(false);
}

describe("TaskCompactSheet", () => {
  it("paints a projection immediately but mounts no mutation control before canonical hydration", async () => {
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);

    // Seeded paint: human title and status, straight from the projection.
    const hydrating = await screen.findByTestId("task-detail-hydrating");
    expect(within(hydrating).getByText("Coordinate the review")).toBeTruthy();
    expect(hydrating.textContent).toContain("In progress");
    expect(within(hydrating).getByRole("heading", { level: 1, name: "Coordinate the review" })).toBeTruthy();

    // No mutation control exists at all while the version is untrusted.
    expect(screen.queryByTestId("task-status-control")).toBeNull();
    expect(screen.queryByTestId("task-due-control")).toBeNull();
    expect(screen.queryByTestId("task-close-control")).toBeNull();
    expect(screen.queryByTestId("task-edit-title")).toBeNull();
    expect(screen.queryByTestId("task-edit-priority")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add comment" })).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expectNoEagerCommitmentList(fetcher);

    release();

    // Canonical snapshot with a trustworthy version enables the controls.
    expect(await screen.findByTestId("task-status-control")).toBeTruthy();
    expect(screen.getByTestId("task-close-control")).toBeTruthy();
    expect(screen.getByTestId("task-due-control")).toBeTruthy();
    expect(screen.queryByTestId("task-detail-hydrating")).toBeNull();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(visualHeadings("Coordinate the review")).toHaveLength(1);
    expectNoEagerCommitmentList(fetcher);
  });

  it("names the dialog from a visually hidden title", async () => {
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);
    await screen.findByTestId("task-detail-hydrating");

    const dialog = screen.getByRole("dialog", { name: "Coordinate the review" });
    const dialogTitle = within(dialog)
      .getAllByRole("heading", { name: "Coordinate the review" })
      .find((heading) => heading.classList.contains("sr-only"));
    expect(dialogTitle).toBeTruthy();

    release();
    await screen.findByTestId("task-status-control");
    expect(screen.getByRole("dialog", { name: "Coordinate the review" })).toBeTruthy();
    expect(
      within(screen.getByRole("dialog"))
        .getAllByRole("heading", { name: "Coordinate the review" })
        .some((heading) => heading.classList.contains("sr-only")),
    ).toBe(true);
    expect(visualHeadings("Coordinate the review")).toHaveLength(1);
  });

  it("enables Status only once a canonical version is held", async () => {
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);
    await screen.findByTestId("task-detail-hydrating");
    release();

    const control = await screen.findByTestId("task-status-control");
    const select = within(control).getByRole("combobox");
    await waitFor(() => expect(select).not.toBeDisabled());
  });

  it("opens without a projection and still hydrates", async () => {
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(null);
    expect(screen.queryByTestId("task-detail-hydrating")).toBeNull();
    release();
    expect(await screen.findByTestId("task-status-control")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Task detail" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Task detail" }).classList.contains("sr-only")).toBe(true);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("presents the Task as a dialog with an accessible name and closes on Escape", async () => {
    const user = userEvent.setup();
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    const { onOpenChange } = renderSheet(SEED);
    release();
    await screen.findByTestId("task-status-control");

    // Radix dialog semantics come from the shared Sheet, not from a new overlay.
    expect(screen.getByRole("dialog", { name: "Coordinate the review" })).toBeTruthy();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("offers no Technical details at all while diagnostics are off", async () => {
    // The ON case below proves the identifiers are reachable *behind* the
    // disclosure. This proves the disclosure itself is absent by default, which
    // is the product state and the one the ON case cannot speak to.
    diagnostics.enabled = false;
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);
    release();
    await screen.findByTestId("task-status-control");
    const sheet = screen.getByTestId("task-compact-sheet");

    expect(within(sheet).queryByText("Technical details")).toBeNull();
    expect(screen.queryByTestId("task-technical-details")).toBeNull();
    expect(sheet.textContent).not.toContain(TASK_ID);
    // Product truth: the Task's status still reads in product language.
    expect(sheet.textContent).toContain("In progress");
  });

  it("keeps raw identifiers out of the compact Task view until diagnostics are opened", async () => {
    const user = userEvent.setup();
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);
    release();
    // A mutation control only mounts after canonical hydration, so this is the
    // earliest point at which the hydrated Task view is fully rendered.
    await screen.findByTestId("task-status-control");
    const sheet = screen.getByTestId("task-compact-sheet");

    expect(sheet.textContent).not.toContain(TASK_ID);
    expect(sheet.textContent).not.toMatch(/in_progress|\bp2\b/);
    expect(sheet.textContent).toContain("In progress");

    await user.click(screen.getByText("Technical details"));
    await waitFor(() => expect(screen.getByTestId("task-compact-sheet").textContent).toContain(TASK_ID));
  });

  it("states a terminal Task without status, due, close, or cancel choosers", async () => {
    const { fetcher, release } = gatedFetch(TERMINAL);
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);
    release();

    expect(await screen.findByTestId("task-terminal-summary")).toBeTruthy();
    expect(screen.queryByTestId("task-status-control")).toBeNull();
    expect(screen.queryByTestId("task-due-control")).toBeNull();
    expect(screen.queryByTestId("task-close-trigger")).toBeNull();
    expect(screen.queryByTestId("task-cancel-trigger")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
