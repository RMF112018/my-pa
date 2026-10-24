"use client";

/**
 * The note-version drilldown of the Issue view (record lineage S3 contract
 * section 7.6). The cited note version is read only when the user opens it
 * (`meetings.notes.read_version`, body included). When it is not the current
 * version, the current note is a separate, explicit action (`meetings.read`)
 * shown in its own region, so the 2 bodies are never mixed.
 */
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import type { EvidenceAnchorView } from "@/lib/api/decode/capabilities/records.lineage";
import type { MeetingNoteVersion } from "@/lib/api/decode/capabilities/meetings.notes.read_version";
import { fetchMeeting, fetchNoteVersion } from "@/lib/api/work-client";

type Cited =
  | { readonly kind: "closed" }
  | { readonly kind: "loading" }
  | { readonly kind: "open"; readonly note: MeetingNoteVersion & { readonly body_markdown: string } }
  | { readonly kind: "failed" };

type Current =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "open"; readonly versionNumber: number; readonly body: string }
  | { readonly kind: "failed" };

export const NOTE_UNREADABLE = "The note version could not be read.";
export const CURRENT_UNREADABLE = "The current note could not be read.";

export function NoteVersionDrilldown({ anchor }: { readonly anchor: EvidenceAnchorView }) {
  const regionId = useId();
  const currentId = useId();
  const [expanded, setExpanded] = useState(false);
  const [cited, setCited] = useState<Cited>({ kind: "closed" });
  const [current, setCurrent] = useState<Current>({ kind: "idle" });
  const versionId = anchor.version_id;
  if (anchor.family !== "meeting_note_version" || versionId === null) return null;

  async function toggle() {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (cited.kind === "open" || versionId === null) return;
    setCited({ kind: "loading" });
    try {
      const read = await fetchNoteVersion(anchor.root_id, versionId);
      const body = read.note.body_markdown;
      setCited(body === undefined ? { kind: "failed" } : { kind: "open", note: { ...read.note, body_markdown: body } });
    } catch {
      setCited({ kind: "failed" });
    }
  }

  async function showCurrent() {
    setCurrent({ kind: "loading" });
    try {
      const { meeting } = await fetchMeeting(anchor.root_id);
      setCurrent(meeting.notes === null
        ? { kind: "failed" }
        : { kind: "open", versionNumber: meeting.notes.version_number, body: meeting.notes.body_markdown });
    } catch {
      setCurrent({ kind: "failed" });
    }
  }

  const note = cited.kind === "open" ? cited.note : null;
  const passage = note !== null && anchor.passage_start_cp !== null && anchor.passage_end_cp !== null
    // Offsets count Unicode code points, as the server does.
    ? Array.from(note.body_markdown).slice(anchor.passage_start_cp, anchor.passage_end_cp).join("")
    : null;

  return (
    <div className="mt-1">
      <Button size="sm" variant="secondary" aria-expanded={expanded} aria-controls={regionId} onClick={() => void toggle()}>
        {expanded ? "Hide note version" : "Open note version"}
      </Button>
      <div id={regionId} hidden={!expanded} className="mt-2">
        {!expanded ? null : cited.kind === "loading" ? (
          <p role="status" className="text-muted">Reading the note version…</p>
        ) : cited.kind === "failed" ? (
          <p className="text-muted">{NOTE_UNREADABLE}</p>
        ) : note !== null ? (
          <>
            {note.is_current ? (
              <p className="text-xs text-muted">Version {note.version_number} (current)</p>
            ) : current.kind === "open" ? (
              <p className="text-xs text-muted">Version {note.version_number}; the current version is {current.versionNumber}</p>
            ) : (
              <p className="text-xs text-muted">Version {note.version_number}; a later version is current</p>
            )}
            {passage !== null ? (
              <figure className="mb-2 mt-1">
                <figcaption className="text-xs text-muted">Cited passage</figcaption>
                <blockquote className="mt-1 whitespace-pre-wrap break-words border-l-2 border-moss-slate/30 pl-2">{passage}</blockquote>
              </figure>
            ) : null}
            <p className="text-xs text-muted">Cited note version text</p>
            <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-moss-slate/15 p-2 font-sans text-sm">{note.body_markdown}</pre>
            {note.is_current ? null : (
              <div className="mt-2">
                {current.kind === "idle" || current.kind === "failed" ? (
                  <Button size="sm" variant="secondary" aria-controls={currentId} onClick={() => void showCurrent()}>
                    Show the current note
                  </Button>
                ) : null}
                <div id={currentId} className="mt-2">
                  {current.kind === "loading" ? <p role="status" className="text-muted">Reading the current note…</p> : null}
                  {current.kind === "failed" ? <p className="text-muted">{CURRENT_UNREADABLE}</p> : null}
                  {current.kind === "open" ? (
                    <section aria-label="Current note">
                      <p className="text-xs text-muted">Current note, version {current.versionNumber}</p>
                      <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-moss-slate/15 p-2 font-sans text-sm">{current.body}</pre>
                    </section>
                  ) : null}
                </div>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
