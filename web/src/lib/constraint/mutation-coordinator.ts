/**
 * Constraint mutation coordinator — R02-WP10 Phase 4.
 *
 * A fresh design for the Constraint runtime (not a port of
 * `@/lib/task/mutation-coordinator.ts`, whose general shape this borrows
 * ideas from — per-key write lock, stable idempotency key, conflict vs.
 * ambiguous classification — but whose logic is never imported). Implements,
 * exactly as frozen in the dispatch's SP2 supplement:
 *
 * - the five lock-key families (`constraint:<id>`, `category:<id>`,
 *   `category-collection:<projectId>`, and one create-intent lock per
 *   mounted Create / Quick-Capture-Constraint surface);
 * - a reorder-vs-record-lock interaction (a `category-collection` reorder
 *   additionally refuses while any `category-record` lock for the same
 *   Project is unresolved);
 * - ambiguous-outcome lock retention (an ambiguous attempt keeps its lock
 *   held — unlike a confirmed/conflicted/definitively-failed one — until the
 *   caller explicitly retries it to a terminal state or abandons it);
 * - the mandatory Project-scope epoch guard (Artifact 05 SP3.6): a settling
 *   response whose captured epoch no longer equals the *current* epoch is
 *   dropped before any conflict/ambiguous classification runs — no
 *   `reconcile`, no `feedback` (so nothing crosses into
 *   `useMutationFeedback()`), no `resolveFocus`, and no conflict
 *   base/current/attempted snapshot is recorded;
 * - conflict base/current/attempted mirroring, for a later form to read and
 *   `hasDirtyAuthoredState`/`hasPendingOrAmbiguousMutation`, the two
 *   ingredients of the `CanSwitchProjectScope` barrier `constraint-runtime-
 *   provider.tsx` builds on top of this module (see that file's
 *   `useCanSwitchProjectScope` — this module intentionally exposes only the
 *   two booleans, since the soft-block's confirm/discard UI needs JSX and
 *   this module stays React-free).
 */

export type ConstraintMutationPhase =
  | "idle"
  | "pending"
  | "confirmed"
  | "failed"
  | "conflict"
  | "ambiguous"
  | "stale_epoch";

/**
 * Free-form label for feedback/telemetry only. Locking is entirely driven by
 * the explicit `lockRequest` on {@link ConstraintMutateInput}, not by kind.
 */
export type ConstraintMutationKind =
  | "constraintCreate"
  | "constraintUpdate"
  | "constraintTransition"
  | "constraintPublish"
  | "constraintClose"
  | "constraintFollowUp"
  | "constraintVoid"
  | "constraintReopen"
  | "categoryCreate"
  | "categoryUpdate"
  | "categoryDeactivate"
  | "categoryReorder"
  | "captureConstraintCreate";

export type ConstraintMutationErrorSubtype =
  | "validation"
  | "unauthenticated"
  | "forbidden"
  | "authority"
  | "network"
  | "gateway"
  | "backend"
  | "contract";

export interface ConstraintMutationError {
  readonly subtype: ConstraintMutationErrorSubtype;
  readonly message: string;
  readonly status?: number;
  readonly code?: string;
}

/** Classify a thrown dispatch error into a coarse subtype for UX/logging. */
export function classifyConstraintMutationError(error: unknown): ConstraintMutationError {
  if (error === null || error === undefined) {
    return { subtype: "network", message: "unknown mutation failure" };
  }
  if (
    typeof error === "object" &&
    "subtype" in error &&
    typeof (error as ConstraintMutationError).subtype === "string"
  ) {
    return error as ConstraintMutationError;
  }

  const status = (error as { status?: number }).status;
  const code = (error as { code?: string }).code;
  const message =
    error instanceof Error
      ? error.message
      : typeof (error as { message?: string }).message === "string"
        ? (error as { message: string }).message
        : "mutation failed";

  if (status === undefined && (error instanceof TypeError || /network|fetch|offline|lost/i.test(message))) {
    return { subtype: "network", message };
  }
  if (status === 401) return { subtype: "unauthenticated", message, status, code };
  if (status === 403) return { subtype: "forbidden", message, status, code };
  if (status === 422 || status === 400) return { subtype: "validation", message, status, code };
  if (status === 502 || status === 503 || status === 504) {
    if (code === "upstream_contract_invalid") return { subtype: "contract", message, status, code };
    return { subtype: "gateway", message, status, code };
  }
  if (status !== undefined && status >= 500) return { subtype: "backend", message, status, code };
  if (code === "authority_unavailable" || /authority/i.test(String(code ?? ""))) {
    return { subtype: "authority", message, status, code };
  }
  return { subtype: "backend", message, status, code };
}

/** Ambiguous = the request may have applied server-side; retain key/lock. */
export function isAmbiguousConstraintMutationFailure(error: unknown): boolean {
  const status = (error as { status?: number } | null | undefined)?.status;
  if (status === 409) return false;
  const classified = classifyConstraintMutationError(error);
  if (classified.subtype === "network") return true;
  if (classified.subtype === "gateway") return true;
  if (classified.subtype === "contract") return false;
  return status !== undefined && [502, 503, 504].includes(status);
}

// ---------------------------------------------------------------------------
// Locking — SP2, frozen.
// ---------------------------------------------------------------------------

export type ConstraintLockKind =
  | "constraint-record"
  | "category-record"
  | "category-collection"
  | "create-intent";

export interface ConstraintLockRequest {
  readonly kind: ConstraintLockKind;
  /** The exact frozen lock key string — build with the helpers below. */
  readonly key: string;
  /**
   * Required for `"category-record"` (so a same-Project reorder can detect
   * it) and for `"category-collection"` reorders (`checkProjectRecordLocks`)
   * so they can look up blocking record locks by Project.
   */
  readonly projectId?: string;
  /**
   * Only a `"category-collection"` *reorder* sets this: per SP2, a reorder
   * additionally refuses while any `category-record` lock for the same
   * Project is unresolved. A collection-level *create* does not check this.
   */
  readonly checkProjectRecordLocks?: boolean;
}

export function constraintLockKey(constraintId: string): string {
  return `constraint:${constraintId}`;
}

export function categoryLockKey(categoryId: string): string {
  return `category:${categoryId}`;
}

export function categoryCollectionLockKey(projectId: string): string {
  return `category-collection:${projectId}`;
}

/**
 * One create-intent lock key per mounted Create / Quick-Capture-Constraint
 * surface instance. SP2 defines no key parameter beyond "this one open
 * surface instance" — mint this once per mount (e.g. in a `useMemo`/`useRef`
 * on that surface) and reuse it for the surface's whole lifetime.
 */
export function mintCreateIntentLockKey(
  surface: "constraint-create" | "capture-constraint-create",
): string {
  return `${surface}:${crypto.randomUUID()}`;
}

interface LockRecord {
  readonly attemptId: string;
  readonly kind: ConstraintLockKind;
  readonly projectId?: string;
}

// ---------------------------------------------------------------------------
// Mutation state.
// ---------------------------------------------------------------------------

export interface ConstraintConflictState {
  /** The canonical state the attempt was frozen against, if the caller supplied one. */
  readonly base?: unknown;
  /** The server's current canonical state returned (or fetched) on 409. */
  readonly current?: unknown;
  /** What this attempt tried to write. */
  readonly attempted: unknown;
}

export interface ConstraintMutationState {
  phase: ConstraintMutationPhase;
  kind?: ConstraintMutationKind;
  attemptId?: string;
  lockKey?: string;
  idempotencyKey?: string;
  expectedVersion?: number;
  expectedVersions?: readonly number[];
  error?: ConstraintMutationError;
  confirmedResult?: unknown;
  conflict?: ConstraintConflictState;
}

function idleState(): ConstraintMutationState {
  return { phase: "idle" };
}

/** `useProjectScope().isCurrentEpoch`, as this module consumes it. */
export type IsCurrentEpoch = (epoch: number) => boolean;

export interface ConstraintMutateHooks<TResult = unknown> {
  /** Write-through into `read-coordinator.ts`'s canonical state. Skipped on a stale-epoch settle. */
  readonly reconcile?: (result: TResult) => void | Promise<void>;
  /** Typically wraps `useMutationFeedback().publish(...)`. Skipped on a stale-epoch settle. */
  readonly feedback?: (result: TResult | undefined, phase: ConstraintMutationPhase) => void | Promise<void>;
  /** Typically wraps `FocusReturnRegistry.resolve(...)`. Skipped on a stale-epoch settle. */
  readonly resolveFocus?: (result: TResult | undefined, phase: ConstraintMutationPhase) => void;
  /** When a 409 body carries no `current`, fetch authoritative state. No auto-resubmit. */
  readonly fetchCurrent?: () => Promise<unknown>;
}

export interface ConstraintDispatchArgs<TRequest> {
  readonly request: TRequest;
  readonly idempotencyKey: string;
  readonly expectedVersion?: number;
  readonly expectedVersions?: readonly number[];
  readonly attemptId: string;
}

export interface ConstraintMutateInput<TRequest = unknown, TResult = unknown> {
  readonly kind: ConstraintMutationKind;
  readonly lockRequest: ConstraintLockRequest;
  readonly idempotencyKey: string;
  /** Single-record versioned mutations. */
  readonly expectedVersion?: number;
  /** Positional, for a multi-record body (e.g. Category reorder) — SP4 forward-compat. */
  readonly expectedVersions?: readonly number[];
  readonly request: TRequest;
  /** Project-scope epoch active when this mutation is dispatched. */
  readonly epoch: number;
  /** `useProjectScope().isCurrentEpoch`, called once at settle time. */
  readonly isCurrentEpoch: IsCurrentEpoch;
  readonly dispatch: (args: ConstraintDispatchArgs<TRequest>) => Promise<TResult>;
  /** The canonical state this attempt was frozen against, mirrored into conflict state on 409. */
  readonly baseSnapshot?: unknown;
  readonly hooks?: ConstraintMutateHooks<TResult>;
}

export interface ConstraintMutateOutcome<TResult = unknown> {
  readonly refused: boolean;
  readonly reason?: string;
  readonly attemptId: string;
  readonly state: ConstraintMutationState;
  readonly result?: TResult;
  /** True only for the SP3.6 stale-epoch drop — the response above is otherwise inert. */
  readonly epochStale?: boolean;
}

interface ActiveAttempt {
  readonly attemptId: string;
  readonly kind: ConstraintMutationKind;
  readonly lockRequest: ConstraintLockRequest;
  readonly idempotencyKey: string;
  readonly expectedVersion?: number;
  readonly expectedVersions?: readonly number[];
  readonly request: unknown;
  readonly baseSnapshot?: unknown;
  readonly dispatch: ConstraintMutateInput["dispatch"];
  readonly hooks?: ConstraintMutateHooks;
}

function mintAttemptId(): string {
  return crypto.randomUUID();
}

export class ConstraintMutationCoordinator {
  private readonly byAttempt = new Map<string, ConstraintMutationState>();
  private readonly active = new Map<string, ActiveAttempt>();
  private readonly locks = new Map<string, LockRecord>();
  private readonly latestByLock = new Map<string, string>();
  private readonly dirtySurfaces = new Set<string>();
  private disposed = false;

  getState(attemptId: string): ConstraintMutationState | undefined {
    return this.byAttempt.get(attemptId);
  }

  getLatestForLock(lockKey: string): ConstraintMutationState | undefined {
    const attemptId = this.latestByLock.get(lockKey);
    return attemptId ? this.byAttempt.get(attemptId) : undefined;
  }

  isLocked(lockKey: string): boolean {
    return this.locks.has(lockKey);
  }

  getLockHolder(lockKey: string): string | undefined {
    return this.locks.get(lockKey)?.attemptId;
  }

  /**
   * True while any lock is held — every held lock corresponds, by
   * construction, to a mutation that is either in-flight (`pending`) or
   * settled `ambiguous` (locks are released on every other terminal phase).
   * This is the exact hard-block predicate `CanSwitchProjectScope` needs.
   */
  hasPendingOrAmbiguousMutation(): boolean {
    return this.locks.size > 0;
  }

  /** A later form reports/clears its own dirty (unsaved authored) state here. */
  reportDirtyState(surfaceId: string, dirty: boolean): void {
    if (dirty) this.dirtySurfaces.add(surfaceId);
    else this.dirtySurfaces.delete(surfaceId);
  }

  clearDirtyState(surfaceId: string): void {
    this.dirtySurfaces.delete(surfaceId);
  }

  /** True while any registered surface reports unsaved authored state. */
  hasDirtyAuthoredState(): boolean {
    return this.dirtySurfaces.size > 0;
  }

  /**
   * Dispatch one mutation. Refuses synchronously (before any network call)
   * when the lock is unavailable, so a caller can disable a control instead
   * of attempting a doomed mutation.
   */
  async mutate<TRequest, TResult>(
    input: ConstraintMutateInput<TRequest, TResult>,
  ): Promise<ConstraintMutateOutcome<TResult>> {
    const attemptId = mintAttemptId();

    const refuse = (reason: string): ConstraintMutateOutcome<TResult> => ({
      refused: true,
      reason,
      attemptId,
      state: idleState(),
    });

    const lockCheck = this.canAcquire(input.lockRequest);
    if (!lockCheck.granted) return refuse(lockCheck.reason);

    const state: ConstraintMutationState = {
      phase: "pending",
      kind: input.kind,
      attemptId,
      lockKey: input.lockRequest.key,
      idempotencyKey: input.idempotencyKey,
      expectedVersion: input.expectedVersion,
      expectedVersions: input.expectedVersions,
    };
    this.byAttempt.set(attemptId, state);
    this.latestByLock.set(input.lockRequest.key, attemptId);

    const attempt: ActiveAttempt = {
      attemptId,
      kind: input.kind,
      lockRequest: input.lockRequest,
      idempotencyKey: input.idempotencyKey,
      expectedVersion: input.expectedVersion,
      expectedVersions: input.expectedVersions,
      request: input.request,
      baseSnapshot: input.baseSnapshot,
      dispatch: input.dispatch as ConstraintMutateInput["dispatch"],
      hooks: input.hooks as ConstraintMutateHooks | undefined,
    };
    this.acquireLock(attempt.lockRequest, attemptId);
    this.active.set(attemptId, attempt);

    return this.run(attempt, input.epoch, input.isCurrentEpoch);
  }

  /** Explicit same-key retry for ambiguous attempts only — no blind conflict retry. */
  async retry<TResult = unknown>(
    attemptId: string,
    epoch: number,
    isCurrentEpoch: IsCurrentEpoch,
  ): Promise<ConstraintMutateOutcome<TResult>> {
    const state = this.byAttempt.get(attemptId);
    if (!state) {
      return { refused: true, reason: "unknown attempt", attemptId, state: idleState() };
    }
    if (state.phase !== "ambiguous") {
      return { refused: true, reason: "retry requires ambiguous mutation state", attemptId, state: { ...state } };
    }
    const attempt = this.active.get(attemptId);
    if (!attempt) {
      return { refused: true, reason: "ambiguous attempt metadata lost", attemptId, state: { ...state } };
    }

    state.phase = "pending";
    state.error = undefined;
    // Lock is already held by this attempt from the original dispatch.
    return this.run(attempt, epoch, isCurrentEpoch) as Promise<ConstraintMutateOutcome<TResult>>;
  }

  /**
   * Explicitly abandon an ambiguous attempt: releases its lock and clears
   * its state. Not usable on a `pending` (in-flight) attempt — a dispatch
   * must settle (confirmed/failed/conflict/ambiguous) before it can be
   * abandoned, so no in-flight network effect is ever silently disowned.
   */
  abandon(attemptId: string): boolean {
    const state = this.byAttempt.get(attemptId);
    const attempt = this.active.get(attemptId);
    if (!state || !attempt || state.phase !== "ambiguous") return false;
    this.releaseLock(attempt.lockRequest, attemptId);
    this.active.delete(attemptId);
    state.phase = "idle";
    state.error = undefined;
    state.conflict = undefined;
    return true;
  }

  /** Clear a terminal (confirmed/failed/conflict/stale_epoch) attempt's state back to idle. */
  acknowledge(attemptId: string): void {
    const state = this.byAttempt.get(attemptId);
    if (!state) return;
    if (state.phase !== "pending" && state.phase !== "ambiguous") {
      state.phase = "idle";
      state.error = undefined;
      state.confirmedResult = undefined;
      state.conflict = undefined;
    }
    this.active.delete(attemptId);
  }

  clearSession(): void {
    this.byAttempt.clear();
    this.active.clear();
    this.locks.clear();
    this.latestByLock.clear();
    this.dirtySurfaces.clear();
  }

  dispose(): void {
    this.disposed = true;
    this.clearSession();
  }

  isDisposed(): boolean {
    return this.disposed;
  }

  private canAcquire(request: ConstraintLockRequest): { granted: true } | { granted: false; reason: string } {
    if (this.locks.has(request.key)) {
      return { granted: false, reason: `lock already held: ${request.key}` };
    }
    if (request.kind === "category-collection" && request.checkProjectRecordLocks && request.projectId) {
      for (const record of this.locks.values()) {
        if (record.kind === "category-record" && record.projectId === request.projectId) {
          return {
            granted: false,
            reason: `blocked by outstanding category record lock for Project ${request.projectId}`,
          };
        }
      }
    }
    return { granted: true };
  }

  private acquireLock(request: ConstraintLockRequest, attemptId: string): void {
    this.locks.set(request.key, { attemptId, kind: request.kind, projectId: request.projectId });
  }

  private releaseLock(request: ConstraintLockRequest, attemptId: string): void {
    if (this.locks.get(request.key)?.attemptId === attemptId) {
      this.locks.delete(request.key);
    }
  }

  private async run<TResult>(
    attempt: ActiveAttempt,
    epoch: number,
    isCurrentEpoch: IsCurrentEpoch,
  ): Promise<ConstraintMutateOutcome<TResult>> {
    try {
      const result = (await attempt.dispatch({
        request: attempt.request,
        idempotencyKey: attempt.idempotencyKey,
        expectedVersion: attempt.expectedVersion,
        expectedVersions: attempt.expectedVersions,
        attemptId: attempt.attemptId,
      })) as TResult;
      return await this.settleSuccess(attempt, result, epoch, isCurrentEpoch);
    } catch (error) {
      return (await this.settleFailure(attempt, error, epoch, isCurrentEpoch)) as ConstraintMutateOutcome<TResult>;
    }
  }

  /**
   * SP3.6 epoch guard, shared by the success and failure paths: evaluated
   * before any other classification. On staleness this releases the lock
   * (so the resource is never left deadlocked by a response nobody will act
   * on) but performs none of the three forbidden effects — no `reconcile`,
   * no `feedback`, no `resolveFocus` — and records no conflict snapshot.
   */
  private settleStaleEpoch<TResult>(attempt: ActiveAttempt): ConstraintMutateOutcome<TResult> {
    const state = this.byAttempt.get(attempt.attemptId)!;
    state.phase = "stale_epoch";
    state.error = undefined;
    state.confirmedResult = undefined;
    state.conflict = undefined;
    this.releaseLock(attempt.lockRequest, attempt.attemptId);
    this.active.delete(attempt.attemptId);
    return { refused: false, attemptId: attempt.attemptId, state: { ...state }, epochStale: true };
  }

  private async settleSuccess<TResult>(
    attempt: ActiveAttempt,
    result: TResult,
    epoch: number,
    isCurrentEpoch: IsCurrentEpoch,
  ): Promise<ConstraintMutateOutcome<TResult>> {
    if (!isCurrentEpoch(epoch)) return this.settleStaleEpoch<TResult>(attempt);

    const state = this.byAttempt.get(attempt.attemptId)!;
    state.phase = "confirmed";
    state.confirmedResult = result;
    state.error = undefined;
    state.conflict = undefined;

    await attempt.hooks?.reconcile?.(result);
    await attempt.hooks?.feedback?.(result, "confirmed");
    attempt.hooks?.resolveFocus?.(result, "confirmed");

    this.releaseLock(attempt.lockRequest, attempt.attemptId);
    return { refused: false, attemptId: attempt.attemptId, state: { ...state }, result };
  }

  private async settleFailure(
    attempt: ActiveAttempt,
    error: unknown,
    epoch: number,
    isCurrentEpoch: IsCurrentEpoch,
  ): Promise<ConstraintMutateOutcome> {
    if (!isCurrentEpoch(epoch)) return this.settleStaleEpoch(attempt);

    const status = (error as { status?: number } | null | undefined)?.status;
    if (status === 409) return this.settleConflict(attempt, error);

    const classified = classifyConstraintMutationError(error);
    const state = this.byAttempt.get(attempt.attemptId)!;

    if (isAmbiguousConstraintMutationFailure(error)) {
      state.phase = "ambiguous";
      state.error = classified;
      // Lock intentionally retained: SP2 — an ambiguous outcome remains the
      // same logical intent and a second material attempt for this lock key
      // must be refused until retry settles or the caller abandons it.
      await attempt.hooks?.feedback?.(undefined, "ambiguous");
      attempt.hooks?.resolveFocus?.(undefined, "ambiguous");
      return { refused: false, attemptId: attempt.attemptId, state: { ...state } };
    }

    state.phase = "failed";
    state.error = classified;
    this.releaseLock(attempt.lockRequest, attempt.attemptId);
    this.active.delete(attempt.attemptId);
    await attempt.hooks?.feedback?.(undefined, "failed");
    attempt.hooks?.resolveFocus?.(undefined, "failed");
    return { refused: false, attemptId: attempt.attemptId, state: { ...state } };
  }

  private async settleConflict(attempt: ActiveAttempt, error: unknown): Promise<ConstraintMutateOutcome> {
    const classified = classifyConstraintMutationError(error);
    let current = (error as { current?: unknown } | null | undefined)?.current;
    if (current === undefined && attempt.hooks?.fetchCurrent) {
      try {
        current = await attempt.hooks.fetchCurrent();
      } catch {
        current = undefined;
      }
    }

    const state = this.byAttempt.get(attempt.attemptId)!;
    state.phase = "conflict";
    state.error = classified;
    state.conflict = { base: attempt.baseSnapshot, current, attempted: attempt.request };
    // SP2: a 409 releases the network attempt (lock free again) but the
    // conflict snapshot above survives until the caller resolves/discards it.
    this.releaseLock(attempt.lockRequest, attempt.attemptId);
    this.active.delete(attempt.attemptId);
    await attempt.hooks?.feedback?.(undefined, "conflict");
    attempt.hooks?.resolveFocus?.(undefined, "conflict");
    return { refused: false, attemptId: attempt.attemptId, state: { ...state } };
  }
}

export function createConstraintMutationCoordinator(): ConstraintMutationCoordinator {
  return new ConstraintMutationCoordinator();
}
