// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksUpdate } from "./tasks.update";

const AT = "2026-08-09T12:00:00.000Z";

function task(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "tsk_aaaaaaaa11111111",
    title: "Canonical",
    description: null,
    lifecycle_state: "open",
    evidence_state: "accepted",
    origin_evidence_ref: "cap_aaaaaaaa11111111",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: "direct_principal",
    closure_history_id: null,
    version: 2,
    priority: null,
    due_at: null,
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    project_id: null,
    situation_id: null,
    recurrence_id: null,
    opened_at: AT,
    closed_at: null,
    created_at: AT,
    updated_at: AT,
    commitment_id: null,
    role: null,
    ...overrides,
  };
}

function history(overrides: Record<string, unknown> = {}) {
  return {
    history_id: "thst_bbbbbbbb22222222",
    task_id: "tsk_aaaaaaaa11111111",
    action: "update",
    actor: "principal",
    outcome: "applied",
    before_version: 1,
    after_version: 2,
    occurred_at: AT,
    recorded_at: AT,
    ...overrides,
  };
}

function payload(overrides: Record<string, unknown> = {}) {
  return { task: task(), history: history(), replayed: false, ...overrides };
}

describe("decodeTasksUpdate", () => {
  it("accepts a Python update receipt", () => {
    const decoded = decodeTasksUpdate(payload());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.task.version).toBe(2);
  });

  it("fails closed when task is omitted", () => {
    const { task: _, ...rest } = payload();
    expect(decodeTasksUpdate(rest).ok).toBe(false);
  });

  it("fails closed when replayed is omitted", () => {
    const { replayed: _, ...rest } = payload();
    expect(decodeTasksUpdate(rest).ok).toBe(false);
  });

  it("fails closed when task.version is missing rather than inferring it", () => {
    const { version: _, ...rest } = task();
    expect(decodeTasksUpdate(payload({ task: rest })).ok).toBe(false);
  });

  it("fails closed on an invalid history action enum", () => {
    expect(decodeTasksUpdate(payload({ history: history({ action: "patch" }) })).ok).toBe(false);
  });

  it("fails closed when history is the wrong type", () => {
    expect(decodeTasksUpdate(payload({ history: [] })).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksUpdate(payload({ extra_update_field: true })).ok).toBe(true);
  });
});
