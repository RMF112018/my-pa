import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type * as React from "react";
import { TaskTechnicalDetails } from "@/components/tasks/task-technical-details";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { TaskDetail, WorkHistoryRow } from "@/contracts/work";
import type { TaskCivilClock } from "@/lib/tasks/presentation";

const clock: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-12" };

function taskDetail(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    task_id: "task-abc-123",
    title: "Send the revised scope to the client",
    lifecycle_state: "completed",
    priority: "p2",
    due_at: "2026-09-12T15:00:00Z",
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-09-11T09:00:00Z",
    opened_at: "2026-09-01T09:00:00Z",
    closed_at: "2026-09-11T09:00:00Z",
    description: null,
    evidence_state: "accepted",
    origin_kind: "evidence",
    origin_evidence_ref: "evidence-origin-77",
    closure_evidence_ref: "evidence-closure-88",
    accepted_by_review_decision_id: "review-decision-99",
    acceptance_kind: "explicit",
    closure_history_id: "history-2",
    version: 7,
    commitment_id: null,
    role: null,
    project_id: "project-555",
    situation_id: "situation-666",
    ...overrides,
  };
}

const history: readonly WorkHistoryRow[] = [
  {
    history_id: "history-1",
    action: "task_status_changed",
    actor: "principal",
    outcome: "applied",
    before_version: 5,
    after_version: 6,
    occurred_at: "2026-09-10T09:00:00Z",
    recorded_at: "2026-09-10T09:00:01Z",
  },
  {
    history_id: "history-2",
    action: "task_closed",
    actor: "principal",
    outcome: "applied",
    before_version: 6,
    after_version: 7,
    occurred_at: "2026-09-11T09:00:00Z",
    recorded_at: "2026-09-11T09:00:01Z",
  },
];

const disclosure: DisclosureEnvelope = {
  scope: "task history",
  coverage: "partial",
  freshnessAt: "2026-09-11T09:05:00Z",
  authority: "accepted",
  limitations: ["Older rows were archived."],
  truncated: true,
  nextCursor: "cursor-2",
};

function renderDetails(props: Partial<React.ComponentProps<typeof TaskTechnicalDetails>> = {}) {
  return render(
    <TaskTechnicalDetails
      task={taskDetail()}
      clock={clock}
      history={history}
      historyLoaded
      {...props}
    />,
  );
}

async function expand() {
  await userEvent.click(screen.getByText("Technical details"));
}

let writeText: ReturnType<typeof vi.fn>;

beforeEach(() => {
  writeText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("TaskTechnicalDetails", () => {
  it("is collapsed by default and renders no diagnostic content", () => {
    renderDetails();

    expect(screen.getByText("Technical details")).toBeTruthy();
    expect(screen.queryByText("task-abc-123")).toBeNull();
    expect(screen.queryByText("evidence-origin-77")).toBeNull();
    expect(screen.getByTestId("task-technical-details").textContent).toBe("Technical details");
  });

  it("calls onExpand on the first expansion only", async () => {
    const onExpand = vi.fn();
    renderDetails({ onExpand });

    await expand();
    expect(onExpand).toHaveBeenCalledTimes(1);
    expect(screen.getByText("task-abc-123")).toBeTruthy();

    await expand();
    expect(screen.queryByText("task-abc-123")).toBeNull();

    await expand();
    expect(onExpand).toHaveBeenCalledTimes(1);
    expect(screen.getByText("task-abc-123")).toBeTruthy();
  });

  it("exposes identity, references, raw relationship ids and raw history codes when expanded", async () => {
    renderDetails();
    await expand();

    expect(screen.getByText("task-abc-123")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText("evidence-origin-77")).toBeTruthy();
    expect(screen.getByText("evidence-closure-88")).toBeTruthy();
    expect(screen.getByText("review-decision-99")).toBeTruthy();
    expect(screen.getByText("project-555")).toBeTruthy();
    expect(screen.getByText("situation-666")).toBeTruthy();
    expect(screen.getByText("task_status_changed")).toBeTruthy();
    expect(screen.getByText("task_closed")).toBeTruthy();
    expect(screen.getByText("v6→v7")).toBeTruthy();
    expect(screen.getByText("Closure receipt")).toBeTruthy();
  });

  it("renders disclosure metadata when supplied", async () => {
    renderDetails({ historyDisclosure: disclosure });
    await expand();

    const group = within(screen.getByRole("region", { name: "Disclosure" }));
    expect(group.getByText("accepted")).toBeTruthy();
    expect(group.getByText("partial")).toBeTruthy();
    expect(group.getByText("2026-09-11T09:05:00Z")).toBeTruthy();
    expect(group.getByText("Yes")).toBeTruthy();
    expect(group.getByText("Older rows were archived.")).toBeTruthy();
  });

  it("offers Continue history only when a next cursor exists", async () => {
    const onContinueHistory = vi.fn();
    const { unmount } = renderDetails({
      historyDisclosure: { ...disclosure, nextCursor: undefined },
      onContinueHistory,
    });
    await expand();
    expect(screen.queryByRole("button", { name: "Continue history" })).toBeNull();
    unmount();

    renderDetails({ historyDisclosure: disclosure, onContinueHistory });
    await expand();
    await userEvent.click(screen.getByRole("button", { name: "Continue history" }));
    expect(onContinueHistory).toHaveBeenCalledTimes(1);
  });

  it("copies the Task ID per value and offers no copy-all control", async () => {
    renderDetails();
    await expand();

    await userEvent.click(screen.getByRole("button", { name: "Copy Task ID" }));
    expect(writeText).toHaveBeenCalledWith("task-abc-123");

    expect(screen.queryByRole("button", { name: /copy all/i })).toBeNull();
    expect(screen.getByTestId("task-technical-details").textContent).not.toMatch(/copy all/i);
    expect(screen.getByRole("button", { name: "Copy origin evidence reference" })).toBeTruthy();
  });

  it("reveals evidence only through the explicit path and never auto-loads it", async () => {
    const onRevealEvidence = vi.fn();
    renderDetails({ onRevealEvidence });
    await expand();

    expect(onRevealEvidence).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "View origin evidence" }));
    expect(onRevealEvidence).toHaveBeenCalledWith("evidence-origin-77");

    await userEvent.click(screen.getByRole("button", { name: "View closure evidence" }));
    expect(onRevealEvidence).toHaveBeenCalledWith("evidence-closure-88");
  });

  it("shows the loading copy while technical history is loading", async () => {
    renderDetails({ history: [], historyLoaded: false, historyLoading: true });
    await expand();

    expect(screen.getByText("Loading technical history…")).toBeTruthy();
    expect(screen.queryByText("No history rows were returned.")).toBeNull();
  });

  it("states an empty history only once the caller has loaded it", async () => {
    renderDetails({ history: [], historyLoaded: true, historyLoading: false });
    await expand();

    expect(screen.getByText("No history rows were returned.")).toBeTruthy();
  });
});
