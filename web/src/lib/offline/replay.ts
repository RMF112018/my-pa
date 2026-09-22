/**
 * Replaying held notes to the server, and the receipt that has to come back
 * before anything local is deleted.
 *
 * **Foreground only.** Replay runs when the capture surface mounts and when the
 * browser fires `online`. Background Sync is not used and **no background-sync
 * guarantee is claimed**: a note queued in a tab that is then closed stays
 * queued until the app is opened again.
 *
 * **There is one receipt verifier and it does not live here.** This module used
 * to carry its own, checking five fields. It now imports
 * `verifyCaptureReceipt` from `lib/capture/receipt.ts` — the same function the
 * online BFF path uses — because two verifiers for one receipt is two answers to
 * "was this stored", and the weaker one decides what gets deleted. The shared
 * verifier validates the **whole** canonical acknowledgement and compares
 * Principal, idempotency key, kind, content digest and **Project including
 * null** against the frozen intent.
 *
 * **The session is re-resolved at every boundary that matters**: before the
 * payload is decrypted, immediately before the POST, and again before the
 * deletion. Both the Principal and the opaque replay binding must be unchanged
 * for that attempt. A same-Principal cookie transition still blocks the
 * deletion, because the proof that authorized the write was obtained under a
 * session that no longer exists.
 *
 * **Deletion is the narrowest operation in this file.** It requires a complete
 * verified receipt *and* a final transactional comparison against the exact
 * bytes the attempt worked from. HTTP 2xx alone, a synthetic acknowledgement, an
 * echoed Project, a missing field, the wrong Project or a null mismatch all
 * leave the ciphertext exactly where it was.
 *
 * **The Project is the frozen one.** It comes out of the authenticated payload
 * and is sent verbatim. Current global Project Scope is never consulted: the
 * note was filed against a Project when it was written, and replaying it
 * somewhere else because the user has since changed context would be the same
 * defect as rebinding it to a different Principal.
 *
 * **The idempotency key is never regenerated.** It is minted once at enqueue and
 * replayed verbatim, so a second replay meets the backend's `UNIQUE
 * (principal_id, idempotency_key)` and returns the original receipt with
 * `created: false`. That is a success and it deletes the local payload: the note
 * is stored, and storing it twice is what the key exists to prevent.
 */
import {
  contentSha256 as sharedContentSha256,
  verifyCaptureReceipt,
} from "@/lib/capture/receipt";
import type { CaptureKind, FrozenCaptureIntent } from "@/lib/capture/contract";
import {
  CaptureQueueProtocolError,
  type CaptureQueueProtocolReason,
} from "@/lib/offline/capture-intent-codec";
import { CaptureQueueUnavailableError, withCaptureQueueLock } from "@/lib/offline/coordinator";
import { CaptureKeyUnavailableError, loadPrincipalKey } from "@/lib/offline/key";
import {
  deleteReplayed,
  markNeedsReauth,
  markReplayFailed,
  quarantineEntry,
  queueSnapshot,
  readCaptureIntent,
  readPayloadRecord,
  replayable,
  retains,
  snapshotRetainedPayload,
  type OfflineEntry,
} from "@/lib/offline/queue";

/** How long one replay attempt may take before it is abandoned as ambiguous. */
export const REPLAY_ATTEMPT_TIMEOUT_MS = 15_000;

/** What a transport hands back. Deliberately the raw status and body. */
export interface ReplayResponse {
  readonly status: number;
  readonly body: unknown;
}

/** How a replay reaches the server. Injected so the verification can be tested. */
export type ReplayTransport = (request: {
  readonly text: string;
  readonly captureKind: CaptureKind;
  readonly idempotencyKey: string;
  readonly projectId: string | null;
  readonly replayBinding: string;
  readonly signal: AbortSignal;
}) => Promise<ReplayResponse>;

export interface AuthenticatedReplaySession {
  readonly principalId: string;
  readonly replayBinding: string;
}

export type ReplaySessionResolver = () => Promise<AuthenticatedReplaySession | null>;

/**
 * SHA-256 of the UTF-8 bytes of `text`, lowercase hex — the backend's `digest_of`.
 *
 * Re-exported rather than reimplemented: existing callers keep their import and
 * there is still exactly one hashing implementation in the tree.
 */
export const contentSha256 = sharedContentSha256;

/** What one replay pass did. Counts, never content. */
export interface ReplaySummary {
  readonly attempted: number;
  readonly replayed: number;
  readonly quarantined: number;
  readonly needsReauth: number;
  readonly failed: number;
  readonly stoppedForReauth: boolean;
  /** Rows the queue lock or a missing key prevented this pass from attempting. */
  readonly blocked: number;
}

/** Statuses that mean "this session is not usable", and end the pass. */
function isStaleSession(response: ReplayResponse): boolean {
  if (response.status === 401 || response.status === 403) return true;
  if (response.status !== 409 || typeof response.body !== "object" || response.body === null) {
    return false;
  }
  const body = response.body as { error?: { code?: unknown } };
  return body.error?.code === "replay_session_changed";
}

function sameSession(
  left: AuthenticatedReplaySession,
  right: AuthenticatedReplaySession | null,
): right is AuthenticatedReplaySession {
  return (
    right !== null &&
    right.principalId === left.principalId &&
    right.replayBinding === left.replayBinding
  );
}

async function resolveQuietly(
  resolveSession: ReplaySessionResolver,
): Promise<AuthenticatedReplaySession | null> {
  try {
    return await resolveSession();
  } catch {
    return null;
  }
}

/** The protocol reason a thrown queue error carries, or a bounded fallback. */
function protocolReason(error: unknown): CaptureQueueProtocolReason {
  if (error instanceof CaptureQueueProtocolError) return error.reason;
  if (error instanceof CaptureKeyUnavailableError) return "key_unavailable";
  return "malformed_intent";
}

/**
 * Replay everything queued under `currentPrincipalId`.
 *
 * `currentPrincipalId` is the rendered identity used to select the local key. It
 * is not authentication authority: `resolveSession` obtains that immediately
 * before every entry, and again before the write and the deletion.
 *
 * Each row is attempted while holding the origin-wide queue lock, which is taken
 * and released per row rather than once per pass — one bounded network attempt
 * per acquisition, so a second tab is never locked out for a whole drain and a
 * stalled attempt never holds the queue.
 */
export async function replayQueuedCaptures(
  db: IDBDatabase,
  currentPrincipalId: string,
  transport: ReplayTransport,
  resolveSession: ReplaySessionResolver,
): Promise<ReplaySummary> {
  const entries = await queueSnapshot(db);
  let attempted = 0;
  let replayed = 0;
  let quarantined = 0;
  let needsReauth = 0;
  let failed = 0;
  let blocked = 0;
  let stoppedForReauth = false;

  for (const entry of entries) {
    if (!retains(entry)) continue;

    // The Principal check precedes everything, including the decryption. A
    // foreign entry is quarantined without its bytes being read.
    if (entry.principalId !== currentPrincipalId) {
      if (entry.state !== "quarantined") {
        await quarantineEntry(
          db,
          entry.entryId,
          "queued by a different principal than the one now signed in",
        );
        quarantined += 1;
      }
      continue;
    }

    if (!replayable(entry)) continue;
    if (stoppedForReauth) break;

    let result: ReplayRowResult;
    try {
      result = await withCaptureQueueLock(() =>
        replayOne(db, currentPrincipalId, entry, transport, resolveSession),
      );
    } catch (error) {
      // No lock is no attempt. Nothing was decrypted, nothing was sent, no
      // replay attempt is consumed, and the bytes are untouched.
      if (error instanceof CaptureQueueUnavailableError) {
        blocked += 1;
        continue;
      }
      throw error;
    }

    if (result.outcome === "blocked") {
      blocked += 1;
      continue;
    }
    if (result.attempted) attempted += 1;
    const outcome = result.outcome;
    if (outcome === "replayed") replayed += 1;
    else if (outcome === "needs_reauth") {
      needsReauth += 1;
      // Stop the pass. Continuing would send every remaining note into the same
      // refusal and turn one stale session into a queue of failures.
      stoppedForReauth = true;
    } else if (outcome === "failed") failed += 1;
  }

  return { attempted, replayed, quarantined, needsReauth, failed, blocked, stoppedForReauth };
}

type ReplayOutcome = "replayed" | "needs_reauth" | "failed" | "blocked" | "not_attempted";

/**
 * One row's result, and whether it consumed an attempt.
 *
 * The two are not the same question. A missing authority, an unusable key, a
 * lock held elsewhere or a row another tab already finished are all decided
 * *before* anything is sent, and none of them is an attempt: counting them would
 * spend an entry's five-failure budget on conditions that never reached the
 * network. Only a row whose transport actually ran has been attempted.
 */
interface ReplayRowResult {
  readonly outcome: ReplayOutcome;
  readonly attempted: boolean;
}

/**
 * One row, under the lock.
 *
 * Reads the full sequence top to bottom: authority, then key, then bytes, then
 * authority again, then the network, then the receipt, then authority a third
 * time, then the transactional deletion. Every step that fails leaves the
 * ciphertext where it is.
 */
async function replayOne(
  db: IDBDatabase,
  currentPrincipalId: string,
  entry: OfflineEntry,
  transport: ReplayTransport,
  resolveSession: ReplaySessionResolver,
): Promise<ReplayRowResult> {
  // Re-fold under the lock: another tab may have completed or released this row
  // between the snapshot and the acquisition.
  const current = (await queueSnapshot(db)).find(
    (candidate) => candidate.entryId === entry.entryId,
  );
  if (!current || !retains(current) || !replayable(current)) {
    return { outcome: "not_attempted", attempted: false };
  }

  const opening = await resolveQuietly(resolveSession);
  if (opening === null || opening.principalId !== current.principalId) {
    await markNeedsReauth(db, current.entryId, "current authenticated principal does not own entry");
    return { outcome: "needs_reauth", attempted: false };
  }

  // Read-only. Replay never mints a key: a fresh one could not open these bytes,
  // and writing it would destroy the only thing that ever could.
  let key: CryptoKey | null;
  try {
    key = await loadPrincipalKey(db, currentPrincipalId);
  } catch {
    // An unusable stored key is a property of the stored bytes, not of this
    // attempt. It is not an attempt and consumes no replay budget.
    return { outcome: "blocked", attempted: false };
  }
  if (key === null) return { outcome: "blocked", attempted: false };

  const record = await readPayloadRecord(db, current.entryId);
  if (record === null) {
    await markReplayFailed(db, current.entryId, "payload_missing");
    return { outcome: "failed", attempted: true };
  }
  const snapshot = await snapshotRetainedPayload(db, current);
  if (snapshot === null) {
    await markReplayFailed(db, current.entryId, "payload_missing");
    return { outcome: "failed", attempted: true };
  }

  let intent: { text: string; projectId: string | null };
  try {
    intent = await readCaptureIntent(db, key, current, record);
  } catch (error) {
    // Unsupported, unauthenticated or malformed bytes are never POSTed. The
    // owned attempt had begun, so it appends exactly one bounded failure and the
    // bytes are retained; retrying the network would not change what they are.
    await markReplayFailed(db, current.entryId, protocolReason(error));
    return { outcome: "failed", attempted: true };
  }

  // Immediately before the write. The cookie may have changed while the payload
  // was being decrypted, and the binding carried to the BFF must be the current
  // one or the BFF's own replay admission will refuse it.
  const beforeWrite = await resolveQuietly(resolveSession);
  if (!sameSession(opening, beforeWrite)) {
    await markNeedsReauth(db, current.entryId, "session_changed");
    return { outcome: "needs_reauth", attempted: false };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REPLAY_ATTEMPT_TIMEOUT_MS);
  let response: ReplayResponse;
  try {
    response = await transport({
      text: intent.text,
      captureKind: current.captureKind as CaptureKind,
      idempotencyKey: current.idempotencyKey,
      projectId: intent.projectId,
      replayBinding: beforeWrite.replayBinding,
      signal: controller.signal,
    });
  } catch {
    // An abort or a transport failure is ambiguous: the backend may have
    // committed. It is never "not stored" and it never deletes.
    await markReplayFailed(db, current.entryId, "transport_unconfirmed");
    return { outcome: "failed", attempted: true };
  } finally {
    clearTimeout(timeout);
  }

  if (isStaleSession(response)) {
    await markNeedsReauth(db, current.entryId, "session_changed");
    return { outcome: "needs_reauth", attempted: true };
  }
  if (response.status < 200 || response.status >= 300) {
    await markReplayFailed(db, current.entryId, `http_${response.status}`);
    return { outcome: "failed", attempted: true };
  }

  const frozen: FrozenCaptureIntent = {
    principalId: beforeWrite.principalId,
    // In-memory generation counter only; not persisted and not part of identity.
    sessionEpoch: 0,
    captureKind: current.captureKind as CaptureKind,
    text: intent.text,
    idempotencyKey: current.idempotencyKey,
    projectId: intent.projectId,
  };
  const verdict = await verifyCaptureReceipt(response.body, frozen);
  if (!verdict.ok) {
    await markReplayFailed(db, current.entryId, verdict.reason);
    return { outcome: "failed", attempted: true };
  }

  // The third and last session check. An earlier proof cannot authorize a
  // deletion after a logout or a Principal switch.
  const beforeDelete = await resolveQuietly(resolveSession);
  if (!sameSession(opening, beforeDelete)) {
    await markNeedsReauth(db, current.entryId, "session_changed");
    return { outcome: "needs_reauth", attempted: true };
  }

  const deletion = await deleteReplayed(db, snapshot, verdict.ack.receipt.receiptId);
  if (!deletion.ok) {
    // Another actor finished this row, or the record under that key is no longer
    // the one that was verified. Either way the bytes here are not the bytes the
    // receipt covers, so they stay.
    if (deletion.reason === "already_terminal") {
      return { outcome: "not_attempted", attempted: true };
    }
    await markReplayFailed(db, current.entryId, "receipt_invalid");
    return { outcome: "failed", attempted: true };
  }
  return { outcome: "replayed", attempted: true };
}
