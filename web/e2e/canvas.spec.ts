/**
 * Map (`/canvas`) against the real stack.
 *
 * Playwright has no dedicated deterministic `entities.graph` fixture — the
 * canvas page unit file records that, and seeded neighborhood e2e stays on
 * People/search-contract. This spec covers what the disposable empty database
 * can actually produce: unseeded instructional copy, fail-closed as-of, unknown
 * seed, workspace CSRF, and a real stale-version conflict. Overlay
 * non-fabrication after conflict remains in `canvas-map-client.test.tsx`.
 *
 * `PFE-AC-185..190` remain SUPERSEDED (no MossAIc/ChatLLM). This file does not
 * claim scale/performance budgets, visual-regression gates, or real-device
 * proof — those stay WP28/WP30.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { LIVE_URL } from "../playwright.config";
import { EMPTINESS_CLAIMS, expectState, signIn } from "./fixtures";

const UNKNOWN_FOCUS = "ent_aaaaaaaa11111111";
const ATTACKER_ORIGIN = "https://attacker.example";
const OPAQUE_SID = /^[0-9a-f]{64}$/;

const CANVAS_UI_FILES = [
  "src/app/(app)/canvas/canvas-page.tsx",
  "src/app/(app)/canvas/page.tsx",
  "src/components/canvas/canvas-map-client.tsx",
  "src/components/canvas/graph-map.tsx",
  "src/components/canvas/directory-list.tsx",
  "src/components/canvas/canvas-inspector.tsx",
  "src/components/canvas/neighborhood-export.ts",
] as const;

type ErrorEnvelope = {
  code?: string;
  errorClass?: string;
  message?: string;
};

type WorkspaceBody = {
  version?: number;
  updated_at?: string | null;
  positions?: Record<string, { x: number; y: number }>;
  focus_entity_id?: string | null;
  error?: ErrorEnvelope;
};

function canvasUiSource(): string {
  return CANVAS_UI_FILES.map((relative) =>
    readFileSync(path.join(__dirname, "..", relative), "utf8"),
  ).join("\n");
}

function opaqueEntityId(marker: string): string {
  const suffix = `${marker}${crypto.randomUUID().replace(/-/g, "")}`.slice(0, 32);
  return `ent_${suffix}`;
}

async function sessionSid(page: Page, origin: string): Promise<string> {
  const cookies = await page.context().cookies(origin);
  const cookie = cookies.find((entry) => entry.name === "mypa_session");
  expect(cookie, "signed-in context must carry mypa_session").toBeDefined();
  expect(cookie!.httpOnly).toBe(true);
  expect(cookie!.value).toMatch(OPAQUE_SID);
  return cookie!.value;
}

async function inPageWorkspacePost(
  page: Page,
  body: Record<string, unknown>,
): Promise<{ status: number; body: WorkspaceBody }> {
  return page.evaluate(async (payload) => {
    const response = await fetch("/api/canvas/workspace", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    return { status: response.status, body: (await response.json()) as WorkspaceBody };
  }, body);
}

function expectNoNeighborhood(page: Page) {
  return Promise.all([
    expect(page.getByTestId("canvas-empty")).toHaveCount(0),
    expect(page.getByTestId("canvas-directory")).toHaveCount(0),
    expect(page.getByTestId("canvas-map")).toHaveCount(0),
    expect(page.getByTestId("canvas-synthetic")).toHaveCount(0),
  ]);
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("unseeded /canvas is instructional seed-required, not empty-success and not a directory", async ({
  page,
}) => {
  await page.goto("/canvas");
  await expect(page.getByRole("heading", { name: "Map", level: 1 })).toBeVisible();
  await expectState(page, "canvas-seed-required", "empty");
  await expect(page.getByText("A seed is required")).toBeVisible();
  await expect(page.getByTestId("canvas-seed-required")).toContainText(
    /Provide focusEntityId or scopeEntityId/i,
  );
  await expect(page.getByTestId("canvas-seed-required")).toContainText(
    /empty URL is not an empty neighborhood/i,
  );
  await expect(page.getByTestId("canvas-seed-required")).toContainText(
    /not a directory of everyone/i,
  );
  await expect(page.getByRole("link", { name: "Search People" })).toHaveAttribute("href", "/people");
  await expectNoNeighborhood(page);
  const text = (await page.getByTestId("canvas-seed-required").textContent()) ?? "";
  for (const claim of EMPTINESS_CLAIMS) {
    expect(text, "unseeded Map must not claim a successful empty neighborhood").not.toMatch(claim);
  }
});

test("invalid asOf fail-closes without treating it as an empty graph", async ({ page }) => {
  await page.goto(`/canvas?focusEntityId=${UNKNOWN_FOCUS}&asOf=yesterday`);
  await expect(page.getByRole("heading", { name: "Map", level: 1 })).toBeVisible();
  await expectState(page, "canvas-unavailable", "unavailable");
  await expect(page.getByText("That map query was not valid")).toBeVisible();
  await expect(page.getByTestId("surface-state-detail")).toHaveText(
    "asOf must be an RFC 3339 timestamp with an explicit timezone.",
  );
  await expect(page.getByTestId("canvas-seed-required")).toHaveCount(0);
  await expect(page.getByTestId("canvas-not-found")).toHaveCount(0);
  await expect(page.getByTestId("canvas-as-of")).toHaveCount(0);
  await expectNoNeighborhood(page);
});

test("unknown focusEntityId is not_found, not an empty graph", async ({ page }) => {
  await page.goto(`/canvas?focusEntityId=${UNKNOWN_FOCUS}`);
  await expect(page).toHaveURL(new RegExp(`focusEntityId=${UNKNOWN_FOCUS}`));
  await expect(page.getByRole("heading", { name: "Map", level: 1 })).toBeVisible();
  await expectState(page, "canvas-not-found", "unavailable");
  await expect(page.getByText("That neighborhood was not found")).toBeVisible();
  await expect(page.getByTestId("canvas-not-found")).toContainText(
    /Nothing is claimed about other seeds or other principals/i,
  );
  await expect(page.getByTestId("canvas-seed-required")).toHaveCount(0);
  await expect(page.getByTestId("canvas-unavailable")).toHaveCount(0);
  await expectNoNeighborhood(page);
});

test("stale workspace expected_version is a typed conflict and does not fabricate a graph", async ({
  page,
}) => {
  const focusEntityId = opaqueEntityId("wp27ws");
  const first = await inPageWorkspacePost(page, {
    focus_entity_id: focusEntityId,
    expected_version: 0,
    positions: { [focusEntityId]: { x: 12.5, y: 40.25 } },
  });
  expect(first.status, "first overlay write creates version 1").toBe(200);
  expect(first.body.version).toBe(1);
  expect(first.body.positions?.[focusEntityId]).toEqual({ x: 12.5, y: 40.25 });

  const stale = await inPageWorkspacePost(page, {
    focus_entity_id: focusEntityId,
    expected_version: 0,
    positions: { [focusEntityId]: { x: 99, y: 99 } },
  });
  expect(stale.status, "stale expected_version must be 409").toBe(409);
  expect(stale.body.error?.errorClass).toBe("conflict");
  expect(stale.body).not.toHaveProperty("positions");
  expect(stale.body).not.toHaveProperty("version");

  await page.goto(`/canvas?focusEntityId=${encodeURIComponent(focusEntityId)}`);
  await expectState(page, "canvas-not-found", "unavailable");
  await expectNoNeighborhood(page);
  await expect(page.getByTestId("canvas-workspace-conflict")).toHaveCount(0);
});

test("cross-origin workspace POST is 403", async ({ page, playwright }) => {
  const sid = await sessionSid(page, LIVE_URL);
  const focusEntityId = opaqueEntityId("wp27csrf");
  const attacker = await playwright.request.newContext({
    extraHTTPHeaders: {
      origin: ATTACKER_ORIGIN,
      cookie: `mypa_session=${sid}`,
    },
  });
  try {
    const refused = await attacker.post(`${LIVE_URL}/api/canvas/workspace`, {
      data: {
        focus_entity_id: focusEntityId,
        expected_version: 0,
        positions: { [focusEntityId]: { x: 1, y: 1 } },
      },
    });
    expect(refused.status(), "cross-site workspace POST must be 403").toBe(403);
    const body = (await refused.json()) as WorkspaceBody;
    expect(body.error?.code).toBe("cross_site_request");
    if (body.error?.errorClass !== undefined) {
      expect(body.error.errorClass).toBe("authorization");
    }
  } finally {
    await attacker.dispose();
  }

  const replay = await inPageWorkspacePost(page, {
    focus_entity_id: focusEntityId,
    expected_version: 0,
    positions: { [focusEntityId]: { x: 1, y: 1 } },
  });
  expect(replay.status, "same-origin workspace POST must not be 403").not.toBe(403);
  expect(replay.status, "the 403 must not have created the overlay").toBe(200);
  expect(replay.body.version).toBe(1);
});

test("Map destination has no MossAIc/ChatLLM iframe (PFE-AC-185..190 remain SUPERSEDED)", async ({
  page,
}) => {
  const source = canvasUiSource();
  expect(source, "PFE-AC-185..190 remain SUPERSEDED: no MossAIc iframe").not.toMatch(/MossAIc/i);
  expect(source, "PFE-AC-185..190 remain SUPERSEDED: no ChatLLM iframe").not.toMatch(/ChatLLM/i);
  expect(source, "Map destination UI must not embed an iframe").not.toMatch(/<iframe\b/i);

  await page.goto("/canvas");
  await expect(page.getByRole("heading", { name: "Map", level: 1 })).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(0);
});
