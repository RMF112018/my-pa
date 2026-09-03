// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksSearch } from "./tasks.search";
import { TASK_LIST_ENTRY } from "./tasks.list.test";

describe("decodeTasksSearch", () => {
  it("accepts the same page shape as tasks.list", () => {
    const decoded = decodeTasksSearch({ tasks: [TASK_LIST_ENTRY] });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksSearch({ tasks: [{ ...TASK_LIST_ENTRY, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when tasks is omitted", () => {
    expect(decodeTasksSearch({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeTasksSearch({}).ok).toBe(false);
    expect(decodeTasksSearch({ tasks: [] }).ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeTasksSearch({ tasks: "x" }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { version: _, ...rest } = TASK_LIST_ENTRY;
    expect(decodeTasksSearch({ tasks: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeTasksSearch({ tasks: [{ ...TASK_LIST_ENTRY, lifecycle_state: "archived" }] }).ok,
    ).toBe(false);
  });
});
