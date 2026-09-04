// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_VIEW } from "./_entity-fixtures";
import { decodeEntitiesGet } from "./entities.get";

describe("decodeEntitiesGet", () => {
  it("accepts a Python-derived success payload", () => {
    expect(decodeEntitiesGet({ entity: ENTITY_VIEW }).ok).toBe(true);
  });

  it("fails closed when entity is omitted", () => {
    expect(decodeEntitiesGet({}).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeEntitiesGet({ entity: 1 }).ok).toBe(false);
  });
});
