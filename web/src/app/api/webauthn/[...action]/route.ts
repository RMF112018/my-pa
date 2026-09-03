import { NextResponse, type NextRequest } from "next/server";
import { rejectCallerSuppliedPrincipal, TokenClaimsError } from "@/lib/auth/claims";
import { requirePrincipal } from "@/lib/api/guard";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import { callWebAuthnGateway } from "@/lib/auth/webauthn-server";
import {
  isOpaqueSessionSid,
  parseOpaqueSessionSid,
  SESSION_COOKIE_NAME,
  SESSION_COOKIE_OPTIONS,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth/session";
import {
  rotateSid,
  revokeSid,
  MissingSessionServiceSecretError,
  SessionServiceUnavailableError,
} from "@/lib/auth/session-service";

const PUBLIC_ACTIONS = new Set([
  "authentication/options",
  "authentication/complete",
  "recovery/consume",
]);

const SESSION_ISSUE_ACTIONS = new Set(["authentication/complete", "recovery/consume"]);

function refuse(code: string, status: number): NextResponse {
  return NextResponse.json({ error: { code } }, { status });
}

function authorityUnavailable(): NextResponse {
  return NextResponse.json({ error: { code: "authority_unavailable" } }, { status: 503 });
}

function asAuthorityFailure(error: unknown): NextResponse | null {
  if (
    error instanceof MissingSessionServiceSecretError ||
    error instanceof SessionServiceUnavailableError
  ) {
    return authorityUnavailable();
  }
  return null;
}

function browserPayload(payload: Record<string, unknown>): Record<string, unknown> {
  const { issuedSid: _stripped, ...rest } = payload;
  return rest;
}

/**
 * Set the HttpOnly session cookie to the Python-issued SID, then revoke a
 * prior cookie SID if one was presented and differs. Sign-in must not fail
 * when that revoke returns false or the service is already done with it.
 */
export async function attachIssuedSidCookie(
  response: NextResponse,
  issuedSid: string,
  request: NextRequest,
): Promise<void> {
  response.cookies.set(SESSION_COOKIE_NAME, issuedSid, {
    ...SESSION_COOKIE_OPTIONS,
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  const prior = parseOpaqueSessionSid(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!prior || prior === issuedSid) return;
  try {
    await revokeSid(prior, request);
  } catch {
    // Session fixation cleanup is best-effort after the new cookie is set.
  }
}

function jsonResponse(payload: Record<string, unknown>, status: number): NextResponse {
  return NextResponse.json(browserPayload(payload), { status });
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ action: string[] }> },
): Promise<Response> {
  const blocked = admitBrowserMutation(request);
  if (blocked) return blocked;
  const { action } = await context.params;
  const joined = action.join("/");
  let body: Record<string, unknown> = {};
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return refuse("bad_request", 400);
  }
  try {
    rejectCallerSuppliedPrincipal(body);
  } catch (error) {
    if (error instanceof TokenClaimsError) return refuse("caller_supplied_principal", 400);
    throw error;
  }
  let principal;
  if (!PUBLIC_ACTIONS.has(joined)) {
    const guard = await requirePrincipal(request);
    if (!guard.ok) return guard.response;
    principal = guard.principal;
  }
  const upstream = await callWebAuthnGateway(joined, body, request, principal);
  const text = await upstream.text();
  let payload: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = JSON.parse(text);
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      payload = parsed as Record<string, unknown>;
    }
  } catch {
    return new Response(text, {
      status: upstream.status,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  }

  if (upstream.ok && joined === "step-up/complete") {
    return finishStepUp(request, payload ?? {});
  }

  if (upstream.ok && SESSION_ISSUE_ACTIONS.has(joined)) {
    return finishIssuedSession(request, payload ?? {}, upstream.status);
  }

  if (payload) return jsonResponse(payload, upstream.status);
  return new Response(text, {
    status: upstream.status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

async function finishIssuedSession(
  request: NextRequest,
  payload: Record<string, unknown>,
  status: number,
): Promise<NextResponse> {
  const raw = payload.issuedSid;
  if (typeof raw !== "string" || !isOpaqueSessionSid(raw)) {
    if (payload.sessionCreated === true) return authorityUnavailable();
    return jsonResponse(payload, status);
  }
  const issuedSid = parseOpaqueSessionSid(raw);
  if (!issuedSid) return authorityUnavailable();
  const response = jsonResponse(payload, status);
  await attachIssuedSidCookie(response, issuedSid, request);
  return response;
}

async function finishStepUp(
  request: NextRequest,
  payload: Record<string, unknown>,
): Promise<NextResponse> {
  const currentSid = parseOpaqueSessionSid(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!currentSid) return refuse("unauthenticated", 401);
  let issuedSid: string | null;
  try {
    issuedSid = await rotateSid(currentSid, request);
  } catch (error) {
    const failure = asAuthorityFailure(error);
    if (failure) return failure;
    throw error;
  }
  if (issuedSid === null) {
    const denied = refuse("unauthenticated", 401);
    denied.cookies.set(SESSION_COOKIE_NAME, "", { ...SESSION_COOKIE_OPTIONS, maxAge: 0 });
    return denied;
  }
  const normalized = parseOpaqueSessionSid(issuedSid);
  if (!normalized) return authorityUnavailable();
  const response = jsonResponse(payload, 200);
  response.cookies.set(SESSION_COOKIE_NAME, normalized, {
    ...SESSION_COOKIE_OPTIONS,
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}
