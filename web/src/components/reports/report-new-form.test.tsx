/**
 * WP07 U6/U7: the draft model and `/reports/new` against a stubbed BFF
 * (`fetch`): the inline publish request shape, the transfer path above
 * 512 KiB (begin -> append* -> finalize -> publish with the transfer ref), a
 * JSON parse error blocking submit, double-submit prevention, refusal words,
 * and the local file picker reading text only.
 *
 * jsdom's ArrayBuffer is not Node's, so WebCrypto's `digest` is delegated to
 * Node's SHA-256 over a copy of the same bytes (as report-view.test.tsx does).
 */
import { createHash } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";
import { MAX_STAGED_BYTES } from "@/lib/reports/transfer-client";
import { ReportNewForm } from "./report-new-form";
import {
  EMPTY_DRAFT,
  FORM_MESSAGES,
  buildPatch,
  contentOf,
  isNoChange,
  readTextFile,
  splitTerms,
  validateDraft,
  type ReportDraft,
} from "./report-form";

type Json = Record<string, unknown>;
const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push, refresh: vi.fn() }) }));

const SESSION = "grxfr_aaaaaaaa11111111";
const TOKEN = `grxtk_${"0123456789abcdef".repeat(4)}`;
const EXPIRES = "2026-08-09T13:00:00.000Z";
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

const backend = (result: unknown) => Response.json({ shape: "backend", ...(result as Json), disclosure: {} });
const refusedAnswer = (status: number, code: string, errorClass = "invalid_request") =>
  Response.json({ state: "refused", error: { errorClass, code, message: "safe_field" }, disclosure: {} }, { status });
const published = () => structuredClone(fixtures["reports.publish"]) as Json;

interface Call { readonly path: string; readonly method: string; readonly body?: Json }
function stub(answer: (path: string, body?: Json) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Json) : undefined;
    calls.push({ path, method: init?.method ?? "GET", ...(body ? { body } : {}) });
    return answer(path, body);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

/** A fake transfer BFF (begin/append/finalize/abort) plus a publish answer. */
function transferBff(publish: (body: Json) => Response = () => backend(published())) {
  const limit = 262_144;
  let declared = { byteCount: 0, sha256: "", format: "text" };
  const chunks: Uint8Array[] = [];
  const calls = stub((path, body) => {
    if (path === "/api/reports/transfers") {
      declared = { byteCount: body!.byteCount as number, sha256: body!.sha256 as string, format: body!.format as string };
      return backend({
        session_id: SESSION, state: "open", format: declared.format, encoding: "identity",
        declared_byte_count: declared.byteCount, declared_sha256: declared.sha256, chunk_byte_limit: limit,
        chunk_count: Math.ceil(declared.byteCount / limit), expires_at: EXPIRES, replayed: false,
      });
    }
    if (path.endsWith("/append")) {
      const sequence = body!.sequence as number;
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
    if (path.endsWith("/finalize")) {
      return backend({
        session_id: SESSION, state: "finalized", content_token: TOKEN, expires_at: EXPIRES,
        byte_count: declared.byteCount, sha256: declared.sha256, format: declared.format, encoding: "identity",
        decoded_byte_count: declared.byteCount, decoded_sha256: declared.sha256,
      });
    }
    if (path.endsWith("/abort")) return backend({ session_id: SESSION, state: "aborted", replayed: false });
    if (path === "/api/reports") return publish(body!);
    throw new Error("unexpected route");
  });
  return { calls, chunks };
}

function renderForm() {
  return render(<MutationFeedbackProvider><ReportNewForm /></MutationFeedbackProvider>);
}
const posts = (calls: readonly Call[]) => calls.filter((call) => call.method === "POST");

beforeEach(() => {
  nav.push.mockReset();
  vi.spyOn(globalThis.crypto.subtle, "digest").mockImplementation(async (_algorithm, data) => {
    const bytes = Buffer.from(new Uint8Array(data as ArrayBuffer));
    return Uint8Array.from(createHash("sha256").update(bytes).digest()).buffer;
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the draft model", () => {
  const draft = (patch: Partial<ReportDraft>): ReportDraft => ({ ...EMPTY_DRAFT, title: "T", ...patch });

  it("splits comma-separated terms", () => {
    expect(splitTerms(" a, b ,, c ,")).toEqual(["a", "b", "c"]);
    expect(splitTerms("")).toEqual([]);
  });

  it("bounds the title as the server does (1..256 code points, trimmed)", () => {
    expect(validateDraft(draft({ title: "   " }), { content: true }).title).toBe(FORM_MESSAGES.titleRequired);
    expect(validateDraft(draft({ title: "😀".repeat(256) }), { content: true }).title).toBeUndefined();
    expect(validateDraft(draft({ title: "x".repeat(257) }), { content: true }).title).toBe(FORM_MESSAGES.titleTooLong);
  });

  it("refuses unparsable or missing JSON for json and mixed, and builds no content from it", () => {
    expect(validateDraft(draft({ format: "json", json: "{" }), { content: true }).json).toBe(FORM_MESSAGES.jsonInvalid);
    expect(validateDraft(draft({ format: "mixed", json: "" }), { content: true }).json).toBe(FORM_MESSAGES.jsonRequired);
    expect(contentOf(draft({ format: "json", json: "{" }))).toBeNull();
    expect(contentOf(draft({ format: "mixed", body: "b", json: '{"k":1}' }))).toEqual({ format: "mixed", body: "b", data: { k: 1 } });
  });

  it("bounds topics and tags (24 entries, 64 characters, no duplicates)", () => {
    expect(validateDraft(draft({ tags: Array.from({ length: 25 }, (_, i) => `t${i}`).join(",") }), { content: true }).tags).toMatch(/At most 24/);
    expect(validateDraft(draft({ topics: "x".repeat(65) }), { content: true }).topics).toMatch(/64 characters/);
    expect(validateDraft(draft({ tags: "A, a" }), { content: true }).tags).toMatch(/repeat/);
  });

  it("patches only changed fields and clears emptied optional ones", () => {
    const baseline = draft({ body: "old", type: "weekly_note", summary: "S", reportDate: "2026-08-09", tags: "draft", topics: "x" });
    const change = buildPatch(baseline, { ...baseline, title: " New ", type: "", summary: "", tags: "draft, final" }, { content: true });
    expect(change).toEqual({ patch: { title: "New", tags: ["draft", "final"] }, clearFields: ["type", "summary"] });
    expect(isNoChange(buildPatch(baseline, { ...baseline }, { content: true }))).toBe(true);
    expect(buildPatch(baseline, { ...baseline, body: "new" }, { content: true }).patch).toEqual({ content: { format: "markdown", body: "new" } });
    expect(buildPatch(baseline, { ...baseline, body: "new" }, { content: false }).patch).toEqual({});
  });

  it("treats re-formatted but equal JSON as unchanged", () => {
    const baseline = draft({ format: "json", json: '{\n  "a": 1\n}' });
    expect(isNoChange(buildPatch(baseline, { ...baseline, json: '{"a":1}' }, { content: true }))).toBe(true);
  });

  it("reads a local text file in the browser and refuses binary or oversized files", async () => {
    expect(await readTextFile(new Blob(["# Héllo"], { type: "text/markdown" }))).toEqual({ ok: true, text: "# Héllo" });
    expect(await readTextFile(new Blob([new Uint8Array([0xff, 0xfe, 0x00, 0x01])]))).toEqual({ ok: false, message: FORM_MESSAGES.fileNotText });
    expect(await readTextFile(new Blob(["a\u0000b"]))).toEqual({ ok: false, message: FORM_MESSAGES.fileNotText });
    const huge = { size: MAX_STAGED_BYTES + 1 } as Blob;
    expect(await readTextFile(huge)).toEqual({ ok: false, message: FORM_MESSAGES.fileTooLarge });
  });
});

describe("ReportNewForm", () => {
  it("publishes an inline request with only the filled fields, then goes to the report", async () => {
    const calls = stub(() => backend(published()));
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "  Weekly  ");
    await userEvent.type(screen.getByLabelText("Body"), "# Hi");
    await userEvent.type(screen.getByLabelText("Type"), "weekly_note");
    await userEvent.type(screen.getByLabelText("Tags"), "a, b");
    fireEvent.change(screen.getByLabelText("Report date"), { target: { value: "2026-08-09" } });
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/reports/grpt_aaaaaaaa11111111"));
    expect(posts(calls)).toEqual([{
      path: "/api/reports",
      method: "POST",
      body: {
        title: "Weekly",
        type: "weekly_note",
        tags: ["a", "b"],
        reportDate: "2026-08-09",
        content: { format: "markdown", body: "# Hi" },
        idempotencyKey: expect.stringMatching(/^report-publish-/),
      },
    }]);
    expect(await screen.findByText(/Report published: version 1\. Receipt grrc_/)).toBeInTheDocument();
  });

  it("blocks submit on unparsable JSON and sends nothing", async () => {
    const calls = stub(() => backend(published()));
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "T");
    await userEvent.selectOptions(screen.getByLabelText("Format"), "json");
    fireEvent.change(screen.getByLabelText("JSON data"), { target: { value: "{not json" } });
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText(FORM_MESSAGES.jsonInvalid)).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("sends JSON content as parsed data", async () => {
    const calls = stub(() => backend(published()));
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "T");
    await userEvent.selectOptions(screen.getByLabelText("Format"), "json");
    fireEvent.change(screen.getByLabelText("JSON data"), { target: { value: '{"rows":[1,2]}' } });
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0]!.body!.content).toEqual({ format: "json", data: { rows: [1, 2] } });
  });

  it("sends a request above 512 KiB through begin/append/finalize, then publishes with the transfer ref", async () => {
    const { calls, chunks } = transferBff();
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "Large");
    await userEvent.selectOptions(screen.getByLabelText("Format"), "text");
    const body = "a".repeat(600_000);
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: body } });
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/reports/grpt_aaaaaaaa11111111"));
    expect(calls.map((call) => call.path)).toEqual([
      "/api/reports/transfers",
      `/api/reports/transfers/${SESSION}/append`,
      `/api/reports/transfers/${SESSION}/append`,
      `/api/reports/transfers/${SESSION}/append`,
      `/api/reports/transfers/${SESSION}/finalize`,
      "/api/reports",
    ]);
    expect(calls[0]!.body).toEqual({
      format: "text", byteCount: 600_000, sha256: sha(new TextEncoder().encode(body)),
      idempotencyKey: expect.stringMatching(/^report-transfer-/),
    });
    expect(chunks.map((chunk) => chunk.byteLength)).toEqual([262_144, 262_144, 75_712]);
    expect(calls[5]!.body).toEqual({
      title: "Large",
      content: { transfer: { sessionId: SESSION, contentToken: TOKEN } },
      idempotencyKey: expect.stringMatching(/^report-publish-/),
    });
    for (const call of calls) expect(call.path).not.toContain("grxtk_");
  });

  it("shows the uploading state while large content is staged", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    stub(async () => { await gate; return refusedAnswer(400, "invalid_request"); });
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "Large");
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "b".repeat(600_000) } });
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText(FORM_MESSAGES.uploading)).toBeInTheDocument();
    release();
    expect(await screen.findByText("The request was not accepted.")).toBeInTheDocument();
  });

  it("prevents a double submit while one is in flight", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const calls = stub(async () => { await gate; return backend(published()); });
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "T");
    await userEvent.type(screen.getByLabelText("Body"), "b");
    const form = screen.getByRole("form", { name: "New report" });
    fireEvent.submit(form);
    fireEvent.submit(form);
    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    release();
    await waitFor(() => expect(nav.push).toHaveBeenCalledTimes(1));
    expect(posts(calls)).toHaveLength(1);
  });

  it("shows a refusal in product words and keeps the draft; a resubmission gets a new key", async () => {
    const calls = stub(() => refusedAnswer(400, "invalid_request"));
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "T");
    await userEvent.type(screen.getByLabelText("Body"), "b");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("The request was not accepted.")).toBeInTheDocument();
    expect(screen.queryByText("safe_field")).toBeNull();
    expect(screen.getByLabelText(/^Title/)).toHaveValue("T");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    expect(posts(calls)[0]!.body!.idempotencyKey).not.toBe(posts(calls)[1]!.body!.idempotencyKey);
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("reuses the key when the answer was ambiguous", async () => {
    const calls = stub(() => refusedAnswer(503, "unavailable", "unavailable"));
    renderForm();
    await userEvent.type(screen.getByLabelText(/^Title/), "T");
    await userEvent.type(screen.getByLabelText("Body"), "b");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Reports are unavailable right now.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(4));
    expect(new Set(posts(calls).map((call) => call.body!.idempotencyKey)).size).toBe(1);
  });

  it("reads a picked text file into the body, in the browser, with no request", async () => {
    const calls = stub(() => backend(published()));
    renderForm();
    const file = new File(["# From disk"], "notes.md", { type: "text/markdown" });
    await userEvent.upload(screen.getByLabelText("Read text from a local file"), file);
    await waitFor(() => expect(screen.getByLabelText("Body")).toHaveValue("# From disk"));
    expect(calls).toEqual([]);
  });

  it("refuses a picked binary file and leaves the body alone", async () => {
    stub(() => backend(published()));
    renderForm();
    await userEvent.type(screen.getByLabelText("Body"), "keep");
    const file = new File([new Uint8Array([0xff, 0xfe, 0xfd])], "x.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByLabelText("Read text from a local file"), file);
    expect(await screen.findByText(FORM_MESSAGES.fileNotText)).toBeInTheDocument();
    expect(screen.getByLabelText("Body")).toHaveValue("keep");
  });

  it("previews markdown through the shared renderer", async () => {
    stub(() => backend(published()));
    renderForm();
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "# Heading\n\nText." } });
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    const preview = screen.getByTestId("report-form-preview");
    expect(preview.querySelector("[data-format='markdown']")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
  });
});
