/**
 * Server-only WebAuthn BFF helpers for ceremony routes.
 *
 * Attestation (`x-my-pa-webauthn-attestation`) is for WP03 ceremony calls that
 * already have a Principal. Session-service routes (resolve/touch/rotate/revoke/
 * issue-synthetic) must go through `session-service.ts` and must not send this
 * header. Cookie set and `issuedSid` stripping happen in the route handler.
 *
 * Authenticated gateway calls also copy the opaque SID from the HttpOnly cookie
 * onto `x-my-pa-auth-sid`. The browser never supplies that header.
 */

import { createHmac } from "node:crypto";
import type { PrincipalSession } from "@/contracts/identity";
import { canonicalPrincipalUuid } from "@/lib/auth/claims";
import { parseOpaqueSessionSid, SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { gatewayBaseUrl } from "@/lib/api/gateway-config";

export const WEBAUTHN_ATTESTATION_HEADER = "x-my-pa-webauthn-attestation";
export const WEBAUTHN_SID_HEADER = "x-my-pa-auth-sid";

export class MissingWebAuthnBffSecretError extends Error {
  constructor() {
    super("MYPA_WEBAUTHN_BFF_SECRET must be a 32+ character server secret.");
    this.name = "MissingWebAuthnBffSecretError";
  }
}

function bffSecret(): string {
  const configured =
    process.env.MYPA_WEBAUTHN_BFF_SECRET ?? process.env.MY_PA_WEBAUTHN_BFF_SECRET ?? "";
  if (configured.trim().length < 32) throw new MissingWebAuthnBffSecretError();
  return configured;
}

function base64Url(bytes: Buffer): string {
  return bytes.toString("base64url");
}

type CookieJar = { get(name: string): { value?: string } | undefined };

function opaqueSidFromRequest(request: Request): string | null {
  const jar = (request as Request & { cookies?: CookieJar }).cookies;
  const fromJar = parseOpaqueSessionSid(jar?.get(SESSION_COOKIE_NAME)?.value);
  if (fromJar) return fromJar;
  const header = request.headers.get("cookie");
  if (!header) return null;
  for (const part of header.split(";")) {
    const trimmed = part.trim();
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    if (trimmed.slice(0, eq) !== SESSION_COOKIE_NAME) continue;
    return parseOpaqueSessionSid(trimmed.slice(eq + 1));
  }
  return null;
}

/** Signed `{iat,pid}` with sorted JSON keys, matching Python `issue_webauthn_attestation`. */
export function issueWebAuthnAttestation(principal: PrincipalSession, now = Date.now()): string {
  const pid = canonicalPrincipalUuid(principal.principalId);
  const payload = base64Url(
    Buffer.from(JSON.stringify({ iat: Math.floor(now / 1000), pid }, ["iat", "pid"])),
  );
  const signature = createHmac("sha256", bffSecret()).update(payload).digest("hex");
  return `${payload}.${signature}`;
}

export async function callWebAuthnGateway(
  action: string,
  body: Record<string, unknown>,
  request: Request,
  principal?: PrincipalSession,
): Promise<Response> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    origin: request.headers.get("origin") ?? new URL(request.url).origin,
  };
  const fetchSite = request.headers.get("sec-fetch-site");
  if (fetchSite) headers["sec-fetch-site"] = fetchSite;
  if (principal) {
    headers[WEBAUTHN_ATTESTATION_HEADER] = issueWebAuthnAttestation(principal);
    const sid = opaqueSidFromRequest(request);
    if (sid) headers[WEBAUTHN_SID_HEADER] = sid;
  }
  const response = await fetch(`${gatewayBaseUrl()}/webauthn/v1/${action}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const text = await response.text();
  return new Response(text, {
    status: response.status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
