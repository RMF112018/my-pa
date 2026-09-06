import { ok, optional } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  pick,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

export interface GoodNotesRun {
  readonly run_id: string;
  readonly state: string;
  readonly failure_class: string | null;
  readonly started_at: string;
  readonly completed_at: string | null;
  readonly page_version_id?: string;
}

export interface GoodNotesRunsListResult {
  readonly runs: readonly GoodNotesRun[];
  readonly next_cursor?: string;
}

const RUN_KEYS = [
  "run_id",
  "state",
  "failure_class",
  "started_at",
  "completed_at",
  "page_version_id",
] as const;

function decodeRun(input: unknown) {
  const known = pick(input, RUN_KEYS);
  if (!known.ok) return known;
  const runId = requiredString(known.value.run_id);
  if (!runId.ok) return runId;
  const state = requiredString(known.value.state);
  if (!state.ok) return state;
  const failureClass = requiredNullableString(known.value.failure_class);
  if (!failureClass.ok) return failureClass;
  const startedAt = requiredString(known.value.started_at);
  if (!startedAt.ok) return startedAt;
  const completedAt = requiredNullableString(known.value.completed_at);
  if (!completedAt.ok) return completedAt;
  const pageVersionId = optional(known.value.page_version_id, requiredString);
  if (!pageVersionId.ok) return pageVersionId;
  return ok({
    run_id: runId.value,
    state: state.value,
    failure_class: failureClass.value,
    started_at: startedAt.value,
    completed_at: completedAt.value,
    ...(pageVersionId.value !== undefined ? { page_version_id: pageVersionId.value } : {}),
  });
}

export const decodeGoodNotesRunsList: Decoder<GoodNotesRunsListResult> = (input) => {
  const known = pick(input, ["runs", "next_cursor"]);
  if (!known.ok) return known;
  if (known.value.runs === undefined) return fail("a required array was omitted");
  const runs = decodeItems(known.value.runs, decodeRun);
  if (!runs.ok) return runs;
  const cursor = optional(known.value.next_cursor, requiredString);
  if (!cursor.ok) return cursor;
  return ok({
    runs: runs.value,
    ...(cursor.value !== undefined ? { next_cursor: cursor.value } : {}),
  });
};
