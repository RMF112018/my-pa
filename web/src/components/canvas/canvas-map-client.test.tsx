import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CanvasMapClient } from "./canvas-map-client";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

const FOCUS = "ent_aaaaaaaa11111111";
const NEIGHBOR = "ent_bbbbbbbb22222222";

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

const EDGES: readonly GraphEdge[] = [
  {
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
  },
];

function mount() {
  return render(
    <CanvasMapClient
      nodes={NODES}
      edges={EDGES}
      focusEntityId={FOCUS}
      scopeEntityId=""
      savedPositions={{}}
      version={0}
    />,
  );
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
    expect(screen.getByRole("link", { name: "Pat Synthetic" })).toHaveAttribute(
      "href",
      `/people/${FOCUS}`,
    );
  });

  it("disables People links while arranging", () => {
    mount();
    fireEvent.click(screen.getByTestId("canvas-arrange-toggle"));
    expect(screen.getByTestId("canvas-arrange-toggle")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("link", { name: "Pat Synthetic" })).toBeNull();
    expect(screen.getByTestId(`canvas-node-${FOCUS}`)).toBeTruthy();
  });

  it("keeps local positions and shows a truthful conflict", async () => {
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
    const fetchSpy = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => {
      return new Response(
        JSON.stringify({
          error: {
            errorClass: "conflict",
            code: "conflict",
            message: "stale expected_version",
          },
        }),
        { status: 409, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchSpy);
    mount();
    fireEvent.click(screen.getByTestId("canvas-arrange-toggle"));
    const node = screen.getByTestId(`canvas-node-${FOCUS}`);
    fireEvent.pointerDown(node, { pointerId: 1, clientX: 400, clientY: 280 });
    const svg = screen.getByTestId("canvas-map").querySelector("svg");
    expect(svg).not.toBeNull();
    fireEvent.pointerMove(svg!, { pointerId: 1, clientX: 120, clientY: 80 });
    fireEvent.pointerUp(svg!, { pointerId: 1, clientX: 120, clientY: 80 });
    expect(await screen.findByTestId("canvas-workspace-conflict")).toHaveTextContent(
      /saved layout version changed/i,
    );
    const moved = screen.getByTestId("canvas-map").querySelector(`circle[cx="120"][cy="80"]`);
    expect(moved).not.toBeNull();
    expect(JSON.parse(String(fetchSpy.mock.calls[0]?.[1]?.body ?? "{}"))).toMatchObject({
      focus_entity_id: FOCUS,
      expected_version: 0,
    });
  });
});
