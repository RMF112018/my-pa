import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

const LIGHT_DIGEST = "0e23ec91915d7dee068c6aa1219d53cfda63ecaff273c859286d95b66723bae4";
const DARK_DIGEST = "d3e72a20779bbf0f309a3da1eb6d7699fd396281eb174293c2a8e0ff50d9bfaa";

const PUBLIC_PNGS = [
  "/icons/favicon-light-32.png",
  "/icons/favicon-dark-32.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
];

type IconLink = { rel: string; href: string; media: string | null };

async function iconLinks(page: Page): Promise<IconLink[]> {
  return page.evaluate(() =>
    Array.from(
      document.querySelectorAll('link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]'),
    ).map((node) => {
      const link = node as HTMLLinkElement;
      return {
        rel: link.rel,
        href: link.getAttribute("href") ?? "",
        media: link.getAttribute("media"),
      };
    }),
  );
}

async function matchingMediaIconHref(page: Page): Promise<string> {
  const href = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('link[rel="icon"][media]'));
    const match = links.find((node) =>
      window.matchMedia((node as HTMLLinkElement).media).matches,
    );
    return match?.getAttribute("href") ?? "";
  });
  expect(href).toBeTruthy();
  return href;
}

function sha256Hex(body: Buffer): string {
  return createHash("sha256").update(body).digest("hex");
}

test("public favicon and icon routes serve the My PA identity", async ({ page, request, baseURL }) => {
  await page.goto("/sign-in");
  await expect(page).toHaveTitle("My PA");

  const links = await iconLinks(page);
  expect(links.length).toBeGreaterThan(0);

  const light = links.find(
    (link) =>
      link.href.includes("favicon-light-32.png") && (link.media ?? "").includes("prefers-color-scheme: light"),
  );
  const dark = links.find(
    (link) =>
      link.href.includes("favicon-dark-32.png") && (link.media ?? "").includes("prefers-color-scheme: dark"),
  );
  expect(light, "light media favicon link").toBeTruthy();
  expect(dark, "dark media favicon link").toBeTruthy();
  expect(links.some((link) => (link.media ?? "").includes("prefers-color-scheme: light"))).toBe(true);
  expect(links.some((link) => (link.media ?? "").includes("prefers-color-scheme: dark"))).toBe(true);

  await page.emulateMedia({ colorScheme: "light" });
  const lightHref = await matchingMediaIconHref(page);
  expect(lightHref).toContain("favicon-light-32.png");
  const lightResponse = await request.get(new URL(lightHref, baseURL as string).toString());
  expect(lightResponse.status()).toBe(200);
  expect(sha256Hex(await lightResponse.body())).toBe(LIGHT_DIGEST);

  await page.emulateMedia({ colorScheme: "dark" });
  const darkHref = await matchingMediaIconHref(page);
  expect(darkHref).toContain("favicon-dark-32.png");
  const darkResponse = await request.get(new URL(darkHref, baseURL as string).toString());
  expect(darkResponse.status()).toBe(200);
  expect(sha256Hex(await darkResponse.body())).toBe(DARK_DIGEST);

  const favicon = await request.get(new URL("/favicon.ico", baseURL as string).toString());
  expect(favicon.status()).toBe(200);
  const faviconType = (favicon.headers()["content-type"] ?? "").toLowerCase();
  expect(
    faviconType.includes("icon") || faviconType.includes("octet-stream") || faviconType.includes("x-icon"),
  ).toBe(true);

  for (const path of PUBLIC_PNGS) {
    const response = await request.get(new URL(path, baseURL as string).toString());
    expect(response.status(), path).toBe(200);
    expect((response.headers()["content-type"] ?? "").toLowerCase(), path).toContain("png");
  }

  const applePaths = ["/apple-icon", "/apple-icon.png"] as const;
  const appleResults = [];
  for (const path of applePaths) {
    const response = await request.get(new URL(path, baseURL as string).toString());
    const contentType = (response.headers()["content-type"] ?? "").toLowerCase();
    appleResults.push({
      path,
      status: response.status(),
      contentType,
    });
  }
  const appleOk = appleResults.filter(
    (entry) => entry.status === 200 && (entry.contentType.includes("png") || entry.contentType.includes("image")),
  );
  expect(appleOk.length, `apple-icon routes: ${JSON.stringify(appleResults)}`).toBeGreaterThanOrEqual(1);
});
