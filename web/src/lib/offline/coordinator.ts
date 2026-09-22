/**
 * Origin-wide serialization for the capture queue.
 *
 * Two tabs of this application share one IndexedDB and one queue. Without a
 * lock they can both read the same pending entry, both decrypt it, and both POST
 * it; the backend's `UNIQUE (principal_id, idempotency_key)` still collapses
 * that into one capture, but the *local* half — two racing verify-then-delete
 * transactions over the same payload — is this tier's to get right.
 *
 * So every mutating queue path runs inside one exclusive origin-wide Web Lock.
 *
 * **It fails closed, in both directions.** `ifAvailable: true` means a lock this
 * process cannot have right now yields `null` rather than a wait, and that is a
 * typed `busy` — no counter advances, no transaction opens, no request is sent.
 * An environment with no Web Locks API at all is `locks_unavailable`, which is
 * also a refusal: falling back to a per-tab flag would claim a serialization
 * this origin does not have, and inventing a lease record in IndexedDB would be
 * a second lock with none of the browser's release-on-crash semantics.
 *
 * **The callback's lifetime owns the lock.** It is released when the callback
 * settles, which is why the caller runs exactly one bounded attempt per
 * acquisition and re-acquires for the next row rather than holding the lock
 * across a whole drain.
 *
 * **What this does not claim.** An already-open older version of this
 * application does not know about this lock and does not honour it. Canonical
 * backend idempotency remains the final duplicate-prevention authority across
 * processes and across mixed-version clients; this is conservative local
 * serialization of a small queue, not a general scheduler and not a distributed
 * lock.
 */

/** The one lock name this origin uses for the capture queue. */
export const CAPTURE_QUEUE_LOCK_NAME = "mypa-offline-capture";

/** Why the queue could not be entered. Closed, and content-free. */
export type CaptureQueueUnavailableReason = "busy" | "locks_unavailable";

/**
 * Raised when the queue lock could not be taken.
 *
 * Distinct from every protocol error because the correct response is different:
 * nothing was attempted, nothing was written, and the caller's bytes and draft
 * are exactly as they were.
 */
export class CaptureQueueUnavailableError extends Error {
  readonly reason: CaptureQueueUnavailableReason;

  constructor(reason: CaptureQueueUnavailableReason) {
    super(reason);
    this.name = "CaptureQueueUnavailableError";
    this.reason = reason;
  }
}

type LockManagerLike = {
  request(
    name: string,
    options: { mode: "exclusive"; ifAvailable: true },
    callback: (lock: unknown) => Promise<unknown>,
  ): Promise<unknown>;
};

function lockManager(): LockManagerLike | null {
  const candidate = (globalThis as { navigator?: { locks?: unknown } }).navigator?.locks;
  if (
    typeof candidate !== "object" ||
    candidate === null ||
    typeof (candidate as { request?: unknown }).request !== "function"
  ) {
    return null;
  }
  return candidate as LockManagerLike;
}

/** Whether this environment can serialize the queue at all. */
export function captureQueueLockSupported(): boolean {
  return lockManager() !== null;
}

const NOT_ACQUIRED = Symbol("capture-queue-lock-not-acquired");

/**
 * Run `operation` while holding the exclusive capture-queue lock.
 *
 * `operation` runs at most once, and only with the lock held. When the lock is
 * held elsewhere the callback is **not invoked at all** — this is the difference
 * between "somebody else is draining" and "the drain found nothing", and a
 * caller that cannot tell them apart would report an empty queue that is not
 * empty.
 *
 * No `steal`, and no `signal`: stealing would run two owners at once, which is
 * the whole thing being prevented, and an abort signal would drop the lock while
 * the callback's own transaction was still live.
 */
export async function withCaptureQueueLock<T>(operation: () => Promise<T>): Promise<T> {
  const locks = lockManager();
  if (locks === null) throw new CaptureQueueUnavailableError("locks_unavailable");

  const outcome = await locks.request(
    CAPTURE_QUEUE_LOCK_NAME,
    { mode: "exclusive", ifAvailable: true },
    async (lock: unknown) => {
      if (lock === null || lock === undefined) return NOT_ACQUIRED;
      return { value: await operation() };
    },
  );

  if (outcome === NOT_ACQUIRED) throw new CaptureQueueUnavailableError("busy");
  return (outcome as { value: T }).value;
}
