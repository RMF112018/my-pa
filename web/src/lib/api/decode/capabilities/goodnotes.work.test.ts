// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesWork } from "./goodnotes.work";

export const WORK = {
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
  content_sha256: "a".repeat(64),
  logical_page_id: "gnlp_aaaaaaaaaaaaaaaaaaaaaaaa",
  renderer_name: "synthetic",
  renderer_version: "1",
  render_profile_version: "v1",
};

describe("decodeGoodNotesWork", () => {
  it("accepts a Python work_payload", () => {
    const decoded = decodeGoodNotesWork(WORK);
    expect(decoded.ok).toBe(true);
  });

  it("accepts null renderer and logical_page fields", () => {
    const decoded = decodeGoodNotesWork({
      ...WORK,
      logical_page_id: null,
      renderer_name: null,
      renderer_version: null,
      render_profile_version: null,
    });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeGoodNotesWork({ ...WORK, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when a required field is missing", () => {
    const { content_sha256: _, ...rest } = WORK;
    expect(decodeGoodNotesWork(rest).ok).toBe(false);
  });

  it("fails closed when content_sha256 is not 64 lowercase hex", () => {
    expect(decodeGoodNotesWork({ ...WORK, content_sha256: "A".repeat(64) }).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesWork({ pulse_items: 1 }).ok).toBe(false);
  });
});
