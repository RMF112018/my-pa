import { type NextRequest, type NextResponse } from "next/server";
import { peopleGet, peopleInvalid } from "@/lib/api/people-route";

const SEARCH_FIELDS = {
  q: { gateway: "query", type: "string" },
  entityType: { gateway: "entity_type", type: "string" },
  pageSize: { gateway: "page_size", type: "integer" },
  after: { gateway: "after", type: "string" },
} as const;

const RESOLVE_FIELDS = {
  reference: { gateway: "reference", type: "string" },
  namespace: { gateway: "namespace", type: "string" },
  entityType: { gateway: "entity_type", type: "string" },
  scopeEntityId: { gateway: "scope_entity_id", type: "string" },
  asOf: { gateway: "as_of", type: "string" },
} as const;

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

/**
 * People collection reads. This is not a directory listing.
 *
 * * `?q=` -> `entities.search`
 * * `?reference=` -> `entities.resolve`
 * * neither, or both, is refused rather than enumerating every entity
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const query = params.get("q")?.trim() ?? "";
  const reference = params.get("reference")?.trim() ?? "";
  if (query && reference) {
    return noStore(peopleInvalid("ask either q or reference, not both; this is not a directory"));
  }
  if (query) {
    return peopleGet(request, "people-search", "entities.search", SEARCH_FIELDS);
  }
  if (reference) {
    return peopleGet(request, "people-resolve", "entities.resolve", RESOLVE_FIELDS);
  }
  return noStore(
    peopleInvalid("People requires q for search or reference for resolve; it does not list every entity"),
  );
}