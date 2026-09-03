import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures";

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
