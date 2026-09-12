"use client";

/**
 * AppShell — persistent chrome around every signed-in destination.
 * Landmarks: banner (header), navigation, main. Capture is always reachable.
 */
import { createContext, useContext, useState, type ReactNode } from "react";
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

const OpenCaptureContext = createContext<() => void>(() => {
  throw new Error("useOpenCapture is only valid inside AppShell");
});

export function useOpenCapture(): () => void {
  return useContext(OpenCaptureContext);
}

export function AppShell({
  principal,
  children,
}: {
  principal: PrincipalSession;
  children: ReactNode;
}) {
  const [captureOpen, setCaptureOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [utilityOpen, setUtilityOpen] = useState(false);
  const { preferences, update } = useShellPreferences();

  const openCapture = () => setCaptureOpen(true);
  const account = {
    principal,
    theme: preferences.theme,
    density: preferences.density,
    onToggleTheme: () => update({ theme: preferences.theme === "light" ? "dark" : "light" }),
    onToggleDensity: () =>
      update({ density: preferences.density === "comfortable" ? "compact" : "comfortable" }),
  };

  // Session epoch keys Task client state; Principal replacement remounts/resets it.
  // identitySubject is the durable auth subject for this shell session — never an API param.
  const sessionEpoch = `${principal.identityProvider}:${principal.identitySubject}`;

  return (
    <TaskRuntimeProvider principalId={principal.principalId} sessionEpoch={sessionEpoch}>
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
                  className="min-w-0 p-4 pb-[calc(var(--nav-height)+env(safe-area-inset-bottom))] lg:p-6 lg:pb-6"
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
              onClose={() => setCaptureOpen(false)}
              principalId={principal.principalId}
            />
            <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} onCapture={openCapture} />
            <OfflineQueueStatus principalId={principal.principalId} />
          </div>
        </InspectorSelectionProvider>
      </OpenCaptureContext.Provider>
    </TaskRuntimeProvider>
  );
}
