/**
 * Session envelope — HMAC-SHA256 signed, HttpOnly cookie.
 *
 * Uses the Web Crypto API only, so verification works in the Edge runtime
 * (middleware) and the Node runtime (route handlers) alike. The session
 * value is `base64url(payloadJson) + "." + base64url(hmac)`. No identity
 * field is ever read from the client without the signature verifying first.
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

interface SessionPayload {
  readonly principal: PrincipalSession;
  /** Unix seconds after which the session is invalid. */
  readonly exp: number;
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

/** Encode a principal into a signed session token. */
export async function encodeSession(principal: PrincipalSession): Promise<string> {
  const payload: SessionPayload = {
    principal,
    exp: Math.floor(Date.now() / 1000) + SESSION_MAX_AGE_SECONDS,
  };
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload));
  const signature = await crypto.subtle.sign("HMAC", await hmacKey(), payloadBytes as BufferSource);
  return `${base64UrlEncode(payloadBytes)}.${base64UrlEncode(new Uint8Array(signature))}`;
}

/**
 * Verify a session token. Returns the principal on success, `null` on any
 * failure — malformed token, bad signature, expiry, missing fields. Fail closed.
 */
export async function verifySession(token: string | undefined | null): Promise<PrincipalSession | null> {
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
  if (typeof payload.exp !== "number" || payload.exp <= Math.floor(Date.now() / 1000)) {
    return null;
  }
  const p = payload.principal;
  if (
    !p ||
    typeof p.principalId !== "string" ||
    typeof p.tid !== "string" ||
    typeof p.oid !== "string" ||
    typeof p.upn !== "string" ||
    typeof p.displayName !== "string"
  ) {
    return null;
  }
  return p;
}

/** Cookie attributes shared by set/clear paths. */
export const SESSION_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  secure: process.env.NODE_ENV === "production",
};
