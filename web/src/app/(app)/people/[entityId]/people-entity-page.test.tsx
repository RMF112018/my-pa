import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";
import {
  ASSIGNMENT,
  ENTITY_ID,
  IDENTITY_HISTORY_ENTRY,
  PROFILE,
  RELATIONSHIP,
} from "@/lib/api/decode/capabilities/_entity-fixtures";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
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

import { PeopleEntityPage } from "./people-entity-page";

function whole() {
  return {
    coverage: { state: "not_enrolled" },
    freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
    trust: { level: "source_original", basis: ["user_authored_record"] },
    truncation: { is_truncated: false },
    limitations: [],
    partial_result: false,
  };
}

function answerByCapability(map: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const capability = String(url).match(/\/v1\/([^/?#]+)/)?.[1] ?? "";
      const result = Object.prototype.hasOwnProperty.call(map, capability) ? map[capability] : {};
      return new Response(JSON.stringify({ result, disclosure: whole() }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
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

const HISTORY = {
  entity_id: ENTITY_ID,
  entries: [IDENTITY_HISTORY_ENTRY],
  is_truncated: false,
  next_cursor: null,
  audit_id: "audit_aaaaaaaa11111111",
};

describe("People entity page", () => {
  it("keeps the entity when companion reads fail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: unknown) => {
        const capability = String(url).match(/\/v1\/([^/?#]+)/)?.[1] ?? "";
        if (capability === "entities.profile") {
          return new Response(JSON.stringify({ result: { profile: PROFILE }, disclosure: whole() }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        throw new TypeError("fetch failed");
      }),
    );
    await renderServerPage(() =>
      PeopleEntityPage({ params: Promise.resolve({ entityId: ENTITY_ID }) }),
    );
    expect(screen.getByTestId("people-profile")).toBeTruthy();
    expect(screen.getByTestId("people-entity-id").textContent).toBe(ENTITY_ID);
    expect(screen.getByTestId("people-assignments-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.getByTestId("degraded-banner")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /merge/i })).toBeNull();
  });

  it("groups current and historical assignments from backend fields", async () => {
    answerByCapability({
      "entities.profile": { profile: PROFILE },
      "entities.assignments.list": {
        assignments: [
          { ...ASSIGNMENT, assignment_id: "asn_now000000000001", is_current: true, status: "active", role: "Current role" },
          { ...ASSIGNMENT, assignment_id: "asn_then00000000001", is_current: false, status: "ended", role: "Former role" },
        ],
      },
      "entities.relationships": { relationships: [RELATIONSHIP] },
      "entities.identity_history": HISTORY,
    });
    await renderServerPage(() =>
      PeopleEntityPage({ params: Promise.resolve({ entityId: ENTITY_ID }) }),
    );
    expect(screen.getByTestId("people-assignments-current").textContent).toMatch(/Current role/);
    expect(screen.getByTestId("people-assignments-historical").textContent).toMatch(/Former role/);
    expect(screen.getByTestId("people-history")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /merge/i })).toBeNull();
  });

  it("does not empty-success when the profile itself could not be read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    await renderServerPage(() =>
      PeopleEntityPage({ params: Promise.resolve({ entityId: ENTITY_ID }) }),
    );
    expect(screen.getByTestId("people-profile-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("people-profile")).toBeNull();
  });
});
