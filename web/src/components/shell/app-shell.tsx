"use client";

/**
 * AppShell — persistent chrome around every signed-in destination.
 * Landmarks: banner (header), navigation, main. Capture is always reachable.
 */
import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { PrincipalSession } from "@/contracts/identity";
import { ContextHeader } from "@/components/shell/context-header";
import { NavRail, MobileNav } from "@/components/shell/nav";
import { CaptureDialog } from "@/components/shell/capture-dialog";
import { OfflineQueueStatus } from "@/components/offline/offline-queue-status";
import { CommandPalette } from "@/components/shell/command-palette";
import { UtilityRegion } from "@/components/shell/utility-region";
import { InspectorSelectionProvider } from "@/components/shell/inspector-selection";
import { useShellPreferences } from "@/components/shell/shell-preferences";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { TaskCreateSheet } from "@/components/tasks/task-create-sheet";
import { ConstraintRuntimeProvider } from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider, useProjectScope } from "@/components/shell/project-scope-provider";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";
import {
  beginCaptureExperience,
  captureSessionReducer,
  type CaptureSessionState,
} from "@/lib/capture/session";

const OpenCaptureContext = createContext<() => void>(() => {
  throw new Error("useOpenCapture is only valid inside AppShell");
});

export function useOpenCapture(): () => void {
  return useContext(OpenCaptureContext);
}

export function AppShell({
  principal,
  sessionEpoch,
  initialProjectScope,
  children,
}: {
  principal: PrincipalSession;
  /** Browser-safe digest bound to the exact verified HttpOnly session SID. */
  sessionEpoch: string;
  initialProjectScope?: ResolvedProjectScope;
  children: ReactNode;
}) {
  return (
    <ProjectScopeProvider
      principalId={principal.principalId}
      sessionEpoch={sessionEpoch}
      initialResolution={initialProjectScope}
    >
      <TaskRuntimeProvider principalId={principal.principalId} sessionEpoch={sessionEpoch}>
        <ConstraintRuntimeProvider principalId={principal.principalId} sessionEpoch={sessionEpoch}>
          <AppShellBody principal={principal}>{children}</AppShellBody>
        </ConstraintRuntimeProvider>
      </TaskRuntimeProvider>
    </ProjectScopeProvider>
  );
}

/**
 * The shell's consumer body, and the sole owner of the local Capture experience.
 *
 * It is an inner component rather than the outer one for one reason: it has to
 * read the global Project Scope that `ProjectScopeProvider` supplies, and a
 * component cannot consume a context it mounts itself. Nothing was duplicated —
 * the providers above are the existing ones, moved above this body rather than
 * around it.
 *
 * The Capture Project context lives here, in one reducer, and is initialized
 * from global scope exactly once per experience. Nothing in this file writes
 * global scope back.
 */
function AppShellBody({
  principal,
  children,
}: {
  principal: PrincipalSession;
  children: ReactNode;
}) {
  const globalScope = useProjectScope();
  const [captureOpen, setCaptureOpen] = useState(false);
  // Capture and the Task sheet are two overlays that are never open together:
  // the handoff below closes one before it opens the other, so there is exactly
  // one modal owner at a time and no nested dialog stack to trap focus in.
  const [taskCreateOpen, setTaskCreateOpen] = useState(false);
  // Whatever had focus when Capture was opened, so closing the Task sheet the
  // Capture chooser handed off to returns focus where the person started.
  const captureInvokerRef = useRef<HTMLElement | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [utilityOpen, setUtilityOpen] = useState(false);
  const { preferences, update } = useShellPreferences();

  /** The Project global scope currently names, or null for ALL_PROJECTS. */
  const globalProjectId =
    globalScope.resolution.scope.kind === "PROJECT"
      ? globalScope.resolution.scope.projectId
      : null;

  const [capture, dispatchCapture] = useReducer(
    captureSessionReducer,
    { principalId: principal.principalId, sessionEpoch: globalScope.epoch, projectId: null },
    (seed: { principalId: string; sessionEpoch: number; projectId: string | null }) =>
      beginCaptureExperience({ experienceId: "capture-initial", ...seed }),
  );

  /**
   * The Project a Capture-launched Task starts from.
   *
   * Held separately from the reducer because it is the launcher's *proposal*:
   * the Task sheet decides whether it applies, and a frozen intent overrules it.
   */
  const [taskLauncherProject, setTaskLauncherProject] = useState<string | null>(null);
  const taskContext = useMemo(
    () => (taskLauncherProject ? { projectId: taskLauncherProject } : undefined),
    [taskLauncherProject],
  );

  const openCapture = () => {
    captureInvokerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // A fresh open reads global scope once. It never writes it, and it never
    // reads a previous experience's local selection back.
    dispatchCapture({
      type: "open",
      experienceId: `capture-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      principalId: principal.principalId,
      sessionEpoch: globalScope.epoch,
      projectId: globalProjectId,
    });
    setCaptureOpen(true);
  };

  /**
   * Capture reported Create Task. Nothing was captured and nothing was queued —
   * this is only a change of surface. Capture closes first, then the canonical
   * Task sheet opens; Task creation never enters the capture offline queue.
   *
   * The nullable Project travels as an explicit argument, and the Capture
   * experience is suspended rather than ended so Back can resume it.
   */
  const handleCreateTaskFromCapture = (projectId: string | null) => {
    setTaskLauncherProject(projectId);
    dispatchCapture({ type: "to_task" });
    setCaptureOpen(false);
    setTaskCreateOpen(true);
  };

  /**
   * Back out of a Capture-launched Task sheet: return to the same Capture
   * experience, adopting the Project the Task sheet actually holds.
   */
  const backToCapture = (context: { projectId: string | null }) => {
    setTaskCreateOpen(false);
    dispatchCapture({ type: "task_back", projectId: context.projectId });
    setCaptureOpen(true);
  };

  const handleTaskCreateOpenChange = (next: boolean) => {
    setTaskCreateOpen(next);
    if (next) return;
    // The sheet returns focus to whatever it took it from, which for a
    // Capture-launched sheet is a control that is now unmounted. Take focus
    // back after that has run so it lands on the button the person pressed.
    const invoker = captureInvokerRef.current;
    if (invoker?.isConnected) window.setTimeout(() => invoker.focus(), 0);
  };
  const account = {
    principal,
    theme: preferences.theme,
    density: preferences.density,
    onToggleTheme: () => update({ theme: preferences.theme === "light" ? "dark" : "light" }),
    onToggleDensity: () =>
      update({ density: preferences.density === "comfortable" ? "compact" : "comfortable" }),
  };

  return (
    <OpenCaptureContext.Provider value={openCapture}>
      <InspectorSelectionProvider onSelectionPublished={() => setUtilityOpen(true)}>
        <div className="flex min-h-screen flex-col">
          <ContextHeader
            principal={account.principal}
            theme={account.theme}
            density={account.density}
            onToggleTheme={account.onToggleTheme}
            onToggleDensity={account.onToggleDensity}
          />
          <div className="flex flex-1">
            <NavRail
              collapsed={preferences.navCollapsed}
              onCollapsedChange={(navCollapsed) => update({ navCollapsed })}
              onCapture={openCapture}
              account={account}
            />
            <div className="min-w-0 flex-1">
              <main
                id="main"
                /*
                 * Below `lg` the nav rail is hidden, so `main` is the
                 * full-width in-flow region and its left and right edges are
                 * physical edges in landscape. It remains the single supplier
                 * of the bottom inset for its subtree (see work-detail.tsx,
                 * which gave up its own). At `lg` the shorthand takes over:
                 * the rail and the utility region own the sides there, and no
                 * device at that width reports a non-zero side inset.
                 */
                className="min-w-0 pt-4 pr-[max(1rem,env(safe-area-inset-right))] pb-[calc(var(--nav-height)+env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] lg:p-6 lg:pb-6"
              >
                {children}
              </main>
            </div>
            {utilityOpen || preferences.utilityPinned ? (
              <UtilityRegion
                open={utilityOpen || preferences.utilityPinned}
                onOpenChange={setUtilityOpen}
                pinned={preferences.utilityPinned}
                onPinnedChange={(utilityPinned) => update({ utilityPinned })}
                width={preferences.utilityWidth}
                onWidthChange={(utilityWidth) => update({ utilityWidth })}
              />
            ) : null}
          </div>
          <MobileNav onCapture={openCapture} />
          <CaptureDialog
            open={captureOpen}
            onClose={() => {
              dispatchCapture({ type: "close" });
              setCaptureOpen(false);
            }}
            principalId={principal.principalId}
            session={capture}
            dispatch={dispatchCapture}
            onCreateTask={handleCreateTaskFromCapture}
          />
          <TaskCreateSheet
            open={taskCreateOpen}
            onOpenChange={handleTaskCreateOpenChange}
            entry="capture"
            context={taskContext}
            principalId={principal.principalId}
            sessionEpoch={globalScope.epoch}
            onBack={backToCapture}
          />
          <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} onCapture={openCapture} />
          <OfflineQueueStatus principalId={principal.principalId} />
        </div>
      </InspectorSelectionProvider>
    </OpenCaptureContext.Provider>
  );
}

export type { CaptureSessionState };
