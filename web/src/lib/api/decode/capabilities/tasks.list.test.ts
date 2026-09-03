// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksList } from "./tasks.list";

export const TASK_LIST_ENTRY = {
  task_id: "tsk_aaaa0001aaaa0001aaaa0001",
  title: "Check the pour",
  lifecycle_state: "open",
  priority: "p2",
  due_at: "2026-01-02T00:00:00Z",
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  version: 1,
};

describe("decodeTasksList", () => {
  it("accepts a Python-derived page", () => {
    const decoded = decodeTasksList({ tasks: [TASK_LIST_ENTRY] });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksList({ tasks: [{ ...TASK_LIST_ENTRY, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when tasks is omitted", () => {
    expect(decodeTasksList({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeTasksList({}).ok).toBe(false);
    const empty = decodeTasksList({ tasks: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.tasks).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeTasksList({ tasks: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { title: _, ...rest } = TASK_LIST_ENTRY;
    expect(decodeTasksList({ tasks: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeTasksList({ tasks: [{ ...TASK_LIST_ENTRY, priority: "urgent" }] }).ok).toBe(false);
  });
});
