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
 * enqueue.** `replay.ts` compares the currently authenticated principal against
 * the entry's own and refuses when they differ. It quarantines; it does not
 * rebind, does not delete, and does not send. `quarantineForeignEntries` is the
 * same rule applied eagerly at a sign-in boundary so the state a person sees is
 * right before anything tries to replay.
 *
 * **The only deletion is the one a verified receipt earns, and there is no
 * discard.** No user-initiated discard control exists in this package, so the
 * receipt-verified deletion below is the sole removal path. `deleteReplayed`
 * removes the ciphertext and appends a `payload_deleted` event naming the
 * receipt. `replay.ts` decides whether a receipt has been earned and this module
 * does not: keeping the decision and the deletion in different files means the
 * verification cannot be quietly widened by editing the store.
 *
 * **The bound refuses; it never evicts.** At `MAX_QUEUED_ENTRIES` or
 * `MAX_QUEUED_BYTES` a new enqueue raises `OfflineQueueFullError` and the
 * capture surface keeps the note in the field. Dropping the oldest entry to make
 * room would delete a note the person believes is held, which is the one outcome
 * a queue must never produce.
 *
 * **Quarantine is terminal for automatic replay, and that is a limitation
 * rather than a design goal.** A quarantined entry keeps its bytes and stays
 * visible as a count and a state, but nothing in this package releases it — not
 * even signing back in as the principal that queued it. Releasing one needs a
 * user-initiated control this package does not provide, so a quarantined entry
 * occupies its share of the bound indefinitely. Stated here rather than left to
 * be discovered.
 */
import {
  EVENT_STORE,
  PAYLOAD_STORE,
  request,
  transactionDone,
} from "@/lib/offline/db";
import { seal, unseal, type SealedPayload } from "@/lib/offline/key";

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
  | "replayed";

export interface OfflineEntry {
  readonly entryId: string;
  /** The principal authenticated when this entry was queued. Immutable. */
  readonly principalId: string;
  /** Minted once, at enqueue, and never regenerated. */
  readonly idempotencyKey: string;
  readonly captureKind: string;
  readonly byteLength: number;
  readonly queuedAt: number;
  readonly state: OfflineEntryState;
  readonly attemptCount: number;
  readonly lastReason: string | null;
}

type OfflineEventRecord =
  | {
      seq?: number;
      entryId: string;
      type: "enqueued";
      at: number;
      principalId: string;
      idempotencyKey: string;
      captureKind: string;
      byteLength: number;
    }
  | { seq?: number; entryId: string; type: "quarantined"; at: number; reason: string }
  | { seq?: number; entryId: string; type: "needs_reauth"; at: number; reason: string }
  | { seq?: number; entryId: string; type: "replay_failed"; at: number; reason: string }
  | { seq?: number; entryId: string; type: "payload_deleted"; at: number; receiptId: string };

interface PayloadRecord {
  readonly entryId: string;
  readonly iv: Uint8Array;
  readonly ciphertext: ArrayBuffer;
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
    if (current.state === "replayed") continue;
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
    }
  }
  return [...byId.values()].sort(
    (a, b) => (appendedAt.get(a.entryId) ?? 0) - (appendedAt.get(b.entryId) ?? 0),
  );
}

/** Whether an entry still holds bytes on this device. */
export function retains(entry: OfflineEntry): boolean {
  return entry.state !== "replayed";
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

/**
 * Queue one note, encrypted, bound to `principalId`.
 *
 * The text is sealed before the transaction opens, so no plaintext is ever
 * handed to the store and the only failure that can leave a half-written entry
 * is one IndexedDB itself aborts — which aborts the event and the payload
 * together, since both are written in one transaction.
 */
export async function enqueueCapture(
  db: IDBDatabase,
  key: CryptoKey,
  input: {
    readonly principalId: string;
    readonly text: string;
    readonly captureKind: string;
    readonly idempotencyKey: string;
  },
): Promise<OfflineEntry> {
  const sealed = await seal(key, input.text);
  const entryId = `oq-${crypto.randomUUID()}`;
  const at = Date.now();

  const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
  const eventStore = tx.objectStore(EVENT_STORE);
  const existing = (await request(eventStore.getAll())) as OfflineEventRecord[];
  const retained = foldEntries(existing).filter(retains);
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
  };
  eventStore.add(event);
  const payload: PayloadRecord = {
    entryId,
    iv: sealed.iv,
    ciphertext: sealed.ciphertext,
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
 * Delete one entry's ciphertext and append the event that says why.
 *
 * The `receiptId` is required rather than optional: the only deletion this
 * module performs is one a server receipt earned, and a call that cannot name
 * the receipt has not earned it.
 */
export async function deleteReplayed(
  db: IDBDatabase,
  entryId: string,
  receiptId: string,
): Promise<void> {
  const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
  tx.objectStore(PAYLOAD_STORE).delete(entryId);
  tx.objectStore(EVENT_STORE).add({
    entryId,
    type: "payload_deleted",
    at: Date.now(),
    receiptId,
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

/** Read and decrypt one entry's payload. Returns `null` when the bytes are gone. */
export async function readPayloadText(
  db: IDBDatabase,
  key: CryptoKey,
  entryId: string,
): Promise<string | null> {
  const tx = db.transaction(PAYLOAD_STORE, "readonly");
  const record = (await request(tx.objectStore(PAYLOAD_STORE).get(entryId))) as
    | PayloadRecord
    | undefined;
  await transactionDone(tx).catch(() => undefined);
  if (!record) return null;
  const sealed: SealedPayload = { iv: record.iv, ciphertext: record.ciphertext };
  return unseal(key, sealed);
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
