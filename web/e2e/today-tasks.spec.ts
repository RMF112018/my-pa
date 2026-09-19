/**
 * Today, answered in place (WP-TUX-07), against the real stack.
 *
 * Every assertion below is made in Chromium (or Firefox/WebKit, by project)
 * against a real Next.js server, a real Python gateway and a real PostgreSQL.
 * Nothing here stubs the product silently. Three tests intercept `/api/pulse`
 * on the *client* revalidation path only — never the server render — and each
 * states its reason where it does it: a refresh failure that is not a real
 * refused response proves nothing about behaviour under one (AC-013); a
 * genuinely quiet Today cannot be arranged in a database every spec in the run
 * shares (AC-012); and a backend-derived *non-Task* Pulse item is not
 * constructible from a browser at this head at all (AC-020, which says why).
 * Every other read and write below is the real chain.
 *
 * **How a Task reaches Today here.** WP-POSTUX-06 civil-day membership: an
 * open, accepted Task whose `due_at` or `scheduled_at` falls in the browser's
 * civil day. Overdue-only is Pulse attention, not canonical Today. So a Task
 * created through the canonical BFF with `dueAt` now is on Today on the next
 * read, which is what `seedTodayTask` does. The synthetic Pulse fixture is
 * deliberately *not* used: `app/(app)/today/page.tsx` short-circuits to
 * `PulseList` when `MYPA_DATA_PROVIDER=synthetic`, so a synthetic build never
 * renders `TodayPulseSurface` or `TodayTaskCard` at all, and the browser suite
 * runs a default build on purpose (see `playwright.config.ts`).
 *
 * **Why the network is watched rather than inferred.** Three of the criteria
 * here are claims about requests — that Reschedule writes `dueAt` and nothing
 * else, that rendering Today reads no Task detail, and that the write's
 * `expectedVersion` comes from a canonical read ordered before it. None of
 * those can be read off the DOM, and a re-read of the Task afterwards cannot
 * distinguish "was not sent" from "was sent and had no effect". So the requests
 * themselves are recorded, in order, and asserted.
 *
 * Tasks created here are synthetic, marker-named and live only in the
 * disposable database `e2e/stack.sh` creates for the run.
 */
import { expect, test, type Page, type Request } from "@playwright/test";
import { signIn } from "./fixtures";
import { browserWorkClock, type BrowserWorkClock } from "../src/lib/api/work-client";

/** The exact Empty copy the surface owns. See `TODAY_EMPTY_COPY`. */
const TODAY_EMPTY_COPY = "Nothing needs your attention right now.";

/** The concise attention reason `BackendPulseList` derives for `task_overdue`. */
const OVERDUE_REASON = "Overdue";

/**
 * Every `/api/pulse` read, whatever it carries in its query string.
 *
 * A glob is anchored to the end of the whole URL — Playwright's
 * `globToRegexPattern` appends `$` and `urlMatches` tests the full URL, query
 * string included — so `"**\/api\/pulse"` stopped matching the moment the
 * surface began sending `?workDate=&timezone=`, and every stub written with it
 * silently never fired. A regex is used rather than a wider glob because a
 * glob's single `*` does not cross `/`, and a timezone is exactly the kind of
 * value that carries one.
 */
const PULSE_ROUTE = /\/api\/pulse(\?|$)/;

type ApiAnswer<T> = { status: number; body: T };

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
        headers: payload ? { "content-type": "application/json" } : undefined,
        body: payload ? JSON.stringify(payload) : undefined,
      });
      return { status: response.status, body: (await response.json()) as T };
    },
    { target: path, method: options.method, payload: options.body },
  );
}

function marker(suffix: string): string {
  return `${test.info().project.name}-${Date.now()}-${suffix}`;
}

function key(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

interface TaskRow {
  readonly task_id: string;
  readonly version: number;
  readonly due_at: string | null;
  readonly scheduled_at: string | null;
  readonly deferred_until: string | null;
  readonly lifecycle_state: string;
  readonly title: string;
}

/**
 * Create an open Task whose due moment has already passed, so the derivation
 * surfaces it as `task_overdue` on the next Today read.
 *
 * Three days back rather than one: `_days()` in the derivation reports whole
 * days, and a boundary case would make the reason sentence depend on when the
 * suite happened to run.
 */
async function seedTodayTask(page: Page, title: string): Promise<string> {
  const dueAt = new Date().toISOString();
  const created = await api<{ task?: { task_id: string } }>(page, "/api/tasks", {
    method: "POST",
    body: { title, dueAt, idempotencyKey: key("e2e-today-seed") },
  });
  expect(created.status, `seeding "${title}" must be accepted`).toBeLessThan(300);
  const taskId = created.body.task?.task_id;
  expect(taskId, "the create answer must carry the canonical Task id").toBeTruthy();
  seededTaskIds.push(taskId as string);
  return taskId as string;
}

/* ------------------------------------------------------------------ *
 * Teardown — leave the shared database as this file found it
 * ------------------------------------------------------------------ */

/**
 * Every Task the current test has created. Reset per test, drained after it.
 *
 * **Why this file has to clean up after itself.** `e2e/stack.sh` creates one
 * disposable database for the whole run and every spec in the job shares it,
 * and what this file seeds is not inert: an *open, past-due* Task is precisely
 * what `pulse_derivation` puts on Today, and what `work_view=unscheduled`
 * sorts to the front (`asc(due_at).nullslast()` — a Task with no due moment
 * sorts last). Left behind, these rows accumulate across projects and change
 * what every later spec sees: Today grows a card per leftover, and the
 * Unscheduled list fills with past-due rows ahead of whatever the next spec
 * just created. That is not a hypothetical — it is what put three latent
 * defects in `journeys.spec.ts` and one in `work-acceptance.spec.ts` on screen
 * as a red `responsive` job.
 *
 * Specs stay independent of each other regardless: every test here seeds its
 * own marker-named Tasks and locates cards by that marker, so none of them
 * depends on another's teardown having run. This keeps the *neighbours* clean,
 * not this file's own tests.
 */
const seededTaskIds: string[] = [];

/**
 * Cancelled, not closed, and the distinction is not cosmetic.
 *
 * These Tasks were scaffolding; none of them was ever *done*. `cancelled` says
 * that, and it keeps the teardown's rows out of any Closed/Completed listing a
 * neighbouring spec might read or count. Both states are terminal, so either
 * would take the row off Today and out of Unscheduled — the choice is about
 * what the record then claims happened.
 */
const TEARDOWN_STATE = "cancelled";

/**
 * Dispose of every Task the test seeded, and fail loudly if disposal fails.
 *
 * Deterministic rather than best-effort: each row is read, and one that is not
 * already terminal is transitioned with the version that read returned. A
 * silent `catch` here would let the leak back in the moment the endpoint
 * changed shape, which is exactly the failure this teardown exists to prevent.
 * There is no polling and no wait: the transition is confirmed by its own
 * response, so this adds no timing dependence to the suite.
 */
async function disposeSeededTasks(page: Page): Promise<void> {
  const ids = [...seededTaskIds];
  seededTaskIds.length = 0;
  for (const taskId of ids) {
    const read = await api<{ task?: TaskRow }>(page, `/api/tasks/${taskId}`);
    // A Task the test itself disposed of through the product is already done.
    if (read.status !== 200 || !read.body.task) continue;
    const task = read.body.task;
    if (task.lifecycle_state === "completed" || task.lifecycle_state === "cancelled") continue;
    const disposed = await api<unknown>(page, `/api/tasks/${taskId}/transition`, {
      method: "POST",
      body: {
        toState: TEARDOWN_STATE,
        expectedVersion: task.version,
        idempotencyKey: key("e2e-today-teardown"),
      },
    });
    expect(
      disposed.status,
      `teardown must dispose of seeded Task ${taskId}: ${JSON.stringify(disposed.body)}`,
    ).toBeLessThan(300);
  }
}

async function readTask(page: Page, taskId: string): Promise<TaskRow> {
  const answer = await api<{ task: TaskRow }>(page, `/api/tasks/${taskId}`);
  expect(answer.status).toBe(200);
  return answer.body.task;
}

/** The card for one Task, located by the title the Pulse projection carried. */
function cardFor(page: Page, title: string) {
  return page.getByTestId("today-task-card").filter({ hasText: title });
}

/**
 * The civil day and zone the Today surface will itself ask `/api/pulse` for.
 *
 * `browserWorkClock` is the product's one clock — the surface derives its query
 * from exactly this function — so the probe below asks about the same civil day
 * the derivation is being asked about. Only the zone is read out of the page;
 * the date is derived by the shared helper rather than computed a second time
 * here, because two derivations of "today" are two things that can disagree.
 *
 * A literal date cannot stand in for it: a Task seeded with `dueAt` of now is
 * correctly not a member of some other civil day, so a fixed date turns a right
 * answer from the backend into a failing assertion.
 */
async function todayClock(page: Page): Promise<BrowserWorkClock> {
  const timezone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  return browserWorkClock(new Date(), timezone);
}

async function openToday(page: Page): Promise<void> {
  await page.goto("/today");
  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();
}

/* ------------------------------------------------------------------ *
 * Network observation
 * ------------------------------------------------------------------ */

interface Observed {
  readonly seq: number;
  readonly method: string;
  readonly pathname: string;
  readonly taskId: string;
  readonly body: unknown;
}

/** `/api/tasks/<id>` exactly — not `/history`, not `/comments`, not the list. */
const TASK_DETAIL = /^\/api\/tasks\/([^/]+)$/;

/**
 * Record Task-detail reads and writes in the order the browser issued them.
 *
 * Ordering is the point: AC-005 is not only "one read happened", it is "the
 * read happened *before* the write whose `expectedVersion` it supplied". A set
 * of requests cannot say that, so each is stamped with a monotonic sequence.
 */
function observeTaskRequests(page: Page): { readonly events: Observed[] } {
  const events: Observed[] = [];
  let seq = 0;
  page.on("request", (request: Request) => {
    let pathname: string;
    try {
      pathname = new URL(request.url()).pathname;
    } catch {
      return;
    }
    const match = TASK_DETAIL.exec(pathname);
    if (!match) return;
    let body: unknown;
    try {
      const raw = request.postData();
      body = raw ? (JSON.parse(raw) as unknown) : undefined;
    } catch {
      body = request.postData();
    }
    seq += 1;
    events.push({ seq, method: request.method(), pathname, taskId: match[1] as string, body });
  });
  return { events };
}

function describe(events: readonly Observed[]): string {
  return events.map((event) => `#${event.seq} ${event.method} ${event.pathname}`).join("\n") || "(none)";
}

/**
 * Capture every message that appears in the shell mutation feedback region.
 *
 * Success feedback expires after five seconds, so polling for it races the
 * TTL on a slow machine. An observer installed before the activation records
 * what was announced whether or not it is still on screen when asserted.
 */
async function recordAnnouncements(page: Page): Promise<void> {
  await page.evaluate(() => {
    const store: string[] = [];
    (window as unknown as { __mypaAnnouncements: string[] }).__mypaAnnouncements = store;
    const note = (root: ParentNode) => {
      for (const live of root.querySelectorAll('[data-testid^="mutation-feedback-live-"]')) {
        const text = (live.textContent ?? "").trim();
        if (text && !store.includes(text)) store.push(text);
      }
    };
    note(document);
    new MutationObserver(() => note(document)).observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  });
}

async function announcements(page: Page): Promise<string[]> {
  return page.evaluate(
    () => (window as unknown as { __mypaAnnouncements?: string[] }).__mypaAnnouncements ?? [],
  );
}

test.beforeEach(async ({ page }) => {
  seededTaskIds.length = 0;
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

/*
  Runs after a failed test as well as a passing one, which is the point: a test
  that fails half way through has still seeded rows, and those are exactly the
  runs that used to leave the most behind.
*/
test.afterEach(async ({ page }) => {
  await disposeSeededTasks(page);
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-002 / AC-003 — the two operations, reachable and cheap
 * ------------------------------------------------------------------ */

/**
 * Also TASK-AC-024, TASK-AC-025 and TASK-AC-044: the Today card states what the Task is and
 * why it is here, offers exactly the two actions, and Close costs two activations and asks
 * for no authored text.
 */
test("TUX07-AC-002/003: Reschedule and Close are on the card, and Close costs two activations with no note", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const title = `E2E today card ${marker("ac002")}`;
  const taskId = await seedTodayTask(page, title);
  await openToday(page);

  const card = cardFor(page, title);
  await expect(card).toBeVisible();

  // AC-002: title and the concise reason, with no derivation bookkeeping.
  await expect(card.getByTestId("today-task-card-title")).toHaveText(title);
  await expect(card.getByTestId("today-task-card-reason")).toHaveText(OVERDUE_REASON);
  await expect(card.getByTestId("pulse-rank")).toHaveCount(0);
  await expect(card.getByTestId("pulse-basis")).toHaveCount(0);
  await expect(card).not.toContainText(/Rank \d/);
  // No identifiers: not the Task id it was handed, not a pulse id.
  await expect(card).not.toContainText(taskId);
  await expect(card).not.toContainText(/\bpls_[0-9a-f]/);
  // No Status control: the card has read no Task and may not assert a lifecycle.
  await expect(card.getByRole("group", { name: `Change status for ${title}` })).toHaveCount(0);
  // No Due *value*: the trigger is an action, not an assertion about the record.
  await expect(card).not.toContainText(/No due date/i);

  // AC-002: both operations are reachable directly, with no disclosure in front.
  const reschedule = card.getByRole("button", { name: `Reschedule ${title}` });
  const close = card.getByTestId("task-close-trigger");
  await expect(reschedule).toBeVisible();
  await expect(close).toBeVisible();
  await expect(close).toHaveText("Close Task");

  // AC-003, activation one.
  await close.click();
  const confirmation = card.getByTestId("task-close-confirmation");
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toHaveAttribute("role", "alertdialog");

  // AC-003: the confirmation opens on the non-destructive choice.
  const keepOpen = card.getByTestId("task-close-keep-open");
  await expect(keepOpen).toBeFocused();

  // AC-003: no note, and no lifecycle selector, anywhere in the confirmation.
  await expect(confirmation.getByRole("textbox")).toHaveCount(0);
  await expect(confirmation.locator("textarea")).toHaveCount(0);
  await expect(confirmation.locator("input")).toHaveCount(0);
  await expect(confirmation.getByRole("combobox")).toHaveCount(0);
  await expect(confirmation.locator("select")).toHaveCount(0);

  await recordAnnouncements(page);

  // AC-003, activation two. Nothing between them but the confirmation itself.
  await card.getByTestId("task-close-confirm").click();

  // The Task is closed in the record, which is the only proof that two
  // activations were the whole cost.
  await expect
    .poll(async () => (await readTask(page, taskId)).lifecycle_state, {
      timeout: 30_000,
      message: "two activations must close the Task",
    })
    .toBe("completed");
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-004 — Reschedule moves Due, and moves nothing else
 * ------------------------------------------------------------------ */

test("TUX07-AC-004: a Today Reschedule sends only dueAt and leaves scheduled_at and deferred_until byte-identical", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const title = `E2E today reschedule ${marker("ac004")}`;
  const taskId = await seedTodayTask(page, title);
  const before = await readTask(page, taskId);

  const { events } = observeTaskRequests(page);
  await openToday(page);
  const card = cardFor(page, title);
  await expect(card).toBeVisible();

  await recordAnnouncements(page);
  await card.getByRole("button", { name: `Reschedule ${title}` }).click();
  const choices = card.getByRole("group", { name: "Due choices" });
  await expect(choices).toBeVisible();
  await choices.getByRole("button", { name: "Tomorrow" }).click();

  await expect
    .poll(() => events.filter((event) => event.method === "PATCH").length, {
      timeout: 30_000,
      message: "the Reschedule must reach the record",
    })
    .toBe(1);

  const writes = events.filter((event) => event.method === "PATCH");
  const write = writes[0] as Observed;
  expect(write.taskId, "the write must address the operated Task").toBe(taskId);

  // The body is exactly three keys. Asserting the sorted key list rather than
  // absence-by-name means a future field cannot be added here unnoticed.
  const body = write.body as Record<string, unknown>;
  expect(Object.keys(body).sort()).toEqual(["dueAt", "expectedVersion", "idempotencyKey"]);
  expect(body).not.toHaveProperty("scheduledAt");
  expect(body).not.toHaveProperty("deferredUntil");
  expect(body).not.toHaveProperty("clearFields");
  expect(body).not.toHaveProperty("toState");
  expect(body).not.toHaveProperty("lifecycleState");

  // The record, read back. Due moved; the two scheduling fields did not.
  await expect
    .poll(async () => (await readTask(page, taskId)).due_at, {
      timeout: 30_000,
      message: "Due must actually move",
    })
    .not.toBe(before.due_at);
  const after = await readTask(page, taskId);
  expect(after.scheduled_at, "scheduled_at must be untouched").toBe(before.scheduled_at);
  expect(after.deferred_until, "deferred_until must be untouched").toBe(before.deferred_until);
  expect(after.lifecycle_state, "Reschedule is not a lifecycle change").toBe(before.lifecycle_state);
  expect(after.title).toBe(before.title);

  // AC-017: the outcome was announced through the shared region.
  expect(await announcements(page)).toContainEqual(expect.stringMatching(/^Due date moved to /));
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-005 — no Task-detail fan-out
 * ------------------------------------------------------------------ */

test("TUX07-AC-005: rendering Today reads no Task detail, and the first operation reads exactly one", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const operatedTitle = `E2E today operated ${marker("ac005a")}`;
  const bystanderTitle = `E2E today bystander ${marker("ac005b")}`;
  const operatedId = await seedTodayTask(page, operatedTitle);
  const bystanderId = await seedTodayTask(page, bystanderTitle);

  const { events } = observeTaskRequests(page);
  await openToday(page);
  await expect(cardFor(page, operatedTitle)).toBeVisible();
  await expect(cardFor(page, bystanderTitle)).toBeVisible();

  /*
    Sit through more than one foreground revalidation cycle before concluding
    that rendering fans out to nothing. The policy is a 5s cadence, so a single
    frame after first paint would not have caught a card that re-reads its Task
    on every refresh — which is the fan-out shape that actually costs.
  */
  await page.waitForTimeout(12_000);
  expect(
    events,
    `rendering Today must read no Task detail:\n${describe(events)}`,
  ).toEqual([]);

  // First operation activation on one card only.
  const card = cardFor(page, operatedTitle);
  await card.getByRole("button", { name: `Reschedule ${operatedTitle}` }).click();
  await card.getByRole("group", { name: "Due choices" }).getByRole("button", { name: "Tomorrow" }).click();

  await expect
    .poll(() => events.filter((event) => event.method === "PATCH").length, {
      timeout: 30_000,
      message: "the operation must reach the record",
    })
    .toBe(1);

  const write = events.find((event) => event.method === "PATCH") as Observed;
  const readsBeforeWrite = events.filter(
    (event) => event.method === "GET" && event.seq < write.seq,
  );

  // Exactly one canonical read, for the operated Task, ordered before the write.
  expect(
    readsBeforeWrite.length,
    `exactly one canonical read before the write:\n${describe(events)}`,
  ).toBe(1);
  expect((readsBeforeWrite[0] as Observed).taskId).toBe(operatedId);
  expect((readsBeforeWrite[0] as Observed).seq).toBeLessThan(write.seq);

  // The bystander card was never read, before or after.
  expect(
    events.filter((event) => event.taskId === bystanderId),
    `the bystander Task must never be read or written:\n${describe(events)}`,
  ).toEqual([]);

  // The version written is the version that read returned.
  const canonical = await api<{ task: TaskRow }>(page, `/api/tasks/${operatedId}`);
  expect(canonical.status).toBe(200);
  const sent = (write.body as { expectedVersion?: unknown }).expectedVersion;
  expect(typeof sent, "expectedVersion must be a number, not a guess").toBe("number");
  // The write moved the Task on by one, so the version it named is the one the
  // canonical read before it held.
  expect(canonical.body.task.version).toBe((sent as number) + 1);
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-012 / AC-013 — Empty is a claim, and a failed refresh is not one
 * ------------------------------------------------------------------ */

test("TUX07-AC-012: an authoritative Empty renders exactly the Empty copy", async ({ page }) => {
  test.setTimeout(180_000);
  const title = `E2E today emptied ${marker("ac012")}`;
  await seedTodayTask(page, title);
  await openToday(page);
  await expect(cardFor(page, title)).toBeVisible();

  /*
    The Empty here is authoritative and is intercepted for determinism, not for
    convenience: the disposable database is shared by every spec in the run, so
    a genuinely quiet Today cannot be arranged without depending on what other
    specs left behind. What is served is exactly what the backend serves on a
    quiet day — the backend shape, complete coverage, no limitation, zero items
    — and the surface's own classification is what is under test.
  */
  await page.route(PULSE_ROUTE, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        shape: "backend",
        todayRows: [],
        completeness: "full",
        disclosure: { scope: "pulse", coverage: "complete", limitations: [], truncated: false },
      }),
    });
  });

  const empty = page.getByTestId("today-empty");
  await expect(empty).toBeVisible({ timeout: 30_000 });
  await expect(cardFor(page, title)).toHaveCount(0);
  await expect(empty).toHaveAttribute("data-state", "empty");
  await expect(empty).toHaveAttribute("role", "status");
  await expect(empty.getByRole("heading")).toHaveText(TODAY_EMPTY_COPY);
});

test("TUX07-AC-013: a failed refresh keeps the rows and marks the surface stale, and never becomes Empty", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const title = `E2E today retained ${marker("ac013")}`;
  await seedTodayTask(page, title);
  await openToday(page);
  const card = cardFor(page, title);
  await expect(card).toBeVisible();

  // A real refused response on the client read path. The first render came from
  // the server, so what is being tested is what a *refresh* failure does to an
  // answer that already stands.
  await page.route(PULSE_ROUTE, async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { errorClass: "unavailable", code: "e2e_forced_refresh_failure" } }),
    });
  });

  await expect(page.getByTestId("today-stale")).toBeVisible({ timeout: 30_000 });

  // The rows stand, and no emptiness is claimed.
  await expect(card).toBeVisible();
  await expect(card.getByTestId("today-task-card-title")).toHaveText(title);
  await expect(page.getByTestId("today-empty")).toHaveCount(0);
  await expect(page.getByTestId("today-degraded-empty")).toHaveCount(0);
  await expect(page.getByTestId("pulse-empty")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(TODAY_EMPTY_COPY);

  // Give the backoff two more cadences and check it has still not flipped.
  await page.waitForTimeout(12_000);
  await expect(card).toBeVisible();
  await expect(page.getByTestId("today-empty")).toHaveCount(0);
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-014 / AC-017 / AC-018 — reconciliation, announcement, focus
 * ------------------------------------------------------------------ */

/** Where focus is, described well enough to name the element in a failure. */
async function focusDescription(page: Page): Promise<string> {
  return page.evaluate(() => {
    const active = document.activeElement;
    if (!active || active === document.body) return "BODY";
    const label =
      active.getAttribute("data-testid") ??
      active.getAttribute("aria-label") ??
      (active.textContent ?? "").trim().slice(0, 40);
    return `${active.tagName}:${label}`;
  });
}

/**
 * Close the named card and wait for Today to reconcile it away.
 *
 * Shared by the reconciliation test and the focus test so both observe exactly
 * the same sequence; the focus answer depends on what unmounts and when, so
 * two different routes to "the card is gone" would not be comparable.
 */
async function closeCardAndReconcile(page: Page, title: string): Promise<void> {
  const card = cardFor(page, title);
  await card.getByTestId("task-close-trigger").click();
  await expect(card.getByTestId("task-close-confirmation")).toBeVisible();
  await card.getByTestId("task-close-confirm").click();
  await expect(cardFor(page, title)).toHaveCount(0, { timeout: 60_000 });
}

/**
 * Also TASK-AC-034: a Task that disappears from an open surface is announced rather than
 * silently removed.
 */
test("TUX07-AC-014/017: an open Today reconciles a completed Task away and announces it", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const closedTitle = `E2E today reconciled ${marker("ac014a")}`;
  const keptTitle = `E2E today kept ${marker("ac014b")}`;
  await seedTodayTask(page, closedTitle);
  await seedTodayTask(page, keptTitle);

  await openToday(page);
  const kept = cardFor(page, keptTitle);
  await expect(cardFor(page, closedTitle)).toBeVisible();
  await expect(kept).toBeVisible();

  // A sentinel that a document reload would destroy. AC-014 is specifically
  // that the *already-open* page reconciles, so "it reloaded and looked right"
  // would not be evidence for it.
  await page.evaluate(() => {
    (window as unknown as { __mypaNoReload: boolean }).__mypaNoReload = true;
  });
  await recordAnnouncements(page);

  // AC-014: the card leaves Today on the authoritative re-read, with no reload.
  await closeCardAndReconcile(page, closedTitle);
  await expect(kept, "the untouched card must stay").toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as { __mypaNoReload?: boolean }).__mypaNoReload === true,
    ),
    "Today must reconcile without a hard refresh",
  ).toBe(true);

  // AC-017: announced through the shared mutation feedback region, in its words.
  expect(await announcements(page)).toContain(`${closedTitle} closed`);
});

/**
 * TUX07-AC-018 — an ordinary test, and what it took to make it one.
 *
 * The assertion is unchanged from when it carried a `test.fail()` declaration.
 * That declaration is gone because this run was observed: Playwright reported
 * "Expected to fail, but passed" against the fix, and then passed outright
 * against the same assertion with the declaration removed.
 *
 * **What was wrong, in two parts.** Confirming Close disables the control the
 * user is on, so the browser drops focus to `document.body`.
 * `use-task-row-operations.ts` returns it on unlock through `liveReturn(held)`,
 * which tries the held control (gone — the Task became terminal and
 * `TaskTerminalActions` withheld itself), then the first live control in the
 * held `role="group"` (gone with it), then the row's own `a[href]`. A Work-list
 * row has such an anchor; `TodayTaskCard` has none, so the chain resolved to
 * `null` and the user was left at the top of the document. `liveReturn` gained
 * a last step — the row root itself, when the surface has made it focusable by
 * script — and `TodayTaskCard` carries `tabIndex={-1}` for it to land on.
 *
 * That was necessary and not sufficient, and a measured focus timeline said so:
 * the root fallback fired correctly, and about a frame later Today's
 * authoritative Pulse re-read removed that very card, so focus landed and
 * evaporated back to the body. `useTaskRowOperations` cannot repair that — by
 * the time reconciliation unmounts the row its own `rowRef` is detached. So
 * `TodayPulseSurface` now owns the second half, the way `workbench.tsx` has
 * owned it for the Work list since WP-TUX-05: a bubbling `focusin` listener
 * records which card holds focus, and an effect keyed on the answer places focus
 * on the surviving neighbour — or a stable heading — but only when focus has
 * genuinely fallen to the body and the recorded element has actually left the
 * document. Component guards live in `today-pulse-surface.test.tsx`.
 */
/** Also TASK-AC-034: the focus half of the same criterion — where focus lands once the card
 * the user was operating has left the surface. */
test("TUX07-AC-018: focus lands deterministically after the card leaves Today", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const closedTitle = `E2E today focus ${marker("ac018a")}`;
  const keptTitle = `E2E today focus kept ${marker("ac018b")}`;
  await seedTodayTask(page, closedTitle);
  await seedTodayTask(page, keptTitle);

  await openToday(page);
  await expect(cardFor(page, closedTitle)).toBeVisible();
  await expect(cardFor(page, keptTitle)).toBeVisible();

  // Operate from the keyboard: focus return only matters for a user who had it.
  await cardFor(page, closedTitle).getByTestId("task-close-trigger").focus();
  await expect(cardFor(page, closedTitle).getByTestId("task-close-trigger")).toBeFocused();
  await closeCardAndReconcile(page, closedTitle);

  // Poll rather than sample once: a focus return that arrives a frame or two
  // after the list settles is still a deterministic landing, and calling that a
  // defect would be a false report.
  await expect
    .poll(() => focusDescription(page), {
      timeout: 10_000,
      message: "focus must not be stranded on document.body after the card leaves",
    })
    .not.toBe("BODY");
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-019 — the narrow viewports, with the chooser open
 * ------------------------------------------------------------------ */

const NARROW_WIDTHS = [320, 360, 375, 390, 430] as const;

/** Also TASK-AC-045: 320-430 CSS px with no horizontal scroll and both operations still
 * operable, measured here on Today. */
test("TUX07-AC-019: the Today Task card reflows at 320-430 with both operations reachable", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const title = `E2E today reflow ${marker("ac019")}`;
  await seedTodayTask(page, title);

  const overflow = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );

  for (const width of NARROW_WIDTHS) {
    await page.setViewportSize({ width, height: 844 });
    await openToday(page);
    const card = cardFor(page, title);
    await expect(card, `the card must render at ${width}`).toBeVisible();

    // Title and reason are visible without expanding anything.
    await expect(card.getByTestId("today-task-card-title"), `title at ${width}`).toBeVisible();
    await expect(card.getByTestId("today-task-card-reason"), `reason at ${width}`).toBeVisible();

    const reschedule = card.getByRole("button", { name: `Reschedule ${title}` });
    const close = card.getByTestId("task-close-trigger");
    await expect(reschedule, `Reschedule at ${width}`).toBeVisible();
    await expect(close, `Close at ${width}`).toBeVisible();

    expect(await overflow(), `Today overflows horizontally at ${width}`).toBeLessThanOrEqual(1);

    // Primary controls are at least a 44px touch target.
    for (const [name, control] of [
      ["Reschedule", reschedule],
      ["Close Task", close],
    ] as const) {
      const box = await control.boundingBox();
      expect(box, `${name} must have a box at ${width}`).not.toBeNull();
      expect(Math.round(box!.width), `${name} width at ${width}`).toBeGreaterThanOrEqual(44);
      expect(Math.round(box!.height), `${name} height at ${width}`).toBeGreaterThanOrEqual(44);
    }

    // Measured again with the Due chooser open: a popover is the thing most
    // likely to push a narrow page sideways, and it is part of Reschedule.
    await reschedule.click();
    const choices = card.getByRole("group", { name: "Due choices" });
    await expect(choices, `the Due chooser must open at ${width}`).toBeVisible();
    await expect(choices.getByRole("button", { name: "Tomorrow" })).toBeVisible();
    // Close is still reachable with the chooser open.
    await expect(close, `Close must stay reachable at ${width}`).toBeVisible();
    expect(
      await overflow(),
      `Today overflows horizontally at ${width} with the Due chooser open`,
    ).toBeLessThanOrEqual(1);
    await page.keyboard.press("Escape");
    await expect(choices).toHaveCount(0);
  }
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-020 — a non-Task item gains nothing
 * ------------------------------------------------------------------ */

test("TUX07-AC-020: a non-Task Pulse item renders with no Reschedule and no Close", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const title = `E2E today mixed task ${marker("ac020")}`;
  await seedTodayTask(page, title);

  /*
    The Task half of this list is entirely real: a Task is seeded through the
    canonical BFF, the derivation is asked for it, and the item the gateway
    produced is what gets rendered. The Commitment beside it is a constructed
    `BackendPulseItem`, and the reason is a fact about this head rather than a
    shortcut.

    `application/commitments.py` creates a Commitment `PROPOSED` unless the
    caller supplies an `accepted_by_review_decision_id`, and `/api/commitments`
    is the only Commitment create the browser tier has — it exposes no
    direct-acceptance path, and `derive_pulse` filters on
    `evidence_state = 'accepted'`. A Commitment created through the product
    therefore *cannot* reach Today at this head. (Tasks can, because
    `TaskOriginKind.DIRECT_PRINCIPAL` accepts on create, which is what makes
    the Task half real here.) Situations and Decisions have no browser-tier
    create either. So a genuinely backend-derived non-Task Pulse item is not
    constructible from a browser at this head, and the remaining honest option
    is to serve the shape the route's own contract defines and assert what the
    product renders from it.

    What is under test is exactly that rendering: `BackendPulseList` branches on
    the row's `kind`, and the canonical Task row and the derived non-Task row go
    through one render pass in one list, so the comparison is like-for-like
    rather than two separate pages.
  */
  const clock = await todayClock(page);
  const served = await api<{
    todayRows?: { kind: string; title?: string }[];
    disclosure: unknown;
  }>(
    page,
    `/api/pulse?workDate=${clock.workDate}&timezone=${encodeURIComponent(clock.timezone)}`,
  );
  expect(served.status).toBe(200);
  const todayRows = served.body.todayRows ?? [];
  const taskRow = todayRows.find((row) => row.kind === "task" && row.title === title);
  expect(
    taskRow,
    "the seeded Task must be in the canonical Today set the real backend answered",
  ).toBeTruthy();

  const commitmentRef = "cmt_e2e00000000000000000000000ac020";
  const commitmentItem = {
    pulseId: "pls_e2e00000000000000000000000ac020",
    itemType: "commitment",
    itemRef: commitmentRef,
    reasonCode: "commitment_overdue",
    reason: "The agreed moment passed 3 day(s) ago and the commitment is still open.",
    basisRefs: [commitmentRef, "cap_e2e00000000000000000000000ac0"],
    consequence:
      "A counterparty is still entitled to expect this, and nothing here has told them otherwise.",
    nextStep: "Close it with the evidence that discharged it, or re-agree the moment.",
    attentionRank: 8,
    generatedAt: new Date().toISOString(),
  };

  await page.route(PULSE_ROUTE, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        shape: "backend",
        // The route's own order: canonical Task rows, then the derived rows.
        todayRows: [taskRow, { kind: "attention", item: commitmentItem }],
        completeness: "full",
        disclosure: { scope: "pulse", coverage: "complete", limitations: [], truncated: false },
      }),
    });
  });

  await openToday(page);

  // The Task half still renders as the card, which is what makes the comparison
  // below mean anything: the same list, the same render, two presentations.
  const card = cardFor(page, title);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByTestId("task-close-trigger")).toBeVisible();
  await expect(card.getByRole("button", { name: `Reschedule ${title}` })).toBeVisible();

  const item = page.getByTestId("pulse-item").filter({
    has: page.locator(`[data-testid="pulse-next-step-link"][href*="${commitmentRef}"]`),
  });
  await expect(item).toBeVisible({ timeout: 30_000 });

  // It keeps the evidentiary presentation and the next-step routing it had.
  await expect(item.getByTestId("pulse-reason")).toContainText(commitmentItem.reason);
  await expect(item.getByTestId("pulse-next-step")).toHaveText(commitmentItem.nextStep);
  await expect(item.getByTestId("pulse-basis")).toHaveCount(1);
  await expect(
    page.getByTestId("today-task-card").filter({ hasText: commitmentItem.reason }),
    "a Commitment must never be rendered as a Today Task card",
  ).toHaveCount(0);

  // And it gains neither Task operation.
  await expect(item.getByTestId("task-close-trigger")).toHaveCount(0);
  await expect(item.getByTestId("task-due-control")).toHaveCount(0);
  await expect(item.getByRole("button", { name: /^Reschedule/ })).toHaveCount(0);
  await expect(item.getByRole("button", { name: "Close Task" })).toHaveCount(0);
  await expect(item.getByRole("button", { name: /^More actions for/ })).toHaveCount(0);
});
