import { describe, expect, it } from "vitest";
import { intelligenceHistory, intelligenceHome, intelligenceReport } from "@/lib/routes/intelligence";

describe("intelligence routes", () => {
  it("freezes the working-surface paths without a clock-dated brief route", () => {
    expect(intelligenceHome()).toBe("/intelligence");
    expect(intelligenceHistory()).toBe("/intelligence/history");
    expect(intelligenceHistory("micr_aaaaaaaa11111111")).toBe(
      "/intelligence/history?cycleRunId=micr_aaaaaaaa11111111",
    );
    expect(intelligenceReport("rpt_aaaaaaaa11111111")).toBe(
      "/intelligence/reports/rpt_aaaaaaaa11111111",
    );
  });
});
