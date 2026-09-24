/**
 * Query-keyed Constraint read coordinator — R02-WP10 Phase 4.
 *
 * A fresh design for the Constraint runtime (not a port of
 * `@/lib/task/read-coordinator.ts`, whose shape this borrows ideas from for
 * generality only). Owns:
 *
 * 1. dedupe of same-key ordinary reads onto one in-flight promise;
 * 2. forced superseding reads that abort the previous request;
 * 3. refusal to apply stale / out-of-order responses after a newer sequence;
 * 4. a mutation barrier so a read started before a confirmed local mutation
 *    can never overwrite the mutation's result;
 * 5. the mandatory Project-scope epoch guard (Artifact 05 SP3.6): a response
 *    whose captured epoch no longer equals the *current* epoch (per the
 *    caller-supplied `isCurrentEpoch`) is dropped outright — no canonical
 *    state overwrite, not even a freshness/loading transition;
 * 6. cleanup of orphaned controllers when entries are released or disposed.
 *
 * This module is React-free. `ConstraintRuntimeProvider` mounts one instance
 * per Project-scope epoch (a fresh identity per epoch, never a mutable
 * in-place reset — see that file), and later Register/Inspector/Category
 * surfaces subscribe to it directly or through `useForegroundRevalidation`
 * (`@/lib/task/use-foreground-revalidation.ts`), which this coordinator
 * satisfies structurally with no adapter needed.
 */

import {
  serializeConstraintQueryKey,
  type ConstraintQueryKey,
} from "@/lib/constraint/query-key";

export type ConstraintFreshnessStatus =
  | "idle"
  | "fresh"
  | "stale"
  | "loading"
  | "unavailable"
  | "suspended";

export type ConstraintReadOutcome =
  | "applied"
  | "deduped"
  | "aborted"
  | "superseded"
  | "barrier_blocked"
  | "stale_epoch"
  | "failed";

export interface ConstraintReadResult<T> {
  readonly outcome: ConstraintReadOutcome;
  readonly data?: T;
  readonly error?: unknown;
  readonly sequence: number;
  /** True when the outcome must not be shown as a user-facing failure. */
  readonly silent: boolean;
}

export interface ConstraintQuerySnapshot<T> {
  readonly key: ConstraintQueryKey;
  readonly keyId: string;
  readonly freshness: ConstraintFreshnessStatus;
  readonly lastConfirmed: T | undefined;
  readonly lastSuccessfulAt: number | null;
  readonly requestSequence: number;
  readonly lastAppliedSequence: number;
  readonly mutationBarrier: number;
  readonly inFlight: boolean;
  readonly refCount: number;
}

export interface ConstraintReadFetchContext {
  readonly signal: AbortSignal;
  readonly sequence: number;
  readonly key: ConstraintQueryKey;
  readonly force: boolean;
}

export type ConstraintReadFetcher<T> = (context: ConstraintReadFetchContext) => Promise<T>;

/** Captured-epoch / current-epoch predicate, as `useProjectScope()` exposes it. */
export type IsCurrentEpoch = (epoch: number) => boolean;

export interface ConstraintReadOptions {
  /** When true, abort any same-key in-flight ordinary read and start a new one. */
  readonly force?: boolean;
  /** Project-scope epoch active when this read was dispatched. */
  readonly epoch: number;
  /** `useProjectScope().isCurrentEpoch`, called at resolution time. */
  readonly isCurrentEpoch: IsCurrentEpoch;
}

export interface ConstraintConfirmedWriteOptions {
  /** Optional entity id for entity-scoped barriers (detail/category). */
  readonly entityId?: string;
  /** Wall-clock override for tests. Defaults to `Date.now()`. */
  readonly at?: number;
  /** Project-scope epoch the confirming mutation was dispatched under. */
  readonly epoch: number;
  /** `useProjectScope().isCurrentEpoch`, called before the write is applied. */
  readonly isCurrentEpoch: IsCurrentEpoch;
}

type Listener<T> = (snapshot: ConstraintQuerySnapshot<T>) => void;

interface Entry<T> {
  readonly key: ConstraintQueryKey;
  readonly keyId: string;
  controller: AbortController | null;
  inFlight: Promise<ConstraintReadResult<T>> | null;
  inFlightSequence: number | null;
  /** Barrier revision observed when the current in-flight read started. */
  inFlightBarrierAtStart: number | null;
  requestSequence: number;
  lastAppliedSequence: number;
  lastConfirmed: T | undefined;
  lastSuccessfulAt: number | null;
  freshness: ConstraintFreshnessStatus;
  mutationBarrier: number;
  refCount: number;
  readonly listeners: Set<Listener<T>>;
}

function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const name = "name" in error ? String((error as { name?: unknown }).name) : "";
  return name === "AbortError" || name === "AbortedError";
}

export class ConstraintReadCoordinator<T = unknown> {
  private readonly entries = new Map<string, Entry<T>>();
  private readonly entityBarriers = new Map<string, number>();
  private disposed = false;

  /** Retain an entry so it survives between reads (provider/subscriber use). */
  retain(key: ConstraintQueryKey): ConstraintQuerySnapshot<T> {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.refCount += 1;
    return this.snapshot(entry);
  }

  /** Release a prior retain; aborts orphaned in-flight work when unused. */
  release(key: ConstraintQueryKey): void {
    const keyId = serializeConstraintQueryKey(key);
    const entry = this.entries.get(keyId);
    if (!entry) return;
    entry.refCount = Math.max(0, entry.refCount - 1);
    this.maybeReclaim(entry);
  }

  subscribe(key: ConstraintQueryKey, listener: Listener<T>): () => void {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.listeners.add(listener);
    listener(this.snapshot(entry));
    return () => {
      entry.listeners.delete(listener);
      this.maybeReclaim(entry);
    };
  }

  getSnapshot(key: ConstraintQueryKey): ConstraintQuerySnapshot<T> | undefined {
    const entry = this.entries.get(serializeConstraintQueryKey(key));
    return entry ? this.snapshot(entry) : undefined;
  }

  /**
   * Perform a keyed read. Ordinary same-key callers share one in-flight
   * promise. Forced callers abort the previous request and start a new one.
   *
   * Epoch guard (SP3.6): the response is evaluated against
   * `options.isCurrentEpoch(options.epoch)` *after* every other staleness
   * check. A stale-epoch response never overwrites `lastConfirmed`, never
   * changes `freshness`, and is reported with outcome `"stale_epoch"`
   * (`silent: true`) so no caller ever surfaces it as a user-visible failure
   * or applies it as canonical state.
   */
  read(
    key: ConstraintQueryKey,
    fetcher: ConstraintReadFetcher<T>,
    options: ConstraintReadOptions,
  ): Promise<ConstraintReadResult<T>> {
    this.assertOpen();
    const entry = this.ensure(key);
    const force = options.force === true;

    if (!force && entry.inFlight) {
      return entry.inFlight.then((result) => ({
        ...result,
        outcome: result.outcome === "applied" || result.outcome === "deduped" ? "deduped" : result.outcome,
        silent: result.silent || result.outcome === "aborted" || result.outcome === "superseded",
      }));
    }

    if (force && entry.inFlight) {
      this.abortInFlight(entry);
    }

    const sequence = ++entry.requestSequence;
    const controller = new AbortController();
    const barrierAtStart = entry.mutationBarrier;
    entry.controller = controller;
    entry.inFlightSequence = sequence;
    entry.inFlightBarrierAtStart = barrierAtStart;
    if (entry.freshness !== "suspended") {
      entry.freshness = entry.lastConfirmed === undefined ? "loading" : "stale";
    }
    this.emit(entry);

    const run = this.execute(entry, fetcher, sequence, controller, barrierAtStart, force, options);
    entry.inFlight = run;
    void run.finally(() => {
      if (entry.inFlight === run) {
        entry.inFlight = null;
        entry.controller = null;
        entry.inFlightSequence = null;
        entry.inFlightBarrierAtStart = null;
        this.emit(entry);
        this.maybeReclaim(entry);
      }
    });
    return run;
  }

  /**
   * Raise the mutation / entity ordering barrier so any read that started
   * earlier cannot overwrite confirmed local mutation results.
   */
  raiseMutationBarrier(key: ConstraintQueryKey, options?: { readonly entityId?: string }): number {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.mutationBarrier += 1;
    if (options?.entityId) {
      const prior = this.entityBarriers.get(options.entityId) ?? 0;
      const next = Math.max(prior + 1, entry.mutationBarrier);
      this.entityBarriers.set(options.entityId, next);
      entry.mutationBarrier = Math.max(entry.mutationBarrier, next);
    }
    this.emit(entry);
    return entry.mutationBarrier;
  }

  /**
   * Apply a confirmed local mutation result. Raises the barrier first so any
   * still-in-flight pre-mutation read cannot overwrite this confirmation.
   *
   * Epoch-guarded: if `options.isCurrentEpoch(options.epoch)` is false this
   * is a no-op that returns the entry's current (untouched) snapshot — the
   * barrier is not even raised, since a stale-epoch mutation confirmation
   * must not affect canonical state at all.
   */
  applyConfirmed(
    key: ConstraintQueryKey,
    data: T,
    options: ConstraintConfirmedWriteOptions,
  ): ConstraintQuerySnapshot<T> {
    this.assertOpen();
    const entry = this.ensure(key);
    if (!options.isCurrentEpoch(options.epoch)) {
      return this.snapshot(entry);
    }
    this.raiseMutationBarrier(key, { entityId: options.entityId });
    entry.lastConfirmed = data;
    entry.lastSuccessfulAt = options.at ?? Date.now();
    entry.lastAppliedSequence = Math.max(entry.lastAppliedSequence, entry.requestSequence);
    entry.freshness = "fresh";
    this.emit(entry);
    return this.snapshot(entry);
  }

  markStale(key: ConstraintQueryKey): void {
    const entry = this.entries.get(serializeConstraintQueryKey(key));
    if (!entry) return;
    entry.freshness = "stale";
    this.emit(entry);
  }

  markUnavailable(key: ConstraintQueryKey): void {
    const entry = this.entries.get(serializeConstraintQueryKey(key));
    if (!entry) return;
    entry.freshness = "unavailable";
    this.emit(entry);
  }

  markSuspended(key: ConstraintQueryKey): void {
    const entry = this.entries.get(serializeConstraintQueryKey(key));
    if (!entry) return;
    entry.freshness = "suspended";
    this.emit(entry);
  }

  markFresh(key: ConstraintQueryKey): void {
    const entry = this.entries.get(serializeConstraintQueryKey(key));
    if (!entry || entry.lastConfirmed === undefined) return;
    entry.freshness = "fresh";
    this.emit(entry);
  }

  /** Abort all in-flight reads and drop every entry. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const entry of [...this.entries.values()]) {
      this.abortInFlight(entry);
      entry.listeners.clear();
      this.entries.delete(entry.keyId);
    }
    this.entityBarriers.clear();
  }

  /** True after {@link dispose}; used by the provider to remint after Strict Mode cleanup. */
  isDisposed(): boolean {
    return this.disposed;
  }

  private async execute(
    entry: Entry<T>,
    fetcher: ConstraintReadFetcher<T>,
    sequence: number,
    controller: AbortController,
    barrierAtStart: number,
    force: boolean,
    options: ConstraintReadOptions,
  ): Promise<ConstraintReadResult<T>> {
    try {
      const data = await fetcher({
        signal: controller.signal,
        sequence,
        key: entry.key,
        force,
      });

      if (controller.signal.aborted || entry.inFlightSequence !== sequence) {
        return { outcome: "aborted", sequence, silent: true };
      }
      if (sequence < entry.lastAppliedSequence) {
        return { outcome: "superseded", sequence, silent: true };
      }
      if (entry.mutationBarrier > barrierAtStart) {
        return { outcome: "barrier_blocked", sequence, silent: true };
      }
      // SP3.6 epoch guard: evaluated last, after every ordering check has
      // already passed — this response is otherwise the newest, in-order,
      // unbarriered answer for this key, and is still dropped if the
      // Project-scope epoch it was dispatched under is no longer current.
      if (!options.isCurrentEpoch(options.epoch)) {
        return { outcome: "stale_epoch", sequence, silent: true, data };
      }

      entry.lastConfirmed = data;
      entry.lastSuccessfulAt = Date.now();
      entry.lastAppliedSequence = sequence;
      entry.freshness = "fresh";
      this.emit(entry);
      return { outcome: "applied", data, sequence, silent: false };
    } catch (error) {
      if (controller.signal.aborted || entry.inFlightSequence !== sequence || isAbortError(error)) {
        return { outcome: "aborted", sequence, silent: true, error };
      }
      if (sequence < entry.lastAppliedSequence) {
        return { outcome: "superseded", sequence, silent: true, error };
      }
      if (entry.mutationBarrier > barrierAtStart) {
        return { outcome: "barrier_blocked", sequence, silent: true, error };
      }
      if (!options.isCurrentEpoch(options.epoch)) {
        return { outcome: "stale_epoch", sequence, silent: true, error };
      }
      if (entry.lastConfirmed !== undefined) {
        entry.freshness = "stale";
      } else if (entry.freshness !== "suspended") {
        entry.freshness = "unavailable";
      }
      this.emit(entry);
      return { outcome: "failed", sequence, silent: false, error };
    }
  }

  private ensure(key: ConstraintQueryKey): Entry<T> {
    const keyId = serializeConstraintQueryKey(key);
    let entry = this.entries.get(keyId);
    if (entry) return entry;
    entry = {
      key,
      keyId,
      controller: null,
      inFlight: null,
      inFlightSequence: null,
      inFlightBarrierAtStart: null,
      requestSequence: 0,
      lastAppliedSequence: 0,
      lastConfirmed: undefined,
      lastSuccessfulAt: null,
      freshness: "idle",
      mutationBarrier: 0,
      refCount: 0,
      listeners: new Set(),
    };
    this.entries.set(keyId, entry);
    return entry;
  }

  private abortInFlight(entry: Entry<T>): void {
    if (!entry.controller) return;
    try {
      entry.controller.abort();
    } catch {
      // Abort must never throw into callers.
    }
  }

  /**
   * Drop only truly unused empty entries. Confirmed data and raised barriers
   * stay until {@link dispose} so mutation reconciliation survives between
   * React retain cycles. Orphaned in-flight reads are aborted.
   */
  private maybeReclaim(entry: Entry<T>): void {
    if (entry.refCount > 0 || entry.listeners.size > 0) return;
    if (entry.inFlight) {
      this.abortInFlight(entry);
      return;
    }
    const empty =
      entry.lastConfirmed === undefined &&
      entry.mutationBarrier === 0 &&
      entry.lastAppliedSequence === 0 &&
      entry.freshness === "idle";
    if (empty) this.drop(entry);
  }

  private drop(entry: Entry<T>): void {
    this.abortInFlight(entry);
    entry.listeners.clear();
    this.entries.delete(entry.keyId);
  }

  private snapshot(entry: Entry<T>): ConstraintQuerySnapshot<T> {
    return {
      key: entry.key,
      keyId: entry.keyId,
      freshness: entry.freshness,
      lastConfirmed: entry.lastConfirmed,
      lastSuccessfulAt: entry.lastSuccessfulAt,
      requestSequence: entry.requestSequence,
      lastAppliedSequence: entry.lastAppliedSequence,
      mutationBarrier: entry.mutationBarrier,
      inFlight: entry.inFlight !== null,
      refCount: entry.refCount,
    };
  }

  private emit(entry: Entry<T>): void {
    if (entry.listeners.size === 0) return;
    const snap = this.snapshot(entry);
    for (const listener of [...entry.listeners]) {
      listener(snap);
    }
  }

  private assertOpen(): void {
    if (this.disposed) {
      throw new Error("ConstraintReadCoordinator has been disposed");
    }
  }
}

/** Factory for provider/bootstrap code that prefers a function over `new`. */
export function createConstraintReadCoordinator<T = unknown>(): ConstraintReadCoordinator<T> {
  return new ConstraintReadCoordinator<T>();
}
