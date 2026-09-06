import { NextResponse, type NextRequest } from "next/server";
import {
  backendDisclosure,
  invokeGateway,
  transportLimitations,
  type GatewayCapability,
} from "@/lib/api/gateway";
import type { CapabilityResults } from "@/lib/api/decode";
import { requirePrincipal } from "@/lib/api/guard";
import { notImplemented, resolveServing } from "@/lib/api/serving";
import { rejectCallerSuppliedPrincipal, TokenClaimsError } from "@/lib/auth/claims";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { PrincipalSession } from "@/contracts/identity";
import type { CaptureSearchMatch } from "@/lib/api/decode/capabilities/capture.search";
import type { CommitmentListEntry } from "@/lib/api/decode/capabilities/commitments.search";
import type { EntitySummary } from "@/lib/api/decode/capabilities/entities.search";
import type { GoodNotesSearchHit } from "@/lib/api/decode/capabilities/goodnotes.search";
import type { KnowledgeSearchMatch } from "@/lib/api/decode/capabilities/knowledge.search";
import type { ReportSearchMatch } from "@/lib/api/decode/capabilities/reports.search";
import type { TaskListEntry } from "@/lib/api/decode/capabilities/tasks.search";

const SCOPE = "search";
const PAGE_SIZE = 10;
const IDENTIFIER = /^[a-z]+_[A-Za-z0-9]{8,64}$/;

type SearchCapability = Extract<
  GatewayCapability,
  | "tasks.search"
  | "commitments.search"
  | "capture.search"
  | "reports.search"
  | "entities.search"
  | "knowledge.search"
  | "goodnotes.search"
>;

type CalledDomain =
  | "tasks"
  | "commitments"
  | "capture"
  | "reports"
  | "entities"
  | "knowledge"
  | "goodnotes";

export type FederatedSearchHit =
  | { readonly domain: "tasks"; readonly capability: "tasks.search"; readonly item: TaskListEntry }
  | {
      readonly domain: "commitments";
      readonly capability: "commitments.search";
      readonly item: CommitmentListEntry;
    }
  | { readonly domain: "capture"; readonly capability: "capture.search"; readonly item: CaptureSearchMatch }
  | { readonly domain: "reports"; readonly capability: "reports.search"; readonly item: ReportSearchMatch }
  | { readonly domain: "entities"; readonly capability: "entities.search"; readonly item: EntitySummary }
  | {
      readonly domain: "knowledge";
      readonly capability: "knowledge.search";
      readonly item: KnowledgeSearchMatch;
    }
  | {
      readonly domain: "goodnotes";
      readonly capability: "goodnotes.search";
      readonly item: GoodNotesSearchHit;
    };

export type DomainCoverage = {
  readonly domain: CalledDomain | "meetings" | "projects" | "canvas" | "relationship_memory";
  readonly capability?: SearchCapability;
  readonly state: "searched" | "degraded" | "unavailable" | "knowledge_not_enrolled" | "omitted";
  readonly hitCount: number;
  readonly reason?: string;
};

type CalledSpec = {
  readonly domain: CalledDomain;
  readonly capability: SearchCapability;
  readonly payload: Record<string, unknown>;
};

const OMITTED: readonly DomainCoverage[] = [
  { domain: "meetings", state: "omitted", hitCount: 0, reason: "no_search_capability" },
  { domain: "projects", state: "omitted", hitCount: 0, reason: "no_search_capability" },
  { domain: "canvas", state: "omitted", hitCount: 0, reason: "no_search_capability" },
  { domain: "relationship_memory", state: "omitted", hitCount: 0, reason: "not_browser_admitted" },
];

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

function invalidRequest(message: string): NextResponse {
  return NextResponse.json(
    { error: { errorClass: "validation", code: "invalid_request", message } },
    { status: 400 },
  );
}

function invalidIdentifier(field: string): NextResponse {
  return NextResponse.json(
    {
      error: {
        errorClass: "validation",
        code: "invalid_identifier",
        message: `${field} must be an opaque identifier of the form prefix_suffix`,
      },
    },
    { status: 400 },
  );
}

function publicResult(result: Record<string, unknown>) {
  return JSON.parse(
    JSON.stringify(result, (key, value) =>
      key === "principal_id" || key === "principalId" ? undefined : value,
    ),
  ) as Record<string, unknown>;
}

function hitItems(
  capability: SearchCapability,
  result: CapabilityResults[SearchCapability],
): readonly unknown[] {
  if (capability === "tasks.search" && "tasks" in result) return result.tasks;
  if (capability === "commitments.search" && "commitments" in result) return result.commitments;
  if (capability === "entities.search" && "entities" in result) return result.entities;
  if (capability === "reports.search" && "items" in result) return result.items;
  if (capability === "goodnotes.search" && "hits" in result) return result.hits;
  if (
    (capability === "capture.search" || capability === "knowledge.search") &&
    "matches" in result
  ) {
    return result.matches;
  }
  return [];
}

function toHits(
  domain: CalledDomain,
  capability: SearchCapability,
  items: readonly unknown[],
): FederatedSearchHit[] {
  return items.map((item) => ({ domain, capability, item }) as FederatedSearchHit);
}

function overallDisclosure(partial: boolean, truncated: boolean): DisclosureEnvelope {
  return {
    scope: SCOPE,
    coverage: partial ? "partial" : "complete",
    freshnessAt: null,
    authority: "derived",
    limitations: [...transportLimitations()],
    truncated,
  };
}

async function searchOne(
  principal: PrincipalSession,
  spec: CalledSpec,
): Promise<{ hits: FederatedSearchHit[]; coverage: DomainCoverage; truncated: boolean }> {
  const outcome = await invokeGateway(principal, spec.capability, spec.payload);
  if (!outcome.ok) {
    return {
      hits: [],
      coverage: {
        domain: spec.domain,
        capability: spec.capability,
        state: "unavailable",
        hitCount: 0,
        reason: outcome.error.code,
      },
      truncated: false,
    };
  }
  const disclosure = backendDisclosure(
    `${SCOPE}:${spec.capability}`,
    outcome.disclosure,
    transportLimitations(),
  );
  if (disclosure.coverage === "unavailable") {
    return {
      hits: [],
      coverage: {
        domain: spec.domain,
        capability: spec.capability,
        state: "unavailable",
        hitCount: 0,
        reason: "unavailable",
      },
      truncated: false,
    };
  }
  const items = hitItems(spec.capability, outcome.result);
  const hits = toHits(spec.domain, spec.capability, items);
  const degraded = disclosure.coverage === "partial";
  return {
    hits,
    coverage: {
      domain: spec.domain,
      capability: spec.capability,
      state: degraded ? "degraded" : "searched",
      hitCount: hits.length,
    },
    truncated: disclosure.truncated,
  };
}

export async function searchGet(request: NextRequest): Promise<NextResponse> {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return noStore(guard.response);

  const params = request.nextUrl.searchParams;
  const query = params.get("q")?.trim() ?? "";
  if (!query) {
    return noStore(invalidRequest("Search requires q; an empty query is not a listing"));
  }

  try {
    rejectCallerSuppliedPrincipal(Object.fromEntries(params.entries()));
  } catch (error) {
    if (error instanceof TokenClaimsError) {
      return noStore(
        NextResponse.json(
          { error: { code: "caller_supplied_principal", message: error.message } },
          { status: 400 },
        ),
      );
    }
    throw error;
  }

  const enrollmentRaw = params.get("enrollmentId")?.trim() ?? "";
  if (enrollmentRaw && !IDENTIFIER.test(enrollmentRaw)) {
    return noStore(invalidIdentifier("enrollmentId"));
  }

  const serving = resolveServing();
  if (serving.kind === "refused") return noStore(serving.response);
  if (serving.kind === "synthetic") {
    return noStore(
      notImplemented(
        SCOPE,
        "The synthetic provider has no federated search fixture. Federated search requires the executable Python search capabilities.",
      ),
    );
  }

  const invoked: CalledSpec[] = [
    { domain: "tasks", capability: "tasks.search", payload: { query, page_size: PAGE_SIZE } },
    {
      domain: "commitments",
      capability: "commitments.search",
      payload: { query, page_size: PAGE_SIZE },
    },
    { domain: "capture", capability: "capture.search", payload: { query, page_size: PAGE_SIZE } },
    { domain: "reports", capability: "reports.search", payload: { query, page_size: PAGE_SIZE } },
    { domain: "entities", capability: "entities.search", payload: { query, page_size: PAGE_SIZE } },
    { domain: "goodnotes", capability: "goodnotes.search", payload: { query, page_size: PAGE_SIZE } },
  ];
  if (enrollmentRaw) {
    invoked.push({
      domain: "knowledge",
      capability: "knowledge.search",
      payload: { enrollment_id: enrollmentRaw, query, page_size: PAGE_SIZE },
    });
  }

  const settled = await Promise.all(invoked.map((spec) => searchOne(guard.principal, spec)));
  const hits = settled.flatMap((row) => row.hits);
  const coverage: DomainCoverage[] = settled.map((row) => row.coverage);
  if (!enrollmentRaw) {
    coverage.push({
      domain: "knowledge",
      capability: "knowledge.search",
      state: "knowledge_not_enrolled",
      hitCount: 0,
    });
  }
  coverage.push(...OMITTED);

  const incomplete = coverage.some(
    (row) =>
      row.state === "omitted" ||
      row.state === "unavailable" ||
      row.state === "degraded" ||
      row.state === "knowledge_not_enrolled",
  );
  const truncated = settled.some((row) => row.truncated);

  return noStore(
    NextResponse.json(
      publicResult({
        shape: "backend",
        query,
        hits,
        coverage,
        disclosure: overallDisclosure(incomplete, truncated),
      }),
    ),
  );
}
