// @vitest-environment node
/** WP07: the browser Reports client — paths, decoding, refusals, A2 conflicts, idempotency. */
import { afterEach, describe, expect, it, vi } from "vitest";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import standalone from "@/lib/api/decode/fixtures/python/reports.standalone.json";
import {
  CONFLICT_MESSAGE,
  LIFECYCLE_STALE_MESSAGE,
  STALE_MESSAGE,
  abortReportTransfer,
  catalogPath,
  changeReportLifecycle,
  classifyConflict,
  fetchReport,
  fetchReportCatalog,
  finalizeReportTransfer,
  refusal,
  reportIntent,
  updateReport,
} from "./client";

const REPORT = "grpt_aaaaaaaa11111111";
const CURRENT = { headVersionNumber: 4, headVersionId: "grver_aaaaaaaa11111111", lifecycleState: "active", lifecycleRevision: 2, held: false };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const backend = (result: unknown) => json({ shape: "backend", ...(result as object), disclosure: {} });
const refused = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  json({ state: "refused", error: { errorClass: code === "conflict" ? "conflict" : "invalid_request", code, message: "safe_field" }, disclosure: {}, ...extra }, status);

function stub(...answers: (Response | Error)[]) {
  const fetchMock = vi.fn<typeof fetch>();
  for (const answer of answers) {
    fetchMock.mockImplementationOnce(async () => {
      if (answer instanceof Error) throw answer;
      return answer;
    });
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("catalog reads", () => {
  it("always sends the plane explicitly, both values", () => {
    expect(catalogPath({ plane: "standalone" })).toBe("/api/reports?plane=standalone");
    expect(catalogPath({ plane: "all" })).toBe("/api/reports?plane=all");
  });
  it("repeats array filters and drops blank text", () => {
    expect(catalogPath({ plane: "all", query: "  ", type: " note ", tags: ["a", "b"], lifecycleStates: ["archived"], cursor: "c" }))
      .toBe("/api/reports?plane=all&type=note&tags=a&tags=b&lifecycleStates=archived&cursor=c");
  });
  it("decodes a standalone page and a search page", async () => {
    stub(backend(standalone["reports.list.all"]), backend(standalone["reports.search.all"]));
    const list = await fetchReportCatalog({ plane: "all" });
    expect(list.ok && list.value.items.map((item) => item.plane)).toEqual(["standalone", "intelligence"]);
    const search = await fetchReportCatalog({ plane: "all", query: "synthetic" });
    expect(search.ok).toBe(true);
  });
  it("refuses an answer that is not the promised contract", async () => {
    stub(backend(fixtures["reports.list"]));
    expect(await fetchReportCatalog({ plane: "standalone" })).toMatchObject({ ok: false, status: 503, code: "upstream_contract_invalid" });
  });
  it("does not retry a GET", async () => {
    const fetchMock = stub(json({}, 503), json({}, 503));
    expect((await fetchReport(REPORT)).ok).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("mutations", () => {
  it("keeps the refusal's status, class, code and message, and a 409's current", async () => {
    stub(refused(409, "conflict", { current: CURRENT }));
    const outcome = await updateReport(REPORT, { expectedVersion: 3, patch: { title: "T" }, changeReason: "r", idempotencyKey: "k" });
    expect(outcome).toEqual({ ok: false, status: 409, errorClass: "conflict", code: "conflict", message: "safe_field", current: CURRENT });
  });
  it("drops a malformed current", async () => {
    stub(refused(409, "conflict", { current: { ...CURRENT, held: "yes" } }));
    const outcome = await updateReport(REPORT, { expectedVersion: 3, patch: {}, changeReason: "r", idempotencyKey: "k" });
    expect(outcome.ok === false && outcome.current).toBeUndefined();
  });
  it("retries an ambiguous failure once with the identical body (the same key)", async () => {
    const fetchMock = stub(new TypeError("network"), backend(fixtures["reports.archive"]));
    const outcome = await changeReportLifecycle(REPORT, "archive", { expectedLifecycleRevision: 0, idempotencyKey: "intent-1" });
    expect(outcome.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [first, second] = fetchMock.mock.calls.map(([, init]) => init!.body);
    expect(first).toBe(second);
    expect(JSON.parse(String(first))).toEqual({ expectedLifecycleRevision: 0, idempotencyKey: "intent-1" });
    expect(String(fetchMock.mock.calls[0]![0])).toBe(`/api/reports/${REPORT}/archive`);
  });
  it("never retries a definitive refusal or a conflict", async () => {
    const fetchMock = stub(refused(409, "conflict"), refused(409, "conflict"));
    await changeReportLifecycle(REPORT, "delete", { expectedLifecycleRevision: 0, idempotencyKey: "k", reason: " tidy " });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetchMock.mock.calls[0]![1]!.body))).toEqual({ expectedLifecycleRevision: 0, idempotencyKey: "k", reason: "tidy" });
  });
  it("R1-3: never retries a finalize (its token is minted once), lost or 503", async () => {
    for (const lost of [new TypeError("network"), refused(503, "unavailable")]) {
      const fetchMock = stub(lost, backend(fixtures["reports.transfer.finalize"]));
      const outcome = await finalizeReportTransfer("grxfr_aaaaaaaa11111111");
      expect(outcome.ok).toBe(false);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  });
  it("still retries the other transfer POSTs (abort) once on a lost answer", async () => {
    const fetchMock = stub(new TypeError("network"), backend(fixtures["reports.transfer.abort"]));
    expect((await abortReportTransfer("grxfr_aaaaaaaa11111111")).ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("decodes the lifecycle answer of the capability that was asked", async () => {
    // A contract mismatch is 503: the mutation may have applied, so it is sent once more, same body.
    const fetchMock = stub(backend(fixtures["reports.archive"]), backend(fixtures["reports.archive"]));
    expect(await changeReportLifecycle(REPORT, "restore", { expectedLifecycleRevision: 0, idempotencyKey: "k" }))
      .toMatchObject({ ok: false, code: "upstream_contract_invalid" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("reportIntent", () => {
  it("keeps one key across ambiguous answers and rotates after a definitive one or a new payload", () => {
    const intent = reportIntent("report-archive");
    const first = intent.keyFor({ revision: 0 });
    expect(first).toMatch(/^report-archive-/);
    intent.settle(refusal(503, "unavailable", "unavailable", "x"));
    expect(intent.keyFor({ revision: 0 })).toBe(first);
    intent.settle(refusal(0, "unavailable", "transport_failed", "x"));
    expect(intent.keyFor({ revision: 0 })).toBe(first);
    intent.settle(refusal(409, "conflict", "conflict", "x"));
    const second = intent.keyFor({ revision: 0 });
    expect(second).not.toBe(first);
    expect(intent.keyFor({ revision: 1 })).not.toBe(second);
  });
});

describe("classifyConflict (Amendment A2)", () => {
  const conflict = (current?: typeof CURRENT) => refusal(409, "conflict", "conflict", "x", current);
  it("is stale when the head version differs from the submitted expected version", () => {
    expect(classifyConflict(conflict(CURRENT), { expectedVersion: 3 })).toEqual({ kind: "stale", current: CURRENT });
    expect(STALE_MESSAGE(4)).toBe("This report changed since you opened it (now version 4).");
  });
  it("is the generic conflict when the version is the same, or there is no current", () => {
    expect(classifyConflict(conflict(CURRENT), { expectedVersion: 4 })).toEqual({ kind: "conflict" });
    expect(classifyConflict(conflict(), { expectedVersion: 3 })).toEqual({ kind: "conflict" });
    expect(CONFLICT_MESSAGE).toMatch(/conflicted with an earlier one/);
  });
  it("judges lifecycle actions by the lifecycle revision, in lifecycle words", () => {
    expect(classifyConflict(conflict(CURRENT), { expectedLifecycleRevision: 1 }).kind).toBe("stale");
    expect(LIFECYCLE_STALE_MESSAGE("trashed")).toBe("This report's state changed since you opened it (now in Trash).");
    expect(LIFECYCLE_STALE_MESSAGE("archived")).toBe("This report's state changed since you opened it (now archived).");
    expect(LIFECYCLE_STALE_MESSAGE("constructor")).toBe("This report's state changed since you opened it (now constructor).");
    expect(classifyConflict(conflict(CURRENT), { expectedLifecycleRevision: 2 }).kind).toBe("conflict");
  });
  it("is none for anything but a 409", () => {
    expect(classifyConflict(refusal(400, "invalid_request", "invalid_request", "x"), { expectedVersion: 1 })).toEqual({ kind: "none" });
    expect(classifyConflict({ ok: true, value: 1 }, { expectedVersion: 1 })).toEqual({ kind: "none" });
  });
});
