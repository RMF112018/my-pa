// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeEntitiesGraph } from "./entities.graph";

const NODE = {
  entity_id: "ent_aaaaaaaa11111111",
  projection_id: "gprj_ent_aaaaaaaa11111111",
  entity_type: "person",
  display_label: "Pat Synthetic",
  status: "active",
  superseded_by_entity_id: null,
};

const EDGE = {
  edge_kind: "relationship",
  edge_id: "erel_aaaaaaaa11111111",
  type: "works_for",
  from_entity_id: "ent_aaaaaaaa11111111",
  to_entity_id: "ent_bbbbbbbb22222222",
  from_projection_id: "gprj_ent_aaaaaaaa11111111",
  to_projection_id: "gprj_ent_bbbbbbbb22222222",
  scope_entity_id: null,
  is_current: null,
  state: "active",
  version: 1,
};

describe("decodeEntitiesGraph", () => {
  it("accepts a Python-derived page", () => {
    const decoded = decodeEntitiesGraph({ nodes: [NODE], edges: [EDGE], next_cursor: null });
    expect(decoded.ok).toBe(true);
  });

  it("fails closed when nodes is omitted", () => {
    expect(decodeEntitiesGraph({ edges: [], next_cursor: null }).ok).toBe(false);
  });

  it("fails closed when edges is omitted", () => {
    expect(decodeEntitiesGraph({ nodes: [], next_cursor: null }).ok).toBe(false);
  });

  it("does not treat omitted arrays as empty success", () => {
    const empty = decodeEntitiesGraph({ nodes: [], edges: [], next_cursor: null });
    expect(empty.ok).toBe(true);
    if (empty.ok) {
      expect(empty.value.nodes).toEqual([]);
      expect(empty.value.edges).toEqual([]);
    }
  });

  it("ignores extra fields", () => {
    const decoded = decodeEntitiesGraph({
      nodes: [{ ...NODE, leaked: "no" }],
      edges: [{ ...EDGE, leaked: "no" }],
      next_cursor: null,
      leaked: "no",
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value).not.toHaveProperty("leaked");
      expect(JSON.stringify(decoded.value)).not.toContain("leaked");
    }
  });
});
