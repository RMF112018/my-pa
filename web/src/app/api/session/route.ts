/**
 * Session establishment and teardown.
 *
 * Four gates on the way in, in this order, and the order is the point — the
 * cheapest refusal that reveals the least comes first:
 *
 * 1. **Cross-site.** `POST` and `DELETE` change state and the cookie is
 *    `sameSite: "lax"`, so a request that did not come from this origin is
 *    refused before anything else happens (`lib/http/origin.ts`).
 * 2. **Mode.** `MYPA_AUTH_MODE` decides whether a synthetic sign-in exists at
 *    all. Unset is a refusal, not a default, and `synthetic` in a production
 *    build is a refusal too. Until WP-05 this route minted a session for either
 *    hardcoded principal with no gate whatsoever — the deployment did not have
 *    to be a development one, and nothing said so.
 * 3. **Caller-supplied identity.** The body may not carry `principal_id`,
 *    `principalId`, `tid`, or `oid`, at any depth.
 * 4. **Claims.** The synthetic provider's own claims go through the same
 *    validation a real token's will, against the *configured* home tenant
 *    rather than a constant this module holds.
 *
 * Sign-in mints a fresh `sid` and registers it, which revokes any session that
 * principal already held — so a session identifier from before the sign-in
 * cannot be carried across it. Sign-out revokes the `sid` server-side *and*
 * clears the cookie; the first is what makes replaying the cookie fail, and the
 * second is only tidiness.
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  validateTokenClaims,
  rejectCallerSuppliedPrincipal,
  TokenClaimsError,
} from "@/lib/auth/claims";
import { findSyntheticPrincipal } from "@/lib/auth/synthetic";
import { authMode, homeTenantId } from "@/lib/auth/mode";
import {
  encodeSession,
  newSessionId,
  verifySessionEnvelope,
  SESSION_COOKIE_NAME,
  SESSION_COOKIE_OPTIONS,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth/session";
import { registerSession, revokeSession } from "@/lib/auth/session-registry";
import { isSameOrigin } from "@/lib/http/origin";
import type { PrincipalSession } from "@/contracts/identity";

function refuse(code: string, message: string, status: number): NextResponse {
  return NextResponse.json({ error: { code, message } }, { status });
}

/** The cross-site gate both methods share. */
function crossSite(request: NextRequest): NextResponse | null {
  return isSameOrigin(request)
    ? null
    : refuse("cross_site_request", "this endpoint refuses cross-site requests", 403);
}

/**
 * The configured mode, or the operator-facing refusal.
 *
 * A misconfiguration answers `500`, deliberately: it is not the visitor's
 * request that is wrong, and answering `401` would hide a deployment fault
 * behind a login screen — the same reason `verifySession` throws rather than
 * returning `null` when the signing key is missing.
 */
function configuredMode(): { mode: "synthetic" | "entra" } | { failure: NextResponse } {
  try {
    return { mode: authMode() };
  } catch (error) {
    return {
      failure: refuse(
        "auth_mode_not_configured",
        error instanceof Error ? error.message : "MYPA_AUTH_MODE is not usable",
        500,
      ),
    };
  }
}

export async function POST(request: NextRequest) {
  const blocked = crossSite(request);
  if (blocked) return blocked;

  const configured = configuredMode();
  if ("failure" in configured) return configured.failure;

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return refuse("bad_request", "request body must be JSON", 400);
  }

  try {
    rejectCallerSuppliedPrincipal(body);
  } catch (error) {
    if (error instanceof TokenClaimsError) {
      return refuse("caller_supplied_principal", error.message, 400);
    }
    throw error;
  }

  if (configured.mode !== "synthetic") {
    // The synthetic principals do not exist outside the synthetic mode. Refused
    // rather than falling through to a real sign-in, which this route does not
    // implement: `lib/auth/msal.config.ts` is the seam, and a live app
    // registration is operator-gated and out of scope.
    return refuse(
      "synthetic_sign_in_disabled",
      "MYPA_AUTH_MODE is 'entra'; the synthetic provider is not available",
      403,
    );
  }

  const synthetic = findSyntheticPrincipal(body["syntheticPrincipal"]);
  if (!synthetic) {
    return refuse("unknown_principal", "unknown synthetic principal key", 400);
  }

  let claims;
  try {
    claims = validateTokenClaims({ ...synthetic.claims }, homeTenantId());
  } catch (error) {
    if (error instanceof TokenClaimsError) {
      return refuse("invalid_claims", error.message, 401);
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

  const sid = newSessionId();
  const token = await encodeSession(principal, sid);
  // Registered before the cookie is handed out, and registering revokes any
  // session this principal already held.
  registerSession(principal.principalId, sid);
  const response = NextResponse.json({ signedIn: true, upn: principal.upn });
  response.cookies.set(SESSION_COOKIE_NAME, token, {
    ...SESSION_COOKIE_OPTIONS,
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}

export async function DELETE(request: NextRequest) {
  const blocked = crossSite(request);
  if (blocked) return blocked;

  // Revoke first, clear second. Clearing the cookie is a request the holder may
  // decline; revoking the `sid` is not, and it is what makes a replay of the
  // exact same cookie value fail afterwards.
  const envelope = await verifySessionEnvelope(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (envelope) revokeSession(envelope.sid);

  const response = NextResponse.json({ signedOut: true });
  response.cookies.set(SESSION_COOKIE_NAME, "", { ...SESSION_COOKIE_OPTIONS, maxAge: 0 });
  return response;
}
