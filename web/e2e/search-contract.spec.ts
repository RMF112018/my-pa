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
  expect(goodnotes?.state).toBe("omitted");
  expect(goodnotes?.reason).toBe("goodnotes_not_activated");
  expect(goodnotes).not.toEqual(expect.objectContaining({ state: "searched", hitCount: 0 }));

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
