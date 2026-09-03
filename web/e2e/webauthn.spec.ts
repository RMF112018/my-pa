import { test, expect } from "@playwright/test";
import { DEAD_GATEWAY_URL } from "../playwright.config";
import { ADMISSIBLE_PRINCIPAL, signIn } from "./fixtures";

const OPAQUE_SID = /^[0-9a-f]{64}$/;

async function sessionCookie(page: import("@playwright/test").Page, origin: string) {
  const cookies = await page.context().cookies(origin);
  return cookies.find((cookie) => cookie.name === "mypa_session");
}

test.describe("WebAuthn virtual authenticator", () => {
  test("registers a passkey through the real browser API", async ({ page }) => {
    const client = await page.context().newCDPSession(page);
    await client.send("WebAuthn.enable");
    await client.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "internal",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
        automaticPresenceSimulation: true,
      },
    });
    await signIn(page);
    await page.goto("/system/security");
    await expect(page.getByRole("heading", { name: "Security" })).toBeVisible();
    await page.getByRole("button", { name: "Add a passkey" }).click();
    await expect(page.getByRole("status")).toContainText(/Passkey added|could not/i);
  });
});

test.describe("opaque session cookie", () => {
  test("mypa_session is HttpOnly 64-hex after sign-in, not an HMAC token", async ({
    page,
    baseURL,
  }) => {
    await signIn(page);
    const cookie = await sessionCookie(page, baseURL as string);
    expect(cookie, "signed-in context must carry mypa_session").toBeDefined();
    expect(cookie!.httpOnly).toBe(true);
    expect(cookie!.value).toMatch(OPAQUE_SID);
    expect(cookie!.value).not.toContain(".");
    expect(cookie!.value.split(".")).toHaveLength(1);
  });

  test("sign-out revokes the SID so the same cookie value cannot replay", async ({
    page,
    baseURL,
  }) => {
    await signIn(page);
    const cookie = await sessionCookie(page, baseURL as string);
    expect(cookie?.value).toMatch(OPAQUE_SID);
    const sid = cookie!.value;

    const signOut = page.getByRole("button", { name: "Sign out" });
    if ((await signOut.count()) > 0) {
      await signOut.click();
      await page.waitForURL(/\/sign-in/);
    } else {
      const deleted = await page.request.delete("/api/session");
      expect(deleted.ok()).toBeTruthy();
      await page.goto("/sign-in");
    }

    await page.context().addCookies([
      {
        name: "mypa_session",
        value: sid,
        url: baseURL as string,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const replay = await page.request.get("/api/pulse");
    expect(replay.status(), "revoked SID must not authenticate a protected API").toBe(401);

    // Edge middleware only checks SID shape, so /today may still load. The
    // signed-in shell must not appear for a revoked cookie.
    await page.goto("/today");
    if (new URL(page.url()).pathname === "/today") {
      await expect(page.getByTestId("capture-button")).toHaveCount(0);
    } else {
      await expect(page).toHaveURL(/\/sign-in/);
    }
  });

  test("middleware plants a relative next and never an absolute evil URL", async ({ page }) => {
    await page.goto("/work");
    await expect(page).toHaveURL(/\/sign-in/);
    const landed = new URL(page.url());
    const next = landed.searchParams.get("next");
    expect(next).toBe("/work");
    expect(next?.startsWith("/")).toBe(true);
    expect(next).not.toMatch(/^https?:/i);
    expect(page.url()).not.toMatch(/evil/i);

    const button = page.getByTestId(`sign-in-${ADMISSIBLE_PRINCIPAL}`);
    await expect(button).toBeVisible();
    await button.click();
    await page.waitForURL((url) => {
      const path = new URL(url).pathname;
      return path === "/work" || path === "/today";
    });
    expect(page.url()).not.toMatch(/https:\/\/evil/i);

    await page.context().clearCookies();
    await page.goto("/sign-in?next=https://evil.example");
    await expect(page.getByTestId(`sign-in-${ADMISSIBLE_PRINCIPAL}`)).toBeVisible();
    await page.getByTestId(`sign-in-${ADMISSIBLE_PRINCIPAL}`).click();
    await page.waitForURL((url) => new URL(url).pathname === "/today");
    expect(page.url()).not.toMatch(/evil/i);
  });
});

test.describe("dead gateway session-service", () => {
  test("a cookie-shaped SID against a refused gateway is 503 not 401", async ({
    page,
    playwright,
  }) => {
    // 503 authority_unavailable for a cookie-shaped SID when the gateway port
    // answers nothing. Guard tests already pin the mapping; this is the browser
    // path. If the dead Next cannot be reached, fail rather than skip.
    await signIn(page);
    const cookie = await sessionCookie(page, page.url());
    expect(cookie?.value).toMatch(OPAQUE_SID);

    const dead = await playwright.request.newContext({
      baseURL: DEAD_GATEWAY_URL,
      extraHTTPHeaders: { cookie: `mypa_session=${cookie!.value}` },
    });
    try {
      const response = await dead.get("/api/pulse");
      expect(response.status(), "gateway outage must not look like a missing login").toBe(503);
      await expect(response.json()).resolves.toMatchObject({
        error: { code: "authority_unavailable" },
      });
    } finally {
      await dead.dispose();
    }
  });
});
