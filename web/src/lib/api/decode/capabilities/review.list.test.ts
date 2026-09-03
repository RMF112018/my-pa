// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReviewList } from "./review.list";

const CAPTURE_CASE = {
  review_case_id: "rvc_aaaa0001aaaa0001aaaa0001",
  proposal_id: "prop_aaaa0001aaaa0001aaaa0001",
  proposal_state: "proposed",
  risk_class: "high",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 3,
  latest_disposition: null,
  subject_kind: "capture_proposal",
  capture_id: "cap_aaaa0001aaaa0001aaaa0001",
  version_id: "capver_aaaa0001aaaa0001aaaa0001",
  proposal_type: "commitment",
};

const MEMORY_CASE = {
  review_case_id: "rvc_bbbb0001bbbb0001bbbb0001",
  proposal_id: "prop_bbbb0001bbbb0001bbbb0001",
  proposal_state: "needs_review",
  risk_class: "critical",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 1,
  latest_disposition: null,
  subject_kind: "relationship_memory",
  subject_entity_id: "ent_aaaa0001aaaa0001aaaa0001",
  proposed_kind: "sensitivity",
  accepted_memory_id: null,
  accepted_memory_version_id: null,
};

describe("decodeReviewList", () => {
  it("accepts polymorphic Python-derived cases", () => {
    const decoded = decodeReviewList({ review_cases: [CAPTURE_CASE, MEMORY_CASE] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.review_cases).toHaveLength(2);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeReviewList({ review_cases: [{ ...CAPTURE_CASE, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when review_cases is omitted", () => {
    expect(decodeReviewList({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeReviewList({}).ok).toBe(false);
    const empty = decodeReviewList({ review_cases: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.review_cases).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeReviewList({ review_cases: 1 }).ok).toBe(false);
  });

  it("fails closed when a kind-required field is missing", () => {
    const { capture_id: _, ...rest } = CAPTURE_CASE;
    expect(decodeReviewList({ review_cases: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeReviewList({ review_cases: [{ ...CAPTURE_CASE, subject_kind: "note" }] }).ok,
    ).toBe(false);
    expect(
      decodeReviewList({ review_cases: [{ ...CAPTURE_CASE, proposal_type: "task" }] }).ok,
    ).toBe(false);
  });
});
