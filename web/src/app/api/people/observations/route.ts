import type { NextRequest } from "next/server";
import { PEOPLE_PAGE_FIELDS, peopleGet } from "@/lib/api/people-route";

export function GET(request: NextRequest) {
  return peopleGet(request, "people-observations", "entities.observations.list", {
    ...PEOPLE_PAGE_FIELDS,
    entityId: { gateway: "entity_id", type: "string" },
    unresolvedOnly: { gateway: "unresolved_only", type: "boolean" },
  });
}
