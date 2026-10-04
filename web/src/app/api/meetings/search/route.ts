import { NextRequest } from "next/server";
import { workGet, invalidWorkRequest, type FieldMap } from "@/lib/api/work-route";

const FILTERS = {
  meetingSeriesId: { gateway: "meeting_series_id", type: "string", pattern: /^mser_[A-Za-z0-9]{8,64}$/ },
  projectId: { gateway: "project_id", type: "string", pattern: /^prj_[A-Za-z0-9]{8,64}$/ },
  startAtFrom: { gateway: "start_at_from", type: "string", format: "timestamp" },
  startAtBefore: { gateway: "start_at_before", type: "string", format: "timestamp" },
  attendeeEntityId: { gateway: "attendee_entity_id", type: "string", pattern: /^ent_[A-Za-z0-9]{8,64}$/ },
  attendeeEmail: { gateway: "attendee_email", type: "string", maxLength: 320, codePointLength: true, storable: true, format: "email" },
  status: { gateway: "status", type: "string", values: ["scheduled", "cancelled"] },
  timeScope: { gateway: "time_scope", type: "string", values: ["all", "upcoming", "past"] },
  sortDirection: { gateway: "sort_direction", type: "string", values: ["asc", "desc"] },
  pageSize: { gateway: "page_size", type: "integer", minimum: 1, maximum: 100 },
  after: { gateway: "after", type: "string", pattern: /^mtg_[A-Za-z0-9]{8,64}$/ },
} satisfies FieldMap;

// The shared parser validates calendar/offset shape; compare at Python's
// microsecond precision rather than losing a sub-millisecond bound to Date.
function instant(value: string): bigint {
  const fraction = /\.(\d+)/.exec(value)?.[1] ?? "";
  const seconds = value.replace(/\.\d+/, "");
  return BigInt(Date.parse(seconds)) * BigInt(1000) + BigInt(fraction.slice(0, 6).padEnd(6, "0"));
}

function validateRange(payload: Readonly<Record<string, unknown>>): string | null {
  if (typeof payload.start_at_from === "string" && typeof payload.start_at_before === "string"
      && instant(payload.start_at_from) >= instant(payload.start_at_before)) {
    return "startAtFrom must be before startAtBefore";
  }
  return null;
}

export async function GET(request: NextRequest) {
  const fields = { ...FILTERS, q: { gateway: "query", type: "string", required: true } } satisfies FieldMap;
  // Check repetition before replacing q, so normalization cannot hide it.
  for (const key of request.nextUrl.searchParams.keys()) {
    if (!Object.hasOwn(fields, key) || request.nextUrl.searchParams.getAll(key).length > 1) {
      return invalidWorkRequest("unknown or repeated scalar query field");
    }
  }
  const raw = request.nextUrl.searchParams.get("q");
  if (raw === null) return invalidWorkRequest("q is required");
  // NFC and Python str.split whitespace, including NEL/C0 separators but not BOM.
  const query = raw.normalize("NFC")
    .split(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/u)
    .filter(Boolean).join(" ");
  const length = Array.from(query).length;
  if (length < 1 || length > 512 || /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/u.test(query)) {
    return invalidWorkRequest("q must contain between 1 and 512 valid normalized characters");
  }
  const url = request.nextUrl.clone();
  url.searchParams.set("q", query);
  return workGet(new NextRequest(url, request), "meetings", "meetings.search", fields, {}, {
    strictQuery: true, validate: validateRange,
  });
}
