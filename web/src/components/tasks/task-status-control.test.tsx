import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskStatusControl } from "@/components/tasks/task-status-control";

afterEach(() => {
  cleanup();
});

const CONFLICT_COPY = "This task changed elsewhere. Review the latest version before saving.";

/**
 * Acceptance traceability: TASK-AC-002, TASK-AC-015, TASK-AC-017, TASK-AC-043.
 *
 * Exactly the four active statuses, named in human language, with the raw token emitted only
 * to the wire (002, 043); the control is the inline Status affordance the list, detail and
 * Board rows all mount (015), it is reachable and operable by keyboard, and it pins the
 * definite 44px sizing contract the Board acceptance run measures (017).
 */
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
   * controls are real touch targets", measured on **macOS** WebKit: 106x22
   * before the fix, 106x44 after. That is the only measurement that is evidence
   * *for this fix*, because macOS WebKit is the only engine where the defect
   * reproduces. Chromium reports 119x44 — but it reports 119x44 with the fix
   * removed too, so it is blind to this defect by construction, as are the
   * Linux CI builds of every engine.
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

  /**
   * WP-POSTUX-03 presentation seam: `labelVisibility`.
   *
   * The default must be bit-for-bit today's rendering — Board, Calendar, Task
   * Detail and Search all mount this control and none of them opts in.
   * `"sr-only"` hides the label visually only (WP03-AC-053) and must not touch
   * the definite 44px sizing contract (WP03-AC-054).
   */
  it("defaults to a visually shown label with no screen-reader-only treatment", () => {
    render(<TaskStatusControl value="open" onChange={() => {}} />);

    const select = screen.getByRole("combobox", { name: "Status" });
    const label = document.querySelector(`label[for="${select.id}"]`);
    expect(label).not.toBeNull();
    expect(label).toHaveTextContent("Status");
    expect(label?.classList.contains("sr-only")).toBe(false);
    expect(label?.classList.contains("text-text-muted")).toBe(true);
  });

  it("keeps the label element, its association and the accessible name under sr-only", () => {
    render(<TaskStatusControl value="open" labelVisibility="sr-only" onChange={() => {}} />);

    // The accessible name still resolves through the real label association.
    const select = screen.getByRole("combobox", { name: "Status" });
    expect(select.id).toBeTruthy();

    const label = document.querySelector(`label[for="${select.id}"]`);
    expect(label).not.toBeNull();
    expect(label?.tagName).toBe("LABEL");
    expect(label).toHaveTextContent("Status");
    // Hidden visually only: still in the DOM, never `hidden`/`aria-hidden`.
    expect(label?.classList.contains("sr-only")).toBe(true);
    expect(label).not.toHaveAttribute("hidden");
    expect(label).not.toHaveAttribute("aria-hidden");

    // The sizing contract is untouched by the presentation seam.
    expect(select.classList.contains("h-11")).toBe(true);
    expect(select.classList.contains("min-h-11")).toBe(true);
    expect(select.classList.contains("min-w-11")).toBe(true);
  });

  it("keeps the terminal state semantically labelled under sr-only", () => {
    render(<TaskStatusControl value="completed" labelVisibility="sr-only" onChange={() => {}} />);

    const control = screen.getByTestId("task-status-control");
    expect(control).toHaveAttribute("data-terminal", "true");
    // The field label text stays available to assistive technology, and so
    // does the terminal state itself.
    expect(control).toHaveTextContent("Status");
    expect(control).toHaveTextContent("Closed");

    const labelText = screen.getByText("Status");
    expect(labelText.classList.contains("sr-only")).toBe(true);
    expect(labelText).not.toHaveAttribute("aria-hidden");
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
