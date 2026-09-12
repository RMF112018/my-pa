import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskCompactSheet } from "@/components/tasks/task-compact-sheet";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskRow } from "@/contracts/work";

afterEach(() => {
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

/** A canonical read that only resolves when the test releases it. */
function gatedFetch() {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.includes("/comments")) return Response.json({ comments: [] });
    if (path.includes("/history")) return Response.json({ history: [] });
    if (path === "/api/commitments?pageSize=100") return Response.json({ commitments: [] });
    if (path === `/api/tasks/${TASK_ID}`) {
      await gate;
      return Response.json({ task: CANONICAL });
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

describe("TaskCompactSheet", () => {
  it("paints a projection immediately but mounts no mutation control before canonical hydration", async () => {
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);

    // Seeded paint: human title and status, straight from the projection.
    const hydrating = await screen.findByTestId("task-detail-hydrating");
    expect(within(hydrating).getByText("Coordinate the review")).toBeTruthy();
    expect(within(hydrating).getByText("In progress")).toBeTruthy();

    // No mutation control exists at all while the version is untrusted.
    expect(screen.queryByTestId("task-status-control")).toBeNull();
    expect(screen.queryByTestId("task-due-control")).toBeNull();
    expect(screen.queryByTestId("task-close-control")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add comment" })).toBeNull();

    release();

    // Canonical snapshot with a trustworthy version enables the controls.
    expect(await screen.findByTestId("task-status-control")).toBeTruthy();
    expect(screen.getByTestId("task-close-control")).toBeTruthy();
    expect(screen.getByTestId("task-due-control")).toBeTruthy();
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
  });

  it("presents the Task as a dialog with an accessible name and closes on Escape", async () => {
    const user = userEvent.setup();
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    const { onOpenChange } = renderSheet(SEED);
    release();
    await screen.findByTestId("task-compact-sheet");

    // Radix dialog semantics come from the shared Sheet, not from a new overlay.
    expect(screen.getByRole("dialog", { name: "Coordinate the review" })).toBeTruthy();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("keeps raw identifiers out of the compact Task view until diagnostics are opened", async () => {
    const user = userEvent.setup();
    const { fetcher, release } = gatedFetch();
    vi.stubGlobal("fetch", fetcher);

    renderSheet(SEED);
    release();
    const sheet = await screen.findByTestId("task-compact-sheet");

    expect(sheet.textContent).not.toContain(TASK_ID);
    expect(sheet.textContent).not.toMatch(/in_progress|\bp2\b/);
    expect(sheet.textContent).toContain("In progress");

    await user.click(screen.getByText("Technical details"));
    await waitFor(() => expect(screen.getByTestId("task-compact-sheet").textContent).toContain(TASK_ID));
  });
});
