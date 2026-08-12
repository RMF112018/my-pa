"use client";

/**
 * AppShell — persistent chrome around every signed-in destination.
 * Landmarks: banner (header), navigation, main. Capture is always reachable.
 */
import { useState, type ReactNode } from "react";
import type { PrincipalSession } from "@/contracts/identity";
import { ContextHeader } from "@/components/shell/context-header";
import { NavRail, MobileNav } from "@/components/shell/nav";
import { CaptureDialog } from "@/components/shell/capture-dialog";
import { Button } from "@/components/ui/button";

export function AppShell({
  principal,
  children,
}: {
  principal: PrincipalSession;
  children: ReactNode;
}) {
  const [captureOpen, setCaptureOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col">
      <ContextHeader principal={principal} />
      <div className="flex flex-1">
        <NavRail />
        <main id="main" className="flex-1 p-4 pb-20 md:pb-4">
          {children}
        </main>
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
      <CaptureDialog open={captureOpen} onClose={() => setCaptureOpen(false)} />
    </div>
  );
}
