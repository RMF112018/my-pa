"use client";

/** Persistent signed-in shell with one main landmark and one launcher owner. */
import { createContext, useContext, useState, type ReactNode } from "react";
import type { PrincipalSession } from "@/contracts/identity";
import { ContextHeader } from "@/components/shell/context-header";
import { NavRail, MobileNav } from "@/components/shell/nav";
import { GlobalLauncher, LauncherPrincipalProvider } from "@/components/shell/global-launcher";
import { OfflineQueueStatus } from "@/components/offline/offline-queue-status";
import { CommandPalette } from "@/components/shell/command-palette";
import { UtilityRegion } from "@/components/shell/utility-region";
import { InspectorSelectionProvider } from "@/components/shell/inspector-selection";
import { useShellPreferences } from "@/components/shell/shell-preferences";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";

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
        <LauncherPrincipalProvider principalId={principal.principalId} sessionEpoch={sessionEpoch}>
          <AppShellBody key={`${principal.principalId}:${sessionEpoch}`} principal={principal}>{children}</AppShellBody>
        </LauncherPrincipalProvider>
      </TaskRuntimeProvider>
    </ProjectScopeProvider>
  );
}

function AppShellBody({ principal, children }: { principal: PrincipalSession; children: ReactNode }) {
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [utilityOpen, setUtilityOpen] = useState(false);
  const { preferences, update } = useShellPreferences();

  const openCapture = () => {
    setSearchOpen(false);
    setLauncherOpen(true);
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
            onNew={openCapture}
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
                className="min-w-0 pt-4 pr-[max(1rem,env(safe-area-inset-right))] pb-[calc(var(--nav-height)+env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] md:pb-6 lg:p-6"
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
          <GlobalLauncher open={launcherOpen} onOpenChange={setLauncherOpen} onConfirmed={() => {}} />
          <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} onCapture={openCapture} />
          <OfflineQueueStatus principalId={principal.principalId} />
        </div>
      </InspectorSelectionProvider>
    </OpenCaptureContext.Provider>
  );
}

export type { CaptureSessionState } from "@/lib/capture/session";
