// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesPagesList } from "./goodnotes.pages.list";

export const PAGE = {
  logical_page_id: "gnlp_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  content_sha256: "a".repeat(64),
  is_latest: true,
  updated_at: "2026-08-09T12:00:00.000Z",
};

describe("decodeGoodNotesPagesList", () => {
  it("accepts a Python-derived page", () => {
    const decoded = decodeGoodNotesPagesList({ pages: [PAGE] });
    expect(decoded.ok).toBe(true);
  });

  it("accepts a null run_id", () => {
    const decoded = decodeGoodNotesPagesList({ pages: [{ ...PAGE, run_id: null }] });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeGoodNotesPagesList({ pages: [{ ...PAGE, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when pages is omitted", () => {
    expect(decodeGoodNotesPagesList({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeGoodNotesPagesList({}).ok).toBe(false);
    const empty = decodeGoodNotesPagesList({ pages: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.pages).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesPagesList({ pages: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { content_sha256: _, ...rest } = PAGE;
    expect(decodeGoodNotesPagesList({ pages: [rest] }).ok).toBe(false);
  });

  it("fails closed when content_sha256 is not 64 lowercase hex", () => {
    expect(
      decodeGoodNotesPagesList({ pages: [{ ...PAGE, content_sha256: "A".repeat(64) }] }).ok,
    ).toBe(false);
  });
});
