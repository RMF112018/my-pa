import { describe, expect, it } from "vitest";
import { overlayLayout, type LayoutNode } from "./layout";

const FOCUS = "ent_aaaaaaaa11111111";
const NEIGHBOR = "ent_bbbbbbbb22222222";
const THIRD = "ent_cccccccc33333333";

const NODES: readonly LayoutNode[] = [
  { entity_id: FOCUS },
  { entity_id: NEIGHBOR },
  { entity_id: THIRD },
];

function pointOf(positions: Map<string, { x: number; y: number }>, id: string) {
  const point = positions.get(id);
  if (!point) throw new Error(`missing ${id}`);
  return point;
}

describe("overlayLayout", () => {
  it("equals radial placement when the saved map is empty", () => {
    const empty = overlayLayout(NODES, FOCUS, {});
    const again = overlayLayout(NODES, FOCUS, {});
    expect([...empty.entries()]).toEqual([...again.entries()]);
    expect(empty.size).toBe(3);
    expect(pointOf(empty, FOCUS)).toEqual({ x: 400, y: 280 });
  });

  it("replaces saved ids and keeps radial for the rest", () => {
    const radial = overlayLayout(NODES, FOCUS, {});
    const saved = { [NEIGHBOR]: { x: 12.5, y: 40.25 } };
    const overlaid = overlayLayout(NODES, FOCUS, saved);
    expect(pointOf(overlaid, NEIGHBOR)).toEqual({ x: 12.5, y: 40.25 });
    expect(pointOf(overlaid, FOCUS)).toEqual(pointOf(radial, FOCUS));
    expect(pointOf(overlaid, THIRD)).toEqual(pointOf(radial, THIRD));
  });

  it("keeps radial for ids that have no saved point", () => {
    const radial = overlayLayout(NODES, FOCUS, {});
    const overlaid = overlayLayout(NODES, FOCUS, {
      [FOCUS]: { x: 1, y: 2 },
    });
    expect(pointOf(overlaid, FOCUS)).toEqual({ x: 1, y: 2 });
    expect(overlaid.has(NEIGHBOR)).toBe(true);
    expect(pointOf(overlaid, NEIGHBOR)).toEqual(pointOf(radial, NEIGHBOR));
    expect(overlaid.has("ent_unknown00000000")).toBe(false);
  });
});
