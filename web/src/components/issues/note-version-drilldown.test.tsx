import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { NoteVersionDrilldown } from "@/components/issues/note-version-drilldown";
import type { EvidenceAnchorView } from "@/lib/api/decode/capabilities/records.lineage";

/*
 * AT-024 (S3, web component): the note-version drilldown (S3 contract section
 * 7.6). The cited version is read only on explicit action; a superseded
 * version offers the current note as a separate action and region.
 */
type Json = Record<string, unknown>;
const anchor = (fixtures["records.lineage"].typed_edges[1]!.evidence as unknown as EvidenceAnchorView[])[0]!;
const NOTE_PATH = "/api/meetings/mtg_aaaaaaaa11111111/notes/mnote_aaaaaaaa11111111?includeBody=true";
const MEETING_PATH = "/api/meetings/mtg_aaaaaaaa11111111";
const CURRENT_BODY = "Synthetic current note: the slab pour moved to Monday.";

function backend(body: Json): Response { return Response.json({ shape: "backend", ...body, disclosure: {} }); }
function meeting(): Json {
  return {
    meeting: {
      meeting_id: "mtg_aaaaaaaa11111111", meeting_series_id: null, series_title: null, series_version: null,
      title: "Synthetic site meeting", status: "scheduled", start_at: "2026-08-09T12:00:00Z", end_at: null,
      timezone_name: "UTC", location_text: null, project_id: null, version: 3, updated_at: "2026-08-09T12:00:00Z",
      virtual_meeting_url: null, description: null, created_at: "2026-08-09T12:00:00Z", cancelled_at: null,
      attendees: [], attachments: [],
      notes: { note_version_id: "mnote_bbbbbbbb22222222", version_number: 2, body_markdown: CURRENT_BODY, recorded_at: "2026-08-09T12:00:00Z" },
    },
  };
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

describe("NoteVersionDrilldown", () => {
  it("opens a cited note version only on explicit action and offers the current note separately", async () => {
    const fetchMock = stub((path) => (path === MEETING_PATH ? backend(meeting()) : backend(fixtures["meetings.notes.read_version"])));
    render(<NoteVersionDrilldown anchor={anchor} />);
    const open = screen.getByRole("button", { name: "Open note version" });
    // Nothing is read before the user asks.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(open).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(open);
    const body = fixtures["meetings.notes.read_version"].note.body_markdown;
    expect(await screen.findByText(body)).toBeInTheDocument();
    expect(screen.getByText(Array.from(body).slice(16, 36).join("").trim())).toBeInTheDocument();
    expect(screen.getByText("Version 1; a later version is current")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([NOTE_PATH]);
    // The current note is its own action, its own read and its own region.
    expect(screen.queryByText(CURRENT_BODY)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Show the current note" }));
    const current = await screen.findByRole("region", { name: "Current note" });
    expect(within(current).getByText(CURRENT_BODY)).toBeInTheDocument();
    expect(within(current).queryByText(body)).toBeNull();
    expect(screen.getByText("Version 1; the current version is 2")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([NOTE_PATH, MEETING_PATH]);
  });

  it("offers no current-note action for the current version, and nothing for a Capture anchor", async () => {
    const currentNote = structuredClone(fixtures["meetings.notes.read_version"]) as Json;
    (currentNote.note as Json).is_current = true;
    stub(() => backend(currentNote));
    const { unmount } = render(<NoteVersionDrilldown anchor={anchor} />);
    await userEvent.click(screen.getByRole("button", { name: "Open note version" }));
    expect(await screen.findByText("Version 1 (current)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show the current note" })).toBeNull();
    unmount();
    const capture = { ...anchor, family: "capture_version", root_id: "cap_aaaaaaaa11111111", version_id: "capver_aaaaaaaa11111111" } as EvidenceAnchorView;
    const { container } = render(<NoteVersionDrilldown anchor={capture} />);
    expect(container).toBeEmptyDOMElement();
  });
});
