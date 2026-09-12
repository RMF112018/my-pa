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

export interface TaskRuntimeValue {
  /** Opaque session key: principalId + epoch. Never an API credential. */
  readonly sessionKey: string;
  readonly principalId: string;
  readonly sessionEpoch: string;
  readonly createIntents: CreateIntentStore;
  readonly readCoordinator: TaskReadCoordinator;
  readonly mutationCoordinator: TaskMutationCoordinatorHandle;
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
}

function createBundle(
  principalId: string,
  sessionEpoch: string,
  createMutationCoordinator: CreateMutationCoordinatorFn | undefined,
): TaskRuntimeBundle {
  return {
    sessionKey: buildSessionKey(principalId, sessionEpoch),
    principalId,
    sessionEpoch,
    createIntents: createIntentStore(),
    readCoordinator: createTaskReadCoordinator(),
    mutationCoordinator:
      createMutationCoordinator?.() ?? createDefaultMutationCoordinatorHandle(),
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
  const createMutationRef = useRef(createMutationCoordinator);
  const [bundle, setBundle] = useState<TaskRuntimeBundle>(() =>
    createBundle(principalId, sessionEpoch, createMutationCoordinator),
  );
  const bundleRef = useRef(bundle);

  useEffect(() => {
    createMutationRef.current = createMutationCoordinator;
  }, [createMutationCoordinator]);

  useEffect(() => {
    bundleRef.current = bundle;
  }, [bundle]);

  // Principal / epoch replacement: dispose prior Task client state and mint fresh.
  useEffect(() => {
    const nextKey = buildSessionKey(principalId, sessionEpoch);
    if (bundleRef.current.sessionKey === nextKey) {
      return;
    }
    disposeBundle(bundleRef.current);
    const next = createBundle(principalId, sessionEpoch, createMutationRef.current);
    bundleRef.current = next;
    setBundle(next);
  }, [principalId, sessionEpoch]);

  // Provider unmount: destroy the active bundle.
  useEffect(() => {
    return () => {
      disposeBundle(bundleRef.current);
    };
  }, []);

  return (
    <MutationFeedbackProvider key={bundle.sessionKey}>
      <TaskRuntimeInner bundle={bundle}>{children}</TaskRuntimeInner>
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
