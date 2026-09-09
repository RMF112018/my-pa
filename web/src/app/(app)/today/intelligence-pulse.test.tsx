/**
 * Level-1 copy on the shipped Today Intelligence pulse.
 *
 * The helper in user-copy.test.ts only classifies strings it is handed. This
 * file renders `IntelligencePulse` through the real gateway/surfaceAnswer path
 * and fails if the primary copy still leads with plane/artifact doctrine.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";
import { collectLevel1Copy } from "@/lib/ui/user-copy";

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "11111111-2222-3333-4444-555555555555:aaaa0001-0000-0000-0000-000000000001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next/navigation")>();
  return {
    ...actual,
    useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  };
});

import { IntelligencePulse } from "./intelligence-pulse";

function whole(overrides: Record<string, unknown> = {}) {
  return {
    coverage: { state: "not_enrolled" },
    freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
    trust: { level: "source_original", basis: ["user_authored_record"] },
    truncation: { is_truncated: false },
    limitations: [],
    partial_result: false,
    ...overrides,
  };
}

function answerReportsList(result: unknown, disclosure: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const capability = String(url).match(/\/v1\/([^/?#]+)/)?.[1] ?? "";
      const payload = capability === "reports.list" ? result : {};
      return new Response(JSON.stringify({ result: payload, disclosure }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

async function renderPulse() {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "window");
  Reflect.deleteProperty(globalThis, "window");
  let tree: React.ReactNode;
  try {
    tree = await IntelligencePulse({ principal: PRINCIPAL });
  } finally {
    if (saved) Object.defineProperty(globalThis, "window", saved);
  }
  return render(tree);
}

function expectUserTaskLevel1() {
  const card = screen.getByTestId("intelligence-pulse");
  const level1 = collectLevel1Copy(card);
  expect(level1).not.toMatch(/\bplane\b/i);
  expect(level1).not.toMatch(/\bartifacts?\b/i);
  expect(level1).not.toMatch(/report plane/i);
  expect(level1).not.toMatch(/^the report/i);
}

beforeEach(() => {
  vi.stubEnv("MYPA_GATEWAY_URL", "http://gateway.invalid");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("IntelligencePulse Level-1 copy on Today", () => {
  it("does not lead empty with artifact-system wording", async () => {
    answerReportsList({ items: [], next_cursor: null }, whole());
    await renderPulse();
    expect(screen.getByTestId("intelligence-pulse")).toHaveAttribute("data-state", "empty");
    expect(screen.getByTestId("intelligence-pulse-none").textContent).toMatch(/no briefings yet/i);
    expectUserTaskLevel1();
  });

  it("does not say the report plane was read incompletely in degraded Level-1", async () => {
    answerReportsList({ items: [], next_cursor: null }, whole({ partial_result: true }));
    await renderPulse();
    expect(screen.getByTestId("intelligence-pulse")).toHaveAttribute("data-state", "degraded");
    const announcement = screen.getByTestId("intelligence-pulse-degraded");
    expect(announcement.textContent).toMatch(/could not be read completely/i);
    expect(announcement.textContent).not.toMatch(/\bplane\b/i);
    expectUserTaskLevel1();
    expect(screen.getByTestId("intelligence-pulse-details").textContent).toMatch(/report plane/i);
  });
});
