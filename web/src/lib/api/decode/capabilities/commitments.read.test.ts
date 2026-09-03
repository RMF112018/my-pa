// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsRead } from "./commitments.read";
import { TASK_LIST_ENTRY } from "./tasks.list.test";

export const COMMITMENT_VIEW = {
  commitment_id: "cmt_aaaa0001aaaa0001aaaa0001",
  direction: "owed_to_principal",
  state: "open",
  counterparty_person_id: "per_aaaa0001aaaa0001aaaa0001",
  title: "Send the drawing",
  description: null,
  due_date: "2026-01-02T00:00:00+00:00",
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
  version: 1,
  evidence_state: "accepted",
  origin_evidence_ref: "asr_aaaa0001aaaa0001aaaa0001",
  closure_evidence_ref: null,
  accepted_by_review_decision_id: null,
  closed_at: null,
  counterparty: { person_id: "per_aaaa0001aaaa0001aaaa0001", display_name: "Synthetic B" },
};

const VALID = {
  commitment: COMMITMENT_VIEW,
  follow_up_task: TASK_LIST_ENTRY,
  counterparty_options: [COMMITMENT_VIEW.counterparty],
  counterparty_options_truncated: false,
};

describe("decodeCommitmentsRead", () => {
  it("accepts a Python-derived public view", () => {
    const decoded = decodeCommitmentsRead(VALID);
    expect(decoded.ok).toBe(true);
  });

  it("accepts a null follow-up task", () => {
    expect(decodeCommitmentsRead({ ...VALID, follow_up_task: null }).ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCommitmentsRead({ ...VALID, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when commitment is omitted", () => {
    const { commitment: _, ...rest } = VALID;
    expect(decodeCommitmentsRead(rest).ok).toBe(false);
  });

  it("fails closed when counterparty_options is omitted", () => {
    const { counterparty_options: _, ...rest } = VALID;
    expect(decodeCommitmentsRead(rest).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCommitmentsRead({ ...VALID, counterparty_options: 1 }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeCommitmentsRead({
        ...VALID,
        commitment: { ...COMMITMENT_VIEW, direction: "both" },
      }).ok,
    ).toBe(false);
  });
});
