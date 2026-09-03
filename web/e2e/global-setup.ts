/**
 * Warm every route on both servers before the first test runs.
 *
 * **Why this is necessary, stated plainly, because it is a real limitation and
 * not a tidiness measure.** This suite runs against `next dev` — it has to, since
 * the only sign-in this build implements is refused in a production build (see
 * `playwright.config.ts`). A dev server compiles routes on demand, and that
 * compilation can reload the server's module context mid-test. The compile is
 * what this loop is for: fetch every route once so the first signed-in request
 * is not also the first compile.
 *
 * Session **authority is PostgreSQL `AuthSessionStore`**, reached through the
 * Python session-service. It is not a process-local Map. A Next reload does not
 * revoke a live SID; `lib/auth/session-registry.ts` is a no-op shim. Warm-up
 * remains useful so `next-dev` is not compiling under a signed-in cookie. It is
 * **not** product proof that in-memory registry revocation is how sessions die.
 * Multi-instance / restart proof lives in
 * `tests/database/test_webauthn_auth_persistence.py`
 * (`test_session_authority_is_postgresql_not_process_local`). Playwright restart
 * of Next is not that proof.
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
