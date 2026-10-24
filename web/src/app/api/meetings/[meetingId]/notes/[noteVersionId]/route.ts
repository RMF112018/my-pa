import type { NextRequest } from "next/server";
import type { MeetingsNotesReadVersionResult } from "@/lib/api/decode/capabilities/meetings.notes.read_version";
import { invalidWorkRequest, isCanonicalId, workGet } from "@/lib/api/work-route";

/**
 * One exact note version of one Meeting (record lineage S1 contract section
 * 7.4), read only when the user opens an evidence anchor. `includeBody` must be
 * stated explicitly; a body the request did not ask for is refused.
 */
type Context = { params: Promise<{ meetingId: string; noteVersionId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { meetingId, noteVersionId } = await context.params;
  if (!isCanonicalId(meetingId, "mtg")) return invalidWorkRequest("meetingId was malformed");
  if (!isCanonicalId(noteVersionId, "mnote")) return invalidWorkRequest("noteVersionId was malformed");
  return workGet(request, `meeting-note:${meetingId}`, "meetings.notes.read_version", {
    includeBody: { gateway: "include_body", type: "boolean", required: true },
  }, { meeting_id: meetingId, note_version_id: noteVersionId }, {
    strictQuery: true,
    project: (result, payload) => {
      const { note } = result as MeetingsNotesReadVersionResult;
      if (note.meeting_id !== meetingId || note.note_version_id !== noteVersionId) return null;
      if (payload.include_body !== true && note.body_markdown !== undefined) return null;
      return { ...result };
    },
  });
}
