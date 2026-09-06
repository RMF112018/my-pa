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
const OPERABLE_NODE_FOCUS = "outline-none focus-visible:[&>circle]:stroke-moss-gold";
const OPERABLE_EDGE_FOCUS = "outline-none focus-visible:[&>line:last-of-type]:stroke-moss-gold";

function shortLabel(label: string): string {
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

function activateKey(event: ReactKeyboardEvent<SVGElement>): boolean {
  return event.key === "Enter" || event.key === " ";
}

function edgeCurrentness(isCurrent: boolean | null): "true" | "false" | "unspecified" {
  if (isCurrent === true) return "true";
  if (isCurrent === false) return "false";
  return "unspecified";
}

function edgeStrokeClass(isCurrent: boolean | null, selected: boolean): string {
  if (selected) return "stroke-moss-green";
  if (isCurrent === true) return "stroke-moss-slate/55";
  if (isCurrent === false) return "stroke-moss-slate/20";
  return "stroke-moss-slate/30";
}

function edgeStrokeWidth(isCurrent: boolean | null, selected: boolean): number {
  if (selected) return 3;
  if (isCurrent === true) return 2.5;
  return 1.5;
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
  inspectEntityId,
  inspectEdgeId,
  svgRef,
  onNodePointerDown,
  onSvgPointerMove,
  onSvgPointerUp,
  onNodeSelect,
  onArrangeSelect,
  onEdgeSelect,
  onInspectNode,
  onInspectEdge,
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  focusEntityId?: string;
  savedPositions?: SavedPositions;
  arrange?: boolean;
  relationshipEdit?: boolean;
  selectedEntityId?: string | null;
  selectedEdgeId?: string | null;
  inspectEntityId?: string | null;
  inspectEdgeId?: string | null;
  svgRef?: Ref<SVGSVGElement>;
  onNodePointerDown?: (entityId: string, event: ReactPointerEvent<SVGElement>) => void;
  onSvgPointerMove?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onSvgPointerUp?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onNodeSelect?: (entityId: string) => void;
  onArrangeSelect?: (entityId: string) => void;
  onEdgeSelect?: (edgeId: string) => void;
  onInspectNode?: (entityId: string) => void;
  onInspectEdge?: (edgeId: string) => void;
}) {
  const positions = overlayLayout(nodes, focusEntityId, savedPositions);
  const drag = arrange && !relationshipEdit;
  const pickNodes = arrange || relationshipEdit;
  const inspectNodes = Boolean(onInspectNode);
  const inspectEdges = Boolean(onInspectEdge);
  return (
    <div data-testid="canvas-map" role="region" aria-label="Neighborhood map">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${CANVAS_MAP_WIDTH} ${CANVAS_MAP_HEIGHT}`}
        className="h-auto w-full rounded-lg border border-border bg-surface"
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
          const interactive = editable || inspectEdges;
          const inspectSelected = inspectEdgeId != null && edge.edge_id === inspectEdgeId;
          const selected = (editable && edge.edge_id === selectedEdgeId) || inspectSelected;
          const currentness = edgeCurrentness(edge.is_current);
          return (
            <g
              key={edge.edge_id}
              data-testid={`canvas-edge-${edge.edge_id}`}
              data-edge-kind={edge.edge_kind}
              data-is-current={currentness}
              tabIndex={interactive ? 0 : undefined}
              role={interactive ? "button" : undefined}
              className={interactive ? OPERABLE_EDGE_FOCUS : undefined}
              aria-label={
                interactive
                  ? `${edge.type} ${edge.edge_kind} from ${edge.from_entity_id} to ${edge.to_entity_id}`
                  : undefined
              }
              aria-pressed={interactive ? selected : undefined}
              onClick={
                interactive
                  ? () => {
                      if (editable) onEdgeSelect?.(edge.edge_id);
                      onInspectEdge?.(edge.edge_id);
                    }
                  : undefined
              }
              onKeyDown={
                interactive
                  ? (event) => {
                      if (!activateKey(event)) return;
                      event.preventDefault();
                      if (editable) onEdgeSelect?.(edge.edge_id);
                      onInspectEdge?.(edge.edge_id);
                    }
                  : undefined
              }
              style={interactive ? { cursor: "pointer" } : undefined}
            >
              {interactive ? (
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
                className={edgeStrokeClass(edge.is_current, selected)}
                strokeWidth={edgeStrokeWidth(edge.is_current, selected)}
                strokeDasharray={edge.is_current === false ? "6 4" : undefined}
              />
            </g>
          );
        })}
        {nodes.map((node) => {
          const point = positions.get(node.entity_id);
          if (!point) return null;
          const focused = node.entity_id === focusEntityId;
          const inspectSelected = inspectEntityId != null && node.entity_id === inspectEntityId;
          const selected = node.entity_id === selectedEntityId || inspectSelected;
          const highlight = selected && (pickNodes || inspectNodes);
          const r = focused ? FOCUS_R : NODE_R;
          const mark = (
            <>
              <circle
                cx={point.x}
                cy={point.y}
                r={r}
                className={focused ? "fill-moss-green/15 stroke-moss-green" : "fill-surface stroke-moss-green"}
                strokeWidth={highlight ? 3 : 2}
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
                role="button"
                aria-label={node.display_label}
                className={OPERABLE_NODE_FOCUS}
                style={{ cursor: drag ? "grab" : "pointer", touchAction: drag ? "none" : undefined }}
                onFocus={
                  drag
                    ? () => {
                        onArrangeSelect?.(node.entity_id);
                        onInspectNode?.(node.entity_id);
                      }
                    : undefined
                }
                onPointerDown={
                  drag
                    ? (event) => {
                        onNodePointerDown?.(node.entity_id, event);
                        onInspectNode?.(node.entity_id);
                      }
                    : undefined
                }
                onClick={
                  relationshipEdit
                    ? () => {
                        onNodeSelect?.(node.entity_id);
                        onInspectNode?.(node.entity_id);
                      }
                    : undefined
                }
                onKeyDown={
                  drag || relationshipEdit
                    ? (event) => {
                        if (!activateKey(event)) return;
                        event.preventDefault();
                        if (drag) onArrangeSelect?.(node.entity_id);
                        if (relationshipEdit) onNodeSelect?.(node.entity_id);
                        onInspectNode?.(node.entity_id);
                      }
                    : undefined
                }
              >
                {mark}
              </g>
            );
          }
          if (inspectNodes) {
            return (
              <g
                key={node.entity_id}
                data-testid={`canvas-node-${node.entity_id}`}
                data-entity-id={node.entity_id}
                tabIndex={0}
                role="button"
                aria-label={node.display_label}
                aria-pressed={inspectSelected}
                className={OPERABLE_NODE_FOCUS}
                style={{ cursor: "pointer" }}
                onClick={() => onInspectNode?.(node.entity_id)}
                onKeyDown={(event) => {
                  if (!activateKey(event)) return;
                  event.preventDefault();
                  onInspectNode?.(node.entity_id);
                }}
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
              className={OPERABLE_NODE_FOCUS}
            >
              {mark}
            </a>
          );
        })}
      </svg>
    </div>
  );
}
