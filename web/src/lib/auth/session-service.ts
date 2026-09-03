/**
 * Node-only HTTP client for Python AuthSessionStore session-service routes.
 *
 * Do not import this file from Edge middleware or client components. The HMAC
 * here authenticates the BFF to the gateway; it is not the browser cookie.
 */

import { createHmac } from "node:crypto";
import type { PrincipalSession, UserLifecycleState } from "@/contracts/identity";
import { gatewayBaseUrl } from "@/lib/api/gateway-config";

export const SESSION_SERVICE_HEADER = "x-my-pa-session-service";
const MINIMUM_SECRET_LENGTH = 32;

const LIFECYCLE_STATES: ReadonlySet<UserLifecycleState> = new Set([
  "invited",
  "active",
  "consent_required",
  "scope_insufficient",
  "suspended",
  "deprovisioned",
]);

export type SessionServiceAction =
  | "sessions/resolve"
  | "sessions/touch"
  | "sessions/rotate"
  | "sessions/revoke"
  | "sessions/issue-synthetic";

export type SyntheticSessionKey = "synthetic-a" | "synthetic-b";

export class MissingSessionServiceSecretError extends Error {
  constructor() {
    super(
      "MYPA_SESSION_SERVICE_SECRET is not set. The BFF cannot authenticate to the " +
        "session-service; this is a deployment defect, not an unauthenticated visitor.",
    );
    this.name = "MissingSessionServiceSecretError";
  }
}

export class SessionServiceUnavailableError extends Error {
  constructor() {
    super("session authority unavailable");
    this.name = "SessionServiceUnavailableError";
  }
}

function sessionServiceSecret(): string {
  const configured =
    process.env.MYPA_SESSION_SERVICE_SECRET ?? process.env.MY_PA_SESSION_SERVICE_SECRET ?? "";
  if (configured.trim().length < MINIMUM_SECRET_LENGTH) {
    throw new MissingSessionServiceSecretError();
  }
  return configured;
}

function sessionCallOrigin(request?: Request): string {
  if (request) {
    const header = request.headers.get("origin");
    if (header) return header;
    try {
      return new URL(request.url).origin;
    } catch {
      throw new SessionServiceUnavailableError();
    }
  }
  const configured = process.env.MYPA_CANONICAL_ORIGIN?.trim();
  if (!configured) throw new SessionServiceUnavailableError();
  try {
    return new URL(configured).origin;
  } catch {
    throw new SessionServiceUnavailableError();
  }
}

/** `base64url({iat}).hexsig` — payload is `{iat}` only, sorted JSON. */
export function issueSessionServiceToken(now = Date.now()): string {
  const secret = sessionServiceSecret();
  const issuedAt = Math.floor(now / 1000);
  const payload = Buffer.from(
    JSON.stringify({ iat: issuedAt }, ["iat"]),
  ).toString("base64url");
  const signature = createHmac("sha256", secret).update(payload).digest("hex");
  return `${payload}.${signature}`;
}

export async function callSessionService(
  action: SessionServiceAction,
  body: Record<string, unknown>,
  request?: Request,
): Promise<Response> {
  const token = issueSessionServiceToken();
  let base: string;
  try {
    base = gatewayBaseUrl();
  } catch {
    throw new SessionServiceUnavailableError();
  }
  const origin = sessionCallOrigin(request);
  let response: Response;
  try {
    response = await fetch(`${base}/webauthn/v1/${action}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin,
        [SESSION_SERVICE_HEADER]: token,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new SessionServiceUnavailableError();
  }
  const text = await response.text();
  return new Response(text, {
    status: response.status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export function mapSessionPrincipal(payload: unknown): PrincipalSession | null {
  if (payload === null || typeof payload !== "object") return null;
  const raw = payload as Record<string, unknown>;
  if (
    typeof raw.principalId !== "string" ||
    typeof raw.tid !== "string" ||
    typeof raw.oid !== "string" ||
    typeof raw.upn !== "string" ||
    typeof raw.displayName !== "string" ||
    typeof raw.lifecycleState !== "string" ||
    typeof raw.synthetic !== "boolean"
  ) {
    return null;
  }
  if (!LIFECYCLE_STATES.has(raw.lifecycleState as UserLifecycleState)) return null;
  return {
    principalId: raw.principalId,
    tid: raw.tid,
    oid: raw.oid,
    upn: raw.upn,
    displayName: raw.displayName,
    lifecycleState: raw.lifecycleState as UserLifecycleState,
    synthetic: raw.synthetic,
    ...(raw.synthetic ? { authenticationProvider: "synthetic" as const } : {}),
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return JSON.parse(await response.text()) as unknown;
  } catch {
    throw new SessionServiceUnavailableError();
  }
}

function errorCode(body: unknown): string | undefined {
  if (body === null || typeof body !== "object") return undefined;
  const error = (body as { error?: { code?: unknown } }).error;
  if (error === null || typeof error !== "object") return undefined;
  return typeof error.code === "string" ? error.code : undefined;
}

function throwIfUnavailable(response: Response, body: unknown): void {
  const code = errorCode(body);
  if (
    response.status === 503 ||
    code === "authority_unavailable" ||
    code === "backend_unavailable"
  ) {
    throw new SessionServiceUnavailableError();
  }
  if (!response.ok && response.status !== 401) {
    throw new SessionServiceUnavailableError();
  }
}

export async function principalFromSessionServiceResponse(
  response: Response,
): Promise<PrincipalSession | null> {
  const body = await readJson(response);
  throwIfUnavailable(response, body);
  if (response.status === 401) return null;
  const principal = mapSessionPrincipal(
    body && typeof body === "object" ? (body as { principal?: unknown }).principal : undefined,
  );
  if (!principal) throw new SessionServiceUnavailableError();
  return principal;
}

export async function resolveSid(
  sid: string,
  request?: Request,
): Promise<PrincipalSession | null> {
  const response = await callSessionService("sessions/resolve", { sid }, request);
  return principalFromSessionServiceResponse(response);
}

export async function touchSid(
  sid: string,
  request?: Request,
): Promise<PrincipalSession | null> {
  const response = await callSessionService("sessions/touch", { sid }, request);
  return principalFromSessionServiceResponse(response);
}

export async function rotateSid(sid: string, request?: Request): Promise<string | null> {
  const response = await callSessionService("sessions/rotate", { sid }, request);
  const body = await readJson(response);
  throwIfUnavailable(response, body);
  if (response.status === 401) return null;
  const issued =
    body && typeof body === "object" ? (body as { issuedSid?: unknown }).issuedSid : undefined;
  if (typeof issued !== "string") throw new SessionServiceUnavailableError();
  return issued;
}

export async function revokeSid(sid: string, request?: Request): Promise<boolean> {
  const response = await callSessionService("sessions/revoke", { sid }, request);
  const body = await readJson(response);
  throwIfUnavailable(response, body);
  if (response.status === 401) return false;
  const revoked =
    body && typeof body === "object" ? (body as { revoked?: unknown }).revoked : undefined;
  return revoked === true;
}

export async function issueSyntheticSession(
  key: SyntheticSessionKey,
  request?: Request,
): Promise<{ issuedSid: string; principal: PrincipalSession }> {
  const response = await callSessionService("sessions/issue-synthetic", { key }, request);
  const body = await readJson(response);
  throwIfUnavailable(response, body);
  if (response.status === 401) throw new SessionServiceUnavailableError();
  if (body === null || typeof body !== "object") throw new SessionServiceUnavailableError();
  const issuedSid = (body as { issuedSid?: unknown }).issuedSid;
  const principal = mapSessionPrincipal((body as { principal?: unknown }).principal);
  if (typeof issuedSid !== "string" || !principal) throw new SessionServiceUnavailableError();
  return { issuedSid, principal };
}
