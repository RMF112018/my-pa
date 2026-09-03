// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksCreate } from "./tasks.create";

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
    version: 1,
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
    history_id: "thst_aaaaaaaa11111111",
    task_id: "tsk_aaaaaaaa11111111",
    action: "create",
    actor: "principal",
    outcome: "applied",
    before_version: 0,
    after_version: 1,
    occurred_at: AT,
    recorded_at: AT,
    ...overrides,
  };
}

function payload(overrides: Record<string, unknown> = {}) {
  return { task: task(), history: history(), replayed: false, ...overrides };
}

describe("decodeTasksCreate", () => {
  it("accepts a Python create receipt", () => {
    const decoded = decodeTasksCreate(payload());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.task.version).toBe(1);
      expect(decoded.value.replayed).toBe(false);
    }
  });

  it("fails closed when history is omitted", () => {
    const { history: _, ...rest } = payload();
    expect(decodeTasksCreate(rest).ok).toBe(false);
  });

  it("fails closed when replayed is the wrong type", () => {
    expect(decodeTasksCreate(payload({ replayed: "false" })).ok).toBe(false);
  });

  it("fails closed when task.version is missing rather than inferring it", () => {
    const { version: _, ...rest } = task();
    expect(decodeTasksCreate(payload({ task: rest })).ok).toBe(false);
  });

  it("fails closed on an invalid lifecycle enum", () => {
    expect(decodeTasksCreate(payload({ task: task({ lifecycle_state: "done" }) })).ok).toBe(false);
  });

  it("fails closed when task is the wrong type", () => {
    expect(decodeTasksCreate(payload({ task: "tsk_aaaaaaaa11111111" })).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksCreate(payload({ extra_create_field: 1 })).ok).toBe(true);
  });
});
