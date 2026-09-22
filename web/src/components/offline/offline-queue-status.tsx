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
 * counted, so nobody has to guess whether they still exist. They can be
 * released or deleted only through the owning Principal's explicit controls.
 *
 * The component renders nothing at all when the queue is empty, which is the
 * ordinary case; a persistent zero-state badge would be chrome for a condition
 * that does not exist.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteHeldCapture,
  drainCaptureQueue,
  heldCaptures,
  heldCaptureCounts,
  releaseHeldCapture,
} from "@/lib/offline/capture-queue";
import { CAPTURE_QUEUE_CHANGED_EVENT, type OfflineEntry, type QueueCounts } from "@/lib/offline/queue";

export function OfflineQueueStatus({ principalId }: { principalId: string }) {
  const [counts, setCounts] = useState<QueueCounts | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [entries, setEntries] = useState<readonly OfflineEntry[]>([]);

  /**
   * The generation this component is currently rendering for.
   *
   * Every asynchronous read captures the value at its start and discards its own
   * result if the counter has moved on. A drain begun under Principal A can
   * otherwise resolve after a sign-out or an account switch and publish A's
   * counts into B's session — the one outcome a held-note indicator must never
   * produce, because the number it shows is a claim about whose notes exist on
   * this device.
   */
  const generation = useRef(0);
  /**
   * Ordering within one generation.
   *
   * The epoch guard stops a previous Principal's read from landing. This stops a
   * *slower earlier* read of the same Principal from landing on top of a faster
   * later one — a drain that started first but finished second would otherwise
   * restore counts the refresh had already superseded.
   */
  const issued = useRef(0);
  const applied = useRef(0);
  const [renderedPrincipal, setRenderedPrincipal] = useState(principalId);
  if (renderedPrincipal !== principalId) {
    // State is adjusted during render, so nothing is ever painted describing the
    // previous Principal's device under the new one. The generation counter is
    // bumped in the effect below, because a ref may not be written during render.
    setRenderedPrincipal(principalId);
    setCounts(null);
    setEntries([]);
    setFailure(null);
  }

  useEffect(() => {
    // Invalidates every read already in flight: when one resolves it finds the
    // generation moved and discards its own result rather than publishing it.
    generation.current += 1;
    applied.current = issued.current;
  }, [principalId]);

  /** Counts only. Opens the database; never mints a key and never replays. */
  const refresh = useCallback(async () => {
    const epoch = generation.current;
    const ticket = (issued.current += 1);
    try {
      const [nextCounts, nextEntries] = await Promise.all([
        heldCaptureCounts(),
        heldCaptures(principalId),
      ]);
      if (epoch !== generation.current || ticket < applied.current) return;
      applied.current = ticket;
      setCounts(nextCounts);
      setEntries(nextEntries);
      setFailure(null);
    } catch (error) {
      if (epoch !== generation.current || ticket < applied.current) return;
      applied.current = ticket;
      setFailure(error instanceof Error ? error.message : "the held notes could not be read");
    }
  }, [principalId]);

  const drain = useCallback(async () => {
    const epoch = generation.current;
    const ticket = (issued.current += 1);
    try {
      const result = await drainCaptureQueue(principalId);
      const nextEntries = await heldCaptures(principalId);
      if (epoch !== generation.current || ticket < applied.current) return;
      applied.current = ticket;
      setCounts(result.counts);
      setEntries(nextEntries);
      setFailure(null);
    } catch (error) {
      // A queue that cannot be opened is reported, not hidden: the counts on
      // screen would otherwise silently stop describing anything.
      if (epoch !== generation.current || ticket < applied.current) return;
      applied.current = ticket;
      setFailure(error instanceof Error ? error.message : "the held notes could not be read");
    }
  }, [principalId]);

  const release = useCallback(
    async (entryId: string) => {
      try {
        await releaseHeldCapture(principalId, entryId);
        await drain();
      } catch (error) {
        setFailure(error instanceof Error ? error.message : "the note could not be released");
      }
    },
    [drain, principalId],
  );

  const remove = useCallback(
    async (entryId: string) => {
      try {
        await deleteHeldCapture(principalId, entryId);
        await refresh();
      } catch (error) {
        setFailure(error instanceof Error ? error.message : "the note could not be deleted");
      }
    },
    [refresh, principalId],
  );

  useEffect(() => {
    const initialDrain = window.setTimeout(() => void drain(), 0);
    const onOnline = () => void drain();
    const onFocus = () => void refresh();
    // A committed mutation anywhere in this tab refreshes the counts. It does
    // not start another replay: a change event is not a reason to send.
    const onQueueChanged = () => void refresh();
    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onFocus);
    window.addEventListener(CAPTURE_QUEUE_CHANGED_EVENT, onQueueChanged);
    return () => {
      window.clearTimeout(initialDrain);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener(CAPTURE_QUEUE_CHANGED_EVENT, onQueueChanged);
    };
  }, [drain, refresh]);

  if (failure) {
    return (
      <p role="alert" data-testid="offline-queue-failure" className="text-sm text-moss-coral-strong">
        Held notes could not be read on this device.
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
      /*
       * `fixed`, flush to the bottom and left viewport edges: under
       * `viewport-fit=cover` 8px puts this inside the ~34px home indicator, and
       * inside the ~44px landscape left inset. This is the one element whose
       * whole job is telling the reader their captured work is held on this
       * device and not saved, so it is the last thing that may be clipped.
       */
      className="fixed bottom-[max(0.5rem,env(safe-area-inset-bottom))] left-[max(0.5rem,env(safe-area-inset-left))] z-20 max-w-xs rounded border border-moss-coral bg-surface p-2 text-xs shadow"
    >
      <p data-testid="offline-queue-held">
        <strong>{held}</strong> note{held === 1 ? "" : "s"} held on this device only — not saved on
        the server.
      </p>
      <p data-testid="offline-queue-ambiguity">
        A held note is kept until the server confirms it. If a send was interrupted, whether it
        reached the server is unknown until the next attempt confirms it.
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
      {entries.map((entry) => (
        <div key={entry.entryId} data-testid={`offline-entry-${entry.entryId}`}>
          <span>{entry.captureKind} queued {new Date(entry.queuedAt).toLocaleString()}</span>
          {entry.state === "quarantined" ? (
            <button type="button" onClick={() => void release(entry.entryId)}>
              Release and retry
            </button>
          ) : null}
          <button type="button" onClick={() => void remove(entry.entryId)}>
            Delete local copy
          </button>
        </div>
      ))}
    </div>
  );
}
