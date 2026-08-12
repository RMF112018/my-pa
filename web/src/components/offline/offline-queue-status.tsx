"use client";

/**
 * What this device is still holding, and the replay that tries to empty it.
 *
 * **Replay is a foreground path.** It runs when this component mounts and when
 * the browser fires `online`, and nowhere else. Background Sync is not used and
 * nothing here claims that a closed tab will send anything.
 *
 * **Queued is never rendered as saved.** Every count below describes notes that
 * exist only on this device. The wording says so in each state, because the
 * whole hazard of an offline queue is a person reading "3 notes" as "3 notes
 * filed" and closing the tab.
 *
 * **A quarantined count is shown rather than hidden.** Notes queued by a
 * different principal are not replayed and not deleted; they are held and
 * counted, so nobody has to guess whether they still exist. They are also not
 * released by this component — see the limitation in `lib/offline/queue.ts`.
 *
 * The component renders nothing at all when the queue is empty, which is the
 * ordinary case; a persistent zero-state badge would be chrome for a condition
 * that does not exist.
 */
import { useCallback, useEffect, useState } from "react";
import { drainCaptureQueue } from "@/lib/offline/capture-queue";
import type { QueueCounts } from "@/lib/offline/queue";

export function OfflineQueueStatus({ principalId }: { principalId: string }) {
  const [counts, setCounts] = useState<QueueCounts | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const drain = useCallback(async () => {
    try {
      const result = await drainCaptureQueue(principalId);
      setCounts(result.counts);
      setFailure(null);
    } catch (error) {
      // A queue that cannot be opened is reported, not hidden: the counts on
      // screen would otherwise silently stop describing anything.
      setFailure(error instanceof Error ? error.message : "the held notes could not be read");
    }
  }, [principalId]);

  useEffect(() => {
    void drain();
    const onOnline = () => void drain();
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [drain]);

  if (failure) {
    return (
      <p role="alert" data-testid="offline-queue-failure" className="text-sm text-moss-coral">
        Held notes could not be read on this device: {failure}
      </p>
    );
  }
  if (!counts) return null;
  const held = counts.pending + counts.stalled + counts.quarantined + counts.needsReauth;
  if (held === 0) return null;

  return (
    <div
      role="status"
      data-testid="offline-queue-status"
      className="fixed bottom-2 left-2 z-20 max-w-xs rounded border border-moss-coral bg-white p-2 text-xs shadow"
    >
      <p data-testid="offline-queue-held">
        <strong>{held}</strong> note{held === 1 ? "" : "s"} held on this device only — not saved on
        the server.
      </p>
      {counts.pending > 0 ? (
        <p data-testid="offline-queue-pending">{counts.pending} waiting to be sent.</p>
      ) : null}
      {counts.quarantined > 0 ? (
        <p data-testid="offline-queue-quarantined">
          {counts.quarantined} quarantined: queued by a different account and kept, not sent.
        </p>
      ) : null}
      {counts.needsReauth > 0 ? (
        <p data-testid="offline-queue-needs-reauth">
          {counts.needsReauth} need you to sign in again before they can be sent.
        </p>
      ) : null}
      {counts.stalled > 0 ? (
        <p data-testid="offline-queue-stalled">
          {counts.stalled} stopped retrying after repeated failures and are still held.
        </p>
      ) : null}
    </div>
  );
}
