import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

type ApiAnswer<T> = { status: number; body: T };

type CoverageRow = {
  domain?: string;
  state?: string;
  hitCount?: number;
  reason?: string;
};

type SearchHit = {
  domain?: string;
  item?: {
    report_id?: string;
    artifact_kind?: string;
    entity_id?: string;
  };
};

type SearchBody = {
  shape?: string;
  query?: string;
  hits?: SearchHit[];
  coverage?: CoverageRow[];
};

async function api<T>(
  page: Page,
  path: string,
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
    { target: path, method: options.method, payload: options.body },
  );
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

test("Federated Search BFF keeps typed hits and honest omitted coverage", async ({ page }) => {
  test.setTimeout(180_000);

  const search = await api<SearchBody>(page, "/api/search?q=morning%20brief");
  expect(search.status).toBe(200);
  expect(search.body.shape).toBe("backend");

  const coverage = search.body.coverage ?? [];
  const goodnotes = coverage.find((row) => row.domain === "goodnotes");
  expect(goodnotes).toBeDefined();
  expect(goodnotes?.state).not.toBe("omitted");
  expect(goodnotes?.reason).not.toBe("goodnotes_not_activated");
  if (goodnotes?.state === "searched") {
    expect(goodnotes.hitCount).toBeGreaterThanOrEqual(0);
  } else {
    expect(["unavailable", "degraded"]).toContain(goodnotes?.state);
    expect(goodnotes?.hitCount).toBe(0);
    expect(goodnotes).not.toEqual(expect.objectContaining({ state: "searched", hitCount: 0 }));
  }

  for (const domain of ["tasks", "commitments", "capture", "reports", "entities"]) {
    const row = coverage.find((entry) => entry.domain === domain);
    expect(row).toBeDefined();
    expect(row?.state).not.toBe("omitted");
  }
  expect(coverage.find((row) => row.domain === "meetings")?.state).toBe("omitted");
  expect(coverage.find((row) => row.domain === "projects")?.state).toBe("omitted");
  expect(coverage.find((row) => row.domain === "canvas")?.state).toBe("omitted");
  expect(coverage.find((row) => row.domain === "relationship_memory")?.state).toBe("omitted");

  const knowledge = coverage.find((row) => row.domain === "knowledge");
  expect(knowledge?.state).toBe("knowledge_not_enrolled");
  expect(knowledge).not.toEqual(expect.objectContaining({ state: "searched", hitCount: 0 }));

  const reportHits = (search.body.hits ?? []).filter((hit) => hit.domain === "reports");
  for (const hit of reportHits) {
    expect(hit.item?.report_id).toMatch(/^rpt_[A-Za-z0-9]{8,64}$/);
    expect(hit.item).not.toEqual(expect.objectContaining({ items: expect.anything() }));
  }
  expect(JSON.stringify(reportHits)).not.toMatch(/brief-item/);
  expect(JSON.stringify(reportHits)).not.toMatch(/BriefSection|BriefItem/);

  const entityHits = (search.body.hits ?? []).filter((hit) => hit.domain === "entities");
  for (const hit of entityHits) {
    expect(hit.item?.entity_id).toMatch(/^ent_/);
  }
  expect(JSON.stringify(entityHits)).not.toMatch(/resolution/);
});

test("Search UX maps federated hits to honest hrefs without capture text", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/search");
  await expect(page.getByRole("heading", { name: "Search", level: 1 })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search" }).fill("morning brief");
  await expect(
    page.locator(
      "[data-testid='search-coverage'], [data-testid='search-not-implemented'], [data-testid='search-unavailable']",
    ).first(),
  ).toBeVisible({ timeout: 30_000 });

  const captureLinks = page.locator('a[href*="captureId="]');
  const captureCount = await captureLinks.count();
  for (let index = 0; index < captureCount; index += 1) {
    const href = (await captureLinks.nth(index).getAttribute("href")) ?? "";
    expect(href).toMatch(/\/knowledge\?/);
    expect(href).toMatch(/captureId=cap_/);
    expect(href).toMatch(/versionId=/);
    expect(href).not.toMatch(/text=/);
  }

  const goodnotesLinks = page.locator('a[href*="/knowledge/goodnotes"]');
  const goodnotesCount = await goodnotesLinks.count();
  for (let index = 0; index < goodnotesCount; index += 1) {
    const href = (await goodnotesLinks.nth(index).getAttribute("href")) ?? "";
    expect(href).toMatch(/\/knowledge\/goodnotes\?/);
    expect(href).toMatch(/pageVersionId=|runId=/);
    expect(href).not.toMatch(/transcription=/);
    expect(href).not.toMatch(/snippet=/);
    expect(href).not.toMatch(/body=/);
  }

  await expect(page.locator('a[href*="knowledgeId="]')).toHaveCount(0);
});
