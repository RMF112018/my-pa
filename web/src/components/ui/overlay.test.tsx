import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dialog } from "@/components/ui/dialog";
import { Sheet } from "@/components/ui/sheet";

afterEach(cleanup);

describe("overlay close targets and dismissal", () => {
  it("gives the dialog close control a 44px minimum target and restores closed state", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Dialog open title="Capture" onClose={onClose}>
        <p>Synthetic overlay body</p>
      </Dialog>,
    );
    const close = screen.getByRole("button", { name: "Close dialog" });
    expect(close.className).toMatch(/min-h-11/);
    expect(close.className).toMatch(/min-w-11/);
    await user.click(close);
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the sheet close control at the shared 44px target", () => {
    render(
      <Sheet open onOpenChange={() => undefined} title="Inspector" placement="inspector">
        Synthetic sheet
      </Sheet>,
    );
    const close = screen.getByRole("button", { name: "Close panel" });
    expect(close.className).toMatch(/min-h-11/);
    expect(close.className).toMatch(/min-w-11/);
    expect(screen.getByRole("dialog").getAttribute("data-placement")).toBe("inspector");
  });

  it("closes from Escape even when a search field holds a query", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Dialog open title="Search" onClose={onClose}>
        <input type="search" aria-label="Search" defaultValue="morning brief" />
      </Dialog>,
    );
    screen.getByRole("searchbox", { name: "Search" }).focus();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
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
});
