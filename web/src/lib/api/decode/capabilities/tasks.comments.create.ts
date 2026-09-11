import { ok } from "../primitives";
import type { Decoder } from "../types";
import { fail, pick, requiredBoolean } from "./_mutation-helpers";
import { decodeTaskCommentEntry, type TaskCommentView } from "./tasks.comments.list";

export type { TaskCommentView };

export interface TasksCommentsCreateResult {
  readonly comment: TaskCommentView;
  readonly replayed: boolean;
}

export const decodeTasksCommentsCreate: Decoder<TasksCommentsCreateResult> = (input) => {
  const known = pick(input, ["comment", "replayed"]);
  if (!known.ok) return known;
  if (known.value.comment === undefined) return fail("a required field was missing");
  const comment = decodeTaskCommentEntry(known.value.comment);
  if (!comment.ok) return comment;
  const replayed = requiredBoolean(known.value.replayed);
  if (!replayed.ok) return replayed;
  return ok({ comment: comment.value, replayed: replayed.value });
};
