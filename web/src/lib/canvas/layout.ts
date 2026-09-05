/**
 * Map geometry: WP16 radial placement, plus an optional saved overlay.
 * Saved x/y win when present; missing ids keep the radial default.
 * An empty saved map is the current WP16 behavior.
 */

export const CANVAS_MAP_WIDTH = 800;
export const CANVAS_MAP_HEIGHT = 560;
const CX = CANVAS_MAP_WIDTH / 2;
const CY = CANVAS_MAP_HEIGHT / 2;
const RADIUS = 180;

export type LayoutNode = { readonly entity_id: string };
export type LayoutPoint = { readonly x: number; readonly y: number };
export type SavedPositions = Readonly<Record<string, LayoutPoint>>;

function radialLayout(
  nodes: readonly LayoutNode[],
  focusEntityId: string,
): Map<string, LayoutPoint> {
  const ordered = [...nodes].sort((a, b) => a.entity_id.localeCompare(b.entity_id));
  const positions = new Map<string, LayoutPoint>();
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

export function overlayLayout(
  nodes: readonly LayoutNode[],
  focusEntityId: string,
  savedPositions: SavedPositions,
): Map<string, LayoutPoint> {
  const radial = radialLayout(nodes, focusEntityId);
  if (Object.keys(savedPositions).length === 0) return radial;
  const overlaid = new Map<string, LayoutPoint>();
  for (const [entityId, point] of radial) {
    const saved = savedPositions[entityId];
    overlaid.set(entityId, saved ? { x: saved.x, y: saved.y } : point);
  }
  return overlaid;
}
