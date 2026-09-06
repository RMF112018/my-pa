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

const RESURRECTED_SURFACES = /Assistant|ChatLLM|MossAIc/i;

const TASK_FIELDS = {
  lifecycle_state: "open",
  priority: "p2",
  due_at: null,
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-09-06T00:00:00Z",
  updated_at: "2026-09-06T00:00:00Z",
  version: 1,
} as const;

function federatedSearchBody(query: string, hits: unknown[], coverage: unknown[]) {
  return {
    shape: "backend",
    query,
    hits,
    coverage,
  };
}

test("Cmd/Ctrl+K opens the same SearchCommandPanel as /search", async ({ page }) => {
  test.setTimeout(180_000);
  await page.locator("body").click();
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command menu" });
  await expect(palette).toBeVisible();
  await expect(palette.getByTestId("search-command-input")).toBeVisible();
  await expect(palette.getByTestId("search-command-list")).toBeVisible();
  await expect(palette.getByRole("searchbox", { name: "Search" })).toBeFocused();
  const paletteDestinations = (await palette.getByTestId("search-command-list").textContent()) ?? "";
  expect(paletteDestinations).toMatch(/Today/);
  expect(paletteDestinations).toMatch(/Knowledge/);
  expect(paletteDestinations).not.toMatch(RESURRECTED_SURFACES);

  await page.keyboard.press("Escape");
  await expect(palette).toHaveCount(0);

  await page.goto("/search");
  await expect(page.getByRole("heading", { name: "Search", level: 1 })).toBeVisible();
  await expect(page.getByTestId("search-command-input")).toBeVisible();
  await expect(page.getByTestId("search-command-list")).toBeVisible();
  const pageDestinations = (await page.getByTestId("search-command-list").textContent()) ?? "";
  expect(pageDestinations).toMatch(/Today/);
  expect(pageDestinations).toMatch(/Knowledge/);
  expect(pageDestinations).not.toMatch(RESURRECTED_SURFACES);
});

test("a stale out-of-order search response does not replace a newer query", async ({ page }) => {
  test.setTimeout(180_000);
  let releaseOlder: () => void = () => undefined;
  const olderHold = new Promise<void>((resolve) => {
    releaseOlder = resolve;
  });

  await page.route("**/api/search*", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("q") ?? "";
    const title = query === "older-query" ? "Older synthetic task" : "Newer synthetic task";
    const taskId = query === "older-query" ? "tsk_olderquery11111111" : "tsk_newerquery11111111";
    const body = federatedSearchBody(
      query,
      [{ domain: "tasks", item: { task_id: taskId, title, ...TASK_FIELDS } }],
      [{ domain: "tasks", state: "searched", hitCount: 1 }],
    );
    try {
      if (query === "older-query") await olderHold;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    } catch {
      await route.abort();
    }
  });

  await page.goto("/search");
  await page.getByTestId("search-command-input").fill("older-query");
  await page.waitForRequest((request) => {
    return request.url().includes("/api/search") && request.url().includes("older-query");
  });
  await page.getByTestId("search-command-input").fill("newer-query");
  await page.waitForResponse((response) => {
    return response.url().includes("/api/search") && response.url().includes("newer-query") && response.ok();
  });
  await expect(page.getByRole("link", { name: "Newer synthetic task" })).toBeVisible();
  releaseOlder();
  await expect(page.getByRole("link", { name: "Newer synthetic task" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Older synthetic task" })).toHaveCount(0);
  await page.unroute("**/api/search*");
});

test("Capture and Knowledge search hrefs are identifier-only", async ({ page }) => {
  test.setTimeout(180_000);
  await page.route("**/api/search*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        federatedSearchBody(
          "synthetic-id-only",
          [
            {
              domain: "capture",
              item: {
                capture_id: "cap_aaaaaaaa11111111",
                version_id: "capver_aaaaaaaa11111111",
                version_number: 1,
                character_count: 12,
                recorded_at: "2026-09-06T00:00:00Z",
                text: "SECRET_CAPTURE_BODY_MUST_NOT_LEAK",
              },
            },
            {
              domain: "knowledge",
              item: {
                knowledge_id: "kno_aaaaaaaa11111111",
                label: "Stored note",
                snippet: "SECRET_KNOWLEDGE_SNIPPET_MUST_NOT_LEAK",
                rank: "strong",
                source_id: "src_aaaaaaaa11111111",
                source_object_id: "sobj_aaaaaaaa11111111",
                version_id: "kver_aaaaaaaa11111111",
              },
            },
          ],
          [
            { domain: "capture", state: "searched", hitCount: 1 },
            { domain: "knowledge", state: "searched", hitCount: 1 },
          ],
        ),
      ),
    });
  });

  await page.goto("/search?enrollmentId=enr_aaaaaaaa11111111");
  await page.getByTestId("search-command-input").fill("synthetic-id-only");
  await expect(page.getByTestId("search-group-capture")).toBeVisible();
  await expect(page.getByTestId("search-group-knowledge")).toBeVisible();

  const captureHref = (await page.locator('a[href*="captureId="]').first().getAttribute("href")) ?? "";
  expect(captureHref).toMatch(/\/knowledge\?/);
  expect(captureHref).toMatch(/captureId=cap_aaaaaaaa11111111/);
  expect(captureHref).toMatch(/versionId=capver_aaaaaaaa11111111/);
  expect(captureHref).not.toMatch(/text=/);
  expect(captureHref).not.toMatch(/body=/);
  expect(captureHref).not.toContain("SECRET_CAPTURE_BODY");

  const knowledgeHref =
    (await page.locator('a[href*="knowledgeId="]').first().getAttribute("href")) ?? "";
  expect(knowledgeHref).toMatch(/\/knowledge\?/);
  expect(knowledgeHref).toMatch(/knowledgeId=kno_aaaaaaaa11111111/);
  expect(knowledgeHref).toMatch(/enrollmentId=enr_aaaaaaaa11111111/);
  expect(knowledgeHref).not.toMatch(/snippet=/);
  expect(knowledgeHref).not.toMatch(/body=/);
  expect(knowledgeHref).not.toMatch(/text=/);
  expect(knowledgeHref).not.toContain("SECRET_KNOWLEDGE_SNIPPET");
  await page.unroute("**/api/search*");
});

test("Search destinations and empty state do not resurrect Assistant, ChatLLM, or MossAIc", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.goto("/search");
  const idle = (await page.getByTestId("search-command-list").textContent()) ?? "";
  expect(idle).not.toMatch(RESURRECTED_SURFACES);
  await expect(page.getByRole("button", { name: "Assistant" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Assistant|ChatLLM|MossAIc/ })).toHaveCount(0);

  await page.route("**/api/search*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        federatedSearchBody("synthetic-empty-query", [], [
          { domain: "tasks", state: "searched", hitCount: 0 },
        ]),
      ),
    });
  });
  await page.getByTestId("search-command-input").fill("synthetic-empty-query");
  await expect(page.getByTestId("search-empty")).toBeVisible();
  const empty = (await page.getByTestId("search-empty").textContent()) ?? "";
  expect(empty).not.toMatch(RESURRECTED_SURFACES);
  await expect(page.getByTestId("search-empty").getByRole("link", { name: /Assistant|ChatLLM|MossAIc/ })).toHaveCount(
    0,
  );
  await page.unroute("**/api/search*");
});

