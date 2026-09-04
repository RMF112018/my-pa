import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  ASSIGNMENT_TYPES,
  ENTITY_STATUSES,
  ENTITY_TYPES,
  RELATIONSHIP_TYPES,
  requiredNullableBoolean,
  type EntityStatus,
  type EntityType,
} from "./_entity-read-helpers";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

const EDGE_KINDS = ["assignment", "relationship"] as const;
const EDGE_TYPES = [...ASSIGNMENT_TYPES, ...RELATIONSHIP_TYPES] as const;
const DIRECTED_STATES = ["active", "ended", "superseded"] as const;

export interface GraphNode {
  readonly entity_id: string;
  readonly projection_id: string;
  readonly entity_type: EntityType;
  readonly display_label: string;
  readonly status: EntityStatus;
  readonly superseded_by_entity_id: string | null;
}

export interface GraphEdge {
  readonly edge_kind: (typeof EDGE_KINDS)[number];
  readonly edge_id: string;
  readonly type: (typeof EDGE_TYPES)[number];
  readonly from_entity_id: string;
  readonly to_entity_id: string | null;
  readonly from_projection_id: string;
  readonly to_projection_id: string | null;
  readonly scope_entity_id: string | null;
  readonly is_current: boolean | null;
  readonly status?: (typeof DIRECTED_STATES)[number];
  readonly state?: (typeof DIRECTED_STATES)[number];
  readonly version: number;
}

export interface EntitiesGraphResult {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly next_cursor: string | null;
}

function decodeGraphNode(input: unknown): DecodeResult<GraphNode> {
  const known = pick(input, [
    "entity_id",
    "projection_id",
    "entity_type",
    "display_label",
    "status",
    "superseded_by_entity_id",
  ]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const projectionId = requiredString(known.value.projection_id);
  if (!projectionId.ok) return projectionId;
  const entityType = oneOf(known.value.entity_type, ENTITY_TYPES);
  if (!entityType.ok) return entityType;
  const label = requiredString(known.value.display_label);
  if (!label.ok) return label;
  const status = oneOf(known.value.status, ENTITY_STATUSES);
  if (!status.ok) return status;
  const superseded = requiredNullableString(known.value.superseded_by_entity_id);
  if (!superseded.ok) return superseded;
  return ok({
    entity_id: entityId.value,
    projection_id: projectionId.value,
    entity_type: entityType.value,
    display_label: label.value,
    status: status.value,
    superseded_by_entity_id: superseded.value,
  } satisfies GraphNode);
}

function decodeGraphEdge(input: unknown): DecodeResult<GraphEdge> {
  const known = pick(input, [
    "edge_kind",
    "edge_id",
    "type",
    "from_entity_id",
    "to_entity_id",
    "from_projection_id",
    "to_projection_id",
    "scope_entity_id",
    "is_current",
    "status",
    "state",
    "version",
  ]);
  if (!known.ok) return known;
  const kind = oneOf(known.value.edge_kind, EDGE_KINDS);
  if (!kind.ok) return kind;
  const edgeId = requiredString(known.value.edge_id);
  if (!edgeId.ok) return edgeId;
  const type = oneOf(known.value.type, EDGE_TYPES);
  if (!type.ok) return type;
  const fromEntity = requiredString(known.value.from_entity_id);
  if (!fromEntity.ok) return fromEntity;
  const toEntity = requiredNullableString(known.value.to_entity_id);
  if (!toEntity.ok) return toEntity;
  const fromProjection = requiredString(known.value.from_projection_id);
  if (!fromProjection.ok) return fromProjection;
  const toProjection = requiredNullableString(known.value.to_projection_id);
  if (!toProjection.ok) return toProjection;
  const scope = requiredNullableString(known.value.scope_entity_id);
  if (!scope.ok) return scope;
  const isCurrent = requiredNullableBoolean(known.value.is_current);
  if (!isCurrent.ok) return isCurrent;
  const version = known.value.version;
  if (typeof version !== "number" || !Number.isSafeInteger(version)) {
    return fail("a required field was not the expected type");
  }
  const shared = {
    edge_id: edgeId.value,
    type: type.value,
    from_entity_id: fromEntity.value,
    to_entity_id: toEntity.value,
    from_projection_id: fromProjection.value,
    to_projection_id: toProjection.value,
    scope_entity_id: scope.value,
    is_current: isCurrent.value,
    version,
  };
  if (kind.value === "assignment") {
    const status = oneOf(known.value.status, DIRECTED_STATES);
    if (!status.ok) return status;
    const edge: GraphEdge = {
      ...shared,
      edge_kind: "assignment",
      status: status.value,
    };
    return ok(edge);
  }
  const state = oneOf(known.value.state, DIRECTED_STATES);
  if (!state.ok) return state;
  const edge: GraphEdge = {
    ...shared,
    edge_kind: "relationship",
    state: state.value,
  };
  return ok(edge);
}

export const decodeEntitiesGraph: Decoder<EntitiesGraphResult> = (input) => {
  const known = pick(input, ["nodes", "edges", "next_cursor"]);
  if (!known.ok) return known;
  if (known.value.nodes === undefined || known.value.edges === undefined) {
    return fail("a required array was omitted");
  }
  const nodes = decodeItems(known.value.nodes, decodeGraphNode);
  if (!nodes.ok) return nodes;
  const edges = decodeItems(known.value.edges, decodeGraphEdge);
  if (!edges.ok) return edges;
  const nextCursor = requiredNullableString(known.value.next_cursor);
  if (!nextCursor.ok) return nextCursor;
  return ok({
    nodes: nodes.value,
    edges: edges.value,
    next_cursor: nextCursor.value,
  });
};
