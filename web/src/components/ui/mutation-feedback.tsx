"use client";

/**
 * Shell-persistent mutation feedback queue.
 *
 * Mounted at AppShell lifetime (via TaskRuntimeProvider or directly) so Create /
 * Close / Cancel confirmations and conflicts survive the source form or sheet
 * unmounting. Reuses `LiveAnnouncement` for polite status vs assertive alert
 * semantics; never steals focus.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { LiveAnnouncement } from "@/components/ui/live-region";

export type MutationFeedbackKind = "success" | "error" | "conflict" | "info";
export type MutationFeedbackTone = "status" | "alert";

/** One queued outcome. `eventId` is the stable dedupe identity. */
export interface MutationFeedbackItem {
  readonly eventId: string;
  readonly kind: MutationFeedbackKind;
  readonly message: string;
  readonly tone: MutationFeedbackTone;
  readonly createdAt: number;
  /** When true, item stays until dismissed (errors/conflicts default to this). */
  readonly persistent?: boolean;
}

export type MutationFeedbackPublishInput = {
  readonly eventId: string;
  readonly kind: MutationFeedbackKind;
  readonly message: string;
  readonly tone?: MutationFeedbackTone;
  readonly createdAt?: number;
  readonly persistent?: boolean;
};

export interface MutationFeedbackValue {
  readonly items: readonly MutationFeedbackItem[];
  /** Publish an outcome. Identical `eventId` is a no-op (dedupe). */
  readonly publish: (item: MutationFeedbackPublishInput) => void;
  /**
   * Background poll / freshness degraded notice. Same stable `eventId` must be
   * reused across intervals so live regions are not spammed.
   */
  readonly publishPollNotice: (item: MutationFeedbackPublishInput) => void;
  readonly dismiss: (eventId: string) => void;
  readonly clear: () => void;
}

const SUCCESS_TTL_MS = 5_000;
const MAX_STACK = 3;

const MutationFeedbackContext = createContext<MutationFeedbackValue | null>(null);

function defaultPersistent(kind: MutationFeedbackKind, explicit?: boolean): boolean {
  if (explicit !== undefined) return explicit;
  return kind === "error" || kind === "conflict";
}

function defaultTone(
  kind: MutationFeedbackKind,
  explicit?: MutationFeedbackTone,
): MutationFeedbackTone {
  if (explicit !== undefined) return explicit;
  return kind === "error" || kind === "conflict" ? "alert" : "status";
}

function normalizeItem(input: MutationFeedbackPublishInput, now: number): MutationFeedbackItem {
  const kind = input.kind;
  return {
    eventId: input.eventId,
    kind,
    message: input.message,
    tone: defaultTone(kind, input.tone),
    createdAt: input.createdAt ?? now,
    persistent: defaultPersistent(kind, input.persistent),
  };
}

function pushBounded(
  current: readonly MutationFeedbackItem[],
  next: MutationFeedbackItem,
): readonly MutationFeedbackItem[] {
  if (current.some((item) => item.eventId === next.eventId)) {
    return current;
  }
  return [next, ...current].slice(0, MAX_STACK);
}

export function MutationFeedbackProvider({
  children,
  now = () => Date.now(),
  successTtlMs = SUCCESS_TTL_MS,
}: {
  readonly children: ReactNode;
  /** Injectable clock for tests. */
  readonly now?: () => number;
  readonly successTtlMs?: number;
}) {
  const [items, setItems] = useState<readonly MutationFeedbackItem[]>([]);
  const expiryTimers = useRef<Map<string, number>>(new Map());
  const knownIds = useRef<Set<string>>(new Set());

  const clearExpiry = useCallback((eventId: string) => {
    const handle = expiryTimers.current.get(eventId);
    if (handle !== undefined) {
      window.clearTimeout(handle);
      expiryTimers.current.delete(eventId);
    }
  }, []);

  const dismiss = useCallback(
    (eventId: string) => {
      clearExpiry(eventId);
      knownIds.current.delete(eventId);
      setItems((current) => current.filter((item) => item.eventId !== eventId));
    },
    [clearExpiry],
  );

  const clear = useCallback(() => {
    for (const eventId of [...expiryTimers.current.keys()]) {
      clearExpiry(eventId);
    }
    knownIds.current.clear();
    setItems([]);
  }, [clearExpiry]);

  const scheduleExpiry = useCallback(
    (item: MutationFeedbackItem) => {
      if (item.persistent) return;
      clearExpiry(item.eventId);
      const handle = window.setTimeout(() => {
        expiryTimers.current.delete(item.eventId);
        knownIds.current.delete(item.eventId);
        setItems((current) => current.filter((entry) => entry.eventId !== item.eventId));
      }, successTtlMs);
      expiryTimers.current.set(item.eventId, handle);
    },
    [clearExpiry, successTtlMs],
  );

  const publish = useCallback(
    (input: MutationFeedbackPublishInput) => {
      const item = normalizeItem(input, now());
      if (knownIds.current.has(item.eventId)) {
        return;
      }
      knownIds.current.add(item.eventId);
      setItems((current) => {
        const next = pushBounded(current, item);
        const kept = new Set(next.map((entry) => entry.eventId));
        for (const id of [...knownIds.current]) {
          if (!kept.has(id)) {
            knownIds.current.delete(id);
            clearExpiry(id);
          }
        }
        return next;
      });
      scheduleExpiry(item);
    },
    [clearExpiry, now, scheduleExpiry],
  );

  const publishPollNotice = useCallback(
    (input: MutationFeedbackPublishInput) => {
      publish({
        ...input,
        kind: input.kind ?? "info",
        tone: input.tone ?? "status",
        persistent: input.persistent ?? true,
      });
    },
    [publish],
  );

  useEffect(() => {
    return () => {
      for (const handle of expiryTimers.current.values()) {
        window.clearTimeout(handle);
      }
      expiryTimers.current.clear();
      knownIds.current.clear();
    };
  }, []);

  const value = useMemo<MutationFeedbackValue>(
    () => ({
      items,
      publish,
      publishPollNotice,
      dismiss,
      clear,
    }),
    [items, publish, publishPollNotice, dismiss, clear],
  );

  return (
    <MutationFeedbackContext.Provider value={value}>
      {children}
      <MutationFeedbackRegion items={items} onDismiss={dismiss} />
    </MutationFeedbackContext.Provider>
  );
}

/**
 * Fixed feedback region: stays visible above mobile bottom nav / safe-area.
 * Pointer-events only on interactive dismiss controls so it never covers the app.
 */
export function MutationFeedbackRegion({
  items,
  onDismiss,
}: {
  readonly items: readonly MutationFeedbackItem[];
  readonly onDismiss: (eventId: string) => void;
}) {
  if (items.length === 0) return null;

  return (
    <div
      data-testid="mutation-feedback-region"
      className="pointer-events-none fixed inset-x-0 z-40 flex flex-col justify-start gap-2 px-3"
      style={{
        // Upper overlay preferred on narrow viewports; bottom inset keeps clear of nav.
        top: "max(0.75rem, env(safe-area-inset-top))",
        paddingBottom: "calc(var(--nav-height, 3.5rem) + env(safe-area-inset-bottom, 0px) + 0.75rem)",
      }}
    >
      <ul className="mx-auto flex w-full max-w-lg flex-col gap-2" aria-label="Mutation feedback">
        {items.map((item) => (
          <li
            key={item.eventId}
            data-testid={`mutation-feedback-item-${item.eventId}`}
            data-kind={item.kind}
            data-tone={item.tone}
            className="pointer-events-auto rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2 shadow-sm"
          >
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <LiveAnnouncement tone={item.tone} testId={`mutation-feedback-live-${item.eventId}`}>
                  {item.message}
                </LiveAnnouncement>
              </div>
              {item.persistent ? (
                <button
                  type="button"
                  className="shrink-0 text-sm text-muted underline-offset-2 hover:underline"
                  onClick={() => onDismiss(item.eventId)}
                  data-testid={`mutation-feedback-dismiss-${item.eventId}`}
                >
                  Dismiss
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function useMutationFeedback(): MutationFeedbackValue {
  const value = useContext(MutationFeedbackContext);
  if (!value) {
    throw new Error("useMutationFeedback is only valid inside MutationFeedbackProvider");
  }
  return value;
}

/** Stable event identities for outcomes that must always publish globally. */
export const MutationFeedbackEvent = {
  createConfirmed: (intentId: string) => `task:create:confirmed:${intentId}`,
  closeConfirmed: (taskId: string, intentId: string) => `task:close:confirmed:${taskId}:${intentId}`,
  cancelConfirmed: (taskId: string, intentId: string) =>
    `task:cancel:confirmed:${taskId}:${intentId}`,
  conflict: (taskId: string, intentId: string) => `task:conflict:${taskId}:${intentId}`,
  mutationFailure: (taskId: string, intentId: string) => `task:failure:${taskId}:${intentId}`,
  filterRemoval: (taskId: string, intentId: string) => `task:filter-removal:${taskId}:${intentId}`,
  /** Reuse this exact id across poll intervals to avoid live-region spam. */
  pollDegraded: (queryKey: string) => `task:poll:degraded:${queryKey}`,
} as const;
