// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsList } from "./reports.list";

const ITEM = {
  report_id: "rpt_aaaaaaaa11111111",
  cycle_run_id: "micr_aaaaaaaa11111111",
  stage: "collector",
  artifact_kind: "collector_candidates",
  focus_area_id: "communications",
  source_lane: null,
  title: "E2E morning brief collector",
  content_sha256: "a".repeat(64),
  artifact_state: "final",
};

describe("decodeReportsList", () => {
  it("accepts a Python-derived success payload", () => {
    const decoded = decodeReportsList({ items: [ITEM], next_cursor: null });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.next_cursor).toBeNull();
  });

  it("ignores unknown extra fields", () => {
    expect(decodeReportsList({ items: [{ ...ITEM, extra: 1 }], next_cursor: null, noise: true }).ok).toBe(
      true,
    );
  });

  it("fails closed when items is omitted", () => {
    expect(decodeReportsList({ next_cursor: null }).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeReportsList({}).ok).toBe(false);
    const empty = decodeReportsList({ items: [], next_cursor: null });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.items).toEqual([]);
  });

  it("fails closed when next_cursor is omitted", () => {
    expect(decodeReportsList({ items: [ITEM] }).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeReportsList({ items: 1, next_cursor: null }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { title: _, ...rest } = ITEM;
    expect(decodeReportsList({ items: [rest], next_cursor: null }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeReportsList({ items: [{ ...ITEM, artifact_kind: "brief" }], next_cursor: null }).ok,
    ).toBe(false);
  });
});
