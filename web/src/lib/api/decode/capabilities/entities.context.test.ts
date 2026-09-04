// @vitest-environment node
import { describe, expect, it } from "vitest";
import { CONTEXT_CARD } from "./_entity-fixtures";
import { decodeEntitiesContext } from "./entities.context";

describe("decodeEntitiesContext", () => {
  it("accepts the frozen context-card wire shape", () => {
    const decoded = decodeEntitiesContext({ context_card: CONTEXT_CARD });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.context_card).toHaveProperty("aliases");
      expect(decoded.value.context_card).not.toHaveProperty("names");
    }
  });

  it("fails closed when a required card array is omitted", () => {
    const { memories: _, ...rest } = CONTEXT_CARD;
    expect(decodeEntitiesContext({ context_card: rest }).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeEntitiesContext({ context_card: { ...CONTEXT_CARD, aliases: undefined } }).ok).toBe(
      false,
    );
  });
});
