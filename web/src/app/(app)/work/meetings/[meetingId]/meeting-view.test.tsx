import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { MEETING_UNAVAILABLE, MeetingView } from "./meeting-view";

/*
 * AT-024 (S3, views): the minimal Meeting view (S3 contract section 7.6, D-18)
 * with the S1 related-Issue panel for the Meeting. The gateway is mocked at
 * `fetch`; the lineage answer is the committed Python fixture re-rooted.
 */
type Json = Record<string, unknown>;
const MEETING_ID = "mtg_aaaaaaaa11111111";
const MEETING_PATH = `/api/meetings/${MEETING_ID}`;
const LINEAGE_PATH = `/api/records/meeting/${MEETING_ID}/related-issues`;

function backend(body: Json): Response { return Response.json({ shape: "backend", ...body, disclosure: {} }); }
function meeting(): Json {
  return {
    meeting: {
      meeting_id: MEETING_ID, meeting_series_id: null, series_title: null, series_version: null,
      title: "Synthetic site meeting", status: "scheduled", start_at: "2026-08-09T12:00:00Z", end_at: null,
      timezone_name: "UTC", location_text: null, project_id: null, version: 1, updated_at: "2026-08-09T12:00:00Z",
      virtual_meeting_url: null, description: null, created_at: "2026-08-09T12:00:00Z", cancelled_at: null,
      attendees: [], attachments: [], notes: null,
    },
  };
}
function meetingLineage(candidates: number): Json {
  const value = structuredClone(fixtures["records.lineage"]) as Json;
  value.root = { family: "meeting", record_id: MEETING_ID };
  if (candidates > 1) {
    Object.assign(value, {
      selected_issue_id: null,
      issues_matching_root: [
        { issue_id: "sit_aaaaaaaa11111111", title: "First synthetic Issue", state: "open" },
        { issue_id: "sit_bbbbbbbb22222222", title: "Second synthetic Issue", state: "active" },
        { issue_id: "sit_cccccccc33333333", title: "Third synthetic Issue", state: "suspended" },
      ],
      nodes: [{ family: "meeting", record_id: MEETING_ID, depth: 0, reached_from: null, reached_via: null }],
      typed_edges: [], virtual_native_edges: [],
      complete_state: "unresolved_ambiguity", qualifiers: ["unresolved_ambiguity"],
    });
  }
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

describe("MeetingView", () => {
  it("mounts the related-Issue panel on the Meeting view", async () => {
    const fetchMock = stub((path) => (path === MEETING_PATH ? backend(meeting()) : backend(meetingLineage(3))));
    render(<MeetingView meetingId={MEETING_ID} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Synthetic site meeting" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    const panel = await screen.findByRole("region", { name: "Related Issues" });
    // A Meeting in 3 Issues asks for one before it shows any lineage.
    const group = await within(panel).findByRole("group", { name: /belongs to several Issues. Choose one/ });
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
    expect(within(panel).queryByText(/^Issue: /)).toBeNull();
    const paths = () => fetchMock.mock.calls.map(([input]) => String(input)).sort();
    expect(paths()).toEqual([MEETING_PATH, LINEAGE_PATH].sort());
    await userEvent.click(within(group).getByRole("radio", { name: /^Second synthetic Issue/ }));
    expect(paths()).toContain(`${LINEAGE_PATH}?issueId=sit_bbbbbbbb22222222`);
  });

  it("says the Meeting is unavailable when it cannot be read", async () => {
    stub((path) => (path === MEETING_PATH
      ? Response.json({ error: { errorClass: "not_found", code: "not_found", message: "x" } }, { status: 404 })
      : backend(meetingLineage(1))));
    render(<MeetingView meetingId={MEETING_ID} />);
    expect(await screen.findByText(MEETING_UNAVAILABLE)).toBeInTheDocument();
  });
});
