import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, Ref } from "react";
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

function activateKey(event: ReactKeyboardEvent<SVGElement>): boolean {
  return event.key === "Enter" || event.key === " ";
}

export function GraphMap({
  nodes,
  edges,
  focusEntityId = "",
  savedPositions = {},
  arrange = false,
  relationshipEdit = false,
  selectedEntityId,
  selectedEdgeId,
  svgRef,
  onNodePointerDown,
  onSvgPointerMove,
  onSvgPointerUp,
  onNodeSelect,
  onEdgeSelect,
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  focusEntityId?: string;
  savedPositions?: SavedPositions;
  arrange?: boolean;
  relationshipEdit?: boolean;
  selectedEntityId?: string | null;
  selectedEdgeId?: string | null;
  svgRef?: Ref<SVGSVGElement>;
  onNodePointerDown?: (entityId: string, event: ReactPointerEvent<SVGElement>) => void;
  onSvgPointerMove?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onSvgPointerUp?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onNodeSelect?: (entityId: string) => void;
  onEdgeSelect?: (edgeId: string) => void;
}) {
  const positions = overlayLayout(nodes, focusEntityId, savedPositions);
  const drag = arrange && !relationshipEdit;
  const pickNodes = arrange || relationshipEdit;
  return (
    <div data-testid="canvas-map" role="region" aria-label="Neighborhood map">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${CANVAS_MAP_WIDTH} ${CANVAS_MAP_HEIGHT}`}
        className="h-auto w-full rounded-lg border border-border bg-surface"
        role="presentation"
        onPointerMove={drag ? onSvgPointerMove : undefined}
        onPointerUp={drag ? onSvgPointerUp : undefined}
        onPointerCancel={drag ? onSvgPointerUp : undefined}
      >
        {edges.map((edge) => {
          if (edge.to_entity_id === null) return null;
          const from = positions.get(edge.from_entity_id);
          const to = positions.get(edge.to_entity_id);
          if (!from || !to) return null;
          if (from.x === to.x && from.y === to.y) return null;
          const editable = relationshipEdit && edge.edge_kind === "relationship";
          const selected = editable && edge.edge_id === selectedEdgeId;
          return (
            <g
              key={edge.edge_id}
              data-testid={`canvas-edge-${edge.edge_id}`}
              data-edge-kind={edge.edge_kind}
              tabIndex={editable ? 0 : undefined}
              role={editable ? "button" : undefined}
              aria-label={
                editable ? `${edge.type} relationship from ${edge.from_entity_id} to ${edge.to_entity_id}` : undefined
              }
              aria-pressed={editable ? selected : undefined}
              onClick={
                editable
                  ? () => {
                      onEdgeSelect?.(edge.edge_id);
                    }
                  : undefined
              }
              onKeyDown={
                editable
                  ? (event) => {
                      if (!activateKey(event)) return;
                      event.preventDefault();
                      onEdgeSelect?.(edge.edge_id);
                    }
                  : undefined
              }
              style={editable ? { cursor: "pointer" } : undefined}
            >
              {editable ? (
                <line
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke="transparent"
                  strokeWidth={12}
                />
              ) : null}
              <line
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className={selected ? "stroke-moss-green" : "stroke-moss-slate/30"}
                strokeWidth={selected ? 3 : 1.5}
              />
            </g>
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
                strokeWidth={selected && pickNodes ? 3 : 2}
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
          if (pickNodes) {
            return (
              <g
                key={node.entity_id}
                data-testid={`canvas-node-${node.entity_id}`}
                data-entity-id={node.entity_id}
                tabIndex={0}
                aria-label={node.display_label}
                style={{ cursor: drag ? "grab" : "pointer", touchAction: drag ? "none" : undefined }}
                onPointerDown={
                  drag
                    ? (event) => onNodePointerDown?.(node.entity_id, event)
                    : undefined
                }
                onClick={
                  relationshipEdit
                    ? () => {
                        onNodeSelect?.(node.entity_id);
                      }
                    : undefined
                }
                onKeyDown={
                  relationshipEdit
                    ? (event) => {
                        if (!activateKey(event)) return;
                        event.preventDefault();
                        onNodeSelect?.(node.entity_id);
                      }
                    : undefined
                }
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
