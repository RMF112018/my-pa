"use client";

/**
 * Foreground Task freshness adapter for WP-TUX-02.
 *
 * The timing / event / backoff policy itself lives in
 * `@/lib/task/use-foreground-revalidation` (extracted in WP-TUX-07): a Today /
 * Pulse query cannot hold a `TaskQueryKey` — `buildTaskQueryKey` only admits
 * modes `list|search|detail|comments` — and duplicating this policy would
 * create the second, divergent foreground cadence the architecture forbids.
 *
 * This module is now only the Task binding over that one controller: it turns a
 * canonical `TaskQueryKey` into the controller's opaque string identity, hands
 * over the `TaskReadCoordinator` (which satisfies the controller's structural
 * coordinator seam unchanged), and supplies Task notice copy.
 *
 * Behaviour is unchanged:
 * - ~5000ms interval polling of the active query key;
 * - immediate revalidate on window focus, hidden→visible, online regain,
 *   and post-mutation hooks;
 * - continuous poll suspended while hidden or offline;
 * - at most one ordinary in-flight read per key (via TaskReadCoordinator);
 * - transport backoff 5s → 10s → 30s max; focus/visibility/online bypass delay;
 * - 401 suspends noisy polling; 403 fail-closed suspend; 503 retains confirmed,
 *   marks stale, backs off, and emits at most one deduped notice.
 *
 * No jitter: single-operator MCV does not need stampede protection.
 */

import type { TaskQueryKey } from "@/lib/task/query-key";
import { serializeTaskQueryKey } from "@/lib/task/query-key";
import type {
  TaskFreshnessStatus,
  TaskQuerySnapshot,
  TaskReadCoordinator,
  TaskReadFetcher,
  TaskReadResult,
} from "@/lib/task/read-coordinator";
import type {
  ForegroundReconciliationRegistrar,
  ForegroundRevalidationMessages,
  ForegroundRevalidationNotice,
  ForegroundRevalidationNoticeKind,
  ForegroundRevalidationTrigger,
} from "@/lib/task/use-foreground-revalidation";
import {
  FOREGROUND_REVALIDATION_BACKOFF_MS,
  FOREGROUND_REVALIDATION_INTERVAL_MS,
  ForegroundRevalidationHttpError,
  useForegroundRevalidation,
} from "@/lib/task/use-foreground-revalidation";

export const TASK_FRESHNESS_INTERVAL_MS = FOREGROUND_REVALIDATION_INTERVAL_MS;
export const TASK_FRESHNESS_BACKOFF_MS = FOREGROUND_REVALIDATION_BACKOFF_MS;

export type TaskFreshnessTrigger = ForegroundRevalidationTrigger;

export type TaskFreshnessNoticeKind = ForegroundRevalidationNoticeKind;

export type TaskFreshnessNotice = ForegroundRevalidationNotice;

/**
 * Minimal structural view of the session-scoped reconciliation seam owned by
 * `TaskRuntimeProvider`. Declared structurally so this hook keeps no dependency
 * on the provider module and stays usable in isolation.
 */
export type TaskQueryReconciliationRegistrar = ForegroundReconciliationRegistrar;

/** Task-surface notice copy. Unchanged wording from WP-TUX-02. */
const TASK_FRESHNESS_MESSAGES: ForegroundRevalidationMessages = {
  auth: "Session expired. Sign in again to refresh tasks.",
  forbidden: "Task refresh is not permitted for this session.",
  degraded: "Task updates are temporarily unavailable.",
};

export interface UseTaskFreshnessOptions<T> {
  readonly queryKey: TaskQueryKey;
  /** Authenticated Task surface is mounted and eligible to poll. */
  readonly enabled: boolean;
  readonly coordinator: TaskReadCoordinator<T>;
  readonly fetcher: TaskReadFetcher<T>;
  readonly onResult?: (result: TaskReadResult<T>, snapshot: TaskQuerySnapshot<T>) => void;
  readonly onNotice?: (notice: TaskFreshnessNotice) => void;
  /**
   * Session-scoped confirmed-create reconciliation seam. While this query is
   * mounted and enabled it registers its own `notifyMutationConfirmed` so any
   * confirmed Task create — including one launched from the shell, outside Work
   * — revalidates it. Registration owns no timer of its own.
   */
  readonly reconciliation?: TaskQueryReconciliationRegistrar;
  /** Wall-clock / interval overrides for tests. */
  readonly intervalMs?: number;
  readonly backoffMs?: readonly number[];
}

export interface UseTaskFreshnessResult<T> {
  readonly freshness: TaskFreshnessStatus;
  readonly lastSuccessfulAt: number | null;
  readonly lastConfirmed: T | undefined;
  readonly suspended: boolean;
  readonly revalidate: (trigger?: TaskFreshnessTrigger) => Promise<TaskReadResult<T> | undefined>;
  /** Call after a confirmed local mutation to barrier + immediate revalidate. */
  readonly notifyMutationConfirmed: (data?: T) => Promise<TaskReadResult<T> | undefined>;
}

export class TaskFreshnessHttpError extends ForegroundRevalidationHttpError {
  constructor(status: number, message = `HTTP ${status}`) {
    super(status, message);
    this.name = "TaskFreshnessHttpError";
  }
}

export function useTaskFreshness<T>(options: UseTaskFreshnessOptions<T>): UseTaskFreshnessResult<T> {
  const {
    queryKey,
    enabled,
    coordinator,
    fetcher,
    onResult,
    onNotice,
    reconciliation,
    intervalMs,
    backoffMs,
  } = options;

  return useForegroundRevalidation<
    T,
    TaskQueryKey,
    TaskReadFetcher<T>,
    TaskReadResult<T>,
    TaskQuerySnapshot<T>
  >({
    queryId: serializeTaskQueryKey(queryKey),
    queryKey,
    enabled,
    coordinator,
    fetcher,
    onResult,
    onNotice,
    reconciliation,
    messages: TASK_FRESHNESS_MESSAGES,
    intervalMs,
    backoffMs,
  });
}
