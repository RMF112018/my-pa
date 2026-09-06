// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesNotebooksList } from "./goodnotes.notebooks.list";

export const NOTEBOOK = {
  notebook_id: "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa",
  title: "Synthetic notebook",
  updated_at: "2026-08-09T12:00:00.000Z",
  page_count: 2,
  liveness: "unknown",
};

describe("decodeGoodNotesNotebooksList", () => {
  it("accepts a Python-derived page", () => {
    const decoded = decodeGoodNotesNotebooksList({ notebooks: [NOTEBOOK], next_cursor: "cursor" });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.next_cursor).toBe("cursor");
  });

  it("accepts an omitted next_cursor", () => {
    const decoded = decodeGoodNotesNotebooksList({ notebooks: [NOTEBOOK] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value).not.toHaveProperty("next_cursor");
  });

  it("ignores unknown extra fields", () => {
    expect(
      decodeGoodNotesNotebooksList({ notebooks: [{ ...NOTEBOOK, extra: 1 }], path: "/secret" }).ok,
    ).toBe(true);
  });

  it("fails closed when notebooks is omitted", () => {
    expect(decodeGoodNotesNotebooksList({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeGoodNotesNotebooksList({}).ok).toBe(false);
    const empty = decodeGoodNotesNotebooksList({ notebooks: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.notebooks).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesNotebooksList({ notebooks: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { title: _, ...rest } = NOTEBOOK;
    expect(decodeGoodNotesNotebooksList({ notebooks: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid liveness value", () => {
    expect(
      decodeGoodNotesNotebooksList({ notebooks: [{ ...NOTEBOOK, liveness: "unavailable" }] }).ok,
    ).toBe(false);
  });
});
