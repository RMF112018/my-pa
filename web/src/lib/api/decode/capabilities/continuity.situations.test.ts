// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeContinuitySituations } from "./continuity.situations";

const SITUATION = {
  situation_id: "sit_aaaa0001aaaa0001aaaa0001",
  title: "North pour",
  state: "open",
  description: null,
  object_refs: ["cmt_aaaa0001aaaa0001aaaa0001"],
  opened_at: "2026-01-01T00:00:00Z",
  closed_at: null,
  outcome: null,
};

const WORKSPACE = {
  frames: [
    {
      frame_id: "frm_aaaa0001aaaa0001aaaa0001",
      situation_id: SITUATION.situation_id,
      label: "current",
      state: "current",
      evidence_refs: [],
      alternatives: [],
      obligations: [],
      uncertainty: null,
      next_authority: null,
    },
  ],
  traces: [
    {
      trace_id: "trc_aaaa0001aaaa0001aaaa0001",
      object_id: "tsk_aaaa0001aaaa0001aaaa0001",
      object_type: "task",
      source_events: [],
      gaps: [],
    },
  ],
  commitments: [],
  decisions: [],
  tasks: [],
  relationship_events: [
    {
      event_id: "rev_aaaa0001aaaa0001aaaa0001",
      person_id: "per_aaaa0001aaaa0001aaaa0001",
      event_type: "meeting",
      occurred_at: "2026-01-01T00:00:00Z",
      context: null,
      source_ref: null,
    },
  ],
};

describe("decodeContinuitySituations", () => {
  it("accepts a listing without the continuity workspace group", () => {
    const decoded = decodeContinuitySituations({ situations: [SITUATION] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.situations).toHaveLength(1);
      expect(decoded.value.relationship_events).toBeUndefined();
    }
  });

  it("accepts the workspace group when every named array is present", () => {
    const decoded = decodeContinuitySituations({ situations: [SITUATION], ...WORKSPACE });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.relationship_events).toHaveLength(1);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeContinuitySituations({ situations: [{ ...SITUATION, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when situations is omitted", () => {
    expect(decodeContinuitySituations({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeContinuitySituations({}).ok).toBe(false);
    const empty = decodeContinuitySituations({ situations: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.situations).toEqual([]);
  });

  it("fails closed when relationship_events is omitted from a partial workspace", () => {
    const { relationship_events: _, ...partial } = WORKSPACE;
    expect(decodeContinuitySituations({ situations: [], ...partial }).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeContinuitySituations({ situations: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { title: _, ...rest } = SITUATION;
    expect(decodeContinuitySituations({ situations: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeContinuitySituations({ situations: [{ ...SITUATION, state: "done" }] }).ok).toBe(
      false,
    );
    expect(
      decodeContinuitySituations({
        situations: [],
        ...WORKSPACE,
        relationship_events: [{ ...WORKSPACE.relationship_events[0], event_type: "email" }],
      }).ok,
    ).toBe(false);
  });
});
