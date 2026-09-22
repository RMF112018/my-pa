/**
 * The composition both offline surfaces need, in one place.
 *
 * The capture dialog queues; the offline indicator quarantines, replays, and
 * reports counts. This is composition, not an abstraction over the queue — every
 * function below is a call into `queue.ts` and `replay.ts` with the same
 * arguments a caller would have passed.
 *
 * **Reading never mints a key.** The old `open()` resolved a content key on
 * every path, including the ones that only counted rows. That meant looking at
 * the offline indicator on a fresh profile *created* a key, and — worse — a
 * profile whose key store had been cleared while payloads survived would get a
 * brand-new key that could never open them. Status and held-note reads now open
 * only the database; replay loads an existing key and never generates; and only
 * an explicit enqueue may create a first key, under the queue lock.
 *
 * **Every mutation runs under the origin-wide queue lock.** Enqueue, release and
 * explicit user deletion all serialize through `withCaptureQueueLock`; replay
 * takes the same lock per row, inside `replayQueuedCaptures`. The functions in
 * `queue.ts` stay lock-free transaction helpers so no path acquires the lock
 * twice.
 *
 * **The transport is `POST /api/capture`, the same route the online path uses.**
 * A replay is an ordinary capture submission carrying the idempotency key the
 * entry was minted with and the Project it was frozen with, so the backend's
 * `UNIQUE (principal_id, idempotency_key)` is what makes a duplicate replay one
 * capture rather than anything in this file.
 */
import { openOfflineDatabase } from "@/lib/offline/db";
import { withCaptureQueueLock } from "@/lib/offline/coordinator";
import { getOrCreatePrincipalKey } from "@/lib/offline/key";
import {
  CAPTURE_QUEUE_CHANGED_EVENT,
  countStates,
  enqueueCapture,
  deleteHeldByUser,
  releaseQuarantined,
  quarantineForeignEntries,
  queueSnapshot,
  type CaptureQueueIntent,
  type OfflineEntry,
  type QueueCounts,
} from "@/lib/offline/queue";
import { replayQueuedCaptures, type ReplaySummary, type ReplayTransport } from "@/lib/offline/replay";

/** Re-exported so the facade's consumers need not reach past it for the name. */
export { CAPTURE_QUEUE_CHANGED_EVENT };

function announceQueueChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(CAPTURE_QUEUE_CHANGED_EVENT));
}

/**
 * The current authenticated session, as the server reports it.
 *
 * Exported so replay and any other caller use one reader. The binding is a
 * deterministic one-way digest of the session cookie's SID — it is a comparison
 * value, not a credential, it is never stored in IndexedDB and it is never
 * emitted in diagnostics.
 */
export async function authenticatedReplaySession() {
  const response = await fetch("/api/session", { credentials: "same-origin", cache: "no-store" });
  if (!response.ok) return null;
  const body = (await response.json()) as { principalId?: unknown; replayBinding?: unknown };
  return typeof body.principalId === "string" &&
    body.principalId.length > 0 &&
    typeof body.replayBinding === "string" &&
    /^[0-9a-f]{64}$/.test(body.replayBinding)
    ? { principalId: body.principalId, replayBinding: body.replayBinding }
    : null;
}

/** Open the database. No key: a read has no business creating one. */
async function openDatabase(): Promise<IDBDatabase> {
  return openOfflineDatabase();
}

export async function heldCaptures(principalId: string): Promise<readonly OfflineEntry[]> {
  const db = await openDatabase();
  return (await queueSnapshot(db)).filter(
    (entry) =>
      entry.principalId === principalId &&
      entry.state !== "replayed" &&
      entry.state !== "deleted",
  );
}

/** The held counts for this device. Opens the database and nothing else. */
export async function heldCaptureCounts(): Promise<QueueCounts> {
  const db = await openDatabase();
  return countStates(await queueSnapshot(db));
}

export async function releaseHeldCapture(principalId: string, entryId: string): Promise<void> {
  const db = await openDatabase();
  await withCaptureQueueLock(() => releaseQuarantined(db, entryId, principalId));
  announceQueueChanged();
}

export async function deleteHeldCapture(principalId: string, entryId: string): Promise<void> {
  const db = await openDatabase();
  await withCaptureQueueLock(() => deleteHeldByUser(db, entryId, principalId));
  announceQueueChanged();
}

/**
 * Hold one note on this device, encrypted under the signed-in principal's key.
 *
 * This is the one path that may create a first key, and it does so under the
 * lock so two tabs initializing at once produce one key rather than a race in
 * which the second overwrites the first.
 *
 * Every failure — no IndexedDB, no storable non-extractable key, retained bytes
 * whose key is gone, the queue at its bound, the lock held elsewhere —
 * propagates. The caller's contract is to keep the note in the field and say so;
 * there is no path here that reports a hold it did not perform.
 */
export async function queueCaptureOffline(input: CaptureQueueIntent): Promise<OfflineEntry> {
  const db = await openDatabase();
  const entry = await withCaptureQueueLock(async () => {
    const key = await getOrCreatePrincipalKey(db, input.principalId);
    return enqueueCapture(db, key, input);
  });
  announceQueueChanged();
  return entry;
}

/** The live transport: the same route the online capture path posts to. */
export const httpCaptureTransport: ReplayTransport = async (request) => {
  const response = await fetch("/api/capture", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-my-pa-replay-binding": request.replayBinding,
    },
    body: JSON.stringify({
      text: request.text,
      captureKind: request.captureKind,
      idempotencyKey: request.idempotencyKey,
      // The frozen Project, sent explicitly. `null` is the No Project the note
      // was queued with, not an omission.
      projectId: request.projectId,
    }),
    credentials: "same-origin",
    signal: request.signal,
  });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  // Raw status and body: the shared verifier decides what this means.
  return { status: response.status, body };
};

export interface DrainResult {
  readonly summary: ReplaySummary;
  readonly counts: QueueCounts;
}

/**
 * Quarantine anything a different principal queued, then replay what this one
 * did, then report what is still held.
 *
 * The quarantine runs first and unconditionally, so the counts a person is shown
 * describe the state after the account-switch rule has been applied rather than
 * before it.
 */
export async function drainCaptureQueue(
  principalId: string,
  transport: ReplayTransport = httpCaptureTransport,
): Promise<DrainResult> {
  const db = await openDatabase();
  await quarantineForeignEntries(db, principalId);
  const summary = await replayQueuedCaptures(
    db,
    principalId,
    transport,
    authenticatedReplaySession,
  );
  const counts = countStates(await queueSnapshot(db));
  if (summary.replayed > 0 || summary.quarantined > 0 || summary.failed > 0) {
    announceQueueChanged();
  }
  return { summary, counts };
}
