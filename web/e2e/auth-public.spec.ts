/**
 * Public owner-setup and operator-recovery routes.
 *
 * **Limitation, stated rather than papered over.** This e2e stack always
 * migrates a shared disposable database, seeds synthetic Work/Review data, and
 * signs in through `MYPA_AUTH_MODE=synthetic`. The operator CLI refuses to
 * issue a bootstrap grant unless RP ID and origin are production
 * (`pa.bobby-fetting.me`). First-user bootstrap against a clean uninitialized
 * store is therefore not constructible here; AC072-074 remain operator-gated
 * physical/runtime evidence. What this file still proves:
 *
 * - `/setup` and `/recover/operator` are public (no sign-in bounce);
 * - a pasted grant is not written to cookies, web storage, IndexedDB, or
 *   CacheStorage;
 * - direct `registration/options` without a grant is refused;
 * - the service worker does not cache those routes or `/api/webauthn/*`.
 */
import { expect, test } from "@playwright/test";
import { LIVE_URL } from "../playwright.config";
import { expectNoSecretInBrowserStores, signIn } from "./fixtures";

const ATTACKER_ORIGIN = "https://attacker.example";

async function pasteGrantAndLeave(
  page: import("@playwright/test").Page,
  path: "/setup" | "/recover/operator",
  label: string,
  sentinel: string,
): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("heading", { name: /my-pa/i })).toBeVisible();
  const field = page.getByLabel(label);
  await expect(field).toBeVisible();
  await field.fill(sentinel);
  await expectNoSecretInBrowserStores(page, [sentinel]);
  await page.goto("/sign-in");
  await expectNoSecretInBrowserStores(page, [sentinel]);
}

test.describe("public setup and operator recovery", () => {
  test("/setup is public and does not store the grant", async ({ page }) => {
    const sentinel = `e2e-bootstrap-grant-${crypto.randomUUID()}`;
    await page.goto("/setup");
    expect(new URL(page.url()).pathname).toBe("/setup");
    await expect(page.getByRole("heading", { name: "Owner setup" })).toBeVisible();
    await pasteGrantAndLeave(page, "/setup", "Setup grant", sentinel);
  });

  test("/recover/operator is public and does not store the grant", async ({ page }) => {
    const sentinel = `e2e-recovery-grant-${crypto.randomUUID()}`;
    await page.goto("/recover/operator");
    expect(new URL(page.url()).pathname).toBe("/recover/operator");
    await expect(page.getByRole("heading", { name: "Operator recovery" })).toBeVisible();
    await pasteGrantAndLeave(
      page,
      "/recover/operator",
      "Operator recovery grant",
      sentinel,
    );
  });

  test("direct registration/options without a grant fails", async ({ page }) => {
    await page.goto("/setup");
    const unsigned = await page.evaluate(async () => {
      const response = await fetch("/api/webauthn/registration/options", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: "{}",
      });
      return {
        status: response.status,
        body: (await response.json()) as { error?: { code?: string } },
      };
    });
    expect(unsigned.status).toBe(401);

    await signIn(page);
    const signed = await page.evaluate(async () => {
      const response = await fetch("/api/webauthn/registration/options", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: "{}",
      });
      return {
        status: response.status,
        body: (await response.json()) as { error?: { code?: string } },
      };
    });
    expect(signed.status, "authenticated enrollment still needs a step-up grant").toBeGreaterThanOrEqual(
      400,
    );
    expect(["step_up_required", "unauthenticated", "invalid_request"]).toContain(
      signed.body.error?.code ?? "",
    );
  });

  test("cross-origin public auth mutations are 403", async ({ page }) => {
    await page.goto("/setup");
    for (const path of [
      "/api/webauthn/auth-state",
      "/api/webauthn/bootstrap/registration/options",
      "/api/webauthn/operator-recovery/registration/options",
    ]) {
      const response = await fetch(`${LIVE_URL}${path}`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          origin: ATTACKER_ORIGIN,
        },
        body: JSON.stringify({ grant: "e2e-cross-origin-grant" }),
      });
      expect(response.status, path).toBe(403);
      const body = (await response.json()) as { error?: { code?: string } };
      expect(body.error?.code, path).toBe("cross_site_request");
    }
  });

  test("service worker cache holds no grant, setup, or recovery document", async ({
    page,
  }) => {
    await page.goto("/setup");
    await page.goto("/recover/operator");
    await page.goto("/sign-in");
    await expectNoSecretInBrowserStores(page, ["e2e-bootstrap-grant", "e2e-recovery-grant"]);
  });
});
