import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";

/**
 * WP16 radial layout (`layout.ts`) places non-focus nodes on a circle of
 * RADIUS=180. GraphMap draws those nodes at NODE_R=16. Circumference is
 * 2π·180 ≈ 1131px. Adjacent ring nodes overlap their diameters when
 * 2·RADIUS·sin(π/n) < 2·NODE_R, i.e. n > π / asin(NODE_R / RADIUS) ≈ 35.29.
 * The first overlap is 36 ring nodes, so 35 is the last usable ring count.
 */
export const CANVAS_MAP_LAYOUT_RADIUS = 180;
export const CANVAS_MAP_NODE_R = 16;
export const CANVAS_MAP_MAX_RING_NODES = 35;

const SVG_NS = "http://www.w3.org/2000/svg";

export function canvasRingNodeCount(
  nodes: readonly { readonly entity_id: string }[],
  focusEntityId: string,
): number {
  if (nodes.length === 0) return 0;
  const hasFocus = Boolean(focusEntityId) && nodes.some((node) => node.entity_id === focusEntityId);
  return hasFocus ? nodes.length - 1 : nodes.length;
}

export function shouldOmitVisualMap(
  nodes: readonly { readonly entity_id: string }[],
  focusEntityId: string,
): boolean {
  return canvasRingNodeCount(nodes, focusEntityId) > CANVAS_MAP_MAX_RING_NODES;
}

export function serializeNeighborhoodText(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
): string {
  const nodeLines = nodes.map((node) => `${node.display_label}\t${node.entity_id}`);
  const edgeLines = edges.map(
    (edge) =>
      `${edge.from_entity_id}\t${edge.to_entity_id ?? ""}\t${edge.type}\t${edge.edge_kind}`,
  );
  return [
    "Neighborhood (this returned page)",
    "",
    "Nodes",
    "display_label\tentity_id",
    ...nodeLines,
    "",
    "Edges",
    "from_entity_id\tto_entity_id\ttype\tkind",
    ...edgeLines,
    "",
  ].join("\n");
}

export function serializeSvgMarkup(svg: SVGSVGElement): string | null {
  const clone = svg.cloneNode(true);
  if (!(clone instanceof Element)) return null;
  clone.setAttribute("xmlns", SVG_NS);
  if (typeof XMLSerializer === "function") {
    return new XMLSerializer().serializeToString(clone);
  }
  const html = "outerHTML" in clone ? String((clone as SVGSVGElement).outerHTML) : "";
  return html.length > 0 ? html : null;
}

export function downloadTextFile(filename: string, contents: string, mime: string): void {
  if (typeof document === "undefined") return;
  const anchor = document.createElement("a");
  anchor.setAttribute("download", filename);
  const canObjectUrl =
    typeof URL !== "undefined" && typeof URL.createObjectURL === "function";
  let objectUrl: string | null = null;
  if (canObjectUrl) {
    objectUrl = URL.createObjectURL(new Blob([contents], { type: mime }));
    anchor.href = objectUrl;
  } else {
    anchor.href = `data:${mime};charset=utf-8,${encodeURIComponent(contents)}`;
  }
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  if (objectUrl !== null && typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(objectUrl);
  }
}
