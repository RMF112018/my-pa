"use client";

/**
 * Today's client half: the surface that keeps the Pulse fresh after the server
 * has answered once (WP-TUX-07).
 *
 * ## Why this exists, and where the boundary is
 *
 * `today/page.tsx` stays a server component and keeps everything only a server
 * can honestly do: authenticate, short-circuit the synthetic build, read
 * `continuity.pulse` through the server-only transport, and classify that one
 * outcome with `surfaceAnswer`. It deliberately does **not** call its own
 * `/api/pulse` route — the file comment there records the reason, and it has not
 * changed: a server component calling its own API route is a second copy of the
 * same decision.
 *
 * What the server cannot do is notice that the day moved on. So the classified
 * answer crosses the boundary once, as a `TodayPulseAnswer`, and from then on
 * this component owns the reading: `/api/pulse`, which already exists, is
 * `requirePrincipal`-guarded, accepts no payload, and derives the Principal from
 * the session cookie alone.
 *
 * ## One cadence, not a second one
 *
 * Every revalidation here goes through `useForegroundRevalidation` — the
 * repository's one foreground policy (5s cadence; immediate on focus,
 * visibility, online and mutation; suspended while hidden or offline;
 * 5→10→30s backoff; 401/403 suspend; 503 keeps the confirmed answer and says
 * so). There is no timer, no listener and no polling loop in this file.
 *
 * That controller is keyed by a `TaskReadCoordinator`-shaped seam, and a Pulse
 * read cannot hold a `TaskQueryKey` — `buildTaskQueryKey` admits only
 * `list|search|detail|comments` over the resource `tasks`, and Today is none of
 * them. The adapter is therefore the smallest honest one: a single-identity read
 * coordinator over an opaque string key, below, implementing exactly the members
 * the controller calls. The *policy* is not forked; only the key type is.
 *
 * ## The five answers, and the one that is a claim
 *
 * success+rows, authoritative empty, degraded+rows, degraded+zero, and
 * unavailable stay five distinct things. `empty` is the only one that asserts
 * anything about the Principal's record, so it is reachable *only* from a whole,
 * successful answer that carried no rows. A failed refresh, a partial refresh,
 * or a refresh the backend answered with `coverage: "unavailable"` retains the
 * last confirmed answer and marks the surface stale; none of them can clear the
 * surface to Empty, because "the read did not happen" and "you have nothing"
 * are different sentences and only one of them is about the reader.
 *
 * Answers are replaced in one `setState`, so no render ever falls between an old
 * answer and a new one. Backend order is carried through untouched — see
 * `BackendPulseList`.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { BackendPulseList } from "@/components/pulse/backend-pulse-list";
import { DegradedBanner, SurfaceState } from "@/components/ui/surface-state";
import { useTaskRuntime } from "@/components/work/task-runtime-provider";
import {
  ForegroundRevalidationHttpError,
  useForegroundRevalidation,
  type ForegroundFreshnessStatus,
  type ForegroundQuerySnapshot,
  type ForegroundReadCoordinator,
  type ForegroundReadResult,
  type ForegroundRevalidationNotice,
} from "@/lib/task/use-foreground-revalidation";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { BackendPulseItem, TodayPulseAnswer } from "@/contracts/views";

/**
 * The sentence an authoritative quiet day is allowed to say, and the only one.
 * It is a claim about the Principal's record, so it is never printed for a read
 * that failed or came back partial.
 */
export const TODAY_EMPTY_COPY = "Nothing needs your attention right now.";

/** Registration id in the session reconciliation registry. A plain string. */
export const TODAY_PULSE_QUERY_ID = "today:pulse";

/** Notice copy for this surface. Recoverable, and never "your tasks are gone". */
const TODAY_MESSAGES = {
  auth: "Session expired. Sign in again to refresh Today.",
  forbidden: "Refreshing Today is not permitted for this session.",
  degraded: "Today could not be refreshed just now. What is shown is the last confirmed read.",
} as const;

const STALE_COPY =
  "This is the last confirmed read. The refresh did not complete, so something may have " +
  "changed since.";

/** What one `/api/pulse` answer carries. */
export interface PulseReadPayload {
  readonly items: readonly BackendPulseItem[];
  readonly disclosure: DisclosureEnvelope;
}

type PulseReadOutcome = "applied" | "deduped" | "superseded" | "aborted" | "barrier_blocked" | "failed";

interface PulseReadResult extends ForegroundReadResult {
  readonly outcome: PulseReadOutcome;
  readonly data?: PulseReadPayload;
  readonly silent: boolean;
  readonly sequence: number;
}

interface PulseSnapshot extends ForegroundQuerySnapshot<PulseReadPayload> {
  readonly freshness: ForegroundFreshnessStatus;
}

type PulseFetcher = (context: {
  readonly signal: AbortSignal;
  readonly force: boolean;
}) => Promise<PulseReadPayload>;

/**
 * Classify one `/api/pulse` answer into the same five-way shape the server's
 * `surfaceAnswer` produces.
 *
 * The order of the branches is the whole point and it matches `surfaceAnswer`:
 * coverage is read before rows are counted, so a backend that says "this scope
 * was not searched" can never be counted as a quiet day.
 */
export function classifyPulsePayload(payload: PulseReadPayload): TodayPulseAnswer {
  const { items, disclosure } = payload;
  const limitations = disclosure.limitations ?? [];

  if (disclosure.coverage === "unavailable") {
    return {
      kind: "unavailable",
      error: {
        errorClass: "unavailable",
        code: "coverage_unavailable",
        message:
          "The backend answered, and reported that this scope was not searched. " +
          "No conclusion about what you hold follows from it.",
      },
      limitations,
    };
  }

  if (disclosure.coverage === "partial" || disclosure.truncated) {
    return { kind: "degraded", items, limitations, truncated: disclosure.truncated === true };
  }

  if (items.length === 0) return { kind: "empty" };

  return { kind: "records", items };
}

/**
 * Read `/api/pulse`. No payload, no principal, no query — the route accepts
 * none, and the session cookie is the whole of the identity.
 */
const readPulse: PulseFetcher = async ({ signal }) => {
  const response = await fetch("/api/pulse", {
    method: "GET",
    signal,
    cache: "no-store",
    credentials: "same-origin",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new ForegroundRevalidationHttpError(response.status, `pulse read failed (${response.status})`);
  }
  const body: unknown = await response.json();
  if (!body || typeof body !== "object") throw new Error("pulse answer was not an object");
  const candidate = body as { shape?: unknown; items?: unknown; disclosure?: unknown };
  // A synthetic build never reaches this surface: the page short-circuits to the
  // fixture list. Anything but the backend shape is a payload this surface has
  // no honest reading of, so it is a failed read rather than a silent Empty.
  if (candidate.shape !== "backend") throw new Error("pulse answer was not the backend shape");
  if (!Array.isArray(candidate.items)) throw new Error("pulse answer carried no items array");
  if (!candidate.disclosure || typeof candidate.disclosure !== "object") {
    throw new Error("pulse answer carried no disclosure");
  }
  return {
    items: candidate.items as readonly BackendPulseItem[],
    disclosure: candidate.disclosure as DisclosureEnvelope,
  };
};

interface PulseEntry {
  freshness: ForegroundFreshnessStatus;
  lastConfirmed: PulseReadPayload | undefined;
  lastSuccessfulAt: number | null;
  controller: AbortController | null;
  inFlight: Promise<PulseReadResult> | null;
  requestSequence: number;
  lastAppliedSequence: number;
  mutationBarrier: number;
  refCount: number;
  readonly listeners: Set<(snapshot: PulseSnapshot) => void>;
}

function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const name = "name" in error ? String((error as { name?: unknown }).name) : "";
  return name === "AbortError" || name === "AbortedError";
}

/**
 * The smallest coordinator that satisfies the foreground controller's seam for a
 * non-Task, single-identity read: in-flight dedupe, forced supersession, an
 * ordering guard so a slow answer cannot overwrite a newer one, a mutation
 * barrier, and the freshness marks the controller sets. It stores exactly one
 * confirmed answer per key and nothing else — it is not a cache and holds no
 * timer.
 */
export class PulseReadCoordinator
  implements ForegroundReadCoordinator<PulseReadPayload, string, PulseFetcher, PulseReadResult, PulseSnapshot>
{
  private readonly entries = new Map<string, PulseEntry>();

  private ensure(key: string): PulseEntry {
    const existing = this.entries.get(key);
    if (existing) return existing;
    const created: PulseEntry = {
      freshness: "idle",
      lastConfirmed: undefined,
      lastSuccessfulAt: null,
      controller: null,
      inFlight: null,
      requestSequence: 0,
      lastAppliedSequence: 0,
      mutationBarrier: 0,
      refCount: 0,
      listeners: new Set(),
    };
    this.entries.set(key, created);
    return created;
  }

  private snapshot(entry: PulseEntry): PulseSnapshot {
    return {
      freshness: entry.freshness,
      lastConfirmed: entry.lastConfirmed,
      lastSuccessfulAt: entry.lastSuccessfulAt,
    };
  }

  private emit(entry: PulseEntry): void {
    const snapshot = this.snapshot(entry);
    for (const listener of Array.from(entry.listeners)) listener(snapshot);
  }

  retain(key: string): PulseSnapshot {
    const entry = this.ensure(key);
    entry.refCount += 1;
    return this.snapshot(entry);
  }

  release(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    entry.refCount = Math.max(0, entry.refCount - 1);
    if (entry.refCount === 0 && entry.listeners.size === 0) {
      entry.controller?.abort();
      entry.controller = null;
      entry.inFlight = null;
    }
  }

  subscribe(key: string, listener: (snapshot: PulseSnapshot) => void): () => void {
    const entry = this.ensure(key);
    entry.listeners.add(listener);
    listener(this.snapshot(entry));
    return () => {
      entry.listeners.delete(listener);
    };
  }

  getSnapshot(key: string): PulseSnapshot | undefined {
    const entry = this.entries.get(key);
    return entry ? this.snapshot(entry) : undefined;
  }

  read(key: string, fetcher: PulseFetcher, options: { readonly force: boolean }): Promise<PulseReadResult> {
    const entry = this.ensure(key);

    if (entry.inFlight && !options.force) {
      // One ordinary read per identity. The joiner is told so rather than being
      // handed a second answer to apply.
      return entry.inFlight.then((result) =>
        result.outcome === "applied"
          ? { outcome: "deduped" as const, data: result.data, silent: true, sequence: result.sequence }
          : result,
      );
    }

    if (options.force && entry.controller) {
      entry.controller.abort();
      entry.controller = null;
      entry.inFlight = null;
    }

    const controller = new AbortController();
    const sequence = ++entry.requestSequence;
    const barrierAtStart = entry.mutationBarrier;
    entry.controller = controller;
    entry.freshness = "loading";
    this.emit(entry);

    const promise = (async (): Promise<PulseReadResult> => {
      try {
        const data = await fetcher({ signal: controller.signal, force: options.force });
        if (controller.signal.aborted) return { outcome: "aborted", silent: true, sequence };
        if (sequence < entry.lastAppliedSequence) return { outcome: "superseded", silent: true, sequence };
        if (entry.mutationBarrier !== barrierAtStart) {
          return { outcome: "barrier_blocked", silent: true, sequence };
        }
        entry.lastAppliedSequence = sequence;
        entry.lastConfirmed = data;
        entry.lastSuccessfulAt = Date.now();
        entry.freshness = "fresh";
        this.emit(entry);
        return { outcome: "applied", data, silent: false, sequence };
      } catch (error) {
        if (controller.signal.aborted || isAbortError(error)) {
          return { outcome: "aborted", silent: true, sequence };
        }
        // The confirmed answer is deliberately left in place: a failed read is
        // not evidence that what was confirmed has gone away.
        entry.freshness = entry.lastConfirmed === undefined ? "unavailable" : "stale";
        this.emit(entry);
        return { outcome: "failed", error, silent: false, sequence };
      } finally {
        if (entry.controller === controller) {
          entry.controller = null;
          entry.inFlight = null;
        }
      }
    })();

    entry.inFlight = promise;
    return promise;
  }

  markFresh(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "fresh";
    this.emit(entry);
  }

  markStale(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "stale";
    this.emit(entry);
  }

  markSuspended(key: string): void {
    const entry = this.ensure(key);
    entry.freshness = "suspended";
    this.emit(entry);
  }

  applyConfirmed(key: string, data: PulseReadPayload): PulseSnapshot {
    const entry = this.ensure(key);
    entry.mutationBarrier += 1;
    entry.lastConfirmed = data;
    entry.lastSuccessfulAt = Date.now();
    entry.freshness = "fresh";
    this.emit(entry);
    return this.snapshot(entry);
  }

  raiseMutationBarrier(key: string): number {
    const entry = this.ensure(key);
    entry.mutationBarrier += 1;
    return entry.mutationBarrier;
  }
}

export interface TodayPulseSurfaceProps {
  /**
   * The server's one authoritative classification, already made by
   * `surfaceAnswer`. It is the surface's starting answer and is never
   * re-derived here.
   */
  readonly initialAnswer: TodayPulseAnswer;
}

export function TodayPulseSurface({ initialAnswer }: TodayPulseSurfaceProps): React.JSX.Element {
  const runtime = useTaskRuntime();
  const { reconciliation, sessionKey } = runtime;

  const [answer, setAnswer] = useState<TodayPulseAnswer>(initialAnswer);
  const [stale, setStale] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  /*
    One coordinator per session bundle: a replaced principal must not inherit the
    previous one's confirmed answer. Reminted during render when the session key
    changes — the same pattern `TaskRuntimeProvider` uses for its own bundle,
    because this is an identity rather than a cache `useMemo` may drop.
  */
  const [binding, setBinding] = useState(() => ({
    key: sessionKey,
    instance: new PulseReadCoordinator(),
  }));
  let coordinator = binding.instance;
  if (binding.key !== sessionKey) {
    const next = { key: sessionKey, instance: new PulseReadCoordinator() };
    coordinator = next.instance;
    setBinding(next);
  }

  const onResult = useCallback((result: PulseReadResult, snapshot: PulseSnapshot) => {
    if (result.outcome === "applied" || result.outcome === "deduped") {
      const payload = result.data ?? snapshot.lastConfirmed;
      if (!payload) return;
      const next = classifyPulsePayload(payload);
      if (next.kind === "unavailable") {
        // The backend answered that it did not search. That is not a new answer
        // about the record, so the confirmed one stands and the surface says so.
        setStale(true);
        return;
      }
      // One assignment: no render falls between the old answer and the new one.
      setAnswer(next);
      setStale(false);
      setNotice(null);
      return;
    }
    if (result.outcome === "failed" && !result.silent) {
      setStale(true);
    }
  }, []);

  const onNotice = useCallback((next: ForegroundRevalidationNotice) => {
    setNotice(next.message);
    setStale(true);
  }, []);

  const { revalidate } = useForegroundRevalidation<
    PulseReadPayload,
    string,
    PulseFetcher,
    PulseReadResult,
    PulseSnapshot
  >({
    queryId: TODAY_PULSE_QUERY_ID,
    queryKey: TODAY_PULSE_QUERY_ID,
    enabled: true,
    coordinator,
    fetcher: readPulse,
    onResult,
    onNotice,
    messages: TODAY_MESSAGES,
  });

  /*
    Registered by hand rather than through the controller's own `reconciliation`
    option, so there is exactly one registration for this surface: a Task
    confirmed anywhere in the session — Work, Board, Search, a Today card — asks
    Today to re-read, and Today re-reads the server rather than editing a list it
    did not derive.
  */
  const revalidateRef = useRef(revalidate);
  useEffect(() => {
    revalidateRef.current = revalidate;
  });
  useEffect(
    () => reconciliation.registerActiveTaskQuery(TODAY_PULSE_QUERY_ID, () => revalidateRef.current()),
    [reconciliation],
  );

  return (
    <>
      {notice ? (
        <p role="status" data-testid="today-refresh-notice" className="mb-2 text-sm text-muted">
          {notice}
        </p>
      ) : null}
      {stale ? (
        <p role="status" data-testid="today-stale" className="mb-2 text-sm text-muted">
          {STALE_COPY}
        </p>
      ) : null}
      {answer.kind === "unavailable" ? (
        <SurfaceState
          kind="unavailable"
          title="Today could not be derived"
          error={answer.error}
          limitations={answer.limitations}
          testId="today-unavailable"
        />
      ) : answer.kind === "empty" ? (
        <SurfaceState
          kind="empty"
          title={TODAY_EMPTY_COPY}
          diagnostic={
            "The derivation ran and found no accepted commitment, decision, task or situation that " +
            "a named condition holds about right now."
          }
          testId="today-empty"
        />
      ) : answer.kind === "degraded" ? (
        <>
          <DegradedBanner
            scope="today's derivation"
            limitations={answer.limitations}
            truncated={answer.truncated}
          />
          {answer.items.length === 0 ? (
            <SurfaceState
              kind="degraded"
              title="Today is incomplete"
              detail="A quiet day is not established. Something may still need you."
              diagnostic={
                "The derivation was incomplete and surfaced nothing. A partial read does not " +
                "establish that nothing needs attention."
              }
              testId="today-degraded-empty"
            />
          ) : (
            // The gateway's order, untouched. See `BackendPulseList`.
            <BackendPulseList items={answer.items} />
          )}
        </>
      ) : (
        <BackendPulseList items={answer.items} />
      )}
    </>
  );
}
