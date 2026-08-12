/**
 * Route guard — unauthenticated requests are redirected to /sign-in.
 *
 * Full HMAC verification runs here (Web Crypto is available in the Edge
 * runtime). A missing or invalid session cookie never reaches an app page.
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
