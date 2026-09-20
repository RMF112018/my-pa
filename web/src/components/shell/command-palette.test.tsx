/**
 * What the Search palette is allowed to say about a read that failed.
 *
 * **WP08-RT-F010, B-01.** The palette's failure branch once carried the
 * upstream `message` and handed it to `mapUserError`, which classified the text
 * and produced the right Level-1 sentence. Replacing that with a hardcoded
 * `{ errorClass: "unavailable", code: "coverage_unavailable" }` broke two
 * things at once, and this file holds both of them:
 *
 * * **The product sentence, in the default diagnostics-off mode.** Every
 *   failure that is not a 501 classifies as `unavailable` in the palette's own
 *   triage, so a network-down search and a session-authority failure both read
 *   "This could not be read. Try again." instead of "You appear to be offline."
 *   and "We couldn't verify your session.". Offline in particular must never
 *   collapse into a generic read failure.
 * * **The diagnostic, in the on mode.** The constant asserted a class and a
 *   code the backend never sent, in the one channel this work package exists to
 *   make trustworthy.
 *
 * The fix is to classify once, where the `ApiFailure` is caught, and carry the
 * closed record. So these tests assert over the rendered sentence and the
 * rendered diagnostic rather than over the shape of the variant, which is the
 * only place the defect was visible to a reader.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { diagnostics } = vi.hoisted(() => ({ diagnostics: { enabled: false } }));
vi.mock("@/components/diagnostics/diagnostics-provider", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/diagnostics/diagnostics-provider")>();
  return {
    ...actual,
    // Both, for the reason `today-pulse-surface.test.tsx` gives: `WhenDiagnostics`
    // closes over the real hook in its own module scope.
    useDiagnosticsEnabled: () => diagnostics.enabled,
    WhenDiagnostics: ({ children }: { children: React.ReactNode }) =>
      diagnostics.enabled ? children : null,
  };
});

const { search } = vi.hoisted(() => ({
  search: { fetch: vi.fn<(query: string, options?: unknown) => Promise<unknown>>() },
}));
vi.mock("@/lib/search/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/search/client")>();
  return {
    ...actual,
    fetchFederatedSearch: (query: string, options?: unknown) => search.fetch(query, options),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { SearchCommandPanel } from "@/components/shell/command-palette";
import type { ApiFailure } from "@/lib/api/work-client";

/** A transport failure in the shape `lib/api/work-client.ts` actually throws. */
function apiFailure(message: string, extra: Partial<ApiFailure> = {}): ApiFailure {
  const failure = new Error(message) as ApiFailure;
  return Object.assign(failure, extra);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  search.fetch.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  diagnostics.enabled = false;
});

/** Render the panel with a query already typed and let the debounce elapse. */
async function renderFailedSearch(failure: ApiFailure) {
  search.fetch.mockRejectedValue(failure);
  render(<SearchCommandPanel onCapture={() => {}} initialQuery="anything" />);
  await vi.advanceTimersByTimeAsync(250);
  await waitFor(() => expect(screen.getByTestId("search-unavailable")).toBeTruthy());
  return screen.getByTestId("search-unavailable");
}

describe("the Search palette's failed read, with diagnostics off", () => {
  it("says the person is offline rather than that the read failed generically", async () => {
    // `Failed to fetch` is what a browser throws when the network is down, and
    // it is the string `OFFLINE_TEXT` matches. The classification must survive
    // the trip from the catch to the render without the string doing so.
    await renderFailedSearch(apiFailure("Failed to fetch"));
    expect(screen.getByTestId("surface-state-detail").textContent).toBe(
      "You appear to be offline.",
    );
  });

  it("says the session could not be verified rather than that the read failed", async () => {
    await renderFailedSearch(
      apiFailure("session authority unavailable", { status: 503 }),
    );
    expect(screen.getByTestId("surface-state-detail").textContent).toBe(
      "We couldn't verify your session.",
    );
  });

  it("still says a read failed when nothing identifies the failure", async () => {
    // The generic sentence is correct here, and must not be lost while the two
    // specific ones are restored.
    await renderFailedSearch(apiFailure("Request failed (503)", { status: 503 }));
    expect(screen.getByTestId("surface-state-detail").textContent).toBe(
      "This could not be read. Try again.",
    );
  });

  it("renders no diagnostic at all", async () => {
    await renderFailedSearch(apiFailure("Failed to fetch"));
    expect(screen.queryByTestId("surface-state-diagnostic")).toBeNull();
  });
});

describe("the Search palette's failed read, with diagnostics on", () => {
  beforeEach(() => {
    diagnostics.enabled = true;
  });

  it("asserts no class and no code the backend did not send", async () => {
    const region = await renderFailedSearch(apiFailure("Failed to fetch"));
    const diagnostic = screen.getByTestId("surface-state-diagnostic").textContent ?? "";
    // The two fabricated values, named directly.
    expect(diagnostic).not.toContain("coverage_unavailable");
    expect(diagnostic).not.toContain("class unavailable");
    // What it says instead is what was observed: the network was not reached.
    expect(diagnostic).toContain("the network could not be reached");
    expect(diagnostic).toContain("no response was received from this device's network");
    // And the upstream sentence is still not on the page in either mode.
    expect(region.textContent ?? "").not.toContain("Failed to fetch");
  });

  it("names the backend's own class, code and status when it sent them", async () => {
    await renderFailedSearch(
      apiFailure("upstream blew up", {
        status: 503,
        errorClass: "unavailable",
        code: "gateway_unreachable",
      }),
    );
    const diagnostic = screen.getByTestId("surface-state-diagnostic").textContent ?? "";
    expect(diagnostic).toContain("class unavailable");
    expect(diagnostic).toContain("code gateway_unreachable");
    expect(diagnostic).toContain("HTTP 503");
    expect(diagnostic).not.toContain("upstream blew up");
  });

  it("names the condition of a not-built route without inventing a class", async () => {
    search.fetch.mockRejectedValue(apiFailure("no such route", { status: 501 }));
    render(<SearchCommandPanel onCapture={() => {}} initialQuery="anything" />);
    await vi.advanceTimersByTimeAsync(250);
    await waitFor(() => expect(screen.getByTestId("search-not-implemented")).toBeTruthy());
    const diagnostic = screen.getByTestId("surface-state-diagnostic").textContent ?? "";
    expect(diagnostic).toContain("code not_implemented");
    expect(diagnostic).toContain("HTTP 501");
    expect(diagnostic).not.toContain("class unavailable");
    expect(diagnostic).not.toContain("no such route");
  });
});
