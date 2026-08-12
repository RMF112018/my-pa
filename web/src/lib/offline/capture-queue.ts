/**
 * The three-step composition both offline surfaces need, in one place.
 *
 * The capture dialog queues; the offline indicator quarantines, replays, and
 * reports counts. Both have to open the database, resolve the signed-in
 * principal's content key, and fail closed if either refuses, and writing that
 * sequence twice is how the two would eventually disagree about which principal
 * a key belongs to. This is composition, not an abstraction over the queue —
 * every function below is a call into `queue.ts` and `replay.ts` with the same
 * arguments a caller would have passed.
 *
 * **The transport is `POST /api/capture`, the same route the online path uses.**
 * A replay is an ordinary capture submission carrying the idempotency key the
 * entry was minted with, so the backend's `UNIQUE (principal_id,
 * idempotency_key)` is what makes a duplicate replay one capture rather than
 * anything in this file.
 */
import { openOfflineDatabase } from "@/lib/offline/db";
import { principalContentKey } from "@/lib/offline/key";
import {
  countStates,
  enqueueCapture,
  deleteHeldByUser,
  releaseQuarantined,
  quarantineForeignEntries,
  queueSnapshot,
  type OfflineEntry,
  type QueueCounts,
} from "@/lib/offline/queue";
import { replayQueuedCaptures, type ReplaySummary, type ReplayTransport } from "@/lib/offline/replay";

/** Open the database and the signed-in principal's key, or throw. */
async function open(principalId: string) {
  const db = await openOfflineDatabase();
  return { db, key: await principalContentKey(db, principalId) };
}

export async function heldCaptures(principalId: string): Promise<readonly OfflineEntry[]> {
  const { db } = await open(principalId);
  return (await queueSnapshot(db)).filter(
    (entry) => entry.principalId === principalId && entry.state !== "replayed" && entry.state !== "deleted",
  );
}

export async function releaseHeldCapture(principalId: string, entryId: string): Promise<void> {
  const { db } = await open(principalId);
  await releaseQuarantined(db, entryId, principalId);
}

export async function deleteHeldCapture(principalId: string, entryId: string): Promise<void> {
  const { db } = await open(principalId);
  await deleteHeldByUser(db, entryId, principalId);
}

/**
 * Hold one note on this device, encrypted under the signed-in principal's key.
 *
 * Every failure — no IndexedDB, no storable non-extractable key, the queue at
 * its bound — propagates. The caller's contract is to keep the note in the field
 * and say so; there is no path here that reports a hold it did not perform.
 */
export async function queueCaptureOffline(input: {
  readonly principalId: string;
  readonly text: string;
  readonly captureKind: string;
  readonly idempotencyKey: string;
}): Promise<OfflineEntry> {
  const { db, key } = await open(input.principalId);
  return enqueueCapture(db, key, input);
}

/** The live transport: the same route the online capture path posts to. */
export const httpCaptureTransport: ReplayTransport = async (request) => {
  const response = await fetch("/api/capture", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      text: request.text,
      captureKind: request.captureKind,
      idempotencyKey: request.idempotencyKey,
    }),
    credentials: "same-origin",
  });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
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
  const { db, key } = await open(principalId);
  await quarantineForeignEntries(db, principalId);
  const summary = await replayQueuedCaptures(db, principalId, key, transport);
  return { summary, counts: countStates(await queueSnapshot(db)) };
}
