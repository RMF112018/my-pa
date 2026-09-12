import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TaskCompact } from "@/components/tasks/task-compact";
import type { TaskRow } from "@/contracts/work";
import {
  toTaskPresentationModel,
  type TaskCivilClock,
  type TaskPresentationModel,
} from "@/lib/tasks/presentation";

afterEach(cleanup);

const clock: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-12" };

function taskRow(overrides: Partial<TaskRow> = {}): TaskRow {
  return {
    task_id: "task-abc-123",
    title: "Send the revised scope to the client",
    lifecycle_state: "in_progress",
    priority: null,
    due_at: "2026-09-12T15:00:00Z",
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-09-10T09:00:00Z",
    version: 4,
    ...overrides,
  };
}

function model(overrides: Partial<TaskRow> = {}): TaskPresentationModel {
  return toTaskPresentationModel(taskRow(overrides), { clock, canMutate: true });
}

describe("TaskCompact", () => {
  it("renders title, human due phrase, human status label and supplied actions", () => {
    render(
      <TaskCompact
        model={model()}
        actions={
          <button type="button">
            Close Task
          </button>
        }
      />,
    );

    expect(screen.getByText("Send the revised scope to the client")).toBeTruthy();
    expect(screen.getByText("Today")).toBeTruthy();
    expect(screen.getByText("In progress")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Close Task" })).toBeTruthy();
  });

  it("renders no priority at all when the Task has none, and never says Low", () => {
    render(<TaskCompact model={model({ priority: null })} />);

    expect(screen.queryByText("Low")).toBeNull();
    expect(screen.queryByText("No priority")).toBeNull();
    expect(screen.getByTestId("task-compact").textContent).not.toMatch(/Low|priority/i);
  });

  it("renders the human priority label for p1 and never the raw token", () => {
    render(<TaskCompact model={model({ priority: "p1" })} />);

    expect(screen.getByText("Critical")).toBeTruthy();
    expect(screen.getByTestId("task-compact").textContent).not.toContain("p1");
  });

  it("never leaks a raw lifecycle or priority token as text", () => {
    render(
      <TaskCompact
        model={model({ lifecycle_state: "completed", priority: "p2", due_at: null })}
      />,
    );

    expect(screen.getByText("Closed")).toBeTruthy();
    expect(screen.getByText("High")).toBeTruthy();
    expect(screen.getByTestId("task-compact").textContent ?? "").not.toMatch(
      /in_progress|completed|cancelled|p[1-4]\b/,
    );
  });

  it("does not render the Task ID as visible text", () => {
    render(<TaskCompact model={model()} href="/work/tasks/task-abc-123" />);

    const unit = screen.getByTestId("task-compact");
    expect(unit.getAttribute("data-task-id")).toBe("task-abc-123");
    expect(unit.textContent ?? "").not.toContain("task-abc-123");
    expect(screen.queryByText("task-abc-123")).toBeNull();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/work/tasks/task-abc-123");
  });

  it("clamps the title to one line when dense and two lines otherwise", () => {
    const { rerender } = render(<TaskCompact model={model()} dense />);
    expect(screen.getByText("Send the revised scope to the client").className).toContain(
      "line-clamp-1",
    );

    rerender(<TaskCompact model={model()} />);
    expect(screen.getByText("Send the revised scope to the client").className).toContain(
      "line-clamp-2",
    );
  });

  it("does not convey status by colour alone — the status label text is always present", () => {
    render(<TaskCompact model={model({ lifecycle_state: "blocked" })} />);

    const label = screen.getByText("Blocked");
    expect(label).toBeTruthy();
    expect(label.textContent).toBe("Blocked");
  });

  it("ellipsizes a single-line context label and renders the overflow slot", () => {
    const withContext = toTaskPresentationModel(taskRow(), {
      clock,
      contextLabel: "Northwind rebuild",
    });
    render(
      <TaskCompact
        model={withContext}
        overflow={<button type="button">More</button>}
      />,
    );

    expect(screen.getByText("Northwind rebuild").className).toContain("truncate");
    expect(screen.getByRole("button", { name: "More" })).toBeTruthy();
  });
});
