/**
 * Map a decoded `review.list` row onto the workbench listing shape.
 *
 * Capture proposals keep `captureId` / `versionId`. GoodNotes rows keep the
 * identifiers the listing actually returned and never borrow a capture id.
 * The listing still carries no proposal text, evidence span, or impact summary.
 */
import type { ReviewCase } from "@/lib/api/decode/capabilities/review.list";
import type { BackendReviewCase } from "@/contracts/views";

function listingFields(row: ReviewCase) {
  return {
    reviewCaseId: row.review_case_id,
    proposalId: row.proposal_id,
    proposalState: row.proposal_state,
    riskClass: row.risk_class,
    openedAt: row.opened_at,
    reviewVersion: row.review_version,
    latestDisposition: row.latest_disposition,
  };
}

export function toBackendReviewCase(row: ReviewCase): BackendReviewCase {
  if (row.subject_kind === "capture_proposal") {
    return {
      ...listingFields(row),
      subjectKind: "capture_proposal",
      captureId: row.capture_id,
      versionId: row.version_id,
      proposalType: row.proposal_type,
    };
  }
  if (row.subject_kind === "goodnotes_semantic") {
    return {
      ...listingFields(row),
      subjectKind: "goodnotes_semantic",
      runId: row.run_id,
      pageVersionId: row.page_version_id,
      proposalType: row.subject_kind,
    };
  }
  if (row.subject_kind === "goodnotes_region") {
    return {
      ...listingFields(row),
      subjectKind: "goodnotes_region",
      regionId: row.region_id,
      pageVersionId: row.page_version_id,
      confidence: row.confidence,
      proposalType: row.subject_kind,
    };
  }
  return {
    ...listingFields(row),
    subjectKind: row.subject_kind,
    captureId: row.review_case_id,
    versionId: row.proposal_id,
    proposalType: row.subject_kind,
  };
}
