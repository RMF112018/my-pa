import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvidenceSplit } from "@/components/goodnotes/evidence-split";

describe("EvidenceSplit", () => {
  it("keeps a mobile tablist and an md side-by-side grid in the same tree", () => {
    render(
      <EvidenceSplit
        source={<p>source pane</p>}
        interpretation={<p>interpretation pane</p>}
      />,
    );
    const tablist = screen.getByTestId("goodnotes-evidence-tablist");
    expect(tablist).toHaveAttribute("role", "tablist");
    expect(tablist.className).toMatch(/md:hidden/);
    expect(screen.getByRole("tab", { name: "Source" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Interpretation" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    const split = screen.getByTestId("goodnotes-evidence-split");
    expect(split.className).toContain("md:grid-cols-2");
    expect(screen.getByRole("tab", { name: "Source" }).className).toMatch(/min-h-11/);
    expect(screen.getByRole("tab", { name: "Interpretation" }).className).toMatch(/min-h-11/);
  });

  it("switches the mobile pane without inventing a second shell", async () => {
    render(
      <EvidenceSplit
        source={<p>source pane</p>}
        interpretation={<p>interpretation pane</p>}
      />,
    );
    await userEvent.click(screen.getByRole("tab", { name: "Interpretation" }));
    expect(screen.getByRole("tab", { name: "Interpretation" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(document.querySelector("#goodnotes-panel-interpretation")?.className).toContain("block");
    expect(screen.queryByRole("heading", { name: "Assistant" })).toBeNull();
  });
});
