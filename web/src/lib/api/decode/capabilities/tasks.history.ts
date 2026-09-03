import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  decodeTaskHistoryEntry,
  fail,
  pick,
  type TaskHistoryEntry,
} from "./_read-helpers";

export type { TaskHistoryEntry };

export interface TasksHistoryResult {
  readonly history: readonly TaskHistoryEntry[];
}

export const decodeTasksHistory: Decoder<TasksHistoryResult> = (input) => {
  const known = pick(input, ["history"]);
  if (!known.ok) return known;
  if (known.value.history === undefined) return fail("a required array was omitted");
  const history = decodeItems(known.value.history, decodeTaskHistoryEntry);
  if (!history.ok) return history;
  return ok({ history: history.value });
};
