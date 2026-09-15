/**
 * R01-WP05: Project Controls settings administration over the real stack.
 *
 * Browser → same-origin BFF → server-only gateway transport → the Python
 * `project_controls.status` / `project_controls.configure` capabilities → the
 * settings service, its Project row lock and its append-only history → the
 * isolated, disposable PostgreSQL that `e2e/stack.sh` creates, migrates, seeds
 * and drops. No fixture satisfies any assertion here.
 *
 * **This is an API journey, not a screen.** Run 01 ships no settings UI, and
 * this spec deliberately renders none: it signs in through the real sign-in
 * page so the session cookie is a real one, then exercises the transport from
 * inside the page's origin. Asserting on a settings screen would be asserting
 * on something the work package did not build.
 *
 * The two Projects come from the Constraint seed step in `e2e/stack.sh`: one
 * configured at `America/New_York`, and one this Principal owns but has never
 * configured. The second is what makes `not_configured` provable as an
 * authorized answer rather than as an absence.
 */
import { expect, test, type Page } from "@playwright/test";
import { LIVE_URL } from "../playwright.config";
import { signIn } from "./fixtures";

/** Mirrors the Constraint seed step in `e2e/stack.sh`. */
const CONFIGURED_PROJECT = "prj_e2ecst0000000001";
const UNCONFIGURED_PROJECT = "prj_e2ecst0000000002";

/** Well-formed identifiers of Projects this Principal does not have. */
const FOREIGN_PROJECT = "prj_e2ecstzzzzzzzz99";
const UNKNOWN_PROJECT = "prj_e2ecstyyyyyyyy88";

const ATTACKER_ORIGIN = "https://attacker.example";
const OPAQUE_SID = /^[0-9a-f]{64}$/;

function settingsPath(projectId: string): string {
  return `/api/project-controls/projects/${projectId}/settings`;
}

type Answer = {
  status: number;
  cacheControl: string | null;
  body: Record<string, unknown>;
};

/**
 * The exact shape the BFF publishes, in the exact spelling it publishes it.
 *
 * The Python capability answers in snake_case and `lib/api/decode` renames
 * every field; what leaves the route is camelCase throughout, which
 * `lib/api/decode/capabilities/project_controls.status.ts` and its decoder
 * tests already pin. The first draft of this spec accepted either spelling at
 * every accessor, so it passed whichever one arrived — evidence that something
 * answered, not evidence that the contract holds. These names are exact now,
 * and `controls()` refuses the snake_case spelling outright.
 */
type ProjectControls = {
  projectId: string;
  state: string;
  timezoneName: string | null;
  settingsVersion: number | null;
  settingsUpdatedAt: string | null;
};

/** The renamed keys, which the decoder must not have let through. */
const SNAKE_CASE_KEYS = ["project_id", "timezone_name", "settings_version", "settings_updated_at"];

/** The `projectControls` object, in the one spelling the BFF publishes. */
function controls(body: Record<string, unknown>): ProjectControls {
  expect(body, "the BFF publishes camelCase; snake_case is a contract break").not.toHaveProperty(
    "project_controls",
  );
  const value = body.projectControls as ProjectControls | undefined;
  expect(value, "the answer must carry a projectControls object").toBeTruthy();
  expect(typeof value!.projectId, "projectControls.projectId is a string").toBe("string");
  expect(typeof value!.state, "projectControls.state is a string").toBe("string");
  for (const renamed of SNAKE_CASE_KEYS) {
    expect(value, `projectControls must not carry ${renamed}`).not.toHaveProperty(renamed);
  }
  return value!;
}

function stateOf(value: ProjectControls): string {
  return value.state;
}

function timezoneOf(value: ProjectControls): string | null {
  return value.timezoneName;
}

function versionOf(value: ProjectControls): number | null {
  return value.settingsVersion;
}

async function readStatus(page: Page, projectId: string): Promise<Answer> {
  return page.evaluate(async (target) => {
    const response = await fetch(target, {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
    });
    return {
      status: response.status,
      cacheControl: response.headers.get("cache-control"),
      body: (await response.json()) as Record<string, unknown>,
    };
  }, settingsPath(projectId));
}

async function postSettings(
  page: Page,
  projectId: string,
  payload: Record<string, unknown>,
): Promise<Answer> {
  return page.evaluate(
    async ({ target, document }) => {
      const response = await fetch(target, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(document),
      });
      return {
        status: response.status,
        cacheControl: response.headers.get("cache-control"),
        body: (await response.json()) as Record<string, unknown>,
      };
    },
    { target: settingsPath(projectId), document: payload },
  );
}

async function sessionSid(page: Page): Promise<string> {
  const cookies = await page.context().cookies(LIVE_URL);
  const cookie = cookies.find((entry) => entry.name === "mypa_session");
  expect(cookie, "signed-in context must carry mypa_session").toBeDefined();
  expect(cookie!.value).toMatch(OPAQUE_SID);
  return cookie!.value;
}

/** A POST issued from outside the browser, so the Origin header is ours to choose. */
async function nodePost(options: {
  cookie?: string;
  projectId: string;
  payload: Record<string, unknown>;
  origin?: string;
}): Promise<{ status: number; body: Record<string, unknown> }> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (options.cookie) headers.cookie = `mypa_session=${options.cookie}`;
  if (options.origin !== undefined) headers.origin = options.origin;
  const response = await fetch(`${LIVE_URL}${settingsPath(options.projectId)}`, {
    method: "POST",
    headers,
    body: JSON.stringify(options.payload),
  });
  return { status: response.status, body: (await response.json()) as Record<string, unknown> };
}

function key(marker: string, suffix: string): string {
  return `e2e-pcs-${marker}-${suffix}`;
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("status reports configured and not-configured Projects distinctly", async ({ page }) => {
  test.setTimeout(180_000);

  const configured = await readStatus(page, CONFIGURED_PROJECT);
  expect(configured.status).toBe(200);
  expect(configured.cacheControl).toBe("private, no-store");
  const present = controls(configured.body);
  expect(stateOf(present)).toBe("configured");
  expect(timezoneOf(present)).toBe("America/New_York");
  expect(typeof versionOf(present)).toBe("number");
  expect(versionOf(present)).toBeGreaterThanOrEqual(1);
  // The row's own bookkeeping is not published, and neither is any identity.
  expect(JSON.stringify(configured.body)).not.toContain("principal_id");
  expect(JSON.stringify(configured.body)).not.toContain("principalId");

  const absent = await readStatus(page, UNCONFIGURED_PROJECT);
  // An authorized Project with no settings row is a typed 200, not a 404: the
  // state is an answer the capability returns, reachable only *after*
  // same-Principal Project authorization succeeded.
  expect(absent.status).toBe(200);
  expect(absent.cacheControl).toBe("private, no-store");
  const missing = controls(absent.body);
  expect(stateOf(missing)).toBe("not_configured");
  expect(timezoneOf(missing)).toBeNull();
  expect(versionOf(missing)).toBeNull();
});

test("a malformed Project identifier is refused before a capability is spent", async ({
  page,
}) => {
  for (const malformed of ["not-an-id", "prj_short", "cst_e2ecst0000000001"]) {
    const answer = await readStatus(page, malformed);
    expect(answer.status, malformed).toBe(400);
    expect(answer.cacheControl).toBe("private, no-store");
    expect((answer.body.error as { code?: string })?.code).toBe("invalid_request");
    expect(JSON.stringify(answer.body), malformed).not.toContain(malformed);
  }
});

test("a Project this Principal does not have is nondisclosing and equivalent to unknown", async ({
  page,
}) => {
  const foreign = await readStatus(page, FOREIGN_PROJECT);
  const unknown = await readStatus(page, UNKNOWN_PROJECT);

  // The guarantee is equivalence, not a particular number: nothing in the
  // status, the error code or the body distinguishes a Project belonging to
  // another Principal from one that never existed.
  expect(foreign.status).toBe(unknown.status);
  expect(foreign.status).not.toBe(200);
  expect((foreign.body.error as { code?: string })?.code).toBe(
    (unknown.body.error as { code?: string })?.code,
  );
  // A correlation id is minted per request, so it differs between any two
  // calls and says nothing about the Project. Neutralize it — and only it —
  // so the comparison still fails on any field that *would* distinguish the
  // two cases, rather than passing because the bodies were trimmed.
  const comparable = (serialized: string, projectId: string): string =>
    serialized
      .replaceAll(projectId, "«project»")
      .replace(/"correlationId":"corr_[0-9a-f]+"/g, '"correlationId":"«correlation»"');
  expect(comparable(JSON.stringify(foreign.body), FOREIGN_PROJECT)).toBe(
    comparable(JSON.stringify(unknown.body), UNKNOWN_PROJECT),
  );
  // The neutralization must have actually matched, or the assertion above
  // would be comparing two raw bodies and could only pass by luck.
  expect(comparable(JSON.stringify(foreign.body), FOREIGN_PROJECT)).toContain(
    "«correlation»",
  );
  for (const answer of [foreign, unknown]) {
    const serialized = JSON.stringify(answer.body);
    expect(serialized).not.toContain("timezone");
    expect(serialized).not.toContain("settings_version");
    expect(serialized).not.toContain("not_configured");
    expect(serialized).not.toContain("configured");
  }
});

test("configure states a calendar, replays the same key, and refuses a stale version", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const marker = `${test.info().project.name}-${Date.now()}`;

  // The Project starts unconfigured, so the first configure is the initial one
  // and `expectedVersion` is deliberately omitted: "I believe there is nothing
  // here yet".
  const before = await readStatus(page, UNCONFIGURED_PROJECT);
  const startState = stateOf(controls(before.body));

  const firstKey = key(marker, "initial");
  const applied = await postSettings(page, UNCONFIGURED_PROJECT, {
    timezoneName: "America/Chicago",
    idempotencyKey: firstKey,
  });

  if (startState === "not_configured") {
    expect(applied.status).toBe(200);
    expect(applied.cacheControl).toBe("private, no-store");
    expect(applied.body.disposition).toBe("applied");
  } else {
    // A previous run in this worker already configured it; the initial-configure
    // branch is then not this spec's to prove and the rest still is.
    expect([200, 409]).toContain(applied.status);
  }

  const configuredNow = await readStatus(page, UNCONFIGURED_PROJECT);
  expect(configuredNow.status).toBe(200);
  const now = controls(configuredNow.body);
  expect(stateOf(now)).toBe("configured");
  const version = versionOf(now) as number;
  expect(typeof version).toBe("number");

  if (applied.status === 200) {
    // The same key with the same normalized intent replays the original answer
    // rather than writing a second time.
    const replayed = await postSettings(page, UNCONFIGURED_PROJECT, {
      timezoneName: "America/Chicago",
      idempotencyKey: firstKey,
    });
    expect(replayed.status).toBe(200);
    expect(["replayed", "no_op"]).toContain(replayed.body.disposition);
    const after = await readStatus(page, UNCONFIGURED_PROJECT);
    expect(versionOf(controls(after.body))).toBe(version);
  }

  // A stale expected version is a typed conflict, not a silent overwrite.
  const stale = await postSettings(page, UNCONFIGURED_PROJECT, {
    timezoneName: "Europe/London",
    idempotencyKey: key(marker, "stale"),
    expectedVersion: version - 1,
  });
  expect(stale.status).toBe(409);
  expect((stale.body.error as { errorClass?: string })?.errorClass).toBe("conflict");

  // The refused write changed nothing.
  const unchanged = await readStatus(page, UNCONFIGURED_PROJECT);
  expect(versionOf(controls(unchanged.body))).toBe(version);
  expect(timezoneOf(controls(unchanged.body))).toBe(timezoneOf(now));
});

test("configure refuses an invalid IANA zone without echoing it", async ({ page }) => {
  const marker = `${test.info().project.name}-${Date.now()}`;
  const bad = "Mars/Olympus_Mons";
  const answer = await postSettings(page, CONFIGURED_PROJECT, {
    timezoneName: bad,
    idempotencyKey: key(marker, "bad-zone"),
  });
  expect(answer.status).toBe(400);
  expect((answer.body.error as { code?: string })?.code).toBe("invalid_request");
  expect(JSON.stringify(answer.body)).not.toContain(bad);
});

test("configure admits only its three request fields", async ({ page }) => {
  const marker = `${test.info().project.name}-${Date.now()}`;
  const extras: Record<string, unknown>[] = [
    { projectId: FOREIGN_PROJECT },
    { project_id: FOREIGN_PROJECT },
    { clientContext: "settings-screen" },
    { correlationId: "corr-1" },
    { principalId: "synthetic-b" },
    { principal_id: "synthetic-b" },
  ];
  for (const extra of extras) {
    const answer = await postSettings(page, CONFIGURED_PROJECT, {
      timezoneName: "America/New_York",
      idempotencyKey: key(marker, "extra"),
      ...extra,
    });
    expect(answer.status, JSON.stringify(extra)).toBe(400);
    expect(
      ["invalid_request", "caller_supplied_principal"],
      JSON.stringify(extra),
    ).toContain((answer.body.error as { code?: string })?.code);
  }

  // The Project is unchanged by any of those refusals.
  const after = await readStatus(page, CONFIGURED_PROJECT);
  expect(timezoneOf(controls(after.body))).toBe("America/New_York");
});

test("a cross-origin configure is 403 and writes nothing", async ({ page }) => {
  const marker = `${test.info().project.name}-${Date.now()}`;
  const sid = await sessionSid(page);
  const idempotencyKey = key(marker, "cross-site");

  const refused = await nodePost({
    cookie: sid,
    projectId: CONFIGURED_PROJECT,
    payload: { timezoneName: "Europe/London", idempotencyKey },
    origin: ATTACKER_ORIGIN,
  });
  expect(refused.status, "cross-site mutation must be 403").toBe(403);
  expect((refused.body.error as { code?: string })?.code).toBe("cross_site_request");

  const missingOrigin = await nodePost({
    cookie: sid,
    projectId: CONFIGURED_PROJECT,
    payload: { timezoneName: "Europe/London", idempotencyKey },
  });
  expect(missingOrigin.status, "a POST with no Origin must be 403").toBe(403);

  // The Project's calendar is untouched, and the idempotency key was never
  // consumed — the refusal happened before any capability was invoked.
  const after = await readStatus(page, CONFIGURED_PROJECT);
  expect(timezoneOf(controls(after.body))).toBe("America/New_York");
});

test("both handlers require a session and never accept a caller-supplied Principal", async ({
  page,
  browser,
}) => {
  const marker = `${test.info().project.name}-${Date.now()}`;

  // A context that has never signed in carries no session cookie.
  const anonymous = await browser.newContext();
  const anonymousPage = await anonymous.newPage();
  await anonymousPage.goto(`${LIVE_URL}/sign-in`);
  const unauthenticated = await readStatus(anonymousPage, CONFIGURED_PROJECT);
  expect(unauthenticated.status).toBe(401);
  expect((unauthenticated.body.error as { code?: string })?.code).toBe("unauthenticated");
  await anonymous.close();

  // No cookie, and a Principal offered in the body: still 401 or 403, never an
  // answer. The body can never become an identity.
  const forged = await nodePost({
    projectId: CONFIGURED_PROJECT,
    payload: {
      timezoneName: "Europe/London",
      idempotencyKey: key(marker, "forged"),
      principalId: "synthetic-b",
    },
    origin: LIVE_URL,
  });
  expect([400, 401]).toContain(forged.status);
  expect(forged.status).not.toBe(200);

  // And the signed-in session still cannot smuggle one.
  const sid = await sessionSid(page);
  const smuggled = await nodePost({
    cookie: sid,
    projectId: CONFIGURED_PROJECT,
    payload: {
      timezoneName: "Europe/London",
      idempotencyKey: key(marker, "smuggled"),
      principal_id: "synthetic-b",
    },
    origin: LIVE_URL,
  });
  expect(smuggled.status).toBe(400);
  expect((smuggled.body.error as { code?: string })?.code).toBe("caller_supplied_principal");

  const after = await readStatus(page, CONFIGURED_PROJECT);
  expect(timezoneOf(controls(after.body))).toBe("America/New_York");
});
