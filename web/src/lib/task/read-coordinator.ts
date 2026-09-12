/**
 * Query-keyed Task read coordinator for WP-TUX-02.
 *
 * Generalizes the Workbench `AbortController` + monotonically increasing
 * `readGeneration` pattern into a reusable runtime that:
 *
 * 1. dedupes same-key ordinary reads onto one in-flight promise;
 * 2. allows forced superseding reads to abort the previous request;
 * 3. refuses to apply stale / out-of-order responses after a newer sequence;
 * 4. refuses to let a read that started before a confirmed local mutation
 *    overwrite the mutation result (mutation barrier);
 * 5. never surfaces aborted / superseded reads as user-visible failures;
 * 6. cleans up orphaned controllers when entries are released or disposed.
 *
 * Usable from a React provider later; this module itself is React-free.
 */

import {
  serializeTaskQueryKey,
  type TaskQueryKey,
} from "@/lib/task/query-key";

export type TaskFreshnessStatus =
  | "idle"
  | "fresh"
  | "stale"
  | "loading"
  | "unavailable"
  | "suspended";

export type TaskReadOutcome =
  | "applied"
  | "deduped"
  | "aborted"
  | "superseded"
  | "barrier_blocked"
  | "failed";

export interface TaskReadResult<T> {
  readonly outcome: TaskReadOutcome;
  readonly data?: T;
  readonly error?: unknown;
  readonly sequence: number;
  /** True when the outcome must not be shown as a user-facing failure. */
  readonly silent: boolean;
}

export interface TaskQuerySnapshot<T> {
  readonly key: TaskQueryKey;
  readonly keyId: string;
  readonly freshness: TaskFreshnessStatus;
  readonly lastConfirmed: T | undefined;
  readonly lastSuccessfulAt: number | null;
  readonly requestSequence: number;
  readonly lastAppliedSequence: number;
  readonly mutationBarrier: number;
  readonly inFlight: boolean;
  readonly refCount: number;
}

export interface TaskReadFetchContext {
  readonly signal: AbortSignal;
  readonly sequence: number;
  readonly key: TaskQueryKey;
  readonly force: boolean;
}

export type TaskReadFetcher<T> = (context: TaskReadFetchContext) => Promise<T>;

export interface TaskReadOptions {
  /** When true, abort any same-key in-flight ordinary read and start a new one. */
  readonly force?: boolean;
}

export interface TaskConfirmedWriteOptions {
  /** Optional entity id for entity-scoped barriers (detail/comments). */
  readonly entityId?: string;
  /** Wall-clock override for tests. Defaults to `Date.now()`. */
  readonly at?: number;
}

type Listener<T> = (snapshot: TaskQuerySnapshot<T>) => void;

interface Entry<T> {
  readonly key: TaskQueryKey;
  readonly keyId: string;
  controller: AbortController | null;
  inFlight: Promise<TaskReadResult<T>> | null;
  inFlightSequence: number | null;
  /** Barrier revision observed when the current in-flight read started. */
  inFlightBarrierAtStart: number | null;
  requestSequence: number;
  lastAppliedSequence: number;
  lastConfirmed: T | undefined;
  lastSuccessfulAt: number | null;
  freshness: TaskFreshnessStatus;
  mutationBarrier: number;
  refCount: number;
  readonly listeners: Set<Listener<T>>;
}

function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const name = "name" in error ? String((error as { name?: unknown }).name) : "";
  return name === "AbortError" || name === "AbortedError";
}

export class TaskReadCoordinator<T = unknown> {
  private readonly entries = new Map<string, Entry<T>>();
  private readonly entityBarriers = new Map<string, number>();
  private disposed = false;

  /** Retain an entry so it survives between reads (provider/subscriber use). */
  retain(key: TaskQueryKey): TaskQuerySnapshot<T> {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.refCount += 1;
    return this.snapshot(entry);
  }

  /** Release a prior retain; aborts orphaned in-flight work when unused. */
  release(key: TaskQueryKey): void {
    const keyId = serializeTaskQueryKey(key);
    const entry = this.entries.get(keyId);
    if (!entry) return;
    entry.refCount = Math.max(0, entry.refCount - 1);
    this.maybeReclaim(entry);
  }

  subscribe(key: TaskQueryKey, listener: Listener<T>): () => void {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.listeners.add(listener);
    listener(this.snapshot(entry));
    return () => {
      entry.listeners.delete(listener);
      this.maybeReclaim(entry);
    };
  }

  getSnapshot(key: TaskQueryKey): TaskQuerySnapshot<T> | undefined {
    const entry = this.entries.get(serializeTaskQueryKey(key));
    return entry ? this.snapshot(entry) : undefined;
  }

  /**
   * Perform a keyed read. Ordinary same-key callers share one in-flight
   * promise. Forced callers abort the previous request and start a new one.
   */
  read(key: TaskQueryKey, fetcher: TaskReadFetcher<T>, options: TaskReadOptions = {}): Promise<TaskReadResult<T>> {
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

    const run = this.execute(entry, fetcher, sequence, controller, barrierAtStart, force);
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
  raiseMutationBarrier(key: TaskQueryKey, options: TaskConfirmedWriteOptions = {}): number {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.mutationBarrier += 1;
    if (options.entityId) {
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
   * still-in-flight pre-mutation poll cannot overwrite this confirmation.
   */
  applyConfirmed(key: TaskQueryKey, data: T, options: TaskConfirmedWriteOptions = {}): TaskQuerySnapshot<T> {
    this.assertOpen();
    const entry = this.ensure(key);
    this.raiseMutationBarrier(key, options);
    entry.lastConfirmed = data;
    entry.lastSuccessfulAt = options.at ?? Date.now();
    entry.lastAppliedSequence = Math.max(entry.lastAppliedSequence, entry.requestSequence);
    entry.freshness = "fresh";
    this.emit(entry);
    return this.snapshot(entry);
  }

  markStale(key: TaskQueryKey): void {
    const entry = this.entries.get(serializeTaskQueryKey(key));
    if (!entry) return;
    entry.freshness = "stale";
    this.emit(entry);
  }

  markUnavailable(key: TaskQueryKey): void {
    const entry = this.entries.get(serializeTaskQueryKey(key));
    if (!entry) return;
    entry.freshness = "unavailable";
    this.emit(entry);
  }

  markSuspended(key: TaskQueryKey): void {
    const entry = this.entries.get(serializeTaskQueryKey(key));
    if (!entry) return;
    entry.freshness = "suspended";
    this.emit(entry);
  }

  markFresh(key: TaskQueryKey): void {
    const entry = this.entries.get(serializeTaskQueryKey(key));
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

  private async execute(
    entry: Entry<T>,
    fetcher: TaskReadFetcher<T>,
    sequence: number,
    controller: AbortController,
    barrierAtStart: number,
    force: boolean,
  ): Promise<TaskReadResult<T>> {
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
      if (entry.lastConfirmed !== undefined) {
        entry.freshness = "stale";
      } else if (entry.freshness !== "suspended") {
        entry.freshness = "unavailable";
      }
      this.emit(entry);
      return { outcome: "failed", sequence, silent: false, error };
    }
  }

  private ensure(key: TaskQueryKey): Entry<T> {
    const keyId = serializeTaskQueryKey(key);
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

  private snapshot(entry: Entry<T>): TaskQuerySnapshot<T> {
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
      throw new Error("TaskReadCoordinator has been disposed");
    }
  }
}

/** Factory for provider/bootstrap code that prefers a function over `new`. */
export function createTaskReadCoordinator<T = unknown>(): TaskReadCoordinator<T> {
  return new TaskReadCoordinator<T>();
}
