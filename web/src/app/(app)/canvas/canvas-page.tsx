/**
 * Map — a seeded neighborhood. Default remains the WP16 read Map; Arrange
 * is an opt-in overlay on a seeded graph, not a directory of everyone.
 * The page reaches `entities.graph` (and, when showing nodes,
 * `canvas.workspace.get`) through `invokeGateway` rather than through a
 * People or workspace BFF GET.
 */
import type { ReactNode } from "react";
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { DirectoryList } from "@/components/canvas/directory-list";
import { CanvasMapClient } from "@/components/canvas/canvas-map-client";
import { canvasMap, type CanvasMapQuery } from "@/lib/routes/canvas";
import { peopleHome } from "@/lib/routes/people";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import type { PrincipalSession } from "@/contracts/identity";
import type { EntitiesGraphResult } from "@/lib/api/decode/capabilities/entities.graph";
import type { CanvasPositions } from "@/lib/api/decode/capabilities/canvas.workspace.get";

const SCOPE = "canvas";

const BLURB =
  "Map is a neighborhood of a seed you already hold. " +
  "It is not a directory of everyone.";

function frame(children: ReactNode) {
  return (
    <section aria-labelledby="canvas-heading" className="mx-auto max-w-4xl">
      <h1 id="canvas-heading" className="mb-1 text-2xl font-semibold tracking-tight text-moss-slate">
        Map
      </h1>
      <p className="mb-6 max-w-3xl text-sm text-muted">{BLURB}</p>
      {children}
    </section>
  );
}

function oneParam(
  params: Record<string, string | string[] | undefined>,
  name: string,
): string {
  const raw = params[name];
  return (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
}

function parseOptionalInteger(
  raw: string,
): { readonly kind: "absent" } | { readonly kind: "ok"; readonly value: number } | { readonly kind: "invalid" } {
  if (raw === "") return { kind: "absent" };
  if (/^(0|[1-9]\d*)$/.test(raw)) {
    const value = Number(raw);
    if (Number.isSafeInteger(value)) return { kind: "ok", value };
  }
  return { kind: "invalid" };
}

function splitTypes(raw: string): readonly string[] {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

async function loadWorkspaceOverlay(
  principal: PrincipalSession,
  focusEntityId: string,
  scopeEntityId: string,
): Promise<{ readonly positions: CanvasPositions; readonly version: number }> {
  const seedPayload: Record<string, unknown> = {
    ...(focusEntityId ? { focus_entity_id: focusEntityId } : {}),
    ...(scopeEntityId ? { scope_entity_id: scopeEntityId } : {}),
  };
  const workspace = await invokeGateway(principal, "canvas.workspace.get", seedPayload);
  if (!workspace.ok) {
    return { positions: {}, version: 0 };
  }
  return { positions: workspace.result.positions, version: workspace.result.version };
}

async function neighborhood(
  principal: PrincipalSession,
  result: EntitiesGraphResult,
  disclosure: DisclosureEnvelope,
  query: CanvasMapQuery,
  focusEntityId: string,
  scopeEntityId: string,
  degraded: boolean,
) {
  const overlay = await loadWorkspaceOverlay(principal, focusEntityId, scopeEntityId);
  const cursor = result.next_cursor || disclosure.nextCursor || "";
  const showBanner = degraded || disclosure.truncated || Boolean(cursor);
  return (
    <>
      {showBanner ? (
        <DegradedBanner
          scope="this neighborhood"
          limitations={disclosure.limitations}
          truncated={disclosure.truncated && !cursor}
        />
      ) : null}
      <div className="grid gap-8 lg:grid-cols-2">
        <section aria-labelledby="canvas-directory-heading">
          <h2 id="canvas-directory-heading" className="mb-3 text-base font-semibold text-moss-slate">
            Directory
          </h2>
          <DirectoryList nodes={result.nodes} />
        </section>
        <section aria-labelledby="canvas-map-heading">
          <h2 id="canvas-map-heading" className="mb-3 text-base font-semibold text-moss-slate">
            Neighborhood
          </h2>
          <CanvasMapClient
            nodes={result.nodes}
            edges={result.edges}
            focusEntityId={focusEntityId}
            scopeEntityId={scopeEntityId}
            savedPositions={overlay.positions}
            version={overlay.version}
            graphQuery={query}
          />
        </section>
      </div>
      {cursor ? (
        <p className="mt-4 text-sm">
          <Link
            href={canvasMap({ ...query, after: cursor })}
            className="text-moss-green underline"
            data-testid="canvas-continue"
          >
            Continue neighborhood
          </Link>
        </p>
      ) : null}
    </>
  );
}

export async function CanvasPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const params = await searchParams;
  const focusEntityId = oneParam(params, "focusEntityId");
  const scopeEntityId = oneParam(params, "scopeEntityId");
  const hopsRaw = oneParam(params, "hops");
  const relationshipTypesRaw = oneParam(params, "relationshipTypes");
  const asOf = oneParam(params, "asOf");
  const pageSizeRaw = oneParam(params, "pageSize");
  const after = oneParam(params, "after");

  if (syntheticDataEnabled()) {
    return frame(
      <SurfaceState
        kind="not_implemented"
        title="Map has no synthetic fixture"
        detail="This build is serving the synthetic provider. Map reads the Python entity plane, and no fixture stands in for it — run against the gateway to see real records."
        testId="canvas-synthetic"
      />,
    );
  }

  if (!focusEntityId && !scopeEntityId) {
    return frame(
      <SurfaceState
        kind="empty"
        title="A seed is required"
        detail="Map shows a read-only neighborhood of one seed. Provide focusEntityId or scopeEntityId. This is not a directory of everyone, and an empty URL is not an empty neighborhood."
        testId="canvas-seed-required"
      >
        <p className="mt-3 text-sm">
          <Link href={peopleHome()} className="text-moss-green underline">
            Search People
          </Link>
        </p>
      </SurfaceState>,
    );
  }

  const hops = parseOptionalInteger(hopsRaw);
  const pageSize = parseOptionalInteger(pageSizeRaw);
  if (hops.kind === "invalid" || pageSize.kind === "invalid") {
    const detail =
      hops.kind === "invalid" && pageSize.kind === "invalid"
        ? "hops and pageSize must be integers."
        : hops.kind === "invalid"
          ? "hops must be an integer."
          : "pageSize must be an integer.";
    return frame(
      <SurfaceState
        kind="unavailable"
        title="That map query was not valid"
        detail={detail}
        testId="canvas-unavailable"
      />,
    );
  }

  const relationshipTypes = splitTypes(relationshipTypesRaw);
  const payload: Record<string, unknown> = {
    ...(focusEntityId ? { focus_entity_id: focusEntityId } : {}),
    ...(scopeEntityId ? { scope_entity_id: scopeEntityId } : {}),
    ...(hops.kind === "ok" ? { hops: hops.value } : {}),
    ...(relationshipTypes.length > 0 ? { relationship_types: relationshipTypes } : {}),
    ...(asOf ? { as_of: asOf } : {}),
    ...(pageSize.kind === "ok" ? { page_size: pageSize.value } : {}),
    ...(after ? { after } : {}),
  };

  const query: CanvasMapQuery = {
    ...(focusEntityId ? { focusEntityId } : {}),
    ...(scopeEntityId ? { scopeEntityId } : {}),
    ...(hops.kind === "ok" ? { hops: hops.value } : {}),
    ...(relationshipTypes.length > 0 ? { relationshipTypes } : {}),
    ...(asOf ? { asOf } : {}),
    ...(pageSize.kind === "ok" ? { pageSize: pageSize.value } : {}),
    ...(after ? { after } : {}),
  };

  const outcome = await invokeGateway(principal, "entities.graph", payload);
  if (!outcome.ok && outcome.error.errorClass === "not_found") {
    return frame(
      <SurfaceState
        kind="unavailable"
        title="That neighborhood was not found"
        detail="Nothing is claimed about other seeds or other principals."
        testId="canvas-not-found"
      />,
    );
  }

  const answer = surfaceAnswer(`${SCOPE}:entities.graph`, outcome, (result) => result.nodes.length);

  if (answer.kind === "unavailable") {
    return frame(
      <SurfaceState
        kind="unavailable"
        title="That neighborhood could not be read"
        detail={answer.error.message}
        limitations={answer.disclosure.limitations}
        testId="canvas-unavailable"
      />,
    );
  }

  if (answer.kind === "empty") {
    return frame(
      <SurfaceState
        kind="empty"
        title="That neighborhood holds no nodes"
        detail="The seeded read succeeded and returned no entities. That is a fact about this neighborhood, not an unseeded Map."
        limitations={answer.disclosure.limitations}
        testId="canvas-empty"
      />,
    );
  }

  if (answer.kind === "degraded" && answer.rowCount === 0) {
    const cursor = answer.result.next_cursor || answer.disclosure.nextCursor || "";
    return frame(
      <>
        <DegradedBanner
          scope="this neighborhood"
          limitations={answer.disclosure.limitations}
          truncated={answer.disclosure.truncated && !cursor}
        />
        <SurfaceState
          kind="degraded"
          title="This neighborhood is incomplete and returned nothing"
          detail="Because the read did not cover everything, no node is not the same as an empty neighborhood. Nothing is claimed about who you hold."
        />
        {cursor ? (
          <p className="mt-4 text-sm">
            <Link
              href={canvasMap({ ...query, after: cursor })}
              className="text-moss-green underline"
              data-testid="canvas-continue"
            >
              Continue neighborhood
            </Link>
          </p>
        ) : null}
      </>,
    );
  }

  return frame(
    await neighborhood(
      principal,
      answer.result,
      answer.disclosure,
      query,
      focusEntityId,
      scopeEntityId,
      answer.kind === "degraded",
    ),
  );
}
