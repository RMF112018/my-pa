"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { GraphMap } from "@/components/canvas/graph-map";
import { useInspectorSelection } from "@/components/shell/inspector-selection";
import { apiGet, apiPost } from "@/lib/api/client";
import { RELATIONSHIP_TYPES } from "@/lib/api/decode/capabilities/_entity-read-helpers";
import { decodeEntitiesGet } from "@/lib/api/decode/capabilities/entities.get";
import { decodeEntitiesGraph, type GraphEdge, type GraphNode } from "@/lib/api/decode/capabilities/entities.graph";
import { decodeEntitiesRelationships } from "@/lib/api/decode/capabilities/entities.relationships";
import type { CanvasPositions } from "@/lib/api/decode/capabilities/canvas.workspace.get";
import type { CanvasMapQuery } from "@/lib/routes/canvas";
import {
  CANVAS_MAP_HEIGHT,
  CANVAS_MAP_WIDTH,
  overlayLayout,
  type LayoutPoint,
  type SavedPositions,
} from "@/lib/canvas/layout";

const NUDGE = 4;
const SESSION = { hasSession: true } as const;

type WorkspacePutResponse = {
  readonly version?: unknown;
  readonly updated_at?: unknown;
  readonly positions?: unknown;
};

function isFinitePoint(value: unknown): value is LayoutPoint {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    Object.keys(record).length === 2 &&
    typeof record.x === "number" &&
    Number.isFinite(record.x) &&
    typeof record.y === "number" &&
    Number.isFinite(record.y)
  );
}

function readReceiptPositions(value: unknown): CanvasPositions | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const positions: Record<string, LayoutPoint> = {};
  for (const [entityId, point] of Object.entries(value)) {
    if (!isFinitePoint(point)) return null;
    positions[entityId] = { x: point.x, y: point.y };
  }
  return positions;
}

function leftoverDraft(
  current: Record<string, LayoutPoint>,
  sentSnapshot: Record<string, LayoutPoint>,
): Record<string, LayoutPoint> {
  const leftovers: Record<string, LayoutPoint> = {};
  for (const [entityId, point] of Object.entries(current)) {
    const sent = sentSnapshot[entityId];
    if (sent === undefined || sent.x !== point.x || sent.y !== point.y) {
      leftovers[entityId] = point;
    }
  }
  return leftovers;
}

function clientToSvg(svg: SVGSVGElement, clientX: number, clientY: number): LayoutPoint | null {
  const rect = svg.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return null;
  return {
    x: ((clientX - rect.left) / rect.width) * CANVAS_MAP_WIDTH,
    y: ((clientY - rect.top) / rect.height) * CANVAS_MAP_HEIGHT,
  };
}

function peopleGraphPath(query: CanvasMapQuery): string {
  const params = new URLSearchParams();
  if (query.focusEntityId) params.set("focusEntityId", query.focusEntityId);
  if (query.scopeEntityId) params.set("scopeEntityId", query.scopeEntityId);
  if (query.hops !== undefined) params.set("hops", String(query.hops));
  if (query.relationshipTypes !== undefined) {
    const joined =
      typeof query.relationshipTypes === "string"
        ? query.relationshipTypes
        : query.relationshipTypes.join(",");
    if (joined) params.set("relationshipTypes", joined);
  }
  if (query.asOf) params.set("asOf", query.asOf);
  if (query.pageSize !== undefined) params.set("pageSize", String(query.pageSize));
  if (query.after) params.set("after", query.after);
  const encoded = params.toString();
  return encoded.length === 0 ? "/api/people/graph" : `/api/people/graph?${encoded}`;
}

function graphQueryFromSeeds(focusEntityId: string, scopeEntityId: string): CanvasMapQuery {
  return {
    ...(focusEntityId ? { focusEntityId } : {}),
    ...(scopeEntityId ? { scopeEntityId } : {}),
  };
}

function nodeLabel(nodes: readonly GraphNode[], entityId: string): string {
  const match = nodes.find((node) => node.entity_id === entityId);
  return match?.display_label ?? entityId;
}

function splitRefs(raw: string): readonly string[] {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

async function readEntityVersion(entityId: string): Promise<number | null> {
  const response = await apiGet(SESSION, `/api/people/${encodeURIComponent(entityId)}`);
  if (!response.ok || response.data === null) return null;
  const decoded = decodeEntitiesGet(response.data);
  if (!decoded.ok) return null;
  return decoded.value.entity.version;
}

export function CanvasMapClient({
  nodes,
  edges,
  focusEntityId,
  scopeEntityId,
  savedPositions,
  version,
  graphQuery,
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  focusEntityId: string;
  scopeEntityId: string;
  savedPositions: SavedPositions;
  version: number;
  graphQuery?: CanvasMapQuery;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ entityId: string; pointerId: number } | null>(null);
  const draftRef = useRef<Record<string, LayoutPoint>>({});
  const storedRef = useRef<SavedPositions>(savedPositions);
  const expectedVersionRef = useRef(version);
  const savingRef = useRef(false);
  const relationshipEditRef = useRef(false);
  const seedQuery = graphQuery ?? graphQueryFromSeeds(focusEntityId, scopeEntityId);
  const [arrange, setArrange] = useState(false);
  const [relationshipEdit, setRelationshipEdit] = useState(false);
  const [mapNodes, setMapNodes] = useState(nodes);
  const [mapEdges, setMapEdges] = useState(edges);
  const [stored, setStored] = useState<SavedPositions>(savedPositions);
  const [draft, setDraft] = useState<Record<string, LayoutPoint>>({});
  const [, setExpectedVersion] = useState(version);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [fromEntityId, setFromEntityId] = useState("");
  const [toEntityId, setToEntityId] = useState("");
  const [relationshipType, setRelationshipType] = useState<(typeof RELATIONSHIP_TYPES)[number]>(
    RELATIONSHIP_TYPES[0],
  );
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveTo, setEffectiveTo] = useState("");
  const [clearFrom, setClearFrom] = useState(false);
  const [clearTo, setClearTo] = useState(false);
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [clearEvidence, setClearEvidence] = useState(false);
  const [endReason, setEndReason] = useState("");
  const [endNow, setEndNow] = useState(true);
  const [effectiveEnd, setEffectiveEnd] = useState("");
  const [conflict, setConflict] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [relationshipConflict, setRelationshipConflict] = useState<string | null>(null);
  const [relationshipSaveError, setRelationshipSaveError] = useState<string | null>(null);
  const [relationshipBusy, setRelationshipBusy] = useState(false);
  const [, setSaving] = useState(false);
  const { selection, setSelection } = useInspectorSelection();

  useEffect(() => {
    relationshipEditRef.current = relationshipEdit;
  }, [relationshipEdit]);

  useEffect(() => {
    if (!selectedEdgeId) return;
    const edge = mapEdges.find(
      (item) => item.edge_kind === "relationship" && item.edge_id === selectedEdgeId,
    );
    if (!edge) return;
    let cancelled = false;
    void (async () => {
      const response = await apiGet(
        SESSION,
        `/api/people/${encodeURIComponent(edge.from_entity_id)}/relationships`,
      );
      if (cancelled) return;
      if (!response.ok || response.data === null) return;
      const decoded = decodeEntitiesRelationships(response.data);
      if (!decoded.ok) return;
      const row = decoded.value.relationships.find(
        (item) => item.relationship_id === edge.edge_id,
      );
      if (!row) return;
      setEffectiveFrom((current) => (current === "" ? (row.effective_from ?? "") : current));
      setEffectiveTo((current) => (current === "" ? (row.effective_to ?? "") : current));
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedEdgeId, mapEdges]);

  useEffect(() => {
    if (relationshipEditRef.current) return;
    setMapNodes(nodes);
    setMapEdges(edges);
  }, [nodes, edges]);

  const overlay: SavedPositions = { ...stored, ...draft };
  const selectedEdge = mapEdges.find(
    (edge) => edge.edge_kind === "relationship" && edge.edge_id === selectedEdgeId,
  );
  const relationshipEdges = mapEdges.filter((edge) => edge.edge_kind === "relationship");

  async function persist(nextDraft: Record<string, LayoutPoint>) {
    if (Object.keys(nextDraft).length === 0 || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setSaveError(null);
    const sentSnapshot: Record<string, LayoutPoint> = { ...storedRef.current, ...nextDraft };
    const payload: Record<string, unknown> = {
      expected_version: expectedVersionRef.current,
      positions: sentSnapshot,
    };
    if (focusEntityId) payload.focus_entity_id = focusEntityId;
    if (scopeEntityId) payload.scope_entity_id = scopeEntityId;
    let replay = false;
    try {
      const response = await apiPost<WorkspacePutResponse>(
        SESSION,
        "/api/canvas/workspace",
        payload,
      );
      if (!response.ok) {
        if (response.errorClass === "conflict") {
          setConflict(
            "The saved layout version changed. Local positions are kept. Reload to get the current version.",
          );
          return;
        }
        setSaveError(response.error);
        return;
      }
      const data = response.data;
      const receiptVersion = data?.version;
      const receiptPositions = data ? readReceiptPositions(data.positions) : null;
      if (
        data === null ||
        typeof receiptVersion !== "number" ||
        !Number.isInteger(receiptVersion) ||
        receiptVersion < 0 ||
        typeof data.updated_at !== "string" ||
        receiptPositions === null
      ) {
        setSaveError("the save receipt was not usable");
        return;
      }
      storedRef.current = receiptPositions;
      expectedVersionRef.current = receiptVersion;
      setStored(receiptPositions);
      setExpectedVersion(receiptVersion);
      const leftovers = leftoverDraft(draftRef.current, sentSnapshot);
      draftRef.current = leftovers;
      setDraft(leftovers);
      setConflict(null);
      replay = Object.keys(leftovers).length > 0;
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
    if (replay) {
      void persist(draftRef.current);
    }
  }

  function applyMove(entityId: string, point: LayoutPoint) {
    const next = { ...draftRef.current, [entityId]: point };
    draftRef.current = next;
    setDraft(next);
  }

  function onNodePointerDown(entityId: string, event: ReactPointerEvent<SVGElement>) {
    event.preventDefault();
    setSelectedEntityId(entityId);
    setConflict(null);
    drag.current = { entityId, pointerId: event.pointerId };
    const svg = svgRef.current;
    if (svg && typeof svg.setPointerCapture === "function") {
      try {
        svg.setPointerCapture(event.pointerId);
      } catch {
        /* jsdom and some SVG hosts omit capture */
      }
    }
  }

  function onSvgPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const svg = svgRef.current;
    if (!svg) return;
    const point = clientToSvg(svg, event.clientX, event.clientY);
    if (!point) return;
    applyMove(active.entityId, point);
  }

  function onSvgPointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    drag.current = null;
    void persist(draftRef.current);
  }

  function onNudge(event: KeyboardEvent<HTMLDivElement>) {
    if (!arrange || !selectedEntityId) return;
    const delta =
      event.key === "ArrowLeft"
        ? { x: -NUDGE, y: 0 }
        : event.key === "ArrowRight"
          ? { x: NUDGE, y: 0 }
          : event.key === "ArrowUp"
            ? { x: 0, y: -NUDGE }
            : event.key === "ArrowDown"
              ? { x: 0, y: NUDGE }
              : null;
    if (!delta) return;
    event.preventDefault();
    const laidOut = overlayLayout(mapNodes, focusEntityId, overlay);
    const current = laidOut.get(selectedEntityId);
    if (!current) return;
    const next = { x: current.x + delta.x, y: current.y + delta.y };
    const nextDraft = { ...draftRef.current, [selectedEntityId]: next };
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    void persist(nextDraft);
  }

  function clearReviseForm() {
    setEffectiveFrom("");
    setEffectiveTo("");
    setClearFrom(false);
    setClearTo(false);
    setEvidenceRefs("");
    setClearEvidence(false);
  }

  function turnOnArrange() {
    setRelationshipEdit(false);
    clearReviseForm();
    setSelectedEdgeId(null);
    setArrange(true);
  }

  function turnOnRelationshipEdit() {
    setArrange(false);
    drag.current = null;
    setRelationshipEdit(true);
  }

  function publishInspectNode(entityId: string) {
    const node = mapNodes.find((item) => item.entity_id === entityId);
    if (!node) return;
    setSelection({ kind: "node", node });
  }

  function publishInspectEdge(edgeId: string) {
    const edge = mapEdges.find((item) => item.edge_id === edgeId);
    if (!edge) return;
    const from = mapNodes.find((item) => item.entity_id === edge.from_entity_id);
    const to =
      edge.to_entity_id === null
        ? undefined
        : mapNodes.find((item) => item.entity_id === edge.to_entity_id);
    setSelection({ kind: "edge", edge, ...(from ? { from } : {}), ...(to ? { to } : {}) });
  }

  function onNodeSelect(entityId: string) {
    if (!fromEntityId) {
      setFromEntityId(entityId);
      return;
    }
    if (!toEntityId) {
      setToEntityId(entityId);
      return;
    }
    setFromEntityId(entityId);
    setToEntityId("");
  }

  function onEdgeSelect(edgeId: string) {
    const edge = mapEdges.find((item) => item.edge_id === edgeId);
    if (!edge || edge.edge_kind !== "relationship") return;
    clearReviseForm();
    setSelectedEdgeId(edge.edge_id);
    setRelationshipConflict(null);
    setRelationshipSaveError(null);
    publishInspectEdge(edge.edge_id);
  }

  async function reloadGraph(): Promise<boolean> {
    const response = await apiGet(SESSION, peopleGraphPath(seedQuery));
    if (!response.ok || response.data === null) {
      setRelationshipSaveError(response.error ?? "the neighborhood could not be reloaded");
      return false;
    }
    const decoded = decodeEntitiesGraph(response.data);
    if (!decoded.ok) {
      setRelationshipSaveError("the reloaded neighborhood was not usable");
      return false;
    }
    setMapNodes(decoded.value.nodes);
    setMapEdges(decoded.value.edges);
    return true;
  }

  async function handleMutationResult(response: Awaited<ReturnType<typeof apiPost>>): Promise<void> {
    if (!response.ok) {
      if (response.errorClass === "conflict") {
        setRelationshipConflict(
          "The relationship version changed. Local form is kept. Reload to get the current version.",
        );
        return;
      }
      setRelationshipSaveError(response.error);
      return;
    }
    setRelationshipConflict(null);
    setRelationshipSaveError(null);
    const reloaded = await reloadGraph();
    if (reloaded) {
      clearReviseForm();
      setSelectedEdgeId(null);
    }
  }

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (relationshipBusy) return;
    if (!fromEntityId || !toEntityId || fromEntityId === toEntityId) {
      setRelationshipSaveError("create needs two different nodes");
      return;
    }
    setRelationshipBusy(true);
    setRelationshipConflict(null);
    setRelationshipSaveError(null);
    try {
      const [fromVersion, toVersion] = await Promise.all([
        readEntityVersion(fromEntityId),
        readEntityVersion(toEntityId),
      ]);
      if (fromVersion === null || toVersion === null) {
        setRelationshipSaveError("entity version was not returned");
        return;
      }
      const payload: Record<string, unknown> = {
        from_entity_id: fromEntityId,
        expected_from_version: fromVersion,
        relationship_type: relationshipType,
        to_entity_id: toEntityId,
        expected_to_version: toVersion,
        idempotency_key: crypto.randomUUID(),
      };
      if (scopeEntityId) {
        const scopeVersion = await readEntityVersion(scopeEntityId);
        if (scopeVersion === null) {
          setRelationshipSaveError("scope entity version was not returned");
          return;
        }
        payload.scope_entity_id = scopeEntityId;
        payload.expected_scope_version = scopeVersion;
      }
      const response = await apiPost(SESSION, "/api/canvas/relationships", payload);
      await handleMutationResult(response);
    } finally {
      setRelationshipBusy(false);
    }
  }

  async function onRevise(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (relationshipBusy || !selectedEdge) return;
    const refs = splitRefs(evidenceRefs);
    if (!clearEvidence && refs.length === 0) {
      setRelationshipConflict(null);
      setRelationshipSaveError(
        "This Map cannot display current citations. The inspector cannot read evidence_refs from the frozen graph or RelationshipView; a window-only revise would clear them. State a replacement set, or explicitly clear citations.",
      );
      return;
    }
    setRelationshipBusy(true);
    setRelationshipConflict(null);
    setRelationshipSaveError(null);
    try {
      const payload: Record<string, unknown> = {
        relationship_id: selectedEdge.edge_id,
        expected_version: selectedEdge.version,
        idempotency_key: crypto.randomUUID(),
        evidence_refs: clearEvidence ? [] : refs,
      };
      if (effectiveFrom.trim() && !clearFrom) payload.effective_from = effectiveFrom.trim();
      if (effectiveTo.trim() && !clearTo) payload.effective_to = effectiveTo.trim();
      const clear: string[] = [];
      if (clearFrom) clear.push("effective_from");
      if (clearTo) clear.push("effective_to");
      if (clear.length > 0) payload.clear = clear;
      const response = await apiPost(SESSION, "/api/canvas/relationships/revise", payload);
      await handleMutationResult(response);
    } finally {
      setRelationshipBusy(false);
    }
  }

  async function onEnd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (relationshipBusy || !selectedEdge) return;
    const reason = endReason.trim();
    if (!reason) {
      setRelationshipSaveError("end needs a reason");
      return;
    }
    const endedAt = effectiveEnd.trim();
    if (!endNow && !endedAt) {
      setRelationshipSaveError("end needs end_now or an effective end");
      return;
    }
    setRelationshipBusy(true);
    setRelationshipConflict(null);
    setRelationshipSaveError(null);
    try {
      const payload: Record<string, unknown> = {
        relationship_id: selectedEdge.edge_id,
        expected_version: selectedEdge.version,
        reason,
        idempotency_key: crypto.randomUUID(),
      };
      if (endNow) {
        payload.end_now = true;
      } else {
        payload.effective_end = endedAt;
      }
      const response = await apiPost(SESSION, "/api/canvas/relationships/end", payload);
      await handleMutationResult(response);
    } finally {
      setRelationshipBusy(false);
    }
  }

  return (
    <div onKeyDown={onNudge}>
      <div className="mb-3 flex flex-wrap gap-2">
        <Button
          type="button"
          variant={arrange ? "primary" : "secondary"}
          size="sm"
          aria-pressed={arrange}
          data-testid="canvas-arrange-toggle"
          onClick={() => {
            if (arrange) {
              setArrange(false);
              return;
            }
            turnOnArrange();
          }}
        >
          {arrange ? "Done arranging" : "Arrange"}
        </Button>
        <Button
          type="button"
          variant={relationshipEdit ? "primary" : "secondary"}
          size="sm"
          aria-pressed={relationshipEdit}
          data-testid="canvas-relationship-edit-toggle"
          onClick={() => {
            if (relationshipEdit) {
              setRelationshipEdit(false);
              clearReviseForm();
              setSelectedEdgeId(null);
              return;
            }
            turnOnRelationshipEdit();
          }}
        >
          {relationshipEdit ? "Done editing relationships" : "Edit relationships"}
        </Button>
      </div>
      {relationshipEdit ? (
        <div className="mb-3 grid gap-3 rounded-lg border border-border bg-surface p-3 text-sm">
          <form
            data-testid="canvas-relationship-create-form"
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={onCreate}
          >
            <label className="grid gap-1">
              <span className="font-medium text-moss-slate">From</span>
              <Select
                aria-label="From"
                value={fromEntityId}
                onChange={(event) => setFromEntityId(event.target.value)}
                required
              >
                <option value="">Choose a node</option>
                {mapNodes.map((node) => (
                  <option key={node.entity_id} value={node.entity_id}>
                    {node.display_label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="grid gap-1">
              <span className="font-medium text-moss-slate">To</span>
              <Select
                aria-label="To"
                value={toEntityId}
                onChange={(event) => setToEntityId(event.target.value)}
                required
              >
                <option value="">Choose a node</option>
                {mapNodes.map((node) => (
                  <option key={`to-${node.entity_id}`} value={node.entity_id}>
                    {node.display_label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="grid gap-1 sm:col-span-2">
              <span className="font-medium text-moss-slate">Relationship type</span>
              <Select
                aria-label="Relationship type"
                value={relationshipType}
                onChange={(event) =>
                  setRelationshipType(event.target.value as (typeof RELATIONSHIP_TYPES)[number])
                }
              >
                {RELATIONSHIP_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Select>
            </label>
            <div className="sm:col-span-2">
              <Button
                type="submit"
                size="sm"
                data-testid="canvas-relationship-create-submit"
                pending={relationshipBusy}
              >
                Create relationship
              </Button>
            </div>
          </form>
          <label className="grid gap-1">
            <span className="font-medium text-moss-slate">Selected relationship</span>
            <Select
              aria-label="Selected relationship"
              value={selectedEdge?.edge_id ?? ""}
              onChange={(event) => {
                const next = event.target.value;
                if (!next) {
                  clearReviseForm();
                  setSelectedEdgeId(null);
                  return;
                }
                onEdgeSelect(next);
              }}
            >
              <option value="">None</option>
              {relationshipEdges.map((edge) => (
                <option key={edge.edge_id} value={edge.edge_id}>
                  {nodeLabel(mapNodes, edge.from_entity_id)} →{" "}
                  {edge.to_entity_id ? nodeLabel(mapNodes, edge.to_entity_id) : "unknown"} (
                  {edge.type})
                </option>
              ))}
            </Select>
          </label>
          {selectedEdge ? (
            <>
              <form className="grid gap-3" onSubmit={onRevise}>
                <p className="text-xs text-muted">
                  Revise changes the effective window and evidence only. Retarget is end then
                  create.
                </p>
                <label className="grid gap-1">
                  <span className="font-medium text-moss-slate">Effective from</span>
                  <Input
                    aria-label="Effective from"
                    value={effectiveFrom}
                    onChange={(event) => setEffectiveFrom(event.target.value)}
                    placeholder="2026-01-01T00:00:00Z"
                    disabled={clearFrom}
                  />
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={clearFrom}
                    onChange={(event) => setClearFrom(event.target.checked)}
                  />
                  Clear effective from
                </label>
                <label className="grid gap-1">
                  <span className="font-medium text-moss-slate">Effective to</span>
                  <Input
                    aria-label="Effective to"
                    value={effectiveTo}
                    onChange={(event) => setEffectiveTo(event.target.value)}
                    placeholder="2026-12-31T00:00:00Z"
                    disabled={clearTo}
                  />
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={clearTo}
                    onChange={(event) => setClearTo(event.target.checked)}
                  />
                  Clear effective to
                </label>
                <label className="grid gap-1">
                  <span className="font-medium text-moss-slate">Evidence refs</span>
                  <Input
                    aria-label="Evidence refs"
                    value={evidenceRefs}
                    onChange={(event) => setEvidenceRefs(event.target.value)}
                    placeholder="comma-separated identifiers"
                    disabled={clearEvidence}
                  />
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label="Clear evidence citations"
                    data-testid="canvas-relationship-clear-evidence"
                    checked={clearEvidence}
                    onChange={(event) => setClearEvidence(event.target.checked)}
                  />
                  Clear evidence citations
                </label>
                <div>
                  <Button
                    type="submit"
                    size="sm"
                    variant="secondary"
                    data-testid="canvas-relationship-revise-submit"
                    pending={relationshipBusy}
                  >
                    Revise relationship
                  </Button>
                </div>
              </form>
              <form className="grid gap-3" onSubmit={onEnd}>
                <label className="grid gap-1">
                  <span className="font-medium text-moss-slate">End reason</span>
                  <Input
                    aria-label="End reason"
                    value={endReason}
                    onChange={(event) => setEndReason(event.target.value)}
                    required
                  />
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={endNow}
                    onChange={(event) => setEndNow(event.target.checked)}
                  />
                  End now
                </label>
                {endNow ? null : (
                  <label className="grid gap-1">
                    <span className="font-medium text-moss-slate">Effective end</span>
                    <Input
                      aria-label="Effective end"
                      value={effectiveEnd}
                      onChange={(event) => setEffectiveEnd(event.target.value)}
                    />
                  </label>
                )}
                <div>
                  <Button
                    type="submit"
                    size="sm"
                    variant="danger"
                    data-testid="canvas-relationship-end-submit"
                    pending={relationshipBusy}
                  >
                    End relationship
                  </Button>
                </div>
              </form>
            </>
          ) : null}
        </div>
      ) : null}
      {conflict ? (
        <p role="alert" data-testid="canvas-workspace-conflict" className="mb-3 text-sm text-moss-coral-strong">
          {conflict}
        </p>
      ) : null}
      {saveError ? (
        <p role="alert" data-testid="canvas-workspace-save-error" className="mb-3 text-sm text-moss-coral-strong">
          {saveError}
        </p>
      ) : null}
      {relationshipConflict ? (
        <p role="alert" data-testid="canvas-relationship-conflict" className="mb-3 text-sm text-moss-coral-strong">
          {relationshipConflict}
        </p>
      ) : null}
      {relationshipSaveError ? (
        <p
          role="alert"
          data-testid="canvas-relationship-save-error"
          className="mb-3 text-sm text-moss-coral-strong"
        >
          {relationshipSaveError}
        </p>
      ) : null}
      <GraphMap
        nodes={mapNodes}
        edges={mapEdges}
        focusEntityId={focusEntityId}
        savedPositions={overlay}
        arrange={arrange}
        relationshipEdit={relationshipEdit}
        selectedEntityId={selectedEntityId}
        selectedEdgeId={selectedEdgeId}
        inspectEntityId={selection?.kind === "node" ? selection.node.entity_id : null}
        inspectEdgeId={selection?.kind === "edge" ? selection.edge.edge_id : null}
        svgRef={svgRef}
        onNodePointerDown={onNodePointerDown}
        onSvgPointerMove={onSvgPointerMove}
        onSvgPointerUp={onSvgPointerUp}
        onNodeSelect={onNodeSelect}
        onEdgeSelect={onEdgeSelect}
        onInspectNode={publishInspectNode}
        onInspectEdge={publishInspectEdge}
      />
    </div>
  );
}
