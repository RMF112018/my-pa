/**
 * T09 — the deletion predicate (C07).
 *
 * Every test here asks the same question from a different angle: what is
 * sufficient to delete the only copy of somebody's note? The answer is a
 * complete verified receipt for *this* intent, under an unchanged session, over
 * the exact bytes the attempt worked from. Anything less retains.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import {
  EVENT_STORE,
  PAYLOAD_STORE,
  openOfflineDatabase,
  request,
  transactionDone,
} from "@/lib/offline/db";
import { KEY_STORE } from "@/lib/offline/db";
import { getOrCreatePrincipalKey } from "@/lib/offline/key";
import { contentSha256 } from "@/lib/capture/receipt";
import {
  MAX_REPLAY_ATTEMPTS,
  enqueueCapture,
  queueSnapshot,
  type OfflineEntry,
} from "@/lib/offline/queue";
import {
  replayQueuedCaptures,
  type ReplayResponse,
  type ReplayTransport,
} from "@/lib/offline/replay";
import { installTestWebLocks, removeWebLocks } from "@/lib/offline/testing/web-locks";

const PRINCIPAL_A = "syn-aaaa0001";
const PRINCIPAL_B = "syn-bbbb0002";
const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";
const NOTE = "synthetic note alpha";

let db: IDBDatabase;
let key: CryptoKey;
let locks: ReturnType<typeof installTestWebLocks>;

const sessionA = async () => ({ principalId: PRINCIPAL_A, replayBinding: "a".repeat(64) });

beforeEach(async () => {
  globalThis.indexedDB = new IDBFactory();
  vi.restoreAllMocks();
  locks = installTestWebLocks();
  db = await openOfflineDatabase();
  key = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
});

afterEach(() => {
  locks.restore();
});

async function queueOne(
  projectId: string | null = PROJECT_A,
  idempotencyKey = "cap-synthetic-0001",
  text = NOTE,
): Promise<OfflineEntry> {
  return enqueueCapture(db, key, {
    principalId: PRINCIPAL_A,
    text,
    captureKind: "quick_note",
    idempotencyKey,
    projectId,
  });
}

async function payloadPresent(entryId: string): Promise<boolean> {
  const tx = db.transaction(PAYLOAD_STORE, "readonly");
  const record = await request(tx.objectStore(PAYLOAD_STORE).get(entryId));
  await transactionDone(tx).catch(() => undefined);
  return record !== undefined;
}

async function stateOf(entryId: string): Promise<string | undefined> {
  return (await queueSnapshot(db)).find((entry) => entry.entryId === entryId)?.state;
}

async function reasonsFor(entryId: string): Promise<readonly string[]> {
  const tx = db.transaction(EVENT_STORE, "readonly");
  const events = (await request(tx.objectStore(EVENT_STORE).getAll())) as Record<string, unknown>[];
  await transactionDone(tx).catch(() => undefined);
  return events
    .filter((event) => event.entryId === entryId && typeof event.reason === "string")
    .map((event) => event.reason as string);
}

/** A complete canonical acknowledgement for the submission that was sent. */
async function persistedReceipt(
  request_: { text: string; idempotencyKey: string; projectId: string | null },
  overrides: Record<string, unknown> = {},
  receiptOverrides: Record<string, unknown> = {},
): Promise<ReplayResponse> {
  return {
    status: 200,
    body: {
      shape: "backend",
      status: "persisted",
      captureKind: "quick_note",
      created: true,
      receipt: {
        receiptId: "rcpt-synthetic-0001",
        captureId: "cap-synthetic-0001",
        versionId: "ver-synthetic-0001",
        versionNumber: 1,
        idempotencyKey: request_.idempotencyKey,
        contentSha256: await contentSha256(request_.text),
        principalId: PRINCIPAL_A,
        issuedAt: "2026-09-22T12:00:00Z",
        projectId: request_.projectId,
        ...receiptOverrides,
      },
      ...overrides,
    },
  };
}

describe("the Project travels with the intent and is never re-derived", () => {
  it("POSTs the frozen Project and deletes on a fully verified receipt", async () => {
    const entry = await queueOne(PROJECT_A);
    const transport = vi.fn<ReplayTransport>(async (req) => persistedReceipt(req));

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0]![0]).toMatchObject({
      text: NOTE,
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-0001",
      projectId: PROJECT_A,
    });
    expect(transport.mock.calls[0]![0].signal).toBeInstanceOf(AbortSignal);
    expect(summary).toMatchObject({ attempted: 1, replayed: 1, failed: 0 });
    expect(await payloadPresent(entry.entryId)).toBe(false);
    expect(await stateOf(entry.entryId)).toBe("replayed");
  });

  it("POSTs an explicit null for a No Project note", async () => {
    await queueOne(null, "cap-synthetic-none");
    const transport = vi.fn<ReplayTransport>(async (req) => persistedReceipt(req));
    await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);
    expect(transport.mock.calls[0]![0].projectId).toBeNull();
  });
});

describe("a receipt for a different note never authorizes a deletion", () => {
  async function replayWith(
    receipt: (req: { text: string; idempotencyKey: string; projectId: string | null }) => Promise<ReplayResponse>,
    projectId: string | null = PROJECT_A,
  ) {
    const entry = await queueOne(projectId, "cap-synthetic-verify");
    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, receipt, sessionA);
    return { entry, summary };
  }

  it("retains on a Project mismatch", async () => {
    const { entry, summary } = await replayWith(async (req) =>
      persistedReceipt(req, {}, { projectId: PROJECT_B }),
    );
    expect(summary).toMatchObject({ replayed: 0, failed: 1 });
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("project_mismatch");
  });

  it("retains when a Project-bearing note comes back with a null Project", async () => {
    const { entry } = await replayWith(async (req) =>
      persistedReceipt(req, {}, { projectId: null }),
    );
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("project_mismatch");
  });

  it("retains when a No Project note comes back named against a Project", async () => {
    const { entry } = await replayWith(
      async (req) => persistedReceipt(req, {}, { projectId: PROJECT_A }),
      null,
    );
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("project_mismatch");
  });

  it("retains on a digest, key or Principal mismatch", async () => {
    for (const [override, reason] of [
      [{ contentSha256: "0".repeat(64) }, "digest_mismatch"],
      [{ idempotencyKey: "cap-synthetic-other" }, "key_mismatch"],
      [{ principalId: PRINCIPAL_B }, "principal_mismatch"],
    ] as const) {
      globalThis.indexedDB = new IDBFactory();
      db = await openOfflineDatabase();
      key = await getOrCreatePrincipalKey(db, PRINCIPAL_A);
      const { entry } = await replayWith(async (req) => persistedReceipt(req, {}, override));
      expect(await payloadPresent(entry.entryId)).toBe(true);
      expect(await reasonsFor(entry.entryId)).toContain(reason);
    }
  });

  it("retains on a synthetic acknowledgement, which is not durability", async () => {
    const { entry, summary } = await replayWith(async () => ({
      status: 200,
      body: {
        shape: "synthetic",
        status: "acknowledged_not_persisted",
        receiptId: "rcpt-synthetic",
        created: true,
        captureKind: "quick_note",
      },
    }));
    expect(summary).toMatchObject({ replayed: 0, failed: 1 });
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("not_persisted");
  });

  it("retains on a bare 2xx with no receipt at all", async () => {
    const { entry } = await replayWith(async () => ({ status: 200, body: { ok: true } }));
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("malformed_receipt");
  });

  it("retains when the transport times out or throws", async () => {
    const { entry, summary } = await replayWith(async () => {
      throw new DOMException("aborted", "AbortError");
    });
    expect(summary).toMatchObject({ replayed: 0, failed: 1 });
    expect(await payloadPresent(entry.entryId)).toBe(true);
    // Never "not stored": the backend may well have committed.
    expect(await reasonsFor(entry.entryId)).toContain("transport_unconfirmed");
  });
});

describe("corrupt, unsupported and keyless rows are retained and never sent", () => {
  it("never POSTs a row whose version markers do not agree", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-unsupported");
    const record = (await request(
      db.transaction(PAYLOAD_STORE, "readonly").objectStore(PAYLOAD_STORE).get(entry.entryId),
    )) as Record<string, unknown>;
    const tx = db.transaction(PAYLOAD_STORE, "readwrite");
    tx.objectStore(PAYLOAD_STORE).put({
      entryId: record.entryId,
      iv: record.iv,
      ciphertext: record.ciphertext,
    });
    await transactionDone(tx);

    const transport = vi.fn<ReplayTransport>();
    await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(transport).not.toHaveBeenCalled();
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("unsupported_version");
  });

  it("never POSTs a row whose ciphertext will not authenticate", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-corrupt");
    const record = (await request(
      db.transaction(PAYLOAD_STORE, "readonly").objectStore(PAYLOAD_STORE).get(entry.entryId),
    )) as { entryId: string; iv: Uint8Array; ciphertext: ArrayBuffer; schemaVersion: number };
    const corrupted = new Uint8Array(record.ciphertext);
    corrupted[0] = corrupted[0]! ^ 0xff;
    const tx = db.transaction(PAYLOAD_STORE, "readwrite");
    tx.objectStore(PAYLOAD_STORE).put({ ...record, ciphertext: corrupted.buffer });
    await transactionDone(tx);

    const transport = vi.fn<ReplayTransport>();
    await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(transport).not.toHaveBeenCalled();
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("authentication_failed");
  });

  it("does not attempt, and consumes no attempt, when the key is gone", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-keyless");
    const tx = db.transaction(KEY_STORE, "readwrite");
    tx.objectStore(KEY_STORE).clear();
    await transactionDone(tx);

    const transport = vi.fn<ReplayTransport>();
    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(transport).not.toHaveBeenCalled();
    expect(summary).toMatchObject({ attempted: 0, failed: 0, blocked: 1 });
    expect(await payloadPresent(entry.entryId)).toBe(true);
    // No key was minted to "fix" it.
    expect(await stateOf(entry.entryId)).toBe("pending");
  });
});

describe("the queue lock gates every attempt", () => {
  it("attempts nothing while another owner holds the lock", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-busy");
    locks.hold("mypa-offline-capture");
    const transport = vi.fn<ReplayTransport>();

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(transport).not.toHaveBeenCalled();
    expect(summary).toMatchObject({ attempted: 0, replayed: 0, failed: 0, blocked: 1 });
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toEqual([]);
  });

  it("attempts nothing at all when the origin has no Web Locks API", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-nolocks");
    const restore = removeWebLocks();
    try {
      const transport = vi.fn<ReplayTransport>();
      const summary = await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);
      expect(transport).not.toHaveBeenCalled();
      expect(summary.blocked).toBe(1);
      expect(await payloadPresent(entry.entryId)).toBe(true);
    } finally {
      restore();
    }
  });
});

describe("the session is re-checked at every boundary", () => {
  it("does not decrypt when authority cannot be established", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-noauth");
    const decrypt = vi.spyOn(crypto.subtle, "decrypt");
    const transport = vi.fn<ReplayTransport>();

    await replayQueuedCaptures(db, PRINCIPAL_A, transport, async () => null);

    expect(decrypt).not.toHaveBeenCalled();
    expect(transport).not.toHaveBeenCalled();
    expect(await stateOf(entry.entryId)).toBe("needs_reauth");
    expect(await payloadPresent(entry.entryId)).toBe(true);
  });

  it("does not POST when the cookie binding changes between decrypt and write", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-rebind");
    const answers = [
      { principalId: PRINCIPAL_A, replayBinding: "a".repeat(64) },
      // Same Principal, different cookie. The write must not go out under a
      // binding the BFF would refuse.
      { principalId: PRINCIPAL_A, replayBinding: "b".repeat(64) },
    ];
    const transport = vi.fn<ReplayTransport>();

    const summary = await replayQueuedCaptures(
      db,
      PRINCIPAL_A,
      transport,
      async () => answers.shift() ?? null,
    );

    expect(transport).not.toHaveBeenCalled();
    expect(summary).toMatchObject({ attempted: 0, needsReauth: 1 });
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("session_changed");
  });

  it("does not delete when the session changes between the receipt and the deletion", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-latedrift");
    const answers = [
      { principalId: PRINCIPAL_A, replayBinding: "a".repeat(64) },
      { principalId: PRINCIPAL_A, replayBinding: "a".repeat(64) },
      // The third resolution is the one immediately before deletion.
      { principalId: PRINCIPAL_B, replayBinding: "b".repeat(64) },
    ];
    const transport = vi.fn<ReplayTransport>(async (req) => persistedReceipt(req));

    const summary = await replayQueuedCaptures(
      db,
      PRINCIPAL_A,
      transport,
      async () => answers.shift() ?? null,
    );

    expect(transport).toHaveBeenCalledTimes(1);
    expect(summary).toMatchObject({ replayed: 0, needsReauth: 1 });
    // The note was very likely stored. It is still held, because an earlier
    // session's proof cannot authorize a deletion after a Principal switch.
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("session_changed");
  });

  it("carries the current binding to the transport", async () => {
    await queueOne(PROJECT_A, "cap-synthetic-binding");
    const transport = vi.fn<ReplayTransport>(async (req) => persistedReceipt(req));
    await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);
    expect(transport.mock.calls[0]![0].replayBinding).toBe("a".repeat(64));
  });
});

describe("the final transactional check", () => {
  it("does not delete a record that was replaced after the receipt was verified", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-replaced");
    const transport: ReplayTransport = async (req) => {
      // Between the verified receipt and the deletion, the record under this key
      // becomes different bytes. A receipt for the old note may not delete it.
      const tx = db.transaction(PAYLOAD_STORE, "readwrite");
      tx.objectStore(PAYLOAD_STORE).put({
        entryId: entry.entryId,
        iv: new Uint8Array(12),
        ciphertext: new ArrayBuffer(16),
        schemaVersion: 2,
      });
      await transactionDone(tx);
      return persistedReceipt(req);
    };

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(summary).toMatchObject({ replayed: 0, failed: 1 });
    expect(await payloadPresent(entry.entryId)).toBe(true);
  });

  it("is a no-op rather than a second deletion event when another actor finished the row", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-raced");
    const transport: ReplayTransport = async (req) => {
      const tx = db.transaction([EVENT_STORE, PAYLOAD_STORE], "readwrite");
      tx.objectStore(PAYLOAD_STORE).delete(entry.entryId);
      tx.objectStore(EVENT_STORE).add({
        entryId: entry.entryId,
        type: "payload_deleted",
        at: Date.now(),
        receiptId: "rcpt-other-tab",
      });
      await transactionDone(tx);
      return persistedReceipt(req);
    };

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(summary.replayed).toBe(0);
    const tx = db.transaction(EVENT_STORE, "readonly");
    const events = (await request(tx.objectStore(EVENT_STORE).getAll())) as Record<
      string,
      unknown
    >[];
    await transactionDone(tx).catch(() => undefined);
    expect(events.filter((event) => event.type === "payload_deleted").length).toBe(1);
  });
});

describe("the five-failure bound", () => {
  it("stalls after the fifth failure and still holds the bytes", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-stall");
    const transport: ReplayTransport = async () => ({ status: 503, body: null });

    for (let attempt = 0; attempt < MAX_REPLAY_ATTEMPTS; attempt += 1) {
      await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);
    }

    expect(await stateOf(entry.entryId)).toBe("stalled");
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect((await reasonsFor(entry.entryId)).length).toBe(MAX_REPLAY_ATTEMPTS);

    // A stalled entry is not retried, and is not deleted either.
    const spy = vi.fn<ReplayTransport>();
    await replayQueuedCaptures(db, PRINCIPAL_A, spy, sessionA);
    expect(spy).not.toHaveBeenCalled();
    expect(await payloadPresent(entry.entryId)).toBe(true);
  });

  it("spends no attempt on a preflight refusal", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-preflight");
    const transport = vi.fn<ReplayTransport>();
    for (let attempt = 0; attempt < MAX_REPLAY_ATTEMPTS + 2; attempt += 1) {
      locks.hold("mypa-offline-capture");
      await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);
      locks.release("mypa-offline-capture");
    }
    expect(transport).not.toHaveBeenCalled();
    expect(await stateOf(entry.entryId)).toBe("pending");
    expect(await reasonsFor(entry.entryId)).toEqual([]);
  });
});

describe("a foreign Project refusal is the canonical one", () => {
  it("retains the entry and does not retry without the Project", async () => {
    const entry = await queueOne(PROJECT_A, "cap-synthetic-revoked");
    const transport = vi.fn<ReplayTransport>(async () => ({
      status: 404,
      body: { error: { errorClass: "not_found", code: "not_found", message: "project_id" } },
    }));

    await replayQueuedCaptures(db, PRINCIPAL_A, transport, sessionA);

    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0]![0].projectId).toBe(PROJECT_A);
    expect(await payloadPresent(entry.entryId)).toBe(true);
    expect(await reasonsFor(entry.entryId)).toContain("http_404");
  });
});
