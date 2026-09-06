/**
 * Client presentation for federated Search hits.
 *
 * Hrefs are derived here from typed hit identities. The BFF payload is not
 * rewritten. Capture body text is never copied. No client relevance score.
 */
import type { CaptureSearchMatch } from "@/lib/api/decode/capabilities/capture.search";
import type { CommitmentListEntry } from "@/lib/api/decode/capabilities/commitments.search";
import type { EntitySummary } from "@/lib/api/decode/capabilities/entities.search";
import type {
  KnowledgeRank,
  KnowledgeSearchMatch,
} from "@/lib/api/decode/capabilities/knowledge.search";
import type { ReportSearchMatch } from "@/lib/api/decode/capabilities/reports.search";
import type { TaskListEntry } from "@/lib/api/decode/capabilities/tasks.search";

export const SEARCH_DOMAIN_ORDER = [
  "tasks",
  "commitments",
  "capture",
  "reports",
  "entities",
  "knowledge",
] as const;

export type SearchDomain = (typeof SEARCH_DOMAIN_ORDER)[number];

export type FederatedHit =
  | { readonly domain: "tasks"; readonly item: TaskListEntry }
  | { readonly domain: "commitments"; readonly item: CommitmentListEntry }
  | { readonly domain: "capture"; readonly item: CaptureSearchMatch }
  | { readonly domain: "reports"; readonly item: ReportSearchMatch }
  | { readonly domain: "entities"; readonly item: EntitySummary }
  | { readonly domain: "knowledge"; readonly item: KnowledgeSearchMatch };

export type SearchCoverage = {
  readonly domain: string;
  readonly state: string;
  readonly hitCount: number;
  readonly reason?: string;
};

export type PresentedHit = {
  readonly domain: SearchDomain;
  readonly key: string;
  readonly label: string;
  readonly detail: string | null;
  readonly href: string | null;
  readonly rank?: KnowledgeRank;
};

export type PresentedGroup = {
  readonly domain: SearchDomain;
  readonly heading: string;
  readonly hits: readonly PresentedHit[];
};

export const DOMAIN_HEADINGS: Record<SearchDomain, string> = {
  tasks: "Tasks",
  commitments: "Commitments",
  capture: "Capture",
  reports: "Reports",
  entities: "People",
  knowledge: "Knowledge",
};

function identityHref(path: string, id: string): string | null {
  const trimmed = id.trim();
  if (!trimmed) return null;
  return `${path}/${encodeURIComponent(trimmed)}`;
}

export function captureSearchHref(captureId: string, versionId: string): string | null {
  const capture = captureId.trim();
  const version = versionId.trim();
  if (!capture || !version) return null;
  const params = new URLSearchParams();
  params.set("captureId", capture);
  params.set("versionId", version);
  return `/knowledge?${params.toString()}`;
}

export function knowledgeSearchHref(
  knowledgeId: string,
  enrollmentId: string | undefined,
): string | null {
  const knowledge = knowledgeId.trim();
  const enrollment = enrollmentId?.trim() ?? "";
  if (!knowledge || !enrollment) return null;
  const params = new URLSearchParams();
  params.set("knowledgeId", knowledge);
  params.set("enrollmentId", enrollment);
  return `/knowledge?${params.toString()}`;
}

function presentHit(hit: FederatedHit, enrollmentId: string | undefined): PresentedHit {
  switch (hit.domain) {
    case "tasks":
      return {
        domain: "tasks",
        key: hit.item.task_id,
        label: hit.item.title,
        detail: hit.item.lifecycle_state,
        href: identityHref("/work/tasks", hit.item.task_id),
      };
    case "commitments":
      return {
        domain: "commitments",
        key: hit.item.commitment_id,
        label: hit.item.title,
        detail: hit.item.state,
        href: identityHref("/work/commitments", hit.item.commitment_id),
      };
    case "capture":
      return {
        domain: "capture",
        key: `${hit.item.capture_id}:${hit.item.version_id}`,
        label: hit.item.capture_id,
        detail: `Version ${hit.item.version_number} · ${hit.item.character_count} characters · ${hit.item.recorded_at}`,
        href: captureSearchHref(hit.item.capture_id, hit.item.version_id),
      };
    case "reports":
      return {
        domain: "reports",
        key: hit.item.report_id,
        label: hit.item.title,
        detail: hit.item.snippet,
        href: identityHref("/intelligence/reports", hit.item.report_id),
      };
    case "entities":
      return {
        domain: "entities",
        key: hit.item.entity_id,
        label: hit.item.display_name,
        detail: hit.item.entity_id,
        href: identityHref("/people", hit.item.entity_id),
      };
    case "knowledge":
      return {
        domain: "knowledge",
        key: hit.item.knowledge_id,
        label: hit.item.label,
        detail: hit.item.snippet,
        href: knowledgeSearchHref(hit.item.knowledge_id, enrollmentId),
        rank: hit.item.rank,
      };
  }
}

/**
 * Group hits in BFF/domain order. Per-domain order is the upstream hit order.
 * Knowledge rank is copied onto the row for display inside that group only.
 */
export function presentFederatedHits(
  hits: readonly FederatedHit[],
  enrollmentId?: string,
): readonly PresentedGroup[] {
  return SEARCH_DOMAIN_ORDER.flatMap((domain) => {
    const presented = hits
      .filter((hit) => hit.domain === domain)
      .map((hit) => presentHit(hit, enrollmentId));
    if (presented.length === 0) return [];
    return [{ domain, heading: DOMAIN_HEADINGS[domain], hits: presented }];
  });
}
