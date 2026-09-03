// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsWaitingOn } from "./commitments.waiting_on";

const ENTRY = {
  commitment_id: "cmt_aaaa0001aaaa0001aaaa0001",
  title: "Send the drawing",
  counterparty_person_id: "per_aaaa0001aaaa0001aaaa0001",
  due_date: null,
  state: "open",
  follow_up_task_id: "tsk_aaaa0001aaaa0001aaaa0001",
  follow_up_task_title: "Check back",
  follow_up_task_state: "open",
  counterparty: { person_id: "per_aaaa0001aaaa0001aaaa0001", display_name: "Synthetic B" },
};

describe("decodeCommitmentsWaitingOn", () => {
  it("accepts a Python-derived waiting-on page", () => {
    expect(decodeCommitmentsWaitingOn({ waiting_on: [ENTRY] }).ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCommitmentsWaitingOn({ waiting_on: [{ ...ENTRY, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when waiting_on is omitted", () => {
    expect(decodeCommitmentsWaitingOn({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeCommitmentsWaitingOn({}).ok).toBe(false);
    expect(decodeCommitmentsWaitingOn({ waiting_on: [] }).ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCommitmentsWaitingOn({ waiting_on: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { title: _, ...rest } = ENTRY;
    expect(decodeCommitmentsWaitingOn({ waiting_on: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeCommitmentsWaitingOn({ waiting_on: [{ ...ENTRY, state: "waiting" }] }).ok).toBe(
      false,
    );
  });
});
