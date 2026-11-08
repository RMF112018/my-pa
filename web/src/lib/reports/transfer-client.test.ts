// @vitest-environment node
/**
 * WP07 U6: the browser transfer orchestration against a fake BFF (`fetch`).
 *
 * The fake answers each /api/reports transfer route the way the routes answer
 * (`{shape:"backend", ...result, disclosure}`), keeps the staged chunks, and
 * uses a tiny `chunk_byte_limit` so every chunk boundary is reachable with
 * synthetic strings of a few bytes.
 */
import { createHash } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  INLINE_REQUEST_MAX_BYTES,
  MAX_STAGED_BYTES,
  contentFromDecoded,
  needsTransfer,
  readFullContent,
  UPLOAD_STATE_UNKNOWN_MESSAGE,
  stagedBytes,
  transferBinding,
  uploadViaTransfer,
  withTransferredContent,
} from "./transfer-client";
import { publishReport, updateReport, type ReportOutcome, type TransferReportContent } from "./client";

const SESSION = "grxfr_aaaaaaaa11111111";
const REPORT = "grpt_aaaaaaaa11111111";
const TOKEN = `grxtk_${"0123456789abcdef".repeat(4)}`;
const EXPIRES = "2026-08-09T13:00:00.000Z";
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");
const enc = (text: string) => new TextEncoder().encode(text);

interface Call { readonly url: string; readonly method: string; readonly body: Record<string, unknown> | undefined }

const backend = (result: Record<string, unknown>, status = 200) =>
  new Response(JSON.stringify(status === 200 ? { shape: "backend", ...result, disclosure: {} } : result), {
    status, headers: { "content-type": "application/json" },
  });
const refusedAnswer = (status: number, code: string, errorClass = "invalid_request") =>
  backend({ state: "refused", error: { errorClass, code, message: "safe_field" }, disclosure: {} }, status);

/** A fake transfer BFF: begin -> append -> finalize, with optional injected failures. */
function fakeTransfers(
  limit: number,
  failures: { append?: number; appendStatus?: number; finalize?: boolean; finalizeLost?: "network" | 503 } = {},
) {
  const calls: Call[] = [];
  let declared = { byteCount: 0, sha256: "", format: "text" };
  const chunks: Uint8Array[] = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ url, method: init?.method ?? "GET", body });
    if (url === "/api/reports/transfers") {
      declared = { byteCount: body!.byteCount as number, sha256: body!.sha256 as string, format: body!.format as string };
      return backend({
        session_id: SESSION, state: "open", format: declared.format, encoding: "identity",
        declared_byte_count: declared.byteCount, declared_sha256: declared.sha256, chunk_byte_limit: limit,
        chunk_count: Math.ceil(declared.byteCount / limit), expires_at: EXPIRES, replayed: false,
      });
    }
    if (url.endsWith("/append")) {
      const sequence = body!.sequence as number;
      if (failures.append === sequence) return refusedAnswer(failures.appendStatus ?? 400, "invalid_request");
      const bytes = Uint8Array.from(Buffer.from(body!.chunk as string, "base64"));
      chunks[sequence] = bytes;
      const received = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
      const complete = received === declared.byteCount;
      return backend({
        session_id: SESSION, sequence, byte_offset: sequence * limit, byte_count: bytes.byteLength,
        chunk_sha256: sha(bytes), received_byte_count: received, declared_byte_count: declared.byteCount,
        complete, next_sequence: complete ? null : sequence + 1, expires_at: EXPIRES, replayed: false,
      });
    }
    if (url.endsWith("/finalize")) {
      if (failures.finalize) return refusedAnswer(409, "conflict", "conflict");
      if (failures.finalizeLost === "network") throw new TypeError("network");
      if (failures.finalizeLost === 503) return refusedAnswer(503, "unavailable", "unavailable");
      return backend({
        session_id: SESSION, state: "finalized", content_token: TOKEN, expires_at: EXPIRES,
        byte_count: declared.byteCount, sha256: declared.sha256, format: declared.format, encoding: "identity",
        decoded_byte_count: declared.byteCount, decoded_sha256: declared.sha256,
      });
    }
    if (url.endsWith("/abort")) return backend({ session_id: SESSION, state: "aborted", replayed: false });
    throw new Error("unexpected route");
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, chunks, fetchMock };
}

const consoleSpies: ReturnType<typeof vi.spyOn>[] = [];
beforeEach(() => {
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    consoleSpies.push(vi.spyOn(console, method).mockImplementation(() => undefined));
  }
});
/** Only the publish/update submit may carry a content token, and only in its body. */
const TOKEN_BODY_ROUTE = /^\/api\/reports(\/grpt_[^/]+\/update)?$/;

/** Every fetch call any test made: no token in a URL or header; in a body only on the submit. */
function tokenLeaks(fetchMock: unknown): string[] {
  if (!vi.isMockFunction(fetchMock)) return [];
  return (fetchMock.mock.calls as Parameters<typeof fetch>[]).flatMap(([input, init]) => {
    const url = String(input);
    const leaks: string[] = [];
    if (url.includes("grxtk_")) leaks.push(`url ${url}`);
    new Headers(init?.headers).forEach((value, name) => {
      if (value.includes("grxtk_") || name.includes("grxtk_")) leaks.push(`header ${name} on ${url}`);
    });
    if (String(init?.body ?? "").includes("grxtk_") && !TOKEN_BODY_ROUTE.test(url)) leaks.push(`body on ${url}`);
    return leaks;
  });
}

afterEach(() => {
  for (const spy of consoleSpies.splice(0)) {
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  }
  expect(tokenLeaks(globalThis.fetch)).toEqual([]);
  vi.unstubAllGlobals();
});

function concat(chunks: Uint8Array[]): Uint8Array {
  return Uint8Array.from(chunks.flatMap((chunk) => Array.from(chunk)));
}

describe("stagedBytes (WP06 T3 identity rules)", () => {
  it("is the UTF-8 body for markdown and text", () => {
    expect(Array.from(stagedBytes("markdown", "# Hé"))).toEqual(Array.from(enc("# Hé")));
    expect(Array.from(stagedBytes("text", "plain"))).toEqual(Array.from(enc("plain")));
  });
  it("is the JSON text of the data for json, and of {body, data} for mixed", () => {
    expect(new TextDecoder().decode(stagedBytes("json", undefined, { b: 1, a: [true] }))).toBe('{"b":1,"a":[true]}');
    expect(new TextDecoder().decode(stagedBytes("mixed", "x", { k: "v" }))).toBe('{"body":"x","data":{"k":"v"}}');
  });
  it("refuses a value its format does not carry", () => {
    expect(() => stagedBytes("text")).toThrow(TypeError);
    expect(() => stagedBytes("json", undefined, undefined)).toThrow(TypeError);
    expect(() => stagedBytes("mixed", undefined, { k: 1 })).toThrow(TypeError);
  });
  it("round-trips decoded bytes back into body and data", () => {
    expect(contentFromDecoded("json", enc('{"a":1}'))).toEqual({ data: { a: 1 } });
    expect(contentFromDecoded("mixed", enc('{"body":"b","data":[1]}'))).toEqual({ body: "b", data: [1] });
    expect(contentFromDecoded("mixed", enc('{"data":[1]}'))).toBeNull();
    expect(contentFromDecoded("text", Uint8Array.from([0xff]))).toBeNull();
  });
});

describe("needsTransfer (U6: inline JSON UTF-8 length > 512 KiB)", () => {
  it("is false at the bound and true one byte above it", () => {
    const overhead = JSON.stringify({ body: "" }).length;
    expect(needsTransfer({ body: "x".repeat(INLINE_REQUEST_MAX_BYTES - overhead) })).toBe(false);
    expect(needsTransfer({ body: "x".repeat(INLINE_REQUEST_MAX_BYTES - overhead + 1) })).toBe(true);
  });
  it("counts UTF-8 bytes, not UTF-16 units", () => {
    const overhead = JSON.stringify({ body: "" }).length;
    expect(needsTransfer({ body: "é".repeat(Math.ceil((INLINE_REQUEST_MAX_BYTES - overhead + 1) / 2)) })).toBe(true);
  });
});

describe("uploadViaTransfer", () => {
  const upload = (text: string, key = "xfer-key-1") =>
    uploadViaTransfer({ format: "text", staged: enc(text), idempotencyKey: key });

  it("refuses empty content before any request", async () => {
    const { fetchMock } = fakeTransfers(4);
    const outcome = await upload("");
    expect(outcome).toMatchObject({ ok: false, status: 0, code: "content_empty" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends one byte as one chunk", async () => {
    const { calls, chunks } = fakeTransfers(4);
    const outcome = await upload("a");
    expect(outcome).toEqual({ ok: true, value: { sessionId: SESSION, contentToken: TOKEN } });
    expect(calls.map((call) => call.url)).toEqual([
      "/api/reports/transfers", `/api/reports/transfers/${SESSION}/append`, `/api/reports/transfers/${SESSION}/finalize`,
    ]);
    expect(calls[0]!.body).toEqual({ format: "text", byteCount: 1, sha256: sha(enc("a")), idempotencyKey: "xfer-key-1" });
    expect(chunks.map((chunk) => chunk.byteLength)).toEqual([1]);
  });

  it("sends an exact multiple of the limit as full chunks", async () => {
    const { calls, chunks } = fakeTransfers(4);
    expect((await upload("abcdefgh")).ok).toBe(true);
    expect(chunks.map((chunk) => chunk.byteLength)).toEqual([4, 4]);
    const appends = calls.filter((call) => call.url.endsWith("/append"));
    expect(appends.map((call) => call.body!.sequence)).toEqual([0, 1]);
    expect(appends.map((call) => call.body!.chunkSha256)).toEqual([sha(enc("abcd")), sha(enc("efgh"))]);
  });

  it("sends many chunks with a shorter last one, reassembling the staged bytes exactly", async () => {
    const { chunks } = fakeTransfers(4);
    const text = "héllo, wörld";
    expect((await upload(text)).ok).toBe(true);
    const sizes = chunks.map((chunk) => chunk.byteLength);
    expect(sizes.slice(0, -1).every((size) => size === 4)).toBe(true);
    expect(sizes.at(-1)).toBe(enc(text).byteLength % 4 || 4);
    expect(sizes.at(-1)).toBeLessThan(4);
    expect(Array.from(concat(chunks))).toEqual(Array.from(enc(text)));
  });

  it("refuses more than 16 MiB before begin (no request is sent)", async () => {
    const { fetchMock } = fakeTransfers(262_144);
    const outcome = await uploadViaTransfer({ format: "text", staged: new Uint8Array(MAX_STAGED_BYTES + 1), idempotencyKey: "k" });
    expect(outcome).toMatchObject({ ok: false, status: 0, code: "content_too_large" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts exactly 16 MiB in 64 full chunks", async () => {
    const { chunks } = fakeTransfers(262_144);
    const staged = new Uint8Array(MAX_STAGED_BYTES).fill(0x61);
    expect((await uploadViaTransfer({ format: "text", staged, idempotencyKey: "k" })).ok).toBe(true);
    expect(chunks).toHaveLength(64);
  });

  it("aborts after an append failure and answers the refusal", async () => {
    const { calls } = fakeTransfers(4, { append: 1 });
    const outcome = await upload("abcdefghij");
    expect(outcome).toMatchObject({ ok: false, status: 400, code: "invalid_request" });
    expect(calls.map((call) => call.url.split("/").at(-1))).toEqual(["transfers", "append", "append", "abort"]);
  });

  it("aborts after a finalize failure", async () => {
    const { calls } = fakeTransfers(4, { finalize: true });
    const outcome = await upload("abc");
    expect(outcome).toMatchObject({ ok: false, status: 409, code: "conflict" });
    expect(calls.map((call) => call.url.split("/").at(-1))).toEqual(["transfers", "append", "finalize", "abort"]);
  });

  it.each(["network", 503] as const)(
    "R1-3: sends finalize once; a lost answer (%s) is 'upload state unknown' and the session is aborted",
    async (lostAs) => {
      const { calls } = fakeTransfers(4, { finalizeLost: lostAs });
      const outcome = await upload("abc");
      expect(outcome).toEqual({
        ok: false, status: 0, errorClass: "unavailable", code: "transfer_state_unknown", message: UPLOAD_STATE_UNKNOWN_MESSAGE,
      });
      expect(calls.map((call) => call.url.split("/").at(-1))).toEqual(["transfers", "append", "finalize", "abort"]);
    },
  );

  it("retries an ambiguous append once with the identical body, then aborts", async () => {
    const { calls } = fakeTransfers(4, { append: 0, appendStatus: 503 });
    const outcome = await upload("ab");
    expect(outcome).toMatchObject({ ok: false, status: 503 });
    const appends = calls.filter((call) => call.url.endsWith("/append"));
    expect(appends).toHaveLength(2);
    expect(appends[0]!.body).toEqual(appends[1]!.body);
    expect(calls.at(-1)!.url.endsWith("/abort")).toBe(true);
  });

  it("reuses the same begin key when the begin answer was lost", async () => {
    const { fetchMock } = fakeTransfers(4);
    fetchMock.mockImplementationOnce(async () => { throw new TypeError("network"); });
    expect((await upload("abc", "intent-key")).ok).toBe(true);
    const begins = fetchMock.mock.calls.filter(([input]) => String(input) === "/api/reports/transfers");
    expect(begins).toHaveLength(2);
    expect(begins.map(([, init]) => JSON.parse(String(init!.body)).idempotencyKey)).toEqual(["intent-key", "intent-key"]);
    expect(begins[0]![1]!.body).toBe(begins[1]![1]!.body);
  });

  it("keeps the content token out of every URL and every console call", async () => {
    const { calls } = fakeTransfers(4);
    const use = vi.fn(async () => ({ ok: true as const, value: "published" }));
    const outcome = await withTransferredContent({ format: "text", staged: enc("abcdef"), idempotencyKey: "k" }, use);
    expect(outcome).toEqual({ ok: true, value: "published" });
    expect(use).toHaveBeenCalledWith({ transfer: { sessionId: SESSION, contentToken: TOKEN } });
    // The token is returned only to the one callback, never sent in a URL;
    // afterEach asserts no console method was called at all.
    expect(calls.every((call) => !call.url.includes("grxtk_"))).toBe(true);
    expect(JSON.stringify(outcome)).not.toContain("grxtk_");
  });
});

describe("withTransferredContent + publishReport", () => {
  it("publishes with {transfer:{sessionId, contentToken}} in the body, retrying with the same key", async () => {
    const { calls, fetchMock } = fakeTransfers(4);
    const transfers = fetchMock.getMockImplementation()!;
    const publishes: Call[] = [];
    let attempt = 0;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) !== "/api/reports") return transfers(input, init);
      publishes.push({ url: String(input), method: init!.method!, body: JSON.parse(String(init!.body)) });
      attempt += 1;
      if (attempt === 1) throw new TypeError("network");
      const { default: fixtures } = await import("@/lib/api/decode/fixtures/python/success.json");
      return backend(fixtures["reports.publish"] as Record<string, unknown>);
    });
    const outcome = await withTransferredContent({ format: "text", staged: enc("abcde"), idempotencyKey: "xfer" }, (content) =>
      publishReport({ title: "T", content, idempotencyKey: "publish-key" }));
    expect(outcome.ok).toBe(true);
    expect(publishes).toHaveLength(2);
    expect(publishes[0]!.body).toEqual(publishes[1]!.body);
    expect(publishes[0]!.body).toEqual({ title: "T", content: { transfer: { sessionId: SESSION, contentToken: TOKEN } }, idempotencyKey: "publish-key" });
    expect(calls.some((call) => call.url.endsWith("/abort"))).toBe(false);
  });

  it("aborts the session when the publish is refused", async () => {
    const { calls, fetchMock } = fakeTransfers(4);
    const transfers = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) =>
      String(input) === "/api/reports" ? refusedAnswer(400, "invalid_request") : transfers(input, init));
    const outcome = await withTransferredContent({ format: "text", staged: enc("abc"), idempotencyKey: "x" }, (content) =>
      publishReport({ title: "T", content, idempotencyKey: "p" }));
    expect(outcome).toMatchObject({ ok: false, status: 400 });
    expect(calls.at(-1)!.url).toBe(`/api/reports/transfers/${SESSION}/abort`);
    expect(calls.every((call) => !call.url.includes("grxtk_"))).toBe(true);
    expect(tokenLeaks(fetchMock)).toEqual([]);
  });
});

describe("R1-2: transferBinding keeps a transfer for the same resubmit while the answer is ambiguous", () => {
  type Submit = (content: TransferReportContent) => Promise<ReportOutcome<unknown>>;
  const request = (text: string) => ({ format: "text" as const, staged: enc(text), idempotencyKey: `xfer-${text}` });

  /** The transfer fake, with the publish/update routes answering `answer(n)` on their n-th call. */
  function withSubmit(answer: (n: number, url: string) => Response | Promise<Response>) {
    const fake = fakeTransfers(4);
    const transfers = fake.fetchMock.getMockImplementation()!;
    let submits = 0;
    fake.fetchMock.mockImplementation(async (input, init) =>
      TOKEN_BODY_ROUTE.test(String(input)) ? answer(++submits, String(input)) : transfers(input, init));
    return fake;
  }
  const lost = async (): Promise<Response> => { throw new TypeError("network"); };
  const ok = async (url = "/api/reports") => {
    const { default: fixtures } = await import("@/lib/api/decode/fixtures/python/success.json");
    return backend(fixtures[url.endsWith("/update") ? "reports.update" : "reports.publish"] as Record<string, unknown>);
  };
  const begins = (calls: Call[]) => calls.filter((call) => call.url === "/api/reports/transfers");
  const aborts = (calls: Call[]) => calls.filter((call) => call.url.endsWith("/abort"));
  /** The submit bodies (the wrapped fake does not record these in `calls`). */
  const submitted = (fetchMock: ReturnType<typeof fakeTransfers>["fetchMock"]) =>
    fetchMock.mock.calls
      .filter(([input]) => TOKEN_BODY_ROUTE.test(String(input)))
      .map(([, init]) => ({ body: JSON.parse(String(init!.body)) as Record<string, unknown> }));

  it.each([
    ["publish", ((content) => publishReport({ title: "T", content, idempotencyKey: "intent-key" })) as Submit],
    ["update", ((content) => updateReport(REPORT, {
      expectedVersion: 1, patch: { content }, changeReason: "r", idempotencyKey: "intent-key",
    })) as Submit],
  ])("%s: an ambiguous answer keeps the transfer; the resubmit reuses session, token and key with no begin", async (_name, submit) => {
    const { calls, fetchMock } = withSubmit((n, url) => (n <= 2 ? lost() : ok(url)));
    const binding = transferBinding();
    const first = await binding.submit("draft-1", request("abcde"), submit);
    expect(first).toMatchObject({ ok: false, code: "transport_failed" });
    expect(aborts(calls)).toEqual([]);
    expect((await binding.submit("draft-1", request("abcde"), submit)).ok).toBe(true);
    expect(begins(calls)).toHaveLength(1);
    const bodies = submitted(fetchMock).map((call) => call.body);
    expect(bodies).toHaveLength(3);
    for (const body of bodies) expect(body).toEqual(bodies[0]);
    expect(JSON.stringify(bodies[0])).toContain(`"sessionId":"${SESSION}"`);
    expect(JSON.stringify(bodies[0])).toContain(`"contentToken":"${TOKEN}"`);
    expect(bodies[0]!.idempotencyKey).toBe("intent-key");
    expect(aborts(calls)).toEqual([]);
  });

  it("a definitive refusal aborts; the next submit uploads afresh", async () => {
    const { calls } = withSubmit((n) => (n === 1 ? refusedAnswer(400, "invalid_request") : ok()));
    const binding = transferBinding();
    const submit: Submit = (content) => publishReport({ title: "T", content, idempotencyKey: "k" });
    expect(await binding.submit("d", request("abc"), submit)).toMatchObject({ ok: false, status: 400 });
    expect(aborts(calls).map((call) => call.url)).toEqual([`/api/reports/transfers/${SESSION}/abort`]);
    expect((await binding.submit("d", request("abc"), submit)).ok).toBe(true);
    expect(begins(calls)).toHaveLength(2);
  });

  it("a changed draft drops the held transfer (abort) and uploads afresh", async () => {
    const { calls } = withSubmit((n) => (n <= 2 ? lost() : ok()));
    const binding = transferBinding();
    const submit: Submit = (content) => publishReport({ title: "T", content, idempotencyKey: "k" });
    await binding.submit("draft-1", request("abc"), submit);
    expect((await binding.submit("draft-2", request("xyz"), submit)).ok).toBe(true);
    expect(aborts(calls)).toHaveLength(1);
    expect(begins(calls)).toHaveLength(2);
  });

  it("release aborts a held transfer once, and a success holds nothing", async () => {
    const { calls } = withSubmit((n) => (n <= 2 ? lost() : ok()));
    const binding = transferBinding();
    const submit: Submit = (content) => publishReport({ title: "T", content, idempotencyKey: "k" });
    await binding.submit("d", request("abc"), submit);
    await binding.release();
    await binding.release();
    expect(aborts(calls)).toHaveLength(1);
    expect((await binding.submit("d", request("abc"), submit)).ok).toBe(true);
    await binding.release();
    expect(aborts(calls)).toHaveLength(1);
  });
});

describe("readFullContent", () => {
  const POINTER_TEXT = "synthetic full body, read in ranges";

  function fakeContent(text: string, options: { length?: number; corrupt?: number; partSha?: string } = {}) {
    const bytes = enc(text);
    const length = options.length ?? 8;
    const urls: string[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      urls.push(url);
      const query = new URL(url, "http://localhost").searchParams;
      const offset = Number(query.get("offset"));
      const slice = bytes.subarray(offset, Math.min(bytes.byteLength, offset + length));
      const sent = options.corrupt === offset ? Uint8Array.from(slice, (byte, index) => (index === 0 ? byte ^ 1 : byte)) : slice;
      const end = offset + slice.byteLength;
      return backend({
        plane: "standalone", report_id: REPORT, version_id: "grver_aaaaaaaa11111111", version_number: 2,
        part: "decoded", offset, byte_count: sent.byteLength, chunk: Buffer.from(sent).toString("base64"),
        chunk_sha256: sha(slice), total_byte_count: bytes.byteLength, part_sha256: options.partSha ?? sha(bytes),
        eof: end === bytes.byteLength, next_offset: end === bytes.byteLength ? null : end,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    return { bytes, urls };
  }

  it("reads every range sequentially and verifies the whole", async () => {
    const { bytes, urls } = fakeContent(POINTER_TEXT);
    const outcome = await readFullContent(REPORT, 2, { part: "decoded", byte_count: bytes.byteLength, sha256: sha(bytes) }, { includeWithdrawn: true });
    expect(outcome.ok).toBe(true);
    expect(new TextDecoder().decode(outcome.ok ? outcome.value : new Uint8Array())).toBe(POINTER_TEXT);
    expect(urls.map((url) => new URL(url, "http://localhost").searchParams.get("offset"))).toEqual(["0", "8", "16", "24", "32"]);
    expect(urls[0]).toBe(`/api/reports/${REPORT}/content?versionNumber=2&offset=0&part=decoded&includeWithdrawn=true`);
  });

  it("refuses a chunk whose digest does not match, returning nothing", async () => {
    const { bytes } = fakeContent(POINTER_TEXT, { corrupt: 8 });
    const outcome = await readFullContent(REPORT, 2, { part: "decoded", byte_count: bytes.byteLength, sha256: sha(bytes) });
    expect(outcome).toMatchObject({ ok: false, code: "transfer_mismatch" });
    expect("value" in outcome).toBe(false);
  });

  it("refuses when the whole does not match the pointer's sha256", async () => {
    const { bytes } = fakeContent(POINTER_TEXT, { partSha: "c".repeat(64) });
    const outcome = await readFullContent(REPORT, 2, { part: "decoded", byte_count: bytes.byteLength, sha256: "c".repeat(64) });
    expect(outcome).toMatchObject({ ok: false, code: "transfer_mismatch" });
  });

  it("refuses a part whose size differs from the pointer", async () => {
    const { bytes } = fakeContent(POINTER_TEXT);
    const outcome = await readFullContent(REPORT, 2, { part: "decoded", byte_count: bytes.byteLength + 1, sha256: sha(bytes) });
    expect(outcome).toMatchObject({ ok: false, code: "transfer_mismatch" });
  });
});
