/**
 * Route pre-filter — unauthenticated requests are redirected to /sign-in.
 *
 * This file runs in the **Edge** runtime. It checks only that a `mypa_session`
 * cookie is present and is 64 hex characters. It does not HMAC, does not fetch
 * Python, and does not import `session-service.ts`.
 *
 * Liveness, idle TTL, and identity are decided on the Node side by
 * `lib/auth/principal.ts` via the session-service. A 64-hex cookie can still
 * name a dead SID; the page or route that serves the request refuses it.
 */
import { NextResponse, type NextRequest } from "next/server";
import { parseOpaqueSessionSid, SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { safeReturnPath } from "@/lib/auth/return-path";

const PUBLIC_PATHS = new Set(["/sign-in"]);

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    PUBLIC_PATHS.has(pathname) ||
    pathname.startsWith("/api/session") ||
    pathname.startsWith("/api/webauthn/authentication/") ||
    pathname === "/api/webauthn/recovery/consume"
  ) {
    return NextResponse.next();
  }
  const sid = parseOpaqueSessionSid(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!sid) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json(
        { error: { code: "unauthenticated", message: "no valid session" } },
        { status: 401 },
      );
    }
    const signIn = request.nextUrl.clone();
    signIn.pathname = "/sign-in";
    signIn.search = "";
    const candidate = `${pathname}${request.nextUrl.search}`;
    const safe = safeReturnPath(candidate);
    if (safe) signIn.searchParams.set("next", safe);
    return NextResponse.redirect(signIn);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Guard everything except Next.js internals and static assets.
     */
    "/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest|sw.js|icons/|.*\\.svg$).*)",
  ],
};
