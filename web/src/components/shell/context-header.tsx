"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ClipboardCheck, Moon, Sun, User } from "lucide-react";
import { activeFor } from "@/components/shell/destinations";
import type { PrincipalSession } from "@/contracts/identity";
import type { Density, Theme } from "@/components/shell/shell-preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Sheet } from "@/components/ui/sheet";

export type AccountMenuProps = {
  principal: PrincipalSession;
  theme: Theme;
  density: Density;
  onToggleTheme: () => void;
  onToggleDensity: () => void;
  collapsed?: boolean;
  labeled?: boolean;
};

export function AccountMenu({
  principal,
  theme,
  density,
  onToggleTheme,
  onToggleDensity,
  collapsed = false,
  labeled = false,
}: AccountMenuProps) {
  const router = useRouter();
  const [accountOpen, setAccountOpen] = useState(false);

  async function signOut() {
    await fetch("/api/session", { method: "DELETE", credentials: "same-origin" });
    router.push("/sign-in");
    router.refresh();
  }

  return (
    <>
      {labeled ? (
        <button
          type="button"
          aria-haspopup="dialog"
          title={collapsed ? "Account" : undefined}
          onClick={() => setAccountOpen(true)}
          className="flex min-h-11 items-center gap-3 rounded-[var(--radius-md)] px-3 text-sm font-medium text-text-secondary hover:bg-surface-subtle hover:text-text-primary"
        >
          <User size={19} />
          <span className={collapsed ? "sr-only" : ""}>Account</span>
        </button>
      ) : (
        <IconButton label="Account" aria-haspopup="dialog" onClick={() => setAccountOpen(true)}>
          <User size={18} />
        </IconButton>
      )}
      <Sheet open={accountOpen} onOpenChange={setAccountOpen} title="Account" placement="menu">
        {principal.synthetic ? (
          <div className="mb-3">
            <Badge tone="synthetic">Synthetic identity</Badge>
          </div>
        ) : null}
        <div className="truncate text-sm font-medium text-text-primary" data-testid="principal-name">
          {principal.displayName}
        </div>
        <div className="truncate text-xs text-muted" data-testid="principal-upn">
          {principal.upn ?? principal.identitySubject}
        </div>
        <div className="mt-4 border-t pt-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Appearance</p>
          <div className="flex flex-col items-start gap-1">
            <IconButton
              label={theme === "light" ? "Use dark theme" : "Use light theme"}
              onClick={onToggleTheme}
            >
              {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
              <span className="ml-2 text-sm">{theme === "light" ? "Dark theme" : "Light theme"}</span>
            </IconButton>
            <Button
              variant="ghost"
              onClick={onToggleDensity}
              aria-pressed={density === "compact"}
            >
              {density === "comfortable" ? "Use compact density" : "Use comfortable density"}
            </Button>
          </div>
        </div>
        <Button className="mt-4" variant="ghost" onClick={signOut}>
          Sign out
        </Button>
      </Sheet>
    </>
  );
}

export function ContextHeader({
  principal,
  theme,
  density,
  onToggleTheme,
  onToggleDensity,
}: {
  principal: PrincipalSession;
  theme: Theme;
  density: Density;
  onToggleTheme: () => void;
  onToggleDensity: () => void;
}) {
  const pathname = usePathname() ?? "";
  const reviewActive = activeFor(pathname, "/review");

  return (
    <header className="flex min-h-12 items-center justify-between gap-2 border-b border-border bg-surface px-3 py-1.5 lg:hidden">
      <span className="shrink-0 text-lg font-semibold text-interactive">My PA</span>
      <div className="ml-auto flex min-w-0 items-center justify-end gap-1">
        <Link
          href="/review"
          aria-label="Review"
          aria-current={reviewActive ? "page" : undefined}
          className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--radius-md)] ${
            reviewActive ? "bg-interactive-subtle text-interactive" : "text-text-secondary"
          }`}
        >
          <ClipboardCheck size={18} />
        </Link>
        <AccountMenu
          principal={principal}
          theme={theme}
          density={density}
          onToggleTheme={onToggleTheme}
          onToggleDensity={onToggleDensity}
        />
      </div>
    </header>
  );
}
