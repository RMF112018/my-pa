/** Server-only WebAuthn BFF helpers. Do not import from client components. */

import { createHmac } from "node:crypto";
import type { PrincipalSession } from "@/contracts/identity";
import { gatewayBaseUrl } from "@/lib/api/gateway-config";

const ATTESTATION_HEADER = "x-my-pa-webauthn-attestation";

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

export function issueWebAuthnAttestation(principal: PrincipalSession, now = Date.now()): string {
  const payload = base64Url(
    Buffer.from(JSON.stringify({ iat: Math.floor(now / 1000), oid: principal.oid, tid: principal.tid })),
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
  if (principal) headers[ATTESTATION_HEADER] = issueWebAuthnAttestation(principal);
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
