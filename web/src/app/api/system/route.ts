/**
 * System disclosure — what is and is not connected, read from the build rather
 * than asserted about it.
 *
 * Backed by the Python `capabilities.get`, which derives its manifest from the
 * application's own dispatch table: a capability reports `available` exactly
 * when a handler is bound to it, and readiness is counted off that manifest.
 * This route used to return a hardcoded `schemaHead` and an empty
 * `connectedSources` list beside a synthetic disclosure — three constants that
 * would have kept reporting whatever they were last edited to say. The schema
 * head is gone rather than corrected: a migration revision restated in the web
 * tier is a claim nothing here can check, and it was already stale by three
 * revisions.
 *
 * **Connected sources are reported as unknown, not as none.** No capability in
 * the v1 family enumerates a principal's configured sources — `sources.list`
 * takes a `source_id` and lists that container's children, and `sources.status`
 * requires exactly one named subject — so this tier cannot produce the list.
 * `null` plus a stated limitation is the truthful answer; `[]` would assert that
 * nothing is connected, which this route has no way to know.
 *
 * **A disabled Graph connector is reported as deliberately off.** It is not a
 * degraded source and must never appear as one. Microsoft Graph is retained in
 * the product definition and off by default. Browser Entra/MSAL sign-in is
 * retired; Graph connector activation remains a separate concern.
 *
 * **Morning Intelligence readiness is `reports.resolve_set`, not system health.**
 * `cycle_run_id` is discovered from `reports.list` the same way WP11 does — the
 * first listed item — then `morning_brief_inputs` is resolved. Aggregate and
 * per-member states are returned as the handler emitted them. READY is not
 * mapped to a healthy system. A missing heartbeat is unknown, never healthy.
 *
 * **PWA fields are labelled pending WP26.** Cache identity, update channel, and
 * offline/sync status are not invented. Git SHA / deployed artifact identity is
 * not restated (WP29).
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import {
  backendDisclosure,
  invokeGateway,
  transportLimitations,
  type GatewayOutcome,
} from "@/lib/api/gateway";
import type { CapabilitiesGetResult } from "@/lib/api/decode/capabilities/capabilities.get";
import type { ReportsListResult } from "@/lib/api/decode/capabilities/reports.list";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { PrincipalSession } from "@/contracts/identity";

const SCOPE = "system";
const MORNING_BRIEF_SET_ID = "morning_brief_inputs";

/** Stated on every response, backend-served or not. Graph is off by decision. */
const GRAPH_CONNECTOR = {
  state: "off_by_default",
  detail:
    "Microsoft Graph is retained in the product definition and is not the active " +
    "personal-data ingestion path. It is deliberately off — not a degraded or failing " +
    "source. Browser Entra/MSAL is retired; Graph connector activation remains a " +
    "separate concern.",
} as const;

const SOURCES_UNKNOWN =
  "Connected sources cannot be enumerated: no v1 capability lists a principal's " +
  "configured sources, so this build reports them as unknown rather than as none.";

const PWA_PENDING = {
  fields: "PWA_FIELDS_PENDING_WP26",
  detail:
    "Service-worker cache identity, update channel, and offline/sync status are not " +
    "reported. Those fields belong to UI-IMP-WP26 and are not invented here.",
} as const;

const PWA_LIMITATION =
  "PWA_FIELDS_PENDING_WP26: service-worker cache identity, update channel, and " +
  "offline/sync status are not reported on this route.";

type IntelligenceTruth =
  | { state: "resolved"; result: ReportsResolveSetResult }
  | { state: "no_cycle"; detail: string }
  | { state: "unavailable"; detail: string };

/**
 * Discover `cycle_run_id` from `reports.list` (first listed item), then resolve
 * `morning_brief_inputs`. Same capabilities WP11 uses; no new reports surface.
 */
async function loadMorningBriefIntelligence(
  principal: PrincipalSession,
): Promise<IntelligenceTruth> {
  const listed = (await invokeGateway(
    principal,
    "reports.list",
  )) as GatewayOutcome<ReportsListResult>;
  if (!listed.ok) {
    return { state: "unavailable", detail: listed.error.message };
  }
  const cycleRunId = listed.result.items[0]?.cycle_run_id;
  if (typeof cycleRunId !== "string") {
    return {
      state: "no_cycle",
      detail:
        "reports.list returned no artifact, so cycle_run_id is unknown and " +
        "morning_brief_inputs was not resolved.",
    };
  }
  const resolved = (await invokeGateway(principal, "reports.resolve_set", {
    cycle_run_id: cycleRunId,
    set_id: MORNING_BRIEF_SET_ID,
  })) as GatewayOutcome<ReportsResolveSetResult>;
  if (!resolved.ok) {
    return { state: "unavailable", detail: resolved.error.message };
  }
  return { state: "resolved", result: resolved.result };
}

function intelligenceLimitation(intelligence: IntelligenceTruth): string | null {
  if (intelligence.state === "resolved") return null;
  return intelligence.detail;
}

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  const identity = {
    identityProvider:
      guard.principal.authenticationProvider ?? (guard.principal.synthetic ? "synthetic" : "entra"),
    // Browser Entra/MSAL is retired; this field stays false and is not a live seam.
    entraConfigured: false,
    graphConnector: GRAPH_CONNECTOR,
    principal: {
      // Disclosure of the caller's own identity back to the caller only.
      principalId: guard.principal.principalId,
      upn: guard.principal.upn,
    },
    pwa: PWA_PENDING,
  };

  if (serving.kind === "synthetic") {
    return NextResponse.json({
      ...identity,
      dataProvider: "synthetic",
      backend: null,
      connectedSources: null,
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await invokeGateway(guard.principal, "capabilities.get");
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);
  const result = outcome.result as CapabilitiesGetResult;
  const intelligence = await loadMorningBriefIntelligence(guard.principal);
  const extra = [
    SOURCES_UNKNOWN,
    PWA_LIMITATION,
    intelligenceLimitation(intelligence),
    ...transportLimitations(),
  ].filter((item): item is string => item !== null);

  return NextResponse.json({
    ...identity,
    dataProvider: "backend",
    backend: {
      manifest: result.manifest,
      readiness: result.readiness,
      workerPlanes: result.worker_planes,
      intelligence,
    },
    connectedSources: null,
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, extra),
  });
}
