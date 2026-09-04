import { type NextRequest, type NextResponse } from "next/server";
import { peopleGet, peopleInvalid } from "@/lib/api/people-route";

const GRAPH_FIELDS = {
  focusEntityId: { gateway: "focus_entity_id", type: "string" },
  scopeEntityId: { gateway: "scope_entity_id", type: "string" },
  hops: { gateway: "hops", type: "integer" },
  relationshipTypes: { gateway: "relationship_types", type: "string-list" },
  asOf: { gateway: "as_of", type: "string" },
  pageSize: { gateway: "page_size", type: "integer" },
  after: { gateway: "after", type: "string" },
} as const;

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

/**
 * Seeded neighborhood read. This is not a directory of every entity.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const focus = params.get("focusEntityId")?.trim() ?? "";
  const scope = params.get("scopeEntityId")?.trim() ?? "";
  if (!focus && !scope) {
    return noStore(
      peopleInvalid(
        "People graph requires focusEntityId or scopeEntityId; it is not a directory",
      ),
    );
  }
  return peopleGet(request, "people-graph", "entities.graph", GRAPH_FIELDS);
}
