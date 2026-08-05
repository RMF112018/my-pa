/**
 * Session establishment and teardown.
 *
 * POST accepts ONLY a synthetic principal key. Claims come from the
 * synthetic provider (server-side), pass through the same validation the
 * real MSAL flow will use, and identity fields in the request body are
 * rejected outright.
 */
import { NextResponse, type NextRequest } from "next/server";
import { validateTokenClaims, rejectCallerSuppliedPrincipal, TokenClaimsError } from "@/lib/auth/claims";
import { findSyntheticPrincipal, SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";
import {
  encodeSession,
  SESSION_COOKIE_NAME,
  SESSION_COOKIE_OPTIONS,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth/session";
import type { PrincipalSession } from "@/contracts/identity";

export async function POST(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json(
      { error: { code: "bad_request", message: "request body must be JSON" } },
      { status: 400 },
    );
  }

  try {
    rejectCallerSuppliedPrincipal(body);
  } catch (error) {
    if (error instanceof TokenClaimsError) {
      return NextResponse.json(
        { error: { code: "caller_supplied_principal", message: error.message } },
        { status: 400 },
      );
    }
    throw error;
  }

  const synthetic = findSyntheticPrincipal(body["syntheticPrincipal"]);
  if (!synthetic) {
    return NextResponse.json(
      { error: { code: "unknown_principal", message: "unknown synthetic principal key" } },
      { status: 400 },
    );
  }

  let claims;
  try {
    claims = validateTokenClaims({ ...synthetic.claims }, SYNTHETIC_MOSS_TENANT_ID);
  } catch (error) {
    if (error instanceof TokenClaimsError) {
      return NextResponse.json(
        { error: { code: "invalid_claims", message: error.message } },
        { status: 401 },
      );
    }
    throw error;
  }

  const principal: PrincipalSession = {
    principalId: `syn-${claims.oid.slice(0, 8)}`,
    tid: claims.tid,
    oid: claims.oid,
    upn: claims.upn,
    displayName: claims.name,
    lifecycleState: "active",
    synthetic: true,
  };

  const token = await encodeSession(principal);
  const response = NextResponse.json({ signedIn: true, upn: principal.upn });
  response.cookies.set(SESSION_COOKIE_NAME, token, {
    ...SESSION_COOKIE_OPTIONS,
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ signedOut: true });
  response.cookies.set(SESSION_COOKIE_NAME, "", { ...SESSION_COOKIE_OPTIONS, maxAge: 0 });
  return response;
}
