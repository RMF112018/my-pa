"use client";

/**
 * Shared Task operation binder (WP-TUX-05).
 *
 * This is the single place Work List rows and Task detail bind Task operations.
 * No Task surface owns a second mutation engine: every write here goes through
 * the session-scoped `TaskMutationCoordinator`, every confirmed write reconciles
 * registered active Task queries, and every outcome speaks the one product copy.
 *
 * Operation matrix (non-negotiable):
 *
 * | Operation | Presentation  | Expected version | Idempotency | Confirmation authority |
 * |-----------|---------------|------------------|-------------|------------------------|
 * | Status    | optimistic    | yes              | yes         | server Task            |
 * | Due       | optimistic    | yes              | yes         | server Task            |
 * | Comment   | pending row   | no               | yes         | server comment         |
 * | Close     | pessimistic   | yes              | yes         | server Task required   |
 * | Cancel    | pessimistic   | yes              | yes         | server Task required   |
 *
 * A Work-list projection is never write authority: without a trustworthy numeric
 * `version` the Task is canonically hydrated through the read coordinator before
 * any versioned write is dispatched.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTaskRuntime } from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskLifecycle, TaskRow } from "@/contracts/work";
import {
  browserWorkClock,
  createAttemptKey,
  mutationKey,
  workRequest,
} from "@/lib/api/work-client";
import type { MutationKind } from "@/lib/task/mutation-state";
import { buildTaskQueryKey, type TaskQueryKey } from "@/lib/task/query-key";
import {
  civilDayEndIso,
  formatTaskDue,
  formatTaskStatus,
  type TaskActiveStatus,
  type TaskCivilClock,
} from "@/lib/tasks/presentation";

/* ------------------------------------------------------------------ *
 * Product copy — exact, and never leaking transport detail
 * ------------------------------------------------------------------ */

export const TASK_OPERATION_CONFLICT_MESSAGE =
  "This task changed elsewhere. Review the latest details before trying your change again.";
export const TASK_OPERATION_FAILURE_MESSAGE = "Could not save this change. Try again.";
export const TASK_OPERATION_AMBIGUOUS_MESSAGE =
  "The result could not be confirmed. Checking the latest task before retrying.";
export const TASK_COMMENT_ADDED_MESSAGE = "Comment added";
export const TASK_DUE_CLEARED_MESSAGE = "Due date cleared";

export function taskStatusChangedMessage(next: TaskLifecycle): string {
  return `Status changed to ${formatTaskStatus(next)}`;
}

export function taskDueMovedMessage(nextIso: string, clock: TaskCivilClock): string {
  return `Due date moved to ${formatTaskDue(nextIso, clock).phrase}`;
}

export function taskClosedMessage(title: string): string {
  return `${title} closed`;
}

export function taskCancelledMessage(title: string): string {
  return `${title} cancelled`;
}

/* ------------------------------------------------------------------ *
 * Public shape
 * ------------------------------------------------------------------ */

export interface TaskOperationsSeed {
  readonly taskId: string;
  /**
   * Display seed. A Work-list projection is never write authority, even when it
   * happens to carry a `version` — that number is a read of some earlier moment,
   * not a claim about the Task now. Only a caller that already holds a canonical
   * snapshot may say so, with {@link authoritative}.
   */
  readonly task?: TaskDetail | TaskRow | null;
  /**
   * The caller obtained `task` from the canonical Task read, not from a list or
   * search projection. Defaults to false, so an unmarked seed always hydrates
   * before the first versioned write.
   */
  readonly authoritative?: boolean;
}

export interface TaskOperationsOptions {
  /** Civil-day context for Due serialization and Due copy. Defaults to the browser clock. */
  readonly clock?: TaskCivilClock;
  /**
   * `"eager"` hydrates the canonical Task on mount — for a single detail surface,
   * or a list row whose projection carries no version. `"on-demand"` (default)
   * hydrates at the first versioned write, so a list does not fan out one detail
   * read per row.
   */
  readonly hydrate?: "eager" | "on-demand";
}

export type PendingTaskCommentState = "pending" | "failed" | "ambiguous";

/** One outbound comment. The body is preserved verbatim across failure and retry. */
export interface PendingTaskComment {
  readonly localId: string;
  readonly body: string;
  readonly state: PendingTaskCommentState;
}

export interface UseTaskOperationsResult {
  /** Authoritative Task snapshot once hydrated or returned by a confirmed write. */
  readonly task: TaskDetail | undefined;
  /**
   * What to show, which is not always what may be written.
   *
   * The held canonical snapshot while it is the newer of the two, otherwise the
   * seed the surface was given — a list that has been re-read since is simply
   * newer information about the same Task. Display only: `canMutate` and the
   * version behind it come from the canonical read alone, so nothing here can
   * authorise a write.
   */
  readonly display: TaskDetail | TaskRow | null;
  /** True only while a canonical numeric version is held. */
  readonly canMutate: boolean;
  readonly hydrated: boolean;
  readonly pending: MutationKind | null;
  readonly conflict: { readonly current: TaskDetail } | null;
  readonly status: { readonly value: TaskLifecycle; readonly optimistic: boolean };
  readonly due: { readonly value: string | null; readonly optimistic: boolean };
  readonly pendingComments: readonly PendingTaskComment[];
  changeStatus(next: TaskActiveStatus): Promise<void>;
  /** Accepts a civil date (`YYYY-MM-DD`, serialized to civil day end) or a full ISO instant. */
  changeDue(nextIso: string | null): Promise<void>;
  addComment(body: string): Promise<void>;
  retryComment(localId: string): Promise<void>;
  closeTask(): Promise<void>;
  cancelTask(): Promise<void>;
  /** Deliberate: retries an ambiguous attempt verbatim, or re-applies intent to the latest version. */
  reapply(): Promise<void>;
  dismissConflict(): void;
}

/* ------------------------------------------------------------------ *
 * Internals
 * ------------------------------------------------------------------ */

const CIVIL_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

interface StatusIntent {
  readonly kind: "status" | "close" | "cancel";
  readonly toState: TaskLifecycle;
}

interface DueIntent {
  readonly kind: "due";
  readonly dueAt: string | null;
}

type OperationIntent = StatusIntent | DueIntent;

interface CanonicalHold {
  readonly version: number;
  readonly task: TaskDetail | undefined;
}

function isTaskLike(value: unknown): value is TaskDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { task_id?: unknown }).task_id === "string" &&
    typeof (value as { lifecycle_state?: unknown }).lifecycle_state === "string"
  );
}

/** Accepts either a bare Task or the `{ task }` envelope every Task route answers with. */
function taskFromUnknown(value: unknown): TaskDetail | undefined {
  if (isTaskLike(value)) return value;
  if (value && typeof value === "object" && "task" in value) {
    const inner = (value as { task: unknown }).task;
    if (isTaskLike(inner)) return inner;
  }
  return undefined;
}

function seedVersionOf(task: TaskDetail | TaskRow | null | undefined): number | null {
  const version = task?.version;
  return typeof version === "number" && Number.isFinite(version) ? version : null;
}

export function useTaskOperations(
  seed: TaskOperationsSeed,
  options: TaskOperationsOptions = {},
): UseTaskOperationsResult {
  const runtime = useTaskRuntime();
  const { taskId } = seed;
  const seedTask = seed.task ?? null;
  const hydrateMode = options.hydrate ?? "on-demand";

  const browserClock = useMemo<TaskCivilClock>(() => browserWorkClock(), []);
  const clock = options.clock ?? browserClock;

  // A projection seeds display only. Its version never becomes write authority:
  // `ensureCanonical` must reach the read coordinator before the first versioned
  // write unless the caller declared the seed canonical.
  const seedIsAuthoritative = seed.authoritative === true;
  const [snapshot, setSnapshot] = useState<TaskDetail | undefined>(() =>
    isTaskLike(seedTask) && seedVersionOf(seedTask) !== null ? seedTask : undefined,
  );
  const [version, setVersion] = useState<number | null>(() =>
    seedIsAuthoritative ? seedVersionOf(seedTask) : null,
  );
  const [pending, setPending] = useState<MutationKind | null>(null);
  const [conflict, setConflict] = useState<{ readonly current: TaskDetail } | null>(null);
  const [optimisticStatus, setOptimisticStatus] = useState<TaskLifecycle | null>(null);
  const [optimisticDue, setOptimisticDue] = useState<{ readonly value: string | null } | null>(null);
  const [pendingComments, setPendingComments] = useState<readonly PendingTaskComment[]>([]);

  /** Async settle paths read live state through refs, never a stale closure. */
  const snapshotRef = useRef<TaskDetail | undefined>(snapshot);
  const versionRef = useRef<number | null>(version);

  /*
    Adopt a newer authoritative seed in place.

    A surface that holds the canonical Task itself — Task detail — advances its
    own version through writes this binder does not make, such as a bounded
    title save. Remounting the binder on each of those would re-seed it, but it
    would also discard in-flight comment state: a comment left in `failed`
    awaiting retry would silently lose its body the moment the user saved a
    title. Adopting the newer version here instead keeps one write authority
    without throwing away the user's unsent words. Done during render, which is
    React's documented way to adjust state from props, so no effect and no
    cascading render.
  */
  const seedVersion = seedIsAuthoritative ? seedVersionOf(seedTask) : null;
  const [adoptedSeedVersion, setAdoptedSeedVersion] = useState<number | null>(seedVersion);
  if (
    seedVersion !== null &&
    seedVersion !== adoptedSeedVersion &&
    isTaskLike(seedTask) &&
    (version === null || seedVersion > version)
  ) {
    setAdoptedSeedVersion(seedVersion);
    setSnapshot(seedTask);
    setVersion(seedVersion);
  }
  const seedTaskRef = useRef<TaskDetail | TaskRow | null>(seedTask);
  const intentRef = useRef<OperationIntent | null>(null);
  const ambiguousAttemptRef = useRef<string | null>(null);
  const commentAttemptsRef = useRef(new Map<string, { attemptId: string; ambiguous: boolean }>());
  const mountedRef = useRef(true);

  const statusAttempt = useRef(createAttemptKey("task-status"));
  const dueAttempt = useRef(createAttemptKey("task-due"));
  const closeAttempt = useRef(createAttemptKey("task-close"));
  const cancelAttempt = useRef(createAttemptKey("task-cancel"));

  useEffect(() => {
    seedTaskRef.current = seedTask;
  }, [seedTask]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const detailKey = useMemo<TaskQueryKey>(
    () => buildTaskQueryKey({ mode: "detail", taskId, sessionEpoch: runtime.sessionEpoch }),
    [runtime.sessionEpoch, taskId],
  );

  const publish = useCallback(
    (kind: "success" | "error" | "conflict" | "info", message: string, eventId: string) => {
      runtime.feedback.publish({ eventId, kind, message });
    },
    [runtime.feedback],
  );

  const holdCanonical = useCallback((task: TaskDetail) => {
    snapshotRef.current = task;
    setSnapshot(task);
    if (typeof task.version === "number") {
      versionRef.current = task.version;
      setVersion(task.version);
    }
  }, []);

  /*
    Carry an adopted version into the refs the async settle paths read. Advanced
    monotonically, so this can never walk a newer canonical — one a write just
    confirmed — back to an older seed.
  */
  useEffect(() => {
    if (version === null) return;
    if (versionRef.current !== null && version <= versionRef.current) return;
    versionRef.current = version;
    if (snapshot) snapshotRef.current = snapshot;
  }, [snapshot, version]);

  const clearOptimistic = useCallback(() => {
    setOptimisticStatus(null);
    setOptimisticDue(null);
  }, []);

  /** Force a canonical re-read. Never throws: an unreadable Task is `undefined`. */
  const readCanonical = useCallback(
    async (force: boolean): Promise<TaskDetail | undefined> => {
      try {
        const result = await runtime.readCoordinator.read(
          detailKey,
          async ({ signal }) => {
            const detail = await workRequest<{ task: TaskDetail }>(
              `/api/tasks/${encodeURIComponent(taskId)}`,
              { signal },
            );
            return detail.task;
          },
          { force },
        );
        const fromResult = taskFromUnknown(result.data);
        if (fromResult) return fromResult;
        return taskFromUnknown(runtime.readCoordinator.getSnapshot(detailKey)?.lastConfirmed);
      } catch {
        return undefined;
      }
    },
    [detailKey, runtime.readCoordinator, taskId],
  );

  /**
   * Hold a canonical version before any versioned write. A projection without a
   * numeric version is hydrated first; `null` means no write may be attempted.
   */
  const ensureCanonical = useCallback(async (): Promise<CanonicalHold | null> => {
    if (versionRef.current !== null) {
      return { version: versionRef.current, task: snapshotRef.current };
    }
    const task = await readCanonical(false);
    if (!task || typeof task.version !== "number") return null;
    if (mountedRef.current) holdCanonical(task);
    else {
      snapshotRef.current = task;
      versionRef.current = task.version;
    }
    return { version: task.version, task };
  }, [holdCanonical, readCanonical]);

  useEffect(() => {
    if (hydrateMode !== "eager") return;
    if (versionRef.current !== null) return;
    void ensureCanonical();
  }, [ensureCanonical, hydrateMode]);

  const attemptKeyFor = useCallback((kind: MutationKind) => {
    if (kind === "due") return dueAttempt.current;
    if (kind === "close") return closeAttempt.current;
    if (kind === "cancel") return cancelAttempt.current;
    return statusAttempt.current;
  }, []);

  const intentSatisfied = useCallback((task: TaskDetail, intent: OperationIntent): boolean => {
    if (intent.kind === "due") return (task.due_at ?? null) === intent.dueAt;
    return task.lifecycle_state === intent.toState;
  }, []);

  const successMessage = useCallback(
    (intent: OperationIntent, task: TaskDetail | undefined): string => {
      if (intent.kind === "due") {
        return intent.dueAt === null
          ? TASK_DUE_CLEARED_MESSAGE
          : taskDueMovedMessage(intent.dueAt, clock);
      }
      const title = task?.title ?? snapshotRef.current?.title ?? seedTaskRef.current?.title ?? "Task";
      if (intent.kind === "close") return taskClosedMessage(title);
      if (intent.kind === "cancel") return taskCancelledMessage(title);
      return taskStatusChangedMessage(intent.toState);
    },
    [clock],
  );

  /**
   * Confirmed settle. Close and Cancel require a server Task: without one the
   * terminal state is not projected, and the outcome is reported as unconfirmed.
   */
  const settleConfirmed = useCallback(
    async (intent: OperationIntent, attemptId: string, result: unknown, idempotencyKey: string) => {
      const confirmed = taskFromUnknown(result) ?? (await readCanonical(true));
      const terminal = intent.kind === "close" || intent.kind === "cancel";

      if (confirmed) {
        runtime.readCoordinator.applyConfirmed(detailKey, confirmed, { entityId: taskId });
        if (mountedRef.current) holdCanonical(confirmed);
      } else if (terminal) {
        // No authoritative Task: the row/detail stays non-terminal.
        if (mountedRef.current) clearOptimistic();
        publish("info", TASK_OPERATION_AMBIGUOUS_MESSAGE, `task-${intent.kind}-unconfirmed:${idempotencyKey}`);
        return;
      }

      if (mountedRef.current) {
        clearOptimistic();
        setConflict(null);
      }
      intentRef.current = null;
      ambiguousAttemptRef.current = null;
      attemptKeyFor(intent.kind).succeeded();

      runtime.reconciliation.notifyTaskMutationConfirmed({
        kind: intent.kind,
        taskId,
        task: confirmed,
        mutationId: attemptId,
      });
      publish("success", successMessage(intent, confirmed), `task-${intent.kind}-ok:${idempotencyKey}`);
    },
    [
      attemptKeyFor,
      clearOptimistic,
      detailKey,
      holdCanonical,
      publish,
      readCanonical,
      runtime.readCoordinator,
      runtime.reconciliation,
      successMessage,
      taskId,
    ],
  );

  const settleConflict = useCallback(
    (intent: OperationIntent, current: unknown, idempotencyKey: string) => {
      const resolved = taskFromUnknown(current) ?? snapshotRef.current;
      if (resolved) {
        // Latest server state is exposed; the user's intent is preserved, not re-sent.
        if (mountedRef.current) setConflict({ current: resolved });
        holdCanonical(resolved);
      }
      intentRef.current = intent;
      ambiguousAttemptRef.current = null;
      if (mountedRef.current) clearOptimistic();
      attemptKeyFor(intent.kind).succeeded();
      publish("conflict", TASK_OPERATION_CONFLICT_MESSAGE, `task-${intent.kind}-conflict:${idempotencyKey}`);
    },
    [attemptKeyFor, clearOptimistic, holdCanonical, publish],
  );

  const settleAmbiguous = useCallback(
    async (intent: OperationIntent, attemptId: string, idempotencyKey: string) => {
      // Same logical attempt identity is retained: never a blind second write.
      ambiguousAttemptRef.current = attemptId;
      intentRef.current = intent;
      publish("info", TASK_OPERATION_AMBIGUOUS_MESSAGE, `task-${intent.kind}-ambiguous:${idempotencyKey}`);

      const latest = await readCanonical(true);
      if (latest && intentSatisfied(latest, intent)) {
        // The write did land: settle it rather than asking for a retry.
        if (mountedRef.current) {
          holdCanonical(latest);
          clearOptimistic();
        }
        ambiguousAttemptRef.current = null;
        intentRef.current = null;
        attemptKeyFor(intent.kind).succeeded();
        runtime.reconciliation.notifyTaskMutationConfirmed({
          kind: intent.kind,
          taskId,
          task: latest,
          mutationId: attemptId,
        });
        publish("success", successMessage(intent, latest), `task-${intent.kind}-ok:${idempotencyKey}`);
      }
    },
    [
      attemptKeyFor,
      clearOptimistic,
      holdCanonical,
      intentSatisfied,
      publish,
      readCanonical,
      runtime.reconciliation,
      successMessage,
      taskId,
    ],
  );

  const settleFailed = useCallback(
    (intent: OperationIntent, idempotencyKey: string) => {
      // Definitive: the coordinator rolled the projection back to last confirmed.
      if (mountedRef.current) clearOptimistic();
      ambiguousAttemptRef.current = null;
      attemptKeyFor(intent.kind).succeeded();
      publish("error", TASK_OPERATION_FAILURE_MESSAGE, `task-${intent.kind}-fail:${idempotencyKey}`);
    },
    [attemptKeyFor, clearOptimistic, publish],
  );

  const execute = useCallback(
    async (intent: OperationIntent): Promise<void> => {
      /*
        Pending from the first moment, not from the write.

        A list row reaches the canonical Task on demand, so an activation can
        spend a real round trip here before anything is sent. Leaving the
        controls unlocked for that window let a second activation through, and
        the coordinator refused it silently — the user pressed a control twice
        and was told nothing either time.
      */
      /*
        The lock is unwound in `finally`, not on the way out of each branch.

        `setPending` is raised before the canonical read and is the only thing
        disabling this row's controls; every path that leaves this function
        without lowering it leaves the row unusable for the rest of the session,
        because a row is keyed by Task and never remounts while it is listed. A
        throw from the coordinator or from attempt-key derivation is exactly such
        a path, and it is not one the row can recover from on its own.
      */
      try {
        if (mountedRef.current) setPending(intent.kind);
        const hold = await ensureCanonical();
        if (!hold) {
          // The lock is lowered in `finally`, which is the single unwind for
          // every way out of here — including the ones nobody thought of.
          publish("error", TASK_OPERATION_FAILURE_MESSAGE, `task-${intent.kind}-unhydrated:${taskId}`);
          return;
        }

        const material =
          intent.kind === "due"
            ? intent.dueAt === null
              ? { clearFields: ["due_at"], expectedVersion: hold.version }
              : { dueAt: intent.dueAt, expectedVersion: hold.version }
            : { toState: intent.toState, expectedVersion: hold.version };
        const idempotencyKey = attemptKeyFor(intent.kind).forPayload(material);

        const outcome = await runtime.mutationCoordinator.coordinator.mutate({
          kind: intent.kind,
          taskId,
          expectedVersion: hold.version,
          idempotencyKey,
          request: material,
          // Close and Cancel are pessimistic: no terminal state before confirmation.
          optimistic:
            intent.kind === "due"
              ? { dueAt: intent.dueAt }
              : intent.kind === "status"
                ? { status: intent.toState }
                : undefined,
          hooks: {
            fetchCurrent: async () => readCanonical(true),
            barriers: {
              onMutationStart: () => {
                runtime.readCoordinator.raiseMutationBarrier(detailKey, { entityId: taskId });
              },
            },
            onOptimistic: (projection) => {
              if (!mountedRef.current) return;
              if (intent.kind === "due") setOptimisticDue({ value: intent.dueAt });
              else if (projection.status !== undefined) setOptimisticStatus(intent.toState);
            },
            onRollback: () => {
              if (mountedRef.current) clearOptimistic();
            },
          },
          dispatch: async ({ request, idempotencyKey: key, expectedVersion: expected }) =>
            intent.kind === "due"
              ? workRequest(`/api/tasks/${encodeURIComponent(taskId)}`, {
                  method: "PATCH",
                  body: JSON.stringify({ ...request, expectedVersion: expected, idempotencyKey: key }),
                })
              : workRequest(`/api/tasks/${encodeURIComponent(taskId)}/transition`, {
                  method: "POST",
                  body: JSON.stringify({ ...request, expectedVersion: expected, idempotencyKey: key }),
                }),
        });

        if (outcome.refused) {
          // A same-Task write is already in flight; the prior attempt still owns the outcome.
          return;
        }
        if (outcome.state.phase === "confirmed") {
          await settleConfirmed(intent, outcome.attemptId, outcome.result, idempotencyKey);
          return;
        }
        if (outcome.state.phase === "conflict") {
          settleConflict(intent, outcome.state.conflictCurrent, idempotencyKey);
          return;
        }
        if (outcome.state.phase === "ambiguous") {
          await settleAmbiguous(intent, outcome.attemptId, idempotencyKey);
          return;
        }
        settleFailed(intent, idempotencyKey);
      } finally {
        if (mountedRef.current) setPending(null);
      }
    },
    [
      attemptKeyFor,
      clearOptimistic,
      detailKey,
      ensureCanonical,
      publish,
      readCanonical,
      runtime.mutationCoordinator,
      runtime.readCoordinator,
      settleAmbiguous,
      settleConfirmed,
      settleConflict,
      settleFailed,
      taskId,
    ],
  );

  const changeStatus = useCallback(
    async (next: TaskActiveStatus) => {
      await execute({ kind: "status", toState: next });
    },
    [execute],
  );

  const changeDue = useCallback(
    async (nextIso: string | null) => {
      const serialized =
        nextIso === null
          ? null
          : CIVIL_DATE_PATTERN.test(nextIso)
            ? civilDayEndIso(nextIso, clock.timezone)
            : nextIso;
      await execute({ kind: "due", dueAt: serialized });
    },
    [clock.timezone, execute],
  );

  const closeTask = useCallback(async () => {
    await execute({ kind: "close", toState: "completed" });
  }, [execute]);

  const cancelTask = useCallback(async () => {
    await execute({ kind: "cancel", toState: "cancelled" });
  }, [execute]);

  const markComment = useCallback((localId: string, state: PendingTaskCommentState) => {
    setPendingComments((current) =>
      current.map((row) => (row.localId === localId ? { ...row, state } : row)),
    );
  }, []);

  /**
   * Append one comment. No `expectedVersion` travels with it and the Task version
   * is never bumped locally: a comment is an independent append.
   */
  const settleComment = useCallback(
    (
      localId: string,
      idempotencyKey: string,
      outcome: { refused: boolean; attemptId: string; state: { phase: string } },
    ) => {
      if (mountedRef.current) setPending(null);
      if (outcome.refused) {
        markComment(localId, "failed");
        return;
      }
      if (outcome.state.phase === "confirmed") {
        commentAttemptsRef.current.delete(localId);
        setPendingComments((current) => current.filter((row) => row.localId !== localId));
        runtime.reconciliation.notifyTaskMutationConfirmed({
          kind: "commentCreate",
          taskId,
          mutationId: outcome.attemptId,
        });
        publish("success", TASK_COMMENT_ADDED_MESSAGE, `task-comment-ok:${idempotencyKey}`);
        return;
      }
      if (outcome.state.phase === "ambiguous") {
        commentAttemptsRef.current.set(localId, { attemptId: outcome.attemptId, ambiguous: true });
        markComment(localId, "ambiguous");
        publish("info", TASK_OPERATION_AMBIGUOUS_MESSAGE, `task-comment-ambiguous:${idempotencyKey}`);
        return;
      }
      // Definitive failure keeps the body exactly as authored.
      commentAttemptsRef.current.set(localId, { attemptId: outcome.attemptId, ambiguous: false });
      markComment(localId, "failed");
      publish("error", TASK_OPERATION_FAILURE_MESSAGE, `task-comment-fail:${idempotencyKey}`);
    },
    [markComment, publish, runtime.reconciliation, taskId],
  );

  const addComment = useCallback(
    async (body: string) => {
      const localId = `outbound-${crypto.randomUUID()}`;
      const idempotencyKey = mutationKey("task-comment");
      setPendingComments((current) => [...current, { localId, body, state: "pending" }]);
      // Same single unwind as every other write here: the lock is the only thing
      // disabling this surface, and a throw that skips lowering it leaves the
      // user with nothing that works and no way back.
      try {
        setPending("commentCreate");
        const outcome = await runtime.mutationCoordinator.coordinator.mutate({
          kind: "commentCreate",
          taskId,
          idempotencyKey,
          request: { body },
          dispatch: async ({ request, idempotencyKey: key }) =>
            workRequest(`/api/tasks/${encodeURIComponent(taskId)}/comments`, {
              method: "POST",
              body: JSON.stringify({ ...request, idempotencyKey: key }),
            }),
        });
        settleComment(localId, idempotencyKey, outcome);
      } finally {
        if (mountedRef.current) setPending(null);
      }
    },
    [runtime.mutationCoordinator, settleComment, taskId],
  );

  const retryComment = useCallback(
    async (localId: string) => {
      const record = commentAttemptsRef.current.get(localId);
      if (!record || !record.ambiguous) return;
      markComment(localId, "pending");
      try {
        setPending("commentCreate");
        // Same attempt identity, therefore the same idempotency key on the wire.
        const outcome = await runtime.mutationCoordinator.coordinator.retry(record.attemptId);
        settleComment(localId, `retry:${record.attemptId}`, outcome);
      } finally {
        if (mountedRef.current) setPending(null);
      }
    },
    [markComment, runtime.mutationCoordinator, settleComment],
  );

  const reapply = useCallback(async () => {
    const ambiguousAttempt = ambiguousAttemptRef.current;
    const intent = intentRef.current;
    if (ambiguousAttempt && intent) {
      // Same single unwind as `execute`: a retry that throws must not leave the
      // surface locked, which is the one failure the user cannot recover from.
      try {
        if (mountedRef.current) setPending(intent.kind);
        const outcome = await runtime.mutationCoordinator.coordinator.retry(ambiguousAttempt);
        const idempotencyKey = outcome.state.idempotencyKey ?? `retry:${ambiguousAttempt}`;
        if (outcome.refused) return;
        if (outcome.state.phase === "confirmed") {
          await settleConfirmed(intent, outcome.attemptId, outcome.result, idempotencyKey);
          return;
        }
        if (outcome.state.phase === "conflict") {
          settleConflict(intent, outcome.state.conflictCurrent, idempotencyKey);
          return;
        }
        if (outcome.state.phase === "ambiguous") {
          await settleAmbiguous(intent, outcome.attemptId, idempotencyKey);
          return;
        }
        settleFailed(intent, idempotencyKey);
      } finally {
        if (mountedRef.current) setPending(null);
      }
      return;
    }
    if (!intent) return;
    // Deliberate new attempt against the version the conflict exposed.
    if (mountedRef.current) setConflict(null);
    await execute(intent);
  }, [
    execute,
    runtime.mutationCoordinator,
    settleAmbiguous,
    settleConfirmed,
    settleConflict,
    settleFailed,
  ]);

  const dismissConflict = useCallback(() => {
    setConflict(null);
    intentRef.current = null;
  }, []);

  /*
    The canonical snapshot wins while it is the newer of the two.

    A projection must never fill in a field the server has legitimately cleared,
    which is why the held snapshot is preferred at equal standing. But a held
    snapshot is a reading of one moment, and the list around it keeps being
    re-read: the Task can be changed from its own detail sheet, from a second
    tab, or by anyone else, and the refreshed projection is then simply newer
    information about the same Task. Preferring the snapshot outright froze the
    row at whatever it first held — a row went on showing an open Task as open,
    and offering to close it, long after it had been closed elsewhere.

    Newer for display only. Write authority is untouched: `version` still comes
    from the canonical read alone, so a projection cannot authorise a write no
    matter how fresh it is.
  */
  const seedIsNewer =
    snapshot !== undefined &&
    seedTask !== null &&
    (typeof seedTask.version === "number" && typeof snapshot.version === "number"
      ? seedTask.version > snapshot.version
      : seedTask.updated_at > snapshot.updated_at);
  const displayBase = seedIsNewer ? seedTask : (snapshot ?? seedTask);
  const displayStatus = optimisticStatus ?? displayBase?.lifecycle_state ?? "open";
  const displayDue = optimisticDue ? optimisticDue.value : (displayBase?.due_at ?? null);

  return {
    task: snapshot,
    display: displayBase,
    canMutate: version !== null,
    hydrated: snapshot !== undefined,
    pending,
    conflict,
    status: { value: displayStatus, optimistic: optimisticStatus !== null },
    due: { value: displayDue, optimistic: optimisticDue !== null },
    pendingComments,
    changeStatus,
    changeDue,
    addComment,
    retryComment,
    closeTask,
    cancelTask,
    reapply,
    dismissConflict,
  };
}
