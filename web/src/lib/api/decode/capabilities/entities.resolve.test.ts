// @vitest-environment node
import { describe, expect, it } from "vitest";
import { RESOLUTION } from "./_entity-fixtures";
import { decodeEntitiesResolve } from "./entities.resolve";

describe("decodeEntitiesResolve", () => {
  it("accepts an ambiguous Python-derived success and keeps outcome visible", () => {
    const decoded = decodeEntitiesResolve({ resolution: RESOLUTION });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.resolution.outcome).toBe("ambiguous");
      expect(decoded.value.resolution.entity_id).toBeNull();
    }
  });

  it("fails closed when candidates is omitted", () => {
    const { candidates: _, ...rest } = RESOLUTION;
    expect(decodeEntitiesResolve({ resolution: rest }).ok).toBe(false);
  });

  it("does not treat an omitted candidate array as empty success", () => {
    expect(decodeEntitiesResolve({ resolution: { ...RESOLUTION, candidates: undefined } }).ok).toBe(
      false,
    );
    const empty = decodeEntitiesResolve({
      resolution: { ...RESOLUTION, candidates: [], warnings: [] },
    });
    expect(empty.ok).toBe(true);
  });
});
