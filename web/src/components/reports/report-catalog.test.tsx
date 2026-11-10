/**
 * WP07 U7: the Reports list/search and Trash against a stubbed BFF (`fetch`),
 * over the committed Python-built standalone fixtures.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import standalone from "@/lib/api/decode/fixtures/python/reports.standalone.json";
import { ReportCatalog } from "./report-catalog";

type Json = Record<string, unknown>;
const FORBIDDEN = /purge|permanent|legal hold|place hold|release hold|retention|empty trash/i;

const backend = (result: unknown) =>
  Response.json({ shape: "backend", ...(result as Json), disclosure: {} });
const refusedAnswer = (status: number, code: string, current?: Json) =>
  Response.json({ state: "refused", error: { errorClass: "conflict", code, message: "safe_field" }, disclosure: {}, ...(current ? { current } : {}) }, { status });

function stub(answer: (path: string, init?: RequestInit) => Response) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => answer(String(input), init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const paths = (fetchMock: ReturnType<typeof stub>) => fetchMock.mock.calls.map(([input]) => String(input));
const query = (path: string) => new URL(path, "http://localhost").searchParams;

function trashedPage(): Json {
  const page = structuredClone(standalone["reports.list.standalone"]) as { items: Json[] } & Json;
  page.items = page.items.map((item) => ({ ...item, lifecycle_state: "trashed", lifecycle_revision: 2, held: false }));
  return page;
}

function expectNoForbiddenControls() {
  for (const control of [...screen.queryAllByRole("button"), ...screen.queryAllByRole("link")]) {
    expect(control.textContent ?? "").not.toMatch(FORBIDDEN);
  }
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ReportCatalog", () => {
  it("sends the plane explicitly: Standalone by default, then All", async () => {
    const fetchMock = stub((path) => backend(query(path).get("plane") === "all" ? standalone["reports.list.all"] : standalone["reports.list.standalone"]));
    render(<ReportCatalog />);
    expect(await screen.findByRole("link", { name: "Synthetic report" })).toHaveAttribute("href", "/reports/grpt_aaaaaaaa11111111");
    expect(paths(fetchMock)).toEqual(["/api/reports?plane=standalone&lifecycleStates=active&pageSize=25"]);
    await userEvent.selectOptions(screen.getByLabelText("Show"), "all");
    expect(await screen.findByText("Pipeline")).toBeInTheDocument();
    expect(paths(fetchMock)[1]).toBe("/api/reports?plane=all&lifecycleStates=active&pageSize=25");
    expect(paths(fetchMock).every((path) => query(path).has("plane"))).toBe(true);
  });

  it("shows held as a read-only badge with no hold control", async () => {
    stub(() => backend(standalone["reports.list.standalone"]));
    render(<ReportCatalog />);
    const list = await screen.findByRole("list", { name: "Reports" });
    expect(within(list).getByText("On hold")).toBeInTheDocument();
    expect(within(list).queryAllByRole("button")).toEqual([]);
    expect(screen.queryByRole("button", { name: /hold/i })).toBeNull();
    expectNoForbiddenControls();
  });

  it("labels pipeline items, links them to Intelligence and gives them no action", async () => {
    stub(() => backend(standalone["reports.list.all"]));
    render(<ReportCatalog />);
    const list = await screen.findByRole("list", { name: "Reports" });
    const pipeline = list.querySelector('[data-plane="intelligence"]') as HTMLElement;
    expect(within(pipeline).getByText("Pipeline")).toBeInTheDocument();
    expect(within(pipeline).getByRole("link")).toHaveAttribute("href", "/intelligence/reports/rpt_aaaaaaaa11111111");
    expect(within(pipeline).queryAllByRole("button")).toEqual([]);
  });

  it("applies search, type and tag filters and the Archived lifecycle", async () => {
    const fetchMock = stub((path) => backend(query(path).has("query") ? standalone["reports.search.all"] : standalone["reports.list.standalone"]));
    render(<ReportCatalog />);
    await screen.findByRole("list", { name: "Reports" });
    await userEvent.selectOptions(screen.getByLabelText("State"), "archived");
    await userEvent.type(screen.getByLabelText("Search"), "synthetic");
    await userEvent.type(screen.getByLabelText("Type"), "weekly_note");
    await userEvent.type(screen.getByLabelText("Tag"), "draft");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(paths(fetchMock)).toHaveLength(3));
    const last = query(paths(fetchMock).at(-1)!);
    expect(Object.fromEntries(last)).toEqual({ plane: "standalone", lifecycleStates: "archived", pageSize: "25", query: "synthetic", type: "weekly_note", tags: "draft" });
  });

  it("loads more with the cursor and the same filters", async () => {
    const fetchMock = stub((path) => backend(query(path).has("cursor") ? standalone["reports.list.standalone"] : standalone["reports.list.all"]));
    render(<ReportCatalog />);
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    await waitFor(() => expect(paths(fetchMock)).toHaveLength(2));
    expect(paths(fetchMock)[1]).toBe("/api/reports?plane=standalone&lifecycleStates=active&pageSize=25&cursor=synthetic-cursor");
    expect(await screen.findAllByRole("link", { name: "Synthetic report" })).toHaveLength(2);
  });

  it("says unavailable, not empty, when the read is refused", async () => {
    stub(() => refusedAnswer(503, "unavailable"));
    render(<ReportCatalog />);
    expect(await screen.findByRole("heading", { name: "Reports unavailable" })).toBeInTheDocument();
    expect(screen.queryByText("No reports match")).toBeNull();
  });

  it("links to Trash and to New report", async () => {
    stub(() => backend(standalone["reports.list.standalone"]));
    render(<ReportCatalog />);
    expect(screen.getByRole("link", { name: "Trash" })).toHaveAttribute("href", "/reports/trash");
    expect(screen.getByRole("link", { name: "New report" })).toHaveAttribute("href", "/reports/new");
    await screen.findByRole("list", { name: "Reports" });
  });
});

describe("ReportCatalog in Trash", () => {
  it("lists standalone trashed reports and restores one with its lifecycle revision", async () => {
    const restored = { ...(fixtures["reports.restore"] as Json) };
    const fetchMock = stub((path) => (path.endsWith("/restore") ? backend(restored) : backend(trashedPage())));
    render(<ReportCatalog mode="trash" />);
    const list = await screen.findByRole("list", { name: "Reports in Trash" });
    expect(paths(fetchMock)[0]).toBe("/api/reports?plane=standalone&lifecycleStates=trashed&pageSize=25");
    await userEvent.click(within(list).getByRole("button", { name: "Restore" }));
    expect(await screen.findByText(/Restored "Synthetic report"/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/restore"))!;
    expect(String(post[0])).toBe("/api/reports/grpt_aaaaaaaa11111111/restore");
    const body = JSON.parse(String(post[1]!.body));
    expect(body).toEqual({ expectedLifecycleRevision: 2, idempotencyKey: expect.stringMatching(/^report-restore-/) });
    await waitFor(() => expect(paths(fetchMock).filter((path) => path.startsWith("/api/reports?"))).toHaveLength(2));
    expectNoForbiddenControls();
  });

  it("shows the A2 stale message and offers Review latest on a 409", async () => {
    const fetchMock = stub((path) => (path.endsWith("/restore")
      ? refusedAnswer(409, "conflict", { headVersionNumber: 3, headVersionId: "grver_aaaaaaaa11111111", lifecycleState: "active", lifecycleRevision: 3, held: false })
      : backend(trashedPage())));
    render(<ReportCatalog mode="trash" />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore" }));
    expect(await screen.findByText("This report's state changed since you opened it (now active).")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/restore"))).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Review latest" }));
    await waitFor(() => expect(paths(fetchMock).filter((path) => path.startsWith("/api/reports?"))).toHaveLength(2));
  });
});
