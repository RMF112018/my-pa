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
  const button = page.getByTestId(`sign-in-${ADMISSIBLE_PRINCIPAL}`);
  await expect(button).toBeVisible();
  await button.click();
  await page.waitForURL("**/today");
  await expect(page.getByTestId("capture-button")).toBeVisible();
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
