/**
 * Situations — **real-backed as of WP-11.**
 *
 * `SqlSituationRepository` was already real and already principal-scoped; what
 * was missing was a way to reach it over the transport, and `continuity.situations`
 * is it. Revision `8f2b6c4d1a37` carries the forward `ALTER` that admits the
 * name to the audited capability vocabulary.
 *
 * The listing returns the acting Principal's Situations and nothing else: the
 * repository adds `principal_id = <caller>` to the `SELECT`, so a Situation
 * belonging to another Principal is not filtered out of the answer — it is never
 * in it. The response does not echo a Principal back, because the session cookie
 * is the only identity carrier this tier has.
 *
 * The backend row carries no per-row disclosure and the fixture shape does, so
 * the two are returned as different shapes rather than as one shape with an
 * invented field; `shape` says which one a reader is holding.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticSituations } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { SituationRow } from "@/lib/api/decode/capabilities/continuity.situations";
import type { BackendSituation, SituationState } from "@/contracts/views";

const SCOPE = "situations";

function toBackendSituation(row: SituationRow): BackendSituation {
  return {
    situationId: row.situation_id,
    title: row.title,
    state: row.state as SituationState,
    description: row.description,
    objectRefs: row.object_refs,
    openedAt: row.opened_at,
    closedAt: row.closed_at,
    outcome: row.outcome,
  };
}

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  if (serving.kind === "synthetic") {
    return NextResponse.json({
      shape: "synthetic",
      situations: syntheticSituations(guard.principal),
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await invokeGateway(guard.principal, "continuity.situations");
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);
  const result = outcome.result as { situations: readonly SituationRow[] };

  return NextResponse.json({
    shape: "backend",
    situations: result.situations.map(toBackendSituation),
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, transportLimitations()),
  });
}
