// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCanvasWorkspaceGet } from "./canvas.workspace.get";

const OVERLAY = {
  focus_entity_id: "ent_aaaaaaaa11111111",
  scope_entity_id: null,
  version: 1,
  positions: { ent_aaaaaaaa11111111: { x: 12.5, y: 40.25 } },
  updated_at: "2026-08-09T12:00:00.000Z",
};

describe("decodeCanvasWorkspaceGet", () => {
  it("accepts a Python-derived overlay", () => {
    const decoded = decodeCanvasWorkspaceGet(OVERLAY);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.version).toBe(1);
      expect(decoded.value.positions.ent_aaaaaaaa11111111).toEqual({ x: 12.5, y: 40.25 });
    }
  });

  it("accepts an empty overlay when nothing has been saved", () => {
    const decoded = decodeCanvasWorkspaceGet({
      focus_entity_id: "ent_aaaaaaaa11111111",
      scope_entity_id: null,
      version: 0,
      positions: {},
      updated_at: null,
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.version).toBe(0);
      expect(decoded.value.positions).toEqual({});
      expect(decoded.value.updated_at).toBeNull();
    }
  });

  it("fails closed when positions is omitted", () => {
    const { positions: _positions, ...rest } = OVERLAY;
    expect(decodeCanvasWorkspaceGet(rest).ok).toBe(false);
  });

  it("fails closed when a point has a non-numeric x", () => {
    expect(
      decodeCanvasWorkspaceGet({
        ...OVERLAY,
        positions: { ent_aaaaaaaa11111111: { x: "12.5", y: 40.25 } },
      }).ok,
    ).toBe(false);
  });

  it("fails closed when a point carries an extra key", () => {
    expect(
      decodeCanvasWorkspaceGet({
        ...OVERLAY,
        positions: { ent_aaaaaaaa11111111: { x: 12.5, y: 40.25, z: 1 } },
      }).ok,
    ).toBe(false);
  });
});
