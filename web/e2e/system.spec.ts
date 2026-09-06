/**
 * System, against the live gateway, on desktop.
 *
 * Capability readiness is counted off `capabilities.get`. Live worker health is
 * a different field. Connected sources are unknown — never an invented empty
 * list — and git SHA / deployed artifact identity is not restated here (WP29).
 * PWA fields on this page are labelled as this-browser observations; the server
 * route does not claim them. Morning Intelligence members stay listed when the
 * aggregate is not READY.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

type ApiAnswer<T> = { status: number; body: T };

type SystemBody = {
  connectedSources?: unknown;
  gitSha?: unknown;
  git_sha?: unknown;
  commitSha?: unknown;
  revision?: unknown;
  schemaHead?: unknown;
  pwa?: {
    observation?: string;
    controller?: unknown;
    caches?: unknown;
    online?: unknown;
    queueCounts?: unknown;
  };
  backend?: {
    readiness?: { implemented_capabilities?: number; total_capabilities?: number; state?: string };
    workerPlanes?: Array<{ state?: string; last_heartbeat_at?: string | null }>;
    intelligence?: {
      state?: string;
      result?: { aggregate?: string; members?: Array<{ readiness?: string }> };
    };
  };
};

async function api<T>(page: Page, path: string): Promise<ApiAnswer<T>> {
  return page.evaluate(async (target) => {
    const response = await fetch(target, {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
    });
    return { status: response.status, body: (await response.json()) as T };
  }, path);
}

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "System live-gateway protection is measured on desktop");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("System shows capability readiness against live health without inventing sources or a git SHA", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.goto("/system");
  await expect(page.getByRole("heading", { name: "System", level: 1 })).toBeVisible();

  await expect(page.getByTestId("system-readiness")).toContainText(
    /\d+ of [1-9]\d* contracted capabilities/,
  );
  await expect(page.getByTestId("system-readiness-unknown")).toHaveCount(0);
  await expect(page.getByTestId("system-available")).toBeVisible();

  const heartbeatKnown = page.getByTestId("system-worker-heartbeat");
  const heartbeatUnknown = page.getByTestId("system-worker-heartbeat-unknown");
  expect((await heartbeatKnown.count()) + (await heartbeatUnknown.count())).toBeGreaterThan(0);
  if ((await page.getByTestId("system-worker-not-healthy").count()) > 0) {
    await expect(page.getByTestId("system-worker-not-healthy").first()).toBeVisible();
  }

  await expect(page.getByTestId("system-sources-unknown")).toContainText(/cannot list/i);
  await expect(page.getByTestId("system-sources-unknown")).toContainText(/unknown/i);
  await expect(page.getByText(/None connected/)).toHaveCount(0);
  await expect(page.getByTestId("system-git-sha")).toHaveCount(0);

  const system = await api<SystemBody>(page, "/api/system");
  expect(system.status).toBe(200);
  expect(system.body.connectedSources).toBeNull();
  expect(system.body).not.toHaveProperty("gitSha");
  expect(system.body).not.toHaveProperty("git_sha");
  expect(system.body).not.toHaveProperty("commitSha");
  expect(system.body).not.toHaveProperty("revision");
  expect(system.body).not.toHaveProperty("schemaHead");
  expect(system.body.backend?.readiness?.total_capabilities).toBeGreaterThan(0);
});

test("System PWA fields are this-browser observations, not server truth", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/system");

  await expect(page.getByTestId("system-pwa-client-side")).toContainText(/this browser/i);
  await expect(page.getByTestId("system-pwa-client-side")).toContainText(/client-side/i);
  await expect(page.getByTestId("system-pwa-this-browser")).toBeVisible();
  await expect(page.getByTestId("system-pwa-online")).toContainText(/this browser/i);
  await expect(page.getByTestId("system-pwa-queue")).toContainText(/this browser/i);
  await expect(page.getByTestId("system-pwa-queue")).toContainText(/not the server/i);
  await expect(page.getByText("PWA_FIELDS_PENDING_WP26")).toHaveCount(0);

  const system = await api<SystemBody>(page, "/api/system");
  expect(system.status).toBe(200);
  expect(system.body.pwa?.observation).toBe("client_side");
  expect(system.body.pwa).not.toHaveProperty("controller");
  expect(system.body.pwa).not.toHaveProperty("caches");
  expect(system.body.pwa).not.toHaveProperty("online");
  expect(system.body.pwa).not.toHaveProperty("queueCounts");
});

test("Morning Intelligence members stay visible when the aggregate is not READY", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.goto("/system");

  await expect(page.getByTestId("system-intelligence-not-system-health")).toContainText(
    /not a claim that the system is healthy/i,
  );
  await expect(page.getByTestId("system-intelligence-aggregate")).toBeVisible();
  await expect(page.getByTestId("system-intelligence-members")).toBeVisible();

  const aggregate = ((await page.getByTestId("system-intelligence-aggregate").textContent()) ?? "").trim();
  const states = await page.getByTestId("system-intelligence-member-readiness").allTextContents();
  expect(states.length).toBeGreaterThan(0);
  expect(states).not.toEqual([aggregate]);
  if (aggregate !== "READY") {
    expect(states.some((state) => state.trim() !== "READY")).toBe(true);
    await expect(page.getByTestId("system-intelligence-member").first()).toBeVisible();
  }
});
