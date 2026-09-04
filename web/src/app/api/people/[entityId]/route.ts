import type { NextRequest } from "next/server";
import { peopleGet } from "@/lib/api/people-route";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ entityId: string }> },
) {
  const { entityId } = await context.params;
  return peopleGet(request, "people-get", "entities.get", {}, { entity_id: entityId });
}
