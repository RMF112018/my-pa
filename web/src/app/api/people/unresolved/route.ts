import type { NextRequest } from "next/server";
import { PEOPLE_PAGE_FIELDS, peopleGet } from "@/lib/api/people-route";

export function GET(request: NextRequest) {
  return peopleGet(request, "people-unresolved", "entities.unresolved_mentions", PEOPLE_PAGE_FIELDS);
}
