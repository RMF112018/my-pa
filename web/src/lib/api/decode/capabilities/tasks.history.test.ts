// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksHistory } from "./tasks.history";

const ENTRY = {
  history_id: "thst_aaaa0001aaaa0001aaaa0001",
  task_id: "tsk_aaaa0001aaaa0001aaaa0001",
  action: "create",
  actor: "principal",
  outcome: "applied",
  before_version: 0,
  after_version: 1,
  occurred_at: "2026-01-01T00:00:00Z",
  recorded_at: "2026-01-01T00:00:00Z",
};

describe("decodeTasksHistory", () => {
  it("accepts a Python-derived history page", () => {
    const decoded = decodeTasksHistory({ history: [ENTRY] });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksHistory({ history: [{ ...ENTRY, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when history is omitted", () => {
    expect(decodeTasksHistory({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeTasksHistory({}).ok).toBe(false);
    expect(decodeTasksHistory({ history: [] }).ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeTasksHistory({ history: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { action: _, ...rest } = ENTRY;
    expect(decodeTasksHistory({ history: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeTasksHistory({ history: [{ ...ENTRY, outcome: "ok" }] }).ok).toBe(false);
  });
});
