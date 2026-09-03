// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsSearch } from "./commitments.search";
import { COMMITMENT_LIST_ENTRY } from "./commitments.list.test";

const VALID = {
  commitments: [COMMITMENT_LIST_ENTRY],
  counterparty_options: [],
  counterparty_options_truncated: false,
};

describe("decodeCommitmentsSearch", () => {
  it("accepts the same page shape as commitments.list", () => {
    expect(decodeCommitmentsSearch(VALID).ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCommitmentsSearch({ ...VALID, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when commitments is omitted", () => {
    const { commitments: _, ...rest } = VALID;
    expect(decodeCommitmentsSearch(rest).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    const { commitments: _, ...rest } = VALID;
    expect(decodeCommitmentsSearch(rest).ok).toBe(false);
    expect(decodeCommitmentsSearch({ ...VALID, commitments: [] }).ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCommitmentsSearch({ ...VALID, counterparty_options_truncated: "no" }).ok).toBe(
      false,
    );
  });

  it("fails closed when a required field is missing", () => {
    const { version: _, ...entry } = COMMITMENT_LIST_ENTRY;
    expect(decodeCommitmentsSearch({ ...VALID, commitments: [entry] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeCommitmentsSearch({
        ...VALID,
        commitments: [{ ...COMMITMENT_LIST_ENTRY, direction: "inward" }],
      }).ok,
    ).toBe(false);
  });
});
