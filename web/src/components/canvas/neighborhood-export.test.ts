import { describe, expect, it } from "vitest";
import {
  CANVAS_MAP_MAX_RING_NODES,
  canvasRingNodeCount,
  shouldOmitVisualMap,
} from "./neighborhood-export";

const FOCUS = "ent_aaaaaaaa11111111";

function ringNodes(ringCount: number, includeFocus = true) {
  const ring = Array.from({ length: ringCount }, (_, index) => ({
    entity_id: `ent_${(index + 1).toString(16).padStart(16, "0")}`,
  }));
  return includeFocus ? [{ entity_id: FOCUS }, ...ring] : ring;
}

describe("neighborhood visual-map scale", () => {
  it("keeps the last usable ring count at 35", () => {
    expect(CANVAS_MAP_MAX_RING_NODES).toBe(35);
  });

  it("does not omit the visual map at 35 ring nodes when focus is in the set", () => {
    const nodes = ringNodes(35);
    expect(canvasRingNodeCount(nodes, FOCUS)).toBe(35);
    expect(shouldOmitVisualMap(nodes, FOCUS)).toBe(false);
  });

  it("omits the visual map at 36 ring nodes when focus is in the set", () => {
    const nodes = ringNodes(36);
    expect(canvasRingNodeCount(nodes, FOCUS)).toBe(36);
    expect(shouldOmitVisualMap(nodes, FOCUS)).toBe(true);
  });
});
