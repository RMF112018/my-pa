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

  /**
   * The 44px sizing contract, pinned at the source.
   *
   * **This is not browser-rendering proof and must never be read as such.**
   * jsdom lays nothing out, so this asserts only that the control still carries
   * the definite block height the fix introduced. The geometry itself — that the
   * rendered box really is at least 44 CSS px tall — is proved in Playwright by
   * `e2e/work-acceptance.spec.ts`, "TASK-AC-017 the Board Status and Due
   * controls are real touch targets", measured on **macOS** WebKit (106x22
   * before the fix, 106x44 after) and on Chromium.
   *
   * Be careful which browser evidence you credit. The Linux Playwright builds
   * used in CI render this control 44px tall *with or without* the fix, because
   * they honour `min-height` on a native select and `ui/select.tsx` already
   * carries `min-h-[var(--control-height)]`. A green WebKit or Firefox run in
   * the advisory `frontend / browsers` lane therefore says nothing about this
   * defect — it was measured passing on a branch with the fix removed. This
   * assertion, in the blocking `frontend / unit` job, is what actually fails
   * when the definite height is dropped.
   *
   * Why a definite `h-11` rather than `min-h-11` alone: macOS WebKit does not
   * honour `min-height` on a default-appearance `<select>` — it resolves it
   * down to the intrinsic ~18px — and the control rendered 22 CSS px there. The
   * native select is deliberately kept — no `appearance-none`, no custom
   * combobox — so the height has to be stated outright.
   */
  it("keeps a native select and pins the definite 44px sizing contract", () => {
    render(<TaskStatusControl value="open" onChange={() => {}} />);

    const select = screen.getByRole("combobox", { name: "Status" });
    expect(select.tagName).toBe("SELECT");

    // `h-11` is 2.75rem = 44px, the same target `--control-height` names.
    expect(select.classList.contains("h-11")).toBe(true);
    expect(select.classList.contains("min-h-11")).toBe(true);
    expect(select.classList.contains("min-w-11")).toBe(true);
    // The native control is preserved: nothing strips its platform appearance.
    expect(select.classList.contains("appearance-none")).toBe(false);
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
