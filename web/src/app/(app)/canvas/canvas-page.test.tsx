/**
 * Map page answers. Seeded neighborhood e2e stays on People/search-contract
 * only because Playwright has no dedicated deterministic `entities.graph`
 * fixture; unit tests cover unseeded/not_found/truncated/synthetic; a11y scans
 * unseeded `/canvas`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";
import { canvasMap } from "@/lib/routes/canvas";

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

import { CanvasPage } from "./canvas-page";

const FOCUS = "ent_aaaaaaaa11111111";
const NEIGHBOR = "ent_bbbbbbbb22222222";
const CURSOR = "cur_aaaaaaaa11111111";

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

function node(entityId: string, label: string) {
  return {
    entity_id: entityId,
    projection_id: `gprj_${entityId}`,
    entity_type: "person",
    display_label: label,
    status: "active",
    superseded_by_entity_id: null,
  };
}

function edge() {
  return {
    edge_kind: "relationship",
    edge_id: "erel_aaaaaaaa11111111",
    type: "works_for",
    from_entity_id: FOCUS,
    to_entity_id: NEIGHBOR,
    from_projection_id: `gprj_${FOCUS}`,
    to_projection_id: `gprj_${NEIGHBOR}`,
    scope_entity_id: null,
    is_current: null,
    state: "active",
    version: 1,
  };
}

const TWO_NODES = {
  nodes: [node(FOCUS, "Pat Synthetic"), node(NEIGHBOR, "Acme Synthetic")],
  edges: [edge()],
  next_cursor: null as string | null,
};

function gatewayNotFound() {
  return new Response(
    JSON.stringify({
      error: {
        code: "not_found",
        message: "the named target was not found",
        correlation_id: "corr_aaaaaaaa11111111",
      },
    }),
    { status: 404, headers: { "content-type": "application/json" } },
  );
}

function emptyWorkspace(focus = FOCUS) {
  return {
    focus_entity_id: focus,
    scope_entity_id: null,
    version: 0,
    positions: {},
    updated_at: null,
  };
}

function answerGraph(
  result: unknown,
  disclosure: unknown = whole(),
  workspace: unknown = emptyWorkspace(),
) {
  const spy = vi.fn(async (url: string | URL | Request, _init?: RequestInit) => {
    const href = String(url);
    const body = href.includes("/v1/canvas.workspace.get")
      ? { result: workspace, disclosure }
      : { result, disclosure };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function fetchUrls(spy: ReturnType<typeof vi.fn>): string[] {
  return spy.mock.calls.map((call) => String(call[0]));
}

function payloadOf(spy: ReturnType<typeof vi.fn>, index: number): Record<string, unknown> {
  return JSON.parse(String(spy.mock.calls[index]?.[1]?.body ?? "{}")) as Record<string, unknown>;
}

function socketFails() {
  const spy = vi.fn(async () => {
    throw new TypeError("fetch failed");
  });
  vi.stubGlobal("fetch", spy);
  return spy;
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

function seededParams(extra: Record<string, string> = {}) {
  return Promise.resolve({ focusEntityId: FOCUS, ...extra });
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

describe("Canvas page", () => {
  it("renders the synthetic fixture state without calling the gateway", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const fetchSpy = socketFails();
    await renderServerPage(() => CanvasPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByTestId("canvas-synthetic")).toHaveAttribute("data-state", "not_implemented");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(fetchUrls(fetchSpy).some((url) => url.includes("canvas.workspace.get"))).toBe(false);
    expect(screen.queryByTestId("canvas-arrange-toggle")).toBeNull();
    expect(screen.queryByTestId("canvas-relationship-edit-toggle")).toBeNull();
  });

  it("requires a seed and does not invent a directory of everyone", async () => {
    const fetchSpy = socketFails();
    await renderServerPage(() => CanvasPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByTestId("canvas-seed-required")).toHaveAttribute("data-state", "empty");
    const search = screen.getByRole("link", { name: "Search People" });
    expect(search).toHaveAttribute("href", "/people");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(fetchUrls(fetchSpy).some((url) => url.includes("canvas.workspace.get"))).toBe(false);
    expect(screen.queryByTestId("canvas-arrange-toggle")).toBeNull();
    expect(screen.queryByTestId("canvas-relationship-edit-toggle")).toBeNull();
  });

  it("refuses invalid hops without calling the gateway", async () => {
    const fetchSpy = socketFails();
    await renderServerPage(() =>
      CanvasPage({ searchParams: seededParams({ hops: "not-an-integer" }) }),
    );
    expect(screen.getByTestId("canvas-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(fetchUrls(fetchSpy).some((url) => url.includes("canvas.workspace.get"))).toBe(false);
    expect(screen.queryByTestId("canvas-arrange-toggle")).toBeNull();
    expect(screen.queryByTestId("canvas-relationship-edit-toggle")).toBeNull();
  });

  it("refuses invalid pageSize without calling the gateway", async () => {
    const fetchSpy = socketFails();
    await renderServerPage(() =>
      CanvasPage({ searchParams: seededParams({ pageSize: "1.5" }) }),
    );
    expect(screen.getByTestId("canvas-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("posts entities.graph with a snake_case payload", async () => {
    const fetchSpy = answerGraph(TWO_NODES);
    await renderServerPage(() =>
      CanvasPage({
        searchParams: seededParams({
          hops: "2",
          relationshipTypes: "works_for,reports_to",
          asOf: "2026-01-01T00:00:00Z",
          pageSize: "25",
          after: "cur_prev00000000001",
        }),
      }),
    );
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/entities.graph");
    const sent = JSON.parse(String(fetchSpy.mock.calls[0]?.[1]?.body ?? "{}")) as {
      payload?: Record<string, unknown>;
    };
    expect(sent.payload).toEqual({
      focus_entity_id: FOCUS,
      hops: 2,
      relationship_types: ["works_for", "reports_to"],
      as_of: "2026-01-01T00:00:00Z",
      page_size: 25,
      after: "cur_prev00000000001",
    });
    expect(sent.payload).not.toHaveProperty("focusEntityId");
    expect(sent.payload).not.toHaveProperty("principal_id");
    expect(String(fetchSpy.mock.calls[1]?.[0])).toContain("/v1/canvas.workspace.get");
    const workspaceSent = payloadOf(fetchSpy, 1);
    expect(workspaceSent.payload).toEqual({ focus_entity_id: FOCUS });
    expect(workspaceSent.payload).not.toHaveProperty("principal_id");
    expect(workspaceSent.payload).not.toHaveProperty("focusEntityId");
  });

  it("says not found when the seed is unknown", async () => {
    const fetchSpy = vi.fn(async () => gatewayNotFound());
    vi.stubGlobal("fetch", fetchSpy);
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-not-found")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("canvas-empty")).toBeNull();
    expect(screen.queryByTestId("canvas-directory")).toBeNull();
    expect(screen.queryByTestId("canvas-arrange-toggle")).toBeNull();
    expect(screen.queryByTestId("canvas-relationship-edit-toggle")).toBeNull();
    expect(fetchUrls(fetchSpy).some((url) => url.includes("canvas.workspace.get"))).toBe(false);
  });

  it("says unavailable when the socket never answered", async () => {
    socketFails();
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("canvas-empty")).toBeNull();
  });

  it("says empty only when a seeded read returned no nodes", async () => {
    const fetchSpy = answerGraph({ nodes: [], edges: [], next_cursor: null });
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-empty")).toHaveAttribute("data-state", "empty");
    expect(screen.queryByTestId("canvas-directory")).toBeNull();
    expect(screen.queryByTestId("canvas-arrange-toggle")).toBeNull();
    expect(screen.queryByTestId("canvas-relationship-edit-toggle")).toBeNull();
    expect(fetchUrls(fetchSpy).some((url) => url.includes("canvas.workspace.get"))).toBe(false);
  });

  it("renders directory and map when the neighborhood has records", async () => {
    answerGraph(TWO_NODES);
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-directory")).toBeTruthy();
    expect(screen.getByTestId("canvas-map")).toBeTruthy();
    expect(screen.getAllByText("Pat Synthetic").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Acme Synthetic").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("canvas-continue")).toBeNull();
    expect(screen.getByTestId("canvas-arrange-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("canvas-relationship-edit-toggle")).toHaveAttribute("aria-pressed", "false");
  });

  it("still shows the graph when workspace get is unavailable", async () => {
    const fetchSpy = vi.fn(async (url: string | URL | Request) => {
      if (String(url).includes("/v1/canvas.workspace.get")) {
        throw new TypeError("fetch failed");
      }
      return new Response(JSON.stringify({ result: TWO_NODES, disclosure: whole() }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchSpy);
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-map")).toBeTruthy();
    expect(screen.getByTestId("canvas-directory")).toBeTruthy();
    expect(screen.queryByTestId("canvas-unavailable")).toBeNull();
    expect(fetchUrls(fetchSpy).some((url) => url.includes("canvas.workspace.get"))).toBe(true);
  });

  it("applies saved overlay points on the seeded map", async () => {
    answerGraph(TWO_NODES, whole(), {
      focus_entity_id: FOCUS,
      scope_entity_id: null,
      version: 1,
      positions: { [FOCUS]: { x: 10, y: 20 } },
      updated_at: "2026-01-01T00:00:00Z",
    });
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    const focusCircle = screen.getByTestId("canvas-map").querySelector(`circle[cx="10"][cy="20"]`);
    expect(focusCircle).not.toBeNull();
  });

  it("does not treat omitted nodes as an empty neighborhood", async () => {
    answerGraph({ edges: [], next_cursor: null });
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("canvas-empty")).toBeNull();
    expect(screen.queryByTestId("canvas-directory")).toBeNull();
  });

  it("does not treat omitted edges as an empty neighborhood", async () => {
    answerGraph({ nodes: TWO_NODES.nodes, next_cursor: null });
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("canvas-empty")).toBeNull();
  });

  it("continues a truncated neighborhood without claiming complete coverage", async () => {
    answerGraph(
      { ...TWO_NODES, next_cursor: CURSOR },
      whole({ truncation: { is_truncated: true, next_cursor: CURSOR } }),
    );
    await renderServerPage(() => CanvasPage({ searchParams: seededParams() }));
    expect(screen.getByTestId("canvas-directory")).toBeTruthy();
    expect(screen.getByTestId("canvas-map")).toBeTruthy();
    const cont = screen.getByTestId("canvas-continue");
    expect(cont).toHaveAttribute("href", canvasMap({ focusEntityId: FOCUS, after: CURSOR }));
    expect(screen.getByTestId("degraded-banner")).toBeTruthy();
    expect(screen.getByTestId("degraded-banner").textContent).toMatch(/less than the whole/i);
    expect(screen.getByTestId("degraded-banner").textContent).not.toMatch(/complete coverage/i);
  });
});
