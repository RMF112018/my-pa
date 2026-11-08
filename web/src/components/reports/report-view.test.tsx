/**
 * WP07 U5-U7: one standalone report against a stubbed BFF (`fetch`), over the
 * committed Python-built fixtures: actions by state, confirmation, A2 conflict
 * copy, version selection, history, and the verified full-content load.
 *
 * jsdom's ArrayBuffer is not Node's, so WebCrypto's `digest` is delegated to
 * Node's SHA-256 over a copy of the same bytes: the digest checked is real.
 */
import { createHash } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import standalone from "@/lib/api/decode/fixtures/python/reports.standalone.json";
import { CONFLICT_MESSAGE } from "@/lib/reports/client";
import { ReportView } from "./report-view";

type Json = Record<string, unknown>;
const REPORT = "grpt_aaaaaaaa11111111";
const FORBIDDEN = /purge|permanent|legal hold|place hold|release hold|retention|empty trash/i;
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

const backend = (result: unknown) => Response.json({ shape: "backend", ...(result as Json), disclosure: {} });
const refusedAnswer = (status: number, code: string, current?: Json) =>
  Response.json({ state: "refused", error: { errorClass: "conflict", code, message: "safe_field" }, disclosure: {}, ...(current ? { current } : {}) }, { status });

function readOf(name: keyof typeof standalone, patch: Json = {}): Json {
  return { ...(structuredClone(standalone[name]) as Json), ...patch };
}

function stub(answer: (path: string, init?: RequestInit) => Response) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => answer(String(input), init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const posts = (fetchMock: ReturnType<typeof stub>) =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === "POST").map(([input, init]) => ({ path: String(input), body: JSON.parse(String(init!.body)) as Json }));
const reads = (fetchMock: ReturnType<typeof stub>) =>
  fetchMock.mock.calls.map(([input]) => String(input)).filter((path) => path.startsWith(`/api/reports/${REPORT}?`));

function expectNoForbiddenControls() {
  for (const control of [...screen.queryAllByRole("button", { hidden: true }), ...screen.queryAllByRole("link")]) {
    expect(control.textContent ?? "").not.toMatch(FORBIDDEN);
  }
  expect(document.body.textContent ?? "").not.toMatch(FORBIDDEN);
}

beforeEach(() => {
  vi.spyOn(globalThis.crypto.subtle, "digest").mockImplementation(async (_algorithm, data) => {
    const bytes = Buffer.from(new Uint8Array(data as ArrayBuffer));
    const digest = createHash("sha256").update(bytes).digest();
    return Uint8Array.from(digest).buffer;
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ReportView", () => {
  it("shows the head version, details, held badge and markdown through the shared renderer", async () => {
    const fetchMock = stub(() => backend(readOf("reports.read.markdown")));
    render(<ReportView reportId={REPORT} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Synthetic report" })).toBeInTheDocument();
    expect(reads(fetchMock)).toEqual([`/api/reports/${REPORT}?includeWithdrawn=true`]);
    expect(screen.getByText("On hold")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /hold/i })).toBeNull();
    const content = screen.getByTestId("report-content");
    expect(within(content).getByRole("heading", { name: "Synthetic" })).toBeInTheDocument();
    expect(within(content).getByText("Body.")).toBeInTheDocument();
    expectNoForbiddenControls();
  });

  it("pretty-prints JSON content as text", async () => {
    stub(() => backend(readOf("reports.read.json")));
    render(<ReportView reportId={REPORT} />);
    const data = await screen.findByLabelText("Report data");
    expect(data.tagName).toBe("PRE");
    expect(data.textContent).toBe(JSON.stringify({ rows: [1, 2], ok: true }, null, 2));
  });

  it.each([
    ["active", ["Archive", "Move to Trash"], true],
    ["archived", ["Restore", "Move to Trash"], false],
    ["trashed", ["Restore"], false],
  ] as const)("offers the %s actions only", async (state, expected, editable) => {
    stub(() => backend(readOf("reports.read.markdown", { lifecycle_state: state })));
    render(<ReportView reportId={REPORT} />);
    const actions = await screen.findByRole("region", { name: "Report actions" });
    expect(within(actions).getAllByRole("button").map((button) => button.textContent)).toEqual(expected);
    const edit = within(actions).queryByRole("link", { name: "Edit" });
    if (editable) expect(edit).toHaveAttribute("href", `/reports/${REPORT}/edit`);
    else expect(edit).toBeNull();
    expectNoForbiddenControls();
  });

  it("requires confirmation before Move to Trash and shows the receipt", async () => {
    const deleted = { ...(fixtures["reports.delete"] as Json) };
    const fetchMock = stub((path) => (path.endsWith("/delete") ? backend(deleted) : backend(readOf("reports.read.markdown", { lifecycle_revision: 4 }))));
    render(<ReportView reportId={REPORT} />);
    const actions = await screen.findByRole("region", { name: "Report actions" });
    await userEvent.click(within(actions).getByRole("button", { name: "Move to Trash" }));
    expect(posts(fetchMock)).toEqual([]);
    const dialog = screen.getByRole("dialog", { name: "Move this report to Trash?" });
    await userEvent.type(within(dialog).getByLabelText("Reason (optional)"), "tidy");
    await userEvent.click(within(dialog).getByRole("button", { name: "Move to Trash" }));
    expect(await screen.findByText(/Move to Trash: done\./)).toBeInTheDocument();
    expect(posts(fetchMock)).toEqual([{
      path: `/api/reports/${REPORT}/delete`,
      body: { expectedLifecycleRevision: 4, idempotencyKey: expect.stringMatching(/^report-delete-/), reason: "tidy" },
    }]);
    expect(screen.getByTestId("report-action-feedback")).toHaveTextContent(/Receipt grrc_aaaaaaaa/);
    await waitFor(() => expect(reads(fetchMock)).toHaveLength(2));
  });

  it("does nothing when the confirmation is cancelled", async () => {
    const fetchMock = stub(() => backend(readOf("reports.read.markdown")));
    render(<ReportView reportId={REPORT} />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive" }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "Archive this report?" })).getByRole("button", { name: "Cancel" }));
    expect(posts(fetchMock)).toEqual([]);
  });

  it("A2: a 409 with a moved revision says the report changed, keeps it, and Review latest reloads", async () => {
    const current = { headVersionNumber: 3, headVersionId: "grver_aaaaaaaa11111111", lifecycleState: "archived", lifecycleRevision: 1, held: true };
    const fetchMock = stub((path) => (path.endsWith("/archive") ? refusedAnswer(409, "conflict", current) : backend(readOf("reports.read.markdown"))));
    render(<ReportView reportId={REPORT} />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive" }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "Archive this report?" })).getByRole("button", { name: "Archive" }));
    expect(await screen.findByText("This report changed since you opened it (now version 3).")).toBeInTheDocument();
    expect(posts(fetchMock)).toHaveLength(1);
    expect(reads(fetchMock)).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Review latest" }));
    await waitFor(() => expect(reads(fetchMock)).toHaveLength(2));
    expect(posts(fetchMock)).toHaveLength(1);
  });

  it("A2: a 409 at the same revision (or without current) is the generic conflict, and a resubmission gets a new key", async () => {
    const same = { headVersionNumber: 1, headVersionId: "grver_aaaaaaaa11111111", lifecycleState: "active", lifecycleRevision: 0, held: true };
    const fetchMock = stub((path) => (path.endsWith("/archive") ? refusedAnswer(409, "conflict", same) : backend(readOf("reports.read.markdown"))));
    render(<ReportView reportId={REPORT} />);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await userEvent.click(await screen.findByRole("button", { name: "Archive" }));
      await userEvent.click(within(screen.getByRole("dialog", { name: "Archive this report?" })).getByRole("button", { name: "Archive" }));
      expect(await screen.findByText(CONFLICT_MESSAGE)).toBeInTheDocument();
    }
    const keys = posts(fetchMock).map((post) => post.body.idempotencyKey);
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it("reads an exact version chosen by number", async () => {
    const fetchMock = stub((path) => backend(readOf("reports.read.markdown", path.includes("versionNumber=1")
      ? { head_version_number: 2, version_number: 1, version_id: "grver_bbbbbbbb22222222" }
      : { head_version_number: 2, version_number: 2 })));
    render(<ReportView reportId={REPORT} />);
    await userEvent.selectOptions(await screen.findByLabelText("Version"), "1");
    expect(await screen.findByText("Showing an earlier version; the latest is version 2.")).toBeInTheDocument();
    expect(reads(fetchMock).at(-1)).toBe(`/api/reports/${REPORT}?versionNumber=1&includeWithdrawn=true`);
  });

  it("shows versions and lifecycle events in the History tab", async () => {
    const lifecycle = {
      ...(fixtures["reports.history"] as Json), entries: "lifecycle",
      items: [{ event_id: "grlev_aaaaaaaa11111111", lifecycle_revision: 1, operation: "archive", prior_state: "active", resulting_state: "archived", reason: "done", transitioned_at: "2026-08-09T12:00:00.000Z" }],
    };
    const fetchMock = stub((path) => (path.includes("/history?entries=lifecycle") ? backend(lifecycle)
      : path.includes("/history") ? backend(fixtures["reports.history"]) : backend(readOf("reports.read.markdown"))));
    render(<ReportView reportId={REPORT} />);
    await userEvent.click(await screen.findByRole("tab", { name: "History" }));
    expect(await screen.findByText(/Version 2 · Details changed/)).toBeInTheDocument();
    expect(await screen.findByText(/Archive: Active → Archived/)).toBeInTheDocument();
    const history = fetchMock.mock.calls.map(([input]) => String(input)).filter((path) => path.includes("/history"));
    expect(history.sort()).toEqual([
      `/api/reports/${REPORT}/history?entries=lifecycle&pageSize=20&includeWithdrawn=true`,
      `/api/reports/${REPORT}/history?entries=versions&pageSize=20&includeWithdrawn=true`,
    ]);
  });
});

describe("ReportView full-content load", () => {
  const TEXT = "A synthetic body that the read omitted, loaded in verified ranges.";
  const BYTES = new TextEncoder().encode(TEXT);

  function omitted(pointerSha = sha(BYTES)): Json {
    const read = readOf("reports.read.omitted");
    const content = read.content as Json;
    content.decoded_byte_count = BYTES.byteLength;
    content.body_chunked_read = { capability: "reports.transfer.read_chunk", part: "decoded", byte_count: BYTES.byteLength, sha256: pointerSha };
    return read;
  }

  function contentAnswer(path: string, corrupt = false): Response {
    const params = new URL(path, "http://localhost").searchParams;
    const offset = Number(params.get("offset"));
    const slice = BYTES.subarray(offset, Math.min(BYTES.byteLength, offset + 16));
    const sent = corrupt && offset === 16 ? new TextEncoder().encode("X".repeat(slice.byteLength)) : slice;
    const end = offset + slice.byteLength;
    return backend({
      plane: "standalone", report_id: REPORT, version_id: "grver_aaaaaaaa11111111", version_number: 1,
      part: "decoded", offset, byte_count: sent.byteLength, chunk: Buffer.from(sent).toString("base64"), chunk_sha256: sha(slice),
      total_byte_count: BYTES.byteLength, part_sha256: sha(BYTES), eof: end === BYTES.byteLength, next_offset: end === BYTES.byteLength ? null : end,
    });
  }

  it("offers Load full content (size), verifies every digest, then renders", async () => {
    const fetchMock = stub((path) => (path.includes("/content?") ? contentAnswer(path) : backend(omitted())));
    render(<ReportView reportId={REPORT} />);
    await userEvent.click(await screen.findByRole("button", { name: `Load full content (${BYTES.byteLength} bytes)` }));
    expect(await screen.findByText(TEXT)).toBeInTheDocument();
    const ranges = fetchMock.mock.calls.map(([input]) => String(input)).filter((path) => path.includes("/content?"));
    expect(ranges).toHaveLength(Math.ceil(BYTES.byteLength / 16));
    expect(ranges[0]).toBe(`/api/reports/${REPORT}/content?versionNumber=1&offset=0&part=decoded&includeWithdrawn=true`);
    expect(vi.mocked(globalThis.crypto.subtle.digest)).toHaveBeenCalled();
  });

  it("renders nothing of the content when a chunk fails its digest", async () => {
    stub((path) => (path.includes("/content?") ? contentAnswer(path, true) : backend(omitted())));
    render(<ReportView reportId={REPORT} />);
    await userEvent.click(await screen.findByRole("button", { name: /Load full content/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The content could not be verified, so it is not shown.");
    expect(screen.queryByText(TEXT)).toBeNull();
    expect(screen.queryByTestId("report-content")).toBeNull();
  });

  it("renders nothing when the whole does not match the pointer", async () => {
    stub((path) => (path.includes("/content?") ? contentAnswer(path) : backend(omitted("d".repeat(64)))));
    render(<ReportView reportId={REPORT} />);
    await userEvent.click(await screen.findByRole("button", { name: /Load full content/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
    expect(screen.queryByText(TEXT)).toBeNull();
  });
});
