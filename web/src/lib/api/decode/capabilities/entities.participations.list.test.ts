// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_ID, PARTICIPATION } from "./_entity-fixtures";
import { decodeEntitiesParticipationsList } from "./entities.participations.list";

describe("decodeEntitiesParticipationsList", () => {
  it("accepts a Python-derived page", () => {
    expect(
      decodeEntitiesParticipationsList({
        entity_id: ENTITY_ID,
        perspective: "participant",
        participations: [PARTICIPATION],
      }).ok,
    ).toBe(true);
  });

  it("fails closed when participations is omitted", () => {
    expect(
      decodeEntitiesParticipationsList({ entity_id: ENTITY_ID, perspective: "participant" }).ok,
    ).toBe(false);
  });
});
