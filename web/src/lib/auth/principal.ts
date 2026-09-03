/**
 * The authoritative answer to "who is calling?" on the Node side.
 *
 * Edge middleware only checks that a `mypa_session` cookie is 64 hex characters.
 * Python `AuthSessionStore` is the authority: this module POSTs the opaque SID
 * to `sessions/touch` so idle TTL advances, and maps the returned Principal.
 *
 * A missing or dead SID is `null` (unauthenticated). A missing service secret,
 * gateway outage, or 503 is `AuthorityUnavailableError` — never `null`, so a
 * deployment defect is not answered as "please sign in".
 */
import { parseOpaqueSessionSid } from "@/lib/auth/session";
import {
  callSessionService,
  principalFromSessionServiceResponse,
} from "@/lib/auth/session-service";
import type { PrincipalSession } from "@/contracts/identity";

/** The session-service cannot decide who this caller is. Distinct from 401. */
export class AuthorityUnavailableError extends Error {
  constructor() {
    super("session authority unavailable");
    this.name = "AuthorityUnavailableError";
  }
}

/** The signed-in principal, or `null` — SID shape, then Python liveness. */
export async function resolveSessionPrincipal(
  token: string | undefined | null,
  request?: Request,
): Promise<PrincipalSession | null> {
  const sid = parseOpaqueSessionSid(token);
  if (!sid) return null;
  try {
    const response = await callSessionService("sessions/touch", { sid }, request);
    return await principalFromSessionServiceResponse(response);
  } catch (error) {
    if (error instanceof AuthorityUnavailableError) throw error;
    throw new AuthorityUnavailableError();
  }
}
