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
    <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-2">
      <div className="flex items-center gap-2">
        <span className="text-lg font-semibold text-moss-green">my-pa</span>
        <span className="hidden text-xs text-muted sm:inline">MossAIc personal assistant</span>
      </div>
      <div className="flex items-center gap-3">
        {principal.synthetic ? <Badge tone="synthetic">Synthetic identity</Badge> : null}
        <div className="text-right">
          <div className="text-sm font-medium text-moss-slate" data-testid="principal-name">
            {principal.displayName}
          </div>
          <div className="text-xs text-muted" data-testid="principal-upn">
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
