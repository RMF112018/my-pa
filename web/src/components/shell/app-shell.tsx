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
import { Button } from "@/components/ui/button";
import { CommandPalette } from "@/components/shell/command-palette";
import { UtilityRegion } from "@/components/shell/utility-region";
import { InspectorSelectionProvider } from "@/components/shell/inspector-selection";
import { useShellPreferences } from "@/components/shell/shell-preferences";

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
  const [commandOpen, setCommandOpen] = useState(false);
  const [utilityOpen, setUtilityOpen] = useState(false);
  const { preferences, update } = useShellPreferences();

  const openCapture = () => setCaptureOpen(true);

  return (
    <OpenCaptureContext.Provider value={openCapture}>
      <InspectorSelectionProvider onSelectionPublished={() => setUtilityOpen(true)}>
        <div className="flex min-h-screen flex-col">
          <ContextHeader
            principal={principal}
            onOpenCommands={() => setCommandOpen(true)}
            theme={preferences.theme}
            onToggleTheme={() =>
              update({ theme: preferences.theme === "light" ? "dark" : "light" })
            }
            onOpenInspector={() => setUtilityOpen(true)}
          />
          <div className="flex flex-1">
            <NavRail
              collapsed={preferences.navCollapsed}
              onCollapsedChange={(navCollapsed) => update({ navCollapsed })}
            />
            <div className="min-w-0 flex-1">
              <main
                id="main"
                className="min-w-0 p-4 pb-[calc(8.5rem+env(safe-area-inset-bottom))] md:p-6"
              >
                {children}
              </main>
            </div>
            <UtilityRegion
              open={utilityOpen || preferences.utilityPinned}
              onOpenChange={setUtilityOpen}
              pinned={preferences.utilityPinned}
              onPinnedChange={(utilityPinned) => update({ utilityPinned })}
              width={preferences.utilityWidth}
              onWidthChange={(utilityWidth) => update({ utilityWidth })}
            />
          </div>
          <MobileNav />
          <Button
            onClick={() => setCaptureOpen(true)}
            aria-haspopup="dialog"
            className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] right-4 z-20 rounded-full shadow-lg md:bottom-6"
            data-testid="capture-button"
          >
            + Capture
          </Button>
          <CaptureDialog
            open={captureOpen}
            onClose={() => setCaptureOpen(false)}
            principalId={principal.principalId}
          />
          <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} onCapture={openCapture} />
          <OfflineQueueStatus principalId={principal.principalId} />
        </div>
      </InspectorSelectionProvider>
    </OpenCaptureContext.Provider>
  );
}
