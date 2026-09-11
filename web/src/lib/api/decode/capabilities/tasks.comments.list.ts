import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredString,
  TASK_MUTATION_ACTORS,
} from "./_read-helpers";

export interface TaskCommentView {
  readonly comment_id: string;
  readonly task_id: string;
  readonly body: string;
  readonly author_kind: (typeof TASK_MUTATION_ACTORS)[number];
  readonly author_id: string;
  readonly created_at: string;
}

export type TaskCommentListEntry = TaskCommentView;

export interface TasksCommentsListResult {
  readonly comments: readonly TaskCommentListEntry[];
}

const COMMENT_KEYS = [
  "comment_id",
  "task_id",
  "body",
  "author_kind",
  "author_id",
  "created_at",
] as const;

export function decodeTaskCommentEntry(input: unknown) {
  const known = pick(input, COMMENT_KEYS);
  if (!known.ok) return known;
  const commentId = requiredString(known.value.comment_id);
  if (!commentId.ok) return commentId;
  const taskId = requiredString(known.value.task_id);
  if (!taskId.ok) return taskId;
  const body = requiredString(known.value.body);
  if (!body.ok) return body;
  const authorKind = oneOf(known.value.author_kind, TASK_MUTATION_ACTORS);
  if (!authorKind.ok) return authorKind;
  const authorId = requiredString(known.value.author_id);
  if (!authorId.ok) return authorId;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  return ok({
    comment_id: commentId.value,
    task_id: taskId.value,
    body: body.value,
    author_kind: authorKind.value,
    author_id: authorId.value,
    created_at: createdAt.value,
  });
}

export const decodeTasksCommentsList: Decoder<TasksCommentsListResult> = (input) => {
  const known = pick(input, ["comments"]);
  if (!known.ok) return known;
  if (known.value.comments === undefined) return fail("a required array was omitted");
  const comments = decodeItems(known.value.comments, decodeTaskCommentEntry);
  if (!comments.ok) return comments;
  return ok({ comments: comments.value });
};
