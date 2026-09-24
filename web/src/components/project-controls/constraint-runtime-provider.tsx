"use client";

/**
 * Session / Project-scope-bound Constraint runtime — R02-WP10 Phase 4.
 *
 * The **sole** shared Constraint runtime a page mounts (`PC-CM-UX-AC-014`):
 * every later Register/Inspector/authoring/Quick-Capture surface reads this
 * one `ConstraintReadCoordinator` and `ConstraintMutationCoordinator`
 * instance through `useConstraintRuntime()`, never a private copy of its
 * own. Two mounted consumers therefore always observe the same underlying
 * state — there is exactly one runtime, not a competitor per surface.
 *
 * **Epoch identity (SP3.5).** This provider consumes `useProjectScope()`
 * (`@/components/shell/project-scope-provider`, Impl-2 / Phase 3, already
 * landed). Its runtime bundle — read coordinator, mutation coordinator,
 * focus-return registry — is keyed by `principalId :: sessionEpoch ::
 * scopeEpoch` and is disposed and *recreated* (never mutated in place)
 * whenever the Project-scope epoch changes, exactly mirroring how
 * `TaskRuntimeProvider` remints on `principalId`/`sessionEpoch` change. A
 * fresh identity per epoch is what makes the SP3.6 epoch-tag guard in
 * `read-coordinator.ts` / `mutation-coordinator.ts` meaningful rather than
 * redundant: even a request that somehow raced past disposal is still
 * dropped by that per-response epoch check, never by disposal timing alone.
 *
 * **Mount API for Integration (Integrator-only — see this file's own
 * dispatch §7; `app-shell.tsx` itself is never edited here):**
 *
 * ```tsx
 * <ProjectScopeProvider ...>
 *   <TaskRuntimeProvider ...>
 *     <ConstraintRuntimeProvider principalId={principal.principalId} sessionEpoch={sessionEpoch}>
 *       <AppShellBody ...>{children}</AppShellBody>
 *     </ConstraintRuntimeProvider>
 *   </TaskRuntimeProvider>
 * </ProjectScopeProvider>
 * ```
 *
 * `ConstraintRuntimeProvider` must sit *inside* `ProjectScopeProvider` (it
 * calls `useProjectScope()`) and, per §3, is wired between
 * `TaskRuntimeProvider` and `AppShellBody` — it needs no props from
 * `TaskRuntimeProvider` and does not read `useMutationFeedback()` from
 * *outside* its own subtree; it consumes the existing, already-mounted
 * `MutationFeedbackProvider` (mounted inside `TaskRuntimeProvider`,
 * `@/components/work/task-runtime-provider.tsx:355`) because that provider
 * wraps `TaskRuntimeProvider`'s children, and this provider — and the
 * surfaces that will use its coordinators — mount inside those children.
 * `principalId` and `sessionEpoch` are the only two props this provider
 * needs from `AppShell`'s own scope; both are already threaded there for
 * `TaskRuntimeProvider` and mean exactly the same thing here.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import { Sheet } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { useProjectScope } from "@/components/shell/project-scope-provider";
import type { CanSwitchProjectScope } from "@/components/shell/project-picker";
import { buildConstraintSessionKey } from "@/lib/constraint/query-key";
import {
  createConstraintReadCoordinator,
  type ConstraintReadCoordinator,
} from "@/lib/constraint/read-coordinator";
import {
  createConstraintMutationCoordinator,
  type ConstraintMutationCoordinator,
} from "@/lib/constraint/mutation-coordinator";
import {
  createFocusReturnRegistry,
  type FocusReturnRegistry,
} from "@/lib/constraint/focus-return";

export interface ConstraintRuntimeValue {
  /** Opaque session key: `principalId::sessionEpoch`. Never an API credential. */
  readonly sessionKey: string;
  readonly principalId: string;
  readonly sessionEpoch: string;
  /** `useProjectScope().epoch`, captured into this bundle's identity. */
  readonly scopeEpoch: number;
  /** `useProjectScope().isCurrentEpoch`, passed through for coordinator calls. */
  readonly isCurrentEpoch: (epoch: number) => boolean;
  readonly readCoordinator: ConstraintReadCoordinator;
  readonly mutationCoordinator: ConstraintMutationCoordinator;
  readonly focusReturn: FocusReturnRegistry;
  /**
   * The §5a scope-switch barrier, ready to pass straight into
   * `<ProjectPicker canSwitchScope={...} />` — see `useCanSwitchProjectScope`
   * below, which is the documented way to obtain this.
   */
  readonly canSwitchScope: CanSwitchProjectScope;
}

const ConstraintRuntimeContext = createContext<ConstraintRuntimeValue | null>(null);

function buildBundleKey(sessionKey: string, scopeEpoch: number): string {
  return `${sessionKey}::${scopeEpoch}`;
}

interface RuntimeBundle {
  readonly bundleKey: string;
  readonly sessionKey: string;
  readonly scopeEpoch: number;
  readonly readCoordinator: ConstraintReadCoordinator;
  readonly mutationCoordinator: ConstraintMutationCoordinator;
  readonly focusReturn: FocusReturnRegistry;
}

function createBundle(sessionKey: string, scopeEpoch: number): RuntimeBundle {
  return {
    bundleKey: buildBundleKey(sessionKey, scopeEpoch),
    sessionKey,
    scopeEpoch,
    readCoordinator: createConstraintReadCoordinator(),
    mutationCoordinator: createConstraintMutationCoordinator(),
    focusReturn: createFocusReturnRegistry(),
  };
}

function disposeBundle(bundle: RuntimeBundle): void {
  try {
    bundle.mutationCoordinator.dispose();
  } catch {
    // Epoch/session replacement must proceed even if a coordinator throws.
  }
  try {
    bundle.readCoordinator.dispose();
  } catch {
    // same
  }
  try {
    bundle.focusReturn.dispose();
  } catch {
    // same
  }
}

/** Pending confirm/discard prompt for the soft §5a barrier (SP3, case 2). */
interface DiscardPrompt {
  readonly resolve: (allow: boolean) => void;
}

export function ConstraintRuntimeProvider({
  principalId,
  sessionEpoch,
  children,
}: {
  /** Authenticated principal id — session key only; never forwarded to Constraint APIs. */
  readonly principalId: string;
  /** Authenticated session epoch (sid / issuance generation) — same value `TaskRuntimeProvider` receives. */
  readonly sessionEpoch: string;
  readonly children: ReactNode;
}) {
  const projectScope = useProjectScope();
  const sessionKey = buildConstraintSessionKey(principalId, sessionEpoch);
  const desiredKey = buildBundleKey(sessionKey, projectScope.epoch);

  const [bundle, setBundle] = useState<RuntimeBundle>(() => createBundle(sessionKey, projectScope.epoch));
  // Strict Mode runs effect cleanup+setup back-to-back; defer dispose so a
  // remounting setup can cancel it and keep the live coordinators — same
  // pattern `TaskRuntimeProvider` uses for its own bundle.
  const pendingDisposeRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  let activeBundle = bundle;
  if (bundle.bundleKey !== desiredKey) {
    disposeBundle(bundle);
    activeBundle = createBundle(sessionKey, projectScope.epoch);
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
    <ConstraintRuntimeInner
      bundle={activeBundle}
      principalId={principalId}
      sessionEpoch={sessionEpoch}
      isCurrentEpoch={projectScope.isCurrentEpoch}
    >
      {children}
    </ConstraintRuntimeInner>
  );
}

function ConstraintRuntimeInner({
  bundle,
  principalId,
  sessionEpoch,
  isCurrentEpoch,
  children,
}: {
  readonly bundle: RuntimeBundle;
  readonly principalId: string;
  readonly sessionEpoch: string;
  readonly isCurrentEpoch: (epoch: number) => boolean;
  readonly children: ReactNode;
}) {
  // The existing, already-mounted feedback provider (see this file's header
  // comment) — never a second `MutationFeedbackProvider` instance.
  const feedback = useMutationFeedback();
  const [discardPrompt, setDiscardPrompt] = useState<DiscardPrompt | null>(null);

  const resolveDiscardPrompt = useCallback((allow: boolean) => {
    setDiscardPrompt((current) => {
      current?.resolve(allow);
      return null;
    });
  }, []);

  /**
   * §5a `CanSwitchProjectScope`.
   *
   * Case 1 (hard block): any lock held by this epoch's mutation coordinator
   * is, by construction, a pending or ambiguous Constraint mutation — refuse
   * immediately, synchronously, no dialog, no request sent.
   *
   * Case 2 (soft block): no pending/ambiguous mutation, but a later form has
   * reported dirty authored state via
   * `mutationCoordinator.reportDirtyState(surfaceId, true)`. Rather than a
   * plain refusal, this opens the confirm/discard `Sheet` below and resolves
   * the returned Promise only once the person answers it — `true` only on
   * explicit "Discard changes"; cancelling (including Escape / overlay
   * click, which `Sheet`'s `onOpenChange` routes here identically) resolves
   * `false` and leaves route/scope/form untouched, exactly as `ProjectPicker`
   * requires. `ProjectPicker`'s own `PROJECT_PICKER_BLOCKED` notice covers
   * a `false` result in either case; it reads correctly for both a hard
   * block and a declined discard ("Finish or discard what you're doing
   * before switching Projects"), so this function raises no messaging of
   * its own — a deliberate choice, documented in the Phase-4 handoff.
   *
   * No manual "clear the dirty registry" step is needed on confirmed
   * discard: a successful scope switch always changes the Project-scope
   * epoch, and this provider recreates a fresh `mutationCoordinator` (with
   * an empty dirty-surface set) for the new epoch — see the module header.
   */
  const canSwitchScope = useCallback<CanSwitchProjectScope>(() => {
    if (bundle.mutationCoordinator.hasPendingOrAmbiguousMutation()) return false;
    if (!bundle.mutationCoordinator.hasDirtyAuthoredState()) return true;
    return new Promise<boolean>((resolve) => {
      setDiscardPrompt({ resolve });
    });
  }, [bundle]);

  const value = useMemo<ConstraintRuntimeValue>(
    () => ({
      sessionKey: bundle.sessionKey,
      principalId,
      sessionEpoch,
      scopeEpoch: bundle.scopeEpoch,
      isCurrentEpoch,
      readCoordinator: bundle.readCoordinator,
      mutationCoordinator: bundle.mutationCoordinator,
      focusReturn: bundle.focusReturn,
      canSwitchScope,
    }),
    [bundle, principalId, sessionEpoch, isCurrentEpoch, canSwitchScope],
  );

  // `feedback` is consumed only to prove (and, for later workers, document)
  // that this provider mounts where `useMutationFeedback()` is reachable —
  // mutation feedback is otherwise published entirely through
  // `hooks.feedback` on individual `mutate()` calls, not by this provider.
  void feedback;

  return (
    <ConstraintRuntimeContext.Provider value={value}>
      {children}
      <Sheet
        open={discardPrompt !== null}
        onOpenChange={(open) => {
          if (!open) resolveDiscardPrompt(false);
        }}
        title="Discard unsaved changes?"
        description="Switching Projects will discard unsaved Constraint changes in this session."
        placement="inspector"
      >
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            data-testid="constraint-scope-discard-cancel"
            onClick={() => resolveDiscardPrompt(false)}
          >
            Keep editing
          </Button>
          <Button
            type="button"
            variant="primary"
            data-testid="constraint-scope-discard-confirm"
            onClick={() => resolveDiscardPrompt(true)}
          >
            Discard changes
          </Button>
        </div>
      </Sheet>
    </ConstraintRuntimeContext.Provider>
  );
}

export function useConstraintRuntime(): ConstraintRuntimeValue {
  const value = useContext(ConstraintRuntimeContext);
  if (!value) {
    throw new Error("useConstraintRuntime is only valid inside ConstraintRuntimeProvider");
  }
  return value;
}

/**
 * The exact, documented way to obtain the §5a `CanSwitchProjectScope` export
 * for wiring into `<ProjectPicker canSwitchScope={...} />` — a small hook
 * over `useConstraintRuntime()`, per this file's header. Must be called from
 * a component mounted inside `ConstraintRuntimeProvider` (e.g.
 * `context-header.tsx`'s Picker mount, once the Integrator wires this
 * provider into `app-shell.tsx`).
 */
export function useCanSwitchProjectScope(): CanSwitchProjectScope {
  return useConstraintRuntime().canSwitchScope;
}
