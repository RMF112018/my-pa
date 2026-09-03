// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeKnowledgeRead } from "./knowledge.read";

const VALID = {
  knowledge_id: "knw_aaaa0001aaaa0001aaaa0001",
  label: "text/plain",
  media_type: "text/plain",
  character_count: 12,
  metadata_only: false,
  is_truncated: false,
  provenance: {
    source_id: "src_aaaa0001aaaa0001aaaa0001",
    source_object_id: "sobj_aaaa0001aaaa0001aaaa0001",
    version_id: "ver_aaaa0001aaaa0001aaaa0001",
    extractor: "plain_text",
    extractor_version: "1",
    trust_level: "source_original",
    observed_at: "2026-01-01T00:00:00Z",
    processed_at: "2026-01-01T00:00:00Z",
  },
  text: "hello world",
};

describe("decodeKnowledgeRead", () => {
  it("accepts a Python-derived success payload with optional text", () => {
    const decoded = decodeKnowledgeRead(VALID);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.text).toBe("hello world");
  });

  it("accepts metadata-only without text", () => {
    const { text: _, ...rest } = VALID;
    const decoded = decodeKnowledgeRead({ ...rest, metadata_only: true });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.text).toBeUndefined();
  });

  it("ignores unknown extra fields", () => {
    expect(decodeKnowledgeRead({ ...VALID, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when a required field is missing", () => {
    const { knowledge_id: _, ...rest } = VALID;
    expect(decodeKnowledgeRead(rest).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeKnowledgeRead({ ...VALID, character_count: "12" }).ok).toBe(false);
  });

  it("fails closed when provenance is omitted", () => {
    const { provenance: _, ...rest } = VALID;
    expect(decodeKnowledgeRead(rest).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeKnowledgeRead({
        ...VALID,
        provenance: { ...VALID.provenance, trust_level: "derived" },
      }).ok,
    ).toBe(false);
  });
});
