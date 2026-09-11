/**
 * T08-09: the six Constraint reads over the real synthetic stack.
 *
 * Browser → same-origin BFF → server-only gateway transport → Python capability
 * dispatcher → the WP03 read service → an isolated, disposable PostgreSQL that
 * `stack.sh` creates, migrates, seeds and drops. No fixture satisfies any
 * assertion here: the rows come from the Constraint seed step in `e2e/stack.sh`, and the page
 * the WP05 shell renders is deliberately *not* what is being read.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

/** Mirrors the Constraint seed step in `e2e/stack.sh`. Synthetic, disposable, Principal-bound. */
const PROJECT = "prj_e2ecst0000000001";
const CATEGORY = "ccat_e2ecst0000000001";
const FIRST = "cst_e2ecst0000000001";
const SECOND = "cst_e2ecst0000000002";

/** A well-formed identifier of a record this Principal does not have. */
const FOREIGN_PROJECT = "prj_e2ecstzzzzzzzz99";
const FOREIGN_CONSTRAINT = "cst_e2ecstzzzzzzzz99";

const BASE = `/api/project-controls/projects`;

type Answer = { status: number; cacheControl: string | null; body: Record<string, unknown> };

async function read(page: Page, pathName: string): Promise<Answer> {
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
  }, pathName);
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("all six read capabilities answer from PostgreSQL through the BFF", async ({ page }) => {
  test.setTimeout(180_000);

  const register = await read(page, `${BASE}/${PROJECT}/constraints?scope=all&sort=code&dir=asc`);
  expect(register.status).toBe(200);
  expect(register.cacheControl).toBe("private, no-store");
  const rows = register.body.constraints as Record<string, unknown>[];
  expect(rows.map((row) => row.constraintCode)).toEqual(["1.01", "1.02"]);
  // The derived flags are the backend's, decoded as required booleans.
  for (const row of rows) {
    expect(typeof row.isOverdue).toBe("boolean");
    expect(typeof row.isDueSoon).toBe("boolean");
    expect(typeof row.inMyCourt).toBe("boolean");
    expect(row.syncState).toBe("never_synced");
    expect(typeof row.constraintCode).toBe("string");
  }

  const search = await read(page, `${BASE}/${PROJECT}/constraints?q=Crane&scope=all`);
  expect(search.status).toBe(200);
  const hits = search.body.constraints as Record<string, unknown>[];
  expect(hits).toHaveLength(1);
  expect(hits[0].constraintId).toBe(SECOND);

  const detail = await read(page, `${BASE}/${PROJECT}/constraints/${FIRST}`);
  expect(detail.status).toBe(200);
  const constraint = detail.body.constraint as Record<string, unknown>;
  expect(constraint.constraintId).toBe(FIRST);
  expect(constraint.version).toBe(2);
  expect(Array.isArray(constraint.relationships)).toBe(true);
  expect(Array.isArray(constraint.evidenceLinks)).toBe(true);
  expect((constraint.sync as Record<string, unknown>).state).toBe("never_synced");

  const history = await read(page, `${BASE}/${PROJECT}/constraints/${FIRST}/history?pageSize=10`);
  expect(history.status).toBe(200);
  const receipts = history.body.history as Record<string, unknown>[];
  expect(receipts).toHaveLength(1);
  expect(receipts[0].outcome).toBe("no_op");
  expect(receipts[0].afterVersion).toBe(2);

  const overview = await read(page, `${BASE}/${PROJECT}/constraints/overview`);
  expect(overview.status).toBe(200);
  const position = overview.body.overview as Record<string, unknown>;
  expect(position.projectId).toBe(PROJECT);
  expect(position.projectTimezone).toBe("America/New_York");
  expect(position).toHaveProperty("averageOpenAgeBusinessDays");
  expect(position).toHaveProperty("syncHealth");
  expect(position).not.toHaveProperty("averageOpenAge");
  expect(position).not.toHaveProperty("synchronizationHealth");
  expect(position.totalOpen).toBe(2);

  const categories = await read(page, `${BASE}/${PROJECT}/constraint-categories?state=active`);
  expect(categories.status).toBe(200);
  const scheme = categories.body.categories as Record<string, unknown>[];
  expect(scheme).toHaveLength(1);
  expect(scheme[0].categoryId).toBe(CATEGORY);
  expect(scheme[0].prefixLocked).toBe(false);
});

test("a foreign Project or Constraint discloses nothing about its existence", async ({ page }) => {
  const foreignRegister = await read(page, `${BASE}/${FOREIGN_PROJECT}/constraints`);
  const foreignDetail = await read(page, `${BASE}/${PROJECT}/constraints/${FOREIGN_CONSTRAINT}`);
  const foreignHistory = await read(
    page,
    `${BASE}/${PROJECT}/constraints/${FOREIGN_CONSTRAINT}/history`,
  );
  // Three different truthful answers, and none of them says whether the record
  // exists. A Register the read plane cannot place on a Project calendar is
  // `unavailable` and carries **no** `constraints` key — an empty page here
  // would be the "unavailable rendered as zero Constraints" defect. A foreign
  // Constraint reads exactly as an absent one: `not_found`. A foreign
  // Constraint's receipts are the same empty page an untouched one returns.
  expect(foreignRegister.status).toBe(503);
  expect(foreignRegister.body.state).toBe("unavailable");
  expect(foreignRegister.body).not.toHaveProperty("constraints");
  expect(foreignDetail.status).toBe(404);
  expect((foreignDetail.body.error as Record<string, unknown>).code).toBe("not_found");
  expect(foreignHistory.status).toBe(200);
  expect(foreignHistory.body.history).toEqual([]);
  for (const answer of [foreignRegister, foreignDetail, foreignHistory]) {
    expect(answer.cacheControl).toBe("private, no-store");
    const serialized = JSON.stringify(answer.body);
    expect(serialized).not.toContain("Switchgear");
    expect(serialized).not.toContain("Crane");
    expect(serialized).not.toContain(FIRST);
  }
});

test("the Register refuses an undeclared or out-of-vocabulary query at the BFF", async ({
  page,
}) => {
  for (const query of ["direction=desc", "scope=everything", "sync=partial", "q=x&sort=code"]) {
    const answer = await read(page, `${BASE}/${PROJECT}/constraints?${query}`);
    expect(answer.status, query).toBe(400);
    expect((answer.body.error as Record<string, unknown>).code).toBe("invalid_request");
  }
});

test("the live shell renders Overview, server-filtered Register, and lazy Inspector reads", async ({ page }) => {
  const seen: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/project-controls/")) seen.push(request.url());
  });
  await page.goto(`/work/projects/${PROJECT}/constraints`);
  const workspace = page.locator("#main").getByTestId("constraints-live-workspace");
  await expect(workspace).toBeVisible();
  await expect(workspace.getByTestId("kpi-totalOpen")).toContainText("2");
  await expect(workspace.getByTestId(`overview-category-${CATEGORY}`)).toContainText("View in Register");

  await workspace.getByTestId(`overview-category-${CATEGORY}`).click();
  await expect(page).toHaveURL(new RegExp(`category=${CATEGORY}`));
  const firstItem = workspace.locator(
    `[data-testid="register-row-${FIRST}"], [data-testid="register-card-${FIRST}"]`,
  );
  await expect(firstItem).toBeVisible();
  await expect(workspace.getByTestId("register-new-constraint")).toHaveCount(0);

  await firstItem.getByRole("button", { name: "1.01" }).click();
  await expect(page.getByTestId("constraint-inspector")).toBeVisible();
  await expect(page.getByTestId("inspector-details")).toContainText(PROJECT);
  await expect(page.getByTestId("inspector-history")).toContainText("Version 2 → 2");
  await expect(page.getByTestId("inspector-evidence")).toBeVisible();
  expect(seen.some((url) => url.includes(`/constraints/${FIRST}`))).toBe(true);
});

test("search canonicalizes incompatible list controls and remains responsive", async ({ page }) => {
  await page.goto(`/work/projects/${PROJECT}/constraints?view=register&overdue=1&group=status`);
  const workspace = page.locator("#main").getByTestId("constraints-live-workspace");
  await expect(workspace.getByTestId("register-loading")).toHaveCount(0, { timeout: 30_000 });
  const search = workspace.getByTestId("register-search");
  await search.fill("Crane");
  await expect(page).toHaveURL(/q=Crane/);
  await expect(page).not.toHaveURL(/overdue=1|group=status/);
  await expect(
    workspace.locator(
      `[data-testid="register-row-${SECOND}"], [data-testid="register-card-${SECOND}"]`,
    ),
  ).toBeVisible();
  await expect(
    workspace.locator(
      `[data-testid="register-row-${FIRST}"], [data-testid="register-card-${FIRST}"]`,
    ),
  ).toHaveCount(0);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
