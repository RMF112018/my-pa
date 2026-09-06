import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { CanvasMapClient } from "./canvas-map-client";
import { CanvasInspector } from "./canvas-inspector";
import { InspectorSelectionProvider } from "@/components/shell/inspector-selection";
import { IDENTITY_HISTORY_ENTRY } from "@/lib/api/decode/capabilities/_entity-fixtures";
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

const SECOND_EDGE: GraphEdge = {
  ...RELATIONSHIP_EDGE,
  edge_id: "erel_bbbbbbbb22222222",
  type: "reports_to",
};

const EDGES: readonly GraphEdge[] = [RELATIONSHIP_EDGE, ASSIGNMENT_EDGE];

const NEW_EDGE: GraphEdge = {
  ...RELATIONSHIP_EDGE,
  edge_id: NEW_EDGE_ID,
  type: "reports_to",
};

function mount(scopeEntityId = "", edges: readonly GraphEdge[] = EDGES) {
  return render(
    <CanvasMapClient
      nodes={NODES}
      edges={edges}
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

function mountWithInspector(scopeEntityId = "") {
  return render(
    <InspectorSelectionProvider>
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
      />
      <CanvasInspector />
    </InspectorSelectionProvider>,
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

function relationshipsBody(overrides: Record<string, unknown> = {}) {
  return {
    relationships: [
      {
        relationship_id: RELATIONSHIP_EDGE.edge_id,
        is_current: true,
        from_entity_id: FOCUS,
        relationship_type: "works_for",
        to_entity_id: NEIGHBOR,
        scope_entity_id: null,
        state: "active",
        effective_from: null,
        effective_to: null,
        version: 1,
        ...overrides,
      },
    ],
  };
}

function isRelationshipsGet(href: string, method: string) {
  return method === "GET" && /\/api\/people\/[^/]+\/relationships$/.test(href);
}

function postBodyFor(fetchSpy: ReturnType<typeof vi.fn>, href: string) {
  const call = fetchSpy.mock.calls.find(
    ([url, init]) => fetchMeta(String(url), init).href === href,
  );
  return JSON.parse(String(call?.[1]?.body ?? "{}")) as Record<string, unknown>;
}

function identityHistoryBody(overrides: Record<string, unknown> = {}) {
  return {
    entity_id: FOCUS,
    entries: [IDENTITY_HISTORY_ENTRY],
    is_truncated: false,
    next_cursor: null,
    audit_id: "audit_aaaaaaaa11111111",
    shape: "backend",
    disclosure: { limitations: [] },
    ...overrides,
  };
}

function fillCreateForm() {
  fireEvent.change(screen.getByLabelText("From"), { target: { value: FOCUS } });
  fireEvent.change(screen.getByLabelText("To"), { target: { value: NEIGHBOR } });
  fireEvent.change(screen.getByLabelText("Relationship type"), { target: { value: "reports_to" } });
}

function selectRelationshipEdge(edgeId = RELATIONSHIP_EDGE.edge_id) {
  fireEvent.change(screen.getByLabelText("Selected relationship"), {
    target: { value: edgeId },
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
  it("defaults to inspectable Map without People wrappers on the graph", () => {
    mount();
    expect(screen.getByTestId("canvas-arrange-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("canvas-relationship-edit-toggle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("link", { name: "Pat Synthetic" })).toBeNull();
    expect(screen.getByTestId(`canvas-node-${FOCUS}`)).toBeTruthy();
    expect(screen.queryByTestId("canvas-relationship-create-form")).toBeNull();
  });

  it("publishes node fields to the inspector and keeps the People link there", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href.startsWith(`/api/people/${FOCUS}/identity-history`)) {
        return jsonResponse(identityHistoryBody());
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mountWithInspector();
    expect(screen.queryByRole("link", { name: "Pat Synthetic" })).toBeNull();
    fireEvent.click(screen.getByTestId(`canvas-node-${FOCUS}`));
    const panel = await screen.findByTestId("inspector-node");
    expect(panel).toHaveTextContent("Pat Synthetic");
    expect(panel).toHaveTextContent("person");
    expect(panel).toHaveTextContent("active");
    expect(panel).toHaveTextContent(FOCUS);
    expect(screen.getByRole("link", { name: "Pat Synthetic" })).toHaveAttribute(
      "href",
      `/people/${FOCUS}`,
    );
    expect(await screen.findByTestId("inspector-changes")).toHaveTextContent(
      IDENTITY_HISTORY_ENTRY.operation,
    );
    expect(screen.getByTestId("inspector-changes")).toHaveTextContent(
      IDENTITY_HISTORY_ENTRY.history_id,
    );
    expect(screen.getByTestId("inspector-changes")).toHaveTextContent(
      IDENTITY_HISTORY_ENTRY.occurred_at,
    );
    expect(screen.getByTestId("inspector-changes")).not.toHaveTextContent("direct_mutation");
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
      if (isRelationshipsGet(href, method)) return jsonResponse(relationshipsBody());
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
    fireEvent.change(screen.getByLabelText("Evidence refs"), {
      target: { value: "ev_stated" },
    });
    fireEvent.click(screen.getByTestId("canvas-relationship-revise-submit"));
    expect(await screen.findByTestId("canvas-relationship-conflict")).toHaveTextContent(
      /relationship version changed/i,
    );
    const reviseBody = postBodyFor(fetchSpy, "/api/canvas/relationships/revise");
    expect(reviseBody).toMatchObject({
      relationship_id: RELATIONSHIP_EDGE.edge_id,
      expected_version: 1,
      effective_from: "2026-01-01T00:00:00Z",
      evidence_refs: ["ev_stated"],
    });
    expect(reviseBody).not.toHaveProperty("from_entity_id");
    expect(reviseBody).not.toHaveProperty("to_entity_id");
    expect(fetchSpy.mock.calls.some(([url]) => String(url).startsWith("/api/people/graph"))).toBe(false);
  });

  it("does not POST a window-only revise that would clear citations", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) return jsonResponse(relationshipsBody());
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
    expect(screen.getByTestId("canvas-relationship-save-error")).toHaveTextContent(
      /cannot display current citations/i,
    );
    expect(screen.getByTestId("canvas-relationship-save-error")).toHaveTextContent(
      /inspector cannot read evidence_refs/i,
    );
    expect(
      fetchSpy.mock.calls.some(
        ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships/revise",
      ),
    ).toBe(false);
  });

  it("prefills the revise window from entities.relationships and still refuses window-only revise", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) {
        return jsonResponse(
          relationshipsBody({
            effective_from: "2026-01-01T00:00:00Z",
            effective_to: "2026-12-31T00:00:00Z",
          }),
        );
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    selectRelationshipEdge();
    await waitFor(() => {
      expect(screen.getByLabelText("Effective from")).toHaveValue("2026-01-01T00:00:00Z");
    });
    expect(screen.getByLabelText("Effective to")).toHaveValue("2026-12-31T00:00:00Z");
    fireEvent.click(screen.getByTestId("canvas-relationship-revise-submit"));
    expect(screen.getByTestId("canvas-relationship-save-error")).toHaveTextContent(
      /cannot display current citations/i,
    );
    expect(screen.getByTestId("canvas-relationship-save-error")).toHaveTextContent(
      /inspector cannot read evidence_refs/i,
    );
    expect(
      fetchSpy.mock.calls.some(
        ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships/revise",
      ),
    ).toBe(false);
  });

  it("does not revise the newly selected edge with the prior edge window", async () => {
    const twoEdges = [RELATIONSHIP_EDGE, SECOND_EDGE, ASSIGNMENT_EDGE];
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) {
        return jsonResponse({
          relationships: [
            {
              relationship_id: RELATIONSHIP_EDGE.edge_id,
              is_current: true,
              from_entity_id: FOCUS,
              relationship_type: "works_for",
              to_entity_id: NEIGHBOR,
              scope_entity_id: null,
              state: "active",
              effective_from: "2026-01-01T00:00:00Z",
              effective_to: "2026-06-01T00:00:00Z",
              version: 1,
            },
            {
              relationship_id: SECOND_EDGE.edge_id,
              is_current: true,
              from_entity_id: FOCUS,
              relationship_type: "reports_to",
              to_entity_id: NEIGHBOR,
              scope_entity_id: null,
              state: "active",
              effective_from: "2026-07-01T00:00:00Z",
              effective_to: "2026-12-01T00:00:00Z",
              version: 1,
            },
          ],
        });
      }
      if (method === "POST" && href === "/api/canvas/relationships/revise") {
        return jsonResponse(receipt(SECOND_EDGE.edge_id));
      }
      if (method === "GET" && href.startsWith("/api/people/graph")) {
        return jsonResponse({ nodes: NODES, edges: twoEdges, next_cursor: null });
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount("", twoEdges);
    openRelationshipEdit();
    selectRelationshipEdge(RELATIONSHIP_EDGE.edge_id);
    await waitFor(() => {
      expect(screen.getByLabelText("Effective from")).toHaveValue("2026-01-01T00:00:00Z");
    });
    expect(screen.getByLabelText("Effective to")).toHaveValue("2026-06-01T00:00:00Z");
    selectRelationshipEdge(SECOND_EDGE.edge_id);
    await waitFor(() => {
      expect(screen.getByLabelText("Effective from")).toHaveValue("2026-07-01T00:00:00Z");
    });
    expect(screen.getByLabelText("Effective to")).toHaveValue("2026-12-01T00:00:00Z");
    fireEvent.change(screen.getByLabelText("Evidence refs"), {
      target: { value: "ev_stated" },
    });
    fireEvent.click(screen.getByTestId("canvas-relationship-revise-submit"));
    await waitFor(() => {
      expect(
        fetchSpy.mock.calls.some(
          ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships/revise",
        ),
      ).toBe(true);
    });
    const reviseBody = postBodyFor(fetchSpy, "/api/canvas/relationships/revise");
    expect(reviseBody).toMatchObject({
      relationship_id: SECOND_EDGE.edge_id,
      expected_version: 1,
      effective_from: "2026-07-01T00:00:00Z",
      effective_to: "2026-12-01T00:00:00Z",
      evidence_refs: ["ev_stated"],
    });
    expect(reviseBody.effective_from).not.toBe("2026-01-01T00:00:00Z");
    expect(reviseBody.effective_to).not.toBe("2026-06-01T00:00:00Z");
  });

  it("POSTs stated evidence_refs on revise", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) return jsonResponse(relationshipsBody());
      if (method === "POST" && href === "/api/canvas/relationships/revise") {
        return jsonResponse(receipt(RELATIONSHIP_EDGE.edge_id));
      }
      if (method === "GET" && href.startsWith("/api/people/graph")) {
        return jsonResponse({ nodes: NODES, edges: EDGES, next_cursor: null });
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    openRelationshipEdit();
    selectRelationshipEdge();
    fireEvent.change(screen.getByLabelText("Evidence refs"), {
      target: { value: "ev_one, ev_two" },
    });
    fireEvent.click(screen.getByTestId("canvas-relationship-revise-submit"));
    await waitFor(() => {
      expect(
        fetchSpy.mock.calls.some(
          ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships/revise",
        ),
      ).toBe(true);
    });
    const reviseCall = fetchSpy.mock.calls.find(
      ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships/revise",
    );
    const reviseBody = JSON.parse(String(reviseCall?.[1]?.body ?? "{}")) as Record<string, unknown>;
    expect(reviseBody.evidence_refs).toEqual(["ev_one", "ev_two"]);
  });

  it("shows a truthful conflict on end, never DELETE", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) return jsonResponse(relationshipsBody());
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
    expect(methods.includes("POST")).toBe(true);
    expect(methods.includes("DELETE")).toBe(false);
    const endBody = postBodyFor(fetchSpy, "/api/canvas/relationships/end");
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
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) return jsonResponse(relationshipsBody());
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
    expect(
      fetchSpy.mock.calls.some(
        ([url, init]) => fetchMeta(String(url), init).href === "/api/canvas/relationships/end",
      ),
    ).toBe(false);
  });

  it("ends with effective_end and never sends end_now beside it", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) return jsonResponse(relationshipsBody());
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
    const endBody = postBodyFor(fetchSpy, "/api/canvas/relationships/end");
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

  it("publishes relationship edge fields and window without inventing citations", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (isRelationshipsGet(href, method)) {
        return jsonResponse(
          relationshipsBody({
            effective_from: "2026-02-01T00:00:00Z",
            effective_to: null,
          }),
        );
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    mountWithInspector();
    fireEvent.click(screen.getByTestId(`canvas-edge-${RELATIONSHIP_EDGE.edge_id}`));
    const panel = await screen.findByTestId("inspector-edge");
    expect(panel).toHaveTextContent("works_for");
    expect(panel).toHaveTextContent("relationship");
    expect(panel).toHaveTextContent("active");
    expect(panel).toHaveTextContent("unspecified");
    expect(panel).toHaveTextContent(FOCUS);
    expect(panel).toHaveTextContent(NEIGHBOR);
    await waitFor(() => {
      expect(panel).toHaveTextContent("2026-02-01T00:00:00Z");
    });
    expect(panel).not.toHaveTextContent("evidence_refs");
  });
});

function syntheticNode(index: number): GraphNode {
  const entityId = index === 0 ? FOCUS : `ent_${index.toString(16).padStart(16, "0")}`;
  return {
    entity_id: entityId,
    projection_id: `gprj_${entityId}`,
    entity_type: "person",
    display_label: `Synthetic ${index}`,
    status: "active",
    superseded_by_entity_id: null,
  };
}

function neighborhoodWithRing(ringCount: number): GraphNode[] {
  return [syntheticNode(0), ...Array.from({ length: ringCount }, (_, index) => syntheticNode(index + 1))];
}

function mountRing(ringCount: number) {
  const nodes = neighborhoodWithRing(ringCount);
  return render(
    <CanvasMapClient
      nodes={nodes}
      edges={[]}
      focusEntityId={FOCUS}
      scopeEntityId=""
      savedPositions={{}}
      version={0}
      graphQuery={{ focusEntityId: FOCUS }}
    />,
  );
}

describe("CanvasMapClient keyboard Arrange, axe, scale, and export", () => {
  it("is axe-clean for inspectable Map controls including Arrange and export", async () => {
    const { container } = render(
      <main>
        <InspectorSelectionProvider>
          <CanvasMapClient
            nodes={NODES}
            edges={EDGES}
            focusEntityId={FOCUS}
            scopeEntityId=""
            savedPositions={{}}
            version={0}
            graphQuery={{ focusEntityId: FOCUS }}
          />
        </InspectorSelectionProvider>
      </main>,
    );
    expect(screen.getByTestId("canvas-arrange-toggle")).toBeTruthy();
    expect(screen.getByTestId("canvas-export-text")).toBeTruthy();
    expect(screen.getByTestId("canvas-export-svg")).toBeTruthy();
    expect((await axe.run(container)).violations).toEqual([]);
  });

  it("nudges an Arrange node selected by focus without pointerDown", async () => {
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
    const node = screen.getByTestId(`canvas-node-${FOCUS}`);
    fireEvent.focus(node);
    fireEvent.keyDown(node, { key: "ArrowRight" });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const calls = fetchSpy.mock.calls.map(([url, init]) => fetchMeta(String(url), init));
    expect(calls.every((call) => call.href === "/api/canvas/workspace" && call.method === "POST")).toBe(
      true,
    );
    expect(putBody(fetchSpy.mock.calls[0][1]).positions?.[FOCUS]).toEqual(
      expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) }),
    );
  });

  it("nudges an Arrange node selected by Enter without pointerDown", async () => {
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
    const node = screen.getByTestId(`canvas-node-${FOCUS}`);
    fireEvent.keyDown(node, { key: "Enter" });
    fireEvent.keyDown(node, { key: "ArrowLeft" });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const calls = fetchSpy.mock.calls.map(([url, init]) => fetchMeta(String(url), init));
    expect(calls.every((call) => call.href === "/api/canvas/workspace" && call.method === "POST")).toBe(
      true,
    );
  });

  it("keeps the visual map and both export actions at 35 ring nodes", () => {
    mountRing(35);
    expect(screen.getByTestId("canvas-map")).toBeTruthy();
    expect(screen.queryByTestId("canvas-map-fallback")).toBeNull();
    expect(screen.getByTestId("canvas-export-text")).toBeTruthy();
    expect(screen.getByTestId("canvas-export-svg")).toBeTruthy();
  });

  it("omits the visual map and SVG export at 36 ring nodes", () => {
    mountRing(36);
    expect(screen.getByTestId("canvas-map-fallback")).toBeTruthy();
    expect(screen.queryByTestId("canvas-map")).toBeNull();
    expect(screen.getByTestId("canvas-export-text")).toBeTruthy();
    expect(screen.queryByTestId("canvas-export-svg")).toBeNull();
  });

  it("downloads neighborhood text without throwing", () => {
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-neighborhood");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    mount();
    expect(screen.getByTestId("canvas-export-svg")).toBeTruthy();
    expect(() => fireEvent.click(screen.getByTestId("canvas-export-text"))).not.toThrow();
    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
  });
});
