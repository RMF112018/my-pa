// @vitest-environment node
import { describe, expect, it } from "vitest";
import { UNRESOLVED_MENTION } from "./_entity-fixtures";
import { decodeEntitiesUnresolvedMentions } from "./entities.unresolved_mentions";

describe("decodeEntitiesUnresolvedMentions", () => {
  it("accepts a Python-derived page without observed_value", () => {
    const decoded = decodeEntitiesUnresolvedMentions({ mentions: [UNRESOLVED_MENTION] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.mentions[0]).not.toHaveProperty("observed_value");
  });

  it("fails closed when mentions is omitted", () => {
    expect(decodeEntitiesUnresolvedMentions({}).ok).toBe(false);
  });

  it("does not echo observed_value", () => {
    expect(
      decodeEntitiesUnresolvedMentions({
        mentions: [{ ...UNRESOLVED_MENTION, observed_value: "should-not-leak" }],
      }).ok,
    ).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    const empty = decodeEntitiesUnresolvedMentions({ mentions: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.mentions).toEqual([]);
  });
});
