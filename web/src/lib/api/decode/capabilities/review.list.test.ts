// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { decodeItems, requiredString } from "./_read-helpers";
import { decodeReviewDecide } from "./review.decide";
import { decodeReviewList } from "./review.list";

const FIXTURES = join(process.cwd(), "src/lib/api/decode/fixtures/python");

function fixture(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(FIXTURES, name), "utf8")) as Record<string, unknown>;
}

/**
 * The Python Knowledge `review.list` row (R6 section 10.1 keys plus the read-only
 * candidate of fix round 4, Manager ruling on DEV-83), as `review_case_view` emits it.
 */
const KNOWLEDGE_CASE = {
  current_assertion_id: "kasr_9c2e4f6a8b0c2e4f6a8b0c2e4f6a8b0c",
  current_value: "net 30",
  effective_from: "2026-10-04T12:00:00+00:00",
  effective_to: null,
  evidence_ref_ids: [
    "kaevd_1b0f3a7c9e2d4f6a8b0c2e4f6a8b0c2e",
    "kaevd_5d7f9b1d3f5a7c9e1b3d5f7a9c1e3b5d",
  ],
  qualifier: null,
  value: "net 60",
  value_type: "text",
  latest_disposition: null,
  opened_at: "2026-10-04T12:00:00.000Z",
  predicate_code: "organization.payment_terms",
  proposal_id: "kaprp_7a88c3d12e4066cd1e9f007ebf89c4b0",
  proposal_state: "needs_review",
  review_case_id: "rvw_aa77ff0d68d72af5b4771d736a0f789e",
  review_requirement: "requires_operator",
  review_version: 0,
  risk_class: "high",
  subject_id: "ent_66fb736038ea9e42d480f6f466210679",
  subject_kind: "knowledge_assertion",
  subject_kind_of_fact: "entity",
};

/** The Knowledge row with one key omitted (a required candidate key missing). */
function without(key: keyof typeof KNOWLEDGE_CASE): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...KNOWLEDGE_CASE };
  delete copy[key];
  return copy;
}

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

const SEMANTIC_CASE = {
  review_case_id: "rvc_cccc0001cccc0001cccc0001",
  proposal_id: "prop_cccc0001cccc0001cccc0001",
  proposal_state: "proposed",
  risk_class: "moderate",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 1,
  latest_disposition: null,
  subject_kind: "goodnotes_semantic",
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
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

  it("accepts a goodnotes_semantic case with run_id and page_version_id", () => {
    const decoded = decodeReviewList({ review_cases: [SEMANTIC_CASE] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.review_cases[0]).toMatchObject({
        subject_kind: "goodnotes_semantic",
        run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
      });
    }
  });

  it("fails closed when a goodnotes_semantic case omits run_id", () => {
    const { run_id: _, ...rest } = SEMANTIC_CASE;
    expect(decodeReviewList({ review_cases: [rest] }).ok).toBe(false);
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

  it("fails closed on an invalid enum inside a known kind", () => {
    // An unknown `subject_kind` is no longer a page failure (KLP-AC-135, below);
    // a known kind with a bad token still is.
    expect(
      decodeReviewList({ review_cases: [{ ...CAPTURE_CASE, proposal_type: "task" }] }).ok,
    ).toBe(false);
  });
});

describe("KLP-AC-033 / KLP-AC-135: a page mixing capture, knowledge_assertion and unknown rows", () => {
  it("decodes a Knowledge row with the R6 section 10.1 keys and the read-only candidate", () => {
    const decoded = decodeReviewList({ review_cases: [KNOWLEDGE_CASE] });
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.review_cases).toEqual([
      {
        review_case_id: "rvw_aa77ff0d68d72af5b4771d736a0f789e",
        proposal_id: "kaprp_7a88c3d12e4066cd1e9f007ebf89c4b0",
        proposal_state: "needs_review",
        risk_class: "high",
        opened_at: "2026-10-04T12:00:00.000Z",
        review_version: 0,
        latest_disposition: null,
        subject_kind: "knowledge_assertion",
        subject_kind_of_fact: "entity",
        subject_id: "ent_66fb736038ea9e42d480f6f466210679",
        predicate_code: "organization.payment_terms",
        review_requirement: "requires_operator",
        value_type: "text",
        value: "net 60",
        qualifier: null,
        effective_from: "2026-10-04T12:00:00+00:00",
        effective_to: null,
        evidence_ref_ids: [
          "kaevd_1b0f3a7c9e2d4f6a8b0c2e4f6a8b0c2e",
          "kaevd_5d7f9b1d3f5a7c9e1b3d5f7a9c1e3b5d",
        ],
        current_assertion_id: "kasr_9c2e4f6a8b0c2e4f6a8b0c2e4f6a8b0c",
        current_value: "net 30",
      },
    ]);
    expect(decoded.value.dropped_row_count).toBe(0);
  });

  it("decodes the committed Python mixed page (capture then knowledge_assertion)", () => {
    const decoded = decodeReviewList(fixture("success.json")["review.list"]);
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.review_cases.map((row) => row.subject_kind)).toEqual([
      "capture_proposal",
      "knowledge_assertion",
    ]);
    expect(decoded.value.review_cases[1]).toMatchObject({
      value: "net 60",
      current_value: "net 30",
    });
    expect(decoded.value.dropped_row_count).toBe(0);
  });

  it("decodes a withheld or absent holder as both holder fields null", () => {
    const decoded = decodeReviewList({
      review_cases: [{ ...KNOWLEDGE_CASE, current_assertion_id: null, current_value: null }],
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.review_cases[0]).toMatchObject({
        current_assertion_id: null,
        current_value: null,
      });
    }
  });

  it("decodes the post-accept Knowledge row slice C recorded", () => {
    const decoded = decodeReviewList({
      review_cases: [
        { ...KNOWLEDGE_CASE, latest_disposition: "accept", proposal_state: "accepted", review_version: 1 },
      ],
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.review_cases[0]).toMatchObject({
        latest_disposition: "accept",
        proposal_state: "accepted",
        review_version: 1,
      });
    }
  });

  it("carries only the declared candidate keys, never excerpt text or a raw column", () => {
    const decoded = decodeReviewList({
      review_cases: [
        {
          ...KNOWLEDGE_CASE,
          value_text: "net 99",
          excerpt: "secret excerpt words",
          evidence: ["x"],
          capture_id: "cap_x",
        },
      ],
    });
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    const row = decoded.value.review_cases[0] as unknown as Record<string, unknown>;
    expect(Object.keys(row).sort()).toEqual(
      [
        "review_case_id",
        "proposal_id",
        "proposal_state",
        "risk_class",
        "opened_at",
        "review_version",
        "latest_disposition",
        "subject_kind",
        "subject_kind_of_fact",
        "subject_id",
        "predicate_code",
        "review_requirement",
        "value_type",
        "value",
        "qualifier",
        "effective_from",
        "effective_to",
        "evidence_ref_ids",
        "current_assertion_id",
        "current_value",
      ].sort(),
    );
    expect(JSON.stringify(row)).not.toContain("net 99");
    expect(JSON.stringify(row)).not.toContain("secret excerpt words");
  });

  it("accepts capture, knowledge_assertion and unknown rows on one page, in order", () => {
    const decoded = decodeReviewList({
      review_cases: [
        CAPTURE_CASE,
        KNOWLEDGE_CASE,
        { review_case_id: "rvw_unknown0001unknown0001", subject_kind: "future_kind" },
        MEMORY_CASE,
      ],
    });
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.review_cases.map((row) => row.subject_kind)).toEqual([
      "capture_proposal",
      "knowledge_assertion",
      "unknown",
      "relationship_memory",
    ]);
    expect(decoded.value.dropped_row_count).toBe(0);
  });

  it("an unknown row needs only review_case_id and subject_kind and keeps nothing decidable", () => {
    const decoded = decodeReviewList({
      review_cases: [
        {
          review_case_id: "rvw_unknown0001unknown0001",
          subject_kind: "future_kind",
          // A newer backend's extra keys — including ones that look decidable —
          // are not carried: the row is inert.
          review_version: 4,
          proposal_id: "prop_x",
          proposal_state: "not_a_state",
        },
      ],
    });
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.review_cases).toEqual([
      {
        subject_kind: "unknown",
        review_case_id: "rvw_unknown0001unknown0001",
        reported_subject_kind: "future_kind",
      },
    ]);
  });

  it("drops and counts a row that fails even review_case_id + subject_kind; the page survives", () => {
    const decoded = decodeReviewList({
      review_cases: [
        CAPTURE_CASE,
        { subject_kind: "future_kind" },
        { review_case_id: "rvw_unknown0001unknown0001" },
        { review_case_id: 7, subject_kind: "future_kind" },
        { review_case_id: "rvw_unknown0001unknown0001", subject_kind: 3 },
        { review_case_id: "", subject_kind: "future_kind" },
        { review_case_id: "rvw_unknown0001unknown0001", subject_kind: "" },
        null,
        "rvw_string_row",
        [KNOWLEDGE_CASE],
        KNOWLEDGE_CASE,
      ],
    });
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.review_cases.map((row) => row.subject_kind)).toEqual([
      "capture_proposal",
      "knowledge_assertion",
    ]);
    expect(decoded.value.dropped_row_count).toBe(9);
  });

  it("a page of only dropped rows decodes as empty-with-a-count, not as a failure", () => {
    const decoded = decodeReviewList({ review_cases: [{}, null] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.review_cases).toEqual([]);
      expect(decoded.value.dropped_row_count).toBe(2);
    }
  });

  it("holds a known knowledge_assertion row to its full contract (not loosened)", () => {
    const { predicate_code: _p, ...noPredicate } = KNOWLEDGE_CASE;
    const { subject_id: _s, ...noSubject } = KNOWLEDGE_CASE;
    for (const bad of [
      noPredicate,
      noSubject,
      { ...KNOWLEDGE_CASE, subject_kind_of_fact: "capture" },
      { ...KNOWLEDGE_CASE, review_requirement: "auto" },
      { ...KNOWLEDGE_CASE, risk_class: "medium" },
      { ...KNOWLEDGE_CASE, proposal_state: "open" },
      { ...KNOWLEDGE_CASE, latest_disposition: "approve" },
      { ...KNOWLEDGE_CASE, review_version: "0" },
      { ...KNOWLEDGE_CASE, value_type: "number" },
      { ...KNOWLEDGE_CASE, value: 60 },
      { ...KNOWLEDGE_CASE, qualifier: "deadline" },
      { ...KNOWLEDGE_CASE, effective_from: 1 },
      { ...KNOWLEDGE_CASE, evidence_ref_ids: "kaevd_1b0f3a7c9e2d4f6a8b0c2e4f6a8b0c2e" },
      { ...KNOWLEDGE_CASE, evidence_ref_ids: ["excerpt text"] },
      { ...KNOWLEDGE_CASE, current_assertion_id: "ent_x" },
      { ...KNOWLEDGE_CASE, current_assertion_id: null },
      without("value"),
      without("evidence_ref_ids"),
      without("current_value"),
    ]) {
      expect(decodeReviewList({ review_cases: [CAPTURE_CASE, bad] }).ok).toBe(false);
    }
  });

  it("leaves every other capability's decodeItems aborting on the first bad row", () => {
    const strict = decodeItems([{ id: "a" }, { id: 1 }], (row) =>
      requiredString((row as Record<string, unknown>).id),
    );
    expect(strict.ok).toBe(false);
  });
});

describe("KLP-AC-033: the Knowledge review.decide result is the existing seven-key shape", () => {
  const variants = fixture("review.knowledge.json") as Record<string, Record<string, unknown>>;

  it("decodes every committed Python Knowledge decide variant without a discriminator", () => {
    const capture = fixture("success.json")["review.decide"] as Record<string, unknown>;
    expect(Object.keys(variants).sort()).toEqual([
      "review.decide.accept",
      "review.decide.invalidate",
      "review.decide.reject",
    ]);
    for (const [name, payload] of Object.entries(variants)) {
      expect(Object.keys(payload).sort(), name).toEqual(Object.keys(capture).sort());
      const decoded = decodeReviewDecide(payload);
      expect(decoded.ok, name).toBe(true);
      if (decoded.ok) expect(decoded.value, name).toEqual(payload);
    }
  });

  it("carries kadec_/kasr_/kamut_ through on an accept and nulls on a reject", () => {
    const accept = decodeReviewDecide(variants["review.decide.accept"]);
    expect(accept.ok).toBe(true);
    if (accept.ok && "decision_id" in accept.value) {
      expect(accept.value.decision_id).toMatch(/^kadec_/);
      expect(accept.value.assertion_id).toMatch(/^kasr_/);
      expect(accept.value.receipt_id).toMatch(/^kamut_/);
    }
    const reject = decodeReviewDecide(variants["review.decide.reject"]);
    expect(reject.ok).toBe(true);
    if (reject.ok && "decision_id" in reject.value) {
      expect(reject.value.assertion_id).toBeNull();
      expect(reject.value.receipt_id).toBeNull();
    }
  });
});
