"use client";

/**
 * Today's client half: the surface that reads and keeps Today fresh
 * (WP-TUX-07, amended by WP-POSTUX-06).
 *
 * ## Why this exists, and where the boundary is
 *
 * **This changed at WP-POSTUX-06 and the old description is kept nowhere.**
 * `today/page.tsx` no longer performs a server-side `continuity.pulse` read and
 * no longer hands this component a pre-classified `initialAnswer`. It could not:
 * Today membership is now defined against a *civil date in the viewer's own
 * timezone*, and a server component rendering before any client code has run
 * does not know that timezone. So the read moved here in full.
 *
 * Every read this component issues goes to `/api/pulse?workDate=…&timezone=…`,
 * with both values derived by `browserWorkClock` from the browser's own clock
 * and IANA zone. That route is `requirePrincipal`-guarded and derives the
 * Principal from the session cookie alone — the query carries a civil day and a
 * zone, never an identity. The route then calls `tasks.list` with
 * `work_view=today`, which is the *same* server predicate Work uses; there is no
 * second Today query and no client-side membership rule in this file.
 *
 * What comes back is `todayRows`: one row per canonical Today Task, each
 * carrying the derivation's own row under `attention` when the derivation
 * produced one, followed by the non-Task rows the derivation raised. This file
 * renders those rows in the order the route composed them and does not filter,
 * re-key or re-order them.
 *
 * `initialAnswer` remains an accepted prop and is still honoured when supplied,
 * because it is what lets a caller seed a confirmed answer in a test. Nothing in
 * the application passes it any more.
 *
 * ## A first read that fails is not a quiet day
 *
 * Because there is no server-rendered answer to fall back on, the first read is
 * the only thing standing between the viewer and an empty screen. While it is in
 * flight the surface renders a distinct `loading` state — not an `unavailable`
 * card wearing a placeholder message. If it *fails*, the surface adopts the
 * gateway's own refusal envelope, so the diagnostic the reader sees is the one
 * the transport actually produced rather than a sentence this file invented.
 *
 * Once any answer has been confirmed the older rule takes over unchanged: a
 * failed, partial or `coverage: "unavailable"` refresh keeps the confirmed rows
 * and marks the surface stale. It never empties and never overwrites them.
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
import { DegradedBanner, LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
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
import type { DisclosureEnvelope, ErrorEnvelope } from "@/contracts/envelope";
import type { TodayPulseAnswer, TodayRow } from "@/contracts/views";
import { browserWorkClock } from "@/lib/api/work-client";

/**
 * The sentence an authoritative quiet day is allowed to say, and the only one.
 * It is a claim about the Principal's record, so it is never printed for a read
 * that failed or came back partial.
 */
export const TODAY_EMPTY_COPY = "Nothing needs your attention right now.";

/** Registration id in the session reconciliation registry. A plain string. */
export const TODAY_PULSE_QUERY_ID = "today:pulse";

/**
 * The Task cards currently on screen, in the order the route composed them.
 *
 * Scoped to the region this surface renders rather than to the document, so a
 * card belonging to some other list — the Intelligence Pulse below Today, a
 * future second list — can never be counted as one of these, and an index
 * remembered here always means a place in this list.
 */
function cardsIn(container: HTMLElement | null): readonly HTMLElement[] {
  return container ? Array.from(container.querySelectorAll<HTMLElement>("[data-today-task]")) : [];
}

/** Whether a control is disabled, which is why the browser let go of it. */
function isDisabled(element: HTMLElement): boolean {
  return typeof element.matches === "function" && element.matches(":disabled");
}

/**
 * Where focus goes when it is placed on a card.
 *
 * A Today card is not a link and carries no anchor, so the stable thing to hand
 * focus to is the card root itself — it names the Task through
 * `aria-labelledby` and leaves every surviving control of that card ahead of
 * the user. The root has to have opted into script focus: an element with no
 * `tabindex` swallows `focus()` silently, which would look like a successful
 * return while leaving the user on the body, so an un-opted root is declined
 * here and the heading catches them instead.
 */
function cardTarget(card: HTMLElement | undefined): HTMLElement | null {
  if (!card) return null;
  return card.hasAttribute("tabindex") ? card : null;
}

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
  readonly items: readonly TodayRow[];
  readonly disclosure: DisclosureEnvelope;
  readonly completeness?: "full" | "partial";
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

  if (disclosure.coverage === "partial" || disclosure.truncated || payload.completeness === "partial") {
    return { kind: "degraded", items, limitations, truncated: disclosure.truncated === true };
  }

  if (items.length === 0) return { kind: "empty" };

  return { kind: "records", items };
}

/**
 * Compute the browser's current civil date as YYYY-MM-DD in the browser's
 * IANA timezone.
 *
 * This is called before every fetch so that midnight/timezone-change
 * transitions cause a new semantic query. The server owns validating and
 * converting these dimensions to UTC.
 */
/**
 * Read `/api/pulse` with explicit work_date and timezone query parameters.
 *
 * **Query identity includes date/timezone.** The key passed to this fetcher
 * includes the work_date and timezone so that a midnight transition or
 * timezone change produces a different semantic query. The fetcher itself is
 * stateless and does not remember the last work_date/timezone; the coordinator
 * and component handle that through the changing query key.
 *
 * The session cookie provides authentication and Principal derivation. The
 * work_date and timezone are required query parameters that the backend
 * validates and uses to construct the canonical Today window in the browser's
 * civil day.
 */
/** The classes `ErrorEnvelope` admits, kept as a value so a body can be checked. */
const ERROR_CLASSES = [
  "validation",
  "authentication",
  "authorization",
  "not_found",
  "conflict",
  "policy_denied",
  "unavailable",
  "internal",
] as const;

function toErrorClass(value: string): ErrorEnvelope["errorClass"] | null {
  return ERROR_CLASSES.find((candidate) => candidate === value) ?? null;
}

function readStrings(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

/**
 * What a refused `/api/pulse` answer actually said, rather than its status code.
 *
 * The route answers a refused gateway with `gatewayRefusal()`, whose `error`
 * carries the transport's own diagnostic — "the application gateway did not
 * answer" and the like — and whose `disclosure.limitations` repeats it in the
 * caller's terms. Throwing on the status alone discards both and leaves the
 * surface with nothing to say beyond a number, which is how a genuinely refused
 * read ends up indistinguishable from a surface that never read at all. So the
 * body is read here and travels with the error.
 *
 * Nothing is invented: if the body is not a readable envelope, the fallback says
 * only what is actually known — that this read did not complete, and at what
 * status — and never names a cause.
 */
interface PulseReadRefusal {
  readonly error: ErrorEnvelope;
  readonly limitations: readonly string[];
}

async function readRefusal(response: Response): Promise<PulseReadRefusal> {
  const fallback: PulseReadRefusal = {
    error: {
      errorClass: "unavailable",
      code: "pulse_read_failed",
      message: `The Today read did not complete (HTTP ${response.status}).`,
    },
    limitations: [],
  };
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return fallback;
  }
  if (!body || typeof body !== "object") return fallback;
  const envelope = "error" in body ? (body as { error?: unknown }).error : undefined;
  const disclosure = "disclosure" in body ? (body as { disclosure?: unknown }).disclosure : undefined;
  const limitations =
    disclosure && typeof disclosure === "object"
      ? readStrings((disclosure as { limitations?: unknown }).limitations)
      : [];
  if (!envelope || typeof envelope !== "object") return { ...fallback, limitations };
  const fields = envelope as { errorClass?: unknown; code?: unknown; message?: unknown };
  const errorClass = typeof fields.errorClass === "string" ? toErrorClass(fields.errorClass) : null;
  const message =
    typeof fields.message === "string" && fields.message.trim().length > 0
      ? fields.message
      : fallback.error.message;
  return {
    error: {
      errorClass: errorClass ?? fallback.error.errorClass,
      code: typeof fields.code === "string" && fields.code.length > 0 ? fields.code : fallback.error.code,
      message,
    },
    limitations,
  };
}

/**
 * A refused read, carrying what the route said about it.
 *
 * Subclasses the controller's own HTTP error so the one foreground policy still
 * reads the status off it (401 suspends, 403 fail-closed, 503 backs off); the
 * envelope is additional, never a replacement.
 */
export class PulseReadHttpError extends ForegroundRevalidationHttpError {
  readonly envelope: ErrorEnvelope;
  readonly limitations: readonly string[];

  constructor(status: number, refusal: PulseReadRefusal) {
    super(status, refusal.error.message);
    this.name = "PulseReadHttpError";
    this.envelope = refusal.error;
    this.limitations = refusal.limitations;
  }
}

/**
 * The `unavailable` answer a failed read becomes when nothing has ever been
 * confirmed — the route's own words where there are any, and otherwise only
 * what the failure itself establishes.
 */
export function unavailableFromReadError(error: unknown): TodayPulseAnswer {
  if (error instanceof PulseReadHttpError) {
    return { kind: "unavailable", error: error.envelope, limitations: error.limitations };
  }
  const message =
    error instanceof Error && error.message.trim().length > 0
      ? error.message
      : "The Today read did not complete.";
  return {
    kind: "unavailable",
    error: { errorClass: "unavailable", code: "pulse_read_failed", message },
    limitations: [],
  };
}

const readPulse: PulseFetcher = async ({ signal }) => {
  const { workDate, timezone } = browserWorkClock();
  const url = new URL("/api/pulse", window.location.origin);
  url.searchParams.set("workDate", workDate);
  url.searchParams.set("timezone", timezone);

  const response = await fetch(url.toString(), {
    method: "GET",
    signal,
    cache: "no-store",
    credentials: "same-origin",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new PulseReadHttpError(response.status, await readRefusal(response));
  }
  const body: unknown = await response.json();
  if (!body || typeof body !== "object") throw new Error("pulse answer was not an object");
  const candidate = body as {
    shape?: unknown;
    todayRows?: unknown;
    disclosure?: unknown;
    completeness?: unknown;
  };
  // A synthetic build never reaches this surface: the page short-circuits to the
  // fixture list. Anything but the backend shape is a payload this surface has
  // no honest reading of, so it is a failed read rather than a silent Empty.
  if (candidate.shape !== "backend") throw new Error("pulse answer was not the backend shape");
  // A missing row array is a read that did not happen, never a quiet day.
  if (!Array.isArray(candidate.todayRows)) throw new Error("pulse answer carried no todayRows array");
  if (!candidate.disclosure || typeof candidate.disclosure !== "object") {
    throw new Error("pulse answer carried no disclosure");
  }
  return {
    items: candidate.todayRows as readonly TodayRow[],
    disclosure: candidate.disclosure as DisclosureEnvelope,
    completeness: candidate.completeness === "partial" ? "partial" : "full",
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
   * Optional server classification for backward compatibility and testing.
   * Normally not provided; the surface computes Today from the browser's
   * work_date and timezone on first load.
   */
  readonly initialAnswer?: TodayPulseAnswer;
}

export function TodayPulseSurface({ initialAnswer }: TodayPulseSurfaceProps = {}): React.JSX.Element {
  const runtime = useTaskRuntime();
  const { reconciliation, sessionKey } = runtime;

  /*
    Before the first read lands there is no answer at all, and `loading` is that
    and nothing else. It is deliberately not one of the five: rendering the
    unavailable card while a read is still in flight states a failure that has
    not happened, and rendering it with placeholder copy — the shape this
    surface previously carried — put "Loading Today..." where the diagnostic of
    a genuinely refused read belongs, which is precisely how a real refusal
    became unreadable.
  */
  const [answer, setAnswer] = useState<TodayPulseAnswer | { readonly kind: "loading" }>(
    initialAnswer ?? { kind: "loading" },
  );
  const [stale, setStale] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  /*
    Whether any answer has ever stood on this surface.

    This is what separates the two halves of a failed read. With an answer
    standing, a failure retains it and marks the surface stale — the rows are
    still the last thing the backend confirmed, and "the refresh did not happen"
    says nothing against them. With nothing standing, retaining nothing is not
    an option and the honest thing is the failure itself, stated in the route's
    own words.

    A ref rather than state: it is read inside the read callback and never
    rendered, and it must be true for the render that sets the answer rather
    than one render later.
  */
  const settled = useRef(initialAnswer !== undefined);

  /**
   * The card that currently holds focus, and where it sits in the visible list.
   *
   * This mirrors the Work surface's restoration (`workbench.tsx`), for the same
   * reason and with the same shape. `useTaskRowOperations` already returns focus
   * to the control the user operated, or — since a Today card's own affordances
   * withdraw when the Task becomes terminal — to the card root. That return is
   * correct and it is not enough here: Today's authoritative re-read then
   * removes the very card it just landed on, and by the time reconciliation
   * unmounts that row the hook's own `rowRef` is detached. Only the component
   * that owns the list can see that a focused card has left it.
   *
   * So focus is recorded where it actually is rather than predicted from a
   * write, and it is acted on only when that exact card leaves and focus has
   * genuinely fallen to the document body. There is one entry, it names whichever
   * card the user is really in, and no unrelated read — a cadence refresh, a
   * second card's write confirming first — can spend it on somebody else.
   */
  const focusedCard = useRef<{ readonly taskId: string; readonly index: number; readonly element: HTMLElement } | null>(
    null,
  );
  /** The rendered Pulse — the only place Today's Task cards live. */
  const pulseRegion = useRef<HTMLDivElement | null>(null);
  /** The last resort, and never `document.body`. */
  const pulseHeading = useRef<HTMLHeadingElement | null>(null);

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
      if (next.kind === "unavailable" && settled.current) {
        // The backend answered that it did not search. That is not a new answer
        // about the record, so the confirmed one stands and the surface says so.
        setStale(true);
        return;
      }
      // One assignment: no render falls between the old answer and the new one.
      settled.current = true;
      setAnswer(next);
      setStale(false);
      setNotice(null);
      return;
    }
    if (result.outcome === "failed" && !result.silent) {
      if (!settled.current && snapshot.lastConfirmed === undefined) {
        /*
          The first read failed and there is nothing to retain. Saying so is the
          whole point: an unread Today rendered as a quiet one is the single
          claim this surface may never make, and a placeholder left in place
          would have said neither.
        */
        setAnswer(unavailableFromReadError(result.error));
        setStale(false);
        setNotice(null);
        return;
      }
      setStale(true);
    }
  }, []);

  const onNotice = useCallback((next: ForegroundRevalidationNotice) => {
    /*
      The degraded notice is a sentence about the last confirmed read. With no
      confirmed read behind it there is no such thing to describe, and the
      answer itself already states the failure. The auth and forbidden notices
      are actionable whatever has been read, so they are always shown.
    */
    if (next.kind === "degraded" && !settled.current) return;
    setNotice(next.message);
    setStale(true);
  }, []);

  // Compute a query key that includes work_date and timezone so that midnight
  // and timezone changes produce a new semantic query.
  const { workDate, timezone } = browserWorkClock();
  const queryKey = `${TODAY_PULSE_QUERY_ID}:${workDate}:${timezone}`;

  const { revalidate } = useForegroundRevalidation<
    PulseReadPayload,
    string,
    PulseFetcher,
    PulseReadResult,
    PulseSnapshot
  >({
    queryId: TODAY_PULSE_QUERY_ID,
    queryKey: queryKey,
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

  /**
   * Remember which card focus is in, whenever it moves.
   *
   * `focusin` bubbles — React's `onFocus` is `focusin` — so one handler on the
   * region covers every card and every control inside one, including the
   * controls a card mounts after this renders and the card root itself when the
   * shared engine places focus there.
   */
  function rememberFocusedCard(event: React.FocusEvent<HTMLElement>) {
    const card = (event.target as HTMLElement).closest<HTMLElement>("[data-today-task]");
    const taskId = card?.getAttribute("data-today-task") ?? null;
    if (!card || !taskId) return;
    /*
      Position is taken from the element itself and never by looking the Task up
      again: the Pulse may surface one Task under more than one item, and a
      lookup by id would answer with the first of them and send the user to a
      card they were not standing in.
    */
    focusedCard.current = {
      taskId,
      index: cardsIn(pulseRegion.current).indexOf(card),
      element: event.target as HTMLElement,
    };
  }

  /*
    Restore focus after the authoritative re-read took it away.

    Keyed on the answer the server returned, not on a mutation callback: the card
    that was operated may already be unmounted by then, so nothing it fires can
    be relied on, and Today's membership is the Pulse's decision rather than
    anything this surface may infer locally.

    Two conditions, and together they are the whole design: focus must have
    fallen to the document body, and the element that was holding it must have
    actually left the document. That pair is what separates a real loss from a
    user who deliberately clicked away and from a control that merely
    re-rendered, and it makes this safe for any list change whatever its cause —
    a write confirming, a cadence refresh, a degraded answer replacing a whole
    one. A change that costs the user nothing is left alone.
  */
  useEffect(() => {
    if (!focusedCard.current) return;
    const frame = requestAnimationFrame(() => {
      const lost = focusedCard.current;
      if (!lost) return;
      /*
        A thrown error here is invisible — nothing awaits this callback — and it
        would leave a stale record behind to mislead the next re-read. Fail by
        forgetting where focus was, which costs one restore rather than every
        restore after it.
      */
      try {
        const active = document.activeElement;
        const stillMounted = lost.element.isConnected;

        /*
          Focus is somewhere real: the card kept it, or a popover, a dialog or
          the user's own click took it deliberately.

          The record is maintained rather than merely consumed. If the card it
          names has since gone while the user was working elsewhere it is
          finished and must be dropped — kept, it would be read on some later
          re-read as "focus was taken from this card" and haul the user back out
          of wherever they had got to. If the card is still here its position is
          refreshed: cards above it can leave without the user touching anything,
          and no new focus event fires to correct a remembered index that is by
          then pointing at somebody else's card.
        */
        if (active && active !== document.body) {
          if (!stillMounted) {
            focusedCard.current = null;
            return;
          }
          const card = lost.element.closest<HTMLElement>("[data-today-task]");
          const moved = card ? cardsIn(pulseRegion.current).indexOf(card) : -1;
          focusedCard.current = { ...lost, index: moved };
          return;
        }

        /*
          Focus is on the body and the control the user was in is still right
          there. Either they put it down themselves — clicking the page
          background, dismissing something — or the card disabled it under them
          while a write runs, which a browser answers by dropping focus to the
          body. The first is a choice and is owed nothing; the second is the very
          loss this exists to repair, and reading them as the same thing would
          throw the record away on any refresh landing mid-write, leaving nothing
          to catch focus when the write then confirmed and took the card.
        */
        if (stillMounted && !isDisabled(lost.element)) {
          focusedCard.current = null;
          return;
        }
        if (stillMounted) return;

        focusedCard.current = null;
        const after = cardsIn(pulseRegion.current);
        const survivor = after.find(
          (candidate) => candidate.getAttribute("data-today-task") === lost.taskId,
        );
        /*
          The remembered position can sit past the end of the list — more than
          one card can leave in a single answer — so clamp to the last card still
          standing rather than reading past it. Landing on the nearest surviving
          neighbour is the whole point; giving up here would send the user to the
          heading with perfectly good cards in front of them.
        */
        const clamped = Math.min(lost.index, after.length - 1);
        const target = cardTarget(survivor) ?? cardTarget(after[clamped]);
        if (target) {
          target.focus();
          return;
        }
        pulseHeading.current?.focus();
      } catch {
        focusedCard.current = null;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [answer]);

  return (
    /*
      A listener, not an interactive element: `onFocus` is `focusin` and bubbles,
      so this one handler sees focus land anywhere in the Pulse, including on
      controls a card mounts later.
    */
    <div ref={pulseRegion} onFocus={rememberFocusedCard}>
      {/*
        The stable last resort. The page's own `<h1>` is rendered by a server
        component that has not opted into script focus, so focusing it would do
        nothing silently; this heading is owned by the surface that needs it, is
        always mounted whatever the answer, and names the region for a screen
        reader when focus arrives on it.
      */}
      <h2 ref={pulseHeading} tabIndex={-1} className="sr-only" data-testid="today-pulse-heading">
        Today
      </h2>
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
      {answer.kind === "loading" ? (
        <LoadingStatus label="Reading Today…" testId="today-loading" />
      ) : answer.kind === "unavailable" ? (
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
            "Today's Task read ran and returned no Task for this day, and the derivation ran and " +
            "raised no commitment, decision, observation or situation either."
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
                "The read was incomplete and carried no Task and no other row. A partial read " +
                "does not establish that nothing needs attention."
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
    </div>
  );
}
