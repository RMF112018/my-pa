/**
 * What every browser spec shares: signing in, and the vocabulary of a truthful
 * state.
 *
 * **Sign-in offers exactly one principal, and that is a decision rather than an
 * omission.** Campaign decision `D-15` pins this tier to one Principal whenever
 * the gateway runs in `local_operator` mode, because the gateway serves one
 * fixed process principal for the life of its process — two sign-in buttons
 * there would be two costumes on one person, which is precisely the defect a
 * reviewer demonstrated in WP-06 by reading one synthetic identity's capture
 * back as another. So this helper signs in as the one admissible principal and
 * no spec attempts a second: a two-identity browser test is **not constructible
 * at this head**, and constructing one would mean widening the pin that prevents
 * the disclosure.
 */
import { expect, type Page } from "@playwright/test";

/** The one principal `local_operator` mode admits. See `lib/auth/synthetic.ts`. */
export const ADMISSIBLE_PRINCIPAL = "synthetic-a";

/** Obviously-synthetic capture text. Nothing here is a real note. */
export function syntheticNote(marker: string): string {
  return `E2E synthetic note ${marker} — pour the north slab and confirm the mix design.`;
}

/**
 * Hide Next.js `next dev` chrome so it cannot intercept clicks.
 *
 * This suite runs against `next dev` because a production build refuses the
 * synthetic provider (see `playwright.config.ts`). `PasskeySignIn` currently
 * hydrates a different first paint than SSR, and `next dev` puts a
 * `<nextjs-portal>` error overlay on top of the real form. That overlay is
 * framework development chrome, not product UI — `visual.spec.ts` already
 * hides it the same way. Hiding it here does not close the hydration defect
 * and does not claim Safari/PWA (AC072-074).
 */
export async function hideNextjsDevOverlay(page: Page): Promise<void> {
  await page.addStyleTag({
    content: "nextjs-portal { display: none !important; pointer-events: none !important; }",
  });
}

/**
 * Sign in through the real screen, and land where the app sends you.
 *
 * The last assertion is not decoration. The URL becoming `/today` only says the
 * client router navigated; the shell being on screen says the *server* resolved
 * the session and rendered the signed-in tree. Without it, a session that was
 * accepted and then refused on the very next request fails somewhere later and
 * unrecognisably — which is exactly how the service-worker RSC caching defect
 * first presented, as an unrelated locator timing out three tests further on.
 */
export async function signIn(page: Page, origin?: string): Promise<void> {
  await page.goto(`${origin ?? ""}/sign-in`);
  await hideNextjsDevOverlay(page);
  const button = page.getByTestId(`sign-in-${ADMISSIBLE_PRINCIPAL}`);
  await expect(button).toBeVisible();
  await button.click();
  await page.waitForURL("**/today");
  await expect(visibleCaptureButton(page)).toBeVisible();
}

/** Desktop rail and mobile tab both expose Capture; only one is in the viewport. */
export function visibleCaptureButton(page: Page) {
  return page
    .locator('[data-testid="capture-button-desktop"], [data-testid="capture-button-mobile"]')
    .filter({ visible: true });
}

export async function openAccount(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Account" }).click();
  await expect(page.getByRole("dialog", { name: "Account" })).toBeVisible();
}

export async function pinInspector(page: Page): Promise<void> {
  await page.evaluate(() => {
    const key = "my-pa:shell-preferences:v1";
    const current = JSON.parse(localStorage.getItem(key) ?? "{}") as Record<string, unknown>;
    localStorage.setItem(key, JSON.stringify({ ...current, utilityPinned: true }));
  });
  await page.reload();
  await expect(visibleCaptureButton(page)).toBeVisible();
}

type SecretStoreDump = {
  local: Record<string, string>;
  session: Record<string, string>;
  indexed: unknown[];
  cached: Array<{ url: string; body: string }>;
  cookie: string;
};

/**
 * Dump web storage, IndexedDB, and CacheStorage and prove none of the named
 * sentinels (raw grant, recovery code, SID) were persisted. Cached static
 * bundles may mention the word "grant"; that is not a secret.
 */
export async function expectNoSecretInBrowserStores(
  page: Page,
  sentinels: readonly string[] = [],
): Promise<void> {
  const dump = (await page.evaluate(async () => {
    const fromStorage = (store: Storage) => {
      const entries: Record<string, string> = {};
      for (let index = 0; index < store.length; index += 1) {
        const key = store.key(index);
        if (key !== null) entries[key] = store.getItem(key) ?? "";
      }
      return entries;
    };
    const indexed: unknown[] = [];
    for (const meta of await indexedDB.databases()) {
      if (!meta.name) continue;
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const open = indexedDB.open(meta.name as string, meta.version);
        open.onsuccess = () => resolve(open.result);
        open.onerror = () => reject(open.error ?? new Error("idb"));
      });
      for (const storeName of Array.from(db.objectStoreNames)) {
        const rows = await new Promise<unknown>((resolve, reject) => {
          const req = db.transaction(storeName, "readonly").objectStore(storeName).getAll();
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => reject(req.error ?? new Error("idb store"));
        });
        indexed.push({ db: meta.name, store: storeName, rows });
      }
      db.close();
    }
    const cached: Array<{ url: string; body: string }> = [];
    for (const name of await caches.keys()) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) {
        const response = await cache.match(request);
        cached.push({
          url: request.url,
          body: response ? await response.clone().text().catch(() => "") : "",
        });
      }
    }
    return {
      local: fromStorage(localStorage),
      session: fromStorage(sessionStorage),
      indexed,
      cached,
      cookie: document.cookie,
    };
  })) as SecretStoreDump;

  const durable = JSON.stringify({
    local: dump.local,
    session: dump.session,
    indexed: dump.indexed,
    cookie: dump.cookie,
  }).toLowerCase();
  expect(durable, "HttpOnly SID must not appear in script-visible stores").not.toContain(
    "mypa_session",
  );
  expect(durable).not.toContain("bearer ");
  expect(durable).not.toMatch(/eyj[a-z0-9_-]+\.[a-z0-9_-]+\./i);

  const cachedUrls = dump.cached.map((entry) => new URL(entry.url).pathname);
  expect(
    cachedUrls.filter(
      (pathname) =>
        pathname === "/setup" ||
        pathname.startsWith("/setup/") ||
        pathname === "/recover/operator" ||
        pathname.startsWith("/recover/") ||
        pathname === "/api" ||
        pathname.startsWith("/api/") ||
        pathname === "/sign-in",
    ),
    "service-worker cache must not hold auth HTML, grants, or API",
  ).toEqual([]);

  const haystack = `${durable}\n${dump.cached.map((entry) => entry.body).join("\n")}`.toLowerCase();
  for (const sentinel of sentinels) {
    if (!sentinel) continue;
    expect(haystack, `sentinel ${sentinel} must not persist in browser stores`).not.toContain(
      sentinel.toLowerCase(),
    );
  }
}

/**
 * Assert that a region is one of the four truthful states and says which.
 *
 * The check is on `data-state`, which the four state cards carry and which no
 * amount of restyling can blur, plus the ARIA role — `alert` for the failure and
 * `status` for the three that are not failures — so a state that started
 * announcing itself as the wrong kind of thing reddens.
 */
export async function expectState(
  page: Page,
  testId: string,
  kind: "empty" | "unavailable" | "degraded" | "not_implemented",
): Promise<void> {
  const region = page.getByTestId(testId);
  await expect(region).toBeVisible();
  await expect(region).toHaveAttribute("data-state", kind);
  await expect(region).toHaveAttribute("role", kind === "unavailable" ? "alert" : "status");
}

/** The sentences a failed read must never contain. */
export const EMPTINESS_CLAIMS = [
  /holds nothing/i,
  /you have none/i,
  /no results/i,
  /nothing found/i,
];
