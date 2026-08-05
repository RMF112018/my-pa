/**
 * Projects listing route — WP-06 (R5).
 *
 * Principal-scoped exactly like the situations route: the principal is taken
 * from the verified session, never the payload, and the listing returns only
 * that principal's own projects — the web-tier shadow of the Python
 * `list_projects` `principal_scoped` read path (MU-AC-05).
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { syntheticProjects } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  return NextResponse.json({
    projects: syntheticProjects(guard.principal),
    disclosure: syntheticDisclosure("projects"),
  });
}
