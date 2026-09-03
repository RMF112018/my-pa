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
 *    build is a refusal too. `passkey` is the production web mode; this route
 *    does not mint a synthetic identity in that mode.
 * 3. **Caller-supplied identity.** The body may not carry `principal_id`,
 *    `principalId`, `tid`, or `oid`, at any depth.
 * 4. **Claims.** The synthetic provider's own claims go through the same
 *    validation a real token's will, against the *configured* home tenant
 *    rather than a constant this module holds.
 *
 * Sign-in asks Python to issue a durable SID (`issueSyntheticSession`) and
 * sets that raw SID as the HttpOnly cookie. The SID is never returned in
 * browser JSON. A prior cookie SID, if present and different, is revoked after
 * the new cookie is set — session fixation of *this* browser only, not every
 * SID for the principal.
 *
 * Sign-out revokes the SID via the session-service *and* clears the cookie;
 * the first is what makes replaying the cookie fail.
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  validateTokenClaims,
  rejectCallerSuppliedPrincipal,
  TokenClaimsError,
} from "@/lib/auth/claims";
import {
  PrincipalNotAdmissibleError,
  resolveAdmissibleSyntheticPrincipal,
} from "@/lib/auth/synthetic";
import { authMode, homeTenantId, type AuthMode } from "@/lib/auth/mode";
import {
  parseOpaqueSessionSid,
  sessionReplayBinding,
  SESSION_COOKIE_NAME,
  SESSION_COOKIE_OPTIONS,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth/session";
import {
  issueSyntheticSession,
  revokeSid,
  MissingSessionServiceSecretError,
  SessionServiceUnavailableError,
} from "@/lib/auth/session-service";
import { requirePrincipal } from "@/lib/api/guard";
import { isSameOrigin } from "@/lib/http/origin";

function refuse(code: string, message: string, status: number): NextResponse {
  return NextResponse.json({ error: { code, message } }, { status });
}

function authorityUnavailable(): NextResponse {
  return refuse("authority_unavailable", "session authority unavailable", 503);
}

function asAuthorityFailure(error: unknown): NextResponse | null {
  if (
    error instanceof MissingSessionServiceSecretError ||
    error instanceof SessionServiceUnavailableError
  ) {
    return authorityUnavailable();
  }
  return null;
}

function setSessionCookie(response: NextResponse, issuedSid: string): void {
  response.cookies.set(SESSION_COOKIE_NAME, issuedSid, {
    ...SESSION_COOKIE_OPTIONS,
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

function clearSessionCookie(response: NextResponse): void {
  response.cookies.set(SESSION_COOKIE_NAME, "", { ...SESSION_COOKIE_OPTIONS, maxAge: 0 });
}

/** Revoke a prior cookie SID after the new cookie is set. Never fails the sign-in. */
async function revokePriorSid(
  request: NextRequest,
  issuedSid: string,
): Promise<void> {
  const prior = parseOpaqueSessionSid(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!prior || prior === issuedSid) return;
  try {
    await revokeSid(prior, request);
  } catch {
    // Fixation cleanup is best-effort. The new session is already issued.
  }
}

/** The cross-site gate both mutating methods share. */
function crossSite(request: NextRequest): NextResponse | null {
  return isSameOrigin(request)
    ? null
    : refuse("cross_site_request", "this endpoint refuses cross-site requests", 403);
}

/** Current authenticated replay authority, derived from this request's cookie SID. */
export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;
  const sid = parseOpaqueSessionSid(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!sid) return refuse("unauthenticated", "no valid session", 401);
  return NextResponse.json({
    principalId: guard.principal.principalId,
    replayBinding: await sessionReplayBinding(sid),
  });
}

/**
 * The configured mode, or the operator-facing refusal.
 *
 * A misconfiguration answers `500`, deliberately: it is not the visitor's
 * request that is wrong, and answering `401` would hide a deployment fault
 * behind a login screen.
 */
function configuredMode(): { mode: AuthMode } | { failure: NextResponse } {
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
    return refuse(
      "synthetic_sign_in_disabled",
      "MYPA_AUTH_MODE is 'passkey'; the synthetic provider is not available",
      403,
    );
  }

  let synthetic;
  try {
    synthetic = resolveAdmissibleSyntheticPrincipal(body["syntheticPrincipal"]);
  } catch (error) {
    if (error instanceof PrincipalNotAdmissibleError) {
      return refuse("principal_not_admissible", error.message, 403);
    }
    throw error;
  }
  if (!synthetic) {
    return refuse("unknown_principal", "unknown synthetic principal key", 400);
  }

  try {
    validateTokenClaims({ ...synthetic.claims }, homeTenantId());
  } catch (error) {
    if (error instanceof TokenClaimsError) {
      return refuse("invalid_claims", error.message, 401);
    }
    throw error;
  }

  let issued;
  try {
    issued = await issueSyntheticSession(synthetic.key, request);
  } catch (error) {
    const failure = asAuthorityFailure(error);
    if (failure) return failure;
    throw error;
  }

  const issuedSid = parseOpaqueSessionSid(issued.issuedSid);
  if (!issuedSid) return authorityUnavailable();

  const response = NextResponse.json({ signedIn: true, upn: issued.principal.upn });
  setSessionCookie(response, issuedSid);
  await revokePriorSid(request, issuedSid);
  return response;
}

export async function DELETE(request: NextRequest) {
  const blocked = crossSite(request);
  if (blocked) return blocked;

  const sid = parseOpaqueSessionSid(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (sid) {
    try {
      await revokeSid(sid, request);
    } catch (error) {
      const failure = asAuthorityFailure(error);
      if (failure) return failure;
      throw error;
    }
  }

  const response = NextResponse.json({ signedOut: true });
  clearSessionCookie(response);
  return response;
}
