/**
 * Server-only completion seam for an upstream MSAL authorization-code flow.
 *
 * This module does not accept a browser body or decode an unsigned JWT. Its
 * input is the result returned after MSAL has validated the issuer, signature,
 * audience, nonce, expiry, and authorization-code exchange. Live client and
 * tenant configuration remain operator-gated; the local candidate owns what
 * happens after that validated result exists.
 */
import { validateTokenClaims } from "@/lib/auth/claims";
import { homeTenantId } from "@/lib/auth/mode";
import { encodeSession, newSessionId } from "@/lib/auth/session";
import { registerSession } from "@/lib/auth/session-registry";
import type { PrincipalSession } from "@/contracts/identity";

export interface ValidatedMsalResult {
  readonly validationAuthority: "msal";
  readonly accessToken: string;
  readonly claims: Readonly<Record<string, unknown>>;
}

export interface EstablishedEntraSession {
  readonly cookie: string;
  readonly principal: PrincipalSession;
}

export async function establishValidatedEntraSession(
  result: ValidatedMsalResult,
): Promise<EstablishedEntraSession> {
  if (result.validationAuthority !== "msal" || result.accessToken.trim().length < 16) {
    throw new Error("a validated MSAL access token is required");
  }
  const claims = validateTokenClaims(result.claims, homeTenantId());
  const principal: PrincipalSession = {
    principalId: `entra-${claims.oid}`,
    tid: claims.tid,
    oid: claims.oid,
    upn: claims.upn,
    displayName: claims.name,
    lifecycleState: "active",
    synthetic: false,
  };
  const sid = newSessionId();
  registerSession(principal.principalId, sid, undefined, result.accessToken);
  return { cookie: await encodeSession(principal, sid), principal };
}
