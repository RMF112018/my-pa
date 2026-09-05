import { peopleEntity } from "@/lib/routes/people";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

const WIDTH = 800;
const HEIGHT = 560;
const CX = WIDTH / 2;
const CY = HEIGHT / 2;
const RADIUS = 180;
const NODE_R = 16;
const FOCUS_R = 22;

type Point = { readonly x: number; readonly y: number };

function layout(nodes: readonly GraphNode[], focusEntityId: string): Map<string, Point> {
  const ordered = [...nodes].sort((a, b) => a.entity_id.localeCompare(b.entity_id));
  const positions = new Map<string, Point>();
  if (ordered.length === 0) return positions;
  if (ordered.length === 1) {
    positions.set(ordered[0].entity_id, { x: CX, y: CY });
    return positions;
  }

  const focus = focusEntityId ? ordered.find((node) => node.entity_id === focusEntityId) : undefined;
  const ring = focus ? ordered.filter((node) => node.entity_id !== focus.entity_id) : ordered;
  if (focus) {
    positions.set(focus.entity_id, { x: CX, y: CY });
  }
  const count = ring.length;
  ring.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / count - Math.PI / 2;
    positions.set(node.entity_id, {
      x: CX + RADIUS * Math.cos(angle),
      y: CY + RADIUS * Math.sin(angle),
    });
  });
  return positions;
}

function shortLabel(label: string): string {
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

export function GraphMap({
  nodes,
  edges,
  focusEntityId = "",
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  focusEntityId?: string;
}) {
  const positions = layout(nodes, focusEntityId);
  return (
    <div data-testid="canvas-map" role="region" aria-label="Neighborhood map">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full rounded-lg border border-border bg-surface"
        role="presentation"
      >
        {edges.map((edge) => {
          if (edge.to_entity_id === null) return null;
          const from = positions.get(edge.from_entity_id);
          const to = positions.get(edge.to_entity_id);
          if (!from || !to) return null;
          if (from.x === to.x && from.y === to.y) return null;
          return (
            <line
              key={edge.edge_id}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              className="stroke-moss-slate/30"
              strokeWidth={1.5}
            />
          );
        })}
        {nodes.map((node) => {
          const point = positions.get(node.entity_id);
          if (!point) return null;
          const focused = node.entity_id === focusEntityId;
          const r = focused ? FOCUS_R : NODE_R;
          return (
            <a
              key={node.entity_id}
              href={peopleEntity(node.entity_id)}
              aria-label={node.display_label}
              className="outline-none focus-visible:[&>circle]:stroke-moss-gold"
            >
              <circle
                cx={point.x}
                cy={point.y}
                r={r}
                className={focused ? "fill-moss-green/15 stroke-moss-green" : "fill-surface stroke-moss-green"}
                strokeWidth={2}
              />
              <text
                x={point.x}
                y={point.y + r + 16}
                textAnchor="middle"
                className="fill-moss-slate"
                fontSize={11}
              >
                {shortLabel(node.display_label)}
              </text>
            </a>
          );
        })}
      </svg>
    </div>
  );
}
