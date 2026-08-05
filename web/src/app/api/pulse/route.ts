/**
 * Pulse read model stub — WP-02. Principal-scoped synthetic fixtures.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { syntheticPulse, syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  return NextResponse.json({
    items: syntheticPulse(guard.principal),
    disclosure: syntheticDisclosure("pulse"),
  });
}
