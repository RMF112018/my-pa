/**
 * The browser suite, and exactly what tiers it runs against.
 *
 * **This is a real browser.** Chromium (Chrome for Testing) is launched by
 * Playwright and drives the shipped pages; nothing here is jsdom and nothing
 * here is relabelled. What it drives is a real Next.js server, which reaches a
 * real Python gateway over a loopback socket, which reaches a real PostgreSQL —
 * the whole chain the operating brief asks for, with no stub in it. The one
 * thing the harness supplies is the database: `e2e/stack.sh` creates a
 * disposable one at head so a browser run cannot write into the configured
 * development database.
 *
 * **Why the Next tier runs in development mode, stated rather than glossed.**
 * The only sign-in this build implements is the synthetic identity provider, and
 * `lib/auth/mode.ts` refuses it outright when `NODE_ENV === "production"` — a
 * production build with a passwordless sign-in button is a defect, not a
 * configuration. `next start` sets `NODE_ENV=production`. So a browser run that
 * signs in has to be a `next dev` run, and pretending otherwise would mean
 * weakening that refusal for the convenience of a test. The production build is
 * still checked, by `npm run build`, which is a separate and honest claim.
 *
 * **Two servers, because a failure state has to come from a real failure.** The
 * gateway call happens on the server, so a browser cannot intercept it and a
 * route stub would prove nothing about the server's own error mapping. Instead a
 * second Next server is started with `MYPA_GATEWAY_URL` pointing at a port
 * nothing listens on: every page it serves reaches the genuine "the application
 * gateway did not answer" path, through the real transport, and the assertions
 * about unavailable states are made against that.
 *
 * **`localhost`, not `127.0.0.1`, and the difference is load-bearing.** The two
 * state-changing session routes refuse a request whose `Origin` does not equal
 * the request's own origin (`lib/http/origin.ts`), which is a real CSRF defence
 * and must not be relaxed for a test. Next's dev server reports its own URL as
 * `localhost`, so a browser driven at `127.0.0.1` sends `Origin:
 * http://127.0.0.1:3100` against a `request.url` of `http://localhost:3100` and
 * sign-in is correctly refused. The suite therefore drives the same name the
 * server answers to. The guard is untouched.
 *
 * **This suite is not in the unit baseline.** `vitest.config.ts` includes
 * `src/**` only, and these live in `e2e/`, so `npm test` neither collects nor
 * reports them. `npm run e2e` is the only way to run them, and it is the only
 * command that needs a database and a gateway.
 */
import { defineConfig, devices } from "@playwright/test";

/** The Next server wired to the real Python gateway. */
export const LIVE_PORT = 3100;
/** The Next server whose gateway address answers nothing. */
export const DEAD_GATEWAY_PORT = 3101;

export const LIVE_URL = `http://localhost:${LIVE_PORT}`;
export const DEAD_GATEWAY_URL = `http://localhost:${DEAD_GATEWAY_PORT}`;

/** Where the harness put the Python gateway. See `e2e/stack.sh`. */
const GATEWAY_URL = process.env.MYPA_E2E_GATEWAY_URL ?? "http://127.0.0.1:9099";

/**
 * A signing key for the browser suite's own sessions.
 *
 * Synthetic, generated for this harness, and a credential for nothing: it signs
 * cookies minted by the synthetic development provider against a disposable
 * database. It is written down here rather than left to a default because
 * `lib/auth/session.ts` has no default and must not acquire one.
 */
const SESSION_SECRET =
  process.env.MYPA_SESSION_SECRET ?? "synthetic-e2e-signing-key-000000000000000000";

const baseEnv = {
  MYPA_SESSION_SECRET: SESSION_SECRET,
  MYPA_AUTH_MODE: "synthetic",
  MYPA_GATEWAY_AUTH_MODE: "local_operator",
  // Deliberately absent: MYPA_DATA_PROVIDER. The suite runs a default build,
  // which serves the backend or states that it cannot, and never fixtures.
};

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  // Compiles every route before any session exists. See `e2e/global-setup.ts`:
  // a dev server compiling on demand can reload its module context mid-test,
  // which revokes the in-memory session the test just signed in with.
  globalSetup: "./e2e/global-setup.ts",
  // A browser run touching one shared gateway and one shared database is not
  // parallel-safe: two workers capturing at once would race the listing
  // assertions. One worker, and the suite is small enough that it costs little.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: LIVE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Service workers must be allowed to register: the PWA install criteria are
    // part of what this suite measures, so blocking them would measure nothing.
    serviceWorkers: "allow",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile",
      // A real mobile emulation profile: 390x844, touch, and a mobile UA.
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: [
    {
      command: `npx next dev --turbopack --port ${LIVE_PORT}`,
      url: `${LIVE_URL}/sign-in`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stderr: "pipe",
      env: { ...baseEnv, MYPA_GATEWAY_URL: GATEWAY_URL },
    },
    {
      command: `npx next dev --turbopack --port ${DEAD_GATEWAY_PORT}`,
      url: `${DEAD_GATEWAY_URL}/sign-in`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stderr: "pipe",
      // Port 1 on loopback. Nothing listens there, so every gateway call takes
      // the genuine connect-refused path through the real transport.
      env: { ...baseEnv, MYPA_GATEWAY_URL: "http://127.0.0.1:1" },
    },
  ],
});
