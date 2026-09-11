// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeTasksCommentsList } from "./tasks.comments.list";

export const TASK_COMMENT = {
  comment_id: "tcm_aaaa0001aaaa0001aaaa0001",
  task_id: "tsk_aaaa0001aaaa0001aaaa0001",
  body: "Synthetic follow-up note",
  author_kind: "principal",
  author_id: "prn_aaaa0001aaaa0001aaaa0001aaaa0001",
  created_at: "2026-01-01T00:00:00.000Z",
};

describe("decodeTasksCommentsList", () => {
  it("accepts a Python comment page", () => {
    const decoded = decodeTasksCommentsList({ comments: [TASK_COMMENT] });
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeTasksCommentsList({ comments: [{ ...TASK_COMMENT, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when comments is omitted", () => {
    expect(decodeTasksCommentsList({}).ok).toBe(false);
  });

  it("accepts an empty page", () => {
    expect(decodeTasksCommentsList({ comments: [] }).ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeTasksCommentsList({ comments: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { body: _, ...rest } = TASK_COMMENT;
    expect(decodeTasksCommentsList({ comments: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid author kind", () => {
    expect(decodeTasksCommentsList({ comments: [{ ...TASK_COMMENT, author_kind: "owner" }] }).ok).toBe(
      false,
    );
  });
});
