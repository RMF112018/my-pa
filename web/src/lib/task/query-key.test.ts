import { describe, expect, it } from "vitest";
import {
  buildTaskQueryKey,
  serializeTaskQueryKey,
  taskQueryKeysEqual,
  type TaskQueryKeyInput,
} from "@/lib/task/query-key";

const BASE: TaskQueryKeyInput = {
  mode: "list",
  workView: "today",
  workDate: "2026-09-11",
  timezone: "America/New_York",
  archiveMode: "exclude",
  sessionEpoch: "epoch-1",
};

describe("buildTaskQueryKey equality", () => {
  it("produces equal keys for equal semantic inputs including empty-vs-undefined normalization", () => {
    const a = buildTaskQueryKey({
      ...BASE,
      q: "",
      lifecycle: null,
      priority: undefined,
      cursor: "  ",
      page: null,
    });
    const b = buildTaskQueryKey({
      ...BASE,
      q: undefined,
      lifecycle: undefined,
      priority: null,
      cursor: null,
      page: undefined,
    });
    expect(taskQueryKeysEqual(a, b)).toBe(true);
    expect(serializeTaskQueryKey(a)).toBe(serializeTaskQueryKey(b));
    expect(a.resource).toBe("tasks");
    expect(a.q).toBeNull();
    expect(a.cursor).toBeNull();
  });

  it("normalizes sessionEpoch number and string forms", () => {
    const a = buildTaskQueryKey({ ...BASE, sessionEpoch: 7 });
    const b = buildTaskQueryKey({ ...BASE, sessionEpoch: "7" });
    expect(taskQueryKeysEqual(a, b)).toBe(true);
  });

  it("never includes a Principal field in the serialized key", () => {
    const key = buildTaskQueryKey(BASE);
    const serialized = serializeTaskQueryKey(key);
    expect(serialized.toLowerCase()).not.toContain("principal");
    expect(Object.keys(key)).not.toContain("principal");
    expect(Object.keys(key)).not.toContain("principalId");
  });
});

describe("buildTaskQueryKey isolation", () => {
  it.each([
    ["mode", { mode: "search" as const }],
    ["workView", { workView: "overdue" }],
    ["workDate", { workDate: "2026-09-12" }],
    ["timezone", { timezone: "America/Los_Angeles" }],
    ["q", { q: "drawings" }],
    ["archiveMode", { archiveMode: "only" }],
    ["lifecycle", { lifecycle: "open" }],
    ["priority", { priority: "p1" }],
    ["cursor", { cursor: "tsk_aaaaaaaa11111111" }],
    ["page", { page: 2 }],
    ["taskId", { mode: "detail" as const, taskId: "tsk_aaaaaaaa11111111" }],
    ["sessionEpoch", { sessionEpoch: "epoch-2" }],
  ])("differs when %s changes", (_label, patch) => {
    const left = buildTaskQueryKey(BASE);
    const right = buildTaskQueryKey({ ...BASE, ...patch });
    expect(taskQueryKeysEqual(left, right)).toBe(false);
    expect(serializeTaskQueryKey(left)).not.toBe(serializeTaskQueryKey(right));
  });

  it("keeps list and search modes distinct even with the same q", () => {
    const list = buildTaskQueryKey({ ...BASE, mode: "list", q: "plan" });
    const search = buildTaskQueryKey({ ...BASE, mode: "search", q: "plan" });
    expect(taskQueryKeysEqual(list, search)).toBe(false);
  });

  it("keeps detail and comments distinct for the same taskId", () => {
    const detail = buildTaskQueryKey({
      mode: "detail",
      taskId: "tsk_aaaaaaaa11111111",
      sessionEpoch: "epoch-1",
    });
    const comments = buildTaskQueryKey({
      mode: "comments",
      taskId: "tsk_aaaaaaaa11111111",
      sessionEpoch: "epoch-1",
    });
    expect(taskQueryKeysEqual(detail, comments)).toBe(false);
  });

  it("rejects an empty sessionEpoch", () => {
    expect(() => buildTaskQueryKey({ ...BASE, sessionEpoch: "  " })).toThrow(/sessionEpoch/);
  });
});
