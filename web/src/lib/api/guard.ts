/**
 * Server-side route guard helpers.
 *
 * Every app API route derives its principal from the opaque session cookie SID
 * via `resolveSessionPrincipal` — never from the request payload — and rejects
 * payloads that carry identity fields.
 *
 * A dead or missing SID is 401. A missing session-service secret or a down
 * gateway is 503 `authority_unavailable`, never 401.
 */
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { AuthorityUnavailableError, resolveSessionPrincipal } from "@/lib/auth/principal";
import { rejectCallerSuppliedPrincipal, TokenClaimsError } from "@/lib/auth/claims";
import type { PrincipalSession } from "@/contracts/identity";

export type Guarded =
  | { ok: true; principal: PrincipalSession }
  | { ok: false; response: NextResponse };

/** Resolve the principal from the session cookie or produce 401 / 503. */
export async function requirePrincipal(request: NextRequest): Promise<Guarded> {
  try {
    const principal = await resolveSessionPrincipal(
      request.cookies.get(SESSION_COOKIE_NAME)?.value,
      request,
    );
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
  } catch (error) {
    if (error instanceof AuthorityUnavailableError) {
      return {
        ok: false,
        response: NextResponse.json(
          { error: { code: "authority_unavailable", message: "session authority unavailable" } },
          { status: 503 },
        ),
      };
    }
    throw error;
  }
}

/** Parse a JSON body and refuse caller-supplied identity fields. */
export async function readCleanBody(
  request: NextRequest,
): Promise<{ ok: true; body: Record<string, unknown> } | { ok: false; response: NextResponse }> {
  let body: unknown;
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
  if (body === null || Array.isArray(body) || typeof body !== "object") {
    return {
      ok: false,
      response: NextResponse.json(
        { error: { code: "bad_request", message: "request body must be a JSON object" } },
        { status: 400 },
      ),
    };
  }
  const cleanBody = body as Record<string, unknown>;
  try {
    rejectCallerSuppliedPrincipal(cleanBody);
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
  return { ok: true, body: cleanBody };
}
