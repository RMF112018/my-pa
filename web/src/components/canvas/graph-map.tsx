import type { PointerEvent as ReactPointerEvent, Ref } from "react";
import { peopleEntity } from "@/lib/routes/people";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";
import {
  CANVAS_MAP_HEIGHT,
  CANVAS_MAP_WIDTH,
  overlayLayout,
  type SavedPositions,
} from "@/lib/canvas/layout";

const NODE_R = 16;
const FOCUS_R = 22;

function shortLabel(label: string): string {
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

export function GraphMap({
  nodes,
  edges,
  focusEntityId = "",
  savedPositions = {},
  arrange = false,
  selectedEntityId,
  svgRef,
  onNodePointerDown,
  onSvgPointerMove,
  onSvgPointerUp,
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  focusEntityId?: string;
  savedPositions?: SavedPositions;
  arrange?: boolean;
  selectedEntityId?: string | null;
  svgRef?: Ref<SVGSVGElement>;
  onNodePointerDown?: (entityId: string, event: ReactPointerEvent<SVGElement>) => void;
  onSvgPointerMove?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onSvgPointerUp?: (event: ReactPointerEvent<SVGSVGElement>) => void;
}) {
  const positions = overlayLayout(nodes, focusEntityId, savedPositions);
  return (
    <div data-testid="canvas-map" role="region" aria-label="Neighborhood map">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${CANVAS_MAP_WIDTH} ${CANVAS_MAP_HEIGHT}`}
        className="h-auto w-full rounded-lg border border-border bg-surface"
        role="presentation"
        onPointerMove={arrange ? onSvgPointerMove : undefined}
        onPointerUp={arrange ? onSvgPointerUp : undefined}
        onPointerCancel={arrange ? onSvgPointerUp : undefined}
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
          const selected = node.entity_id === selectedEntityId;
          const r = focused ? FOCUS_R : NODE_R;
          const mark = (
            <>
              <circle
                cx={point.x}
                cy={point.y}
                r={r}
                className={focused ? "fill-moss-green/15 stroke-moss-green" : "fill-surface stroke-moss-green"}
                strokeWidth={selected && arrange ? 3 : 2}
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
            </>
          );
          if (arrange) {
            return (
              <g
                key={node.entity_id}
                data-testid={`canvas-node-${node.entity_id}`}
                data-entity-id={node.entity_id}
                tabIndex={0}
                aria-label={node.display_label}
                style={{ cursor: "grab", touchAction: "none" }}
                onPointerDown={(event) => onNodePointerDown?.(node.entity_id, event)}
              >
                {mark}
              </g>
            );
          }
          return (
            <a
              key={node.entity_id}
              href={peopleEntity(node.entity_id)}
              aria-label={node.display_label}
              className="outline-none focus-visible:[&>circle]:stroke-moss-gold"
            >
              {mark}
            </a>
          );
        })}
      </svg>
    </div>
  );
}
