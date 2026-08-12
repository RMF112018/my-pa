/**
 * Replaying held notes to the server, and the receipt that has to come back
 * before anything local is deleted.
 *
 * **Foreground only.** Replay runs when the capture surface mounts and when the
 * browser fires `online`. Background Sync is not used and **no background-sync
 * guarantee is claimed**: a note queued in a tab that is then closed stays
 * queued until the app is opened again.
 *
 * **The authenticated Principal check precedes plaintext access.** Replay asks
 * the server which Principal the current HttpOnly session authenticates, then
 * compares that answer with the immutable queue owner before calling the only
 * function that decrypts. A stale rendered Principal therefore has no authority.
 *
 * **A local payload is deleted only for a receipt that has been checked, not for
 * an HTTP 200.** `verifyReceipt` requires all five of:
 *
 * 1. `shape === "backend"` — the synthetic provider's answer is a different
 *    shape and must never earn a deletion;
 * 2. `status === "persisted"` — `acknowledged_not_persisted` is exactly the
 *    state in which the note is *not* stored, so it deletes nothing;
 * 3. a non-empty `receipt.receiptId`, and `receipt.idempotencyKey` equal to the
 *    key this entry was minted with — a receipt for someone else's submission is
 *    not this entry's receipt;
 * 4. `receipt.contentSha256` equal to a SHA-256 this tier computes locally over
 *    the exact bytes the backend hashes.
 * 5. `receipt.principalId` equal to the queue owner and the Principal established
 *    by replay-time session introspection.
 *
 * The fourth is checkable here because the backend's digest is reproducible from
 * the web tier: `my_pa.domain.capture.version.digest_of` is
 * `hashlib.sha256(text.encode("utf-8")).hexdigest()` over the capture text **as
 * stored**, with no normalisation, and `POST /api/capture` sends `text.trim()`
 * and the Python side stores that string verbatim. So the digest over the same
 * trimmed string is the digest the receipt must carry.
 *
 * Anything else — a transport failure, a malformed body, a partially shaped
 * receipt, a mismatched digest — leaves the ciphertext exactly where it was.
 *
 * **The idempotency key is never regenerated.** It is minted once at enqueue and
 * replayed verbatim, so a second replay of the same entry meets the backend's
 * `UNIQUE (principal_id, idempotency_key)` and returns the original receipt with
 * `created: false`. That is a success and it deletes the local payload: the note
 * is stored, and storing it twice is what the key exists to prevent.
 */
import {
  deleteReplayed,
  markNeedsReauth,
  markReplayFailed,
  quarantineEntry,
  queueSnapshot,
  readPayloadText,
  replayable,
  retains,
  type OfflineEntry,
} from "@/lib/offline/queue";

/** What a transport hands back. Deliberately the raw status and body. */
export interface ReplayResponse {
  readonly status: number;
  readonly body: unknown;
}

/** How a replay reaches the server. Injected so the verification can be tested. */
export type ReplayTransport = (request: {
  readonly text: string;
  readonly captureKind: string;
  readonly idempotencyKey: string;
  readonly replayBinding: string;
}) => Promise<ReplayResponse>;

export interface AuthenticatedReplaySession {
  readonly principalId: string;
  readonly replayBinding: string;
}

export type ReplaySessionResolver = () => Promise<AuthenticatedReplaySession | null>;

/** Why a receipt was not accepted. Each value names one failed check. */
export type ReceiptRejection =
  | "not_an_object"
  | "not_backend_shape"
  | "not_persisted"
  | "missing_receipt_id"
  | "idempotency_key_mismatch"
  | "digest_mismatch"
  | "principal_mismatch";

export type ReceiptVerdict =
  | { readonly ok: true; readonly receiptId: string; readonly created: boolean }
  | { readonly ok: false; readonly reason: ReceiptRejection };

/** SHA-256 of the UTF-8 bytes of `text`, lowercase hex — the backend's `digest_of`. */
export async function contentSha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text) as BufferSource,
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Whether this response is a receipt for this entry's submission.
 *
 * Every check is positive. A body whose shape this function does not recognise
 * falls through to a rejection rather than to acceptance, because the failure
 * directions are not symmetric: a rejected good receipt costs one replayed
 * submission that the idempotency key collapses, and an accepted bad one deletes
 * the only copy of somebody's note.
 */
export function verifyReceipt(
  body: unknown,
  expected: {
    readonly idempotencyKey: string;
    readonly contentSha256: string;
    readonly principalId: string;
  },
): ReceiptVerdict {
  if (typeof body !== "object" || body === null) return { ok: false, reason: "not_an_object" };
  const envelope = body as {
    shape?: unknown;
    status?: unknown;
    created?: unknown;
    receipt?: {
      receiptId?: unknown;
      idempotencyKey?: unknown;
      contentSha256?: unknown;
      principalId?: unknown;
    };
  };
  if (envelope.shape !== "backend") return { ok: false, reason: "not_backend_shape" };
  if (envelope.status !== "persisted") return { ok: false, reason: "not_persisted" };
  const receipt = envelope.receipt;
  if (typeof receipt !== "object" || receipt === null) {
    return { ok: false, reason: "missing_receipt_id" };
  }
  const receiptId = receipt.receiptId;
  if (typeof receiptId !== "string" || receiptId.trim().length === 0) {
    return { ok: false, reason: "missing_receipt_id" };
  }
  if (receipt.idempotencyKey !== expected.idempotencyKey) {
    return { ok: false, reason: "idempotency_key_mismatch" };
  }
  if (receipt.contentSha256 !== expected.contentSha256) {
    return { ok: false, reason: "digest_mismatch" };
  }
  if (receipt.principalId !== expected.principalId) {
    return { ok: false, reason: "principal_mismatch" };
  }
  return { ok: true, receiptId, created: envelope.created !== false };
}

/** What one replay pass did. Counts, never content. */
export interface ReplaySummary {
  readonly attempted: number;
  readonly replayed: number;
  readonly quarantined: number;
  readonly needsReauth: number;
  readonly failed: number;
  readonly stoppedForReauth: boolean;
}

/** Statuses that mean "this session is not usable", and end the pass. */
function isStaleSession(response: ReplayResponse): boolean {
  return response.status === 401 || response.status === 403;
}

/**
 * Replay everything queued under `currentPrincipalId` after independently
 * resolving the current authenticated session.
 *
 * `key` is that principal's content key. It is only ever used on entries whose
 * stored `principalId` equals `currentPrincipalId`, so it is never asked to
 * decrypt bytes it did not seal.
 *
 * `currentPrincipalId` remains the rendered identity used to select the local
 * key. It is not authentication authority. `resolveSession` obtains that
 * authority immediately before the pass, and its opaque binding is carried to
 * the write so the BFF can reject a cookie change between check and admission.
 */
export async function replayQueuedCaptures(
  db: IDBDatabase,
  currentPrincipalId: string,
  key: CryptoKey,
  transport: ReplayTransport,
  resolveSession: ReplaySessionResolver,
): Promise<ReplaySummary> {
  let authenticated: AuthenticatedReplaySession | null = null;
  try {
    authenticated = await resolveSession();
  } catch {
    authenticated = null;
  }
  const entries = await queueSnapshot(db);
  let attempted = 0;
  let replayed = 0;
  let quarantined = 0;
  let needsReauth = 0;
  let failed = 0;
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

    // This is the authoritative replay-time identity check. It occurs before
    // `replayOne`, which is the only function that reads/decrypts payload bytes.
    if (authenticated === null || entry.principalId !== authenticated.principalId) {
      await markNeedsReauth(db, entry.entryId, "current authenticated principal does not own entry");
      needsReauth += 1;
      stoppedForReauth = true;
      break;
    }

    attempted += 1;
    const outcome = await replayOne(db, key, entry, transport, authenticated);
    if (outcome === "replayed") replayed += 1;
    else if (outcome === "needs_reauth") {
      needsReauth += 1;
      // Stop the pass. Continuing would send every remaining note into the same
      // refusal and turn one stale session into a queue of failures.
      stoppedForReauth = true;
    } else failed += 1;
  }

  return { attempted, replayed, quarantined, needsReauth, failed, stoppedForReauth };
}

async function replayOne(
  db: IDBDatabase,
  key: CryptoKey,
  entry: OfflineEntry,
  transport: ReplayTransport,
  authenticated: AuthenticatedReplaySession,
): Promise<"replayed" | "needs_reauth" | "failed"> {
  let text: string | null;
  try {
    text = await readPayloadText(db, key, entry.entryId);
  } catch {
    // A payload that will not decrypt is not evidence that it should be thrown
    // away. It is recorded and kept.
    await markReplayFailed(db, entry.entryId, "payload_undecryptable");
    return "failed";
  }
  if (text === null) {
    await markReplayFailed(db, entry.entryId, "payload_missing");
    return "failed";
  }

  let response: ReplayResponse;
  try {
    response = await transport({
      text,
      captureKind: entry.captureKind,
      idempotencyKey: entry.idempotencyKey,
      replayBinding: authenticated.replayBinding,
    });
  } catch {
    await markReplayFailed(db, entry.entryId, "transport_failed");
    return "failed";
  }

  if (isStaleSession(response)) {
    await markNeedsReauth(db, entry.entryId, `session refused with ${response.status}`);
    return "needs_reauth";
  }
  if (response.status < 200 || response.status >= 300) {
    await markReplayFailed(db, entry.entryId, `http_${response.status}`);
    return "failed";
  }

  const verdict = verifyReceipt(response.body, {
    idempotencyKey: entry.idempotencyKey,
    contentSha256: await contentSha256(text),
    principalId: authenticated.principalId,
  });
  if (!verdict.ok) {
    await markReplayFailed(db, entry.entryId, verdict.reason);
    return "failed";
  }

  await deleteReplayed(db, entry.entryId, verdict.receiptId);
  return "replayed";
}
