import type { NextRequest } from "next/server";
import { workGet, workPost, isCanonicalId, invalidWorkRequest } from "@/lib/api/work-route";

type Context = { params: Promise<{ meetingId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { meetingId } = await context.params;
  if (!isCanonicalId(meetingId, "mtg")) return invalidWorkRequest("meetingId was malformed");
  return workGet(request, `meeting:${meetingId}`, "meetings.read", {}, { meeting_id: meetingId }, { strictQuery: true });
}

// The shared parser validates calendar/offset shape; compare at Python's
// microsecond precision rather than losing a sub-millisecond bound to Date.
function instant(value: string): bigint {
  const fraction = /\.(\d+)/.exec(value)?.[1] ?? "";
  const seconds = value.replace(/\.\d+/, "");
  return BigInt(Date.parse(seconds)) * BigInt(1000) + BigInt(fraction.slice(0, 6).padEnd(6, "0"));
}

export async function PATCH(request: NextRequest, context: Context) {
  const { meetingId } = await context.params;
  if (!isCanonicalId(meetingId, "mtg")) return invalidWorkRequest("meetingId was malformed");
  return workPost(request, `meeting:${meetingId}`, "meetings.update", {
    expectedVersion: { gateway: "expected_version", type: "integer", required: true, minimum: 1 },
    idempotencyKey: { gateway: "idempotency_key", type: "string", required: true, minLength: 1, maxLength: 128, codePointLength: true, storable: true },
    title: { gateway: "title", type: "string", nullable: true, minLength: 1, nonBlank: true, maxLength: 200, codePointLength: true, storable: true },
    startAt: { gateway: "start_at", type: "string", nullable: true, format: "timestamp" },
    endAt: { gateway: "end_at", type: "string", nullable: true, format: "timestamp" },
    timezoneName: { gateway: "timezone_name", type: "string", nullable: true, format: "timezone" },
    status: { gateway: "status", type: "string", nullable: true, values: ["scheduled", "cancelled"] },
    locationText: { gateway: "location_text", type: "string", nullable: true, maxLength: 500, codePointLength: true, storable: true },
    virtualMeetingUrl: { gateway: "virtual_meeting_url", type: "string", nullable: true, minLength: 1, maxLength: 2048, codePointLength: true, storable: true, format: "https-url" },
    description: { gateway: "description", type: "string", nullable: true, maxLength: 100000, codePointLength: true, storable: true },
    projectId: { gateway: "project_id", type: "string", nullable: true, pattern: /^prj_[A-Za-z0-9]{8,64}$/ },
    // Three wire states (operator decision 2026-10-09, retiring AC-007): omitted
    // leaves series membership unchanged and is never sent; a series id attaches
    // or moves the Meeting; an explicit null is forwarded as null and detaches it.
    meetingSeriesId: { gateway: "meeting_series_id", type: "string", nullable: true, pattern: /^mser_[A-Za-z0-9]{8,64}$/ },
    clearFields: {
      gateway: "clear_fields", type: "string-array", maxItems: 5, uniqueItems: true,
      values: ["endAt", "locationText", "virtualMeetingUrl", "description", "projectId"],
      itemMapping: { endAt: "end_at", locationText: "location_text", virtualMeetingUrl: "virtual_meeting_url", description: "description", projectId: "project_id" },
    },
    attendeesReplace: { gateway: "attendees_replace", type: "attendee-array", nullable: true, maxItems: 100 },
    attachmentAddDocumentIds: { gateway: "attachment_add_document_ids", type: "string-array", maxItems: 50, uniqueItems: true, pattern: /^mdoc_[A-Za-z0-9]{8,64}$/ },
    attachmentRemoveIds: { gateway: "attachment_remove_ids", type: "string-array", maxItems: 50, uniqueItems: true, pattern: /^matc_[A-Za-z0-9]{8,64}$/ },
    notesMode: { gateway: "notes_mode", type: "string", nullable: true, values: ["append", "replace"] },
    notesMarkdown: { gateway: "notes_markdown", type: "string", nullable: true, minLength: 1, nonBlank: true, maxLength: 100000, codePointLength: true, storable: true },
  }, { meeting_id: meetingId }, {
    strictQuery: true,
    validate: (payload) => {
      const clears = (payload.clear_fields ?? []) as string[];
      const supplied = (name: string) => payload[name] !== undefined && payload[name] !== null;
      if (supplied("project_id") && clears.includes("project_id")) return "projectId cannot be set and cleared together";
      if (supplied("notes_mode") !== supplied("notes_markdown")) return "notesMode and notesMarkdown must be supplied together";
      if (typeof payload.start_at === "string" && typeof payload.end_at === "string"
          && instant(payload.end_at) < instant(payload.start_at)) return "endAt cannot be before startAt";
      const scalars = ["title", "start_at", "end_at", "timezone_name", "status", "location_text", "virtual_meeting_url", "description", "project_id", "notes_mode", "attendees_replace", "meeting_series_id"];
      // Unlike the other nullable scalars, a null meeting_series_id is material: it detaches.
      const seriesSent = Object.hasOwn(payload, "meeting_series_id");
      if (!scalars.some(supplied) && !seriesSent && clears.length === 0
          && ((payload.attachment_add_document_ids ?? []) as string[]).length === 0
          && ((payload.attachment_remove_ids ?? []) as string[]).length === 0) return "at least one Meeting mutation is required";
      return null;
    },
  });
}
