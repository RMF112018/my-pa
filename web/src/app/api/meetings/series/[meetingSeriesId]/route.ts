import type { NextRequest } from "next/server";
import { workPost, isCanonicalId, invalidWorkRequest } from "@/lib/api/work-route";

export async function PATCH(request: NextRequest, context: { params: Promise<{ meetingSeriesId: string }> }) {
  const { meetingSeriesId } = await context.params;
  if (!isCanonicalId(meetingSeriesId, "mser")) return invalidWorkRequest("meetingSeriesId was malformed");
  return workPost(request, `meeting-series:${meetingSeriesId}`, "meetings.series.update", {
    expectedVersion: { gateway: "expected_version", type: "integer", required: true, minimum: 1 },
    idempotencyKey: { gateway: "idempotency_key", type: "string", required: true, minLength: 1, maxLength: 128, codePointLength: true, storable: true },
    title: { gateway: "title", type: "string", required: true, minLength: 1, nonBlank: true, maxLength: 200, codePointLength: true, storable: true },
  }, { meeting_series_id: meetingSeriesId }, { strictQuery: true });
}
