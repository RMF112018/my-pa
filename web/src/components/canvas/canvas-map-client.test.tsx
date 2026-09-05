import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    stubMapRect();
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      void url;
      void init;
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
      return new Response(
        JSON.stringify({
          version: (body.expected_version ?? 0) + 1,
          updated_at: "2026-09-05T17:00:00.000Z",
          positions: body.positions ?? {},
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
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
      new Response(
        JSON.stringify({
          version: 1,
          updated_at: "2026-09-05T17:00:00.000Z",
          positions: firstPayload.positions ?? {},
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
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
});
