import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeTaskView, fail, pick, type TaskView } from "./_read-helpers";

export type { TaskView };

export interface TasksReadResult {
  readonly task: TaskView;
}

export const decodeTasksRead: Decoder<TasksReadResult> = (input) => {
  const known = pick(input, ["task"]);
  if (!known.ok) return known;
  if (known.value.task === undefined) return fail("a required field was missing");
  const task = decodeTaskView(known.value.task);
  if (!task.ok) return task;
  return ok({ task: task.value });
};
