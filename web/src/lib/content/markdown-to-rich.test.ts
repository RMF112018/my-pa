import { describe, expect, it } from "vitest";
import { markdownToRich } from "@/lib/content/markdown-to-rich";

describe("markdownToRich", () => {
  it("turns scraped markdown into RichContent text, never Brief item IDs", () => {
    const nodes = markdownToRich("# Morning Brief\n\n- scraped item one\n- scraped item two");
    expect(nodes).toEqual([
      { type: "heading", text: "Morning Brief", level: 2 },
      { type: "list", ordered: false, items: ["scraped item one", "scraped item two"] },
    ]);
    const serialized = JSON.stringify(nodes);
    expect(serialized).toContain("scraped item one");
    expect(serialized).not.toMatch(/item_id|section_id|brief-item|brief_item/i);
    expect(nodes.some((node) => "items" in node && Array.isArray(node.items) && node.items.includes("scraped item one"))).toBe(
      true,
    );
  });

  it("admits ATX headings, paragraphs, lists, and safe sole-line links", () => {
    const nodes = markdownToRich(
      [
        "## Focus",
        "",
        "A paragraph of secondary body.",
        "",
        "1. first",
        "2. second",
        "",
        "[Evidence](https://example.test/evidence)",
        "",
        "[Internal](/intelligence/reports/rpt_aaaaaaaa11111111)",
      ].join("\n"),
    );
    expect(nodes).toEqual([
      { type: "heading", text: "Focus", level: 2 },
      { type: "paragraph", text: "A paragraph of secondary body." },
      { type: "list", ordered: true, items: ["first", "second"] },
      { type: "link", text: "Evidence", href: "https://example.test/evidence" },
      {
        type: "link",
        text: "Internal",
        href: "/intelligence/reports/rpt_aaaaaaaa11111111",
      },
    ]);
  });

  it("omits raw HTML, scripts, images, fences, and rejected hrefs fail-closed", () => {
    const nodes = markdownToRich(
      [
        "<script>alert(1)</script>",
        "<p>kept as text if tags strip to words</p>",
        "",
        "![x](javascript:alert(1))",
        "<img src=\"javascript:alert(1)\">",
        "",
        "```",
        "secret fence",
        "```",
        "",
        "[Bad](javascript:alert(1))",
        "",
        "[Mail](mailto:synthetic@example.test)",
        "",
        "[Proto](http://example.test/x)",
      ].join("\n"),
    );
    const serialized = JSON.stringify(nodes);
    expect(serialized).not.toMatch(/script|javascript:|secret fence|<img/i);
    expect(nodes.find((node) => node.type === "link")).toBeUndefined();
    expect(nodes.some((node) => node.type === "paragraph" && node.text.includes("kept as text"))).toBe(
      true,
    );
    expect(nodes.some((node) => node.type === "paragraph" && node.text === "Bad")).toBe(true);
    expect(nodes.some((node) => node.type === "paragraph" && node.text === "Mail")).toBe(true);
  });

  it("does not throw on malformed input and does not invent item schema", () => {
    expect(markdownToRich("")).toEqual([]);
    expect(markdownToRich("<div>")).toEqual([]);
    expect(() => markdownToRich("***\n\n> quote\n\n|| table")).not.toThrow();
    const nodes = markdownToRich("***\n\n> quote\n\n|| table");
    expect(JSON.stringify(nodes)).not.toMatch(/section_id|item_id/);
  });
});
