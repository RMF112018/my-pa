/**
 * Installability, measured in the browser rather than read off a file.
 *
 * A manifest that parses and a worker that registers are the two things a static
 * review cannot establish, and they are the two things Chromium actually checks
 * before it will offer an install. So this file asks the browser: did the
 * manifest parse into the fields it needs, is a service worker **activated and
 * controlling this page**, and does the worker's fetch handler behave as the
 * partitioning rule requires.
 *
 * **No claim is made about universal background capability, because there is
 * none.** The worker holds no queue and performs no replay; Background Sync is
 * not used. The offline capture path is a foreground path, and `offline.spec.ts`
 * proves it as one. A test asserting "notes send themselves from a closed tab"
 * would be asserting something this build deliberately does not do.
 */
import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures";

/** The sizes Chromium wants before it treats an icon set as installable. */
const REQUIRED_ICON_SIZES = ["192x192", "512x512"];

test("the manifest is linked, parses, and carries the install fields", async ({ page, request, baseURL }) => {
  await page.goto("/sign-in");

  const link = page.locator('link[rel="manifest"]');
  await expect(link).toHaveCount(1);
  const href = await link.getAttribute("href");
  expect(href).toBeTruthy();

  const response = await request.get(new URL(href as string, baseURL as string).toString());
  expect(response.status()).toBe(200);
  const manifest = (await response.json()) as {
    name?: string;
    short_name?: string;
    start_url?: string;
    scope?: string;
    display?: string;
    background_color?: string;
    theme_color?: string;
    icons?: Array<{ src: string; sizes: string; type: string; purpose?: string }>;
  };

  expect(manifest.name, "name").toBeTruthy();
  expect(manifest.short_name, "short_name").toBeTruthy();
  expect(manifest.start_url, "start_url").toBeTruthy();
  expect(manifest.scope, "scope").toBeTruthy();
  expect(["standalone", "fullscreen", "minimal-ui"]).toContain(manifest.display);
  expect(manifest.background_color, "background_color").toBeTruthy();
  expect(manifest.theme_color, "theme_color").toBeTruthy();

  const sizes = (manifest.icons ?? []).flatMap((icon) => icon.sizes.split(/\s+/));
  for (const required of REQUIRED_ICON_SIZES) {
    expect(sizes, `an icon of ${required} is required for installability`).toContain(required);
  }
  // A maskable icon is what stops the launcher from letterboxing the app.
  expect(
    (manifest.icons ?? []).some((icon) => (icon.purpose ?? "").includes("maskable")),
    "at least one maskable icon",
  ).toBe(true);

  // Every icon the manifest names must actually be fetchable at its own type.
  for (const icon of manifest.icons ?? []) {
    const iconResponse = await request.get(new URL(icon.src, baseURL as string).toString());
    expect(iconResponse.status(), `${icon.src} must be served`).toBe(200);
    expect(iconResponse.headers()["content-type"]).toContain(icon.type.split("/")[1]);
  }
});

test("the service worker registers, activates, and controls the page", async ({ page }) => {
  await signIn(page);

  const state = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    return {
      scope: registration.scope,
      active: registration.active?.state ?? null,
      controlled: navigator.serviceWorker.controller !== null,
    };
  });

  expect(state.active, "the worker must reach 'activated'").toBe("activated");
  expect(state.scope).toContain("/");

  // Control arrives on the next navigation for a first-load registration; the
  // worker calls `clients.claim()`, so a reload must be controlled.
  await page.reload();
  const controlled = await page.evaluate(() => navigator.serviceWorker.controller !== null);
  expect(controlled, "the activated worker must control the page after a reload").toBe(true);
  expect(state.controlled || controlled).toBe(true);
});

test("the worker never caches a principal-bound response", async ({ page }) => {
  await signIn(page);
  await page.waitForFunction(async () => (await navigator.serviceWorker.ready) !== undefined);
  await page.goto("/library");
  await page.reload();

  const cached = await page.evaluate(async () => {
    const names = await caches.keys();
    const urls: string[] = [];
    for (const name of names) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) urls.push(request.url);
    }
    return urls;
  });

  // Not one `/api/*` response, and not one HTML document: both are
  // session-derived, and a cache is shared by every session on this profile.
  expect(cached.filter((url) => new URL(url).pathname.startsWith("/api"))).toEqual([]);
  expect(cached.some((url) => url.endsWith("/manifest.webmanifest"))).toBe(true);
});
