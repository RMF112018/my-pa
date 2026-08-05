/**
 * Situations listing route — WP-06 (R5).
 *
 * The principal comes from the verified session only; the listing can only
 * ever return that principal's own situations. This is the web-tier shadow of
 * the Python `list_situations` read path, which is `principal_scoped` so a
 * caller cannot list another principal's situations (MU-AC-05). The response
 * never echoes an identity field back to the client — the session cookie is
 * the only identity carrier.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { syntheticSituations } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  return NextResponse.json({
    situations: syntheticSituations(guard.principal),
    disclosure: syntheticDisclosure("situations"),
  });
}
