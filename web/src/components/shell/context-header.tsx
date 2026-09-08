"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Command, Moon, PanelRightOpen, Sun, User } from "lucide-react";
import type { PrincipalSession } from "@/contracts/identity";
import type { Theme } from "@/components/shell/shell-preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Sheet } from "@/components/ui/sheet";

export function ContextHeader({
  principal,
  onOpenCommands,
  theme,
  onToggleTheme,
  onOpenInspector,
}: {
  principal: PrincipalSession;
  onOpenCommands: () => void;
  theme: Theme;
  onToggleTheme: () => void;
  onOpenInspector: () => void;
}) {
  const router = useRouter();
  const [accountOpen, setAccountOpen] = useState(false);

  async function signOut() {
    await fetch("/api/session", { method: "DELETE", credentials: "same-origin" });
    router.push("/sign-in");
    router.refresh();
  }

  return (
    <header className="flex min-h-12 items-center justify-between gap-2 border-b border-border bg-surface px-3 py-1.5 md:px-4">
      <span className="shrink-0 text-lg font-semibold text-interactive">my-pa</span>
      <div className="flex min-w-0 items-center justify-end gap-1">
        <Button variant="ghost" size="sm" onClick={onOpenCommands}>
          <Command size={17} />
          Commands <span className="hidden text-xs text-text-muted sm:inline">⌘K</span>
        </Button>
        <IconButton
          label={theme === "light" ? "Use dark theme" : "Use light theme"}
          onClick={onToggleTheme}
        >
          {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
        </IconButton>
        <IconButton label="Open Inspector" className="md:hidden" onClick={onOpenInspector}>
          <PanelRightOpen size={18} />
        </IconButton>
        <IconButton
          label="Account"
          aria-haspopup="dialog"
          onClick={() => setAccountOpen(true)}
        >
          <User size={18} />
        </IconButton>
      </div>
      <Sheet open={accountOpen} onOpenChange={setAccountOpen} title="Account">
        {principal.synthetic ? (
          <div className="mb-3">
            <Badge tone="synthetic">Synthetic identity</Badge>
          </div>
        ) : null}
        <div className="truncate text-sm font-medium text-moss-slate" data-testid="principal-name">
          {principal.displayName}
        </div>
        <div className="truncate text-xs text-muted" data-testid="principal-upn">
          {principal.upn ?? principal.identitySubject}
        </div>
        <Button className="mt-4" variant="ghost" onClick={signOut}>
          Sign out
        </Button>
      </Sheet>
    </header>
  );
}
