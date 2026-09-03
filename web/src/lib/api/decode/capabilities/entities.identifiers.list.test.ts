// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_ID, LIFECYCLE_IDENTIFIER } from "./_entity-fixtures";
import { decodeEntitiesIdentifiersList } from "./entities.identifiers.list";

describe("decodeEntitiesIdentifiersList", () => {
  const valid = { entity_id: ENTITY_ID, identifiers: [LIFECYCLE_IDENTIFIER] };

  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesIdentifiersList(valid).ok).toBe(true);
  });

  it("fails closed when identifiers is omitted", () => {
    expect(decodeEntitiesIdentifiersList({ entity_id: ENTITY_ID }).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    const empty = decodeEntitiesIdentifiersList({ entity_id: ENTITY_ID, identifiers: [] });
    expect(empty.ok).toBe(true);
  });
});
