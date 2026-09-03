// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeKnowledgeReveal } from "./knowledge.reveal";

const DIGEST = "b".repeat(64);
const AT = "2026-08-09T12:00:00.000Z";

function unavailable(overrides: Record<string, unknown> = {}) {
  return {
    subject_id: "cap_aaaaaaaa11111111",
    subject_kind: null,
    state: "unavailable",
    gap: "subject_kind_is_outside_the_evidence_model",
    capture_id: null,
    versions: [],
    spans: [],
    proposed: [],
    accepted: [],
    versions_with_completed_derivation: 0,
    ...overrides,
  };
}

function span(overrides: Record<string, unknown> = {}) {
  return {
    span_id: "span_aaaaaaaa11111111",
    version_id: "capver_aaaaaaaa11111111",
    start_offset: 0,
    end_offset: 4,
    offset_basis: "unicode_code_point_v1",
    line_start: 1,
    column_start: 1,
    line_end: 1,
    column_end: 5,
    character_count: 4,
    quoted_text_sha256: DIGEST,
    span_role: "direct",
    mapping_version: null,
    ...overrides,
  };
}

function evidence() {
  return unavailable({
    state: "evidence",
    gap: null,
    subject_kind: "capture",
    capture_id: "cap_aaaaaaaa11111111",
    versions: [
      {
        version_id: "capver_aaaaaaaa11111111",
        capture_id: "cap_aaaaaaaa11111111",
        version_number: 1,
        is_current: true,
        content_sha256: DIGEST,
        recorded_at: AT,
        derivation_state: "complete",
        derivation_is_complete: true,
      },
    ],
    spans: [span()],
    proposed: [],
    accepted: [],
    versions_with_completed_derivation: 1,
  });
}

describe("decodeKnowledgeReveal", () => {
  it("accepts a Python RevealView with evidence", () => {
    const decoded = decodeKnowledgeReveal(evidence());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.state).toBe("evidence");
  });

  it("treats state=unavailable as success", () => {
    const decoded = decodeKnowledgeReveal(unavailable());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.state).toBe("unavailable");
      expect(decoded.value.gap).toBe("subject_kind_is_outside_the_evidence_model");
    }
  });

  it("fails closed on an unknown state", () => {
    expect(decodeKnowledgeReveal(unavailable({ state: "empty" })).ok).toBe(false);
  });

  it("fails closed when a required array is omitted", () => {
    const { spans: _, ...rest } = evidence();
    expect(decodeKnowledgeReveal(rest).ok).toBe(false);
  });

  it("fails closed when gap is missing on unavailable", () => {
    const { gap: _, ...rest } = unavailable();
    expect(decodeKnowledgeReveal(rest).ok).toBe(false);
  });

  it("fails closed on an invalid span role enum", () => {
    expect(decodeKnowledgeReveal(evidence()).ok).toBe(true);
    const bad = evidence();
    (bad.spans as Record<string, unknown>[])[0] = span({ span_role: "quote" });
    expect(decodeKnowledgeReveal(bad).ok).toBe(false);
  });

  it("fails closed when subject_id is the wrong type", () => {
    expect(decodeKnowledgeReveal(unavailable({ subject_id: 1 })).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeKnowledgeReveal(unavailable({ extra_reveal_field: true })).ok).toBe(true);
  });
});
