import { describe, expect, it } from "vitest";
import { canvasHome, canvasMap } from "@/lib/routes/canvas";

describe("canvas routes", () => {
  it("freezes the Map home path", () => {
    expect(canvasHome()).toBe("/canvas");
  });

  it("treats an empty query as the home path", () => {
    expect(canvasMap()).toBe("/canvas");
    expect(canvasMap({})).toBe("/canvas");
  });

  it("includes a focus seed as focusEntityId", () => {
    const href = canvasMap({ focusEntityId: "ent_aaaaaaaa11111111" });
    expect(href).toContain("/canvas?");
    expect(href).toContain("focusEntityId=ent_aaaaaaaa11111111");
  });

  it("joins relationshipTypes with a comma", () => {
    const href = canvasMap({ relationshipTypes: ["works_for", "reports_to"] });
    const params = new URL(href, "http://canvas.test").searchParams;
    expect(params.get("relationshipTypes")).toBe("works_for,reports_to");
  });

  it("omits empty strings rather than emitting empty keys", () => {
    expect(canvasMap({ focusEntityId: "", asOf: "", after: "" })).toBe("/canvas");
    const href = canvasMap({
      focusEntityId: "",
      scopeEntityId: "ent_bbbbbbbb22222222",
      after: "",
    });
    const params = new URL(href, "http://canvas.test").searchParams;
    expect(params.get("scopeEntityId")).toBe("ent_bbbbbbbb22222222");
    expect(params.has("focusEntityId")).toBe(false);
    expect(params.has("after")).toBe(false);
  });
});
