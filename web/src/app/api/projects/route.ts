/**
 * Projects — **not backend-backed at this head, and it says so.**
 *
 * `SqlProjectRepository` is real and principal-scoped in exactly the way
 * `SqlSituationRepository` is, and it is unreachable for exactly the same reason:
 * no member of the v1 capability set exposes it over `POST /v1/{capability}`, and
 * adding one requires widening the frozen `audit_events.capability` CHECK by
 * migration. See `/api/pulse` for the full form of that argument.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { notImplemented, resolveServing } from "@/lib/api/serving";
import { syntheticProjects } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

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
  if (serving.kind === "backend") return notImplemented(SCOPE, NO_CAPABILITY);

  return NextResponse.json({
    shape: "synthetic",
    projects: syntheticProjects(guard.principal),
    disclosure: syntheticDisclosure(SCOPE),
  });
}
