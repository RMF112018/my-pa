// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksCommentsCreate } from "./tasks.comments.create";
import { TASK_COMMENT } from "./tasks.comments.list.test";

function payload(overrides: Record<string, unknown> = {}) {
  return { comment: TASK_COMMENT, replayed: false, ...overrides };
}

describe("decodeTasksCommentsCreate", () => {
  it("accepts a Python create receipt", () => {
    const decoded = decodeTasksCommentsCreate(payload());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.comment.comment_id).toBe(TASK_COMMENT.comment_id);
      expect(decoded.value.replayed).toBe(false);
    }
  });

  it("fails closed when comment is omitted", () => {
    const { comment: _, ...rest } = payload();
    expect(decodeTasksCommentsCreate(rest).ok).toBe(false);
  });

  it("fails closed when replayed is the wrong type", () => {
    expect(decodeTasksCommentsCreate(payload({ replayed: "false" })).ok).toBe(false);
  });

  it("fails closed when comment body is missing", () => {
    const { body: _, ...rest } = TASK_COMMENT;
    expect(decodeTasksCommentsCreate(payload({ comment: rest })).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksCommentsCreate(payload({ extra_create_field: 1 })).ok).toBe(true);
  });
});
