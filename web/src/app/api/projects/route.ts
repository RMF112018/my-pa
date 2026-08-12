/**
 * Projects — **real-backed as of WP-11.**
 *
 * `SqlProjectRepository` was real and principal-scoped and unreachable, for
 * exactly the reason `/api/situations` records. `continuity.projects` reaches
 * it, and revision `8f2b6c4d1a37` admits the name to the audited vocabulary.
 *
 * `participants` are opaque person references and carry no display name, no
 * contact detail, and no ranking of any kind. Nothing on this path scores a
 * person (`§22`), and there is no field one could go in.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { backendDisclosure, callGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticProjects } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { BackendProject, ProjectState } from "@/contracts/views";

const SCOPE = "projects";

interface PythonProject {
  readonly project_id: string;
  readonly name: string;
  readonly state: string;
  readonly description: string | null;
  readonly participants: readonly string[];
  readonly opened_at: string;
  readonly closed_at: string | null;
}

function toBackendProject(row: PythonProject): BackendProject {
  return {
    projectId: row.project_id,
    name: row.name,
    state: row.state as ProjectState,
    description: row.description,
    participants: row.participants,
    openedAt: row.opened_at,
    closedAt: row.closed_at,
  };
}

const SCOPE = "projects";

const NO_CAPABILITY =
  "Projects has no backend capability. A principal-scoped Project read model exists in " +
  "PostgreSQL, but no member of the v1 capability set exposes it over the gateway, and " +
  "adding one requires widening a frozen audit CHECK constraint by migration.";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  if (serving.kind === "synthetic") {
    return NextResponse.json({
      shape: "synthetic",
      projects: syntheticProjects(guard.principal),
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await callGateway<{ projects?: readonly PythonProject[] }>(
    guard.principal,
    "continuity.projects",
  );
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);

  return NextResponse.json({
    shape: "backend",
    projects: (outcome.result.projects ?? []).map(toBackendProject),
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, transportLimitations()),
  });
}
