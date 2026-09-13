"use client";

/**
 * Generic foreground revalidation controller (extracted for WP-TUX-07).
 *
 * This module owns the repository's ONE foreground freshness policy. It was
 * extracted verbatim out of `useTaskFreshness` so a non-Task surface (Today /
 * Pulse) can share the exact same cadence without being forced to hold a
 * `TaskQueryKey` — `buildTaskQueryKey` only admits modes
 * `list|search|detail|comments`, so a Pulse query cannot express itself as one,
 * and duplicating the policy would create a second, divergent cadence.
 *
 * For an enabled, visible, online surface:
 * - ~5000ms interval polling of the active query identity;
 * - immediate revalidate on window focus, hidden→visible, online regain,
 *   and post-mutation hooks;
 * - continuous poll suspended while hidden or offline;
 * - at most one ordinary in-flight read per identity (via the coordinator);
 * - transport backoff 5s → 10s → 30s max; focus/visibility/online/mutation/
 *   manual bypass the delay gate;
 * - 401 suspends noisy polling; 403 fail-closed suspend; 503 retains confirmed,
 *   marks stale, backs off, and emits at most one deduped notice.
 *
 * No jitter: single-operator MCV does not need stampede protection.
 *
 * Everything here is keyed by an OPAQUE `queryId: string`. The coordinator seam
 * below is declared structurally so `TaskReadCoordinator` satisfies it with no
 * change, and any other keyed read coordinator can too.
 */

import { useEffect, useRef, useState } from "react";

export const FOREGROUND_REVALIDATION_INTERVAL_MS = 5_000;
export const FOREGROUND_REVALIDATION_BACKOFF_MS = [5_000, 10_000, 30_000] as const;

export type ForegroundRevalidationTrigger =
  | "interval"
  | "focus"
  | "visibility"
  | "online"
  | "mutation"
  | "manual";

export type ForegroundRevalidationNoticeKind = "auth" | "forbidden" | "degraded";

export interface ForegroundRevalidationNotice {
  readonly kind: ForegroundRevalidationNoticeKind;
  readonly message: string;
}

/**
 * Mirror of the keyed-read freshness lattice. Declared here (rather than
 * imported from the Task read coordinator) so this module stays free of Task
 * types; the adapter's explicit type arguments make any drift a compile error.
 */
export type ForegroundFreshnessStatus =
  | "idle"
  | "fresh"
  | "stale"
  | "loading"
  | "unavailable"
  | "suspended";

/** The part of a coordinator snapshot this controller surfaces as state. */
export interface ForegroundQuerySnapshot<TData> {
  readonly freshness: ForegroundFreshnessStatus;
  readonly lastConfirmed: TData | undefined;
  readonly lastSuccessfulAt: number | null;
}

/** The part of a coordinator read result this controller inspects. */
export interface ForegroundReadResult {
  readonly outcome: string;
  readonly silent?: boolean;
  readonly error?: unknown;
}

/**
 * Structural view of the keyed read coordinator: exactly the members this
 * controller calls, and nothing more. `TaskReadCoordinator<T>` satisfies this
 * as-is.
 */
export interface ForegroundReadCoordinator<TData, TKey, TFetcher, TResult, TSnapshot> {
  retain(key: TKey): unknown;
  release(key: TKey): void;
  subscribe(key: TKey, listener: (snapshot: TSnapshot) => void): () => void;
  read(key: TKey, fetcher: TFetcher, options: { readonly force: boolean }): Promise<TResult>;
  getSnapshot(key: TKey): TSnapshot | undefined;
  markFresh(key: TKey): void;
  markStale(key: TKey): void;
  markSuspended(key: TKey): void;
  applyConfirmed(key: TKey, data: TData): unknown;
  raiseMutationBarrier(key: TKey): unknown;
}

/**
 * Minimal structural view of the session-scoped reconciliation seam owned by
 * `TaskRuntimeProvider`. Declared structurally so this controller keeps no
 * dependency on the provider module and stays usable in isolation.
 */
export interface ForegroundReconciliationRegistrar {
  readonly registerActiveTaskQuery: (
    queryId: string,
    revalidate: () => void | Promise<unknown>,
  ) => () => void;
  readonly unregisterActiveTaskQuery: (queryId: string) => void;
}

export interface ForegroundRevalidationMessages {
  readonly auth: string;
  readonly forbidden: string;
  readonly degraded: string;
}

const DEFAULT_MESSAGES: ForegroundRevalidationMessages = {
  auth: "Session expired. Sign in again to refresh.",
  forbidden: "Refresh is not permitted for this session.",
  degraded: "Updates are temporarily unavailable.",
};

let registrationSequence = 0;

export interface UseForegroundRevalidationOptions<TData, TKey, TFetcher, TResult, TSnapshot> {
  /** Opaque, stable identity of the active query. Compared with `===`. */
  readonly queryId: string;
  /** Opaque key handed back to the coordinator verbatim. */
  readonly queryKey: TKey;
  /** Surface is mounted and eligible to poll. */
  readonly enabled: boolean;
  readonly coordinator: ForegroundReadCoordinator<TData, TKey, TFetcher, TResult, TSnapshot>;
  readonly fetcher: TFetcher;
  readonly onResult?: (result: TResult, snapshot: TSnapshot) => void;
  readonly onNotice?: (notice: ForegroundRevalidationNotice) => void;
  /**
   * Session-scoped confirmed-create reconciliation seam. While this query is
   * mounted and enabled it registers its own `notifyMutationConfirmed` so any
   * confirmed create — including one launched elsewhere in the shell —
   * revalidates it. Registration owns no timer of its own.
   */
  readonly reconciliation?: ForegroundReconciliationRegistrar;
  /** Surface-specific notice copy. */
  readonly messages?: ForegroundRevalidationMessages;
  /** Wall-clock / interval overrides for tests. */
  readonly intervalMs?: number;
  readonly backoffMs?: readonly number[];
}

export interface UseForegroundRevalidationResult<TData, TResult> {
  readonly freshness: ForegroundFreshnessStatus;
  readonly lastSuccessfulAt: number | null;
  readonly lastConfirmed: TData | undefined;
  readonly suspended: boolean;
  readonly revalidate: (trigger?: ForegroundRevalidationTrigger) => Promise<TResult | undefined>;
  /** Call after a confirmed local mutation to barrier + immediate revalidate. */
  readonly notifyMutationConfirmed: (data?: TData) => Promise<TResult | undefined>;
}

export class ForegroundRevalidationHttpError extends Error {
  readonly status: number;

  constructor(status: number, message = `HTTP ${status}`) {
    super(message);
    this.name = "ForegroundRevalidationHttpError";
    this.status = status;
  }
}

function readHttpStatus(error: unknown): number | null {
  if (error instanceof ForegroundRevalidationHttpError) return error.status;
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

export function useForegroundRevalidation<
  TData,
  TKey,
  TFetcher,
  TResult extends ForegroundReadResult,
  TSnapshot extends ForegroundQuerySnapshot<TData>,
>(
  options: UseForegroundRevalidationOptions<TData, TKey, TFetcher, TResult, TSnapshot>,
): UseForegroundRevalidationResult<TData, TResult> {
  const {
    queryId,
    queryKey,
    enabled,
    coordinator,
    fetcher,
    onResult,
    onNotice,
    reconciliation,
    messages = DEFAULT_MESSAGES,
    intervalMs = FOREGROUND_REVALIDATION_INTERVAL_MS,
    backoffMs = FOREGROUND_REVALIDATION_BACKOFF_MS,
  } = options;

  const [freshness, setFreshness] = useState<ForegroundFreshnessStatus>("idle");
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<number | null>(null);
  const [lastConfirmed, setLastConfirmed] = useState<TData | undefined>(undefined);

  const keyRef = useRef(queryKey);
  const queryIdRef = useRef(queryId);
  const fetcherRef = useRef(fetcher);
  const onResultRef = useRef(onResult);
  const onNoticeRef = useRef(onNotice);
  const messagesRef = useRef(messages);
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
  const revalidateRef = useRef<(trigger?: ForegroundRevalidationTrigger) => Promise<TResult | undefined>>(
    async () => undefined,
  );
  const notifyMutationRef = useRef<(data?: TData) => Promise<TResult | undefined>>(async () => undefined);

  /** Suspended only while the same query identity remains active. */
  const [suspendedQueryId, setSuspendedQueryId] = useState<string | null>(null);
  const suspended = suspendedQueryId === queryId;

  useEffect(() => {
    keyRef.current = queryKey;
    queryIdRef.current = queryId;
    fetcherRef.current = fetcher;
    onResultRef.current = onResult;
    onNoticeRef.current = onNotice;
    messagesRef.current = messages;
    enabledRef.current = enabled;
  }, [queryKey, queryId, fetcher, onResult, onNotice, messages, enabled]);

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
  }, [coordinator, queryId, queryKey]);

  useEffect(() => {
    // Reset backoff / notices when the active query identity changes.
    failureCountRef.current = 0;
    nextAllowedAtRef.current = 0;
    degradedNoticeSentRef.current = false;
    authNoticeSentRef.current = false;
    forbiddenNoticeSentRef.current = false;
    suspendedRef.current = false;
  }, [queryId]);

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

    async function run(trigger: ForegroundRevalidationTrigger): Promise<TResult | undefined> {
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

      // Focus / visibility / online / mutation / manual bypass the backoff gate.
      if (trigger === "focus" || trigger === "visibility" || trigger === "online" || trigger === "mutation" || trigger === "manual") {
        nextAllowedAtRef.current = 0;
      }

      // Ordinary interval reads never stack; coordinator also dedupes.
      if (trigger === "interval" && inFlightRef.current) {
        schedule(cadenceDelay());
        return undefined;
      }

      const key = keyRef.current;
      const id = queryIdRef.current;
      inFlightRef.current = true;
      try {
        const force = trigger === "mutation" || trigger === "manual";
        const result = await coordinator.read(key, fetcherRef.current, { force });
        if (!mountedRef.current || id !== queryIdRef.current) {
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
            setSuspendedQueryId(null);
            coordinator.markFresh(key);
          }
        } else if (result.outcome === "failed" && !result.silent) {
          const status = readHttpStatus(result.error);
          if (status === 401) {
            suspendedRef.current = true;
            setSuspendedQueryId(id);
            coordinator.markSuspended(key);
            clearTimer();
            if (!authNoticeSentRef.current) {
              authNoticeSentRef.current = true;
              onNoticeRef.current?.({
                kind: "auth",
                message: messagesRef.current.auth,
              });
            }
            return result;
          }
          if (status === 403) {
            suspendedRef.current = true;
            setSuspendedQueryId(id);
            coordinator.markSuspended(key);
            clearTimer();
            if (!forbiddenNoticeSentRef.current) {
              forbiddenNoticeSentRef.current = true;
              onNoticeRef.current?.({
                kind: "forbidden",
                message: messagesRef.current.forbidden,
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
                message: messagesRef.current.degraded,
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

    revalidateRef.current = (trigger: ForegroundRevalidationTrigger = "manual") => run(trigger);
    notifyMutationRef.current = async (data?: TData) => {
      const key = keyRef.current;
      if (data !== undefined) {
        coordinator.applyConfirmed(key, data);
      } else {
        coordinator.raiseMutationBarrier(key);
      }
      return run("mutation");
    };

    if (enabled && isDocumentVisible() && isNavigatorOnline() && !suspendedRef.current) {
      void run("manual");
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
  }, [backoffMs, coordinator, enabled, intervalMs, queryId]);

  useEffect(() => {
    if (!reconciliation || !enabled) return;
    // One registration per mounted hook instance, so two hooks sharing a query
    // identity cannot unregister one another.
    registrationSequence += 1;
    const registrationId = `${queryId}#${registrationSequence}`;
    // Called with no argument on purpose: a confirmed create is never applied
    // as list data — it raises the mutation barrier and re-reads the server.
    reconciliation.registerActiveTaskQuery(registrationId, () => notifyMutationRef.current());
    return () => {
      reconciliation.unregisterActiveTaskQuery(registrationId);
    };
  }, [enabled, queryId, reconciliation]);

  return {
    freshness,
    lastSuccessfulAt,
    lastConfirmed,
    suspended,
    revalidate: (trigger: ForegroundRevalidationTrigger = "manual") => revalidateRef.current(trigger),
    notifyMutationConfirmed: (data?: TData) => notifyMutationRef.current(data),
  };
}
