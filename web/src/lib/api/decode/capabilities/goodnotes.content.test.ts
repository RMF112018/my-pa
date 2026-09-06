// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeGoodNotesContent } from "./goodnotes.content";

export const CONTENT_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR42mP4DwABAQEAHLCMmQAAAABJRU5ErkJggg==";

export const CONTENT = {
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
  content_sha256: "a".repeat(64),
  exact_render_sha256: "b".repeat(64),
  media_type: "image/png",
  byte_length: 67,
  digest: "c".repeat(64),
  content_base64: CONTENT_PNG_BASE64,
  renderer_name: "synthetic",
  renderer_version: "1",
  render_profile_version: "v1",
};

describe("decodeGoodNotesContent", () => {
  it("accepts a Python content_payload", () => {
    const decoded = decodeGoodNotesContent(CONTENT);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.media_type).toBe("image/png");
  });

  it("ignores unknown extra fields including a path", () => {
    const decoded = decodeGoodNotesContent({ ...CONTENT, path: "/secret/note.png" });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value).not.toHaveProperty("path");
  });

  it("fails closed when media_type is not image/png", () => {
    expect(decodeGoodNotesContent({ ...CONTENT, media_type: "application/pdf" }).ok).toBe(false);
  });

  it("fails closed when byte_length is not greater than 0", () => {
    expect(decodeGoodNotesContent({ ...CONTENT, byte_length: 0 }).ok).toBe(false);
  });

  it("fails closed when a digest is not 64 lowercase hex", () => {
    expect(decodeGoodNotesContent({ ...CONTENT, digest: "A".repeat(64) }).ok).toBe(false);
  });

  it("fails closed when content_base64 is omitted", () => {
    const { content_base64: _, ...rest } = CONTENT;
    expect(decodeGoodNotesContent(rest).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeGoodNotesContent({ pulse_items: 1 }).ok).toBe(false);
  });
});
