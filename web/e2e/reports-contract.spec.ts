import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

type ApiAnswer<T> = { status: number; body: T };

type ReportListBody = {
  state?: string;
  result?: {
    items?: Array<{
      report_id: string;
      cycle_run_id: string;
      title: string;
      artifact_kind: string;
      stage: string;
    }>;
    next_cursor?: string | null;
  };
};

type ReportReadBody = {
  result?: {
    report_id: string;
    body_markdown?: string;
    structured_content?: Record<string, unknown>;
    title: string;
  };
};

type ResolveSetBody = {
  result?: {
    aggregate: string;
    members?: Array<{
      member_id: string;
      readiness: string;
      required: boolean;
      artifact_id: string | null;
    }>;
  };
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

test("BFF report reads keep structured_content and resolve_set members honest", async ({ page }) => {
  test.setTimeout(180_000);

  await page.goto("/intelligence");
  await expect(page.getByRole("heading", { name: "Intelligence", level: 1 })).toBeVisible();
  await expect(page.getByText(/not admitted to current main/i)).toHaveCount(0);
  await expect(page.getByTestId("intelligence-unavailable")).toHaveCount(0);
  await expect(page.getByTestId("intelligence-listing")).toBeVisible();
  const listed = page.getByTestId("intelligence-report").first();
  await expect(listed).toBeVisible();
  await expect(listed).toContainText("E2E morning brief collector");
  await expect(listed).not.toContainText("scraped item one");
  await expect(listed.getByTestId("intelligence-kind")).toHaveText("collector_candidates");

  const list = await api<ReportListBody>(page, "/api/intelligence?pageSize=25");
  expect(list.status).toBe(200);
  expect(list.body.state).toBe("results");
  expect(list.body.result?.next_cursor).toBeNull();
  const item = list.body.result?.items?.find((row) => row.title === "E2E morning brief collector");
  expect(item).toBeTruthy();
  expect(item?.report_id).toMatch(/^rpt_[A-Za-z0-9]{8,64}$/);
  expect(item?.cycle_run_id).toMatch(/^micr_[A-Za-z0-9]{8,64}$/);
  expect(JSON.stringify(item)).not.toMatch(/scraped item one/);

  const search = await api<ReportListBody>(
    page,
    `/api/intelligence?q=${encodeURIComponent("morning brief")}&pageSize=25`,
  );
  expect(search.status).toBe(200);
  expect(search.body.result?.items?.some((row) => row.report_id === item!.report_id)).toBe(true);

  const read = await api<ReportReadBody>(page, `/api/intelligence/${item!.report_id}`);
  expect(read.status).toBe(200);
  expect(read.body.result?.body_markdown).toContain("scraped item one");
  expect(read.body.result?.structured_content).toEqual({
    lane: "persisted",
    marker: "e2e-structured-not-from-markdown",
  });
  expect(read.body.result?.structured_content).not.toEqual(
    expect.objectContaining({ items: expect.anything() }),
  );
  expect(JSON.stringify(read.body.result?.structured_content)).not.toMatch(/scraped item one/);

  const latest = await api<ReportReadBody>(
    page,
    `/api/intelligence/latest?cycleRunId=${encodeURIComponent(item!.cycle_run_id)}`,
  );
  expect(latest.status).toBe(200);
  expect(latest.body.result?.report_id).toBe(item!.report_id);

  const readiness = await api<ResolveSetBody>(
    page,
    `/api/intelligence/readiness?cycleRunId=${encodeURIComponent(item!.cycle_run_id)}&setId=morning_brief_inputs`,
  );
  expect(readiness.status).toBe(200);
  expect(readiness.body.result?.aggregate).toBe("BLOCKED");
  const members = readiness.body.result?.members ?? [];
  expect(members.length).toBeGreaterThan(1);
  expect(members.every((member) => typeof member.member_id === "string")).toBe(true);
  expect(members.every((member) => typeof member.readiness === "string")).toBe(true);
  expect(members.every((member) => typeof member.required === "boolean")).toBe(true);
  expect(members.some((member) => member.readiness === "MISSING")).toBe(true);
  expect(members.map((member) => member.readiness)).not.toEqual([
    readiness.body.result?.aggregate,
  ]);
});
