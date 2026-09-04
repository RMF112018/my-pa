import { describe, expect, it } from "vitest";
import { ASSIGNMENT } from "@/lib/api/decode/capabilities/_entity-fixtures";
import type { AssignmentView } from "@/lib/api/decode/capabilities/entities.assignments.list";
import {
  directedIsCurrent,
  lifecycleIsCurrent,
  participationIsCurrent,
  partitionByCurrency,
} from "./currency";

const current = { ...ASSIGNMENT, assignment_id: "asn_current00000001", is_current: true, status: "active" } as AssignmentView;
const ended = {
  ...ASSIGNMENT,
  assignment_id: "asn_ended0000000001",
  is_current: false,
  status: "ended",
} as AssignmentView;
const superseded = {
  ...ASSIGNMENT,
  assignment_id: "asn_superseded00001",
  is_current: false,
  status: "superseded",
} as AssignmentView;
const unspecifiedActive = {
  ...ASSIGNMENT,
  assignment_id: "asn_unspecifiedact1",
  is_current: null,
  status: "active",
} as AssignmentView;
const unspecifiedEnded = {
  ...ASSIGNMENT,
  assignment_id: "asn_unspecifiedend1",
  is_current: null,
  status: "ended",
} as AssignmentView;

describe("assignment grouping uses backend currency fields, not the clock", () => {
  it("partitions a mixed list from is_current and status", () => {
    const mixed = [ended, current, unspecifiedEnded, unspecifiedActive, superseded];
    const { current: now, historical } = partitionByCurrency(mixed, directedIsCurrent);
    expect(now.map((row) => row.assignment_id)).toEqual([
      "asn_current00000001",
      "asn_unspecifiedact1",
    ]);
    expect(historical.map((row) => row.assignment_id)).toEqual([
      "asn_ended0000000001",
      "asn_unspecifiedend1",
      "asn_superseded00001",
    ]);
  });

  it("trusts is_current even when status would disagree", () => {
    expect(directedIsCurrent({ is_current: true, status: "ended" })).toBe(true);
    expect(directedIsCurrent({ is_current: false, status: "active" })).toBe(false);
  });

  it("does not consult Date.now or effective dates", () => {
    const source = directedIsCurrent.toString() + partitionByCurrency.toString();
    expect(source).not.toMatch(/Date\.now/);
    expect(source).not.toMatch(/effective_from/);
    expect(source).not.toMatch(/effective_to/);
  });
});

describe("lifecycle and participation currency", () => {
  it("treats retired and superseded as historical", () => {
    expect(lifecycleIsCurrent({ state: "active" })).toBe(true);
    expect(lifecycleIsCurrent({ state: "retired" })).toBe(false);
    expect(lifecycleIsCurrent({ state: "superseded" })).toBe(false);
  });

  it("uses relationship_status_code rather than inventing dates", () => {
    expect(
      participationIsCurrent({ state: "active", relationship_status_code: "active" }),
    ).toBe(true);
    expect(
      participationIsCurrent({ state: "active", relationship_status_code: "completed" }),
    ).toBe(false);
    expect(
      participationIsCurrent({ state: "retired", relationship_status_code: "active" }),
    ).toBe(false);
  });
});
