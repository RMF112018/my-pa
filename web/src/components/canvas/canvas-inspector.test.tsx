import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import type { ReactNode } from "react";
import { CanvasInspector } from "./canvas-inspector";
import {
  InspectorSelectionProvider,
  useInspectorSelection,
} from "@/components/shell/inspector-selection";
import { IDENTITY_HISTORY_ENTRY } from "@/lib/api/decode/capabilities/_entity-fixtures";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

const FOCUS = "ent_aaaaaaaa11111111";
const NEIGHBOR = "ent_bbbbbbbb22222222";
const CURSOR = "cur_aaaaaaaa11111111";

const NODE: GraphNode = {
  entity_id: FOCUS,
  projection_id: `gprj_${FOCUS}`,
  entity_type: "person",
  display_label: "Pat Synthetic",
  status: "active",
  superseded_by_entity_id: null,
};

const NEIGHBOR_NODE: GraphNode = {
  entity_id: NEIGHBOR,
  projection_id: `gprj_${NEIGHBOR}`,
  entity_type: "person",
  display_label: "Acme Synthetic",
  status: "active",
  superseded_by_entity_id: null,
};

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
  is_current: true,
  status: "active",
  version: 2,
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function fetchMeta(url: string, init?: RequestInit) {
  return { href: String(url), method: String(init?.method ?? "GET") };
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
        effective_from: "2026-03-01T00:00:00Z",
        effective_to: "2026-09-01T00:00:00Z",
        version: 1,
        ...overrides,
      },
    ],
  };
}

function PublishNode({ node }: { node: GraphNode }) {
  const { setSelection } = useInspectorSelection();
  return (
    <button type="button" onClick={() => setSelection({ kind: "node", node })}>
      publish-node
    </button>
  );
}

function PublishEdge({
  edge,
  from,
  to,
}: {
  edge: GraphEdge;
  from?: GraphNode;
  to?: GraphNode;
}) {
  const { setSelection } = useInspectorSelection();
  return (
    <button type="button" onClick={() => setSelection({ kind: "edge", edge, from, to })}>
      publish-edge
    </button>
  );
}

function renderInspector(extra?: ReactNode) {
  return render(
    <InspectorSelectionProvider>
      {extra}
      <CanvasInspector />
    </InspectorSelectionProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("CanvasInspector", () => {
  it("keeps the honest empty copy when nothing is selected", () => {
    render(<CanvasInspector />);
    expect(screen.getByTestId("inspector-empty")).toHaveTextContent(
      /Select supported evidence to inspect source, freshness, provenance, and limitations/,
    );
    expect(screen.getByTestId("inspector-empty")).toHaveTextContent(
      /Nothing sensitive is persisted here/,
    );
  });

  it("renders product-owned node fields and a People link", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href.startsWith(`/api/people/${FOCUS}/identity-history`)) {
        return jsonResponse(identityHistoryBody());
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    renderInspector(<PublishNode node={NODE} />);
    fireEvent.click(screen.getByRole("button", { name: "publish-node" }));
    const panel = await screen.findByTestId("inspector-node");
    expect(panel).toHaveTextContent("Pat Synthetic");
    expect(panel).toHaveTextContent("person");
    expect(panel).toHaveTextContent("active");
    expect(panel).toHaveTextContent("none");
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
    expect(screen.getByTestId("inspector-changes")).not.toHaveTextContent("operation_kind");
  });

  it("fails closed when identity history cannot be decoded", async () => {
    const fetchSpy = vi.fn(async () => jsonResponse({ entity_id: FOCUS }));
    vi.stubGlobal("fetch", fetchSpy);
    renderInspector(<PublishNode node={NODE} />);
    fireEvent.click(screen.getByRole("button", { name: "publish-node" }));
    expect(await screen.findByTestId("inspector-changes")).toHaveTextContent(
      /Identity history could not be read/,
    );
    expect(screen.getByTestId("inspector-changes")).not.toHaveTextContent(
      IDENTITY_HISTORY_ENTRY.history_id,
    );
    expect(screen.queryByTestId("inspector-changes-continue")).toBeNull();
  });

  it("fails closed when identity history GET is not ok", async () => {
    const fetchSpy = vi.fn(async () =>
      jsonResponse(
        { error: { errorClass: "unavailable", code: "unavailable", message: "down" } },
        503,
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);
    renderInspector(<PublishNode node={NODE} />);
    fireEvent.click(screen.getByRole("button", { name: "publish-node" }));
    expect(await screen.findByTestId("inspector-changes")).toHaveTextContent(
      /Identity history could not be read/,
    );
  });

  it("continues identity history with after and does not invent rows", async () => {
    const second = {
      ...IDENTITY_HISTORY_ENTRY,
      history_id: "emut_bbbbbbbb22222222",
      operation: "entities.update",
      occurred_at: "2026-08-10T12:00:00.000Z",
    };
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method !== "GET") throw new Error(`unexpected ${method} ${href}`);
      if (href === `/api/people/${FOCUS}/identity-history`) {
        return jsonResponse(
          identityHistoryBody({
            is_truncated: true,
            next_cursor: CURSOR,
          }),
        );
      }
      if (href === `/api/people/${FOCUS}/identity-history?after=${CURSOR}`) {
        return jsonResponse(
          identityHistoryBody({
            entries: [second],
            is_truncated: false,
            next_cursor: null,
          }),
        );
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    renderInspector(<PublishNode node={NODE} />);
    fireEvent.click(screen.getByRole("button", { name: "publish-node" }));
    expect(await screen.findByTestId("inspector-changes")).toHaveTextContent(/truncated/i);
    expect(screen.getByTestId("inspector-changes")).toHaveTextContent(
      IDENTITY_HISTORY_ENTRY.history_id,
    );
    fireEvent.click(screen.getByTestId("inspector-changes-continue"));
    await waitFor(() => {
      expect(screen.getByTestId("inspector-changes")).toHaveTextContent(second.history_id);
    });
    expect(screen.getByTestId("inspector-changes")).toHaveTextContent("entities.update");
    expect(screen.queryByTestId("inspector-changes-continue")).toBeNull();
    const hrefs = fetchSpy.mock.calls.map(([url, init]) => fetchMeta(String(url), init).href);
    expect(hrefs).toContain(`/api/people/${FOCUS}/identity-history?after=${CURSOR}`);
  });

  it("renders relationship edge fields and a relationships window when the row is found", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      const { href, method } = fetchMeta(String(url), init);
      if (method === "GET" && href === `/api/people/${FOCUS}/relationships`) {
        return jsonResponse(relationshipsBody());
      }
      throw new Error(`unexpected ${method} ${href}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    renderInspector(
      <PublishEdge edge={RELATIONSHIP_EDGE} from={NODE} to={NEIGHBOR_NODE} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "publish-edge" }));
    const panel = await screen.findByTestId("inspector-edge");
    expect(panel).toHaveTextContent("works_for");
    expect(panel).toHaveTextContent("relationship");
    expect(panel).toHaveTextContent("state");
    expect(panel).toHaveTextContent("active");
    expect(screen.getByTestId("inspector-field-is_current").querySelector("dd")).toHaveTextContent(
      "unspecified",
    );
    expect(panel).toHaveTextContent("1");
    expect(panel).toHaveTextContent(FOCUS);
    expect(panel).toHaveTextContent(NEIGHBOR);
    await waitFor(() => {
      expect(panel).toHaveTextContent("2026-03-01T00:00:00Z");
    });
    expect(panel).toHaveTextContent("2026-09-01T00:00:00Z");
    expect(panel).not.toHaveTextContent("evidence_refs");
  });

  it("omits the effective window when the relationships read fails", async () => {
    const fetchSpy = vi.fn(async () =>
      jsonResponse(
        { error: { errorClass: "unavailable", code: "unavailable", message: "down" } },
        503,
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);
    renderInspector(<PublishEdge edge={RELATIONSHIP_EDGE} />);
    fireEvent.click(screen.getByRole("button", { name: "publish-edge" }));
    const panel = await screen.findByTestId("inspector-edge");
    expect(panel).toHaveTextContent("works_for");
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(panel).not.toHaveTextContent("effective_from");
    expect(panel).not.toHaveTextContent("effective_to");
  });

  it("renders assignment status and does not fetch relationships", async () => {
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      throw new Error(`unexpected ${fetchMeta(String(url), init).method} ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    renderInspector(<PublishEdge edge={ASSIGNMENT_EDGE} />);
    fireEvent.click(screen.getByRole("button", { name: "publish-edge" }));
    const panel = await screen.findByTestId("inspector-edge");
    expect(panel).toHaveTextContent("assignment");
    expect(panel).toHaveTextContent("status");
    expect(screen.getByTestId("inspector-field-is_current").querySelector("dd")).toHaveTextContent(
      "current",
    );
    expect(screen.getByTestId("inspector-field-is_current").querySelector("dd")).not.toHaveTextContent(
      "unspecified",
    );
    expect(panel).not.toHaveTextContent("effective_from");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("renders not current when is_current is false", () => {
    renderInspector(
      <PublishEdge edge={{ ...ASSIGNMENT_EDGE, is_current: false }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "publish-edge" }));
    expect(screen.getByTestId("inspector-field-is_current").querySelector("dd")).toHaveTextContent(
      "not current",
    );
  });

  it("does not compute currentness from the clock", () => {
    const source = readFileSync("src/components/canvas/canvas-inspector.tsx", "utf8");
    expect(source).not.toMatch(/Date\.now/);
    expect(source).not.toMatch(/evidence_refs/);
  });
});
