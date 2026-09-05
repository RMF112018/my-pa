import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CanvasMapClient } from "./canvas-map-client";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

const FOCUS = "ent_aaaaaaaa11111111";
const NEIGHBOR = "ent_bbbbbbbb22222222";
const SCOPE = "ent_cccccccc33333333";
const NEW_EDGE_ID = "erel_newnewnew11111111";

const NODES: readonly GraphNode[] = [
  {
    entity_id: FOCUS,
    projection_id: `gprj_${FOCUS}`,
    entity_type: "person",
    display_label: "Pat Synthetic",
    status: "active",
    superseded_by_entity_id: null,
  },
  {
    entity_id: NEIGHBOR,
    projection_id: `gprj_${NEIGHBOR}`,
    entity_type: "person",
    display_label: "Acme Synthetic",
    status: "active",
    superseded_by_entity_id: null,
  },
];

const RELATIONSHIP_EDGE: GraphEdge = {
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

const ASSIGNMENT_EDGE: GraphEdge = {
  edge_kind: "assignment",
  edge_id: "asn_aaaaaaaa11111111",
  type: "employment",
  from_entity_id: FOCUS,
  to_entity_id: NEIGHBOR,
  from_projection_id: `gprj_${FOCUS}`,
  to_projection_id: `gprj_${NEIGHBOR}`,
  scope_entity_id: null,
  is_current: null,
  status: "active",
  version: 1,
};

const EDGES: readonly GraphEdge[] = [RELATIONSHIP_EDGE, ASSIGNMENT_EDGE];

const NEW_EDGE: GraphEdge = {
  ...RELATIONSHIP_EDGE,
  edge_id: NEW_EDGE_ID,
  type: "reports_to",
};

function mount(scopeEntityId = "") {
  return render(
    <CanvasMapClient
      nodes={NODES}
      edges={EDGES}
      focusEntityId={FOCUS}
      scopeEntityId={scopeEntityId}
      savedPositions={{}}
      version={0}
      graphQuery={
        scopeEntityId ? { focusEntityId: FOCUS, scopeEntityId } : { focusEntityId: FOCUS }
      }
    />,
  );
}

function stubMapRect() {
  vi.spyOn(SVGSVGElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 800,
    bottom: 560,
    width: 800,
    height: 560,
    toJSON() {
      return {};
    },
  });
}

function dragNode(clientX: number, clientY: number) {
  const node = screen.getByTestId(`canvas-node-${FOCUS}`);
  fireEvent.pointerDown(node, { pointerId: 1, clientX, clientY });
  const svg = screen.getByTestId("canvas-map").querySelector("svg");
  expect(svg).not.toBeNull();
  fireEvent.pointerMove(svg!, { pointerId: 1, clientX, clientY });
  fireEvent.pointerUp(svg!, { pointerId: 1, clientX, clientY });
}

function putBody(init?: RequestInit) {
  return JSON.parse(String(init?.body ?? "{}")) as {
    expected_version?: number;
    positions?: Record<string, { x: number; y: number }>;
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function entityBody(entityId: string, version = 1) {
  return {
    entity: {
      entity_id: entityId,
      entity_type: "person",
      canonical_name: "synthetic",
      display_name: "Synthetic",
      status: "active",
      created_at: "2026-01-01T00:00:00.000Z",
      updated_at: "2026-01-01T00:00:00.000Z",
      version,
      superseded_by_entity_id: null,
    },
  };
}

function conflictBody() {
  return {
    error: {
      errorClass: "conflict",
      code: "conflict",
      message: "stale expected_version",
    },
  };
}

function receipt(recordId: string) {
  return {
    record_id: recordId,
    record_family: "relationship",
    prior_version: null,
    version: 2,
    state: "active",
    receipt_id: "emut_aaaaaaaa11111111",
    audit_id: "audit_aaaaaaaa11111111",
    idempotency_key: "idem-1",
    superseded_id: null,
    evidence_refs: [],
    replayed: false,
    issued_at: "2026-09-05T17:00:00.000Z",
  };
}

function fetchMeta(url: string, init?: RequestInit) {
  return { href: String(url), method: String(init?.method ?? "GET") };
}

function fillCreateForm() {
  fireEvent.change(screen.getByLabelText("From"), { target: { value: FOCUS } });
  fireEvent.change(screen.getByLabelText("To"), { target: { value: NEIGHBOR } });
  fireEvent.change(screen.getByLabelText("Relationship type"), { target: { value: "reports_to" } });
}

function selectRelationshipEdge() {
  fireEvent.change(screen.getByLabelText("Selected relationship"), {
    target: { value: RELATIONSHIP_EDGE.edge_id },
  });
}

function openRelationshipEdit() {
  fireEvent.click(screen.getByTestId("canvas-relationship-edit-toggle"));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("CanvasMapClient", () => {
  it("defaults to read Map with People links and Arrange off", () => {
    mount();
    expect(screen.getByTestId("canvas-arrange-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("canvas-relationship-edit-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("link", { name: "Pat Synthetic" })).toHaveAttribute(
      "href",
      `/people/${FOCUS}`,
    );
    expect(screen.queryByTestId("canvas-relationship-create-form")).toBeNull();
  });

  it("disables People links while arranging", () => {
    mount();
    fireEvent.click(screen.getByTestId("canvas-arrange-toggle"));
    expect(screen.getByTestId("canvas-arrange-toggle")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("link", { name: "Pat Synthetic" })).toBeNull();
    expect(screen.getByTestId(`canvas-node-${FOCUS}`)).toBeTruthy();
    expect(screen.queryByTestId("canvas-relationship-create-form")).toBeNull();
  });

  it("shows the create form in relationship-edit and turns Arrange off", () => {
    mount();
    openRelationshipEdit();
    expect(screen.getByTestId("canvas-relationship-edit-toggle")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("canvas-arrange-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("canvas-relationship-create-form")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Pat Synthetic" })).toBeNull();
    expect(screen.getByTestId(`canvas-node-${FOCUS}`)).toBeTruthy();
    const selected = screen.getByLabelText("Selected relationship") as HTMLSelectElement;
    expect([...selected.options].map((option) => option.value)).toEqual([
      "",
      RELATIONSHIP_EDGE.edge_id,
    ]);
    fireEvent.click(screen.getByTestId("canvas-arrange-toggle"));
    expect(screen.getByTestId("canvas-arrange-toggle")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("canvas-relationship-edit-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("canvas-relationship-create-form")).toBeNull();
  });

  it("does not POST relationships when Arrange dragging", async () => {
    stubMapRect();
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      void url;
      const body = putBody(init);
      return jsonResponse({
        version: (body.expected_version ?? 0) + 1,
        updated_at: "2026-09-05T17:00:00.000Z",
        positions: body.positions ?? {},
      });
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    fireEvent.click(screen.getByTestId("canvas-arrange-toggle"));
    expect(screen.queryByTestId("canvas-relationship-create-form")).toBeNull();
    dragNode(120, 80);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const calls = fetchSpy.mock.calls.map(([url, init]) => fetchMeta(String(url), init));
    expect(calls.every((call) => call.href === "/api/canvas/workspace" && call.method === "POST")).toBe(
      true,
    );
    expect(calls.some((call) => call.href.includes("/api/canvas/relationships"))).toBe(false);
  });

  it("keeps local positions and shows a truthful conflict", async () => {
    stubMapRect();
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      void url;
      void init;
      return jsonResponse(conflictBody(), 409);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    fireEvent.click(screen.getByTestId("canvas-arrange-toggle"));
    dragNode(120, 80);
    expect(await screen.findByTestId("canvas-workspace-conflict")).toHaveTextContent(
      /saved layout version changed/i,
    );
    const moved = screen.getByTestId("canvas-map").querySelector(`circle[cx="120"][cy="80"]`);
    expect(moved).not.toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(putBody(fetchSpy.mock.calls[0][1])).toMatchObject({
      focus_entity_id: FOCUS,
      expected_version: 0,
    });
  });

  it("does not send overlapping PUTs with the same expected_version and keeps in-flight moves", async () => {
    stubMapRect();
    let releaseFirst: ((response: Response) => void) | undefined;
    const firstFetch = new Promise<Response>((resolve) => {
      releaseFirst = resolve;
    });
    let fetchCount = 0;
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      void url;
      fetchCount += 1;
      if (fetchCount === 1) {
        return firstFetch;
      }
      const body = putBody(init);
      return jsonResponse({
        version: (body.expected_version ?? 0) + 1,
        updated_at: "2026-09-05T17:00:00.000Z",
        positions: body.positions ?? {},
      });
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    fireEvent.click(screen.getByTestId("canvas-arrange-toggle"));
    dragNode(120, 80);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    dragNode(240, 160);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(putBody(fetchSpy.mock.calls[0][1]).expected_version).toBe(0);

    const firstPayload = putBody(fetchSpy.mock.calls[0][1]);
    releaseFirst!(
      jsonResponse({
        version: 1,
        updated_at: "2026-09-05T17:00:00.000Z",
        positions: firstPayload.positions ?? {},
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId("canvas-map").querySelector(`circle[cx="240"][cy="160"]`)).not.toBeNull();
    });
    expect(screen.getByTestId("canvas-map").querySelector(`circle[cx="120"][cy="80"]`)).toBeNull();

    await waitFor(() => expect(fetchSpy.mock.calls.length).toBe(2));
    const versions = fetchSpy.mock.calls.map((call) => putBody(call[1]).expected_version);
    expect(versions).toEqual([0, 1]);
    expect(putBody(fetchSpy.mock.calls[1][1]).positions?.[FOCUS]).toEqual({
      x: 240,
      y: 160,
    });
  });

  it("creates only after graph reload, never from a client-fabricated edge", async () => {
    let releaseGraph: ((response: Response) => void) | undefined;
    const graphFetch = new Promise<Response>((resolve) => {
      releaseGraph = resolve;
    });
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href === `/api/people/${FOCUS}`) return jsonResponse(entityBody(FOCUS, 3));
      if (method === "GET" && href === `/api/people/${NEIGHBOR}`) {
        return jsonResponse(entityBody(NEIGHBOR, 4));
      }
      if (method === "POST" && href === "/api/canvas/relationships") {
        return jsonResponse(receipt(NEW_EDGE_ID));
      }
      if (method === "GET" && href.startsWith("/api/people/graph")) return graphFetch;
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    fillCreateForm();
    fireEvent.click(screen.getByTestId("canvas-relationship-create-submit"));

    await waitFor(() => {
      const posts = fetchSpy.mock.calls.filter(
        ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships",
      );
      expect(posts).toHaveLength(1);
    });
    expect(screen.queryByTestId(`canvas-edge-${NEW_EDGE_ID}`)).toBeNull();
    expect(fetchSpy.mock.calls.some(([url, init]) => fetchMeta(String(url), init).href.startsWith("/api/people/graph"))).toBe(
      true,
    );

    const createBody = JSON.parse(
      String(
        fetchSpy.mock.calls.find(
          ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships",
        )?.[1]?.body ?? "{}",
      ),
    ) as Record<string, unknown>;
    expect(createBody).toMatchObject({
      from_entity_id: FOCUS,
      to_entity_id: NEIGHBOR,
      relationship_type: "reports_to",
      expected_from_version: 3,
      expected_to_version: 4,
    });
    expect(typeof createBody.idempotency_key).toBe("string");
    expect(createBody).not.toHaveProperty("scope_entity_id");

    const methodsBeforeReload = fetchSpy.mock.calls.map(([, init]) => String(init?.method ?? "GET"));
    const postIndex = methodsBeforeReload.indexOf("POST");
    expect(postIndex).toBeGreaterThan(-1);
    expect(methodsBeforeReload.slice(0, postIndex).every((method) => method === "GET")).toBe(true);

    releaseGraph!(
      jsonResponse({
        nodes: NODES,
        edges: [...EDGES, NEW_EDGE],
        next_cursor: null,
      }),
    );
    expect(await screen.findByTestId(`canvas-edge-${NEW_EDGE_ID}`)).toBeTruthy();
    fireEvent.click(screen.getByTestId("canvas-relationship-edit-toggle"));
    expect(screen.queryByTestId("canvas-relationship-create-form")).toBeNull();
    expect(screen.getByTestId(`canvas-edge-${NEW_EDGE_ID}`)).toBeTruthy();
  });

  it("shows a truthful conflict on create and does not treat it as success", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href.startsWith("/api/people/ent_")) {
        return jsonResponse(entityBody(href.slice("/api/people/".length)));
      }
      if (method === "POST" && href === "/api/canvas/relationships") {
        return jsonResponse(conflictBody(), 409);
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    fillCreateForm();
    fireEvent.click(screen.getByTestId("canvas-relationship-create-submit"));
    expect(await screen.findByTestId("canvas-relationship-conflict")).toHaveTextContent(
      /relationship version changed/i,
    );
    expect(screen.queryByTestId(`canvas-edge-${NEW_EDGE_ID}`)).toBeNull();
    expect(fetchSpy.mock.calls.some(([url]) => String(url).startsWith("/api/people/graph"))).toBe(false);
  });

  it("shows a truthful conflict on revise and does not treat it as success", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "POST" && href === "/api/canvas/relationships/revise") {
        return jsonResponse(conflictBody(), 409);
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    selectRelationshipEdge();
    fireEvent.change(screen.getByLabelText("Effective from"), {
      target: { value: "2026-01-01T00:00:00Z" },
    });
    fireEvent.click(screen.getByTestId("canvas-relationship-revise-submit"));
    expect(await screen.findByTestId("canvas-relationship-conflict")).toHaveTextContent(
      /relationship version changed/i,
    );
    const reviseBody = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body ?? "{}")) as Record<
      string,
      unknown
    >;
    expect(reviseBody).toMatchObject({
      relationship_id: RELATIONSHIP_EDGE.edge_id,
      expected_version: 1,
      effective_from: "2026-01-01T00:00:00Z",
    });
    expect(reviseBody).not.toHaveProperty("from_entity_id");
    expect(reviseBody).not.toHaveProperty("to_entity_id");
    expect(fetchSpy.mock.calls.some(([url]) => String(url).startsWith("/api/people/graph"))).toBe(false);
  });

  it("shows a truthful conflict on end, never DELETE", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "POST" && href === "/api/canvas/relationships/end") {
        return jsonResponse(conflictBody(), 409);
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    selectRelationshipEdge();
    fireEvent.change(screen.getByLabelText("End reason"), {
      target: { value: "no longer holds" },
    });
    fireEvent.click(screen.getByTestId("canvas-relationship-end-submit"));
    expect(await screen.findByTestId("canvas-relationship-conflict")).toHaveTextContent(
      /relationship version changed/i,
    );
    const methods = fetchSpy.mock.calls.map(([, init]) => String(init?.method ?? "GET"));
    expect(methods).toEqual(["POST"]);
    expect(methods.includes("DELETE")).toBe(false);
    const endBody = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body ?? "{}")) as Record<
      string,
      unknown
    >;
    expect(endBody).toMatchObject({
      relationship_id: RELATIONSHIP_EDGE.edge_id,
      expected_version: 1,
      reason: "no longer holds",
      end_now: true,
    });
  });

  it("does not POST create when a scope seed's version GET fails", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href === `/api/people/${FOCUS}`) return jsonResponse(entityBody(FOCUS, 3));
      if (method === "GET" && href === `/api/people/${NEIGHBOR}`) {
        return jsonResponse(entityBody(NEIGHBOR, 4));
      }
      if (method === "GET" && href === `/api/people/${SCOPE}`) {
        return jsonResponse({ error: { errorClass: "not_found", code: "not_found", message: "missing" } }, 404);
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount(SCOPE);
    openRelationshipEdit();
    fillCreateForm();
    fireEvent.click(screen.getByTestId("canvas-relationship-create-submit"));
    expect(await screen.findByTestId("canvas-relationship-save-error")).toHaveTextContent(
      /scope entity version was not returned/i,
    );
    expect(
      fetchSpy.mock.calls.some(
        ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships",
      ),
    ).toBe(false);
  });

  it("creates a scoped edge only when the scope version GET succeeds", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href === `/api/people/${FOCUS}`) return jsonResponse(entityBody(FOCUS, 3));
      if (method === "GET" && href === `/api/people/${NEIGHBOR}`) {
        return jsonResponse(entityBody(NEIGHBOR, 4));
      }
      if (method === "GET" && href === `/api/people/${SCOPE}`) return jsonResponse(entityBody(SCOPE, 5));
      if (method === "POST" && href === "/api/canvas/relationships") {
        return jsonResponse(receipt(NEW_EDGE_ID));
      }
      if (method === "GET" && href.startsWith("/api/people/graph")) {
        return jsonResponse({ nodes: NODES, edges: [...EDGES, NEW_EDGE], next_cursor: null });
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount(SCOPE);
    openRelationshipEdit();
    fillCreateForm();
    fireEvent.click(screen.getByTestId("canvas-relationship-create-submit"));
    await waitFor(() => {
      const posts = fetchSpy.mock.calls.filter(
        ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships",
      );
      expect(posts).toHaveLength(1);
    });
    const createBody = JSON.parse(
      String(
        fetchSpy.mock.calls.find(
          ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships",
        )?.[1]?.body ?? "{}",
      ),
    ) as Record<string, unknown>;
    expect(createBody).toMatchObject({
      from_entity_id: FOCUS,
      to_entity_id: NEIGHBOR,
      scope_entity_id: SCOPE,
      expected_scope_version: 5,
    });
    expect(await screen.findByTestId(`canvas-edge-${NEW_EDGE_ID}`)).toBeTruthy();
  });

  it("does not POST end when end_now is false and effective_end is empty", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      throw new Error(`unexpected ${fetchMeta(String(url), init).method} ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    selectRelationshipEdge();
    fireEvent.change(screen.getByLabelText("End reason"), {
      target: { value: "no longer holds" },
    });
    fireEvent.click(screen.getByLabelText("End now"));
    expect(screen.getByLabelText("Effective end")).toHaveValue("");
    fireEvent.click(screen.getByTestId("canvas-relationship-end-submit"));
    expect(await screen.findByTestId("canvas-relationship-save-error")).toHaveTextContent(
      /end needs end_now or an effective end/i,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("ends with effective_end and never sends end_now beside it", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "POST" && href === "/api/canvas/relationships/end") {
        return jsonResponse(conflictBody(), 409);
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    selectRelationshipEdge();
    fireEvent.change(screen.getByLabelText("End reason"), {
      target: { value: "no longer holds" },
    });
    fireEvent.click(screen.getByLabelText("End now"));
    fireEvent.change(screen.getByLabelText("Effective end"), {
      target: { value: "2026-08-09T12:00:00.000Z" },
    });
    fireEvent.click(screen.getByTestId("canvas-relationship-end-submit"));
    expect(await screen.findByTestId("canvas-relationship-conflict")).toHaveTextContent(
      /relationship version changed/i,
    );
    const endBody = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body ?? "{}")) as Record<
      string,
      unknown
    >;
    expect(endBody).toMatchObject({
      relationship_id: RELATIONSHIP_EDGE.edge_id,
      expected_version: 1,
      reason: "no longer holds",
      effective_end: "2026-08-09T12:00:00.000Z",
    });
    expect(endBody).not.toHaveProperty("end_now");
  });

  it("does not POST create when an endpoint version GET fails", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href === `/api/people/${FOCUS}`) return jsonResponse(entityBody(FOCUS, 3));
      if (method === "GET" && href === `/api/people/${NEIGHBOR}`) {
        return jsonResponse({ error: { errorClass: "not_found", code: "not_found", message: "missing" } }, 404);
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    fillCreateForm();
    fireEvent.click(screen.getByTestId("canvas-relationship-create-submit"));
    expect(await screen.findByTestId("canvas-relationship-save-error")).toHaveTextContent(
      /entity version was not returned/i,
    );
    expect(
      fetchSpy.mock.calls.some(
        ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships",
      ),
    ).toBe(false);
  });
});
