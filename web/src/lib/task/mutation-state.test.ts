import { describe, expect, it } from "vitest";
import {
  canTransitionMutationPhase,
  classifyMutationError,
  idleMutationState,
  isAmbiguousMutationFailure,
  transitionMutationPhase,
  type MutationPhase,
} from "@/lib/task/mutation-state";

describe("mutation state machine", () => {
  it.each([
    ["idle", "pending", true],
    ["pending", "confirmed", true],
    ["pending", "failed", true],
    ["pending", "conflict", true],
    ["pending", "ambiguous", true],
    ["ambiguous", "pending", true],
    ["confirmed", "idle", true],
    ["failed", "idle", true],
    ["conflict", "idle", true],
    ["idle", "confirmed", false],
    ["confirmed", "pending", false],
    ["failed", "ambiguous", false],
    ["conflict", "ambiguous", false],
  ] as const)("transition %s → %s allowed=%s", (from, to, allowed) => {
    expect(canTransitionMutationPhase(from, to)).toBe(allowed);
    if (allowed) {
      expect(transitionMutationPhase(from, to)).toBe(to);
    } else {
      expect(() => transitionMutationPhase(from, to)).toThrow(/invalid mutation transition/);
    }
  });

  it("starts idle", () => {
    expect(idleMutationState()).toEqual({ phase: "idle" satisfies MutationPhase });
  });

  it("classifies HTTP and network errors into subtypes", () => {
    expect(classifyMutationError(new TypeError("Failed to fetch")).subtype).toBe("network");
    expect(classifyMutationError({ status: 401, message: "no" }).subtype).toBe("unauthenticated");
    expect(classifyMutationError({ status: 403, message: "no" }).subtype).toBe("forbidden");
    expect(classifyMutationError({ status: 400, message: "bad" }).subtype).toBe("validation");
    expect(classifyMutationError({ status: 503, message: "gw" }).subtype).toBe("gateway");
    expect(
      classifyMutationError({ status: 503, code: "upstream_contract_invalid", message: "bad" }).subtype,
    ).toBe("contract");
    expect(classifyMutationError({ status: 500, message: "boom" }).subtype).toBe("backend");
  });

  it("treats network and gateway as ambiguous, contract as not", () => {
    expect(isAmbiguousMutationFailure(new TypeError("offline"))).toBe(true);
    expect(isAmbiguousMutationFailure({ status: 503 })).toBe(true);
    expect(isAmbiguousMutationFailure({ status: 503, code: "upstream_contract_invalid" })).toBe(false);
    expect(isAmbiguousMutationFailure({ status: 400 })).toBe(false);
  });
});
