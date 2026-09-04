// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_ID, IDENTITY_HISTORY_ENTRY } from "./_entity-fixtures";
import { decodeEntitiesIdentityHistory } from "./entities.identity_history";

describe("decodeEntitiesIdentityHistory", () => {
  const valid = {
    entity_id: ENTITY_ID,
    entries: [IDENTITY_HISTORY_ENTRY],
    is_truncated: false,
    next_cursor: null,
    audit_id: "audit_aaaaaaaa11111111",
  };

  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesIdentityHistory(valid).ok).toBe(true);
  });

  it("fails closed when entries is omitted", () => {
    const { entries: _, ...rest } = valid;
    expect(decodeEntitiesIdentityHistory(rest).ok).toBe(false);
  });
});
