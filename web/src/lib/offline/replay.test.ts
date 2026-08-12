/**
 * Replay: the Principal refusal, the stale-session stop, the receipt that has to
 * be verified before anything local is deleted, and the key that is never
 * regenerated.
 *
 * **What level these are, stated plainly.** The queue, the key, the fold, and
 * the replay function are all real, and IndexedDB is a real implementation. The
 * *transport* is faked, so these are unit/integration proofs at the queue and
 * replay boundary and are **not** end-to-end browser proofs. They cannot be, at
 * this head: under `MYPA_GATEWAY_AUTH_MODE=local_operator` the web tier admits
 * exactly one Principal (`D-15`), and with the gateway mode unset or `entra`
 * every backend route refuses, so no reachable configuration admits two
 * identities *and* serves backend data. A browser run of "sign in as A, capture
 * offline, sign in as B, observe quarantine" is not constructible here and none
 * was performed.
 *
 * Every note and identifier below is obviously synthetic.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import { PAYLOAD_STORE, openOfflineDatabase, request, transactionDone } from "@/lib/offline/db";
import { principalContentKey } from "@/lib/offline/key";
import { enqueueCapture, queueSnapshot, type OfflineEntry } from "@/lib/offline/queue";
import {
  contentSha256,
  replayQueuedCaptures,
  verifyReceipt,
  type ReplayResponse,
  type ReplayTransport,
} from "@/lib/offline/replay";

const PRINCIPAL_A = "syn-aaaa0001";
const PRINCIPAL_B = "syn-bbbb0002";
const NOTE = "synthetic note alpha";
const sessionFor = (principalId: string) => async () => ({
  principalId,
  replayBinding: `binding-${principalId}`,
});

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  vi.restoreAllMocks();
});

async function payloadPresent(db: IDBDatabase, entryId: string): Promise<boolean> {
  const tx = db.transaction(PAYLOAD_STORE, "readonly");
  const record = await request(tx.objectStore(PAYLOAD_STORE).get(entryId));
  await transactionDone(tx).catch(() => undefined);
  return record !== undefined;
}

async function queueOne(
  principalId: string,
  text = NOTE,
  idempotencyKey = "cap-synthetic-0001",
): Promise<{ db: IDBDatabase; key: CryptoKey; entry: OfflineEntry }> {
  const db = await openOfflineDatabase();
  const key = await principalContentKey(db, principalId);
  const entry = await enqueueCapture(db, key, {
    principalId,
    text,
    captureKind: "quick_note",
    idempotencyKey,
  });
  return { db, key, entry };
}

/** A well-formed durable receipt for the given submission. */
async function goodReceipt(
  text: string,
  idempotencyKey: string,
  created = true,
): Promise<ReplayResponse> {
  return {
    status: 200,
    body: {
      shape: "backend",
      status: "persisted",
      captureKind: "quick_note",
      created,
      receipt: {
        receiptId: "rcpt-synthetic-0001",
        captureId: "cap-synthetic-0001",
        versionId: "ver-synthetic-0001",
        versionNumber: 1,
        idempotencyKey,
        contentSha256: await contentSha256(text),
        principalId: PRINCIPAL_A,
        issuedAt: "2026-08-09T00:00:00Z",
      },
    },
  };
}

describe("the digest this tier computes is the digest the backend computes", () => {
  it("matches the SHA-256 of the UTF-8 bytes of the stored text", async () => {
    // `my_pa.domain.capture.version.digest_of` is
    // `hashlib.sha256(text.encode("utf-8")).hexdigest()` over the text as stored,
    // with no normalisation, and `POST /api/capture` sends `text.trim()` which
    // the Python side stores verbatim. The vector below is that function's own
    // output for this exact string, taken from the interpreter rather than from
    // this implementation, so the two are compared instead of agreeing with
    // themselves.
    await expect(contentSha256("synthetic note alpha")).resolves.toBe(
      "293ee4b6581c9752781885559b5fd400e26228ad275ac7d746ad9d12b8b91c23",
    );
  });
});

describe("control 2 — a queued entry never rebinds Principal", () => {
  it("checks the authenticating Principal before decrypting a stale rendered Principal's entry", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A);
    const decrypt = vi.spyOn(crypto.subtle, "decrypt");
    const transport = vi.fn<ReplayTransport>();

    const summary = await replayQueuedCaptures(
      db,
      PRINCIPAL_A,
      key,
      transport,
      sessionFor(PRINCIPAL_B),
    );

    expect(decrypt).not.toHaveBeenCalled();
    expect(transport).not.toHaveBeenCalled();
    expect(summary).toMatchObject({ attempted: 0, needsReauth: 1, stoppedForReauth: true });
    expect((await queueSnapshot(db))[0]).toMatchObject({
      principalId: PRINCIPAL_A,
      state: "needs_reauth",
    });
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
  });

  it("fails closed before decrypt when current authentication cannot be established", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A);
    const decrypt = vi.spyOn(crypto.subtle, "decrypt");
    const transport = vi.fn<ReplayTransport>();

    await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, async () => null);

    expect(decrypt).not.toHaveBeenCalled();
    expect(transport).not.toHaveBeenCalled();
    expect((await queueSnapshot(db))[0].state).toBe("needs_reauth");
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
  });

  it("quarantines a foreign entry, never sends it, and never decrypts it", async () => {
    const { db, entry } = await queueOne(PRINCIPAL_A);
    const keyB = await principalContentKey(db, PRINCIPAL_B);
    const decrypt = vi.spyOn(crypto.subtle, "decrypt");
    const transport = vi.fn<ReplayTransport>();

    const summary = await replayQueuedCaptures(db, PRINCIPAL_B, keyB, transport, sessionFor(PRINCIPAL_B));

    expect(transport).not.toHaveBeenCalled();
    expect(decrypt).not.toHaveBeenCalled();
    expect(summary).toMatchObject({ attempted: 0, replayed: 0, quarantined: 1 });

    const folded = (await queueSnapshot(db))[0];
    expect(folded.state).toBe("quarantined");
    // Never rebound and never deleted.
    expect(folded.principalId).toBe(PRINCIPAL_A);
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
  });

  it("replays the caller's own entry in the same pass that quarantines the foreign one", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A, NOTE, "cap-synthetic-mine");
    const keyB = await principalContentKey(db, PRINCIPAL_B);
    const theirs = await enqueueCapture(db, keyB, {
      principalId: PRINCIPAL_B,
      text: "synthetic note owned by b",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-theirs",
    });
    const transport = vi.fn<ReplayTransport>(async (req) =>
      goodReceipt(req.text, req.idempotencyKey),
    );

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));

    expect(summary).toMatchObject({ replayed: 1, quarantined: 1 });
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][0].idempotencyKey).toBe("cap-synthetic-mine");
    expect(await payloadPresent(db, entry.entryId)).toBe(false);
    expect(await payloadPresent(db, theirs.entryId)).toBe(true);
  });

  it("resolves authenticated authority again before every queued entry", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A, NOTE, "cap-synthetic-first");
    const second = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note beta",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-second",
    });
    const resolveSession = vi
      .fn()
      .mockResolvedValueOnce({ principalId: PRINCIPAL_A, replayBinding: "binding-a" })
      .mockResolvedValueOnce({ principalId: PRINCIPAL_B, replayBinding: "binding-b" });
    const transport = vi.fn<ReplayTransport>(async (request) =>
      goodReceipt(request.text, request.idempotencyKey),
    );

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, resolveSession);

    expect(resolveSession).toHaveBeenCalledTimes(2);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(summary).toMatchObject({ replayed: 1, needsReauth: 1, stoppedForReauth: true });
    expect(await payloadPresent(db, entry.entryId)).toBe(false);
    expect(await payloadPresent(db, second.entryId)).toBe(true);
    expect((await queueSnapshot(db)).find((item) => item.entryId === second.entryId)?.state).toBe(
      "needs_reauth",
    );
  });
});

describe("control 4 — a stale session fails closed", () => {
  it.each([401, 403])("moves the entry to needs_reauth on %i and stops the pass", async (status) => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A, NOTE, "cap-synthetic-first");
    const second = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note beta",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-second",
    });
    const transport = vi.fn<ReplayTransport>(async () => ({
      status,
      body: { error: { errorClass: "authentication", code: "unauthenticated" } },
    }));

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));

    expect(summary).toMatchObject({ needsReauth: 1, replayed: 0, stoppedForReauth: true });
    // The pass stopped: the second entry was never attempted.
    expect(transport).toHaveBeenCalledTimes(1);

    const entries = await queueSnapshot(db);
    expect(entries.find((item) => item.entryId === entry.entryId)!.state).toBe("needs_reauth");
    expect(entries.find((item) => item.entryId === second.entryId)!.state).toBe("pending");
    // Nothing was dropped.
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
    expect(await payloadPresent(db, second.entryId)).toBe(true);
  });

  it("stops after the BFF detects a check/send session transition", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A, NOTE, "cap-synthetic-first");
    const second = await enqueueCapture(db, key, {
      principalId: PRINCIPAL_A,
      text: "synthetic note beta",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-second",
    });
    const transport = vi.fn<ReplayTransport>(async () => ({
      status: 409,
      body: {
        error: {
          errorClass: "authentication",
          code: "replay_session_changed",
          message: "the authenticated session changed before replay admission",
        },
      },
    }));

    const summary = await replayQueuedCaptures(
      db,
      PRINCIPAL_A,
      key,
      transport,
      sessionFor(PRINCIPAL_A),
    );

    expect(transport).toHaveBeenCalledTimes(1);
    expect(summary).toMatchObject({ needsReauth: 1, failed: 0, stoppedForReauth: true });
    const entries = await queueSnapshot(db);
    expect(entries.find((item) => item.entryId === entry.entryId)?.state).toBe("needs_reauth");
    expect(entries.find((item) => item.entryId === second.entryId)?.state).toBe("pending");
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
    expect(await payloadPresent(db, second.entryId)).toBe(true);
  });

  it("does not treat an unrelated 409 as an authentication transition", async () => {
    const { db, key } = await queueOne(PRINCIPAL_A);
    const transport = vi.fn<ReplayTransport>(async () => ({
      status: 409,
      body: { error: { errorClass: "conflict", code: "some_other_conflict" } },
    }));

    const summary = await replayQueuedCaptures(
      db,
      PRINCIPAL_A,
      key,
      transport,
      sessionFor(PRINCIPAL_A),
    );

    expect(summary).toMatchObject({ needsReauth: 0, failed: 1, stoppedForReauth: false });
    expect((await queueSnapshot(db))[0].state).toBe("pending");
  });

  it("never replays without a session — the transport is the only way out and it is authenticated", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A);
    const transport = vi.fn<ReplayTransport>(async () => ({ status: 401, body: null }));
    await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));
    // A second pass may try again — that is one attempt per pass, driven by a
    // mount or an `online` event, not a loop — and it still refuses to delete.
    await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));
    expect(transport).toHaveBeenCalledTimes(2);
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
  });
});

describe("control 5 — the local payload is deleted only for a verified receipt", () => {
  it("deletes when all four checks pass", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A);
    const transport: ReplayTransport = async (req) => goodReceipt(req.text, req.idempotencyKey);

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));

    expect(summary).toMatchObject({ replayed: 1, failed: 0 });
    expect(await payloadPresent(db, entry.entryId)).toBe(false);
    expect((await queueSnapshot(db))[0].state).toBe("replayed");
  });

  const malformed: readonly (readonly [string, (good: ReplayResponse) => ReplayResponse])[] = [
    [
      "the synthetic provider's acknowledgement",
      () => ({
        status: 200,
        body: {
          shape: "synthetic",
          receiptId: "rcpt-synthetic-0002",
          created: true,
          status: "acknowledged_not_persisted",
        },
      }),
    ],
    [
      "an HTTP 200 carrying an error envelope",
      () => ({
        status: 200,
        body: { error: { errorClass: "internal", code: "boom", message: "synthetic failure" } },
      }),
    ],
    ["a body that is not an object", () => ({ status: 200, body: "ok" })],
    ["a null body", () => ({ status: 200, body: null })],
    [
      "the right status but the wrong shape",
      (good) => ({
        status: 200,
        body: { ...(good.body as object), shape: "synthetic" },
      }),
    ],
    [
      "a receipt with no receiptId",
      (good) => {
        const body = good.body as { receipt: Record<string, unknown> };
        return {
          status: 200,
          body: { ...body, receipt: { ...body.receipt, receiptId: "" } },
        };
      },
    ],
    [
      "a receipt with no receipt object at all",
      (good) => {
        const body = { ...(good.body as Record<string, unknown>) };
        delete body.receipt;
        return { status: 200, body };
      },
    ],
    [
      "a receipt for a different idempotency key",
      (good) => {
        const body = good.body as { receipt: Record<string, unknown> };
        return {
          status: 200,
          body: { ...body, receipt: { ...body.receipt, idempotencyKey: "cap-synthetic-other" } },
        };
      },
    ],
    [
      "a receipt whose digest is not this note's",
      (good) => {
        const body = good.body as { receipt: Record<string, unknown> };
        return {
          status: 200,
          body: {
            ...body,
            receipt: { ...body.receipt, contentSha256: "0".repeat(64) },
          },
        };
      },
    ],
    [
      "a receipt carrying no digest at all",
      (good) => {
        const body = good.body as { receipt: Record<string, unknown> };
        const receipt = { ...body.receipt };
        delete receipt.contentSha256;
        return { status: 200, body: { ...body, receipt } };
      },
    ],
    [
      "a receipt carrying no Principal binding",
      (good) => {
        const body = good.body as { receipt: Record<string, unknown> };
        const receipt = { ...body.receipt };
        delete receipt.principalId;
        return { status: 200, body: { ...body, receipt } };
      },
    ],
    [
      "a receipt bound to a different Principal",
      (good) => {
        const body = good.body as { receipt: Record<string, unknown> };
        return {
          status: 200,
          body: { ...body, receipt: { ...body.receipt, principalId: PRINCIPAL_B } },
        };
      },
    ],
  ];

  it.each(malformed)("leaves the payload intact for %s", async (_label, mangle) => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A);
    const transport: ReplayTransport = async (req) =>
      mangle(await goodReceipt(req.text, req.idempotencyKey));

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));

    expect(summary.replayed).toBe(0);
    expect(summary.failed).toBe(1);
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
    expect((await queueSnapshot(db))[0].state).toBe("pending");
  });

  it("leaves the payload intact when the transport throws", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A);
    const transport: ReplayTransport = async () => {
      throw new TypeError("synthetic network failure");
    };
    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));
    expect(summary).toMatchObject({ replayed: 0, failed: 1 });
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
  });

  it("leaves the payload intact on a 5xx", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A);
    const transport: ReplayTransport = async () => ({ status: 503, body: null });
    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));
    expect(summary).toMatchObject({ replayed: 0, failed: 1 });
    expect(await payloadPresent(db, entry.entryId)).toBe(true);
  });

  it("names the failed check rather than collapsing them", async () => {
    const digest = await contentSha256(NOTE);
    expect(verifyReceipt({ shape: "synthetic" }, { idempotencyKey: "k", contentSha256: digest, principalId: PRINCIPAL_A })).toEqual({
      ok: false,
      reason: "not_backend_shape",
    });
    expect(
      verifyReceipt(
        { shape: "backend", status: "acknowledged_not_persisted" },
        { idempotencyKey: "k", contentSha256: digest, principalId: PRINCIPAL_A },
      ),
    ).toEqual({ ok: false, reason: "not_persisted" });
    expect(
      verifyReceipt(
        { shape: "backend", status: "persisted", receipt: { receiptId: "r", idempotencyKey: "other" } },
        { idempotencyKey: "k", contentSha256: digest, principalId: PRINCIPAL_A },
      ),
    ).toEqual({ ok: false, reason: "idempotency_key_mismatch" });
    expect(
      verifyReceipt(
        {
          shape: "backend",
          status: "persisted",
          receipt: { receiptId: "r", idempotencyKey: "k", contentSha256: "0".repeat(64) },
        },
        { idempotencyKey: "k", contentSha256: digest, principalId: PRINCIPAL_A },
      ),
    ).toEqual({ ok: false, reason: "digest_mismatch" });
    expect(
      verifyReceipt(
        {
          shape: "backend",
          status: "persisted",
          receipt: {
            receiptId: "r",
            idempotencyKey: "k",
            contentSha256: digest,
            principalId: PRINCIPAL_B,
          },
        },
        { idempotencyKey: "k", contentSha256: digest, principalId: PRINCIPAL_A },
      ),
    ).toEqual({ ok: false, reason: "principal_mismatch" });
  });
});

describe("control 7 — the idempotency key is minted once and never regenerated", () => {
  it("sends the same key on every attempt", async () => {
    const { db, key } = await queueOne(PRINCIPAL_A, NOTE, "cap-synthetic-stable");
    const seen: string[] = [];
    const failing: ReplayTransport = async (req) => {
      seen.push(req.idempotencyKey);
      return { status: 503, body: null };
    };
    await replayQueuedCaptures(db, PRINCIPAL_A, key, failing, sessionFor(PRINCIPAL_A));
    await replayQueuedCaptures(db, PRINCIPAL_A, key, failing, sessionFor(PRINCIPAL_A));
    const succeeding: ReplayTransport = async (req) => {
      seen.push(req.idempotencyKey);
      return goodReceipt(req.text, req.idempotencyKey);
    };
    await replayQueuedCaptures(db, PRINCIPAL_A, key, succeeding, sessionFor(PRINCIPAL_A));

    expect(seen).toEqual([
      "cap-synthetic-stable",
      "cap-synthetic-stable",
      "cap-synthetic-stable",
    ]);
  });

  it("treats a replay that returns created:false as a success and deletes the payload", async () => {
    const { db, key, entry } = await queueOne(PRINCIPAL_A, NOTE, "cap-synthetic-replayed");
    const transport: ReplayTransport = async (req) =>
      goodReceipt(req.text, req.idempotencyKey, false);

    const summary = await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));

    expect(summary).toMatchObject({ replayed: 1 });
    expect(await payloadPresent(db, entry.entryId)).toBe(false);
  });

  it("does not resend an entry whose payload a verified receipt already removed", async () => {
    const { db, key } = await queueOne(PRINCIPAL_A, NOTE, "cap-synthetic-once");
    const transport = vi.fn<ReplayTransport>(async (req) =>
      goodReceipt(req.text, req.idempotencyKey),
    );
    await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));
    await replayQueuedCaptures(db, PRINCIPAL_A, key, transport, sessionFor(PRINCIPAL_A));
    expect(transport).toHaveBeenCalledTimes(1);
  });
});
