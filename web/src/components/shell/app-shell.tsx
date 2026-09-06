"use client";

/**
 * AppShell — persistent chrome around every signed-in destination.
 * Landmarks: banner (header), navigation, main. Capture is always reachable.
 */
import { useState, type ReactNode } from "react";
import { Command, Moon, PanelRightOpen, Sun } from "lucide-react";
import type { PrincipalSession } from "@/contracts/identity";
import { ContextHeader } from "@/components/shell/context-header";
import { NavRail, MobileNav } from "@/components/shell/nav";
import { CaptureDialog } from "@/components/shell/capture-dialog";
import { OfflineQueueStatus } from "@/components/offline/offline-queue-status";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { CommandPalette } from "@/components/shell/command-palette";
import { UtilityRegion } from "@/components/shell/utility-region";
import { InspectorSelectionProvider } from "@/components/shell/inspector-selection";
import { useShellPreferences } from "@/components/shell/shell-preferences";

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

  return (
    <InspectorSelectionProvider onSelectionPublished={() => setUtilityOpen(true)}>
      <div className="flex min-h-screen flex-col">
      <ContextHeader principal={principal} />
      <div className="flex flex-1">
        <NavRail collapsed={preferences.navCollapsed} onCollapsedChange={(navCollapsed) => update({ navCollapsed })} />
        <div className="min-w-0 flex-1"><div className="flex min-h-12 items-center justify-end gap-1 border-b bg-surface px-3"><Button variant="ghost" size="sm" onClick={() => setCommandOpen(true)}><Command size={17} />Commands <span className="hidden text-xs text-text-muted sm:inline">⌘K</span></Button><IconButton label={preferences.theme === "light" ? "Use dark theme" : "Use light theme"} onClick={() => update({ theme: preferences.theme === "light" ? "dark" : "light" })}>{preferences.theme === "light" ? <Moon size={18} /> : <Sun size={18} />}</IconButton><IconButton label="Open Inspector" className="md:hidden" onClick={() => setUtilityOpen(true)}><PanelRightOpen size={18} /></IconButton></div><main id="main" className="min-w-0 p-4 pb-24 md:p-6">{children}</main></div>
        <UtilityRegion open={utilityOpen || preferences.utilityPinned} onOpenChange={setUtilityOpen} pinned={preferences.utilityPinned} onPinnedChange={(utilityPinned) => update({ utilityPinned })} width={preferences.utilityWidth} onWidthChange={(utilityWidth) => update({ utilityWidth })} />
      </div>
      <MobileNav />
      <Button
        onClick={() => setCaptureOpen(true)}
        aria-haspopup="dialog"
        className="fixed bottom-16 right-4 z-20 rounded-full shadow-lg md:bottom-6"
        data-testid="capture-button"
      >
        + Capture
      </Button>
      <CaptureDialog
        open={captureOpen}
        onClose={() => setCaptureOpen(false)}
        principalId={principal.principalId}
      />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} onCapture={() => setCaptureOpen(true)} />
      <OfflineQueueStatus principalId={principal.principalId} />
      </div>
    </InspectorSelectionProvider>
  );
}
