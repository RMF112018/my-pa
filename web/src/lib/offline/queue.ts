/**
 * The offline capture queue: append-only, bounded, and bound to one Principal
 * per entry.
 *
 * **An entry is created once and never rewritten.** Its identity, the
 * `principalId` that was authenticated when it was queued, its idempotency key,
 * and its encrypted bytes are written in a single `enqueued` event and no code
 * path anywhere updates them. Everything that happens afterwards — a quarantine,
 * a stale session, a failed replay, the deletion that follows a verified
 * receipt — is an **appended** event, and the state a surface renders is a fold
 * over those events rather than a column somebody wrote. That shape is not
 * decoration: "the queue rebound my note to whoever is signed in now" is exactly
 * the defect this package exists to rule out, and a store with no update
 * statement cannot commit it.
 *
 * **The principal binding is immutable and is checked at replay, not at
 * enqueue.** `replay.ts` resolves the current authenticated session immediately
 * before replay and compares it with the entry owner before decryption. The
 * rendered identity still selects the local key, but is not treated as session
 * authority. A mismatch retains the ciphertext in `needs_reauth`; an entry
 * foreign to the rendered surface is quarantined. Neither path rebinds, deletes,
 * or sends the payload.
 *
 * **Deletion has two explicit authorities.** `deleteReplayed` requires a
 * verified server receipt. `deleteHeldByUser` requires the owning Principal and
 * records a distinct `user_deleted` event. Neither path can delete another
 * Principal's payload, and an automatic retry can invoke only the first.
 *
 * **The bound refuses; it never evicts.** At `MAX_QUEUED_ENTRIES` or
 * `MAX_QUEUED_BYTES` a new enqueue raises `OfflineQueueFullError` and the
 * capture surface keeps the note in the field. Dropping the oldest entry to make
 * room would delete a note the person believes is held, which is the one outcome
 * a queue must never produce.
 *
 * **Quarantine is terminal for automatic replay.** It can be released only by
 * an explicit action while the original Principal is authenticated; release
 * appends an event and never rewrites the binding.
 */
import {
  EVENT_STORE,
  PAYLOAD_STORE,
  request,
  transactionDone,
} from "@/lib/offline/db";
import { sealBytes, unseal, unsealBytes, type SealedPayload } from "@/lib/offline/key";
import type { CaptureKind } from "@/lib/capture/contract";
import {
  CAPTURE_INTENT_SCHEMA_VERSION,
  CaptureQueueProtocolError,
  captureIntentAdditionalData,
  decodeCaptureIntentV2,
  detectCapturePayloadVersion,
  encodeCaptureIntentV2,
  type CaptureIntentEnvelope,
  type CapturePayloadVersion,
} from "@/lib/offline/capture-intent-codec";

/**
 * The local event a committed queue mutation dispatches.
 *
 * It lives beside the queue rather than on the browser facade because the
 * listener is a UI concern that must survive a test double of that facade: a
 * mocked composition module that omitted this constant would silently stop the
 * indicator refreshing.
 */
export const CAPTURE_QUEUE_CHANGED_EVENT = "mypa:capture-queue-changed";

/** How many entries may be held at once. A count, checked before every enqueue. */
export const MAX_QUEUED_ENTRIES = 50;

/** How many ciphertext bytes may be held at once, across every retained entry. */
export const MAX_QUEUED_BYTES = 1_000_000;

/**
 * How many replay failures an entry absorbs before it stops being retried.
 *
 * Replay runs on mount and on the browser's `online` event rather than on a
 * timer, so this is not what stops a spin — it is what stops an entry that fails
 * for a reason retrying will never fix from being resent on every reconnect
 * forever. A stalled entry keeps its bytes and is reported as stalled.
 */
export const MAX_REPLAY_ATTEMPTS = 5;

/** The states a folded entry can be in. */
export type OfflineEntryState =
  | "pending"
  | "stalled"
  | "quarantined"
  | "needs_reauth"
  | "replayed"
  | "deleted";

export interface OfflineEntry {
  readonly entryId: string;
  /** The principal authenticated when this entry was queued. Immutable. */
  readonly principalId: string;
  /** Minted once, at enqueue, and never regenerated. */
  readonly idempotencyKey: string;
  readonly captureKind: string;
  readonly byteLength: number;
  readonly queuedAt: number;
  /**
   * The application protocol this entry was written under.
   *
   * Absent means a historical row written before the versioned intent existed.
   * It is not defaulted to 2 and not defaulted to 1: absence is the marker, and
   * `detectCapturePayloadVersion` reads the raw stored values rather than
   * trusting this annotation, because persisted input can be anything.
   */
  readonly schemaVersion?: 2;
  readonly state: OfflineEntryState;
  readonly attemptCount: number;
  readonly lastReason: string | null;
}

export type OfflineEventRecord =
  | {
      seq?: number;
      entryId: string;
      type: "enqueued";
      at: number;
      principalId: string;
      idempotencyKey: string;
      captureKind: string;
      byteLength: number;
      schemaVersion?: 2;
    }
  | { seq?: number; entryId: string; type: "quarantined"; at: number; reason: string }
  | { seq?: number; entryId: string; type: "needs_reauth"; at: number; reason: string }
  | { seq?: number; entryId: string; type: "replay_failed"; at: number; reason: string }
  | { seq?: number; entryId: string; type: "released"; at: number; principalId: string }
  | { seq?: number; entryId: string; type: "payload_deleted"; at: number; receiptId: string }
  | { seq?: number; entryId: string; type: "user_deleted"; at: number; principalId: string };

export interface PayloadRecord {
  readonly entryId: string;
  readonly iv: Uint8Array;
  readonly ciphertext: ArrayBuffer;
  readonly schemaVersion?: 2;
}

/**
 * Raised when the queue is at its bound.
 *
 * Typed and carrying which bound was hit, because the surface has to say
 * something a person can act on and "held notes: 50 of 50" is actionable while
 * "could not save" is not. The enqueue is refused; nothing is evicted.
 */
export class OfflineQueueFullError extends Error {
  constructor(
    readonly bound: "entries" | "bytes",
    readonly held: number,
    readonly limit: number,
  ) {
    super(
      bound === "entries"
        ? `this device is already holding ${held} unsent notes, which is the limit of ${limit}. ` +
            "Nothing was queued and nothing was discarded to make room: your note is still in " +
            "the field. Reconnect so the held notes can be sent."
        : `this device is already holding ${held} bytes of unsent notes, which is the limit of ` +
            `${limit}. Nothing was queued and nothing was discarded to make room: your note is ` +
            "still in the field. Reconnect so the held notes can be sent.",
    );
    this.name = "OfflineQueueFullError";
  }
}

/** Fold the append-only log into one entry per `entryId`, in `seq` order. */
export function foldEntries(events: readonly OfflineEventRecord[]): readonly OfflineEntry[] {
  const ordered = [...events].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
  const byId = new Map<string, OfflineEntry>();
  // Entries are returned in the order they were appended, not by wall clock:
  // two notes queued inside the same millisecond have the same `queuedAt`, and
  // a replay pass that reordered them under load would be a different pass each
  // time it ran.
  const appendedAt = new Map<string, number>();
  for (const event of ordered) {
    if (event.type === "enqueued") {
      appendedAt.set(event.entryId, event.seq ?? appendedAt.size);
      byId.set(event.entryId, {
        entryId: event.entryId,
        principalId: event.principalId,
        idempotencyKey: event.idempotencyKey,
        captureKind: event.captureKind,
        byteLength: event.byteLength,
        queuedAt: event.at,
        ...(event.schemaVersion === CAPTURE_INTENT_SCHEMA_VERSION
          ? { schemaVersion: CAPTURE_INTENT_SCHEMA_VERSION }
          : {}),
        state: "pending",
        attemptCount: 0,
        lastReason: null,
      });
      continue;
    }
    const current = byId.get(event.entryId);
    if (!current) continue;
    // `replayed` is terminal: the bytes are gone, so nothing appended
    // afterwards can describe an entry that still exists.
    if (current.state === "replayed" || current.state === "deleted") continue;
    switch (event.type) {
      case "quarantined":
        byId.set(event.entryId, {
          ...current,
          state: "quarantined",
          lastReason: event.reason,
        });
        break;
      case "needs_reauth":
        if (current.state === "quarantined") break;
        byId.set(event.entryId, { ...current, state: "needs_reauth", lastReason: event.reason });
        break;
      case "replay_failed": {
        if (current.state === "quarantined") break;
        const attemptCount = current.attemptCount + 1;
        byId.set(event.entryId, {
          ...current,
          attemptCount,
          state: attemptCount >= MAX_REPLAY_ATTEMPTS ? "stalled" : "pending",
          lastReason: event.reason,
        });
        break;
      }
      case "payload_deleted":
        byId.set(event.entryId, { ...current, state: "replayed", lastReason: null });
        break;
      case "released":
        if (current.state === "quarantined" && event.principalId === current.principalId) {
          byId.set(event.entryId, { ...current, state: "pending", lastReason: null });
        }
        break;
      case "user_deleted":
        if (event.principalId === current.principalId) {
          byId.set(event.entryId, { ...current, state: "deleted", lastReason: null });
        }
        break;
    }
  }
  return [...byId.values()].sort(
    (a, b) => (appendedAt.get(a.entryId) ?? 0) - (appendedAt.get(b.entryId) ?? 0),
  );
}

/** Whether an entry still holds bytes on this device. */
export function retains(entry: OfflineEntry): boolean {
  return entry.state !== "replayed" && entry.state !== "deleted";
}

/** Whether automatic replay may attempt this entry. */
export function replayable(entry: OfflineEntry): boolean {
  return entry.state === "pending" || entry.state === "needs_reauth";
}

/** Every entry the log describes, folded. */
export async function queueSnapshot(db: IDBDatabase): Promise<readonly OfflineEntry[]> {
  const tx = db.transaction(EVENT_STORE, "readonly");
  const events = (await request(tx.objectStore(EVENT_STORE).getAll())) as OfflineEventRecord[];
  await transactionDone(tx).catch(() => undefined);
  return foldEntries(events);
}

/** The intent one enqueue carries. No session binding, no display name, no epoch. */
export interface CaptureQueueIntent {
  readonly principalId: string;
  readonly text: string;
  readonly captureKind: CaptureKind;
  readonly idempotencyKey: string;
  readonly projectId: string | null;
}

/** One entry's decrypted intent, and which protocol it was stored under. */
export interface DecryptedCaptureIntent {
  readonly version: CapturePayloadVersion;
  readonly text: string;
  /** Historical rows have no Project. That is null, not unknown, and not inferred. */
  readonly projectId: string | null;
}

/** Read one payload record without decrypting it. */
export async function readPayloadRecord(
  db: IDBDatabase,
  entryId: string,
): Promise<PayloadRecord | null> {
  const tx = db.transaction(PAYLOAD_STORE, "readonly");
  const record = (await request(tx.objectStore(PAYLOAD_STORE).get(entryId))) as
    | PayloadRecord
    | undefined;
  await transactionDone(tx).catch(() => undefined);
  return record ?? null;
}

function envelopeOf(entry: OfflineEntry): CaptureIntentEnvelope {
  return {
    entryId: entry.entryId,
    principalId: entry.principalId,
    idempotencyKey: entry.idempotencyKey,
    captureKind: entry.captureKind as CaptureKind,
    queuedAt: entry.queuedAt,
  };
}

/**
 * Decrypt and validate one entry's intent.
 *
 * The version is decided by the stored markers before any decryption is
 * attempted, and there is exactly one attempt. A v2 row is opened with its
 * envelope as additional data; a historical row is opened as raw text with none.
 * Neither falls back to the other — trying v2 and then retrying without AAD
 * would use authentication failure as a version probe and would eventually
 * accept a downgraded row as legacy.
 *
 * An unsupported or mismatched marker pair never decrypts at all.
 */
export async function readCaptureIntent(
  db: IDBDatabase,
  key: CryptoKey,
  entry: OfflineEntry,
  record: PayloadRecord,
): Promise<DecryptedCaptureIntent> {
  const version = detectCapturePayloadVersion(
    { schemaVersion: entry.schemaVersion },
    { schemaVersion: record.schemaVersion },
  );
  if (version === "unsupported") throw new CaptureQueueProtocolError("unsupported_version");

  const sealed: SealedPayload = { iv: record.iv, ciphertext: record.ciphertext };
  if (version === "legacy") {
    let text: string;
    try {
      text = await unseal(key, sealed);
    } catch {
      throw new CaptureQueueProtocolError("authentication_failed");
    }
    // A historical row carried no Project and no authenticated kind binding. Any
    // Project-shaped content inside its plaintext is not authority and does not
    // supply an association; the historical answer is null and stays null.
    return { version, text, projectId: null };
  }

  const envelope = envelopeOf(entry);
  let plaintext: Uint8Array;
  try {
    plaintext = await unsealBytes(key, sealed, captureIntentAdditionalData(envelope));
  } catch {
    throw new CaptureQueueProtocolError("authentication_failed");
  }
  const intent = decodeCaptureIntentV2(plaintext, envelope);
  return { version, text: intent.text, projectId: intent.projectId };
}

/**
 * Queue one note, encrypted, bound to `principalId`.
 *
 * **The entry ID is minted before the seal**, because it is part of the
 * additional authenticated data: an envelope has to name the row it belongs to
 * before the bytes that name it are produced.
 *
 * **An identical intent under an existing key is not queued twice.** A retry of
 * the same held note — same Principal, same idempotency key, same text, kind and
 * Project — returns the entry that already exists without resealing anything or
 * appending a second `enqueued` row. A *different* material tuple under that key
 * is a conflict: both the existing bytes and the caller's new draft are kept,
 * and the caller is told, because one key naming two different notes is exactly
 * the ambiguity the backend's uniqueness constraint would resolve by refusing.
 *
 * Equality is established by decrypting the existing entry. When that is not
 * possible — a historical row whose Project was never authenticated, a payload
 * that will not open — equality is *not assumed*: the enqueue is refused as a
 * conflict rather than writing a second row under the same key.
 *
 * Sealing happens before the transaction opens, so no plaintext is handed to the
 * store and no transaction waits on crypto. The capacity check, the journal
 * append and the payload write are one transaction; a refusal or an abort writes
 * nothing and evicts nothing.
 */
export async function enqueueCapture(
  db: IDBDatabase,
  key: CryptoKey,
  input: CaptureQueueIntent,
): Promise<OfflineEntry> {
  const existing = (await queueSnapshot(db)).find(
    (candidate) =>
      retains(candidate) &&
      candidate.principalId === input.principalId &&
      candidate.idempotencyKey === input.idempotencyKey,
  );
  if (existing) {
    const record = await readPayloadRecord(db, existing.entryId);
    if (!record) throw new CaptureQueueProtocolError("intent_conflict");
    let held: DecryptedCaptureIntent;
    try {
      held = await readCaptureIntent(db, key, existing, record);
    } catch {
      throw new CaptureQueueProtocolError("intent_conflict");
    }
    const same =
      held.version === "v2" &&
      held.text === input.text &&
      held.projectId === input.projectId &&
      existing.captureKind === input.captureKind;
    if (!same) throw new CaptureQueueProtocolError("intent_conflict");
    return existing;
  }

  const entryId = `oq-${crypto.randomUUID()}`;
  const at = Date.now();
  const envelope: CaptureIntentEnvelope = {
    entryId,
    principalId: input.principalId,
    idempotencyKey: input.idempotencyKey,
    captureKind: input.captureKind,
    queuedAt: at,
  };
  const sealed = await sealBytes(
    key,
    encodeCaptureIntentV2({ ...envelope, text: input.text, projectId: input.projectId }),
    captureIntentAdditionalData(envelope),
  );

  const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
  const eventStore = tx.objectStore(EVENT_STORE);
  const events = (await request(eventStore.getAll())) as OfflineEventRecord[];
  const retained = foldEntries(events).filter(retains);
  if (retained.length >= MAX_QUEUED_ENTRIES) {
    tx.abort();
    throw new OfflineQueueFullError("entries", retained.length, MAX_QUEUED_ENTRIES);
  }
  const heldBytes = retained.reduce((total, entry) => total + entry.byteLength, 0);
  if (heldBytes + sealed.ciphertext.byteLength > MAX_QUEUED_BYTES) {
    tx.abort();
    throw new OfflineQueueFullError("bytes", heldBytes, MAX_QUEUED_BYTES);
  }

  const event: OfflineEventRecord = {
    entryId,
    type: "enqueued",
    at,
    principalId: input.principalId,
    idempotencyKey: input.idempotencyKey,
    captureKind: input.captureKind,
    byteLength: sealed.ciphertext.byteLength,
    schemaVersion: CAPTURE_INTENT_SCHEMA_VERSION,
  };
  eventStore.add(event);
  const payload: PayloadRecord = {
    entryId,
    iv: sealed.iv,
    ciphertext: sealed.ciphertext,
    schemaVersion: CAPTURE_INTENT_SCHEMA_VERSION,
  };
  tx.objectStore(PAYLOAD_STORE).add(payload);
  await transactionDone(tx);

  return {
    entryId,
    principalId: input.principalId,
    idempotencyKey: input.idempotencyKey,
    captureKind: input.captureKind,
    byteLength: sealed.ciphertext.byteLength,
    queuedAt: at,
    schemaVersion: CAPTURE_INTENT_SCHEMA_VERSION,
    state: "pending",
    attemptCount: 0,
    lastReason: null,
  };
}

/** Append one event. The only write path for a state change. */
async function append(db: IDBDatabase, event: OfflineEventRecord): Promise<void> {
  const tx = db.transaction(EVENT_STORE, "readwrite");
  tx.objectStore(EVENT_STORE).add(event);
  await transactionDone(tx);
}

/** Record that an entry may not be replayed by the principal now signed in. */
export async function quarantineEntry(
  db: IDBDatabase,
  entryId: string,
  reason: string,
): Promise<void> {
  await append(db, { entryId, type: "quarantined", at: Date.now(), reason });
}

/** Record that replaying this entry met an unauthenticated or refused session. */
export async function markNeedsReauth(
  db: IDBDatabase,
  entryId: string,
  reason: string,
): Promise<void> {
  await append(db, { entryId, type: "needs_reauth", at: Date.now(), reason });
}

/** Record a replay attempt that did not produce a verified receipt. */
export async function markReplayFailed(
  db: IDBDatabase,
  entryId: string,
  reason: string,
): Promise<void> {
  await append(db, { entryId, type: "replay_failed", at: Date.now(), reason });
}

/**
 * The exact bytes and identity one replay attempt worked from.
 *
 * Carried into the deletion so the final transaction can prove it is deleting
 * the record it verified rather than whatever currently sits at that key.
 */
export interface RetainedPayloadSnapshot {
  readonly entryId: string;
  readonly principalId: string;
  readonly idempotencyKey: string;
  readonly captureKind: string;
  readonly queuedAt: number;
  readonly schemaVersion?: 2;
  readonly byteLength: number;
  readonly iv: Uint8Array;
  readonly ciphertext: ArrayBuffer;
}

/** The snapshot for one entry, or null when its bytes are already gone. */
export async function snapshotRetainedPayload(
  db: IDBDatabase,
  entry: OfflineEntry,
): Promise<RetainedPayloadSnapshot | null> {
  const record = await readPayloadRecord(db, entry.entryId);
  if (!record) return null;
  return {
    entryId: entry.entryId,
    principalId: entry.principalId,
    idempotencyKey: entry.idempotencyKey,
    captureKind: entry.captureKind,
    queuedAt: entry.queuedAt,
    ...(entry.schemaVersion === CAPTURE_INTENT_SCHEMA_VERSION
      ? { schemaVersion: CAPTURE_INTENT_SCHEMA_VERSION }
      : {}),
    byteLength: entry.byteLength,
    iv: record.iv,
    ciphertext: record.ciphertext,
  };
}

function sameBytes(left: ArrayBufferLike, right: ArrayBufferLike): boolean {
  if (left.byteLength !== right.byteLength) return false;
  const a = new Uint8Array(left);
  const b = new Uint8Array(right);
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return false;
  }
  return true;
}

/** Why a verified deletion did not happen. The bytes are kept in every case. */
export type DeletionRefusal = "already_terminal" | "payload_replaced" | "payload_missing";

export type DeletionOutcome =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: DeletionRefusal };

/**
 * Delete one entry's ciphertext and append the event that says why.
 *
 * The `receiptId` is required rather than optional: the only deletion this
 * module performs is one a server receipt earned, and a call that cannot name
 * the receipt has not earned it.
 *
 * **The snapshot is required for a second reason.** Between the moment a replay
 * verified a receipt and the moment it deletes, this row may have been completed
 * by another tab, released, or replaced. So the final transaction re-reads the
 * folded entry and the payload record and compares identity, immutable metadata,
 * the schema marker, the byte length and the IV and ciphertext bytes against what
 * the attempt actually worked from. Anything different is retained, not deleted:
 * a receipt for one note can never authorize deleting a different one.
 *
 * Crypto and receipt verification happen before this call. Nothing here awaits
 * anything but the transaction itself, so the read-compare-delete sequence
 * cannot be interleaved by IndexedDB.
 */
export async function deleteReplayed(
  db: IDBDatabase,
  snapshot: RetainedPayloadSnapshot,
  receiptId: string,
): Promise<DeletionOutcome> {
  const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
  const eventStore = tx.objectStore(EVENT_STORE);
  const payloadStore = tx.objectStore(PAYLOAD_STORE);

  const events = (await request(eventStore.getAll())) as OfflineEventRecord[];
  const current = foldEntries(events).find((entry) => entry.entryId === snapshot.entryId);
  if (!current || !retains(current)) {
    tx.abort();
    return { ok: false, reason: "already_terminal" };
  }
  if (
    current.principalId !== snapshot.principalId ||
    current.idempotencyKey !== snapshot.idempotencyKey ||
    current.captureKind !== snapshot.captureKind ||
    current.queuedAt !== snapshot.queuedAt ||
    current.byteLength !== snapshot.byteLength ||
    current.schemaVersion !== snapshot.schemaVersion
  ) {
    tx.abort();
    return { ok: false, reason: "payload_replaced" };
  }

  const record = (await request(payloadStore.get(snapshot.entryId))) as PayloadRecord | undefined;
  if (!record) {
    tx.abort();
    return { ok: false, reason: "payload_missing" };
  }
  if (
    record.schemaVersion !== snapshot.schemaVersion ||
    record.ciphertext.byteLength !== snapshot.ciphertext.byteLength ||
    !sameBytes(record.iv.buffer, snapshot.iv.buffer) ||
    !sameBytes(record.ciphertext, snapshot.ciphertext)
  ) {
    tx.abort();
    return { ok: false, reason: "payload_replaced" };
  }

  payloadStore.delete(snapshot.entryId);
  eventStore.add({
    entryId: snapshot.entryId,
    type: "payload_deleted",
    at: Date.now(),
    receiptId,
  } satisfies OfflineEventRecord);
  await transactionDone(tx);
  return { ok: true };
}

/** Release a quarantined entry only after its original Principal signs in. */
export async function releaseQuarantined(
  db: IDBDatabase,
  entryId: string,
  principalId: string,
): Promise<void> {
  const entry = (await queueSnapshot(db)).find((candidate) => candidate.entryId === entryId);
  if (!entry || entry.state !== "quarantined" || entry.principalId !== principalId) {
    throw new Error("only the owning principal may release this quarantined note");
  }
  await append(db, { entryId, type: "released", at: Date.now(), principalId });
}

/**
 * Delete a locally held payload at the owning user's explicit request.
 * This is deliberately distinct from receipt-earned deletion and records the
 * owning Principal that requested it. It cannot delete another account's note.
 */
export async function deleteHeldByUser(
  db: IDBDatabase,
  entryId: string,
  principalId: string,
): Promise<void> {
  const entry = (await queueSnapshot(db)).find((candidate) => candidate.entryId === entryId);
  if (!entry || !retains(entry) || entry.principalId !== principalId) {
    throw new Error("only the owning principal may delete this held note");
  }
  const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
  tx.objectStore(PAYLOAD_STORE).delete(entryId);
  tx.objectStore(EVENT_STORE).add({
    entryId,
    type: "user_deleted",
    at: Date.now(),
    principalId,
  } satisfies OfflineEventRecord);
  await transactionDone(tx);
}

/**
 * Quarantine every retained entry that a different principal queued.
 *
 * Called at a sign-in boundary. It never touches an entry belonging to the
 * principal now signed in, never deletes anything, and never rewrites a
 * binding — the foreign entries keep their bytes and become visible as a count
 * and a state. Returns how many were quarantined.
 */
export async function quarantineForeignEntries(
  db: IDBDatabase,
  currentPrincipalId: string,
): Promise<number> {
  const entries = await queueSnapshot(db);
  const foreign = entries.filter(
    (entry) =>
      retains(entry) && entry.state !== "quarantined" && entry.principalId !== currentPrincipalId,
  );
  for (const entry of foreign) {
    await quarantineEntry(
      db,
      entry.entryId,
      "queued by a different principal than the one now signed in",
    );
  }
  return foreign.length;
}

/**
 * Read and decrypt one entry's intent. Returns `null` when the bytes are gone.
 *
 * Routes through `readCaptureIntent`, so the version markers decide how the
 * payload is opened and a v2 row is authenticated against its journal identity.
 * A caller that only wants the words gets the words; a caller that needs the
 * Project must use `readCaptureIntent`, because this one cannot report it.
 */
export async function readPayloadIntent(
  db: IDBDatabase,
  key: CryptoKey,
  entryId: string,
): Promise<DecryptedCaptureIntent | null> {
  const record = await readPayloadRecord(db, entryId);
  if (!record) return null;
  const entry = (await queueSnapshot(db)).find((candidate) => candidate.entryId === entryId);
  if (!entry) return null;
  return readCaptureIntent(db, key, entry, record);
}

/** The authored text of one entry's intent, or `null` when the bytes are gone. */
export async function readPayloadText(
  db: IDBDatabase,
  key: CryptoKey,
  entryId: string,
): Promise<string | null> {
  return (await readPayloadIntent(db, key, entryId))?.text ?? null;
}

/** How many entries sit in each state. What a surface renders. */
export interface QueueCounts {
  readonly pending: number;
  readonly stalled: number;
  readonly quarantined: number;
  readonly needsReauth: number;
  readonly heldBytes: number;
}

/** Counts over the retained entries only; a replayed entry's bytes are gone. */
export function countStates(entries: readonly OfflineEntry[]): QueueCounts {
  const held = entries.filter(retains);
  return {
    pending: held.filter((entry) => entry.state === "pending").length,
    stalled: held.filter((entry) => entry.state === "stalled").length,
    quarantined: held.filter((entry) => entry.state === "quarantined").length,
    needsReauth: held.filter((entry) => entry.state === "needs_reauth").length,
    heldBytes: held.reduce((total, entry) => total + entry.byteLength, 0),
  };
}
