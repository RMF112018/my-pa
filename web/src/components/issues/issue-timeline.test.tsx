import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { IssueTimeline, TIMELINE_UNAVAILABLE } from "@/components/issues/issue-timeline";
import { ISSUE_MESSAGES } from "@/components/issues/presentation";

/*
 * AT-024 (S3, web component): the Issue timeline (S3 contract section 7.6). The
 * gateway is mocked at `fetch`; each page is the committed Python fixture, so a
 * renamed key fails both sides.
 */
type Json = Record<string, unknown>;
const ISSUE_ID = "sit_aaaaaaaa11111111";
const FIRST = `/api/issues/${ISSUE_ID}/timeline?pageSize=25`;

function page(): Json { return structuredClone(fixtures["issues.timeline"]) as Json; }
function backend(body: Json): Response { return Response.json({ shape: "backend", ...body, disclosure: {} }); }
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

describe("IssueTimeline", () => {
  it("renders timeline entries in server order and labels partial native entries", async () => {
    const answer = page();
    answer.next_cursor = null;
    stub(() => backend(answer));
    render(<IssueTimeline issueId={ISSUE_ID} />);
    const section = await screen.findByRole("region", { name: "Timeline" });
    const items = await within(section).findAllByTestId("timeline-entry");
    expect(items.map((item) => item.querySelector("p.font-medium")?.textContent)).toEqual([
      "Issue created",
      "Linked to a Project",
      "Member recorded: a Task as work",
      "A Task originated from a Meeting note version: contested",
      "Responsibility handed from you to Entity ent_aaaaaaaa11111111",
      expect.stringMatching(/^Handoff retimed to /),
      "Task updated",
      "Constraint state changed",
    ]);
    // A native Task event shows no value, only that none was recorded.
    expect(within(items[6]!).getByText(/Field values were not recorded for this change/)).toBeInTheDocument();
    expect(within(items[6]!).queryByText(/Synthetic/)).toBeNull();
    // A Constraint event shows its recorded ball-in-court.
    expect(within(items[7]!).getByText(/Ball in court: Synthetic Engineer of Record/)).toBeInTheDocument();
    expect(within(items[7]!).getByText(/Recorded state: in progress/)).toBeInTheDocument();
    expect(within(items[7]!).queryByText(/Field values were not recorded/)).toBeNull();
    // Subjects link to their views; a Constraint is named in text.
    expect(within(items[2]!).getByRole("link", { name: `Task tsk_aaaaaaaa11111111` })).toHaveAttribute("href", "/work/tasks/tsk_aaaaaaaa11111111");
    expect(within(items[7]!).queryByRole("link")).toBeNull();
    expect(within(section).queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("shows the hidden-data message without a count", async () => {
    for (const [code, text] of [
      ["restricted_evidence", ISSUE_MESSAGES.restricted],
      ["truncated_budget", ISSUE_MESSAGES.truncated],
      ["partial_native_history", ISSUE_MESSAGES.partialTimeline],
    ] as const) {
      const answer = page();
      Object.assign(answer, { complete_state: code, qualifiers: [code], next_cursor: null });
      stub(() => backend(answer));
      const { unmount } = render(<IssueTimeline issueId={ISSUE_ID} />);
      const section = await screen.findByRole("region", { name: "Timeline" });
      expect(await within(section).findByText(text), code).toBeInTheDocument();
      expect(section.textContent).not.toMatch(/\b\d+ (more|hidden|other|records?|links?|entries|events?)\b/i);
      unmount();
      vi.unstubAllGlobals();
    }
    // A restart answer shows only the message and a restart that reads page 1 again.
    const restart = page();
    Object.assign(restart, { entries: [], complete_state: "scope_changed_restart_required", qualifiers: ["scope_changed_restart_required"], next_cursor: null });
    const fetchMock = stub(() => backend(restart));
    render(<IssueTimeline issueId={ISSUE_ID} />);
    expect(await screen.findByText(ISSUE_MESSAGES.restart)).toBeInTheDocument();
    expect(screen.queryAllByTestId("timeline-entry")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Start again" }));
    await waitFor(() => expect(paths(fetchMock)).toEqual([FIRST, FIRST]));
  });

  it("requests the next timeline page with the cursor only", async () => {
    const first = page();
    const second = page();
    second.entries = (second.entries as Json[]).slice(0, 1).map((entry) => ({ ...entry, entry_id: "irs_bbbbbbbb22222222", action: "updated" }));
    second.next_cursor = null;
    const fetchMock = stub((path) => (path.includes("cursor=") ? backend(second) : backend(first)));
    render(<IssueTimeline issueId={ISSUE_ID} />);
    const more = await screen.findByRole("button", { name: "Show more" });
    await userEvent.click(more);
    expect(await screen.findByText("Issue updated")).toBeInTheDocument();
    expect(paths(fetchMock)).toEqual([FIRST, `${FIRST}&cursor=${first.next_cursor as string}`]);
    expect(screen.getAllByTestId("timeline-entry")).toHaveLength(9);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("says the timeline is unavailable, and renders nothing when unsupported", async () => {
    stub(() => Response.json({ error: { errorClass: "unavailable", code: "unavailable", message: "x" } }, { status: 503 }));
    const { unmount } = render(<IssueTimeline issueId={ISSUE_ID} />);
    expect(await screen.findByText(TIMELINE_UNAVAILABLE)).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();
    stub(() => Response.json({ error: { errorClass: "unavailable", code: "unsupported", message: "x" } }, { status: 503 }));
    const { container } = render(<IssueTimeline issueId={ISSUE_ID} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
