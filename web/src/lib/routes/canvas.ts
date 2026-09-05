/** Canonical Canvas/Map address. The read surface lives at `/canvas`. */
export function canvasHome(): "/canvas" {
  return "/canvas";
}

export type CanvasMapQuery = {
  readonly focusEntityId?: string;
  readonly scopeEntityId?: string;
  readonly hops?: number;
  readonly relationshipTypes?: readonly string[] | string;
  readonly asOf?: string;
  readonly pageSize?: number;
  readonly after?: string;
};

/**
 * Seeded Map URL. Query names MUST match GET /api/people/graph:
 * focusEntityId, scopeEntityId, hops, relationshipTypes, asOf, pageSize, after.
 * Omit empty/undefined keys. Encode values. relationshipTypes as comma-joined string.
 * canvasMap() / canvasMap({}) === canvasHome()
 */
export function canvasMap(query?: CanvasMapQuery): string {
  if (query === undefined) {
    return canvasHome();
  }

  const params = new URLSearchParams();
  setQueryValue(params, "focusEntityId", query.focusEntityId);
  setQueryValue(params, "scopeEntityId", query.scopeEntityId);
  if (query.hops !== undefined) {
    params.set("hops", String(query.hops));
  }
  if (query.relationshipTypes !== undefined) {
    const joined =
      typeof query.relationshipTypes === "string"
        ? query.relationshipTypes
        : query.relationshipTypes.join(",");
    setQueryValue(params, "relationshipTypes", joined);
  }
  setQueryValue(params, "asOf", query.asOf);
  if (query.pageSize !== undefined) {
    params.set("pageSize", String(query.pageSize));
  }
  setQueryValue(params, "after", query.after);

  const encoded = params.toString();
  return encoded.length === 0 ? canvasHome() : `${canvasHome()}?${encoded}`;
}

function setQueryValue(params: URLSearchParams, name: string, value: string | undefined) {
  if (value === undefined || value === "") {
    return;
  }
  params.set(name, value);
}
