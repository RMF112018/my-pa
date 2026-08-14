/**
 * Session envelope — HMAC-SHA256 signed, HttpOnly cookie.
 *
 * Uses the Web Crypto API only, so verification works in the Edge runtime
 * (middleware) and the Node runtime (route handlers) alike. The session
 * value is `base64url(payloadJson) + "." + base64url(hmac)`. No identity
 * field is ever read from the client without the signature verifying first.
 *
 * **What this module can and cannot decide.** It proves that a cookie was minted
 * by this deployment and has not passed its absolute expiry. It cannot know
 * whether the session was *revoked*, because a signed bearer value is valid
 * until it expires and nothing in it changes when someone signs out. Revocation
 * is server-side state and lives in `session-registry.ts`, which is Node-only;
 * `principal.ts` is the resolution that consults both and is the authority every
 * route handler and server component goes through. Calling `verifySession`
 * alone is a signature-and-expiry check, and the two callers that do it —
 * `src/middleware.ts` and this module's own tests — say so where they do it.
 *
 * `sid` is what makes revocation possible at all: a random per-sign-in
 * identifier the registry can be keyed on. Without it a "revoke" could only
 * revoke a principal, so signing out of one browser would sign the person out of
 * every other one, and there would be nothing to rotate on sign-in.
 */
import type { PrincipalSession } from "@/contracts/identity";

export const SESSION_COOKIE_NAME = "mypa_session";
export const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60; // 8 hours

/**
 * Raised when no session secret is configured. Distinct from a verification
 * failure: a bad token means "this caller is not signed in", while this means
 * "this deployment cannot decide who anyone is" — and the two must not be
 * answered the same way, because the second is a misconfiguration that has to
 * reach an operator rather than a visitor.
 */
export class MissingSessionSecretError extends Error {
  constructor() {
    super(
      "MYPA_SESSION_SECRET is not set. The session cookie carries principalId and " +
        "is trusted by the middleware and every requirePrincipal route, so a signing " +
        "key must be configured explicitly. There is no default.",
    );
    this.name = "MissingSessionSecretError";
  }
}

/**
 * The HMAC key, or a refusal.
 *
 * This used to fall back to a hardcoded literal when `MYPA_SESSION_SECRET` was
 * unset, which failed **open** and silently: the session envelope carries
 * `principalId`, `src/middleware.ts` and every `requirePrincipal` route trust
 * whatever verifies against this key, and the fallback was a constant in a
 * public repository. Anyone could therefore mint a session for an arbitrary
 * principal against any deployment that had forgotten one environment
 * variable — and nothing anywhere would have said so, because a signature that
 * verifies looks exactly like a signature that should.
 *
 * A minimum length is enforced for the same reason the default is gone: a
 * one-character secret is a configured secret, and accepting it would move the
 * failure from "unset" to "set to something useless", which is harder to see.
 */
const MINIMUM_SECRET_LENGTH = 32;

function sessionSecret(): string {
  const configured = process.env.MYPA_SESSION_SECRET;
  if (!configured || configured.trim().length < MINIMUM_SECRET_LENGTH) {
    throw new MissingSessionSecretError();
  }
  return configured;
}

export interface SessionPayload {
  readonly principal: PrincipalSession;
  /**
   * The session identifier this sign-in minted. Random, unguessable, and the
   * key the server-side registry revokes by.
   */
  readonly sid: string;
  /** Unix seconds at which the session was issued. */
  readonly iat: number;
  /** Unix seconds after which the session is invalid. */
  readonly exp: number;
}

/**
 * A fresh session identifier: 128 bits from the platform CSPRNG.
 *
 * `crypto.getRandomValues` rather than anything derived from the principal, the
 * clock, or a counter — a predictable `sid` would let someone revoke or
 * impersonate a session they never held.
 */
export function newSessionId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlDecode(text: string): Uint8Array | null {
  try {
    const padded = text.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

async function hmacKey(): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(sessionSecret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

/**
 * Encode a principal into a signed session token.
 *
 * `sid` is supplied by the caller rather than minted here, because the value has
 * to be registered server-side in the same act that issues the cookie — a token
 * carrying a `sid` the registry never heard of would be a session nothing could
 * revoke.
 */
export async function encodeSession(principal: PrincipalSession, sid?: string): Promise<string> {
  const issued = Math.floor(Date.now() / 1000);
  const payload: SessionPayload = {
    principal,
    sid: sid ?? newSessionId(),
    iat: issued,
    exp: issued + SESSION_MAX_AGE_SECONDS,
  };
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload));
  const signature = await crypto.subtle.sign("HMAC", await hmacKey(), payloadBytes as BufferSource);
  return `${base64UrlEncode(payloadBytes)}.${base64UrlEncode(new Uint8Array(signature))}`;
}

/**
 * Verify a session token's signature and absolute expiry, and return the whole
 * envelope. Returns `null` on any failure — malformed token, bad signature,
 * expiry, missing fields. Fail closed.
 *
 * **This is not the authority on whether a session is live.** It cannot see a
 * revocation; see the module docstring and `principal.ts`.
 */
export async function verifySessionEnvelope(
  token: string | undefined | null,
): Promise<SessionPayload | null> {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const payloadBytes = base64UrlDecode(parts[0]);
  const signatureBytes = base64UrlDecode(parts[1]);
  if (!payloadBytes || !signatureBytes) return null;
  const valid = await crypto.subtle.verify(
    "HMAC",
    await hmacKey(),
    signatureBytes as BufferSource,
    payloadBytes as BufferSource,
  );
  if (!valid) return null;
  let payload: SessionPayload;
  try {
    payload = JSON.parse(new TextDecoder().decode(payloadBytes)) as SessionPayload;
  } catch {
    return null;
  }
  const now = Math.floor(Date.now() / 1000);
  if (typeof payload.exp !== "number" || payload.exp <= now) return null;
  if (typeof payload.iat !== "number" || payload.iat > now + 60) return null;
  if (typeof payload.sid !== "string" || payload.sid.length < 16) return null;
  const p = payload.principal;
  if (
    !p ||
    typeof p.principalId !== "string" ||
    typeof p.tid !== "string" ||
    typeof p.oid !== "string" ||
    typeof p.upn !== "string" ||
    typeof p.displayName !== "string" ||
    (p.authenticationProvider !== undefined &&
      !["synthetic", "entra", "local_operator"].includes(p.authenticationProvider))
  ) {
    return null;
  }
  return payload;
}

/**
 * The principal a token names, on signature and absolute expiry alone.
 *
 * Kept because the Edge middleware can use nothing more than this. Every Node
 * caller must use `resolveSessionPrincipal` from `principal.ts` instead, which
 * additionally refuses a revoked or idle session.
 */
export async function verifySession(
  token: string | undefined | null,
): Promise<PrincipalSession | null> {
  return (await verifySessionEnvelope(token))?.principal ?? null;
}

/**
 * Opaque binding for one exact session cookie, used to close replay check/send races.
 *
 * This is not an authentication token and never replaces cookie verification. The
 * browser receives only this one-way digest; a replay POST presents it back and
 * the BFF recomputes it from the HttpOnly cookie that authenticates that request.
 * A cookie transition between introspection and POST therefore changes the
 * binding and is refused before the Capture gateway is called.
 */
export async function sessionReplayBinding(token: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`my-pa:offline-replay:v1:${token}`) as BufferSource,
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Cookie attributes shared by set/clear paths. */
export const SESSION_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  secure: process.env.NODE_ENV === "production",
};
