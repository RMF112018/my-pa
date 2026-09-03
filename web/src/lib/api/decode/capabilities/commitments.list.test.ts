// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsList } from "./commitments.list";

export const COMMITMENT_LIST_ENTRY = {
  commitment_id: "cmt_aaaa0001aaaa0001aaaa0001",
  direction: "owed_by_principal",
  state: "open",
  counterparty_person_id: "per_aaaa0001aaaa0001aaaa0001",
  title: "Send the drawing",
  description: null,
  due_date: null,
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
  version: 1,
  counterparty: { person_id: "per_aaaa0001aaaa0001aaaa0001", display_name: "Synthetic B" },
};

const VALID = {
  commitments: [COMMITMENT_LIST_ENTRY],
  counterparty_options: [COMMITMENT_LIST_ENTRY.counterparty],
  counterparty_options_truncated: false,
};

describe("decodeCommitmentsList", () => {
  it("accepts a Python-derived page", () => {
    expect(decodeCommitmentsList(VALID).ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCommitmentsList({ ...VALID, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when commitments is omitted", () => {
    const { commitments: _, ...rest } = VALID;
    expect(decodeCommitmentsList(rest).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    const { commitments: _, ...rest } = VALID;
    expect(decodeCommitmentsList(rest).ok).toBe(false);
    expect(decodeCommitmentsList({ ...VALID, commitments: [] }).ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCommitmentsList({ ...VALID, commitments: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { title: _, ...entry } = COMMITMENT_LIST_ENTRY;
    expect(decodeCommitmentsList({ ...VALID, commitments: [entry] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeCommitmentsList({
        ...VALID,
        commitments: [{ ...COMMITMENT_LIST_ENTRY, state: "waiting" }],
      }).ok,
    ).toBe(false);
  });
});
