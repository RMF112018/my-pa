// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ENTITY_SUMMARY } from "./_entity-fixtures";
import { decodeEntitiesSearch } from "./entities.search";

describe("decodeEntitiesSearch", () => {
  it("accepts a Python-derived success payload", () => {
    expect(decodeEntitiesSearch({ entities: [ENTITY_SUMMARY] }).ok).toBe(true);
  });

  it("fails closed when entities is omitted", () => {
    expect(decodeEntitiesSearch({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeEntitiesSearch({}).ok).toBe(false);
    const empty = decodeEntitiesSearch({ entities: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.entities).toEqual([]);
  });

  it("fails closed when a required disambiguator array is omitted", () => {
    const { affiliated_organizations: _, ...rest } = ENTITY_SUMMARY;
    expect(decodeEntitiesSearch({ entities: [rest] }).ok).toBe(false);
  });
});
