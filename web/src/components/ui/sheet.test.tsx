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

function classTokens(element: Element): string[] {
  return element.className.split(/\s+/).filter(Boolean);
}

/*
  WP09 corrective. `viewport-fit=cover` moves `top: 0` to the physical screen
  top, so every `fixed` edge-anchored surface now needs its own inset handling;
  `Sheet` had none. These assertions pin the exact tokens rather than merely
  looking for the substring `env(` — the substring is what let the inertia in
  `mutation-feedback` survive review.

  Limitation stated honestly: jsdom neither compiles Tailwind nor resolves
  `env()`/`max()`, so nothing here proves the rendered pixel offset at a
  non-zero inset. What it does prove is that the class contract carries an
  inset-aware token in every place that needs one, and carries no bare
  fixed-length token in those same places.
*/
describe("Sheet safe-area handling under viewport-fit=cover", () => {
  it("pads the detail placement clear of both the top and the bottom inset", () => {
    render(
      <Sheet open onOpenChange={() => undefined} title="Work detail" placement="detail">
        Body
      </Sheet>,
    );
    const tokens = classTokens(screen.getByRole("dialog"));
    expect(tokens).toContain("px-5");
    expect(tokens).toContain("pt-[max(1.25rem,env(safe-area-inset-top))]");
    expect(tokens).toContain("pb-[max(1.25rem,env(safe-area-inset-bottom))]");
    // The uniform shorthand cannot express an inset-aware edge, so it must go.
    expect(tokens).not.toContain("p-5");
  });

  it("pads the menu placement for the bottom inset, and for the top only where lg makes it a full-height rail", () => {
    render(
      <Sheet open onOpenChange={() => undefined} title="Account" placement="menu">
        Body
      </Sheet>,
    );
    const tokens = classTokens(screen.getByRole("dialog"));
    expect(tokens).toContain("px-5");
    expect(tokens).toContain("pb-[max(1.25rem,env(safe-area-inset-bottom))]");
    // Mobile: a bottom sheet never touches the notch, so no top inset is spent.
    expect(tokens).toContain("pt-5");
    // lg: `lg:inset-y-0` makes it reach the physical top.
    expect(tokens).toContain("lg:pt-[max(1.25rem,env(safe-area-inset-top))]");
    expect(tokens).not.toContain("p-5");
  });

  it("pads the inspector placement clear of both insets", () => {
    render(
      <Sheet open onOpenChange={() => undefined} title="Inspector" placement="inspector">
        Body
      </Sheet>,
    );
    const tokens = classTokens(screen.getByRole("dialog"));
    expect(tokens).toContain("px-5");
    expect(tokens).toContain("pt-[max(1.25rem,env(safe-area-inset-top))]");
    expect(tokens).toContain("pb-[max(1.25rem,env(safe-area-inset-bottom))]");
    expect(tokens).not.toContain("p-5");
  });

  it.each(["detail", "inspector"] as const)(
    "gives the close control its own inset-aware offset for the %s placement, because container padding cannot move an absolutely positioned box",
    (placement) => {
      render(
        <Sheet open onOpenChange={() => undefined} title="Panel" placement={placement}>
          Body
        </Sheet>,
      );
      const tokens = classTokens(screen.getByRole("button", { name: "Close panel" }));
      expect(tokens).toContain("absolute");
      expect(tokens).toContain("top-[max(0.75rem,env(safe-area-inset-top))]");
      // A bare `top-3` sits 12px from the physical screen top — under the notch.
      expect(tokens).not.toContain("top-3");
      // The 44px target survives the offset change.
      expect(tokens).toContain("min-h-11");
      expect(tokens).toContain("min-w-11");
    },
  );

  it("keeps the menu close control at a plain offset on mobile and insets it only at lg", () => {
    render(
      <Sheet open onOpenChange={() => undefined} title="Account" placement="menu">
        Body
      </Sheet>,
    );
    const tokens = classTokens(screen.getByRole("button", { name: "Close panel" }));
    // The mobile menu is bottom-anchored: its own top is nowhere near the notch.
    expect(tokens).toContain("top-3");
    expect(tokens).toContain("lg:top-[max(0.75rem,env(safe-area-inset-top))]");
  });
});
