import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import {
  RELATED_ISSUES_EMPTY,
  RELATED_ISSUES_PARTIAL,
  RELATED_ISSUES_TRUNCATED,
  RELATED_ISSUES_UNAVAILABLE,
  RelatedIssuesPanel,
} from "@/components/work/related-issues";

/*
 * AT-024 (S1, web component). The gateway is mocked at `fetch`; the BFF route,
 * decoder and Python shapes are proved by their own tests. The lineage answer
 * here is the committed Python fixture, so a renamed key fails both sides.
 */
type Json = Record<string, unknown>;
const TASK_ID = "tsk_aaaaaaaa11111111";
const LINEAGE_PATH = `/api/records/task/${TASK_ID}/related-issues`;
const NOTE_PATH = "/api/meetings/mtg_aaaaaaaa11111111/notes/mnote_aaaaaaaa11111111?includeBody=true";

function lineage(): Json { return structuredClone(fixtures["records.lineage"]) as Json; }
function backend(body: Json): Response { return Response.json({ shape: "backend", ...body, disclosure: {} }); }
function refusal(status: number, errorClass: string, code: string): Response {
  return Response.json({ state: "unavailable", error: { errorClass, code, message: "refused" } }, { status });
}

function stub(answer: (path: string) => Response) {
  const fetchMock = vi.fn<typeof fetch>(async (input) => answer(String(input)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function paths(fetchMock: ReturnType<typeof stub>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RelatedIssuesPanel", () => {
  it("renders the related Issue with relation, direction, basis and actor class", async () => {
    stub(() => backend(lineage()));
    render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    const panel = await screen.findByRole("region", { name: "Related Issues" });
    expect(await within(panel).findByText(/Issue: Synthetic Issue/)).toBeInTheDocument();
    expect(within(panel).getByText(/State: open/)).toBeInTheDocument();
    expect(within(panel).getByText("Member of this Issue as work")).toBeInTheDocument();
    expect(within(panel).getByText("Originated from a Meeting note version")).toBeInTheDocument();
    const facts = within(panel).getAllByText(/State: active · Basis: user confirmed · Recorded by: local operator/);
    expect(facts).toHaveLength(2);
    expect(within(panel).getByText("Meeting note version 1, characters 16–36")).toBeInTheDocument();
    expect(within(panel).getByText("(origin)")).toBeInTheDocument();
    // No write control of any kind.
    expect(within(panel).queryByRole("textbox")).toBeNull();
    expect(within(panel).getAllByRole("button").map((button) => button.textContent)).toEqual(["Open note version"]);
  });

  it("lists candidate Issues as a radio group and re-queries with the chosen issueId", async () => {
    const ambiguous = lineage();
    Object.assign(ambiguous, {
      selected_issue_id: null,
      issues_matching_root: [
        { issue_id: "sit_aaaaaaaa11111111", title: "Synthetic Issue", state: "open" },
        { issue_id: "sit_bbbbbbbb22222222", title: "Second synthetic Issue", state: "active" },
      ],
      nodes: [{ family: "task", record_id: TASK_ID, depth: 0 }],
      typed_edges: [],
      virtual_native_edges: [],
      complete_state: "unresolved_ambiguity",
    });
    const chosen = lineage();
    chosen.issues_matching_root = ambiguous.issues_matching_root;
    const fetchMock = stub((path) => (path.includes("issueId=") ? backend(chosen) : backend(ambiguous)));
    render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    const group = await screen.findByRole("group", { name: /belongs to several Issues. Choose one/ });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    // Nothing is chosen for the user, and no lineage is shown before a choice.
    expect(radios.every((radio) => !(radio as HTMLInputElement).checked)).toBe(true);
    expect(screen.queryByText(/Member of this Issue/)).toBeNull();
    await userEvent.click(within(group).getByRole("radio", { name: /^Synthetic Issue/ }));
    expect(await screen.findByText("Member of this Issue as work")).toBeInTheDocument();
    expect(paths(fetchMock)).toEqual([LINEAGE_PATH, `${LINEAGE_PATH}?issueId=sit_aaaaaaaa11111111`]);
    expect((screen.getByRole("radio", { name: /^Synthetic Issue/ }) as HTMLInputElement).checked).toBe(true);
  });

  it("shows the empty message when no Issue matches", async () => {
    const none = lineage();
    Object.assign(none, { selected_issue_id: null, issues_matching_root: [], nodes: [{ family: "task", record_id: TASK_ID, depth: 0 }], typed_edges: [], virtual_native_edges: [] });
    stub(() => backend(none));
    render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    expect(await screen.findByText(RELATED_ISSUES_EMPTY)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("shows the partial and truncated messages without hidden counts", async () => {
    for (const [state, message, other] of [
      ["partial_native_history", RELATED_ISSUES_PARTIAL, RELATED_ISSUES_TRUNCATED],
      ["truncated_budget", RELATED_ISSUES_TRUNCATED, RELATED_ISSUES_PARTIAL],
    ] as const) {
      const answer = lineage();
      answer.complete_state = state;
      stub(() => backend(answer));
      const { unmount } = render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
      const panel = await screen.findByRole("region", { name: "Related Issues" });
      expect(await within(panel).findByText(message)).toBeInTheDocument();
      expect(within(panel).queryByText(other)).toBeNull();
      // The Issue that was returned is still shown; nothing counts what was not.
      expect(within(panel).getByText(/Issue: Synthetic Issue/)).toBeInTheDocument();
      expect(panel.textContent).not.toMatch(/\b\d+ (more|hidden|other|records?|links?|edges?)\b/i);
      unmount();
      vi.unstubAllGlobals();
    }
  });

  it("shows the unavailable message on not_found, denied and unavailable", async () => {
    for (const [status, errorClass, code] of [
      [404, "not_found", "not_found"],
      [403, "authorization", "denied"],
      [503, "unavailable", "unavailable"],
      [503, "unavailable", "upstream_contract_invalid"],
    ] as const) {
      stub(() => refusal(status, errorClass, code));
      const { unmount } = render(<RelatedIssuesPanel family="commitment" recordId="cmt_aaaaaaaa11111111" />);
      expect(await screen.findByText(RELATED_ISSUES_UNAVAILABLE), code).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Related Issues" })).toBeInTheDocument();
      unmount();
      vi.unstubAllGlobals();
    }
  });

  it("opens a note-version anchor only on explicit action", async () => {
    const note = structuredClone(fixtures["meetings.notes.read_version"]) as Json;
    const fetchMock = stub((path) => (path === NOTE_PATH ? backend(note) : backend(lineage())));
    render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    const open = await screen.findByRole("button", { name: "Open note version" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/pour the north slab/)).toBeNull();
    expect(paths(fetchMock)).toEqual([LINEAGE_PATH]);
    await userEvent.click(open);
    const close = await screen.findByRole("button", { name: "Hide note version" });
    expect(close).toHaveAttribute("aria-expanded", "true");
    const region = document.getElementById(close.getAttribute("aria-controls")!)!;
    // Code points 16..36 of the synthetic body.
    expect(await within(region).findByText("pour the north slab")).toBeInTheDocument();
    expect(within(region).getByText(/Synthetic note: pour the north slab after the inspection\./)).toBeInTheDocument();
    expect(paths(fetchMock)).toEqual([LINEAGE_PATH, NOTE_PATH]);
    await userEvent.click(close);
    expect(screen.getByRole("button", { name: "Open note version" })).toHaveAttribute("aria-expanded", "false");
    expect(region).not.toBeVisible();
  });

  it("labels a legacy capture anchor as version not recorded", async () => {
    const answer = lineage();
    const edge = (answer.typed_edges as Json[])[1]!;
    (edge.evidence as Json[]).push({
      anchor_id: "ian_bbbbbbbb22222222", family: "capture", root_id: "cap_aaaaaaaa11111111",
      version_kind: "legacy_unversioned", version_id: null, source_version_no: null,
      passage_start_cp: null, passage_end_cp: null, role: "corroborates", availability: "legacy_unversioned",
    });
    stub(() => backend(answer));
    render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    expect(await screen.findByText("Capture, version not recorded")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Open note version" })).toHaveLength(1);
  });

  it("labels an archived capture anchor as capture archived", async () => {
    const answer = lineage();
    const edge = (answer.typed_edges as Json[])[1]!;
    edge.to = { family: "capture_version", record_id: "capver_aaaaaaaa11111111" };
    edge.evidence = [{
      anchor_id: "ian_cccccccc33333333", family: "capture_version", root_id: "cap_aaaaaaaa11111111",
      version_kind: "immutable_version", version_id: "capver_aaaaaaaa11111111", source_version_no: 2,
      passage_start_cp: 0, passage_end_cp: 9, role: "origin", availability: "archived",
    }];
    stub(() => backend(answer));
    render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    expect(await screen.findByText("Capture version 2, Capture archived")).toBeInTheDocument();
    expect(screen.getByText("Originated from a Capture version")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open note version" })).toBeNull();
  });

  it("renders nothing when the capability is unsupported", async () => {
    const fetchMock = stub(() => refusal(503, "unavailable", "unsupported"));
    const { container } = render(<RelatedIssuesPanel family="constraint" recordId="cst_aaaaaaaa11111111" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(screen.queryByText(RELATED_ISSUES_UNAVAILABLE)).toBeNull();
  });

  it("issues exactly one lineage request per render", async () => {
    const fetchMock = stub(() => backend(lineage()));
    const { rerender } = render(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    expect(await screen.findByText("Member of this Issue as work")).toBeInTheDocument();
    rerender(<RelatedIssuesPanel family="task" recordId={TASK_ID} />);
    await waitFor(() => expect(screen.getByText("Originated from a Meeting note version")).toBeInTheDocument());
    // One read for the record: never per Issue, per edge or per node.
    expect(paths(fetchMock)).toEqual([LINEAGE_PATH]);
    expect(paths(fetchMock).some((path) => path.includes("/api/issues"))).toBe(false);
  });
});
