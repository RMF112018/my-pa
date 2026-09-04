import { NextResponse, type NextRequest } from "next/server";
import { PEOPLE_PAGE_FIELDS, peopleGet, peopleInvalid } from "@/lib/api/people-route";

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ entityId: string }> },
) {
  const { entityId } = await context.params;
  const perspective = request.nextUrl.searchParams.get("perspective")?.trim() ?? "";
  if (!perspective) {
    return noStore(peopleInvalid("perspective is required and must be project or participant"));
  }
  return peopleGet(
    request,
    "people-participations",
    "entities.participations.list",
    { ...PEOPLE_PAGE_FIELDS, perspective: { gateway: "perspective", type: "string" } },
    { entity_id: entityId },
  );
}
