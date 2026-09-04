// @vitest-environment node
import { describe, expect, it } from "vitest";
import { RECORDED_OBSERVATION } from "./_entity-fixtures";
import { decodeEntitiesObservationsList } from "./entities.observations.list";

describe("decodeEntitiesObservationsList", () => {
  it("accepts a Python-derived page", () => {
    expect(decodeEntitiesObservationsList({ observations: [RECORDED_OBSERVATION] }).ok).toBe(true);
  });

  it("fails closed when observations is omitted", () => {
    expect(decodeEntitiesObservationsList({}).ok).toBe(false);
  });

  it("does not echo observed_value", () => {
    expect(
      decodeEntitiesObservationsList({
        observations: [{ ...RECORDED_OBSERVATION, observed_value: "should-not-leak" }],
      }).ok,
    ).toBe(false);
  });
});
