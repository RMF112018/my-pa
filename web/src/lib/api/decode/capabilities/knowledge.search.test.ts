// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeKnowledgeSearch } from "./knowledge.search";

const MATCH = {
  knowledge_id: "knw_aaaa0001aaaa0001aaaa0001",
  label: "text/plain",
  snippet: "synthetic snippet",
  rank: "strong",
  source_id: "src_aaaa0001aaaa0001aaaa0001",
  source_object_id: "sobj_aaaa0001aaaa0001aaaa0001",
  version_id: "ver_aaaa0001aaaa0001aaaa0001",
};

describe("decodeKnowledgeSearch", () => {
  it("accepts a Python-derived success payload", () => {
    const decoded = decodeKnowledgeSearch({ matches: [MATCH] });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeKnowledgeSearch({ matches: [{ ...MATCH, extra: 1 }], noise: true }).ok).toBe(true);
  });

  it("fails closed when matches is omitted", () => {
    expect(decodeKnowledgeSearch({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeKnowledgeSearch({}).ok).toBe(false);
    const empty = decodeKnowledgeSearch({ matches: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.matches).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeKnowledgeSearch({ matches: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { snippet: _, ...rest } = MATCH;
    expect(decodeKnowledgeSearch({ matches: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeKnowledgeSearch({ matches: [{ ...MATCH, rank: 0.9 }] }).ok).toBe(false);
    expect(decodeKnowledgeSearch({ matches: [{ ...MATCH, rank: "excellent" }] }).ok).toBe(false);
  });
});
