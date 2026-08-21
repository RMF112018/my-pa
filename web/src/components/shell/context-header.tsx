"use client";

import { useRouter } from "next/navigation";
import type { PrincipalSession } from "@/contracts/identity";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function ContextHeader({ principal }: { principal: PrincipalSession }) {
  const router = useRouter();

  async function signOut() {
    await fetch("/api/session", { method: "DELETE", credentials: "same-origin" });
    router.push("/sign-in");
    router.refresh();
  }

  return (
    <header className="flex flex-col gap-2 border-b border-border bg-surface px-4 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-lg font-semibold text-interactive">my-pa</span>
      </div>
      <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 sm:flex sm:gap-3">
        {principal.synthetic ? <Badge tone="synthetic">Synthetic identity</Badge> : null}
        <div className="min-w-0 text-right">
          <div className="truncate text-sm font-medium text-moss-slate" data-testid="principal-name">
            {principal.displayName}
          </div>
          <div className="truncate text-xs text-muted" data-testid="principal-upn">
            {principal.upn}
          </div>
        </div>
        <Button variant="ghost" onClick={signOut}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
