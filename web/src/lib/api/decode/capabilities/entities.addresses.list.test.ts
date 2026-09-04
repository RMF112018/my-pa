// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_ADDRESS, ENTITY_ID } from "./_entity-fixtures";
import { decodeEntitiesAddressesList } from "./entities.addresses.list";

describe("decodeEntitiesAddressesList", () => {
  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesAddressesList({ entity_id: ENTITY_ID, addresses: [ENTITY_ADDRESS] }).ok).toBe(
      true,
    );
  });

  it("fails closed when addresses is omitted", () => {
    expect(decodeEntitiesAddressesList({ entity_id: ENTITY_ID }).ok).toBe(false);
  });
});
