import { describe, expect, it } from "vitest";
import { classifyForbiddenLevel1Copy, collectLevel1Copy } from "@/lib/ui/user-copy";

describe("Level-1 product language", () => {
  it("flags doctrine terms on non-System surfaces", () => {
    const hits = classifyForbiddenLevel1Copy(
      "The Principal plane is the canonical gateway; a worker replayed it with a coverage token and idempotency.",
    );
    expect(hits).toEqual(
      expect.arrayContaining([
        "Principal",
        "plane",
        "canonical",
        "gateway",
        "worker",
        "replayed",
        "coverage token",
        "idempotency",
      ]),
    );
  });

  it("flags artifact only when the claim is about storage", () => {
    expect(classifyForbiddenLevel1Copy("this artifact is a briefing")).toEqual([]);
    expect(classifyForbiddenLevel1Copy("the artifact was persisted to storage")).toEqual(
      expect.arrayContaining(["artifact", "persisted"]),
    );
  });

  it("does not scan System surfaces", () => {
    expect(
      classifyForbiddenLevel1Copy("gateway worker Principal coverage token", "system"),
    ).toEqual([]);
  });

  it("flags Retry Work read", () => {
    expect(classifyForbiddenLevel1Copy("Retry Work read")).toContain("Retry Work read");
  });

  it("collectLevel1Copy drops Details so plane/artifact diagnostics are not scored as Level-1", () => {
    const root = document.createElement("div");
    root.innerHTML =
      "<p>No briefings yet.</p><details><summary>Details</summary><p>The report plane was read incompletely.</p></details>";
    const level1 = collectLevel1Copy(root);
    expect(level1).toMatch(/no briefings yet/i);
    expect(level1).not.toMatch(/\bplane\b/i);
    expect(classifyForbiddenLevel1Copy(level1)).toEqual([]);
  });
});
