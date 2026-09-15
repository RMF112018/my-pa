import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  TaskDetailSections,
  type TaskContextFact,
  type TaskDetailSectionsProps,
} from "@/components/tasks/task-detail-sections";
import type { TaskDetail } from "@/contracts/work";
import { toTaskPresentationModel, type TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(cleanup);

const CLOCK: TaskCivilClock = { timezone: "America/New_York", workDate: "2026-09-12" };

const DEFAULT_CONTEXT: {
  project: TaskContextFact;
  situation: TaskContextFact;
  commitment: TaskContextFact;
  role: TaskContextFact;
} = {
  project: { state: "unavailable", message: "Project details unavailable" },
  situation: { state: "unavailable", message: "Situation details unavailable" },
  commitment: { state: "absent", message: "No commitment linked" },
  role: { state: "ready", label: "No role set" },
};

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

function slotProps() {
  return {
    statusControl: <div data-testid="slot-status">status slot</div>,
    dueControl: <div data-testid="slot-due">due slot</div>,
    closeControl: <div data-testid="slot-close">close slot</div>,
    refreshControl: <div data-testid="slot-refresh">refresh slot</div>,
    comments: <div data-testid="slot-comments">comments slot</div>,
    technicalDetails: <div data-testid="slot-technical">technical slot</div>,
  };
}

function renderSections(
  overrides: Partial<TaskDetail> = {},
  props: Partial<TaskDetailSectionsProps> = {},
) {
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
    onContextOpen: vi.fn(),
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
      {...DEFAULT_CONTEXT}
      {...slotProps()}
      {...handlers}
      {...props}
    />,
  );
  return { record, ...handlers };
}

function renderStateful(overrides: Partial<TaskDetail> = {}) {
  const record = task(overrides);
  const onTitleSave = vi.fn();
  const onDescriptionSave = vi.fn();
  const onPriorityChange = vi.fn();

  function Harness() {
    const [title, setTitle] = useState(record.title);
    const [description, setDescription] = useState(record.description ?? "");
    return (
      <TaskDetailSections
        model={toTaskPresentationModel(record, { clock: CLOCK, canMutate: true })}
        task={record}
        clock={CLOCK}
        title={title}
        titleDirty={title !== record.title}
        priority={record.priority}
        description={description}
        descriptionDirty={description !== (record.description ?? "")}
        disabled={false}
        pending={false}
        {...DEFAULT_CONTEXT}
        {...slotProps()}
        onTitleChange={setTitle}
        onTitleSave={onTitleSave}
        onPriorityChange={onPriorityChange}
        onDescriptionChange={setDescription}
        onDescriptionSave={onDescriptionSave}
        onPlannedForChange={vi.fn()}
        onSnoozedUntilChange={vi.fn()}
        onArchivedChange={vi.fn()}
      />
    );
  }

  render(<Harness />);
  return { record, onTitleSave, onDescriptionSave, onPriorityChange };
}

describe("progressive Task detail", () => {
  it("keeps Summary and Description primary and read-first", () => {
    renderSections();
    expect(screen.getByTestId("task-summary")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Coordinate the review" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Description" })).toBeTruthy();
    expect(screen.getByText("Confirm the revised scope.")).toBeTruthy();
    expect(screen.getByTestId("slot-status")).toBeTruthy();
    expect(screen.getByTestId("slot-due")).toBeTruthy();
    expect(screen.getByTestId("slot-close")).toBeTruthy();
    expect(screen.getByTestId("slot-comments")).toBeTruthy();

    expect(screen.queryByLabelText("Title")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByTestId("task-edit-title")).toBeTruthy();
    expect(screen.getByTestId("task-edit-priority")).toBeTruthy();
    expect(screen.getByTestId("task-edit-description")).toBeTruthy();
    expect(screen.queryByTestId("task-add-description")).toBeNull();
  });

  it("offers Add description when the Task has none", () => {
    renderSections({ description: null }, { description: "" });
    expect(screen.getByText("No description.")).toBeTruthy();
    expect(screen.getByTestId("task-add-description")).toBeTruthy();
    expect(screen.queryByTestId("task-edit-description")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("collapses Planning, Context and Administrative by default", () => {
    renderSections();
    for (const id of ["task-planning-section", "task-context-section", "task-administrative-section"]) {
      expect(screen.getByTestId(id).hasAttribute("open")).toBe(false);
    }
  });

  it("opens Planning as read-first, then Edit planning reveals date fields", async () => {
    const user = userEvent.setup();
    renderSections();
    await user.click(screen.getByText("Planning"));
    expect(screen.getByTestId("task-planning-section").hasAttribute("open")).toBe(true);
    expect(screen.getByText("Not planned")).toBeTruthy();
    expect(screen.getByText("Not snoozed")).toBeTruthy();
    expect(screen.queryByLabelText("Planned for")).toBeNull();
    expect(screen.queryByLabelText("Snoozed until")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Edit planning" }));
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
    renderSections({}, { project: { state: "ready", label: "Riverside permit" } });
    await user.click(screen.getByText("Context"));
    expect(within(screen.getByTestId("task-context-section")).getByText("Riverside permit")).toBeTruthy();
  });

  it("loads Context facts only on the first open", async () => {
    const user = userEvent.setup();
    const { onContextOpen } = renderSections();
    expect(onContextOpen).not.toHaveBeenCalled();
    await user.click(screen.getByText("Context"));
    expect(onContextOpen).toHaveBeenCalledTimes(1);
    await user.click(screen.getByText("Context"));
    await user.click(screen.getByText("Context"));
    expect(onContextOpen).toHaveBeenCalledTimes(1);
  });

  it("offers priority in product language, including an explicit absence", async () => {
    const user = userEvent.setup();
    renderSections();
    expect(screen.getByText("High")).toBeTruthy();
    expect(screen.queryByLabelText("Priority")).toBeNull();

    await user.click(screen.getByTestId("task-edit-priority"));
    const priority = screen.getByLabelText("Priority") as HTMLSelectElement;
    const labels = Array.from(priority.options).map((option) => option.textContent);
    expect(labels).toEqual(["No priority", "Critical", "High", "Medium", "Low"]);
    expect(labels.join(" ")).not.toMatch(/p[1-4]/);
  });

  it("emits a bounded priority intent, and an explicit clear when unset", async () => {
    const user = userEvent.setup();
    const { onPriorityChange } = renderSections();
    await user.click(screen.getByTestId("task-edit-priority"));
    await user.selectOptions(screen.getByLabelText("Priority"), "p1");
    expect(onPriorityChange).toHaveBeenCalledWith("p1");

    await user.click(screen.getByTestId("task-edit-priority"));
    await user.selectOptions(screen.getByLabelText("Priority"), "");
    expect(onPriorityChange).toHaveBeenLastCalledWith(null);
  });

  it("saves a title only after Edit title, and Cancel restores the committed title", async () => {
    const user = userEvent.setup();
    const { onTitleSave } = renderStateful();
    expect(screen.queryByRole("button", { name: "Save title" })).toBeNull();

    await user.click(screen.getByTestId("task-edit-title"));
    const field = screen.getByLabelText("Title");
    expect(field).toHaveFocus();
    await user.clear(field);
    await user.type(field, "Revised review title");
    await user.click(screen.getByRole("button", { name: "Save title" }));
    expect(onTitleSave).toHaveBeenCalledTimes(1);
    expect(screen.getByDisplayValue("Revised review title")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Title")).toBeNull();
    expect(screen.getByRole("heading", { name: "Coordinate the review" })).toBeTruthy();
    expect(screen.getByTestId("task-edit-title")).toHaveFocus();
  });

  it("closes an unsubmitted title editor on Escape and restores focus", async () => {
    const user = userEvent.setup();
    renderStateful();
    await user.click(screen.getByTestId("task-edit-title"));
    await user.type(screen.getByLabelText("Title"), " extra");
    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText("Title")).toBeNull();
    expect(screen.getByRole("heading", { name: "Coordinate the review" })).toBeTruthy();
    expect(screen.getByTestId("task-edit-title")).toHaveFocus();
  });

  it("saves a description after Edit, and Cancel restores the committed text", async () => {
    const user = userEvent.setup();
    const { onDescriptionSave } = renderStateful();
    await user.click(screen.getByTestId("task-edit-description"));
    const field = screen.getByRole("textbox", { name: "Description" });
    expect(field).toHaveFocus();
    await user.clear(field);
    await user.type(field, "Updated scope notes.");
    await user.click(screen.getByRole("button", { name: "Save description" }));
    expect(onDescriptionSave).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "Description" })).toBeNull();
    expect(screen.getByText("Confirm the revised scope.")).toBeTruthy();
    expect(screen.getByTestId("task-edit-description")).toHaveFocus();
  });

  it("closes an unsubmitted description editor on Escape and restores focus", async () => {
    const user = userEvent.setup();
    renderStateful();
    await user.click(screen.getByTestId("task-edit-description"));
    await user.type(screen.getByRole("textbox", { name: "Description" }), " extra");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "Description" })).toBeNull();
    expect(screen.getByText("Confirm the revised scope.")).toBeTruthy();
    expect(screen.getByTestId("task-edit-description")).toHaveFocus();
  });

  it("restores Add description after cancelling an empty description editor", async () => {
    const user = userEvent.setup();
    renderStateful({ description: null });
    await user.click(screen.getByTestId("task-add-description"));
    await user.type(screen.getByRole("textbox", { name: "Description" }), "scratch");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "Description" })).toBeNull();
    expect(screen.getByTestId("task-add-description")).toHaveFocus();
  });

  it("never renders a whole-Task atomic patch or generic lifecycle form", () => {
    renderSections();
    expect(screen.queryByRole("button", { name: /atomic patch/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Apply transition/i })).toBeNull();
    expect(screen.queryByLabelText("Move to")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Lifecycle" })).toBeNull();
  });

  it("places Cancel and Refresh under More, with Close immediate", () => {
    renderSections({}, { onCancelTask: vi.fn() });
    expect(screen.getByTestId("slot-close")).toBeTruthy();
    expect(screen.getByTestId("task-more-actions")).toBeTruthy();
    expect(within(screen.getByTestId("task-more-actions")).getByTestId("task-cancel-trigger")).toBeTruthy();
    expect(within(screen.getByTestId("task-more-actions")).getByTestId("slot-refresh")).toBeTruthy();
  });

  it("replaces the Close affordance with a terminal summary once the Task is closed", () => {
    renderSections({ lifecycle_state: "completed", closed_at: "2026-09-11T12:00:00Z" }, { onCancelTask: vi.fn() });
    expect(screen.getByTestId("task-terminal-summary").textContent).toBe("This task is closed.");
    expect(screen.queryByTestId("slot-close")).toBeNull();
    expect(screen.queryByTestId("slot-status")).toBeNull();
    expect(screen.queryByTestId("slot-due")).toBeNull();
    expect(screen.queryByTestId("task-cancel-trigger")).toBeNull();
    expect(within(screen.getByTestId("task-more-actions")).getByTestId("slot-refresh")).toBeTruthy();
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
