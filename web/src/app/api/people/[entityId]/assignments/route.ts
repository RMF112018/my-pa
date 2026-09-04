import type { NextRequest } from "next/server";
import { PEOPLE_PAGE_FIELDS, peopleGet } from "@/lib/api/people-route";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ entityId: string }> },
) {
  const { entityId } = await context.params;
  return peopleGet(
    request,
    "people-assignments",
    "entities.assignments.list",
    { ...PEOPLE_PAGE_FIELDS, activeOnly: { gateway: "active_only", type: "boolean" } },
    { entity_id: entityId },
  );
}
