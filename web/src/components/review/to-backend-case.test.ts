import { describe, expect, it } from "vitest";
import type {
  CaptureProposalReviewCase,
  GoodNotesReviewCase,
  GoodNotesSemanticReviewCase,
} from "@/lib/api/decode/capabilities/review.list";
import { toBackendReviewCase } from "./to-backend-case";

const CAPTURE: CaptureProposalReviewCase = {
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

const SEMANTIC: GoodNotesSemanticReviewCase = {
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

const REGION: GoodNotesReviewCase = {
  review_case_id: "rvc_dddd0001dddd0001dddd0001",
  proposal_id: "prop_dddd0001dddd0001dddd0001",
  proposal_state: "needs_review",
  risk_class: "low",
  opened_at: "2026-01-01T00:00:00Z",
  review_version: 2,
  latest_disposition: null,
  subject_kind: "goodnotes_region",
  region_id: "gnreg_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
  confidence: 0.82,
};

describe("toBackendReviewCase", () => {
  it("preserves capture_proposal identifiers exactly", () => {
    expect(toBackendReviewCase(CAPTURE)).toEqual({
      reviewCaseId: CAPTURE.review_case_id,
      proposalId: CAPTURE.proposal_id,
      subjectKind: "capture_proposal",
      captureId: CAPTURE.capture_id,
      versionId: CAPTURE.version_id,
      proposalType: "commitment",
      proposalState: "proposed",
      riskClass: "high",
      openedAt: CAPTURE.opened_at,
      reviewVersion: 3,
      latestDisposition: null,
    });
  });

  it("does not stuff a goodnotes_semantic row into capture identifiers", () => {
    const mapped = toBackendReviewCase(SEMANTIC);
    expect(mapped).toEqual({
      reviewCaseId: SEMANTIC.review_case_id,
      proposalId: SEMANTIC.proposal_id,
      subjectKind: "goodnotes_semantic",
      runId: SEMANTIC.run_id,
      pageVersionId: SEMANTIC.page_version_id,
      proposalType: "goodnotes_semantic",
      proposalState: "proposed",
      riskClass: "moderate",
      openedAt: SEMANTIC.opened_at,
      reviewVersion: 1,
      latestDisposition: null,
    });
    expect(mapped).not.toHaveProperty("captureId");
    expect(mapped).not.toHaveProperty("versionId");
    expect(mapped).not.toHaveProperty("proposalSummary");
    expect(mapped).not.toHaveProperty("evidence");
    expect(mapped).not.toHaveProperty("impactSummary");
  });

  it("maps a goodnotes_region row with region, page version, and listed confidence", () => {
    const mapped = toBackendReviewCase(REGION);
    expect(mapped).toEqual({
      reviewCaseId: REGION.review_case_id,
      proposalId: REGION.proposal_id,
      subjectKind: "goodnotes_region",
      regionId: REGION.region_id,
      pageVersionId: REGION.page_version_id,
      confidence: 0.82,
      proposalType: "goodnotes_region",
      proposalState: "needs_review",
      riskClass: "low",
      openedAt: REGION.opened_at,
      reviewVersion: 2,
      latestDisposition: null,
    });
    expect(mapped).not.toHaveProperty("captureId");
    expect(mapped).not.toHaveProperty("runId");
    expect(mapped).not.toHaveProperty("proposalSummary");
  });
});
