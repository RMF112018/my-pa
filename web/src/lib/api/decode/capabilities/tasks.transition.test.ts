// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksTransition } from "./tasks.transition";

const AT = "2026-08-09T12:00:00.000Z";

function task(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "tsk_aaaaaaaa11111111",
    title: "Canonical",
    description: null,
    lifecycle_state: "completed",
    evidence_state: "accepted",
    origin_evidence_ref: "cap_aaaaaaaa11111111",
    closure_evidence_ref: "cap_bbbbbbbb22222222",
    accepted_by_review_decision_id: null,
    acceptance_kind: "direct_principal",
    closure_history_id: "thst_cccccccc33333333",
    version: 3,
    priority: null,
    due_at: null,
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    project_id: null,
    situation_id: null,
    recurrence_id: null,
    opened_at: AT,
    closed_at: AT,
    created_at: AT,
    updated_at: AT,
    commitment_id: null,
    role: null,
    ...overrides,
  };
}

function history(overrides: Record<string, unknown> = {}) {
  return {
    history_id: "thst_cccccccc33333333",
    task_id: "tsk_aaaaaaaa11111111",
    action: "transition_lifecycle",
    actor: "principal",
    outcome: "applied",
    before_version: 2,
    after_version: 3,
    occurred_at: AT,
    recorded_at: AT,
    ...overrides,
  };
}

function payload(overrides: Record<string, unknown> = {}) {
  return { task: task(), history: history(), replayed: false, ...overrides };
}

describe("decodeTasksTransition", () => {
  it("accepts a Python transition receipt", () => {
    const decoded = decodeTasksTransition(payload());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.task.lifecycle_state).toBe("completed");
  });

  it("fails closed when history is omitted", () => {
    const { history: _, ...rest } = payload();
    expect(decodeTasksTransition(rest).ok).toBe(false);
  });

  it("fails closed when replayed is the wrong type", () => {
    expect(decodeTasksTransition(payload({ replayed: 0 })).ok).toBe(false);
  });

  it("fails closed when task.version is missing rather than inferring it", () => {
    const { version: _, ...rest } = task();
    expect(decodeTasksTransition(payload({ task: rest })).ok).toBe(false);
  });

  it("fails closed on an invalid outcome enum", () => {
    expect(decodeTasksTransition(payload({ history: history({ outcome: "ok" }) })).ok).toBe(false);
  });

  it("fails closed when task is omitted", () => {
    const { task: _, ...rest } = payload();
    expect(decodeTasksTransition(rest).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksTransition(payload({ extra_transition_field: "ignored" })).ok).toBe(true);
  });
});
