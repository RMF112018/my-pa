// @vitest-environment node
import { describe, expect, it } from "vitest";
import { COMMUNICATION_METHOD, ENTITY_ID } from "./_entity-fixtures";
import { decodeEntitiesCommunicationList } from "./entities.communication.list";

describe("decodeEntitiesCommunicationList", () => {
  it("accepts a Python-derived page", () => {
    expect(
      decodeEntitiesCommunicationList({
        entity_id: ENTITY_ID,
        communication_methods: [COMMUNICATION_METHOD],
      }).ok,
    ).toBe(true);
  });

  it("fails closed when communication_methods is omitted", () => {
    expect(decodeEntitiesCommunicationList({ entity_id: ENTITY_ID }).ok).toBe(false);
  });
});
