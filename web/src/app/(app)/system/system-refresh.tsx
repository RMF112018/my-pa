"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Button } from "@/components/ui/button";

/**
 * Bounded visible-only System refresh (PFE-AC-125 substrate).
 *
 * User-initiated. No polling interval. No sockets. Reduced motion is honoured
 * by not introducing animation; the global reduce-motion rule already collapses
 * transitions.
 */
export function SystemRefresh() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function refresh() {
    if (document.visibilityState !== "visible") return;
    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <Button
      type="button"
      variant="secondary"
      size="sm"
      onClick={refresh}
      pending={pending}
      data-testid="system-refresh"
    >
      Refresh
    </Button>
  );
}
