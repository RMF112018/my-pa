// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsSearch } from "./reports.search";

const MATCH = {
  report_id: "rpt_aaaaaaaa11111111",
  title: "E2E morning brief collector",
  snippet: "morning brief",
  cycle_run_id: "micr_aaaaaaaa11111111",
  stage: "collector",
  artifact_kind: "collector_candidates",
};

describe("decodeReportsSearch", () => {
  it("accepts a Python-derived success payload", () => {
    expect(decodeReportsSearch({ items: [MATCH] }).ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeReportsSearch({ items: [{ ...MATCH, extra: 1 }], noise: true }).ok).toBe(true);
  });

  it("fails closed when items is omitted", () => {
    expect(decodeReportsSearch({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeReportsSearch({}).ok).toBe(false);
    const empty = decodeReportsSearch({ items: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.items).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeReportsSearch({ items: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { snippet: _, ...rest } = MATCH;
    expect(decodeReportsSearch({ items: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeReportsSearch({ items: [{ ...MATCH, stage: "planner" }] }).ok).toBe(false);
  });
});
