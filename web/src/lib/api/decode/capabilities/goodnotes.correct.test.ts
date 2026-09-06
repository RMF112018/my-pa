// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesCorrect } from "./goodnotes.correct";

export const CORRECT = {
  occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
  revision_id: "gnrev_aaaaaaaaaaaaaaaaaaaaaaaa",
  prior_revision_id: "gnrev_bbbbbbbbbbbbbbbbbbbbbbbb",
  replayed: false,
  disposition: "canonical_revision_appended",
};

describe("decodeGoodNotesCorrect", () => {
  it("accepts a Python-derived correction receipt", () => {
    const decoded = decodeGoodNotesCorrect(CORRECT);
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeGoodNotesCorrect({ ...CORRECT, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when a required field is missing", () => {
    const { revision_id: _, ...rest } = CORRECT;
    expect(decodeGoodNotesCorrect(rest).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesCorrect({ ...CORRECT, replayed: "false" }).ok).toBe(false);
  });

  it("fails closed on an invalid disposition", () => {
    expect(decodeGoodNotesCorrect({ ...CORRECT, disposition: "accepted" }).ok).toBe(false);
  });
});
