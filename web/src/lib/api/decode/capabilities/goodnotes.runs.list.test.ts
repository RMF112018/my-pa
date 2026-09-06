// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesRunsList } from "./goodnotes.runs.list";

export const RUN = {
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  state: "succeeded",
  failure_class: null,
  started_at: "2026-08-09T12:00:00.000Z",
  completed_at: "2026-08-09T12:01:00.000Z",
};

describe("decodeGoodNotesRunsList", () => {
  it("accepts a Python-derived page", () => {
    const decoded = decodeGoodNotesRunsList({ runs: [RUN] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.runs[0]).not.toHaveProperty("page_version_id");
  });

  it("accepts an optional page_version_id", () => {
    const decoded = decodeGoodNotesRunsList({
      runs: [{ ...RUN, page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa" }],
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.runs[0]?.page_version_id).toBe("gnver_aaaaaaaaaaaaaaaaaaaaaaaa");
  });

  it("ignores unknown extra fields", () => {
    expect(decodeGoodNotesRunsList({ runs: [{ ...RUN, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when runs is omitted", () => {
    expect(decodeGoodNotesRunsList({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeGoodNotesRunsList({}).ok).toBe(false);
    const empty = decodeGoodNotesRunsList({ runs: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.runs).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesRunsList({ runs: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { state: _, ...rest } = RUN;
    expect(decodeGoodNotesRunsList({ runs: [rest] }).ok).toBe(false);
  });

  it("fails closed when completed_at is omitted", () => {
    const { completed_at: _, ...rest } = RUN;
    expect(decodeGoodNotesRunsList({ runs: [rest] }).ok).toBe(false);
  });
});
