/**
 * The authoritative answer to "who is calling?" on the Node side.
 *
 * Three things have to hold before a request has a principal, and only this
 * function checks all three:
 *
 * 1. the cookie verifies against the session secret and is inside its absolute
 *    expiry (`verifySessionEnvelope`);
 * 2. its `sid` is still registered **to the principal the envelope names** — it
 *    has not been signed out, superseded by a later sign-in, lost to a restart,
 *    or paired with a different identity than the one the server registered;
 * 3. it has been used inside the idle window.
 *
 * `src/middleware.ts` checks only the first, because the Edge runtime cannot
 * reach the registry. So middleware is a pre-filter and this is the authority:
 * every `/api/*` route handler and every server component that needs a principal
 * calls this, and a route that called `verifySession` directly would accept a
 * revoked session. Nothing else in the tree should call `verifySession`.
 */
import { verifySessionEnvelope } from "@/lib/auth/session";
import { touchSession } from "@/lib/auth/session-registry";
import type { PrincipalSession } from "@/contracts/identity";

/** The signed-in principal, or `null` — signature, expiry, revocation, idle. */
export async function resolveSessionPrincipal(
  token: string | undefined | null,
): Promise<PrincipalSession | null> {
  const envelope = await verifySessionEnvelope(token);
  if (!envelope) return null;
  if (!touchSession(envelope.sid, envelope.principal.principalId)) return null;
  return envelope.principal;
}
