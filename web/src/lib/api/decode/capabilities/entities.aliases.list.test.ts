// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_ID, LIFECYCLE_ALIAS } from "./_entity-fixtures";
import { decodeEntitiesAliasesList } from "./entities.aliases.list";

describe("decodeEntitiesAliasesList", () => {
  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesAliasesList({ entity_id: ENTITY_ID, aliases: [LIFECYCLE_ALIAS] }).ok).toBe(
      true,
    );
  });

  it("fails closed when aliases is omitted", () => {
    expect(decodeEntitiesAliasesList({ entity_id: ENTITY_ID }).ok).toBe(false);
  });
});
