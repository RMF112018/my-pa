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
 * the product definition and off by default; the Entra authentication this shell
 * uses for identity is a separate concern from Graph connector activation.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { msalSeamConfig } from "@/lib/auth/msal.config";
import { backendDisclosure, callGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

const SCOPE = "system";

/** Stated on every response, backend-served or not. Graph is off by decision. */
const GRAPH_CONNECTOR = {
  state: "off_by_default",
  detail:
    "Microsoft Graph is retained in the product definition and is not the active " +
    "personal-data ingestion path. It is deliberately off — not a degraded or failing " +
    "source. Entra authentication for identity is a separate concern from Graph activation.",
} as const;

const SOURCES_UNKNOWN =
  "Connected sources cannot be enumerated: no v1 capability lists a principal's " +
  "configured sources, so this build reports them as unknown rather than as none.";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  const identity = {
    identityProvider:
      guard.principal.authenticationProvider ?? (guard.principal.synthetic ? "synthetic" : "entra"),
    entraConfigured: msalSeamConfig().enabled,
    graphConnector: GRAPH_CONNECTOR,
    principal: {
      // Disclosure of the caller's own identity back to the caller only.
      principalId: guard.principal.principalId,
      upn: guard.principal.upn,
    },
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

  const outcome = await callGateway<{
    manifest: unknown;
    readiness: unknown;
    worker_planes: unknown;
  }>(
    guard.principal,
    "capabilities.get",
  );
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);

  return NextResponse.json({
    ...identity,
    dataProvider: "backend",
    backend: {
      manifest: outcome.result.manifest,
      readiness: outcome.result.readiness,
      workerPlanes: outcome.result.worker_planes,
    },
    connectedSources: null,
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, [
      SOURCES_UNKNOWN,
      ...transportLimitations(),
    ]),
  });
}
