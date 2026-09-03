import { isRecord, ok, optional } from "../primitives";
import type { Decoder } from "../types";
import {
  fail,
  oneOf,
  pick,
  requiredIntGe,
  requiredNullableString,
  requiredString,
} from "./_mutation-helpers";
import { DISPOSITIONS, PROPOSAL_STATES } from "./knowledge.reveal";

export const HANDOFF_STATES = ["operator_preview_required"] as const;
export const HANDOFF_KINDS = ["merge_entities", "split_identity"] as const;
export const HANDOFF_SOURCES = ["proposed", "corrected"] as const;

export interface IdentityCorrectionHandoff {
  readonly state: (typeof HANDOFF_STATES)[number];
  readonly proposal_id: string;
  readonly proposal_kind: (typeof HANDOFF_KINDS)[number];
  readonly effective_payload_source: (typeof HANDOFF_SOURCES)[number];
  readonly effective_payload: Record<string, unknown>;
}

export type ReviewDecideInvalidated = {
  readonly review_case_id: string;
  readonly result: "invalidated";
};

export type ReviewDecideDecision = {
  readonly review_case_id: string;
  readonly decision_id: string;
  readonly review_version: number;
  readonly disposition: (typeof DISPOSITIONS)[number];
  readonly proposal_state: (typeof PROPOSAL_STATES)[number];
  readonly assertion_id: string | null;
  readonly receipt_id: string | null;
  readonly identity_correction_handoff?: IdentityCorrectionHandoff;
};

export type ReviewDecideResult = ReviewDecideInvalidated | ReviewDecideDecision;

const KEYS = [
  "review_case_id",
  "result",
  "decision_id",
  "review_version",
  "disposition",
  "proposal_state",
  "assertion_id",
  "receipt_id",
  "identity_correction_handoff",
] as const;

const HANDOFF_KEYS = [
  "state",
  "proposal_id",
  "proposal_kind",
  "effective_payload_source",
  "effective_payload",
] as const;

function present(record: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(record, key) && record[key] !== undefined;
}

function decodeHandoff(input: unknown) {
  const known = pick(input, HANDOFF_KEYS);
  if (!known.ok) return known;
  const state = oneOf(known.value.state, HANDOFF_STATES);
  if (!state.ok) return state;
  const proposalId = requiredString(known.value.proposal_id);
  if (!proposalId.ok) return proposalId;
  const kind = oneOf(known.value.proposal_kind, HANDOFF_KINDS);
  if (!kind.ok) return kind;
  const source = oneOf(known.value.effective_payload_source, HANDOFF_SOURCES);
  if (!source.ok) return source;
  if (!isRecord(known.value.effective_payload)) {
    return fail("a required object was missing or unreadable");
  }
  return ok({
    state: state.value,
    proposal_id: proposalId.value,
    proposal_kind: kind.value,
    effective_payload_source: source.value,
    effective_payload: known.value.effective_payload,
  });
}

export const decodeReviewDecide: Decoder<ReviewDecideResult> = (input) => {
  const known = pick(input, KEYS);
  if (!known.ok) return known;
  const reviewCaseId = requiredString(known.value.review_case_id);
  if (!reviewCaseId.ok) return reviewCaseId;
  const hasDecision = present(known.value, "decision_id");
  const hasResult = present(known.value, "result");
  if (hasDecision && hasResult) {
    return fail("a review decision mixed a receipt with an invalidated result");
  }
  if (!hasDecision && !hasResult) {
    return fail("a required field was missing");
  }
  if (hasResult) {
    const result = oneOf(known.value.result, ["invalidated"] as const);
    if (!result.ok) return result;
    return ok({
      review_case_id: reviewCaseId.value,
      result: result.value,
    });
  }
  const decisionId = requiredString(known.value.decision_id);
  if (!decisionId.ok) return decisionId;
  const version = requiredIntGe(known.value.review_version, 0);
  if (!version.ok) return version;
  const disposition = oneOf(known.value.disposition, DISPOSITIONS);
  if (!disposition.ok) return disposition;
  const proposalState = oneOf(known.value.proposal_state, PROPOSAL_STATES);
  if (!proposalState.ok) return proposalState;
  const assertionId = requiredNullableString(known.value.assertion_id);
  if (!assertionId.ok) return assertionId;
  const receiptId = requiredNullableString(known.value.receipt_id);
  if (!receiptId.ok) return receiptId;
  const handoff = optional(known.value.identity_correction_handoff, decodeHandoff);
  if (!handoff.ok) return handoff;
  return ok({
    review_case_id: reviewCaseId.value,
    decision_id: decisionId.value,
    review_version: version.value,
    disposition: disposition.value,
    proposal_state: proposalState.value,
    assertion_id: assertionId.value,
    receipt_id: receiptId.value,
    ...(handoff.value ? { identity_correction_handoff: handoff.value } : {}),
  });
};
