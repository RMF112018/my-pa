import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { IssueLineageTable } from "@/components/issues/issue-lineage-table";
import { ISSUE_MESSAGES } from "@/components/issues/presentation";

/*
 * AT-024 (S3, web component): the Issue lineage table (S3 contract section
 * 7.6). Each page is the committed Python fixture re-rooted at the Issue.
 */
type Json = Record<string, unknown>;
const ISSUE_ID = "sit_aaaaaaaa11111111";
const FIRST = `/api/issues/${ISSUE_ID}/lineage?pageSize=25`;

function page(): Json {
  const value = structuredClone(fixtures["records.lineage"]) as Json;
  value.root = { family: "situation", record_id: ISSUE_ID };
  return value;
}
function backend(body: Json): Response { return Response.json({ shape: "backend", ...body, disclosure: {} }); }
function stub(answer: (path: string) => Response) {
  const fetchMock = vi.fn<typeof fetch>(async (input) => answer(String(input)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("IssueLineageTable", () => {
  it("renders nodes with their path explanations and record links", async () => {
    stub(() => backend(page()));
    render(<IssueLineageTable issueId={ISSUE_ID} />);
    const nodes = await screen.findByRole("table", { name: "Records" });
    const rows = within(nodes).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    expect(within(rows[0]!).getByRole("link", { name: "Task tsk_aaaaaaaa11111111" })).toHaveAttribute("href", "/work/tasks/tsk_aaaaaaaa11111111");
    expect(within(rows[0]!).getByText("The Issue itself")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Meeting note version mnote_aaaaaaaa11111111")).toBeInTheDocument();
    expect(within(rows[1]!).queryByRole("link")).toBeNull();
    expect(within(rows[1]!).getByText("Reached from a Task via originated from")).toBeInTheDocument();
    expect(within(rows[2]!).getByRole("link", { name: "Issue: Synthetic Issue" })).toHaveAttribute("href", `/work/issues/${ISSUE_ID}`);
    expect(within(rows[2]!).getByText("Reached from a Task via member of")).toBeInTheDocument();
    expect(within(rows[3]!).getByRole("link", { name: "Meeting mtg_aaaaaaaa11111111" })).toHaveAttribute("href", "/work/meetings/mtg_aaaaaaaa11111111");
    expect(within(rows[3]!).getByText("Reached from a Meeting note version via note version of")).toBeInTheDocument();
    const links = screen.getByRole("table", { name: "Links" });
    const origin = within(links).getByTestId("lineage-link-irl_bbbbbbbb22222222");
    expect(within(origin).getByText("originated from")).toBeInTheDocument();
    expect(within(origin).getByText("user confirmed")).toBeInTheDocument();
    expect(within(origin).getByText("local operator")).toBeInTheDocument();
    expect(within(origin).getByText("Meeting note version 1, characters 16–36 (origin)")).toBeInTheDocument();
    // Anchors open the drilldown, only on explicit action.
    expect(within(origin).getByRole("button", { name: "Open note version" })).toHaveAttribute("aria-expanded", "false");
  });

  it("shows the restricted, truncated and restart messages", async () => {
    const answer = page();
    Object.assign(answer, { complete_state: "truncated_budget", qualifiers: ["truncated_budget", "restricted_evidence"] });
    stub(() => backend(answer));
    const { unmount } = render(<IssueLineageTable issueId={ISSUE_ID} />);
    const section = await screen.findByRole("region", { name: "Lineage" });
    expect(await within(section).findByText(ISSUE_MESSAGES.truncated)).toBeInTheDocument();
    expect(within(section).getByText(ISSUE_MESSAGES.restricted)).toBeInTheDocument();
    expect(section.textContent).not.toMatch(/\b\d+ (more|hidden|other|records?|links?|edges?|nodes?)\b/i);
    unmount();
    vi.unstubAllGlobals();
    // A restart answer after page 1 replaces what was shown and discloses nothing.
    const restart = page();
    Object.assign(restart, {
      root: { family: "situation", record_id: ISSUE_ID }, selected_issue_id: null, issues_matching_root: [], nodes: [], typed_edges: [],
      virtual_native_edges: [], complete_state: "scope_changed_restart_required", qualifiers: ["scope_changed_restart_required"], next_cursor: null,
    });
    const first = page();
    first.next_cursor = "eyJ2IjoxfQ";
    const fetchMock = stub((path) => (path.includes("cursor=") ? backend(restart) : backend(first)));
    render(<IssueLineageTable issueId={ISSUE_ID} />);
    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));
    expect(await screen.findByText(ISSUE_MESSAGES.restart)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Start again" }));
    await waitFor(() => expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([FIRST, `${FIRST}&cursor=eyJ2IjoxfQ`, FIRST]));
  });

  it("renders a contested related context and states the anchor availability in words", async () => {
    const answer = page();
    const edge = (answer.typed_edges as Json[])[1]!;
    Object.assign(edge, {
      relation_type: "related_context", lifecycle_state: "contested",
      from: { family: "meeting", record_id: "mtg_aaaaaaaa11111111" }, to: { family: "task", record_id: "tsk_aaaaaaaa11111111" },
    });
    (edge.evidence as Json[])[0]!.availability = "restricted";
    stub(() => backend(answer));
    render(<IssueLineageTable issueId={ISSUE_ID} />);
    const row = await screen.findByTestId("lineage-link-irl_bbbbbbbb22222222");
    expect(within(row).getByText("related to")).toBeInTheDocument();
    expect(within(row).getByText("contested")).toBeInTheDocument();
    expect(within(row).getByText(/restricted by your access$/)).toBeInTheDocument();
  });
});
