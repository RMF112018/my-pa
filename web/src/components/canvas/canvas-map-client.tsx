"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { GraphMap } from "@/components/canvas/graph-map";
import { apiPost } from "@/lib/api/client";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";
import type { CanvasPositions } from "@/lib/api/decode/capabilities/canvas.workspace.get";
import {
  CANVAS_MAP_HEIGHT,
  CANVAS_MAP_WIDTH,
  overlayLayout,
  type LayoutPoint,
  type SavedPositions,
} from "@/lib/canvas/layout";

const NUDGE = 4;

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

export function CanvasMapClient({
  nodes,
  edges,
  focusEntityId,
  scopeEntityId,
  savedPositions,
  version,
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  focusEntityId: string;
  scopeEntityId: string;
  savedPositions: SavedPositions;
  version: number;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ entityId: string; pointerId: number } | null>(null);
  const draftRef = useRef<Record<string, LayoutPoint>>({});
  const storedRef = useRef<SavedPositions>(savedPositions);
  const expectedVersionRef = useRef(version);
  const savingRef = useRef(false);
  const [arrange, setArrange] = useState(false);
  const [stored, setStored] = useState<SavedPositions>(savedPositions);
  const [draft, setDraft] = useState<Record<string, LayoutPoint>>({});
  const [, setExpectedVersion] = useState(version);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [, setSaving] = useState(false);

  const overlay: SavedPositions = { ...stored, ...draft };

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
        { hasSession: true },
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
    const laidOut = overlayLayout(nodes, focusEntityId, overlay);
    const current = laidOut.get(selectedEntityId);
    if (!current) return;
    const next = { x: current.x + delta.x, y: current.y + delta.y };
    const nextDraft = { ...draftRef.current, [selectedEntityId]: next };
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    void persist(nextDraft);
  }

  return (
    <div onKeyDown={onNudge}>
      <div className="mb-3">
        <Button
          type="button"
          variant={arrange ? "primary" : "secondary"}
          size="sm"
          aria-pressed={arrange}
          data-testid="canvas-arrange-toggle"
          onClick={() => setArrange((on) => !on)}
        >
          {arrange ? "Done arranging" : "Arrange"}
        </Button>
      </div>
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
      <GraphMap
        nodes={nodes}
        edges={edges}
        focusEntityId={focusEntityId}
        savedPositions={overlay}
        arrange={arrange}
        selectedEntityId={selectedEntityId}
        svgRef={svgRef}
        onNodePointerDown={onNodePointerDown}
        onSvgPointerMove={onSvgPointerMove}
        onSvgPointerUp={onSvgPointerUp}
      />
    </div>
  );
}
