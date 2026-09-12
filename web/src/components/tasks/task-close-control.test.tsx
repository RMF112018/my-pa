import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskCloseControl } from "@/components/tasks/task-close-control";

afterEach(() => {
  cleanup();
});

const TASK_TITLE = "Renew the passport";

function renderControl(overrides: Partial<Parameters<typeof TaskCloseControl>[0]> = {}) {
  const onClose = vi.fn();
  const onCancelTask = vi.fn();
  const props = {
    taskTitle: TASK_TITLE,
    onClose,
    onCancelTask,
    ...overrides,
  };
  const view = render(<TaskCloseControl {...props} />);
  return { ...view, onClose, onCancelTask, props };
}

const closeTrigger = () => screen.getByRole("button", { name: "Close Task" });
const cancelTrigger = () => screen.getByRole("button", { name: "Cancel Task" });

describe("TaskCloseControl", () => {
  it("does not close on the first activation: it only opens a confirmation", async () => {
    const user = userEvent.setup();
    const { onClose } = renderControl();

    await user.click(closeTrigger());

    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("names the Task in the confirmation", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.click(closeTrigger());

    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent(TASK_TITLE);
    const describedBy = dialog.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy as string)?.textContent).toContain(TASK_TITLE);
    const labelledBy = dialog.getAttribute("aria-labelledby");
    expect(document.getElementById(labelledBy as string)).toBeTruthy();
  });

  it("calls onClose exactly once when Confirm Closed is activated", async () => {
    const user = userEvent.setup();
    const { onClose, onCancelTask } = renderControl();

    await user.click(closeTrigger());
    await user.click(screen.getByRole("button", { name: "Confirm Closed" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onCancelTask).not.toHaveBeenCalled();
  });

  it("summons no keyboard: the confirmation contains no text entry at all", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.click(closeTrigger());

    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(dialog.querySelector("input")).toBeNull();
    expect(dialog.querySelector("textarea")).toBeNull();
  });

  it("moves initial focus to the non-destructive Keep open button", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.click(closeTrigger());

    const keepOpen = screen.getByRole("button", { name: "Keep open" });
    expect(document.activeElement).toBe(keepOpen);
    expect(document.activeElement).not.toBe(
      screen.getByRole("button", { name: "Confirm Closed" }),
    );
    expect((document.activeElement as HTMLElement).tagName).toBe("BUTTON");
  });

  it("dismisses on Escape without acting and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    const { onClose } = renderControl();

    const trigger = closeTrigger();
    await user.click(trigger);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it("dismisses on Keep open without acting", async () => {
    const user = userEvent.setup();
    const { onClose, onCancelTask } = renderControl();

    const trigger = closeTrigger();
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "Keep open" }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(onCancelTask).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it("gives Cancel Task its own confirmation with its own cancelled copy", async () => {
    const user = userEvent.setup();
    const { onClose, onCancelTask } = renderControl();

    await user.click(cancelTrigger());

    const dialog = screen.getByRole("alertdialog");
    const description = document.getElementById(
      dialog.getAttribute("aria-describedby") as string,
    );
    expect(description?.textContent).toContain("cancelled");
    expect(description?.textContent).not.toMatch(/will be closed/);
    expect(within(dialog).queryByRole("button", { name: "Confirm Closed" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Confirm Cancelled" }));

    expect(onCancelTask).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps the two confirmations mutually exclusive", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.click(closeTrigger());
    expect(screen.getByRole("button", { name: "Confirm Closed" })).toBeTruthy();

    await user.click(cancelTrigger());
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Confirm Closed" })).toBeNull();
    expect(screen.getByRole("button", { name: "Confirm Cancelled" })).toBeTruthy();
  });

  it("renders Cancel Task at lower prominence than Close Task, and after it", () => {
    renderControl();

    const close = closeTrigger();
    const cancel = cancelTrigger();

    expect(close).toHaveAttribute("data-prominence", "primary");
    expect(cancel).toHaveAttribute("data-prominence", "secondary");
    expect(cancel.className).not.toBe(close.className);
    expect(close.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Accessible names stay semantically distinct: never both just "Cancel".
    expect(close.textContent).toBe("Close Task");
    expect(cancel.textContent).toBe("Cancel Task");
  });

  it("disables the confirm button while pending so it cannot be activated twice", async () => {
    const user = userEvent.setup();
    const { onClose, rerender, props } = renderControl();

    await user.click(closeTrigger());
    await user.click(screen.getByRole("button", { name: "Confirm Closed" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<TaskCloseControl {...props} pending />);

    const confirm = screen.getByRole("button", { name: /Confirm Closed/ });
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute("aria-busy", "true");
    await user.click(confirm);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("prevents the confirmation from opening at all when disabled", async () => {
    const user = userEvent.setup();
    const { onClose, onCancelTask } = renderControl({ disabled: true });

    expect(closeTrigger()).toBeDisabled();
    expect(cancelTrigger()).toBeDisabled();

    await user.click(closeTrigger());
    await user.click(cancelTrigger());

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(onCancelTask).not.toHaveBeenCalled();
  });

  it("offers no Reopen control anywhere", async () => {
    const user = userEvent.setup();
    renderControl();

    expect(screen.queryByRole("button", { name: /reopen/i })).toBeNull();
    expect(screen.getByTestId("task-close-control").textContent).not.toMatch(/reopen/i);

    await user.click(closeTrigger());
    expect(screen.queryByRole("button", { name: /reopen/i })).toBeNull();
    expect(screen.getByTestId("task-close-control").textContent).not.toMatch(/reopen/i);
  });

  it("gives every interactive control a 44px touch target", () => {
    renderControl();
    for (const button of screen.getAllByRole("button")) {
      expect(button.className).toContain("min-h-11");
      expect(button.className).toContain("min-w-11");
    }
  });

  it("hides Cancel Task when the surface has no room for it", () => {
    renderControl({ showCancel: false });
    expect(screen.queryByRole("button", { name: "Cancel Task" })).toBeNull();
    expect(closeTrigger()).toBeTruthy();
  });
});
