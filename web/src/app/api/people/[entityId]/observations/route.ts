import type { NextRequest } from "next/server";
import { PEOPLE_PAGE_FIELDS, peopleGet } from "@/lib/api/people-route";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ entityId: string }> },
) {
  const { entityId } = await context.params;
  return peopleGet(
    request,
    "people-entity-observations",
    "entities.observations.list",
    { ...PEOPLE_PAGE_FIELDS, unresolvedOnly: { gateway: "unresolved_only", type: "boolean" } },
    { entity_id: entityId },
  );
}
