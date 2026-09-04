// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_ID, ENTITY_NAME } from "./_entity-fixtures";
import { decodeEntitiesNamesList } from "./entities.names.list";

describe("decodeEntitiesNamesList", () => {
  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesNamesList({ entity_id: ENTITY_ID, names: [ENTITY_NAME] }).ok).toBe(true);
  });

  it("fails closed when names is omitted", () => {
    expect(decodeEntitiesNamesList({ entity_id: ENTITY_ID }).ok).toBe(false);
  });
});
