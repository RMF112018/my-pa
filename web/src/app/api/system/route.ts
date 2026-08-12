/**
 * System disclosure endpoint — WP-02. Reports what is and is not connected.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { msalSeamConfig } from "@/lib/auth/msal.config";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  return NextResponse.json({
    workPackage: "WP-03",
    schemaHead: "e7f3a9c2d514",
    identityProvider: guard.principal.synthetic ? "synthetic" : "entra",
    entraConfigured: msalSeamConfig().enabled,
    connectedSources: [],
    principal: {
      // Disclosure of the caller's own identity back to the caller only.
      principalId: guard.principal.principalId,
      upn: guard.principal.upn,
    },
    disclosure: syntheticDisclosure("system"),
  });
}
