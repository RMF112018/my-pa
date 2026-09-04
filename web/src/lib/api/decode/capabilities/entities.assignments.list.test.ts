// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ASSIGNMENT } from "./_entity-fixtures";
import { decodeEntitiesAssignmentsList } from "./entities.assignments.list";

describe("decodeEntitiesAssignmentsList", () => {
  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesAssignmentsList({ assignments: [ASSIGNMENT] }).ok).toBe(true);
  });

  it("fails closed when assignments is omitted", () => {
    expect(decodeEntitiesAssignmentsList({}).ok).toBe(false);
  });
});
