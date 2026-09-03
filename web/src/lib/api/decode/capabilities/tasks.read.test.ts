// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksRead } from "./tasks.read";

export const TASK_VIEW = {
  task_id: "tsk_aaaa0001aaaa0001aaaa0001",
  title: "Check the pour",
  description: null,
  lifecycle_state: "open",
  evidence_state: "accepted",
  origin_evidence_ref: "asr_aaaa0001aaaa0001aaaa0001",
  closure_evidence_ref: null,
  accepted_by_review_decision_id: null,
  acceptance_kind: "direct_principal",
  closure_history_id: null,
  version: 1,
  priority: "p2",
  due_at: "2026-01-02T00:00:00Z",
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  project_id: null,
  situation_id: null,
  recurrence_id: null,
  opened_at: "2026-01-01T00:00:00Z",
  closed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  commitment_id: null,
  role: null,
};

describe("decodeTasksRead", () => {
  it("accepts a Python-derived TaskView wrapper", () => {
    const decoded = decodeTasksRead({ task: TASK_VIEW });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksRead({ task: { ...TASK_VIEW, extra: 1 }, noise: true }).ok).toBe(true);
  });

  it("fails closed when task is omitted", () => {
    expect(decodeTasksRead({}).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeTasksRead({ task: [] }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { title: _, ...rest } = TASK_VIEW;
    expect(decodeTasksRead({ task: rest }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeTasksRead({ task: { ...TASK_VIEW, lifecycle_state: "done" } }).ok).toBe(false);
  });
});
