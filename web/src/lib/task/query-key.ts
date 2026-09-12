/**
 * Canonical Task query identity for WP-TUX-02.
 *
 * Keys distinguish resource, mode, work view, civil work date, IANA timezone,
 * search text, archive mode, lifecycle, priority, cursor/page, task id, and
 * session epoch. Equal semantic inputs produce equal keys; differing filters,
 * dates, timezones, cursors, modes, or epochs produce distinct keys.
 *
 * Browser-selected Principal is never part of a key — Principal is
 * server-derived. `sessionEpoch` is an internal client isolation token only.
 */

export const TASK_QUERY_RESOURCE = "tasks" as const;

export const TASK_QUERY_MODES = ["list", "search", "detail", "comments"] as const;
export type TaskQueryMode = (typeof TASK_QUERY_MODES)[number];

/**
 * Input fields for a Task query. Undefined / null / empty optional strings
 * normalize identically so callers need not agree on which sentinel they use.
 */
export interface TaskQueryKeyInput {
  readonly mode: TaskQueryMode;
  readonly workView?: string | null;
  readonly workDate?: string | null;
  readonly timezone?: string | null;
  readonly q?: string | null;
  readonly archiveMode?: string | null;
  readonly lifecycle?: string | null;
  readonly priority?: string | null;
  readonly cursor?: string | null;
  readonly page?: string | number | null;
  readonly taskId?: string | null;
  readonly sessionEpoch: string | number;
}

/**
 * Stable, comparable Task query identity. Field order is fixed; values are
 * normalized. Do not reconstruct this by hand — use {@link buildTaskQueryKey}.
 */
export interface TaskQueryKey {
  readonly resource: typeof TASK_QUERY_RESOURCE;
  readonly mode: TaskQueryMode;
  readonly workView: string | null;
  readonly workDate: string | null;
  readonly timezone: string | null;
  readonly q: string | null;
  readonly archiveMode: string | null;
  readonly lifecycle: string | null;
  readonly priority: string | null;
  readonly cursor: string | null;
  readonly page: string | null;
  readonly taskId: string | null;
  readonly sessionEpoch: string;
}

function normalizeOptionalString(value: string | null | undefined): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function normalizePage(value: string | number | null | undefined): string | null {
  if (value == null || value === "") return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return String(Math.trunc(value));
  }
  return normalizeOptionalString(value);
}

function normalizeSessionEpoch(value: string | number): string {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("sessionEpoch must be a finite number or non-empty string");
    }
    return String(Math.trunc(value));
  }
  const trimmed = value.trim();
  if (!trimmed) {
    throw new TypeError("sessionEpoch must be a finite number or non-empty string");
  }
  return trimmed;
}

/** Build the canonical Task query key from semantic inputs. */
export function buildTaskQueryKey(input: TaskQueryKeyInput): TaskQueryKey {
  if (!TASK_QUERY_MODES.includes(input.mode)) {
    throw new TypeError(`unsupported Task query mode: ${String(input.mode)}`);
  }
  return {
    resource: TASK_QUERY_RESOURCE,
    mode: input.mode,
    workView: normalizeOptionalString(input.workView),
    workDate: normalizeOptionalString(input.workDate),
    timezone: normalizeOptionalString(input.timezone),
    q: normalizeOptionalString(input.q),
    archiveMode: normalizeOptionalString(input.archiveMode),
    lifecycle: normalizeOptionalString(input.lifecycle),
    priority: normalizeOptionalString(input.priority),
    cursor: normalizeOptionalString(input.cursor),
    page: normalizePage(input.page),
    taskId: normalizeOptionalString(input.taskId),
    sessionEpoch: normalizeSessionEpoch(input.sessionEpoch),
  };
}

const KEY_FIELD_ORDER = [
  "resource",
  "mode",
  "workView",
  "workDate",
  "timezone",
  "q",
  "archiveMode",
  "lifecycle",
  "priority",
  "cursor",
  "page",
  "taskId",
  "sessionEpoch",
] as const satisfies ReadonlyArray<keyof TaskQueryKey>;

/** Deterministic map / wire identity for a canonical key. */
export function serializeTaskQueryKey(key: TaskQueryKey): string {
  return JSON.stringify(KEY_FIELD_ORDER.map((field) => key[field]));
}

/** Structural equality of two canonical keys. */
export function taskQueryKeysEqual(a: TaskQueryKey, b: TaskQueryKey): boolean {
  return serializeTaskQueryKey(a) === serializeTaskQueryKey(b);
}
