/**
 * Server-side route guard helpers.
 *
 * Every app API route derives its principal from the verified session
 * cookie — never from the request payload — and rejects payloads that
 * carry identity fields.
 */
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth/session";
import { rejectCallerSuppliedPrincipal, TokenClaimsError } from "@/lib/auth/claims";
import type { PrincipalSession } from "@/contracts/identity";

export type Guarded =
  | { ok: true; principal: PrincipalSession }
  | { ok: false; response: NextResponse };

/** Resolve the principal from the session cookie or produce a 401. */
export async function requirePrincipal(request: NextRequest): Promise<Guarded> {
  const principal = await verifySession(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: { code: "unauthenticated", message: "no valid session" } },
        { status: 401 },
      ),
    };
  }
  return { ok: true, principal };
}

/** Parse a JSON body and refuse caller-supplied identity fields. */
export async function readCleanBody(
  request: NextRequest,
): Promise<{ ok: true; body: Record<string, unknown> } | { ok: false; response: NextResponse }> {
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return {
      ok: false,
      response: NextResponse.json(
        { error: { code: "bad_request", message: "request body must be JSON" } },
        { status: 400 },
      ),
    };
  }
  try {
    rejectCallerSuppliedPrincipal(body);
  } catch (error) {
    if (error instanceof TokenClaimsError) {
      return {
        ok: false,
        response: NextResponse.json(
          { error: { code: "caller_supplied_principal", message: error.message } },
          { status: 400 },
        ),
      };
    }
    throw error;
  }
  return { ok: true, body };
}
