/** Complete the server-side Entra authorization-code flow and issue a session. */
import { NextRequest, NextResponse } from "next/server";

import {
  completeEntraAuthorization,
  ENTRA_FLOW_COOKIE_NAME,
} from "@/lib/auth/entra-code-flow";
import {
  SESSION_COOKIE_NAME,
  SESSION_COOKIE_OPTIONS,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth/session";

export const runtime = "nodejs";

function refused(request: NextRequest): NextResponse {
  const response = NextResponse.redirect(new URL("/sign-in?error=entra_callback", request.url));
  response.cookies.set(ENTRA_FLOW_COOKIE_NAME, "", { ...SESSION_COOKIE_OPTIONS, maxAge: 0 });
  return response;
}

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code") ?? "";
  const state = request.nextUrl.searchParams.get("state") ?? "";
  if (request.nextUrl.searchParams.has("error")) return refused(request);

  try {
    const established = await completeEntraAuthorization({
      code,
      state,
      stateCookie: request.cookies.get(ENTRA_FLOW_COOKIE_NAME)?.value,
    });
    const response = NextResponse.redirect(new URL("/today", request.url));
    response.cookies.set(SESSION_COOKIE_NAME, established.cookie, {
      ...SESSION_COOKIE_OPTIONS,
      maxAge: SESSION_MAX_AGE_SECONDS,
    });
    response.cookies.set(ENTRA_FLOW_COOKIE_NAME, "", {
      ...SESSION_COOKIE_OPTIONS,
      maxAge: 0,
    });
    return response;
  } catch {
    // Neither the authorization code nor an MSAL/token error is reflected.
    return refused(request);
  }
}
