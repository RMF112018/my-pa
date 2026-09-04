import type { ReactNode } from "react";

export type LiveAnnouncementTone = "status" | "alert";

/**
 * Shared live-region for mutation outcomes, conflicts, and degraded refetch.
 *
 * Status uses a polite live region; alerts use assertive + role="alert" so a
 * refusal or conflict is not missed. Colour is never the only carrier.
 */
export function LiveAnnouncement({
  children,
  tone = "status",
  testId,
}: {
  readonly children: ReactNode;
  readonly tone?: LiveAnnouncementTone;
  readonly testId?: string;
}) {
  const isAlert = tone === "alert";
  return (
    <p
      role={isAlert ? "alert" : "status"}
      aria-live={isAlert ? "assertive" : "polite"}
      aria-atomic="true"
      data-testid={testId ?? `live-${tone}`}
      className={isAlert ? "text-sm text-moss-coral-strong" : "text-sm text-muted"}
    >
      {children}
    </p>
  );
}
