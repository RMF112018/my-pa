import { requiredCollection, workRequest } from "@/lib/api/work-client";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { FederatedHit, SearchCoverage } from "@/lib/search/presentation";

const IDENTIFIER = /^[a-z]+_[A-Za-z0-9]{8,64}$/;

export type FederatedSearchResponse = {
  readonly shape: string;
  readonly query: string;
  readonly hits: readonly FederatedHit[];
  readonly coverage: readonly SearchCoverage[];
  readonly disclosure?: DisclosureEnvelope;
};

/** Pass through an already-held enrollment. Never mint one. */
export function admittedEnrollmentId(raw: string | null | undefined): string | undefined {
  const value = raw?.trim() ?? "";
  return IDENTIFIER.test(value) ? value : undefined;
}

export async function fetchFederatedSearch(
  query: string,
  options: { readonly enrollmentId?: string; readonly signal?: AbortSignal } = {},
): Promise<FederatedSearchResponse> {
  const params = new URLSearchParams({ q: query });
  const enrollmentId = admittedEnrollmentId(options.enrollmentId);
  if (enrollmentId) params.set("enrollmentId", enrollmentId);
  const body = await workRequest<Partial<FederatedSearchResponse>>(`/api/search?${params.toString()}`, {
    method: "GET",
    signal: options.signal,
  });
  return {
    shape: typeof body.shape === "string" ? body.shape : "backend",
    query: typeof body.query === "string" ? body.query : query,
    hits: requiredCollection(body.hits, "hits") as readonly FederatedHit[],
    coverage: requiredCollection(body.coverage, "coverage"),
    disclosure: body.disclosure,
  };
}
