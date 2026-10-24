import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { IssueView } from "@/components/issues/issue-view";
import { IssueList } from "@/components/issues/issue-list";
import { ISSUE_MESSAGES } from "@/components/issues/presentation";

/* The Issue view's header and the Issues index (S3 contract section 7.6), over the committed Python fixtures. */
type Json = Record<string, unknown>;
const ISSUE_ID = "sit_aaaaaaaa11111111";

function backend(body: Json): Response { return Response.json({ shape: "backend", ...body, disclosure: {} }); }
function unsupported(): Response {
  return Response.json({ error: { errorClass: "unavailable", code: "unsupported", message: "x" } }, { status: 503 });
}
function lineage(): Json {
  const value = structuredClone(fixtures["records.lineage"]) as Json;
  value.root = { family: "situation", record_id: ISSUE_ID };
  return value;
}
function stub(answer: (path: string) => Response) {
  const fetchMock = vi.fn<typeof fetch>(async (input) => answer(String(input)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("IssueView", () => {
  it("shows the breadcrumb, header, timeline and lineage, one read each", async () => {
    const closed = structuredClone(fixtures["issues.read"]) as Json;
    const anchor = (fixtures["records.lineage"].typed_edges[1]!.evidence as Json[])[0]!;
    Object.assign(closed.issue as Json, {
      state: "closed",
      closure: { version: 2, closed_at: "2026-08-09T12:00:00Z", outcome: "Resolved by the pour.", evidence: [{ ...anchor, role: "resolution" }] },
    });
    const fetchMock = stub((path) => path.includes("/timeline") ? backend(fixtures["issues.timeline"])
      : path.includes("/lineage") ? backend(lineage()) : backend(closed));
    render(<IssueView issueId={ISSUE_ID} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Synthetic Issue" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Work" })).toHaveAttribute("href", "/work");
    expect(within(crumbs).getByRole("link", { name: "Issues" })).toHaveAttribute("href", "/work/issues");
    expect(within(crumbs).getByText("Synthetic Issue")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("issue-closure")).toHaveTextContent("Outcome: Resolved by the pour.");
    expect(screen.getByText(/Project prj_aaaaaaaa11111111/)).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Timeline" })).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Records" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input)).sort()).toEqual([
      `/api/issues/${ISSUE_ID}`, `/api/issues/${ISSUE_ID}/lineage?pageSize=25`, `/api/issues/${ISSUE_ID}/timeline?pageSize=25`,
    ]);
  });

  it("says Issues are not available when the plane is off", async () => {
    stub(() => unsupported());
    render(<IssueView issueId={ISSUE_ID} />);
    expect(await screen.findByText(ISSUE_MESSAGES.notAvailable)).toBeInTheDocument();
  });
});

describe("IssueList", () => {
  it("lists Issues linking to their views and pages with More", async () => {
    const second = { issues: [{ issue_id: "sit_cccccccc33333333", version: 1, state: "open", title: "Synthetic third Issue", updated_at: "2026-08-09T12:00:00.000000Z" }], next_cursor: null, restricted: false };
    const fetchMock = stub((path) => (path.includes("after=") ? backend(second) : backend(fixtures["issues.list"])));
    render(<IssueList />);
    const link = await screen.findByRole("link", { name: "Synthetic Issue" });
    expect(link).toHaveAttribute("href", `/work/issues/${ISSUE_ID}`);
    screen.getByRole("button", { name: "More" }).click();
    expect(await screen.findByRole("link", { name: "Synthetic third Issue" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(["/api/issues", `/api/issues?after=${ISSUE_ID}`]);
  });
});
