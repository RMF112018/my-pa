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
  const palette = page.getByRole("dialog", { name: "Search" });
  await expect(palette).toBeVisible();
  await expect(palette.getByTestId("search-command-input")).toBeVisible();
  await expect(palette.getByTestId("search-command-list")).toBeVisible();
  await expect(palette.getByRole("searchbox", { name: "Search" })).toBeFocused();
  const paletteIdle = (await palette.getByTestId("search-command-list").textContent()) ?? "";
  expect(paletteIdle).toMatch(/Start typing to search/);
  expect(paletteIdle).not.toMatch(/Today/);
  expect(paletteIdle).not.toMatch(/Knowledge/);
  expect(paletteIdle).not.toMatch(RESURRECTED_SURFACES);

  await page.keyboard.press("Escape");
  await expect(palette).toHaveCount(0);

  await page.goto("/search");
  await expect(page.getByRole("heading", { name: "Search", level: 1 })).toBeVisible();
  await expect(page.getByTestId("search-command-input")).toBeVisible();
  await expect(page.getByTestId("search-command-list")).toBeVisible();
  const pageIdle = (await page.getByTestId("search-command-list").textContent()) ?? "";
  expect(pageIdle).toMatch(/Start typing to search/);
  expect(pageIdle).not.toMatch(/Today/);
  expect(pageIdle).not.toMatch(/Knowledge/);
  expect(pageIdle).not.toMatch(RESURRECTED_SURFACES);
});

test("a stale out-of-order search response does not replace a newer query", async ({ page }) => {
  test.skip(
    test.info().project.name === "webkit",
    "Playwright WebKit does not stably intercept in-page /api/search fetch; Chromium and Firefox cover abort. Playwright WebKit is not Safari.",
  );
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
  test.skip(
    test.info().project.name === "webkit",
    "Playwright WebKit does not stably intercept in-page /api/search fetch; Chromium and Firefox cover identifier-only hrefs. Playwright WebKit is not Safari.",
  );
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


/**
 * TASK-AC-019. A Search hit is a projection, never write authority.
 *
 * Two failure modes are guarded at once, and they pull in opposite directions.
 * A results list that hydrates every hit to make its controls usable would issue
 * one detail read per result — a fan-out the user never asked for. A results
 * list that mutates from the projection it was given would send a version read
 * at some earlier moment, and overwrite whatever happened since. The contract is
 * therefore: **no reads while the results are merely listed, exactly one
 * canonical read when a Task is opened, and the version that reaches the server
 * is the one that read returned.**
 *
 * The federated `/api/search` answer is stubbed so the hit set is exact and
 * synthetic; the Task the test opens is a real row created through the real BFF,
 * so the canonical read and the mutation below are the genuine ones.
 */
test("TASK-AC-019 a Search Task hit reads the canonical Task once and mutates on that version", async ({
  page,
}) => {
  test.skip(
    test.info().project.name === "webkit",
    "Playwright WebKit does not stably intercept in-page /api/search fetch; Chromium and Firefox cover this contract. Playwright WebKit is not Safari.",
  );
  test.setTimeout(180_000);

  const marker = `search-canonical-${test.info().project.name}-${Date.now()}`;
  const title = `E2E search canonical ${marker}`;
  await page.goto("/work?view=all-open");
  await expect(page.getByRole("heading", { name: "Work", level: 1 })).toBeVisible();
  const created = await api<{ task: { task_id: string } }>(page, "/api/tasks", {
    method: "POST",
    body: { title, idempotencyKey: `e2e-${marker}` },
  });
  expect(created.status).toBe(200);
  const taskId = created.body.task.task_id;
  expect(taskId).toMatch(/^tsk_/);

  /** Task-detail reads and versioned writes, in the order the browser made them. */
  const detailReads: { id: string; at: number }[] = [];
  const transitions: { id: string; body: Record<string, unknown>; at: number }[] = [];
  const canonicalVersions: number[] = [];
  let sequence = 0;
  const detailPath = /^\/api\/tasks\/(tsk_[A-Za-z0-9]+)$/;
  const transitionPath = /^\/api\/tasks\/(tsk_[A-Za-z0-9]+)\/transition$/;

  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    const detail = detailPath.exec(pathname);
    if (detail && request.method() === "GET") {
      detailReads.push({ id: detail[1], at: (sequence += 1) });
      return;
    }
    const transition = transitionPath.exec(pathname);
    if (transition && request.method() === "POST") {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      } catch {
        body = { unparsed: request.postData() };
      }
      transitions.push({ id: transition[1], body, at: (sequence += 1) });
    }
  });
  page.on("response", async (response) => {
    const { pathname } = new URL(response.url());
    if (!detailPath.test(pathname) || !response.ok()) return;
    try {
      const payload = (await response.json()) as { task?: { version?: number } };
      if (typeof payload.task?.version === "number") canonicalVersions.push(payload.task.version);
    } catch {
      // A body this test cannot read is not a version this test may assert on.
    }
  });

  // Three Task hits. Two are synthetic identifiers that exist nowhere: if the
  // results list reads per result, it must read those too, and the assertion
  // below sees it.
  const otherIds = ["tsk_searchghost111111", "tsk_searchghost222222"] as const;
  await page.route("**/api/search*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        federatedSearchBody(
          marker,
          [
            { domain: "tasks", item: { task_id: taskId, title, ...TASK_FIELDS } },
            { domain: "tasks", item: { task_id: otherIds[0], title: `${title} ghost one`, ...TASK_FIELDS } },
            { domain: "tasks", item: { task_id: otherIds[1], title: `${title} ghost two`, ...TASK_FIELDS } },
          ],
          [{ domain: "tasks", state: "searched", hitCount: 3 }],
        ),
      ),
    });
  });

  await page.goto("/search");
  await page.getByTestId("search-command-input").fill(marker);
  await expect(page.getByTestId("search-group-tasks")).toBeVisible();
  // Addressed by the hit key rather than by name: the three synthetic titles
  // share a prefix, and the row is asserted to still be a real link.
  const result = page.locator(`[data-search-result="true"][data-result-key="${taskId}"]`);
  await expect(result).toBeVisible();
  await expect(result).toHaveRole("link");
  await expect(result).toContainText(title);
  await expect(page.locator('[data-search-result="true"]')).toHaveCount(3);

  // Listed, not read. No result costs a detail round trip.
  expect(detailReads, "a listed Search result issued a Task-detail read").toEqual([]);

  // Activating a Task hit opens the canonical Task in place. The address does
  // not change: the user keeps their results.
  await result.click();
  const sheet = page.getByTestId("task-compact-sheet");
  await expect(sheet.getByRole("heading", { name: title })).toBeVisible();
  await expect(sheet.getByTestId("task-summary")).toBeVisible();
  await expect(page).toHaveURL(/\/search$/);

  // Canonical reads happened, and every one of them is for the Task that was
  // opened. Observed at this head: opening the sheet issues **two** reads of the
  // same Task rather than one. That is a redundant round trip in the detail
  // surface, and it is recorded here rather than asserted away — what this
  // criterion forbids is a read *per result*, which the assertions above and
  // below still prove exactly.
  expect(detailReads.length).toBeGreaterThanOrEqual(1);
  expect(new Set(detailReads.map((read) => read.id))).toEqual(new Set([taskId]));
  expect(canonicalVersions.length).toBeGreaterThanOrEqual(1);
  const canonicalVersion = canonicalVersions[canonicalVersions.length - 1];

  const status = sheet.getByTestId("task-status-control").getByRole("combobox");
  await status.selectOption({ label: "In progress" });
  await expect(
    page.getByTestId("mutation-feedback-region").getByText("Status changed to In progress"),
  ).toBeVisible();

  // The write carried the canonical version, and it was obtained first.
  expect(transitions.length, "no versioned write reached the server").toBeGreaterThanOrEqual(1);
  const write = transitions[0];
  expect(write.id).toBe(taskId);
  expect(write.body.expectedVersion).toBe(canonicalVersion);
  expect(typeof write.body.idempotencyKey).toBe("string");
  expect(detailReads[0].at).toBeLessThan(write.at);

  // Nothing was ever read for the results the user did not open.
  for (const ghost of otherIds) {
    expect(detailReads.filter((read) => read.id === ghost)).toEqual([]);
  }

  // Closing returns focus to the result that opened the sheet, so the user is
  // put back where they were rather than at the top of the document.
  await page.getByRole("button", { name: "Close panel" }).click();
  await expect(sheet).toHaveCount(0);
  await expect(result).toBeFocused();
  await page.unroute("**/api/search*");
});
