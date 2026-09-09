import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";
import { RESOLUTION } from "@/lib/api/decode/capabilities/_entity-fixtures";
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

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ name: "mypa_session", value: "stub" }) }),
}));
vi.mock("@/lib/auth/principal", () => ({
  resolveSessionPrincipal: async () => PRINCIPAL,
}));
vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next/navigation")>();
  return {
    ...actual,
    useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  };
});

import { PeoplePage } from "./people-page";

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

function answerWith(result: unknown, disclosure: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ result, disclosure }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
}

async function renderServerPage(page: () => Promise<React.ReactNode>) {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "window");
  Reflect.deleteProperty(globalThis, "window");
  let tree: React.ReactNode;
  try {
    tree = await page();
  } finally {
    if (saved) Object.defineProperty(globalThis, "window", saved);
  }
  return render(tree);
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

describe("People page caveat", () => {
  it("states the directory and non-merge caveat once", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    const { container } = await renderServerPage(() => PeoplePage({ searchParams: Promise.resolve({}) }));
    const text = container.textContent ?? "";
    expect(text.match(/not a directory/gi)).toHaveLength(1);
    expect(text.match(/ambiguous identities stay visible/gi)).toHaveLength(1);
    expect(text.match(/nothing here merges two people/gi)).toHaveLength(1);
    expect(screen.getByTestId("people-idle")).toHaveAttribute("data-state", "empty");
    expect(screen.getByTestId("people-idle").textContent ?? "").not.toMatch(/not a directory/i);
    expect(screen.queryByRole("button", { name: /merge/i })).toBeNull();
  });

  it("degraded incomplete search is not an empty directory", async () => {
    answerWith({ entities: [] }, whole({ partial_result: true, limitations: ["one scope was skipped"] }));
    await renderServerPage(() =>
      PeoplePage({ searchParams: Promise.resolve({ q: "Pat" }) }),
    );
    const state = screen.getByTestId("people-search-degraded-empty");
    expect(state).toHaveAttribute("data-state", "degraded");
    expect(state.textContent ?? "").not.toMatch(/holds nothing/i);
    expect(screen.queryByTestId("people-search-empty")).toBeNull();
    expect(collectLevel1Copy(state)).not.toMatch(/not a directory/i);
  });

  it("keeps an ambiguous resolve visible and offers no merge", async () => {
    answerWith({ resolution: RESOLUTION }, whole());
    const { container } = await renderServerPage(() =>
      PeoplePage({ searchParams: Promise.resolve({ reference: "Alex Chen" }) }),
    );
    expect(screen.getByTestId("people-resolve-outcome").textContent).toMatch(/ambiguous/i);
    expect(screen.queryByRole("button", { name: /merge/i })).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/\bMerge\b/);
    expect(screen.getByText("Alex Chen")).toBeTruthy();
  });
});
