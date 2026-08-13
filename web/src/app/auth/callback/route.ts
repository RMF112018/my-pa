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
import { canonicalUrl } from "@/lib/http/canonical-origin";

export const runtime = "nodejs";

function refused(): NextResponse {
  const response = NextResponse.redirect(canonicalUrl("/sign-in?error=entra_callback"));
  response.cookies.set(ENTRA_FLOW_COOKIE_NAME, "", { ...SESSION_COOKIE_OPTIONS, maxAge: 0 });
  return response;
}

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code") ?? "";
  const state = request.nextUrl.searchParams.get("state") ?? "";
  if (request.nextUrl.searchParams.has("error")) return refused();

  try {
    const established = await completeEntraAuthorization({
      code,
      state,
      stateCookie: request.cookies.get(ENTRA_FLOW_COOKIE_NAME)?.value,
    });
    const response = NextResponse.redirect(canonicalUrl("/today"));
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
    return refused();
  }
}
