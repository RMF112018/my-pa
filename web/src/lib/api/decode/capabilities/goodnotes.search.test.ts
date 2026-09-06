// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesSearch } from "./goodnotes.search";

export const HIT = {
  kind: "notebook",
  id: "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa",
  title: "Synthetic notebook",
  snippet: "synthetic notebook",
  notebook_id: "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa",
  logical_page_id: null,
  page_version_id: null,
  run_id: null,
  freshness: "2026-08-09T12:00:00.000Z",
};

describe("decodeGoodNotesSearch", () => {
  it("accepts a Python-derived page with nullable identifiers", () => {
    const decoded = decodeGoodNotesSearch({ hits: [HIT] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.hits[0]?.logical_page_id).toBeNull();
      expect(decoded.value.hits[0]?.id).toBe(HIT.id);
    }
  });

  it("ignores unknown extra fields", () => {
    expect(decodeGoodNotesSearch({ hits: [{ ...HIT, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when hits is omitted", () => {
    expect(decodeGoodNotesSearch({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeGoodNotesSearch({}).ok).toBe(false);
    const empty = decodeGoodNotesSearch({ hits: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.hits).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesSearch({ hits: 1 }).ok).toBe(false);
  });

  it("fails closed when a required string is missing", () => {
    const { title: _, ...rest } = HIT;
    expect(decodeGoodNotesSearch({ hits: [rest] }).ok).toBe(false);
  });

  it("fails closed when an identifier key is omitted rather than null", () => {
    const { notebook_id: _, ...rest } = HIT;
    expect(decodeGoodNotesSearch({ hits: [rest] }).ok).toBe(false);
  });
});
