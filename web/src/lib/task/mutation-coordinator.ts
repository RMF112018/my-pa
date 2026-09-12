/**
 * Task mutation coordinator: per-taskId versioned write lock, optimistic status/due,
 * conflict/ambiguous handling, comment intent mutex (not serialized with Task.version lock).
 */

import { isDefinitiveAttemptFailure, type ApiFailure } from "@/lib/api/work-client";
import {
  classifyMutationError,
  idleMutationState,
  isAmbiguousMutationFailure,
  transitionMutationPhase,
  type MutationError,
  type MutationKind,
  type MutationPhase,
  type MutationState,
} from "@/lib/task/mutation-state";

export type TaskMutationKind = MutationKind;

export interface OptimisticProjection {
  status?: string;
  dueAt?: string | null;
}

export interface MutationBarrierHooks {
  /** Notify read coordinator that a mutation dispatch began (barrier token). */
  onMutationStart?: (meta: { taskId?: string; kind: MutationKind; attemptId: string }) => void;
  /** Notify read coordinator that mutation reached a terminal or ambiguous settle. */
  onMutationEnd?: (meta: {
    taskId?: string;
    kind: MutationKind;
    attemptId: string;
    phase: MutationPhase;
  }) => void;
}

export interface MutateHooks<TResult = unknown> {
  reconcile?: (result: TResult) => void | Promise<void>;
  feedback?: (result: TResult, phase: MutationPhase) => void | Promise<void>;
  /** When 409 has no `current`, fetch authoritative Task (no auto-resubmit). */
  fetchCurrent?: (taskId: string) => Promise<unknown>;
  barriers?: MutationBarrierHooks;
  onOptimistic?: (projection: OptimisticProjection) => void;
  onRollback?: (prior: OptimisticProjection) => void;
}

export interface MutateInput<TRequest = unknown, TResult = unknown> {
  kind: MutationKind;
  /** Required for all kinds except create. */
  taskId?: string;
  intentId?: string;
  idempotencyKey: string;
  expectedVersion?: number;
  request: TRequest;
  /** Network dispatch. Must include expectedVersion/idempotencyKey in the wire payload itself. */
  dispatch: (args: {
    request: TRequest;
    idempotencyKey: string;
    expectedVersion?: number;
    intentId?: string;
    attemptId: string;
  }) => Promise<TResult>;
  optimistic?: OptimisticProjection;
  /** Draft snapshot preserved across conflict/failure (coordinator does not mutate it). */
  draft?: unknown;
  hooks?: MutateHooks<TResult>;
}

export interface MutateOutcome<TResult = unknown> {
  refused: boolean;
  reason?: string;
  attemptId: string;
  state: MutationState;
  result?: TResult;
  draft?: unknown;
}

interface ActiveAttempt {
  attemptId: string;
  kind: MutationKind;
  taskId?: string;
  intentId?: string;
  idempotencyKey: string;
  expectedVersion?: number;
  request: unknown;
  draft?: unknown;
  optimisticPrior?: OptimisticProjection;
  optimisticApplied?: OptimisticProjection;
  dispatch: MutateInput["dispatch"];
  hooks?: MutateHooks;
  token: symbol;
}

function mintAttemptId(): string {
  return crypto.randomUUID();
}

function mintMutationKey(kind: MutationKind, intentId?: string): string {
  const id = intentId ?? crypto.randomUUID();
  // Domain IDEMPOTENCY_KEY_PATTERN is [A-Za-z0-9_-]{8,128} — no colons.
  return `task-${kind}-${id}`;
}

function isVersionedKind(kind: MutationKind): boolean {
  return kind === "status" || kind === "due" || kind === "update" || kind === "close" || kind === "cancel";
}

export class TaskMutationCoordinator {
  private byAttempt = new Map<string, MutationState>();
  private active = new Map<string, ActiveAttempt>();
  /** Per-taskId versioned write lock (status/due/update/close/cancel). */
  private taskLock = new Map<string, string>();
  /** Comment create: own intent mutex; does not share Task.version lock. */
  private commentLock = new Map<string, string>();
  /** Create-kind in-flight (no taskId yet). */
  private createLock: string | undefined;
  private lastByTask = new Map<string, string>();
  private lastCreateAttempt: string | undefined;

  getState(attemptId: string): MutationState | undefined {
    return this.byAttempt.get(attemptId);
  }

  getLatestForTask(taskId: string): MutationState | undefined {
    const id = this.lastByTask.get(taskId);
    return id ? this.byAttempt.get(id) : undefined;
  }

  getLatestCreate(): MutationState | undefined {
    return this.lastCreateAttempt ? this.byAttempt.get(this.lastCreateAttempt) : undefined;
  }

  isTaskLocked(taskId: string): boolean {
    return this.taskLock.has(taskId);
  }

  isCommentLocked(taskId: string): boolean {
    return this.commentLock.has(taskId);
  }

  /**
   * Dispatch one mutation. Same-Task versioned kinds serialize; different taskIds
   * may run concurrently. Comments use a separate mutex.
   */
  async mutate<TRequest, TResult>(input: MutateInput<TRequest, TResult>): Promise<MutateOutcome<TResult>> {
    const attemptId = mintAttemptId();
    const intentId = input.intentId ?? attemptId;
    const idempotencyKey = input.idempotencyKey || mintMutationKey(input.kind, intentId);

    const refuse = (reason: string): MutateOutcome<TResult> => ({
      refused: true,
      reason,
      attemptId,
      state: idleMutationState(),
      draft: input.draft,
    });

    if (input.kind !== "create" && !input.taskId) {
      return refuse("taskId is required for this mutation kind");
    }
    if (isVersionedKind(input.kind) && input.expectedVersion === undefined) {
      return refuse("expectedVersion is required for versioned Task mutations");
    }

    if (input.kind === "create") {
      if (this.createLock) return refuse("create mutation already in flight");
    } else if (input.kind === "commentCreate") {
      if (this.commentLock.has(input.taskId!)) {
        return refuse("comment create already in flight for this Task");
      }
    } else if (isVersionedKind(input.kind)) {
      if (this.taskLock.has(input.taskId!)) {
        return refuse("versioned Task mutation already in flight for this Task");
      }
    }

    const token = Symbol(`mutate-${input.kind}`);
    const state: MutationState = {
      phase: "pending",
      kind: input.kind,
      intentId,
      attemptId,
      idempotencyKey,
      expectedVersion: input.expectedVersion,
    };
    this.byAttempt.set(attemptId, state);
    if (input.taskId) this.lastByTask.set(input.taskId, attemptId);
    if (input.kind === "create") this.lastCreateAttempt = attemptId;

    const attempt: ActiveAttempt = {
      attemptId,
      kind: input.kind,
      taskId: input.taskId,
      intentId,
      idempotencyKey,
      expectedVersion: input.expectedVersion,
      request: input.request,
      draft: input.draft,
      dispatch: input.dispatch as MutateInput["dispatch"],
      hooks: input.hooks as MutateHooks | undefined,
      token,
    };

    this.acquireLock(input.kind, input.taskId, attemptId);
    this.active.set(attemptId, attempt);
    input.hooks?.barriers?.onMutationStart?.({
      taskId: input.taskId,
      kind: input.kind,
      attemptId,
    });

    if (input.optimistic) {
      attempt.optimisticPrior = {};
      attempt.optimisticApplied = { ...input.optimistic };
      input.hooks?.onOptimistic?.(input.optimistic);
    }

    try {
      const result = await input.dispatch({
        request: input.request,
        idempotencyKey,
        expectedVersion: input.expectedVersion,
        intentId,
        attemptId,
      });
      return await this.confirm(attempt, result as TResult);
    } catch (error) {
      return (await this.fail(attempt, error)) as MutateOutcome<TResult>;
    }
  }

  /** Explicit same-key retry for ambiguous attempts only — no blind conflict retry. */
  async retry<TResult = unknown>(attemptId: string): Promise<MutateOutcome<TResult>> {
    const state = this.byAttempt.get(attemptId);
    if (!state) {
      return {
        refused: true,
        reason: "unknown attempt",
        attemptId,
        state: idleMutationState(),
      };
    }
    if (state.phase !== "ambiguous") {
      return {
        refused: true,
        reason: "retry requires ambiguous mutation state",
        attemptId,
        state: { ...state },
      };
    }

    const prior = this.active.get(attemptId);
    if (!prior) {
      return {
        refused: true,
        reason: "ambiguous attempt metadata lost",
        attemptId,
        state: { ...state },
      };
    }

    if (prior.kind === "create") {
      if (this.createLock) {
        return { refused: true, reason: "create mutation already in flight", attemptId, state, draft: prior.draft };
      }
    } else if (prior.kind === "commentCreate") {
      if (prior.taskId && this.commentLock.has(prior.taskId)) {
        return { refused: true, reason: "comment create already in flight for this Task", attemptId, state, draft: prior.draft };
      }
    } else if (prior.taskId && this.taskLock.has(prior.taskId)) {
      return {
        refused: true,
        reason: "versioned Task mutation already in flight for this Task",
        attemptId,
        state,
        draft: prior.draft,
      };
    }

    const token = Symbol(`retry-${prior.kind}`);
    prior.token = token;
    state.phase = transitionMutationPhase(state.phase, "pending");
    state.error = undefined;
    this.acquireLock(prior.kind, prior.taskId, attemptId);
    this.active.set(attemptId, prior);
    prior.hooks?.barriers?.onMutationStart?.({
      taskId: prior.taskId,
      kind: prior.kind,
      attemptId,
    });

    try {
      const result = (await prior.dispatch({
        request: prior.request,
        idempotencyKey: prior.idempotencyKey,
        expectedVersion: prior.expectedVersion,
        intentId: prior.intentId,
        attemptId,
      })) as TResult;
      return await this.confirm(prior, result);
    } catch (error) {
      return (await this.fail(prior, error)) as MutateOutcome<TResult>;
    }
  }

  acknowledge(attemptId: string): void {
    const state = this.byAttempt.get(attemptId);
    if (!state) return;
    if (state.phase === "confirmed" || state.phase === "failed" || state.phase === "conflict") {
      state.phase = transitionMutationPhase(state.phase, "idle");
      state.error = undefined;
      state.confirmedResult = undefined;
      state.conflictCurrent = undefined;
    }
    this.active.delete(attemptId);
  }

  clearSession(): void {
    this.byAttempt.clear();
    this.active.clear();
    this.taskLock.clear();
    this.commentLock.clear();
    this.createLock = undefined;
    this.lastByTask.clear();
    this.lastCreateAttempt = undefined;
  }

  private acquireLock(kind: MutationKind, taskId: string | undefined, attemptId: string): void {
    if (kind === "create") {
      this.createLock = attemptId;
      return;
    }
    if (!taskId) return;
    if (kind === "commentCreate") {
      this.commentLock.set(taskId, attemptId);
      return;
    }
    if (isVersionedKind(kind)) {
      this.taskLock.set(taskId, attemptId);
    }
  }

  private releaseLock(kind: MutationKind, taskId: string | undefined, attemptId: string): void {
    if (kind === "create") {
      if (this.createLock === attemptId) this.createLock = undefined;
      return;
    }
    if (!taskId) return;
    if (kind === "commentCreate") {
      if (this.commentLock.get(taskId) === attemptId) this.commentLock.delete(taskId);
      return;
    }
    if (this.taskLock.get(taskId) === attemptId) this.taskLock.delete(taskId);
  }

  private async confirm<TResult>(attempt: ActiveAttempt, result: TResult): Promise<MutateOutcome<TResult>> {
    const state = this.byAttempt.get(attempt.attemptId)!;
    // Create/close must not report durable success before canonical result — we only
    // enter confirmed after dispatch resolves with a result object.
    state.phase = transitionMutationPhase(state.phase, "confirmed");
    state.confirmedResult = result;
    state.error = undefined;
    state.conflictCurrent = undefined;

    await attempt.hooks?.reconcile?.(result);
    await attempt.hooks?.feedback?.(result, "confirmed");

    this.releaseLock(attempt.kind, attempt.taskId, attempt.attemptId);
    attempt.hooks?.barriers?.onMutationEnd?.({
      taskId: attempt.taskId,
      kind: attempt.kind,
      attemptId: attempt.attemptId,
      phase: "confirmed",
    });
    // Keep attempt metadata for acknowledge; physical lock released.
    return {
      refused: false,
      attemptId: attempt.attemptId,
      state: { ...state },
      result,
      draft: attempt.draft,
    };
  }

  private async fail(attempt: ActiveAttempt, error: unknown): Promise<MutateOutcome> {
    const state = this.byAttempt.get(attempt.attemptId)!;
    const classified = classifyMutationError(error);
    const status = (error as ApiFailure)?.status;
    const current = (error as ApiFailure)?.current;

    if (status === 409) {
      return this.settleConflict(attempt, state, classified, current);
    }

    const ambiguous =
      isAmbiguousMutationFailure(error) ||
      (!isDefinitiveAttemptFailure(error) && classified.subtype !== "contract");
    if (ambiguous) {
      state.phase = transitionMutationPhase(state.phase, "ambiguous");
      state.error = classified;
      // Release physical dispatch lock; retain attempt + key + frozen request for retry.
      this.releaseLock(attempt.kind, attempt.taskId, attempt.attemptId);
      attempt.hooks?.barriers?.onMutationEnd?.({
        taskId: attempt.taskId,
        kind: attempt.kind,
        attemptId: attempt.attemptId,
        phase: "ambiguous",
      });
      await attempt.hooks?.feedback?.(undefined, "ambiguous");
      return {
        refused: false,
        attemptId: attempt.attemptId,
        state: { ...state },
        draft: attempt.draft,
      };
    }

    // Definitive failure: rollback optimistic projection; preserve draft.
    if (attempt.optimisticApplied) {
      attempt.hooks?.onRollback?.(attempt.optimisticPrior ?? {});
    }
    state.phase = transitionMutationPhase(state.phase, "failed");
    state.error = classified;
    this.releaseLock(attempt.kind, attempt.taskId, attempt.attemptId);
    attempt.hooks?.barriers?.onMutationEnd?.({
      taskId: attempt.taskId,
      kind: attempt.kind,
      attemptId: attempt.attemptId,
      phase: "failed",
    });
    await attempt.hooks?.feedback?.(undefined, "failed");
    this.active.delete(attempt.attemptId);
    return {
      refused: false,
      attemptId: attempt.attemptId,
      state: { ...state },
      draft: attempt.draft,
    };
  }

  private async settleConflict(
    attempt: ActiveAttempt,
    state: MutationState,
    classified: MutationError,
    current: unknown,
  ): Promise<MutateOutcome> {
    if (attempt.optimisticApplied) {
      attempt.hooks?.onRollback?.(attempt.optimisticPrior ?? {});
    }

    let conflictCurrent = current;
    if (conflictCurrent === undefined && attempt.taskId && attempt.hooks?.fetchCurrent) {
      try {
        conflictCurrent = await attempt.hooks.fetchCurrent(attempt.taskId);
      } catch {
        conflictCurrent = undefined;
      }
    }

    state.phase = transitionMutationPhase(state.phase, "conflict");
    state.error = { ...classified, current: conflictCurrent };
    state.conflictCurrent = conflictCurrent;
    // Draft preserved on attempt; no auto-resubmit.
    this.releaseLock(attempt.kind, attempt.taskId, attempt.attemptId);
    attempt.hooks?.barriers?.onMutationEnd?.({
      taskId: attempt.taskId,
      kind: attempt.kind,
      attemptId: attempt.attemptId,
      phase: "conflict",
    });
    await attempt.hooks?.feedback?.(undefined, "conflict");
    this.active.delete(attempt.attemptId);
    return {
      refused: false,
      attemptId: attempt.attemptId,
      state: { ...state },
      draft: attempt.draft,
    };
  }
}

export function createTaskMutationCoordinator(): TaskMutationCoordinator {
  return new TaskMutationCoordinator();
}

export { mintMutationKey };
