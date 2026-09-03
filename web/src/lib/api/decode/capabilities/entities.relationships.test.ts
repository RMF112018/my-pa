// @vitest-environment node
import { describe, expect, it } from "vitest";
import { RELATIONSHIP } from "./_entity-fixtures";
import { decodeEntitiesRelationships } from "./entities.relationships";

describe("decodeEntitiesRelationships", () => {
  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesRelationships({ relationships: [RELATIONSHIP] }).ok).toBe(true);
  });

  it("fails closed when relationships is omitted", () => {
    expect(decodeEntitiesRelationships({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    const empty = decodeEntitiesRelationships({ relationships: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.relationships).toEqual([]);
  });
});
