/**
 * Warm every route on both servers before the first test runs.
 *
 * **Why this is necessary, stated plainly, because it is a real limitation and
 * not a tidiness measure.** This suite runs against `next dev` — it has to, since
 * the only sign-in this build implements is refused in a production build (see
 * `playwright.config.ts`). A dev server compiles routes on demand, and that
 * compilation can reload the server's module context. The session registry is a
 * process-local, in-memory structure by design (`lib/auth/session-registry.ts`
 * says so in its own docstring: "lost on restart, which is the safe direction"),
 * so a reload in the middle of a test revokes the session that test signed in
 * with, and the test then sees the sign-in screen for no reason it can observe.
 *
 * That is a **development-mode artefact**, not a defect in the product: a
 * production server evaluates its modules once and does not recompile under
 * traffic. But it is real enough to make a browser suite flap, so the fix is to
 * do the compiling *before* any session exists — every route, on both servers,
 * fetched once here.
 *
 * Nothing is asserted and nothing is signed in. A route that 307s to `/sign-in`
 * is a perfectly good warm-up: the compile is what is wanted.
 */
import { LIVE_URL, DEAD_GATEWAY_URL } from "../playwright.config";

const ROUTES = [
  "/sign-in",
  "/today",
  "/work",
  "/intelligence",
  "/people",
  "/knowledge",
  "/knowledge?q=warm",
  "/library",
  "/library?q=warm",
  "/situations",
  "/review",
  "/system",
  "/manifest.webmanifest",
  "/sw.js",
];

async function warm(origin: string): Promise<void> {
  for (const route of ROUTES) {
    try {
      await fetch(`${origin}${route}`, { redirect: "manual" });
    } catch {
      // A warm-up is best effort. If the server is not answering at all, the
      // tests themselves will say so far more clearly than this loop could.
    }
  }
}

export default async function globalSetup(): Promise<void> {
  await Promise.all([warm(LIVE_URL), warm(DEAD_GATEWAY_URL)]);
}
