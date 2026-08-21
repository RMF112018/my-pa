import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { EpistemicLabel, type EpistemicRole } from "@/components/ui/epistemic-label";
import { RichContent, safeHref } from "@/components/ui/rich-content";

afterEach(cleanup);

describe("safe rich content", () => {
  it("allows only the admitted semantic node and URL schemes", () => {
    expect(safeHref("https://example.test/evidence")).toBe("https://example.test/evidence");
    expect(safeHref("mailto:synthetic@example.test")).toBe("mailto:synthetic@example.test");
    expect(safeHref("/knowledge/record-1")).toBe("/knowledge/record-1");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,unsafe")).toBeNull();

    const { container } = render(
      <RichContent
        nodes={[
          { type: "heading", text: "Synthetic evidence" },
          { type: "paragraph", text: "<script>not markup</script>" },
          { type: "link", text: "Allowed", href: "https://example.test/evidence" },
          { type: "link", text: "Blocked", href: "javascript:alert(1)" },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "Allowed" })).toHaveAttribute(
      "href",
      "https://example.test/evidence",
    );
    expect(screen.queryByRole("link", { name: "Blocked" })).toBeNull();
    expect(screen.getByText("Blocked").tagName).toBe("SPAN");
    expect(container.querySelector("script, iframe")).toBeNull();
  });
});

describe("epistemic grammar", () => {
  it("renders every governed role with text and non-color structure", async () => {
    const roles: EpistemicRole[] = [
      "source",
      "ai-derived",
      "user-confirmed",
      "canonical",
      "proposed",
      "needs-review",
      "ambiguous",
      "conflicted",
      "stale",
      "superseded",
      "unavailable",
      "pipeline-incomplete",
    ];
    const { container } = render(
      <div>
        {roles.map((role) => (
          <EpistemicLabel key={role} role={role} />
        ))}
      </div>,
    );

    for (const role of roles) {
      const label = container.querySelector(`[data-epistemic-role="${role}"]`);
      expect(label).not.toBeNull();
      expect(label?.querySelector("svg")).not.toBeNull();
      expect(label?.textContent?.trim()).not.toBe("");
    }
    expect((await axe.run(container)).violations).toEqual([]);
  });
});
