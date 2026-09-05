import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { GraphMap } from "./graph-map";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

const FOCUS = "ent_aaaaaaaa11111111";
const NEIGHBOR = "ent_bbbbbbbb22222222";
const REL_EDGE = "erel_aaaaaaaa11111111";
const ASN_EDGE = "asn_aaaaaaaa11111111";

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

function relationshipEdge(isCurrent: boolean | null): GraphEdge {
  return {
    edge_kind: "relationship",
    edge_id: REL_EDGE,
    type: "works_for",
    from_entity_id: FOCUS,
    to_entity_id: NEIGHBOR,
    from_projection_id: `gprj_${FOCUS}`,
    to_projection_id: `gprj_${NEIGHBOR}`,
    scope_entity_id: null,
    is_current: isCurrent,
    state: "active",
    version: 1,
  };
}

const ASSIGNMENT_EDGE: GraphEdge = {
  edge_kind: "assignment",
  edge_id: ASN_EDGE,
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

function visibleLine(edgeId: string): SVGLineElement {
  const group = screen.getByTestId(`canvas-edge-${edgeId}`);
  const lines = [...group.querySelectorAll("line")];
  const visible = lines.find((line) => line.getAttribute("stroke") !== "transparent");
  expect(visible).not.toBeUndefined();
  return visible as SVGLineElement;
}

afterEach(() => {
  cleanup();
});

describe("GraphMap edge currentness", () => {
  it("marks a server-current edge as current with a solid stronger stroke", () => {
    render(<GraphMap nodes={NODES} edges={[relationshipEdge(true)]} focusEntityId={FOCUS} />);
    const group = screen.getByTestId(`canvas-edge-${REL_EDGE}`);
    expect(group).toHaveAttribute("data-is-current", "true");
    expect(group.textContent).not.toMatch(/current/i);
    expect(group.textContent).not.toMatch(/historical/i);
    const line = visibleLine(REL_EDGE);
    expect(line.getAttribute("stroke-dasharray") ?? line.getAttribute("strokeDasharray")).toBeFalsy();
    expect(line.getAttribute("stroke-width")).toBe("2.5");
  });

  it("marks a server-historical edge as not current with a dashed muted stroke", () => {
    render(<GraphMap nodes={NODES} edges={[relationshipEdge(false)]} focusEntityId={FOCUS} />);
    const group = screen.getByTestId(`canvas-edge-${REL_EDGE}`);
    expect(group).toHaveAttribute("data-is-current", "false");
    expect(group.textContent).not.toMatch(/current/i);
    expect(group.textContent).not.toMatch(/historical/i);
    const line = visibleLine(REL_EDGE);
    expect(line.getAttribute("stroke-dasharray") ?? line.getAttribute("strokeDasharray")).toBe("6 4");
  });

  it("leaves unspecified when is_current is null and does not label current or historical", () => {
    render(<GraphMap nodes={NODES} edges={[relationshipEdge(null)]} focusEntityId={FOCUS} />);
    const group = screen.getByTestId(`canvas-edge-${REL_EDGE}`);
    expect(group).toHaveAttribute("data-is-current", "unspecified");
    expect(group.textContent).not.toMatch(/current/i);
    expect(group.textContent).not.toMatch(/historical/i);
    const line = visibleLine(REL_EDGE);
    expect(line.getAttribute("stroke-dasharray") ?? line.getAttribute("strokeDasharray")).toBeFalsy();
    expect(line.getAttribute("stroke-width")).toBe("1.5");
  });

  it("does not invent node currentness or consult the browser clock", () => {
    render(<GraphMap nodes={NODES} edges={[relationshipEdge(true)]} focusEntityId={FOCUS} />);
    expect(screen.getByRole("link", { name: "Pat Synthetic" })).not.toHaveAttribute("data-is-current");
    const source = readFileSync("src/components/canvas/graph-map.tsx", "utf8");
    expect(source).not.toMatch(/Date\.now/);
  });
});

describe("GraphMap default People links", () => {
  it("wraps nodes in People links when inspect callbacks are omitted", () => {
    render(<GraphMap nodes={NODES} edges={[relationshipEdge(null)]} focusEntityId={FOCUS} />);
    expect(screen.getByRole("link", { name: "Pat Synthetic" })).toHaveAttribute(
      "href",
      `/people/${FOCUS}`,
    );
    expect(screen.queryByTestId(`canvas-node-${FOCUS}`)).toBeNull();
  });
});

describe("GraphMap inspect-selection API", () => {
  it("makes default nodes inspect-selectable and drops the People wrapper", () => {
    const onInspectNode = vi.fn();
    render(
      <GraphMap
        nodes={NODES}
        edges={[relationshipEdge(null)]}
        focusEntityId={FOCUS}
        onInspectNode={onInspectNode}
      />,
    );
    expect(screen.queryByRole("link", { name: "Pat Synthetic" })).toBeNull();
    const node = screen.getByTestId(`canvas-node-${FOCUS}`);
    fireEvent.click(node);
    expect(onInspectNode).toHaveBeenCalledWith(FOCUS);
    fireEvent.keyDown(node, { key: "Enter" });
    fireEvent.keyDown(node, { key: " " });
    expect(onInspectNode).toHaveBeenCalledTimes(3);
  });

  it("calls onInspectNode from Arrange pointer-down", () => {
    const onInspectNode = vi.fn();
    const onNodePointerDown = vi.fn();
    render(
      <GraphMap
        nodes={NODES}
        edges={[relationshipEdge(null)]}
        focusEntityId={FOCUS}
        arrange
        onNodePointerDown={onNodePointerDown}
        onInspectNode={onInspectNode}
      />,
    );
    fireEvent.pointerDown(screen.getByTestId(`canvas-node-${FOCUS}`), { pointerId: 1 });
    expect(onNodePointerDown).toHaveBeenCalledWith(FOCUS, expect.anything());
    expect(onInspectNode).toHaveBeenCalledWith(FOCUS);
  });

  it("calls onNodeSelect and onInspectNode together in relationship-edit", () => {
    const onInspectNode = vi.fn();
    const onNodeSelect = vi.fn();
    render(
      <GraphMap
        nodes={NODES}
        edges={[relationshipEdge(null)]}
        focusEntityId={FOCUS}
        relationshipEdit
        onNodeSelect={onNodeSelect}
        onInspectNode={onInspectNode}
      />,
    );
    fireEvent.click(screen.getByTestId(`canvas-node-${NEIGHBOR}`));
    expect(onNodeSelect).toHaveBeenCalledWith(NEIGHBOR);
    expect(onInspectNode).toHaveBeenCalledWith(NEIGHBOR);
  });

  it("lets assignment and relationship edges be inspected outside relationship-edit", () => {
    const onInspectEdge = vi.fn();
    render(
      <GraphMap
        nodes={NODES}
        edges={[relationshipEdge(null), ASSIGNMENT_EDGE]}
        focusEntityId={FOCUS}
        onInspectEdge={onInspectEdge}
      />,
    );
    fireEvent.click(screen.getByTestId(`canvas-edge-${ASN_EDGE}`));
    fireEvent.click(screen.getByTestId(`canvas-edge-${REL_EDGE}`));
    expect(onInspectEdge.mock.calls.map((call) => call[0])).toEqual([ASN_EDGE, REL_EDGE]);
  });

  it("calls onEdgeSelect and onInspectEdge together for relationship edges", () => {
    const onInspectEdge = vi.fn();
    const onEdgeSelect = vi.fn();
    render(
      <GraphMap
        nodes={NODES}
        edges={[relationshipEdge(null), ASSIGNMENT_EDGE]}
        focusEntityId={FOCUS}
        relationshipEdit
        onEdgeSelect={onEdgeSelect}
        onInspectEdge={onInspectEdge}
      />,
    );
    fireEvent.click(screen.getByTestId(`canvas-edge-${REL_EDGE}`));
    expect(onEdgeSelect).toHaveBeenCalledWith(REL_EDGE);
    expect(onInspectEdge).toHaveBeenCalledWith(REL_EDGE);
    onEdgeSelect.mockClear();
    onInspectEdge.mockClear();
    fireEvent.click(screen.getByTestId(`canvas-edge-${ASN_EDGE}`));
    expect(onEdgeSelect).not.toHaveBeenCalled();
    expect(onInspectEdge).toHaveBeenCalledWith(ASN_EDGE);
  });

  it("highlights inspectEntityId and inspectEdgeId without relationship-edit", () => {
    render(
      <GraphMap
        nodes={NODES}
        edges={[relationshipEdge(null)]}
        focusEntityId={FOCUS}
        onInspectNode={vi.fn()}
        onInspectEdge={vi.fn()}
        inspectEntityId={NEIGHBOR}
        inspectEdgeId={REL_EDGE}
      />,
    );
    const circle = screen.getByTestId(`canvas-node-${NEIGHBOR}`).querySelector("circle");
    expect(circle).toHaveAttribute("stroke-width", "3");
    expect(visibleLine(REL_EDGE).getAttribute("stroke-width")).toBe("3");
  });
});
