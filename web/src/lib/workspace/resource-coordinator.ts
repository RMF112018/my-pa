import { serializeResourceKey, type ResourceKey } from "@/lib/workspace/query-key";

export type ResourceFreshnessStatus =
  | "idle"
  | "fresh"
  | "stale"
  | "loading"
  | "unavailable"
  | "suspended";

export type ResourceReadOutcome =
  | "applied"
  | "deduped"
  | "aborted"
  | "superseded"
  | "barrier_blocked"
  | "failed";

export interface ResourceReadResult<T> {
  readonly outcome: ResourceReadOutcome;
  readonly data?: T;
  readonly error?: unknown;
  readonly sequence: number;
  /** True when the outcome must not be shown as a user-facing failure. */
  readonly silent: boolean;
}

export interface ResourceQuerySnapshot<T, K = ResourceKey> {
  readonly key: K;
  readonly keyId: string;
  readonly freshness: ResourceFreshnessStatus;
  readonly lastConfirmed: T | undefined;
  readonly lastSuccessfulAt: number | null;
  readonly requestSequence: number;
  readonly lastAppliedSequence: number;
  readonly mutationBarrier: number;
  readonly inFlight: boolean;
  readonly refCount: number;
}

export interface ResourceReadFetchContext<K = ResourceKey> {
  readonly signal: AbortSignal;
  readonly sequence: number;
  readonly key: K;
  readonly force: boolean;
}

export type ResourceReadFetcher<T, K = ResourceKey> = (context: ResourceReadFetchContext<K>) => Promise<T>;

export interface ResourceReadOptions {
  /** When true, abort any same-key in-flight ordinary read and start a new one. */
  readonly force?: boolean;
}

export interface ResourceConfirmedWriteOptions {
  /** Wall-clock override for tests. Defaults to `Date.now()`. */
  readonly at?: number;
}

type Listener<T, K> = (snapshot: ResourceQuerySnapshot<T, K>) => void;

interface Entry<T, K> {
  readonly key: K;
  readonly keyId: string;
  controller: AbortController | null;
  inFlight: Promise<ResourceReadResult<T>> | null;
  inFlightSequence: number | null;
  requestSequence: number;
  lastAppliedSequence: number;
  lastConfirmed: T | undefined;
  lastSuccessfulAt: number | null;
  freshness: ResourceFreshnessStatus;
  mutationBarrier: number;
  refCount: number;
  readonly listeners: Set<Listener<T, K>>;
}

function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const name = "name" in error ? String((error as { name?: unknown }).name) : "";
  return name === "AbortError" || name === "AbortedError";
}

/** Shared read mechanics; adapters retain key serialization and barrier policy. */
export class ReadCoordinatorCore<T, K> {
  private readonly entries = new Map<string, Entry<T, K>>();
  private readonly identityBarriers = new Map<string, number>();
  private disposed = false;

  constructor(
    private readonly serializeKey: (key: K) => string,
    private readonly describeKey: (key: K) => { family: string; identity: string | null },
    private readonly disposedMessage: string,
  ) {}

  /** Retain an entry so it survives between reads (provider/subscriber use). */
  retain(key: K): ResourceQuerySnapshot<T, K> {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.refCount += 1;
    return this.snapshot(entry);
  }

  /** Release a prior retain; aborts orphaned in-flight work when unused. */
  release(key: K): void {
    const keyId = this.serializeKey(key);
    const entry = this.entries.get(keyId);
    if (!entry) return;
    entry.refCount = Math.max(0, entry.refCount - 1);
    this.maybeReclaim(entry);
  }

  subscribe(key: K, listener: Listener<T, K>): () => void {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.listeners.add(listener);
    listener(this.snapshot(entry));
    return () => {
      entry.listeners.delete(listener);
      this.maybeReclaim(entry);
    };
  }

  getSnapshot(key: K): ResourceQuerySnapshot<T, K> | undefined {
    const entry = this.entries.get(this.serializeKey(key));
    return entry ? this.snapshot(entry) : undefined;
  }

  /**
   * Perform a keyed read. Ordinary same-key callers share one in-flight
   * promise. Forced callers abort the previous request and start a new one.
   */
  read(key: K, fetcher: ResourceReadFetcher<T, K>, options: ResourceReadOptions = {}): Promise<ResourceReadResult<T>> {
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
    const identityAtStart = this.identityRevision(key);
    entry.controller = controller;
    entry.inFlightSequence = sequence;
    if (entry.freshness !== "suspended") {
      entry.freshness = entry.lastConfirmed === undefined ? "loading" : "stale";
    }
    this.emit(entry);

    const run = this.execute(entry, fetcher, sequence, controller, barrierAtStart, identityAtStart, force);
    entry.inFlight = run;
    void run.finally(() => {
      if (entry.inFlight === run) {
        entry.inFlight = null;
        entry.controller = null;
        entry.inFlightSequence = null;
        this.emit(entry);
        this.maybeReclaim(entry);
      }
    });
    return run;
  }

  /**
   * Raise exact-key ordering protection before applying canonical confirmation.
   */
  raiseMutationBarrier(key: K): number {
    return this.raiseExactBarrier(key);
  }

  protected raiseExactBarrier(key: K, minimum = 0): number {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.mutationBarrier = Math.max(entry.mutationBarrier + 1, minimum);
    this.emit(entry);
    return entry.mutationBarrier;
  }

  raiseIdentityBarrier(family: string, identity: string): number {
    this.assertOpen();
    const id = JSON.stringify([family, identity]);
    const next = (this.identityBarriers.get(id) ?? 0) + 1;
    this.identityBarriers.set(id, next);
    return next;
  }

  invalidateFamily(family: string): number {
    this.assertOpen();
    let count = 0;
    for (const entry of this.entries.values()) {
      if (this.describeKey(entry.key).family !== family) continue;
      entry.mutationBarrier += 1;
      if (entry.lastConfirmed !== undefined) entry.freshness = "stale";
      this.emit(entry);
      count += 1;
    }
    return count;
  }

  private identityRevision(key: K): number {
    const { family, identity } = this.describeKey(key);
    return identity === null ? 0 : this.identityBarriers.get(JSON.stringify([family, identity])) ?? 0;
  }

  /**
   * Apply authoritative data for this key. Earlier reads cannot overwrite it.
   */
  applyConfirmed(key: K, data: T, options: ResourceConfirmedWriteOptions = {}): ResourceQuerySnapshot<T, K> {
    this.raiseMutationBarrier(key);
    return this.confirm(key, data, options.at);
  }

  protected confirm(key: K, data: T, at?: number): ResourceQuerySnapshot<T, K> {
    this.assertOpen();
    const entry = this.ensure(key);
    entry.lastConfirmed = data;
    entry.lastSuccessfulAt = at ?? Date.now();
    entry.lastAppliedSequence = Math.max(entry.lastAppliedSequence, entry.requestSequence);
    entry.freshness = "fresh";
    this.emit(entry);
    return this.snapshot(entry);
  }

  markStale(key: K): void {
    const entry = this.entries.get(this.serializeKey(key));
    if (!entry) return;
    entry.freshness = "stale";
    this.emit(entry);
  }

  markUnavailable(key: K): void {
    const entry = this.entries.get(this.serializeKey(key));
    if (!entry) return;
    entry.freshness = "unavailable";
    this.emit(entry);
  }

  markSuspended(key: K): void {
    const entry = this.entries.get(this.serializeKey(key));
    if (!entry) return;
    entry.freshness = "suspended";
    this.emit(entry);
  }

  markFresh(key: K): void {
    const entry = this.entries.get(this.serializeKey(key));
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
    this.identityBarriers.clear();
  }

  /** True after {@link dispose}; used by providers to remint after Strict Mode cleanup. */
  isDisposed(): boolean {
    return this.disposed;
  }

  private async execute(
    entry: Entry<T, K>,
    fetcher: ResourceReadFetcher<T, K>,
    sequence: number,
    controller: AbortController,
    barrierAtStart: number,
    identityAtStart: number,
    force: boolean,
  ): Promise<ResourceReadResult<T>> {
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
      if (entry.mutationBarrier > barrierAtStart || this.identityRevision(entry.key) !== identityAtStart) {
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
      if (entry.mutationBarrier > barrierAtStart || this.identityRevision(entry.key) !== identityAtStart) {
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

  private ensure(key: K): Entry<T, K> {
    const keyId = this.serializeKey(key);
    let entry = this.entries.get(keyId);
    if (entry) return entry;
    entry = {
      key,
      keyId,
      controller: null,
      inFlight: null,
      inFlightSequence: null,
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

  private abortInFlight(entry: Entry<T, K>): void {
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
  private maybeReclaim(entry: Entry<T, K>): void {
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

  private drop(entry: Entry<T, K>): void {
    this.abortInFlight(entry);
    entry.listeners.clear();
    this.entries.delete(entry.keyId);
  }

  private snapshot(entry: Entry<T, K>): ResourceQuerySnapshot<T, K> {
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

  private emit(entry: Entry<T, K>): void {
    if (entry.listeners.size === 0) return;
    const snap = this.snapshot(entry);
    for (const listener of [...entry.listeners]) {
      listener(snap);
    }
  }

  private assertOpen(): void {
    if (this.disposed) {
      throw new Error(this.disposedMessage);
    }
  }
}

/** In-memory reads owned by one authenticated runtime; no scheduling or persistence. */
export class ResourceCoordinator<T = unknown> extends ReadCoordinatorCore<T, ResourceKey> {
  constructor() {
    super(serializeResourceKey, (key) => key, "ResourceCoordinator has been disposed");
  }
}
