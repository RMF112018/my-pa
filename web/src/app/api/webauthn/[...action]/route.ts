import { NextResponse, type NextRequest } from "next/server";
import { rejectCallerSuppliedPrincipal, TokenClaimsError } from "@/lib/auth/claims";
import { requirePrincipal } from "@/lib/api/guard";
import { isSameOrigin } from "@/lib/http/origin";
import { callWebAuthnGateway } from "@/lib/auth/webauthn-server";
import {
  encodeSession,
  newSessionId,
  SESSION_COOKIE_NAME,
  SESSION_COOKIE_OPTIONS,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth/session";
import { registerSession } from "@/lib/auth/session-registry";
import { localOperatorPrincipal } from "@/lib/auth/local-operator";
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";
import type { PrincipalSession } from "@/contracts/identity";

const PUBLIC_ACTIONS = new Set([
  "authentication/options",
  "authentication/complete",
  "recovery/consume",
]);

function refuse(code: string, status: number): NextResponse {
  return NextResponse.json({ error: { code } }, { status });
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ action: string[] }> },
): Promise<Response> {
  const blocked = isSameOrigin(request)
    ? null
    : refuse("cross_site_request", 403);
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
  if (
    upstream.ok &&
    (joined === "authentication/complete" || joined === "recovery/consume")
  ) {
    const payload = JSON.parse(await upstream.clone().text()) as {
      tid?: string;
      oid?: string;
      sessionCreated?: boolean;
    };
    if (payload.sessionCreated && payload.tid && payload.oid) {
      const sessionPrincipal = principalFromClaims(payload.tid, payload.oid);
      const sid = newSessionId();
      const token = await encodeSession(sessionPrincipal, sid);
      registerSession(sessionPrincipal.principalId, sid);
      const response = NextResponse.json(await upstream.json());
      response.cookies.set(SESSION_COOKIE_NAME, token, {
        ...SESSION_COOKIE_OPTIONS,
        maxAge: SESSION_MAX_AGE_SECONDS,
      });
      return response;
    }
  }
  return upstream;
}

function principalFromClaims(tid: string, oid: string): PrincipalSession {
  if (tid === "local_operator") return localOperatorPrincipal();
  if (tid === SYNTHETIC_MOSS_TENANT_ID) {
    return {
      principalId: `syn-${oid.slice(0, 8)}`,
      tid,
      oid,
      upn: `${oid}@moss.example`,
      displayName: "Passkey",
      lifecycleState: "active",
      synthetic: true,
      authenticationProvider: "synthetic",
    };
  }
  return {
    principalId: `entra-${oid}`,
    tid,
    oid,
    upn: "",
    displayName: "Passkey",
    lifecycleState: "active",
    synthetic: false,
    authenticationProvider: "entra",
  };
}
