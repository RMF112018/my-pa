import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Sheet } from "@/components/ui/sheet";

afterEach(cleanup);

describe("Sheet titleVisibility", () => {
  it("keeps the default title visible", () => {
    render(
      <Sheet open onOpenChange={() => undefined} title="Inspector">
        Body
      </Sheet>,
    );

    const heading = screen.getByRole("heading", { name: "Inspector" });
    expect(heading).toBeVisible();
    expect(heading.classList.contains("sr-only")).toBe(false);
  });

  it("exposes an accessible dialog name when the title is screen-reader only", () => {
    render(
      <Sheet
        open
        onOpenChange={() => undefined}
        title="Task title"
        titleVisibility="sr-only"
      >
        Body
      </Sheet>,
    );

    expect(screen.getByRole("dialog", { name: "Task title" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Task title" }).classList.contains("sr-only")).toBe(
      true,
    );
  });

  it("marks menu and detail placements distinctly", () => {
    const { rerender } = render(
      <Sheet open onOpenChange={() => undefined} title="Account" placement="menu">
        Menu sheet
      </Sheet>,
    );
    expect(screen.getByRole("dialog").getAttribute("data-placement")).toBe("menu");

    rerender(
      <Sheet open onOpenChange={() => undefined} title="Work detail" placement="detail">
        Detail sheet
      </Sheet>,
    );
    expect(screen.getByRole("dialog").getAttribute("data-placement")).toBe("detail");
  });

  it("closes on Escape when no inline confirmation is open", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(
      <Sheet open onOpenChange={onOpenChange} title="Task detail" placement="detail">
        Body
      </Sheet>,
    );

    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not close on Escape while an inline alertdialog confirmation is open", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(
      <Sheet open onOpenChange={onOpenChange} title="Task detail" placement="detail">
        <div role="alertdialog" aria-labelledby="confirm-title">
          <p id="confirm-title">Close Task</p>
          <button type="button">Keep open</button>
        </div>
      </Sheet>,
    );

    screen.getByRole("button", { name: "Keep open" }).focus();
    await user.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Task detail" })).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});
