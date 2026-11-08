/**
 * WP07 U5-U7 + Amendment A2: `/reports/[reportId]/edit` against a stubbed BFF
 * (`fetch`) over the committed Python-built read fixtures: prefill, a patch of
 * only the changed fields plus `clearFields`, the no-change block, the stale
 * conflict that keeps the draft, "Review latest" moving `expectedVersion` with
 * a new key, the generic conflict, non-active reports, metadata-only edits of
 * a large head, and the transfer path for large new content.
 */
import { createHash } from "node:crypto";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import standalone from "@/lib/api/decode/fixtures/python/reports.standalone.json";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";
import { CONFLICT_MESSAGE, STALE_MESSAGE } from "@/lib/reports/client";
import { CONTENT_LOCK_MESSAGES, IDENTITY_KEYS_MESSAGE, UNSAFE_NUMBER_MESSAGE } from "@/lib/reports/content-guards";
import { ReportEditForm } from "./report-edit-form";
import { FORM_MESSAGES } from "./report-form";

type Json = Record<string, unknown>;
const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push, refresh: vi.fn() }) }));

const REPORT = "grpt_aaaaaaaa11111111";
const SESSION = "grxfr_aaaaaaaa11111111";
const TOKEN = `grxtk_${"0123456789abcdef".repeat(4)}`;
const EXPIRES = "2026-08-09T13:00:00.000Z";
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

const backend = (result: unknown) => Response.json({ shape: "backend", ...(result as Json), disclosure: {} });
const refusedAnswer = (status: number, code: string, current?: Json) =>
  Response.json({ state: "refused", error: { errorClass: "conflict", code, message: "safe_field" }, disclosure: {}, ...(current ? { current } : {}) }, { status });
const readOf = (name: keyof typeof standalone, patch: Json = {}): Json => ({ ...(structuredClone(standalone[name]) as Json), ...patch });
const updated = () => structuredClone(fixtures["reports.update"]) as Json;
const current = (headVersionNumber: number): Json => ({
  headVersionNumber, headVersionId: "grver_bbbbbbbb22222222", lifecycleState: "active", lifecycleRevision: 0, held: true,
});

interface Call { readonly path: string; readonly method: string; readonly body?: Json }
function stub(answer: (path: string, body?: Json) => Response | Promise<Response>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Json) : undefined;
    calls.push({ path, method: init?.method ?? "GET", ...(body ? { body } : {}) });
    return answer(path, body);
  }));
  return calls;
}
const updates = (calls: readonly Call[]) => calls.filter((call) => call.path === `/api/reports/${REPORT}/update`);
const reads = (calls: readonly Call[]) => calls.filter((call) => call.path.startsWith(`/api/reports/${REPORT}?`));

function renderForm({ strict = false } = {}) {
  const form = <MutationFeedbackProvider><ReportEditForm reportId={REPORT} /></MutationFeedbackProvider>;
  return render(strict ? <StrictMode>{form}</StrictMode> : form);
}
async function ready() {
  return screen.findByRole("form", { name: "Edit report" });
}
const reasonField = () => screen.getByLabelText(/^Reason for the change/);

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

describe("ReportEditForm", () => {
  it("reads the head with its body (withdrawn included) and prefills the draft", async () => {
    const calls = stub(() => backend(readOf("reports.read.markdown")));
    renderForm();
    await ready();
    expect(reads(calls).map((call) => call.path)).toEqual([`/api/reports/${REPORT}?includeBody=true&includeWithdrawn=true`]);
    expect(screen.getByLabelText(/^Title/)).toHaveValue("Synthetic report");
    expect(screen.getByLabelText("Body")).toHaveValue("# Synthetic\n\nBody.");
    expect(screen.getByLabelText("Type")).toHaveValue("weekly_note");
    expect(screen.getByLabelText("Tags")).toHaveValue("draft");
    expect(screen.getByLabelText("Topics")).toHaveValue("synthetic");
    expect(screen.getByLabelText("Summary")).toHaveValue("A synthetic summary.");
    expect(screen.getByLabelText("Report date")).toHaveValue("2026-08-09");
  });

  it("blocks a submit that changes nothing, and one without a reason", async () => {
    const calls = stub(() => backend(readOf("reports.read.markdown")));
    renderForm();
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(FORM_MESSAGES.reasonRequired)).toBeInTheDocument();
    await userEvent.type(reasonField(), "why");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(FORM_MESSAGES.nothingChanged)).toBeInTheDocument();
    expect(updates(calls)).toEqual([]);
  });

  it("sends only the changed fields, clears emptied optional ones, and goes to the report", async () => {
    const calls = stub((path) => (path.endsWith("/update") ? backend(updated()) : backend(readOf("reports.read.markdown"))));
    renderForm();
    await ready();
    await userEvent.clear(screen.getByLabelText(/^Title/));
    await userEvent.type(screen.getByLabelText(/^Title/), "Renamed");
    await userEvent.clear(screen.getByLabelText("Summary"));
    fireEvent.change(screen.getByLabelText("Report date"), { target: { value: "" } });
    await userEvent.type(screen.getByLabelText("Tags"), ", final");
    await userEvent.type(reasonField(), "  tidy  ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/reports/${REPORT}`));
    expect(updates(calls).map((call) => call.body)).toEqual([{
      expectedVersion: 1,
      patch: { title: "Renamed", tags: ["draft", "final"] },
      clearFields: ["summary", "reportDate"],
      changeReason: "tidy",
      idempotencyKey: expect.stringMatching(/^report-update-/),
    }]);
    expect(await screen.findByText(/Report saved: version 2\. Receipt grrc_/)).toBeInTheDocument();
  });

  it("sends changed content and nothing else", async () => {
    const calls = stub((path) => (path.endsWith("/update") ? backend(updated()) : backend(readOf("reports.read.markdown"))));
    renderForm();
    await ready();
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "# New" } });
    await userEvent.type(reasonField(), "r");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updates(calls)).toHaveLength(1));
    expect(updates(calls)[0]!.body!.patch).toEqual({ content: { format: "markdown", body: "# New" } });
    expect(updates(calls)[0]!.body).not.toHaveProperty("clearFields");
  });

  it("blocks unparsable JSON in a json report", async () => {
    const calls = stub(() => backend(readOf("reports.read.json")));
    renderForm();
    await ready();
    fireEvent.change(screen.getByLabelText("JSON data"), { target: { value: "{" } });
    await userEvent.type(reasonField(), "r");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(FORM_MESSAGES.jsonInvalid)).toBeInTheDocument();
    expect(updates(calls)).toEqual([]);
  });

  it("U5/A2: a stale conflict keeps the draft, says the new version, and never retries", async () => {
    const calls = stub((path) => (path.endsWith("/update") ? refusedAnswer(409, "conflict", current(3)) : backend(readOf("reports.read.markdown"))));
    renderForm();
    await ready();
    await userEvent.clear(screen.getByLabelText(/^Title/));
    await userEvent.type(screen.getByLabelText(/^Title/), "Mine");
    await userEvent.type(reasonField(), "r");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const notice = await screen.findByTestId("report-edit-notice");
    expect(notice).toHaveTextContent(STALE_MESSAGE(3));
    expect(notice).toHaveAttribute("data-kind", "stale");
    expect(screen.getByLabelText(/^Title/)).toHaveValue("Mine");
    expect(reasonField()).toHaveValue("r");
    expect(updates(calls)).toHaveLength(1);
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("U5/A2: Review latest shows the latest head beside the draft; the next submit uses its version with a new key", async () => {
    let head = 1;
    const calls = stub((path, body) => {
      if (path.endsWith("/update")) {
        return body!.expectedVersion === 3 ? backend(updated()) : refusedAnswer(409, "conflict", current(3));
      }
      return backend(readOf("reports.read.markdown", head === 1 ? {} : { head_version_number: 3, version_number: 3, title: "Theirs" }));
    });
    renderForm();
    await ready();
    await userEvent.clear(screen.getByLabelText(/^Title/));
    await userEvent.type(screen.getByLabelText(/^Title/), "Mine");
    await userEvent.type(reasonField(), "r");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(STALE_MESSAGE(3));
    head = 3;
    await userEvent.click(screen.getByRole("button", { name: "Review latest" }));
    const latest = await screen.findByTestId("report-latest");
    expect(within(latest).getByText("Latest: version 3")).toBeInTheDocument();
    expect(within(latest).getByText("Theirs")).toBeInTheDocument();
    expect(within(latest).getByText("Your next save is checked against version 3.")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Title/)).toHaveValue("Mine");
    expect(updates(calls)).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/reports/${REPORT}`));
    const bodies = updates(calls).map((call) => call.body!);
    expect(bodies.map((body) => body.expectedVersion)).toEqual([1, 3]);
    expect(bodies[1]!.patch).toEqual({ title: "Mine" });
    expect(bodies[0]!.idempotencyKey).not.toBe(bodies[1]!.idempotencyKey);
  });

  it("A2: a 409 at the same version (or without current) is the generic conflict; a resubmission gets a new key", async () => {
    let answer = 0;
    const calls = stub((path) => {
      if (!path.endsWith("/update")) return backend(readOf("reports.read.markdown"));
      answer += 1;
      return answer === 1 ? refusedAnswer(409, "idempotency_conflict", current(1)) : refusedAnswer(409, "conflict");
    });
    renderForm();
    await ready();
    await userEvent.type(screen.getByLabelText("Tags"), ", x");
    await userEvent.type(reasonField(), "r");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(updates(calls)).toHaveLength(attempt + 1));
      const notice = await screen.findByTestId("report-edit-notice");
      expect(notice).toHaveTextContent(CONFLICT_MESSAGE);
      expect(notice).toHaveAttribute("data-kind", "conflict");
    }
    const keys = updates(calls).map((call) => call.body!.idempotencyKey);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it.each(["archived", "trashed"] as const)("does not offer editing a %s report and links back", async (state) => {
    const calls = stub(() => backend(readOf("reports.read.markdown", { lifecycle_state: state })));
    renderForm();
    const notice = await screen.findByTestId("report-not-editable");
    expect(notice).toHaveTextContent(/Only active reports can be edited/);
    expect(within(notice).getByRole("link", { name: "Back to the report" })).toHaveAttribute("href", `/reports/${REPORT}`);
    expect(screen.queryByRole("form", { name: "Edit report" })).toBeNull();
    expect(updates(calls)).toEqual([]);
  });

  it("edits a large head's details without its content, and loads the content (verified) to edit it", async () => {
    const text = "Omitted synthetic body.";
    const bytes = new TextEncoder().encode(text);
    const omitted = readOf("reports.read.omitted", { lifecycle_state: "active" });
    const content = omitted.content as Json;
    content.body_chunked_read = { capability: "reports.transfer.read_chunk", part: "decoded", byte_count: bytes.byteLength, sha256: sha(bytes) };
    const calls = stub((path) => {
      if (path.endsWith("/update")) return backend(updated());
      if (path.includes("/content?")) {
        return backend({
          plane: "standalone", report_id: REPORT, version_id: omitted.version_id, version_number: 1, part: "decoded",
          offset: 0, byte_count: bytes.byteLength, chunk: Buffer.from(bytes).toString("base64"), chunk_sha256: sha(bytes),
          total_byte_count: bytes.byteLength, part_sha256: sha(bytes), eof: true, next_offset: null,
        });
      }
      return backend(omitted);
    });
    renderForm();
    await ready();
    expect(screen.getByTestId("report-edit-content-omitted")).toBeInTheDocument();
    expect(screen.queryByLabelText("Body")).toBeNull();
    await userEvent.type(screen.getByLabelText("Tags"), ", y");
    await userEvent.click(screen.getByRole("button", { name: /^Load full content/ }));
    await waitFor(() => expect(screen.getByLabelText("Body")).toHaveValue(text));
    expect(screen.getByLabelText("Tags")).toHaveValue("draft, y");
    await userEvent.type(reasonField(), "r");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updates(calls)).toHaveLength(1));
    expect(updates(calls)[0]!.body!.patch).toEqual({ tags: ["draft", "y"] });
  });

  it("a metadata-only edit of a large head never sends content", async () => {
    const calls = stub((path) => (path.endsWith("/update") ? backend(updated()) : backend(readOf("reports.read.omitted", { lifecycle_state: "active" }))));
    renderForm();
    await ready();
    await userEvent.type(screen.getByLabelText("Type"), "_v2");
    await userEvent.type(reasonField(), "r");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updates(calls)).toHaveLength(1));
    expect(updates(calls)[0]!.body!.patch).toEqual({ type: "weekly_note_v2" });
  });

  it("sends large new content through a transfer and updates with the transfer ref", async () => {
    const limit = 262_144;
    let declared = { byteCount: 0, sha256: "" };
    const calls = stub((path, body) => {
      if (path === "/api/reports/transfers") {
        declared = { byteCount: body!.byteCount as number, sha256: body!.sha256 as string };
        return backend({
          session_id: SESSION, state: "open", format: "markdown", encoding: "identity",
          declared_byte_count: declared.byteCount, declared_sha256: declared.sha256, chunk_byte_limit: limit,
          chunk_count: Math.ceil(declared.byteCount / limit), expires_at: EXPIRES, replayed: false,
        });
      }
      if (path.endsWith("/append")) {
        const sequence = body!.sequence as number;
        const chunk = Uint8Array.from(Buffer.from(body!.chunk as string, "base64"));
        const received = Math.min(declared.byteCount, (sequence + 1) * limit);
        return backend({
          session_id: SESSION, sequence, byte_offset: sequence * limit, byte_count: chunk.byteLength,
          chunk_sha256: sha(chunk), received_byte_count: received, declared_byte_count: declared.byteCount,
          complete: received === declared.byteCount, next_sequence: received === declared.byteCount ? null : sequence + 1,
          expires_at: EXPIRES, replayed: false,
        });
      }
      if (path.endsWith("/finalize")) {
        return backend({
          session_id: SESSION, state: "finalized", content_token: TOKEN, expires_at: EXPIRES,
          byte_count: declared.byteCount, sha256: declared.sha256, format: "markdown", encoding: "identity",
          decoded_byte_count: declared.byteCount, decoded_sha256: declared.sha256,
        });
      }
      if (path.endsWith("/update")) return backend(updated());
      return backend(readOf("reports.read.markdown"));
    });
    renderForm();
    await ready();
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "z".repeat(530_000) } });
    await userEvent.type(reasonField(), "r");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalled());
    const paths = calls.filter((call) => call.method === "POST").map((call) => call.path);
    expect(paths).toEqual([
      "/api/reports/transfers",
      `/api/reports/transfers/${SESSION}/append`,
      `/api/reports/transfers/${SESSION}/append`,
      `/api/reports/transfers/${SESSION}/append`,
      `/api/reports/transfers/${SESSION}/finalize`,
      `/api/reports/${REPORT}/update`,
    ]);
    expect(updates(calls)[0]!.body).toEqual({
      expectedVersion: 1,
      patch: { content: { transfer: { sessionId: SESSION, contentToken: TOKEN } } },
      changeReason: "r",
      idempotencyKey: expect.stringMatching(/^report-update-/),
    });
  });

  describe("R1-2: a large update whose answer was ambiguous", () => {
    /** Each begin opens a new session with its own token; `update` answers the n-th update call. */
    function sessionsBff(update: (n: number) => Response) {
      const limit = 262_144;
      let opened = 0;
      let updatesSeen = 0;
      let declared = { byteCount: 0, sha256: "" };
      const session = (n: number) => `grxfr_aaaaaaaa1111111${n}`;
      const token = (n: number) => `grxtk_${String(n).repeat(64)}`;
      const calls = stub((path, body) => {
        if (path === "/api/reports/transfers") {
          opened += 1;
          declared = { byteCount: body!.byteCount as number, sha256: body!.sha256 as string };
          return backend({
            session_id: session(opened), state: "open", format: "markdown", encoding: "identity",
            declared_byte_count: declared.byteCount, declared_sha256: declared.sha256, chunk_byte_limit: limit,
            chunk_count: Math.ceil(declared.byteCount / limit), expires_at: EXPIRES, replayed: false,
          });
        }
        if (path.endsWith("/append")) {
          const sequence = body!.sequence as number;
          const chunk = Uint8Array.from(Buffer.from(body!.chunk as string, "base64"));
          const received = Math.min(declared.byteCount, (sequence + 1) * limit);
          return backend({
            session_id: session(opened), sequence, byte_offset: sequence * limit, byte_count: chunk.byteLength,
            chunk_sha256: sha(chunk), received_byte_count: received, declared_byte_count: declared.byteCount,
            complete: received === declared.byteCount, next_sequence: received === declared.byteCount ? null : sequence + 1,
            expires_at: EXPIRES, replayed: false,
          });
        }
        if (path.endsWith("/finalize")) {
          return backend({
            session_id: session(opened), state: "finalized", content_token: token(opened), expires_at: EXPIRES,
            byte_count: declared.byteCount, sha256: declared.sha256, format: "markdown", encoding: "identity",
            decoded_byte_count: declared.byteCount, decoded_sha256: declared.sha256,
          });
        }
        if (path.endsWith("/abort")) return backend({ session_id: path.split("/").at(-2)!, state: "aborted", replayed: false });
        if (path.endsWith("/update")) return update(++updatesSeen);
        return backend(readOf("reports.read.markdown"));
      });
      return { calls, session, token };
    }
    const begins = (calls: readonly Call[]) => calls.filter((call) => call.path === "/api/reports/transfers");
    const aborts = (calls: readonly Call[]) => calls.filter((call) => call.path.endsWith("/abort")).map((call) => call.path);
    const lost = () => refusedAnswer(503, "unavailable");

    it("resubmits the same transfer with the same key, without a second upload or an abort", async () => {
      const { calls, session, token } = sessionsBff((n) => (n <= 2 ? lost() : backend(updated())));
      renderForm();
      await ready();
      fireEvent.change(screen.getByLabelText("Body"), { target: { value: "z".repeat(530_000) } });
      await userEvent.type(reasonField(), "r");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      expect(await screen.findByTestId("report-edit-notice")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(nav.push).toHaveBeenCalled());
      expect(begins(calls)).toHaveLength(1);
      const sent = updates(calls).map((call) => call.body!);
      expect(sent).toHaveLength(3);
      for (const body of sent) expect(body).toEqual(sent[0]);
      expect((sent[0]!.patch as Json).content).toEqual({ transfer: { sessionId: session(1), contentToken: token(1) } });
      expect(aborts(calls)).toEqual([]);
    });

    it("aborts on a definitive refusal and uploads afresh next time", async () => {
      const { calls, session } = sessionsBff((n) => (n === 1 ? refusedAnswer(400, "invalid_request") : backend(updated())));
      renderForm();
      await ready();
      fireEvent.change(screen.getByLabelText("Body"), { target: { value: "z".repeat(530_000) } });
      await userEvent.type(reasonField(), "r");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      expect(await screen.findByTestId("report-edit-notice")).toBeInTheDocument();
      expect(aborts(calls)).toEqual([`/api/reports/transfers/${session(1)}/abort`]);
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(nav.push).toHaveBeenCalled());
      expect(begins(calls)).toHaveLength(2);
      const [first, second] = updates(calls).map((call) => call.body!);
      expect(second!.idempotencyKey).not.toBe(first!.idempotencyKey);
    });

    it("drops the held transfer when the draft changes: abort, fresh upload, new key", async () => {
      const { calls, session, token } = sessionsBff((n) => (n <= 2 ? lost() : backend(updated())));
      renderForm();
      await ready();
      fireEvent.change(screen.getByLabelText("Body"), { target: { value: "z".repeat(530_000) } });
      await userEvent.type(reasonField(), "r");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      expect(await screen.findByTestId("report-edit-notice")).toBeInTheDocument();
      fireEvent.change(screen.getByLabelText("Body"), { target: { value: "y".repeat(530_000) } });
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(nav.push).toHaveBeenCalled());
      expect(aborts(calls)).toEqual([`/api/reports/transfers/${session(1)}/abort`]);
      expect(begins(calls)).toHaveLength(2);
      const sent = updates(calls).map((call) => call.body!);
      expect(sent).toHaveLength(3);
      expect((sent[2]!.patch as Json).content).toEqual({ transfer: { sessionId: session(2), contentToken: token(2) } });
      expect(sent[2]!.idempotencyKey).not.toBe(sent[0]!.idempotencyKey);
    });
  });
  describe("WP08 C-WP07 R1 #4/#6: content kept read-only", () => {
    const jsonRead = (data: unknown, patch: Json = {}) => {
      const read = readOf("reports.read.json", patch);
      (read.content as Json).data = data;
      return read;
    };
    async function metadataOnlySave(calls: readonly Call[]) {
      await userEvent.type(screen.getByLabelText("Tags"), ", z");
      await userEvent.type(reasonField(), "r");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(updates(calls)).toHaveLength(1));
      expect(updates(calls)[0]!.body!.patch).toEqual({ tags: ["draft", "z"] });
    }

    it("(b)+(c) the read's identity_keys_withheld flag: content read-only with a notice; a metadata edit sends no content", async () => {
      const calls = stub((path) => (path.endsWith("/update") ? backend(updated()) : backend(jsonRead({ rows: [{}] }, { identity_keys_withheld: true }))));
      renderForm();
      await ready();
      const notice = screen.getByTestId("report-edit-content-locked");
      expect(notice).toHaveAttribute("data-lock", "identity");
      expect(notice).toHaveTextContent(CONTENT_LOCK_MESSAGES.identity);
      expect(screen.queryByLabelText("JSON data")).toBeNull();
      await metadataOnlySave(calls);
    });

    it("(c) loaded data the BFF would refuse (tid) is read-only too", async () => {
      const calls = stub((path) => (path.endsWith("/update") ? backend(updated()) : backend(jsonRead({ tid: "t" }))));
      renderForm();
      await ready();
      expect(screen.getByTestId("report-edit-content-locked")).toHaveAttribute("data-lock", "identity");
      await metadataOnlySave(calls);
    });

    it("(b) without the flag and without identity keys, the content is editable", async () => {
      stub(() => backend(jsonRead({ rows: [1] })));
      renderForm();
      await ready();
      expect(screen.queryByTestId("report-edit-content-locked")).toBeNull();
      expect(screen.getByLabelText("JSON data")).toBeInTheDocument();
    });

    it("R1 #6: an integer beyond 2^53 in the loaded data keeps the content read-only", async () => {
      const calls = stub((path) => (path.endsWith("/update") ? backend(updated()) : backend(jsonRead({ n: 2 ** 60 }))));
      renderForm();
      await ready();
      const notice = screen.getByTestId("report-edit-content-locked");
      expect(notice).toHaveAttribute("data-lock", "precision");
      expect(notice).toHaveTextContent(CONTENT_LOCK_MESSAGES.precision);
      await metadataOnlySave(calls);
    });

    it("R1 #4/#6: content read in chunks is checked after assembly (source text)", async () => {
      const text = '{"n":12345678901234567890}';
      const bytes = new TextEncoder().encode(text);
      const omitted = readOf("reports.read.omitted", { lifecycle_state: "active" });
      const content = omitted.content as Json;
      content.format = "json";
      content.body_chunked_read = { capability: "reports.transfer.read_chunk", part: "decoded", byte_count: bytes.byteLength, sha256: sha(bytes) };
      const calls = stub((path) => {
        if (path.endsWith("/update")) return backend(updated());
        if (path.includes("/content?")) {
          return backend({
            plane: "standalone", report_id: REPORT, version_id: omitted.version_id, version_number: 1, part: "decoded",
            offset: 0, byte_count: bytes.byteLength, chunk: Buffer.from(bytes).toString("base64"), chunk_sha256: sha(bytes),
            total_byte_count: bytes.byteLength, part_sha256: sha(bytes), eof: true, next_offset: null,
          });
        }
        return backend(omitted);
      });
      renderForm();
      await ready();
      await userEvent.click(screen.getByRole("button", { name: /^Load full content/ }));
      expect(await screen.findByTestId("report-edit-content-locked")).toHaveAttribute("data-lock", "precision");
      expect(screen.queryByLabelText("JSON data")).toBeNull();
      await metadataOnlySave(calls);
    });

    it.each([
      ["an identity key", '{"rows":[{"principalId":"p"}]}', IDENTITY_KEYS_MESSAGE],
      ["an integer beyond 2^53", '{"rows":[9007199254740993]}', UNSAFE_NUMBER_MESSAGE],
    ])("(a)/R1 #6: typed JSON with %s is refused before any request", async (_name, json, message) => {
      const calls = stub(() => backend(jsonRead({ rows: [1] })));
      renderForm();
      await ready();
      fireEvent.change(screen.getByLabelText("JSON data"), { target: { value: json } });
      await userEvent.type(reasonField(), "r");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      expect(await screen.findByTestId("report-edit-notice")).toHaveTextContent(message);
      expect(updates(calls)).toEqual([]);
    });
  });

  describe("WP08 R3 #2: unmount and StrictMode (mirroring the new form)", () => {
    const begins = (calls: readonly Call[]) => calls.filter((call) => call.path === "/api/reports/transfers");
    const aborts = (calls: readonly Call[]) => calls.filter((call) => call.path.endsWith("/abort")).map((call) => call.path);
    const lost = () => refusedAnswer(503, "unavailable");
    /** One session per begin; `update` answers the n-th update call. */
    function bff(update: (n: number) => Response | Promise<Response>) {
      const limit = 262_144;
      let declared = { byteCount: 0, sha256: "" };
      let seen = 0;
      return stub((path, body) => {
        if (path === "/api/reports/transfers") {
          declared = { byteCount: body!.byteCount as number, sha256: body!.sha256 as string };
          return backend({
            session_id: SESSION, state: "open", format: "markdown", encoding: "identity",
            declared_byte_count: declared.byteCount, declared_sha256: declared.sha256, chunk_byte_limit: limit,
            chunk_count: Math.ceil(declared.byteCount / limit), expires_at: EXPIRES, replayed: false,
          });
        }
        if (path.endsWith("/append")) {
          const sequence = body!.sequence as number;
          const chunk = Uint8Array.from(Buffer.from(body!.chunk as string, "base64"));
          const received = Math.min(declared.byteCount, (sequence + 1) * limit);
          return backend({
            session_id: SESSION, sequence, byte_offset: sequence * limit, byte_count: chunk.byteLength,
            chunk_sha256: sha(chunk), received_byte_count: received, declared_byte_count: declared.byteCount,
            complete: received === declared.byteCount, next_sequence: received === declared.byteCount ? null : sequence + 1,
            expires_at: EXPIRES, replayed: false,
          });
        }
        if (path.endsWith("/finalize")) {
          return backend({
            session_id: SESSION, state: "finalized", content_token: TOKEN, expires_at: EXPIRES,
            byte_count: declared.byteCount, sha256: declared.sha256, format: "markdown", encoding: "identity",
            decoded_byte_count: declared.byteCount, decoded_sha256: declared.sha256,
          });
        }
        if (path.endsWith("/abort")) return backend({ session_id: SESSION, state: "aborted", replayed: false });
        if (path.endsWith("/update")) return update(++seen);
        return backend(readOf("reports.read.markdown"));
      });
    }
    async function saveLarge() {
      await ready();
      fireEvent.change(screen.getByLabelText("Body"), { target: { value: "z".repeat(530_000) } });
      await userEvent.type(reasonField(), "r");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
    }

    it("an update in flight when the form is left that then answers ambiguously aborts and holds nothing", async () => {
      let answer: () => void = () => undefined;
      const gate = new Promise<void>((resolve) => { answer = resolve; });
      const calls = bff(async () => { await gate; return lost(); });
      const view = renderForm();
      await saveLarge();
      await waitFor(() => expect(updates(calls)).toHaveLength(1));
      view.unmount();
      expect(aborts(calls)).toEqual([]);
      answer();
      await waitFor(() => expect(aborts(calls)).toEqual([`/api/reports/transfers/${SESSION}/abort`]));
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(aborts(calls)).toHaveLength(1);
    });

    it("under StrictMode (mount -> cleanup -> mount) an ambiguous answer is still kept for the resubmit", async () => {
      const calls = bff((n) => (n <= 2 ? lost() : backend(updated())));
      renderForm({ strict: true });
      await saveLarge();
      expect(await screen.findByTestId("report-edit-notice")).toBeInTheDocument();
      expect(aborts(calls)).toEqual([]);
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/reports/${REPORT}`));
      expect(begins(calls)).toHaveLength(1);
      const sent = updates(calls).map((call) => call.body!);
      expect(sent).toHaveLength(3);
      for (const body of sent) expect(body).toEqual(sent[0]);
      expect(aborts(calls)).toEqual([]);
    });
  });
});
