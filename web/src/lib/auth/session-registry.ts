/**
 * Server-side session state: which `sid`s are live, and when each was last seen.
 *
 * A signed cookie is a bearer value. It stays cryptographically valid until its
 * `exp` no matter what happens afterwards, so "sign out" cannot be implemented
 * by clearing it — the browser is not the only thing that can hold a copy, and
 * clearing a cookie is a request the holder may decline. Revocation therefore
 * has to be state the *server* keeps, and this is that state.
 *
 * **The limitation, stated plainly rather than implied away: this registry is
 * process-local and in-memory.** It is a `Map` in a Node module, so it is lost
 * on restart (every session is then revoked, which is the safe direction) and it
 * is not shared between processes (a second instance would not see the first's
 * revocations, which is not). The web tier has no durable store at this head —
 * WP-06 wires the backend — and building a persistence abstraction for one
 * `Map` before there is a second implementation is the speculative layer
 * `AGENTS.md` section 2 forbids. The swap point is the four functions below and
 * nothing else reaches into the maps, so replacing them with a table is a change
 * to this file.
 *
 * **It is Node-only, and that is a runtime fact rather than a preference.**
 * `src/middleware.ts` runs in the Edge runtime, in a separate isolate that
 * cannot see this module's memory. Middleware therefore cannot enforce
 * revocation and does not claim to; it is a cheap pre-filter, and the authority
 * is `principal.ts`, which every `/api/*` route handler and every server-side
 * principal lookup goes through.
 */

/** How long a session may sit unused before it is refused. */
export const IDLE_TIMEOUT_SECONDS = 30 * 60;

interface LiveSession {
  readonly principalId: string;
  lastSeenAt: number;
}

/** `sid` -> the live session it names. */
const live = new Map<string, LiveSession>();

/** `principalId` -> the one `sid` that principal currently holds. */
const current = new Map<string, string>();

function seconds(now: number | undefined): number {
  return now ?? Math.floor(Date.now() / 1000);
}

/**
 * Register a freshly minted `sid` for `principalId`, revoking any prior one.
 *
 * Rotating on every sign-in is what closes session fixation: a `sid` that was
 * valid before the sign-in is not valid after it, so an identifier planted or
 * observed earlier cannot be carried across the boundary.
 */
export function registerSession(principalId: string, sid: string, now?: number): void {
  const previous = current.get(principalId);
  if (previous !== undefined && previous !== sid) live.delete(previous);
  live.set(sid, { principalId, lastSeenAt: seconds(now) });
  current.set(principalId, sid);
}

/**
 * Mark `sid` as used, and report whether it is still live **for this principal**.
 *
 * `false` means revoked, never registered, idle past `IDLE_TIMEOUT_SECONDS`, or
 * registered to a different principal than the envelope claims. They are not
 * distinguished: each of them means "not signed in", and telling them apart
 * would tell a caller whether a session it does not hold exists.
 *
 * **The principal equality check is the WP-08 hardening of WP-07's NOTE 2.**
 * This registry bound a `sid` to liveness and to a principal, but only liveness
 * was ever checked, so an envelope naming principal B carrying principal A's
 * live `sid` resolved to B while touching A's session. Reaching that state
 * already required the HMAC signing secret — which permits forging any identity
 * outright — so it was outside the threat model and is still outside it. It is
 * closed anyway because it is one comparison, and because "the identity in the
 * envelope and the identity the server registered agree" is a property worth
 * having stated rather than argued.
 */
export function touchSession(sid: string, principalId: string, now?: number): boolean {
  const at = seconds(now);
  const session = live.get(sid);
  if (session === undefined) return false;
  if (session.principalId !== principalId) return false;
  if (at - session.lastSeenAt > IDLE_TIMEOUT_SECONDS) {
    revokeSession(sid);
    return false;
  }
  session.lastSeenAt = at;
  return true;
}

/** Revoke `sid`. Idempotent, and safe for a `sid` that was never registered. */
export function revokeSession(sid: string): void {
  const session = live.get(sid);
  live.delete(sid);
  if (session !== undefined && current.get(session.principalId) === sid) {
    current.delete(session.principalId);
  }
}

/** Drop every session. For tests, and for nothing else. */
export function resetSessionRegistry(): void {
  live.clear();
  current.clear();
}
