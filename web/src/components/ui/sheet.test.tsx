import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

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
});
