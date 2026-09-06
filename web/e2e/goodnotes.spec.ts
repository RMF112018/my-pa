/**
 * Knowledge / GoodNotes in a real browser against the real stack.
 *
 * The e2e gateway is a disposable empty database, not `MYPA_DATA_PROVIDER=synthetic`
 * and not a live GoodNotes NAS. Catalog answers are therefore empty, unavailable,
 * or not_implemented — never a fixture notebook, and never a guessed raster.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { expectState, signIn } from "./fixtures";

type ApiAnswer<T> = { status: number; body: T };

type CoverageRow = {
  domain?: string;
  state?: string;
  hitCount?: number;
};

type SearchHit = {
  domain?: string;
};

type SearchBody = {
  shape?: string;
  hits?: SearchHit[];
  coverage?: CoverageRow[];
};

const IDENTIFIER_QUERY_KEYS = new Set([
  "notebookId",
  "logicalPageId",
  "pageVersionId",
  "runId",
  "contentSha256",
]);

const CATALOG_STATES = [
  { testId: "goodnotes-notebooks-empty", kind: "empty" },
  { testId: "goodnotes-notebooks-unavailable", kind: "unavailable" },
  { testId: "goodnotes-synthetic", kind: "not_implemented" },
  { testId: "goodnotes-notebooks-degraded-empty", kind: "degraded" },
] as const;

async function api<T>(
  page: Page,
  pathName: string,
  options: { method?: string; body?: Record<string, unknown> } = {},
): Promise<ApiAnswer<T>> {
  return page.evaluate(
    async ({ target, method, payload }) => {
      const response = await fetch(target, {
        method: method ?? "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: payload
          ? { "content-type": "application/json", origin: window.location.origin }
          : undefined,
        body: payload ? JSON.stringify(payload) : undefined,
      });
      return { status: response.status, body: (await response.json()) as T };
    },
    { target: pathName, method: options.method, payload: options.body },
  );
}

function evidenceSplitSource(): string {
  return readFileSync(
    path.join(__dirname, "../src/components/goodnotes/evidence-split.tsx"),
    "utf8",
  );
}

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

async function expectCatalogWithoutEvidence(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "GoodNotes", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to Knowledge" })).toBeVisible();
  await expect(page.getByTestId("goodnotes-evidence")).toHaveCount(0);
  await expect(page.getByTestId("goodnotes-evidence-tablist")).toHaveCount(0);
  await expect(page.getByTestId("goodnotes-evidence-split")).toHaveCount(0);
  await expect(page.locator('img[src*="/api/goodnotes/raster"]')).toHaveCount(0);

  const listing = page.getByTestId("goodnotes-notebooks");
  let catalogStateCount = 0;
  for (const state of CATALOG_STATES) {
    catalogStateCount += await page.getByTestId(state.testId).count();
  }
  expect(
    catalogStateCount + (await listing.count()),
    "GoodNotes catalog must render a truthful SurfaceState or a gateway listing, never a blank page",
  ).toBeGreaterThan(0);

  for (const state of CATALOG_STATES) {
    if ((await page.getByTestId(state.testId).count()) > 0) {
      await expectState(page, state.testId, state.kind);
    }
  }
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("Knowledge shows a GoodNotes entry that does not claim notebooks exist", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/knowledge");
  const entry = page.getByTestId("knowledge-goodnotes-entry");
  await expect(entry).toBeVisible();
  await expect(entry.getByRole("link", { name: "Open GoodNotes" })).toHaveAttribute(
    "href",
    "/knowledge/goodnotes",
  );
  await expect(entry).toContainText(/does not mean notebooks are present/i);
  await expect(entry).not.toContainText(/you have notebooks/i);
  await expect(entry.getByTestId("goodnotes-notebooks")).toHaveCount(0);

  await entry.getByRole("link", { name: "Open GoodNotes" }).click();
  await expect(page).toHaveURL(/\/knowledge\/goodnotes$/);
  await expectCatalogWithoutEvidence(page);
});

test("GoodNotes catalog is a truthful SurfaceState, never a fixture notebook", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/knowledge/goodnotes");
  await expectCatalogWithoutEvidence(page);
});

test("incomplete runId deep link fails closed without guessing a raster", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/knowledge/goodnotes?runId=gnrun_aaaaaaaaaaaaaaaaaaaaaaaa");
  await expectState(page, "goodnotes-read-missing-ids", "unavailable");
  await expect(page.getByTestId("goodnotes-read-missing-ids")).toContainText(/was not guessed/i);
  await expect(page.getByTestId("goodnotes-evidence")).toHaveCount(0);
  await expect(page.locator('img[src*="/api/goodnotes/raster"]')).toHaveCount(0);
  await expect(page.getByTestId("goodnotes-notebooks")).toHaveCount(0);
});

test("search coverage still includes goodnotes and hit hrefs stay identifier-only", async ({
  page,
}) => {
  test.setTimeout(180_000);

  const search = await api<SearchBody>(page, "/api/search?q=morning%20brief");
  expect(search.status).toBe(200);
  const goodnotes = (search.body.coverage ?? []).find((row) => row.domain === "goodnotes");
  expect(goodnotes).toBeDefined();
  expect(goodnotes?.state).not.toBe("omitted");
  expect(goodnotes?.state).not.toBe("knowledge_not_enrolled");

  await page.goto("/search");
  await page.getByRole("searchbox", { name: "Search" }).fill("morning brief");
  await expect(
    page
      .locator(
        "[data-testid='search-coverage'], [data-testid='search-not-implemented'], [data-testid='search-unavailable']",
      )
      .first(),
  ).toBeVisible({ timeout: 30_000 });

  const goodnotesLinks = page.locator('a[href*="/knowledge/goodnotes"]');
  const goodnotesCount = await goodnotesLinks.count();
  if ((search.body.hits ?? []).some((hit) => hit.domain === "goodnotes")) {
    expect(goodnotesCount).toBeGreaterThan(0);
  }
  for (let index = 0; index < goodnotesCount; index += 1) {
    const href = (await goodnotesLinks.nth(index).getAttribute("href")) ?? "";
    expect(href).toMatch(/^\/knowledge\/goodnotes\?/);
    expect(href).not.toMatch(/transcription=/);
    expect(href).not.toMatch(/snippet=/);
    expect(href).not.toMatch(/body=/);
    const target = new URL(href, "http://example.invalid");
    for (const key of target.searchParams.keys()) {
      expect(IDENTIFIER_QUERY_KEYS.has(key), `unexpected GoodNotes search param ${key}`).toBe(true);
    }
    expect(
      target.searchParams.has("pageVersionId") || target.searchParams.has("runId"),
    ).toBe(true);
  }

  if (goodnotesCount > 0) {
    const firstHref = (await goodnotesLinks.first().getAttribute("href")) ?? "";
    await page.goto(firstHref);
    await expect(page).toHaveURL(/\/knowledge\/goodnotes\?/);
    await expect(page.getByRole("heading", { name: "GoodNotes", level: 1 })).toBeVisible();
  }
});

test("desktop and tablet catalog layout keep the evidence split as md:grid-cols-2", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  test.skip(
    testInfo.project.name === "mobile",
    "mobile overflow is measured in the dedicated 390x844 test",
  );

  const source = evidenceSplitSource();
  expect(source).toMatch(/data-testid="goodnotes-evidence-tablist"/);
  expect(source).toMatch(/className="[^"]*md:hidden/);
  expect(source).toMatch(/data-testid="goodnotes-evidence-split"/);
  expect(source).toMatch(/md:grid-cols-2/);

  await page.goto("/knowledge/goodnotes");
  await expectCatalogWithoutEvidence(page);

  if (testInfo.project.name === "tablet") {
    expect(page.viewportSize()?.width).toBe(768);
  } else {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/knowledge/goodnotes");
    await expectCatalogWithoutEvidence(page);
  }
  expect(await horizontalOverflow(page), "catalog overflows horizontally at 768").toBeLessThanOrEqual(
    1,
  );
});

test("mobile catalog does not overflow when evidence is not shown", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/knowledge/goodnotes");
  await expectCatalogWithoutEvidence(page);
  expect(await horizontalOverflow(page), "catalog overflows horizontally at 390x844").toBeLessThanOrEqual(
    1,
  );
});
