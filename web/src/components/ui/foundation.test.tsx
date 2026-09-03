import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { EpistemicLabel, type EpistemicRole } from "@/components/ui/epistemic-label";
import { RichContent, safeHref } from "@/components/ui/rich-content";
import { safeHref as centralSafeHref } from "@/lib/http/safe-href";

afterEach(cleanup);

describe("safe rich content", () => {
  it("uses the WP05 fail-closed href boundary", () => {
    expect(safeHref).toBe(centralSafeHref);
    expect(safeHref("https://example.test/evidence")).toBe("https://example.test/evidence");
    expect(safeHref("/knowledge/record-1")).toBe("/knowledge/record-1");
    expect(safeHref("mailto:synthetic@example.test")).toBeNull();
    expect(safeHref("http://example.test/x")).toBeNull();
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,unsafe")).toBeNull();
  });

  it("renders the allowlisted vocabulary and ignores unknown nodes", () => {
    const { container } = render(
      <RichContent
        nodes={[
          { type: "heading", text: "Synthetic evidence" },
          { type: "paragraph", text: "<script>not markup</script>" },
          { type: "emphasis", text: "emphasized" },
          { type: "strong", text: "strong" },
          { type: "list", ordered: true, items: ["First", { text: "Second", children: ["Nested"] }] },
          {
            type: "table",
            caption: "Coverage",
            headers: ["Source", "State"],
            rows: [["Capture", "accepted"]],
          },
          {
            type: "figure",
            caption: "Evidence figure",
            alt: "Synthetic crop",
            src: "https://example.test/crop.png",
          },
          { type: "link", text: "Allowed", href: "https://example.test/evidence" },
          { type: "link", text: "Blocked", href: "javascript:alert(1)" },
          { type: "link", text: "Mail", href: "mailto:synthetic@example.test" },
          { type: "script", text: "dropped" } as unknown as Parameters<
            typeof RichContent
          >[0]["nodes"][number],
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Synthetic evidence", level: 2 })).toBeTruthy();
    expect(screen.getByText("<script>not markup</script>").tagName).toBe("P");
    expect(screen.getByText("emphasized").tagName).toBe("EM");
    expect(screen.getByText("strong").tagName).toBe("STRONG");
    expect(container.querySelector("ol")).not.toBeNull();
    expect(screen.getByRole("table", { name: "Coverage" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Synthetic crop" })).toHaveAttribute(
      "src",
      "https://example.test/crop.png",
    );
    expect(screen.getByRole("link", { name: "Allowed" })).toHaveAttribute(
      "href",
      "https://example.test/evidence",
    );
    expect(screen.getByRole("link", { name: "Allowed" })).toHaveAttribute("rel", "noreferrer");
    expect(screen.queryByRole("link", { name: "Blocked" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Mail" })).toBeNull();
    expect(screen.queryByText("dropped")).toBeNull();
    expect(container.querySelector("script, iframe")).toBeNull();
  });

  it("marks AI-derived rich text separately from source evidence", () => {
    render(
      <RichContent
        nodes={[
          { type: "paragraph", text: "Source excerpt", epistemic: "source" },
          { type: "paragraph", text: "Model summary", epistemic: "ai-derived" },
        ]}
      />,
    );
    expect(document.querySelector('[data-epistemic-content="source"]')).not.toBeNull();
    expect(document.querySelector('[data-epistemic-content="ai-derived"]')).not.toBeNull();
    expect(document.querySelector('[data-epistemic-role="ai-derived"]')).not.toBeNull();
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
