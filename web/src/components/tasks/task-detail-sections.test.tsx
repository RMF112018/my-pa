import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskDetailSections } from "@/components/tasks/task-detail-sections";
import type { TaskDetail } from "@/contracts/work";
import { toTaskPresentationModel, type TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(cleanup);

const CLOCK: TaskCivilClock = { timezone: "America/New_York", workDate: "2026-09-12" };

function task(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    task_id: "tsk_aaaaaaaa11111111",
    title: "Coordinate the review",
    lifecycle_state: "in_progress",
    priority: "p2",
    due_at: null,
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-09-01T12:00:00Z",
    updated_at: "2026-09-10T12:00:00Z",
    version: 4,
    description: "Confirm the revised scope.",
    evidence_state: "accepted",
    origin_kind: "direct_principal",
    origin_evidence_ref: null,
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: null,
    closure_history_id: null,
    commitment_id: null,
    role: null,
    project_id: "prj_aaaaaaaa11111111",
    situation_id: null,
    opened_at: "2026-09-01T12:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function renderSections(overrides: Partial<TaskDetail> = {}, props: Record<string, unknown> = {}) {
  const record = task(overrides);
  const handlers = {
    onTitleChange: vi.fn(),
    onTitleSave: vi.fn(),
    onPriorityChange: vi.fn(),
    onDescriptionChange: vi.fn(),
    onDescriptionSave: vi.fn(),
    onPlannedForChange: vi.fn(),
    onSnoozedUntilChange: vi.fn(),
    onArchivedChange: vi.fn(),
  };
  render(
    <TaskDetailSections
      model={toTaskPresentationModel(record, { clock: CLOCK, canMutate: true })}
      task={record}
      clock={CLOCK}
      title={record.title}
      titleDirty={false}
      priority={record.priority}
      description={record.description ?? ""}
      descriptionDirty={false}
      disabled={false}
      pending={false}
      statusControl={<div data-testid="slot-status">status slot</div>}
      dueControl={<div data-testid="slot-due">due slot</div>}
      closeControl={<div data-testid="slot-close">close slot</div>}
      comments={<div data-testid="slot-comments">comments slot</div>}
      technicalDetails={<div data-testid="slot-technical">technical slot</div>}
      projectLabel={null}
      situationLabel={null}
      commitmentLabel="No commitment linked"
      roleLabel="No role set"
      {...handlers}
      {...props}
    />,
  );
  return { record, ...handlers };
}

describe("progressive Task detail", () => {
  it("keeps Summary and Description & Activity primary and expanded", () => {
    renderSections();
    expect(screen.getByRole("heading", { name: "Summary" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Description & Activity" })).toBeTruthy();
    // Primary content is visible without any disclosure interaction.
    expect(screen.getByTestId("slot-status")).toBeTruthy();
    expect(screen.getByTestId("slot-due")).toBeTruthy();
    expect(screen.getByTestId("slot-close")).toBeTruthy();
    expect(screen.getByTestId("slot-comments")).toBeTruthy();
    expect(screen.getByDisplayValue("Confirm the revised scope.")).toBeTruthy();
  });

  it("collapses Planning, Context and Administrative by default", () => {
    renderSections();
    for (const id of ["task-planning-section", "task-context-section", "task-administrative-section"]) {
      expect(screen.getByTestId(id).hasAttribute("open")).toBe(false);
    }
  });

  it("opens a progressive section on demand", async () => {
    const user = userEvent.setup();
    renderSections();
    await user.click(screen.getByText("Planning"));
    expect(screen.getByTestId("task-planning-section").hasAttribute("open")).toBe(true);
    expect(screen.getByLabelText("Planned for")).toBeTruthy();
    expect(screen.getByLabelText("Snoozed until")).toBeTruthy();
  });

  it("uses product language for planning fields rather than backend field names", async () => {
    const user = userEvent.setup();
    renderSections();
    await user.click(screen.getByText("Planning"));
    const planning = screen.getByTestId("task-planning-section");
    expect(planning.textContent).not.toMatch(/scheduled_at|deferred_until/);
    expect(planning.textContent).toContain("Planned for");
    expect(planning.textContent).toContain("Snoozed until");
  });

  it("states missing Context rather than guessing a name or printing a raw reference", async () => {
    const user = userEvent.setup();
    renderSections();
    await user.click(screen.getByText("Context"));
    const context = screen.getByTestId("task-context-section");
    expect(within(context).getByText("Project details unavailable")).toBeTruthy();
    expect(within(context).getByText("Situation details unavailable")).toBeTruthy();
    expect(context.textContent).not.toContain("prj_aaaaaaaa11111111");
  });

  it("shows a human Context label when one is available", async () => {
    const user = userEvent.setup();
    renderSections({}, { projectLabel: "Riverside permit" });
    await user.click(screen.getByText("Context"));
    expect(within(screen.getByTestId("task-context-section")).getByText("Riverside permit")).toBeTruthy();
  });

  it("offers priority in product language, including an explicit absence", () => {
    renderSections();
    const priority = screen.getByLabelText("Priority") as HTMLSelectElement;
    const labels = Array.from(priority.options).map((option) => option.textContent);
    expect(labels).toEqual(["No priority", "Critical", "High", "Medium", "Low"]);
    expect(labels.join(" ")).not.toMatch(/p[1-4]/);
  });

  it("emits a bounded priority intent, and an explicit clear when unset", async () => {
    const user = userEvent.setup();
    const { onPriorityChange } = renderSections();
    await user.selectOptions(screen.getByLabelText("Priority"), "p1");
    expect(onPriorityChange).toHaveBeenCalledWith("p1");
    await user.selectOptions(screen.getByLabelText("Priority"), "");
    expect(onPriorityChange).toHaveBeenLastCalledWith(null);
  });

  it("offers a bounded save only once a field is dirty", async () => {
    const user = userEvent.setup();
    const { onTitleSave } = renderSections({}, { titleDirty: false });
    expect(screen.queryByRole("button", { name: "Save title" })).toBeNull();

    cleanup();
    renderSections({}, { titleDirty: true, onTitleSave });
    await user.click(screen.getByRole("button", { name: "Save title" }));
    expect(onTitleSave).toHaveBeenCalledTimes(1);
  });

  it("never renders a whole-Task atomic patch or generic lifecycle form", () => {
    renderSections();
    expect(screen.queryByRole("button", { name: /atomic patch/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Apply transition/i })).toBeNull();
    expect(screen.queryByLabelText("Move to")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Lifecycle" })).toBeNull();
  });

  it("replaces the Close affordance with a terminal summary once the Task is closed", () => {
    renderSections({ lifecycle_state: "completed", closed_at: "2026-09-11T12:00:00Z" });
    expect(screen.getByTestId("task-terminal-summary").textContent).toBe("This task is closed.");
    expect(screen.queryByTestId("slot-close")).toBeNull();
  });

  it("distinguishes a cancelled Task from a closed one", () => {
    renderSections({ lifecycle_state: "cancelled" });
    expect(screen.getByTestId("task-terminal-summary").textContent).toBe("This task is cancelled.");
  });

  it("places Archive under Administrative rather than in ordinary operation", async () => {
    const user = userEvent.setup();
    const { onArchivedChange } = renderSections();
    // jsdom does not hide collapsed <details> content from queries, so the
    // disclosure state itself is the proof that Archive is not in ordinary operation.
    expect(screen.getByTestId("task-administrative-section").hasAttribute("open")).toBe(false);
    await user.click(screen.getByText("Administrative"));
    expect(screen.getByTestId("task-administrative-section").hasAttribute("open")).toBe(true);
    await user.click(screen.getByLabelText("Archived"));
    expect(onArchivedChange).toHaveBeenCalledWith(true);
  });

  it("renders exactly one technical disclosure slot, last", () => {
    renderSections();
    const root = screen.getByTestId("task-detail-sections");
    const technical = screen.getByTestId("slot-technical");
    expect(root.lastElementChild).toBe(technical);
    expect(screen.queryAllByTestId("slot-technical")).toHaveLength(1);
  });
});
