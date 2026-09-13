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
 * **How a Task reaches Today here.** `domain/situation/pulse_derivation.py`
 * puts an *open, accepted* Task on the Pulse when its due moment has passed
 * (`task_overdue`) or is within the due-soon window (`task_due_soon`), and the
 * derivation runs at read time — there is no pulse table to seed and no
 * acceptance step to drive. So a Task created through the canonical BFF with a
 * due moment in the past is on Today on the very next read, which is what
 * `seedOverdueTask` does. The synthetic Pulse fixture is deliberately *not*
 * used: `app/(app)/today/page.tsx` short-circuits to `PulseList` when
 * `MYPA_DATA_PROVIDER=synthetic`, so a synthetic build never renders
 * `TodayPulseSurface` or `TodayTaskCard` at all, and the browser suite runs a
 * default build on purpose (see `playwright.config.ts`).
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

/** The exact Empty copy the surface owns. See `TODAY_EMPTY_COPY`. */
const TODAY_EMPTY_COPY = "Nothing needs your attention right now.";

/** The concise attention reason `BackendPulseList` derives for `task_overdue`. */
const OVERDUE_REASON = "Overdue";

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
async function seedOverdueTask(page: Page, title: string): Promise<string> {
  const dueAt = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
  const created = await api<{ task?: { task_id: string } }>(page, "/api/tasks", {
    method: "POST",
    body: { title, dueAt, idempotencyKey: key("e2e-today-seed") },
  });
  expect(created.status, `seeding "${title}" must be accepted`).toBeLessThan(300);
  const taskId = created.body.task?.task_id;
  expect(taskId, "the create answer must carry the canonical Task id").toBeTruthy();
  return taskId as string;
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
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
});

/* ------------------------------------------------------------------ *
 * TUX07-AC-002 / AC-003 — the two operations, reachable and cheap
 * ------------------------------------------------------------------ */

test("TUX07-AC-002/003: Reschedule and Close are on the card, and Close costs two activations with no note", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const title = `E2E today card ${marker("ac002")}`;
  const taskId = await seedOverdueTask(page, title);
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
  const taskId = await seedOverdueTask(page, title);
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
  const operatedId = await seedOverdueTask(page, operatedTitle);
  const bystanderId = await seedOverdueTask(page, bystanderTitle);

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
  await seedOverdueTask(page, title);
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
  await page.route("**/api/pulse", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        shape: "backend",
        items: [],
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
  await seedOverdueTask(page, title);
  await openToday(page);
  const card = cardFor(page, title);
  await expect(card).toBeVisible();

  // A real refused response on the client read path. The first render came from
  // the server, so what is being tested is what a *refresh* failure does to an
  // answer that already stands.
  await page.route("**/api/pulse", async (route) => {
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

test("TUX07-AC-014/017: an open Today reconciles a completed Task away and announces it", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const closedTitle = `E2E today reconciled ${marker("ac014a")}`;
  const keptTitle = `E2E today kept ${marker("ac014b")}`;
  await seedOverdueTask(page, closedTitle);
  await seedOverdueTask(page, keptTitle);

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
 * TUX07-AC-018, and a product defect this package did not close.
 *
 * **`test.fail()` is a statement, not a suppression.** This assertion is the
 * criterion as written and it is not weakened: Playwright runs the test, and
 * the run is red the moment it *starts passing*, which is exactly what closing
 * the defect would do. Nothing about AC-018 is claimed as met.
 *
 * **What was observed.** Confirming Close disables the control the user is on,
 * so the browser drops focus to `document.body`. `use-task-row-operations.ts`
 * returns it on unlock through `liveReturn(held)`, which tries, in order: the
 * held control (gone — the Task became terminal and `TaskTerminalActions`
 * withheld itself), the first live control in the held `role="group"` (gone
 * with it), and finally `rowRef.current?.querySelector('a[href]')`. A Work-list
 * row has such an anchor — its own title link — and that is the fallback this
 * engine was written against. `TodayTaskCard` has no anchor at all: its title
 * is an `<h3>` and the card does not route anywhere. So the last resort
 * resolves to `null`, nothing is focused, and the user who closed a Task with
 * the keyboard is left at the top of the document.
 *
 * **The fix is now in, and this declaration is the one thing left to remove.**
 * `liveReturn` gained a last step — the row root itself, when the surface has
 * made it focusable by script — and `TodayTaskCard` carries `tabIndex={-1}` on
 * its root so the engine has somewhere deterministic to land. Both are covered
 * by unit guards (`use-task-row-operations.test.tsx`,
 * `today-task-card.test.tsx`), including one proving a row that *has* an anchor
 * still returns to that anchor rather than to the root.
 *
 * The declaration stays only because this run was never observed: the browser
 * tiers could not be stood up here without colliding with a Playwright run
 * already holding the servers this suite needs. It is left deliberately
 * unweakened, so CI is the thing that answers: the moment this passes,
 * Playwright reports "expected to fail, but passed" and the line below is
 * deleted. No pass is claimed that was not seen.
 */
test("TUX07-AC-018: focus lands deterministically after the card leaves Today", async ({
  page,
}) => {
  test.fail(
    true,
    // The fix for this is in the tree (root fallback + a focusable card root);
    // this stays only until a browser run confirms it, and then it goes.
    "Known product defect: liveReturn's last resort is the row's a[href], and a Today Task card has none, so focus is left on document.body. Fix landed in web/src; awaiting an observed browser run.",
  );
  test.setTimeout(180_000);
  const closedTitle = `E2E today focus ${marker("ac018a")}`;
  const keptTitle = `E2E today focus kept ${marker("ac018b")}`;
  await seedOverdueTask(page, closedTitle);
  await seedOverdueTask(page, keptTitle);

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

test("TUX07-AC-019: the Today Task card reflows at 320-430 with both operations reachable", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const title = `E2E today reflow ${marker("ac019")}`;
  await seedOverdueTask(page, title);

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
  await seedOverdueTask(page, title);

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
    `itemType`, and the two items go through one render pass in one list, so the
    comparison is like-for-like rather than two separate pages.
  */
  const served = await api<{ items: unknown[]; disclosure: unknown }>(page, "/api/pulse");
  expect(served.status).toBe(200);
  const taskItem = (served.body.items as { itemType: string; subjectTitle?: string }[]).find(
    (item) => item.itemType === "task" && item.subjectTitle === title,
  );
  expect(taskItem, "the seeded Task must be derived onto the Pulse by the real backend").toBeTruthy();

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

  await page.route("**/api/pulse", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        shape: "backend",
        items: [commitmentItem, taskItem],
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
