/**
 * Canonical Task presentation language and model (WP-TUX-03).
 *
 * This module is the single product-language contract for Tasks. Surfaces must not
 * re-derive human copy from backend tokens (no `replaceAll("_", " ")` as vocabulary).
 *
 * Boundaries: pure. No fetch, no mutation, no Work/List/Board layout knowledge.
 * Civil-day semantics are consumed from the caller (see `browserWorkClock` in
 * `@/lib/api/work-client`), never re-derived by truncating a UTC timestamp.
 */

import type { TaskDetail, TaskLifecycle, TaskPriority, TaskRow } from "@/contracts/work";

/** Lifecycle states a Task may be moved between as ordinary Status. */
export type TaskActiveStatus = "open" | "in_progress" | "waiting" | "blocked";

/**
 * `completed` and `cancelled` are deliberately absent: closure and cancellation are
 * distinct terminal actions, not ordinary Status choices.
 */
export const TASK_ACTIVE_STATUSES: readonly TaskActiveStatus[] = [
  "open",
  "in_progress",
  "waiting",
  "blocked",
];

export const TASK_STATUS_LABELS: Readonly<Record<TaskLifecycle, string>> = {
  open: "Open",
  in_progress: "In progress",
  waiting: "Waiting",
  blocked: "Blocked",
  completed: "Closed",
  cancelled: "Cancelled",
};

export const TASK_PRIORITY_LABELS: Readonly<Record<TaskPriority, string>> = {
  p1: "Critical",
  p2: "High",
  p3: "Medium",
  p4: "Low",
};

/** A Task without a priority has no priority. It is never silently treated as Low. */
export const NO_PRIORITY_LABEL = "No priority";

export const TASK_STATUS_FIELD_LABEL = "Status";
export const TASK_DUE_FIELD_LABEL = "Due";
export const TASK_PLANNED_FOR_LABEL = "Planned for";
export const TASK_SNOOZED_UNTIL_LABEL = "Snoozed until";
export const TASK_ARCHIVED_LABEL = "Archived";
export const TASK_CLOSE_ACTION_LABEL = "Close Task";
export const TASK_CANCEL_ACTION_LABEL = "Cancel Task";
export const TASK_CLOSE_CONFIRM_LABEL = "Confirm Closed";
export const TASK_CANCEL_CONFIRM_LABEL = "Confirm Cancelled";
export const NO_DUE_DATE_LABEL = "No due date";

export function formatTaskStatus(state: TaskLifecycle): string {
  return TASK_STATUS_LABELS[state];
}

export function formatTaskPriority(priority: TaskPriority | null | undefined): string {
  if (!priority) return NO_PRIORITY_LABEL;
  return TASK_PRIORITY_LABELS[priority];
}

export function isTerminalTaskStatus(state: TaskLifecycle): boolean {
  return state === "completed" || state === "cancelled";
}

export function isActiveTaskStatus(state: TaskLifecycle): state is TaskActiveStatus {
  return (TASK_ACTIVE_STATUSES as readonly string[]).includes(state);
}

/** Concise terminal summary for Summary, or null while the Task is still active. */
export function terminalTaskSummary(state: TaskLifecycle): string | null {
  if (state === "completed") return "This task is closed.";
  if (state === "cancelled") return "This task is cancelled.";
  return null;
}

/* ------------------------------------------------------------------ *
 * Civil-day handling
 * ------------------------------------------------------------------ */

/** Civil-day context supplied by the caller, matching `browserWorkClock`. */
export interface TaskCivilClock {
  readonly timezone: string;
  /** Civil date in `timezone`, `YYYY-MM-DD`. */
  readonly workDate: string;
}

const CIVIL_DAY_MS = 86_400_000;

/**
 * Civil date (`YYYY-MM-DD`) of an instant in a zone.
 *
 * `en-CA` is used for its guaranteed `YYYY-MM-DD` part ordering, matching the
 * technique `browserWorkClock` already uses. Never `toISOString().slice(0, 10)`,
 * which would answer in UTC rather than the Principal's civil day.
 */
export function civilDayInZone(iso: string, timezone: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) {
    throw new TypeError(`unreadable timestamp: ${iso}`);
  }
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instant);
}

/** Whole civil days from `from` to `to`, both `YYYY-MM-DD`. Negative when `to` is earlier. */
export function civilDayOffset(from: string, to: string): number {
  const start = Date.parse(`${from}T00:00:00Z`);
  const end = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(end)) {
    throw new TypeError(`unreadable civil date: ${from} / ${to}`);
  }
  return Math.round((end - start) / CIVIL_DAY_MS);
}

/** `YYYY-MM-DD` shifted by whole civil days. */
export function addCivilDays(workDate: string, days: number): string {
  const base = Date.parse(`${workDate}T00:00:00Z`);
  if (Number.isNaN(base)) throw new TypeError(`unreadable civil date: ${workDate}`);
  return new Date(base + days * CIVIL_DAY_MS).toISOString().slice(0, 10);
}

function zoneOffsetMs(instant: Date, timezone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(instant);
  const read = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? "0");
  const asUtc = Date.UTC(
    read("year"),
    read("month") - 1,
    read("day"),
    read("hour") % 24,
    read("minute"),
    read("second"),
  );
  return asUtc - instant.getTime();
}

/**
 * The instant at which a civil date begins in a zone, as an ISO timestamp.
 *
 * Used to turn a `Today` / `Tomorrow` / picked-date intent into the timestamp the
 * landed contract accepts, without guessing a UTC day boundary.
 */
export function civilDayStartIso(workDate: string, timezone: string): string {
  const naive = new Date(`${workDate}T00:00:00Z`);
  if (Number.isNaN(naive.getTime())) throw new TypeError(`unreadable civil date: ${workDate}`);
  const firstOffset = zoneOffsetMs(naive, timezone);
  let instant = new Date(naive.getTime() - firstOffset);
  const settledOffset = zoneOffsetMs(instant, timezone);
  if (settledOffset !== firstOffset) {
    instant = new Date(naive.getTime() - settledOffset);
  }
  return instant.toISOString();
}

/* ------------------------------------------------------------------ *
 * Due presentation
 * ------------------------------------------------------------------ */

export type TaskDueTone = "none" | "today" | "tomorrow" | "overdue" | "scheduled";

export interface TaskDuePresentation {
  /** Concise human phrase. Never a raw timestamp. */
  readonly phrase: string;
  readonly tone: TaskDueTone;
  /** Whole civil days overdue, or null when not overdue. */
  readonly overdueDays: number | null;
  readonly iso: string | null;
}

export interface FormatTaskDueOptions {
  /**
   * Append a localized time to the phrase.
   *
   * Off by default: the landed contract types every Task date as an opaque nullable
   * ISO string and does not distinguish a date-only due from one with a meaningful
   * explicit time. Callers opt in only once that semantic exists upstream.
   */
  readonly withExplicitTime?: boolean;
}

export function formatTaskDue(
  dueAt: string | null | undefined,
  clock: TaskCivilClock,
  options: FormatTaskDueOptions = {},
): TaskDuePresentation {
  if (!dueAt) {
    return { phrase: NO_DUE_DATE_LABEL, tone: "none", overdueDays: null, iso: null };
  }

  const dueDay = civilDayInZone(dueAt, clock.timezone);
  const offset = civilDayOffset(clock.workDate, dueDay);
  const time = options.withExplicitTime ? formatCivilTime(dueAt, clock.timezone) : null;
  const withTime = (phrase: string) => (time ? `${phrase} at ${time}` : phrase);

  if (offset === 0) {
    return { phrase: withTime("Today"), tone: "today", overdueDays: null, iso: dueAt };
  }
  if (offset === 1) {
    return { phrase: withTime("Tomorrow"), tone: "tomorrow", overdueDays: null, iso: dueAt };
  }
  if (offset < 0) {
    const days = Math.abs(offset);
    return {
      phrase: `Overdue by ${days} ${days === 1 ? "day" : "days"}`,
      tone: "overdue",
      overdueDays: days,
      iso: dueAt,
    };
  }
  return {
    phrase: withTime(formatCivilDate(dueAt, clock)),
    tone: "scheduled",
    overdueDays: null,
    iso: dueAt,
  };
}

function formatCivilDate(iso: string, clock: TaskCivilClock): string {
  const sameYear = civilDayInZone(iso, clock.timezone).slice(0, 4) === clock.workDate.slice(0, 4);
  return new Intl.DateTimeFormat(undefined, {
    timeZone: clock.timezone,
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(new Date(iso));
}

function formatCivilTime(iso: string, timezone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** Concise human phrase for a Planning/Administrative date, or a stated absence. */
export function formatTaskPlanningDate(
  value: string | null | undefined,
  clock: TaskCivilClock,
  absent: string,
): string {
  if (!value) return absent;
  const day = civilDayInZone(value, clock.timezone);
  const offset = civilDayOffset(clock.workDate, day);
  if (offset === 0) return "Today";
  if (offset === 1) return "Tomorrow";
  if (offset === -1) return "Yesterday";
  return formatCivilDate(value, clock);
}

/* ------------------------------------------------------------------ *
 * Presentation model
 * ------------------------------------------------------------------ */

/**
 * The cross-surface Task presentation contract.
 *
 * Every compact Task surface can represent this. No surface is required to render
 * all of it at once.
 */
export interface TaskPresentationModel {
  readonly taskId: string;
  readonly title: string;
  readonly status: TaskLifecycle;
  readonly statusLabel: string;
  readonly active: boolean;
  readonly terminal: boolean;
  readonly terminalSummary: string | null;
  readonly priority: TaskPriority | null;
  readonly priorityLabel: string;
  readonly hasPriority: boolean;
  readonly due: TaskDuePresentation;
  /** Present only when the source is an authoritative, versioned snapshot. */
  readonly version: number | null;
  /**
   * True only when a canonical current snapshot with a trustworthy version is held.
   * A projection seeds display; it never authorizes mutation.
   */
  readonly canMutate: boolean;
  readonly contextLabel: string | null;
}

export interface TaskPresentationOptions {
  readonly clock: TaskCivilClock;
  /** Caller asserts it holds a canonical current snapshot. Defaults to false. */
  readonly canMutate?: boolean;
  readonly contextLabel?: string | null;
  readonly due?: FormatTaskDueOptions;
}

export function toTaskPresentationModel(
  task: TaskRow | TaskDetail,
  options: TaskPresentationOptions,
): TaskPresentationModel {
  const version = typeof task.version === "number" ? task.version : null;
  const terminal = isTerminalTaskStatus(task.lifecycle_state);
  return {
    taskId: task.task_id,
    title: task.title,
    status: task.lifecycle_state,
    statusLabel: formatTaskStatus(task.lifecycle_state),
    active: !terminal,
    terminal,
    terminalSummary: terminalTaskSummary(task.lifecycle_state),
    priority: task.priority,
    priorityLabel: formatTaskPriority(task.priority),
    hasPriority: task.priority !== null && task.priority !== undefined,
    due: formatTaskDue(task.due_at, options.clock, options.due),
    version,
    canMutate: Boolean(options.canMutate) && version !== null,
    contextLabel: options.contextLabel ?? null,
  };
}
