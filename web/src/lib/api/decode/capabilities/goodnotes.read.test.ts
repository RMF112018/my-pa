// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesRead } from "./goodnotes.read";

const DIGEST = "a".repeat(64);

export const READ = {
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
  content_sha256: DIGEST,
  exact_render_sha256: "b".repeat(64),
  raster_digest: "c".repeat(64),
  media_type: "image/png",
  renderer_name: "synthetic",
  renderer_version: "1",
  render_profile_version: "v1",
  interpretation: {
    authority: "interpretation",
    items: [
      {
        proposal_id: "gnprp_aaaaaaaaaaaaaaaaaaaaaaaa",
        analyzer_name: "synthetic",
        analyzer_version: "1",
        schema_version: "note-unit.v1",
        disposition: null,
        extra: "ignored",
      },
      {
        occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
        revision_id: "gnrev_aaaaaaaaaaaaaaaaaaaaaaaa",
        analyzer_name: "synthetic",
        analyzer_version: "1",
        schema_version: "note-unit.v1",
        transcription: "synthetic note",
      },
    ],
  },
  provenance: {
    run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
    page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
    content_sha256: DIGEST,
  },
  processing: { run_status: null, failure_class: null },
};

describe("decodeGoodNotesRead", () => {
  it("accepts a Python-derived page and ignores extra item keys", () => {
    const decoded = decodeGoodNotesRead(READ);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.interpretation.items[0]).not.toHaveProperty("extra");
      expect(decoded.value.interpretation.items[1]?.transcription).toBe("synthetic note");
    }
  });

  it("fails closed when interpretation items are omitted", () => {
    expect(
      decodeGoodNotesRead({ ...READ, interpretation: { authority: "source" } }).ok,
    ).toBe(false);
  });

  it("fails closed on an invalid authority", () => {
    expect(
      decodeGoodNotesRead({
        ...READ,
        interpretation: { authority: "canonical", items: [] },
      }).ok,
    ).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { raster_digest: _, ...rest } = READ;
    expect(decodeGoodNotesRead(rest).ok).toBe(false);
  });

  it("fails closed when a digest is not 64 lowercase hex", () => {
    expect(decodeGoodNotesRead({ ...READ, content_sha256: "A".repeat(64) }).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesRead({ pulse_items: 1 }).ok).toBe(false);
  });
});
