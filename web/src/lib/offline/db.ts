/**
 * The one IndexedDB database this tier owns, and the three stores in it.
 *
 * There is no abstraction over IndexedDB here and there deliberately is not one:
 * `AGENTS.md` section 2 forbids a speculative layer, there is exactly one
 * implementation, and a wrapper would mean the tests exercised the wrapper
 * rather than the store the browser actually uses. The promise adapters below
 * are the whole of the accommodation — IndexedDB's request objects are callback
 * shaped and nothing else in this tree is.
 *
 * **Three stores, and the split between them is what makes the queue
 * append-only.**
 *
 * * `principal_keys` — one non-extractable `CryptoKey` per `principalId`. See
 *   `key.ts` for what that protects and, more importantly, what it does not.
 * * `events` — the append-only log. Every state change is a new record with a
 *   monotonically increasing `seq`; nothing here is ever updated in place, and
 *   an entry's identity, its principal binding, and its idempotency key are
 *   written once in its `enqueued` event and never rewritten.
 * * `payloads` — the encrypted note bytes, keyed by `entryId`. This is the only
 *   store anything ever deletes from, and a deletion is always accompanied by an
 *   appended event that records why. Keeping the ciphertext out of the event log
 *   is what lets the log stay append-only while the bytes are still removable
 *   once the server has taken responsibility for them.
 *
 * **The database is per-origin and per-browser-profile.** It is not synchronised
 * anywhere, it is not backed up, and the browser may evict it under storage
 * pressure. A queued note is held on one device and nowhere else until it
 * replays.
 */

/** The database name. Versioned by `OFFLINE_DB_VERSION`, not by the name. */
export const OFFLINE_DB_NAME = "mypa-offline";

/** Schema version. Bump only alongside an `onupgradeneeded` branch. */
export const OFFLINE_DB_VERSION = 1;

export const KEY_STORE = "principal_keys";
export const EVENT_STORE = "events";
export const PAYLOAD_STORE = "payloads";

/** Index on `events.entryId`, so one entry's history is a range read. */
export const EVENT_ENTRY_INDEX = "by_entry";

/**
 * Raised when this environment has no IndexedDB at all.
 *
 * A distinct error rather than a `null` return: the caller has to be able to
 * tell "there is nothing queued" from "nothing can be queued here", and the
 * second must never be answered by falling back to memory. A queue that lives in
 * a tab's memory would tell someone their note is held and lose it on reload.
 */
export class OfflineStorageUnavailableError extends Error {
  constructor(detail: string) {
    super(
      `offline capture is unavailable: ${detail}. Nothing was queued. A note is ` +
        "kept in the field rather than held somewhere that cannot survive a reload.",
    );
    this.name = "OfflineStorageUnavailableError";
  }
}

/** Whether this environment exposes IndexedDB at all. */
export function offlineStorageAvailable(): boolean {
  return typeof indexedDB !== "undefined";
}

/** Wrap one IndexedDB request as a promise. */
export function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexeddb request failed"));
  });
}

/** Resolve when a transaction commits; reject when it aborts or errors. */
export function transactionDone(tx: IDBTransaction): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onabort = () => reject(tx.error ?? new Error("indexeddb transaction aborted"));
    tx.onerror = () => reject(tx.error ?? new Error("indexeddb transaction failed"));
  });
}

/**
 * Open the offline database, creating the stores on first use.
 *
 * Refuses rather than degrades when IndexedDB is absent.
 */
export function openOfflineDatabase(): Promise<IDBDatabase> {
  if (!offlineStorageAvailable()) {
    throw new OfflineStorageUnavailableError("this browser exposes no IndexedDB");
  }
  return new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);
    open.onupgradeneeded = () => {
      const db = open.result;
      if (!db.objectStoreNames.contains(KEY_STORE)) {
        db.createObjectStore(KEY_STORE, { keyPath: "principalId" });
      }
      if (!db.objectStoreNames.contains(EVENT_STORE)) {
        const events = db.createObjectStore(EVENT_STORE, { keyPath: "seq", autoIncrement: true });
        events.createIndex(EVENT_ENTRY_INDEX, "entryId", { unique: false });
      }
      if (!db.objectStoreNames.contains(PAYLOAD_STORE)) {
        db.createObjectStore(PAYLOAD_STORE, { keyPath: "entryId" });
      }
    };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () =>
      reject(
        new OfflineStorageUnavailableError(
          open.error?.message ?? "the offline database could not be opened",
        ),
      );
    open.onblocked = () =>
      reject(new OfflineStorageUnavailableError("the offline database is blocked by another tab"));
  });
}
