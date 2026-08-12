/**
 * Route pre-filter — unauthenticated requests are redirected to /sign-in.
 *
 * HMAC verification and the absolute expiry check run here, because Web Crypto
 * is available in the Edge runtime. A missing, forged, or expired session cookie
 * never reaches an app page.
 *
 * **This is not the authority on whether a session is live, and it cannot be.**
 * This file runs in the **Edge** runtime, in a separate isolate from the Node
 * route handlers, so it cannot see `lib/auth/session-registry.ts` — a Node
 * module-level `Map`. It therefore cannot tell a live session from one that was
 * signed out, superseded by a later sign-in, or left idle: all three still carry
 * a valid signature and a future `exp`.
 *
 * What enforces those is `lib/auth/principal.ts`, on the Node side, and every
 * `/api/*` route handler and every server component that needs a principal goes
 * through it. So the guarantee is: middleware cheaply turns away the obviously
 * unauthenticated before they cost a render, and nothing is *served* to a
 * revoked session because the thing that serves it checks. The one visible
 * consequence is that a revoked cookie can still reach a page shell, whose own
 * principal lookup then refuses it.
 *
 * Do not add a revocation check here. Making it real would need shared state the
 * Edge runtime can reach, which is a durable store the web tier does not have at
 * this head; faking it with a second in-memory map would produce a check that
 * silently agreed with nothing.
 */
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth/session";

const PUBLIC_PATHS = new Set(["/sign-in"]);

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.has(pathname) || pathname.startsWith("/api/session")) {
    return NextResponse.next();
  }
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const principal = await verifySession(token);
  if (!principal) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json(
        { error: { code: "unauthenticated", message: "no valid session" } },
        { status: 401 },
      );
    }
    const signIn = request.nextUrl.clone();
    signIn.pathname = "/sign-in";
    signIn.search = "";
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
