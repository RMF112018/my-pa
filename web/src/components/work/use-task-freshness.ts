"use client";

/**
 * Foreground Task freshness controller for WP-TUX-02.
 *
 * For authenticated, visible, online Task surfaces:
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

import { useEffect, useRef, useState } from "react";
import type { TaskQueryKey } from "@/lib/task/query-key";
import {
  serializeTaskQueryKey,
  taskQueryKeysEqual,
} from "@/lib/task/query-key";
import type {
  TaskFreshnessStatus,
  TaskQuerySnapshot,
  TaskReadCoordinator,
  TaskReadFetcher,
  TaskReadResult,
} from "@/lib/task/read-coordinator";

export const TASK_FRESHNESS_INTERVAL_MS = 5_000;
export const TASK_FRESHNESS_BACKOFF_MS = [5_000, 10_000, 30_000] as const;

export type TaskFreshnessTrigger =
  | "interval"
  | "focus"
  | "visibility"
  | "online"
  | "mutation"
  | "manual";

export type TaskFreshnessNoticeKind = "auth" | "forbidden" | "degraded";

export interface TaskFreshnessNotice {
  readonly kind: TaskFreshnessNoticeKind;
  readonly message: string;
}

export interface UseTaskFreshnessOptions<T> {
  readonly queryKey: TaskQueryKey;
  /** Authenticated Task surface is mounted and eligible to poll. */
  readonly enabled: boolean;
  readonly coordinator: TaskReadCoordinator<T>;
  readonly fetcher: TaskReadFetcher<T>;
  readonly onResult?: (result: TaskReadResult<T>, snapshot: TaskQuerySnapshot<T>) => void;
  readonly onNotice?: (notice: TaskFreshnessNotice) => void;
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

export class TaskFreshnessHttpError extends Error {
  readonly status: number;

  constructor(status: number, message = `HTTP ${status}`) {
    super(message);
    this.name = "TaskFreshnessHttpError";
    this.status = status;
  }
}

function readHttpStatus(error: unknown): number | null {
  if (error instanceof TaskFreshnessHttpError) return error.status;
  if (!error || typeof error !== "object") return null;
  if ("status" in error && typeof (error as { status: unknown }).status === "number") {
    return (error as { status: number }).status;
  }
  if ("statusCode" in error && typeof (error as { statusCode: unknown }).statusCode === "number") {
    return (error as { statusCode: number }).statusCode;
  }
  return null;
}

function isDocumentVisible(): boolean {
  if (typeof document === "undefined") return true;
  return document.visibilityState === "visible";
}

function isNavigatorOnline(): boolean {
  if (typeof navigator === "undefined") return true;
  return navigator.onLine !== false;
}

export function useTaskFreshness<T>(options: UseTaskFreshnessOptions<T>): UseTaskFreshnessResult<T> {
  const {
    queryKey,
    enabled,
    coordinator,
    fetcher,
    onResult,
    onNotice,
    intervalMs = TASK_FRESHNESS_INTERVAL_MS,
    backoffMs = TASK_FRESHNESS_BACKOFF_MS,
  } = options;

  const [freshness, setFreshness] = useState<TaskFreshnessStatus>("idle");
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<number | null>(null);
  const [lastConfirmed, setLastConfirmed] = useState<T | undefined>(undefined);
  const [suspended, setSuspended] = useState(false);

  const keyRef = useRef(queryKey);
  const fetcherRef = useRef(fetcher);
  const onResultRef = useRef(onResult);
  const onNoticeRef = useRef(onNotice);
  const enabledRef = useRef(enabled);
  const suspendedRef = useRef(false);
  const failureCountRef = useRef(0);
  const nextAllowedAtRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const degradedNoticeSentRef = useRef(false);
  const authNoticeSentRef = useRef(false);
  const forbiddenNoticeSentRef = useRef(false);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);
  const revalidateRef = useRef<(trigger?: TaskFreshnessTrigger) => Promise<TaskReadResult<T> | undefined>>(
    async () => undefined,
  );
  const notifyMutationRef = useRef<(data?: T) => Promise<TaskReadResult<T> | undefined>>(async () => undefined);

  keyRef.current = queryKey;
  fetcherRef.current = fetcher;
  onResultRef.current = onResult;
  onNoticeRef.current = onNotice;
  enabledRef.current = enabled;

  const keyId = serializeTaskQueryKey(queryKey);

  useEffect(() => {
    mountedRef.current = true;
    coordinator.retain(queryKey);
    const unsubscribe = coordinator.subscribe(queryKey, (snapshot) => {
      if (!mountedRef.current) return;
      setFreshness(snapshot.freshness);
      setLastSuccessfulAt(snapshot.lastSuccessfulAt);
      setLastConfirmed(snapshot.lastConfirmed);
    });
    return () => {
      mountedRef.current = false;
      unsubscribe();
      coordinator.release(queryKey);
    };
  }, [coordinator, keyId, queryKey]);

  useEffect(() => {
    // Reset backoff / notices when the active query identity changes.
    failureCountRef.current = 0;
    nextAllowedAtRef.current = 0;
    degradedNoticeSentRef.current = false;
    authNoticeSentRef.current = false;
    forbiddenNoticeSentRef.current = false;
    suspendedRef.current = false;
    setSuspended(false);
  }, [keyId]);

  useEffect(() => {
    function clearTimer() {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    }

    function schedule(delayMs: number) {
      clearTimer();
      if (!mountedRef.current || !enabledRef.current || suspendedRef.current) return;
      if (!isDocumentVisible() || !isNavigatorOnline()) return;
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        void run("interval");
      }, delayMs);
    }

    function cadenceDelay(): number {
      const failures = failureCountRef.current;
      if (failures <= 0) return intervalMs;
      const index = Math.min(failures - 1, backoffMs.length - 1);
      return backoffMs[index] ?? intervalMs;
    }

    async function run(trigger: TaskFreshnessTrigger): Promise<TaskReadResult<T> | undefined> {
      if (!mountedRef.current || !enabledRef.current) return undefined;
      if (suspendedRef.current && trigger !== "manual" && trigger !== "mutation") {
        return undefined;
      }
      if (trigger === "interval") {
        if (!isDocumentVisible() || !isNavigatorOnline()) return undefined;
        if (Date.now() < nextAllowedAtRef.current) {
          schedule(Math.max(0, nextAllowedAtRef.current - Date.now()));
          return undefined;
        }
      }
      if (trigger === "interval" || trigger === "focus" || trigger === "visibility" || trigger === "online") {
        if (!isNavigatorOnline() && trigger !== "online") return undefined;
      }

      // Focus / visibility / online / mutation bypass the backoff gate.
      if (trigger === "focus" || trigger === "visibility" || trigger === "online" || trigger === "mutation" || trigger === "manual") {
        nextAllowedAtRef.current = 0;
      }

      // Ordinary interval reads never stack; coordinator also dedupes.
      if (trigger === "interval" && inFlightRef.current) {
        schedule(cadenceDelay());
        return undefined;
      }

      const key = keyRef.current;
      inFlightRef.current = true;
      try {
        const force = trigger === "mutation" || trigger === "manual";
        const result = await coordinator.read(key, fetcherRef.current, { force });
        if (!mountedRef.current || !taskQueryKeysEqual(key, keyRef.current)) {
          return result;
        }

        const snapshot = coordinator.getSnapshot(key);
        if (snapshot) onResultRef.current?.(result, snapshot);

        if (result.outcome === "applied" || result.outcome === "deduped") {
          failureCountRef.current = 0;
          nextAllowedAtRef.current = 0;
          degradedNoticeSentRef.current = false;
          if (suspendedRef.current && result.outcome === "applied") {
            suspendedRef.current = false;
            setSuspended(false);
            coordinator.markFresh(key);
          }
        } else if (result.outcome === "failed" && !result.silent) {
          const status = readHttpStatus(result.error);
          if (status === 401) {
            suspendedRef.current = true;
            setSuspended(true);
            coordinator.markSuspended(key);
            clearTimer();
            if (!authNoticeSentRef.current) {
              authNoticeSentRef.current = true;
              onNoticeRef.current?.({
                kind: "auth",
                message: "Session expired. Sign in again to refresh tasks.",
              });
            }
            return result;
          }
          if (status === 403) {
            suspendedRef.current = true;
            setSuspended(true);
            coordinator.markSuspended(key);
            clearTimer();
            if (!forbiddenNoticeSentRef.current) {
              forbiddenNoticeSentRef.current = true;
              onNoticeRef.current?.({
                kind: "forbidden",
                message: "Task refresh is not permitted for this session.",
              });
            }
            return result;
          }
          failureCountRef.current += 1;
          const delay = cadenceDelay();
          nextAllowedAtRef.current = Date.now() + delay;
          if (status === 503 || status === null) {
            coordinator.markStale(key);
            if (status === 503 && !degradedNoticeSentRef.current) {
              degradedNoticeSentRef.current = true;
              onNoticeRef.current?.({
                kind: "degraded",
                message: "Task updates are temporarily unavailable.",
              });
            }
          }
        }

        if (!suspendedRef.current && isDocumentVisible() && isNavigatorOnline()) {
          schedule(cadenceDelay());
        }
        return result;
      } finally {
        inFlightRef.current = false;
      }
    }

    function onFocus() {
      void run("focus");
    }

    function onVisibility() {
      if (document.visibilityState === "visible") {
        void run("visibility");
      } else {
        clearTimer();
      }
    }

    function onOnline() {
      void run("online");
    }

    function onOffline() {
      clearTimer();
    }

    revalidateRef.current = (trigger: TaskFreshnessTrigger = "manual") => run(trigger);
    notifyMutationRef.current = async (data?: T) => {
      const key = keyRef.current;
      if (data !== undefined) {
        coordinator.applyConfirmed(key, data);
      } else {
        coordinator.raiseMutationBarrier(key);
      }
      return run("mutation");
    };

    if (enabled && isDocumentVisible() && isNavigatorOnline() && !suspendedRef.current) {
      schedule(intervalMs);
    }

    if (typeof window !== "undefined") {
      window.addEventListener("focus", onFocus);
      window.addEventListener("online", onOnline);
      window.addEventListener("offline", onOffline);
    }
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }

    return () => {
      clearTimer();
      revalidateRef.current = async () => undefined;
      notifyMutationRef.current = async () => undefined;
      if (typeof window !== "undefined") {
        window.removeEventListener("focus", onFocus);
        window.removeEventListener("online", onOnline);
        window.removeEventListener("offline", onOffline);
      }
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    };
  }, [backoffMs, coordinator, enabled, intervalMs, keyId]);

  return {
    freshness,
    lastSuccessfulAt,
    lastConfirmed,
    suspended,
    revalidate: (trigger: TaskFreshnessTrigger = "manual") => revalidateRef.current(trigger),
    notifyMutationConfirmed: (data?: T) => notifyMutationRef.current(data),
  };
}
