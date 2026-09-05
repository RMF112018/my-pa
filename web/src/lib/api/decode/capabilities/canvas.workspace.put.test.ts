// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCanvasWorkspacePut } from "./canvas.workspace.put";

const RECEIPT = {
  focus_entity_id: "ent_aaaaaaaa11111111",
  scope_entity_id: null,
  version: 1,
  positions: { ent_aaaaaaaa11111111: { x: 12.5, y: 40.25 } },
  updated_at: "2026-08-09T12:00:00.000Z",
};

describe("decodeCanvasWorkspacePut", () => {
  it("accepts a Python-derived receipt", () => {
    const decoded = decodeCanvasWorkspacePut(RECEIPT);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.updated_at).toBe("2026-08-09T12:00:00.000Z");
    }
  });

  it("fails closed when positions is omitted", () => {
    expect(
      decodeCanvasWorkspacePut({
        focus_entity_id: RECEIPT.focus_entity_id,
        scope_entity_id: RECEIPT.scope_entity_id,
        version: RECEIPT.version,
        updated_at: RECEIPT.updated_at,
      }).ok,
    ).toBe(false);
  });

  it("fails closed when a point has a non-numeric x", () => {
    expect(
      decodeCanvasWorkspacePut({
        ...RECEIPT,
        positions: { ent_aaaaaaaa11111111: { x: "12.5", y: 40.25 } },
      }).ok,
    ).toBe(false);
  });

  it("fails closed when a point carries an extra key", () => {
    expect(
      decodeCanvasWorkspacePut({
        ...RECEIPT,
        positions: { ent_aaaaaaaa11111111: { x: 12.5, y: 40.25, z: 1 } },
      }).ok,
    ).toBe(false);
  });

  it("fails closed when updated_at is null", () => {
    expect(decodeCanvasWorkspacePut({ ...RECEIPT, updated_at: null }).ok).toBe(false);
  });
});
