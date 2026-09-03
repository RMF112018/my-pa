/**
 * Opaque session cookie — raw AuthSessionStore SID, Edge-safe.
 *
 * The cookie value is 64 hex characters. This module does not HMAC, does not
 * carry a Principal, and does not talk to Python. Edge middleware uses
 * `parseOpaqueSessionSid` as a charset/length pre-filter only. Node authority
 * is `resolveSessionPrincipal` in `principal.ts`, which POSTs the SID to the
 * session-service.
 *
 * Do not import `session-service.ts` from this file: middleware runs on Edge.
 */
export const SESSION_COOKIE_NAME = "mypa_session";
export const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60; // 8 hours

const OPAQUE_SID = /^[0-9a-fA-F]{64}$/;
const REPLAY_BINDING_PREFIX = "my-pa:offline-replay:v1:";

/** Cookie attributes shared by set/clear paths. `maxAge` applies on set. */
export const SESSION_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  secure: process.env.NODE_ENV === "production",
  maxAge: SESSION_MAX_AGE_SECONDS,
};

/** True when `value` is exactly 64 hex characters (any case). */
export function isOpaqueSessionSid(value: string | undefined | null): value is string {
  return typeof value === "string" && OPAQUE_SID.test(value);
}

/**
 * Charset and length only. No HMAC. Returns lowercase hex, or `null`.
 *
 * A missing, short, or non-hex cookie is unauthenticated at the Edge pre-filter.
 * Liveness, idle TTL, and identity are decided by Python, not here.
 */
export function parseOpaqueSessionSid(value: string | undefined | null): string | null {
  if (!isOpaqueSessionSid(value)) return null;
  return value.toLowerCase();
}

/**
 * Opaque binding for one exact session cookie, used to close replay check/send races.
 *
 * This is not an authentication token and never replaces SID verification. The
 * browser receives only this one-way digest; a replay POST presents it back and
 * the BFF recomputes it from the HttpOnly cookie that authenticates that request.
 * The digest is SHA-256 of `my-pa:offline-replay:v1:` plus the opaque SID.
 */
export async function sessionReplayBinding(sid: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${REPLAY_BINDING_PREFIX}${sid}`) as BufferSource,
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
