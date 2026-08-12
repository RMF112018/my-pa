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
 *
 * **The two maps live on `globalThis`, and that is not a style choice — it is
 * the fix for a defect that made this application unusable in a browser.**
 *
 * Next compiles route handlers and server components into *separate module
 * graphs*. A module-level `const live = new Map()` is therefore instantiated
 * **once per graph**: `POST /api/session` registered a `sid` in the route
 * handler's copy, and the server component rendering `/today` then asked the
 * RSC copy — which had never seen it — and was told the session was not live.
 * Every signed-in page redirected straight back to `/sign-in`. Sign in, land on
 * the sign-in screen, forever.
 *
 * Nothing in the repository could see it. Every web test invokes route handlers
 * in one process where the module is imported once, so the two copies are one
 * copy and the bug is invisible; and until WP-13 no test had ever driven a real
 * browser against a real Next server, which is the only place the two graphs
 * exist at the same time. It was found by the first browser run — `POST
 * /api/session` answering `200` and setting a cookie that `GET /api/system`
 * accepted and `GET /today` refused, in the same second, with the same cookie.
 *
 * Keying the state on a process-global symbol makes the two graphs share one
 * registry, which is what "process-local" was always supposed to mean. It
 * weakens nothing: rotation, revocation, the principal-equality check and the
 * idle window are unchanged, and a restart still drops every session, which is
 * still the safe direction. The swap point for a durable store is still the four
 * functions below.
 */

/** How long a session may sit unused before it is refused. */
export const IDLE_TIMEOUT_SECONDS = 30 * 60;

interface LiveSession {
  readonly principalId: string;
  lastSeenAt: number;
}

interface Registry {
  /** `sid` -> the live session it names. */
  readonly live: Map<string, LiveSession>;
  /** `principalId` -> the one `sid` that principal currently holds. */
  readonly current: Map<string, string>;
}

/**
 * The process-global slot the two maps live in.
 *
 * `Symbol.for` rather than a string key so nothing can collide with it by
 * accident, and so the same symbol resolves from every module graph in the
 * process — which is the entire point.
 */
const REGISTRY_KEY = Symbol.for("my-pa.web.auth.session-registry.v1");

type RegistryHolder = typeof globalThis & { [REGISTRY_KEY]?: Registry };

/** The one registry this process has, created on first use. */
function registry(): Registry {
  const holder = globalThis as RegistryHolder;
  const existing = holder[REGISTRY_KEY];
  if (existing !== undefined) return existing;
  const created: Registry = { live: new Map(), current: new Map() };
  holder[REGISTRY_KEY] = created;
  return created;
}

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
  const { live, current } = registry();
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
  const session = registry().live.get(sid);
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
  const { live, current } = registry();
  const session = live.get(sid);
  live.delete(sid);
  if (session !== undefined && current.get(session.principalId) === sid) {
    current.delete(session.principalId);
  }
}

/** Drop every session. For tests, and for nothing else. */
export function resetSessionRegistry(): void {
  const { live, current } = registry();
  live.clear();
  current.clear();
}
