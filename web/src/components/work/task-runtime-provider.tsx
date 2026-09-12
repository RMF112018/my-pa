"use client";

/**
 * AppShell / session-scoped Task runtime.
 *
 * Owns create-intent store, read coordinator, and mutation coordinator for one
 * authenticated session epoch. Principal replacement destroys all Task client
 * state. Principal is never sent as an API parameter — only `principalId` /
 * `sessionEpoch` key the runtime.
 *
 * Mount API for Integration (AppShell owner):
 *
 * ```tsx
 * <TaskRuntimeProvider
 *   principalId={principal.principalId}
 *   sessionEpoch={sessionEpoch}
 * >
 *   {children}
 * </TaskRuntimeProvider>
 * ```
 *
 * Defaults to `createTaskMutationCoordinator` from `@/lib/task/mutation-coordinator`.
 * Tests may inject a fake via `createMutationCoordinator`.
 *
 * Do not mount inside Workbench/detail — lifetime is the signed-in shell.
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  MutationFeedbackProvider,
  useMutationFeedback,
  type MutationFeedbackValue,
} from "@/components/ui/mutation-feedback";
import {
  createIntentStore,
  type CreateIntentStore,
} from "@/lib/task/create-intent";
import {
  createTaskMutationCoordinator,
  type TaskMutationCoordinator,
} from "@/lib/task/mutation-coordinator";
import type { MutationKind } from "@/lib/task/mutation-state";
import { buildTaskQueryKey } from "@/lib/task/query-key";
import {
  createTaskReadCoordinator,
  type TaskReadCoordinator,
} from "@/lib/task/read-coordinator";

/**
 * Runtime-owned mutation coordinator handle.
 * `coordinator` is Worker A's TaskMutationCoordinator; `dispose` runs on
 * principal/epoch replacement (Maps only today — no timers to cancel).
 */
export interface TaskMutationCoordinatorHandle {
  readonly coordinator: TaskMutationCoordinator;
  readonly dispose: () => void;
}

export type CreateMutationCoordinatorFn = () => TaskMutationCoordinatorHandle;

function createDefaultMutationCoordinatorHandle(): TaskMutationCoordinatorHandle {
  const coordinator = createTaskMutationCoordinator();
  return {
    coordinator,
    dispose() {
      // No owned timers/listeners; dropping the instance is sufficient.
    },
  };
}

/**
 * A currently-mounted Task query's own revalidation hook. Called with no
 * arguments: the confirmed Task is never handed to a list query, because only
 * the server decides which Work bucket/filter the new Task belongs to.
 */
export type TaskQueryRevalidator = () => void | Promise<unknown>;

/**
 * One confirmed Task mutation, described for reconciliation.
 *
 * `task` is the server's authoritative Task when the confirming response carried
 * one; it is used only to raise the entity barrier, never merged into a list.
 * `mutationId` is the logical attempt identity (the mutation coordinator's
 * `attemptId`) and is the dedupe key: repeated notifications carrying the same
 * `mutationId` schedule exactly one revalidation pass.
 */
export interface TaskMutationConfirmation {
  readonly kind: MutationKind;
  readonly task?: unknown;
  readonly taskId?: string;
  readonly mutationId?: string;
}

/**
 * Session-scoped confirmed-mutation reconciliation seam.
 *
 * Any surface that can confirm a Task mutation — Work's create sheet, a
 * shell-launched Capture create Work does not own, the Work list row controls,
 * or Task detail — calls `notifyTaskMutationConfirmed`. Every Task query that is
 * mounted right now is asked to revalidate against the server. This is not a
 * cache: nothing is stored, nothing is merged client-side, and no timer is
 * owned. Registrations live only as long as this session bundle and are dropped
 * on principal/epoch replacement.
 */
export interface TaskReconciliationRegistry {
  /** Register a mounted query's revalidation hook. Returns its unregister fn. */
  registerActiveTaskQuery: (queryId: string, revalidate: TaskQueryRevalidator) => () => void;
  unregisterActiveTaskQuery: (queryId: string) => void;
  /**
   * Fire-and-forget: a confirmed mutation must settle even with zero active
   * queries, and a failing or hanging revalidation never propagates.
   */
  notifyTaskMutationConfirmed: (input: TaskMutationConfirmation) => void;
  /** Create-shaped convenience over {@link notifyTaskMutationConfirmed}. */
  notifyCreateConfirmed: (confirmedTask?: unknown, mutationId?: string) => void;
  /** Registration ids currently active — diagnostics and tests only. */
  activeTaskQueryIds: () => readonly string[];
  isDisposed: () => boolean;
  dispose: () => void;
}

/** Bounded so one long session cannot grow the dedupe ledger without limit. */
const RECONCILE_DEDUPE_LIMIT = 64;

function readTaskId(task: unknown): string | undefined {
  if (!task || typeof task !== "object") return undefined;
  const candidate = task as { task_id?: unknown; task?: unknown };
  if (typeof candidate.task_id === "string" && candidate.task_id) return candidate.task_id;
  if (candidate.task !== undefined) return readTaskId(candidate.task);
  return undefined;
}

function unwrapTask(task: unknown): unknown {
  if (!task || typeof task !== "object") return task;
  const candidate = task as { task_id?: unknown; task?: unknown };
  if (typeof candidate.task_id === "string") return task;
  if (candidate.task !== undefined) return unwrapTask(candidate.task);
  return task;
}

function createTaskReconciliationRegistry(options: {
  readonly readCoordinator: TaskReadCoordinator;
  readonly sessionEpoch: string;
}): TaskReconciliationRegistry {
  const queries = new Map<string, TaskQueryRevalidator>();
  /** Logical mutation identities already reconciled in this session bundle. */
  const settled = new Set<string>();
  let disposed = false;

  function rememberMutation(mutationId: string): boolean {
    if (settled.has(mutationId)) return false;
    if (settled.size >= RECONCILE_DEDUPE_LIMIT) {
      const oldest = settled.values().next().value;
      if (oldest !== undefined) settled.delete(oldest);
    }
    settled.add(mutationId);
    return true;
  }

  function raiseEntityBarrier(taskId: string): void {
    try {
      options.readCoordinator.raiseMutationBarrier(
        buildTaskQueryKey({ mode: "detail", taskId, sessionEpoch: options.sessionEpoch }),
        { entityId: taskId },
      );
    } catch {
      // A disposed or unavailable read coordinator must never fail a confirmed
      // mutation; the barrier is an ordering optimisation, not the write itself.
    }
  }

  function notifyTaskMutationConfirmed(input: TaskMutationConfirmation): void {
    if (disposed) return;
    // One logical mutation schedules exactly one revalidation pass, however
    // many surfaces report the same confirmation.
    if (input.mutationId !== undefined && !rememberMutation(input.mutationId)) return;

    const authoritative = unwrapTask(input.task);
    const taskId = input.taskId ?? readTaskId(input.task);
    // Authoritative Task in hand: an older in-flight read for this entity must
    // not be allowed to overwrite the newer confirmed state.
    if (authoritative !== undefined && authoritative !== null && taskId) {
      raiseEntityBarrier(taskId);
    }

    // The confirmed Task is deliberately not applied to any list: Work bucket
    // and filter membership is a server answer, never a client derivation.
    for (const revalidate of Array.from(queries.values())) {
      try {
        void Promise.resolve(revalidate()).catch(() => undefined);
      } catch {
        // A failing query revalidation must never fail a confirmed mutation.
      }
    }
  }

  return {
    registerActiveTaskQuery(queryId, revalidate) {
      if (disposed) return () => undefined;
      queries.set(queryId, revalidate);
      return () => {
        if (queries.get(queryId) === revalidate) queries.delete(queryId);
      };
    },
    unregisterActiveTaskQuery(queryId) {
      queries.delete(queryId);
    },
    notifyTaskMutationConfirmed,
    notifyCreateConfirmed(confirmedTask?: unknown, mutationId?: string) {
      notifyTaskMutationConfirmed({ kind: "create", task: confirmedTask, mutationId });
    },
    activeTaskQueryIds() {
      return Array.from(queries.keys());
    },
    isDisposed() {
      return disposed;
    },
    dispose() {
      disposed = true;
      queries.clear();
      settled.clear();
    },
  };
}

export interface TaskRuntimeValue {
  /** Opaque session key: principalId + epoch. Never an API credential. */
  readonly sessionKey: string;
  readonly principalId: string;
  readonly sessionEpoch: string;
  readonly createIntents: CreateIntentStore;
  readonly readCoordinator: TaskReadCoordinator;
  readonly mutationCoordinator: TaskMutationCoordinatorHandle;
  /** Confirmed-mutation → active-Task-query reconciliation seam (session-scoped). */
  readonly reconciliation: TaskReconciliationRegistry;
  readonly feedback: MutationFeedbackValue;
}

const TaskRuntimeContext = createContext<TaskRuntimeValue | null>(null);

function buildSessionKey(principalId: string, sessionEpoch: string): string {
  return `${principalId}::${sessionEpoch}`;
}

interface TaskRuntimeBundle {
  readonly sessionKey: string;
  readonly principalId: string;
  readonly sessionEpoch: string;
  readonly createIntents: CreateIntentStore;
  readonly readCoordinator: TaskReadCoordinator;
  readonly mutationCoordinator: TaskMutationCoordinatorHandle;
  readonly reconciliation: TaskReconciliationRegistry;
}

function createBundle(
  principalId: string,
  sessionEpoch: string,
  createMutationCoordinator: CreateMutationCoordinatorFn | undefined,
): TaskRuntimeBundle {
  const readCoordinator = createTaskReadCoordinator();
  return {
    sessionKey: buildSessionKey(principalId, sessionEpoch),
    principalId,
    sessionEpoch,
    createIntents: createIntentStore(),
    readCoordinator,
    mutationCoordinator:
      createMutationCoordinator?.() ?? createDefaultMutationCoordinatorHandle(),
    reconciliation: createTaskReconciliationRegistry({ readCoordinator, sessionEpoch }),
  };
}

function disposeBundle(bundle: TaskRuntimeBundle): void {
  try {
    bundle.mutationCoordinator.dispose();
  } catch {
    // Principal replacement must proceed even if a coordinator dispose throws.
  }
  try {
    bundle.readCoordinator.dispose();
  } catch {
    // same
  }
  try {
    bundle.createIntents.clearAll();
  } catch {
    // same
  }
  try {
    // Drops every active-query registration made under the replaced session.
    bundle.reconciliation.dispose();
  } catch {
    // same
  }
}

export function TaskRuntimeProvider({
  principalId,
  sessionEpoch = "default",
  children,
  createMutationCoordinator,
}: {
  /** Authenticated principal id — session key only; never forwarded to Task APIs. */
  readonly principalId: string;
  /**
   * Authenticated session epoch (sid / issuance generation). Changing this or
   * `principalId` destroys all Task client state for the prior epoch.
   */
  readonly sessionEpoch?: string;
  readonly children: ReactNode;
  /** Override factory for tests; production default uses Worker A's module. */
  readonly createMutationCoordinator?: CreateMutationCoordinatorFn;
}) {
  const desiredKey = buildSessionKey(principalId, sessionEpoch);
  const [bundle, setBundle] = useState<TaskRuntimeBundle>(() =>
    createBundle(principalId, sessionEpoch, createMutationCoordinator),
  );
  // Strict Mode runs effect cleanup+setup back-to-back; defer dispose so the
  // remounting setup can cancel it and keep the live coordinator.
  const pendingDisposeRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Remint during render when the session key changes or a deferred dispose
  // already ran (restored state still points at a disposed instance).
  let activeBundle = bundle;
  if (bundle.sessionKey !== desiredKey || bundle.readCoordinator.isDisposed()) {
    if (bundle.sessionKey !== desiredKey && !bundle.readCoordinator.isDisposed()) {
      disposeBundle(bundle);
    }
    activeBundle = createBundle(principalId, sessionEpoch, createMutationCoordinator);
    setBundle(activeBundle);
  }

  useEffect(() => {
    if (pendingDisposeRef.current != null) {
      clearTimeout(pendingDisposeRef.current);
      pendingDisposeRef.current = null;
    }
    const owned = activeBundle;
    return () => {
      pendingDisposeRef.current = setTimeout(() => {
        disposeBundle(owned);
        pendingDisposeRef.current = null;
      }, 0);
    };
  }, [activeBundle]);

  return (
    <MutationFeedbackProvider key={activeBundle.sessionKey}>
      <TaskRuntimeInner bundle={activeBundle}>{children}</TaskRuntimeInner>
    </MutationFeedbackProvider>
  );
}

function TaskRuntimeInner({
  bundle,
  children,
}: {
  readonly bundle: TaskRuntimeBundle;
  readonly children: ReactNode;
}) {
  const feedback = useMutationFeedback();
  const value = useMemo<TaskRuntimeValue>(
    () => ({
      sessionKey: bundle.sessionKey,
      principalId: bundle.principalId,
      sessionEpoch: bundle.sessionEpoch,
      createIntents: bundle.createIntents,
      readCoordinator: bundle.readCoordinator,
      mutationCoordinator: bundle.mutationCoordinator,
      reconciliation: bundle.reconciliation,
      feedback,
    }),
    [bundle, feedback],
  );

  return <TaskRuntimeContext.Provider value={value}>{children}</TaskRuntimeContext.Provider>;
}

export function useTaskRuntime(): TaskRuntimeValue {
  const value = useContext(TaskRuntimeContext);
  if (!value) {
    throw new Error("useTaskRuntime is only valid inside TaskRuntimeProvider");
  }
  return value;
}

export { useMutationFeedback };
