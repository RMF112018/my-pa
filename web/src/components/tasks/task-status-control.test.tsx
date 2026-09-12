import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskStatusControl } from "@/components/tasks/task-status-control";

afterEach(() => {
  cleanup();
});

const CONFLICT_COPY = "This task changed elsewhere. Review the latest version before saving.";

describe("TaskStatusControl", () => {
  it("offers exactly the four active statuses in human language", () => {
    render(<TaskStatusControl value="open" onChange={() => {}} />);

    const select = screen.getByRole("combobox", { name: "Status" });
    const options = within(select).getAllByRole("option");

    expect(options).toHaveLength(4);
    expect(options.map((option) => option.textContent)).toEqual([
      "Open",
      "In progress",
      "Waiting",
      "Blocked",
    ]);
    expect(screen.getByTestId("task-status-control").textContent ?? "").not.toMatch(
      /in_progress|p1|lifecycle/i,
    );
  });

  it("emits the raw active token while displaying only human text", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TaskStatusControl value="open" onChange={onChange} />);

    const select = screen.getByRole("combobox", { name: "Status" });
    await user.selectOptions(select, "in_progress");

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("in_progress");
    expect(screen.getByRole("option", { name: "In progress" })).toBeInTheDocument();
    expect(screen.queryByText("in_progress")).toBeNull();
  });

  it("states a terminal status in words and offers no status editing", () => {
    render(<TaskStatusControl value="completed" onChange={() => {}} />);

    expect(screen.getByTestId("task-status-control")).toHaveTextContent("Closed");
    expect(screen.queryByRole("combobox")).toBeNull();

    cleanup();
    render(<TaskStatusControl value="cancelled" onChange={() => {}} />);
    expect(screen.getByTestId("task-status-control")).toHaveTextContent("Cancelled");
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("blocks change while disabled and marks itself busy while pending", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <TaskStatusControl value="open" disabled onChange={onChange} />,
    );

    const select = screen.getByRole("combobox", { name: "Status" });
    expect(select).toBeDisabled();
    await user.click(select);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("task-status-control")).not.toHaveAttribute("aria-busy");

    rerender(<TaskStatusControl value="open" pending onChange={onChange} />);
    expect(screen.getByRole("combobox", { name: "Status" })).toBeDisabled();
    expect(screen.getByTestId("task-status-control")).toHaveAttribute("aria-busy", "true");
  });

  it("describes the control with the conflict copy when the version drifted", () => {
    render(<TaskStatusControl value="open" conflict onChange={() => {}} />);

    const select = screen.getByRole("combobox", { name: "Status" });
    const describedBy = select.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();

    const note = document.getElementById(describedBy ?? "");
    expect(note).not.toBeNull();
    expect(note).toHaveTextContent(CONFLICT_COPY);
  });

  it("is reachable and operable by keyboard", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TaskStatusControl value="open" onChange={onChange} />);

    const select = screen.getByRole("combobox", { name: "Status" });
    await user.tab();
    expect(select).toHaveFocus();
    expect(select.tagName).toBe("SELECT");

    await user.selectOptions(select, "blocked");
    expect(onChange).toHaveBeenCalledWith("blocked");
  });
});
