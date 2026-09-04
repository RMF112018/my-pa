import type { NextRequest } from "next/server";
import { PEOPLE_PAGE_FIELDS, peopleGet } from "@/lib/api/people-route";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ entityId: string }> },
) {
  const { entityId } = await context.params;
  return peopleGet(request, "people-addresses", "entities.addresses.list", PEOPLE_PAGE_FIELDS, {
    entity_id: entityId,
  });
}
