// @vitest-environment node
import { describe, expect, it } from "vitest";
import { PROFILE } from "./_entity-fixtures";
import { decodeEntitiesProfile } from "./entities.profile";

describe("decodeEntitiesProfile", () => {
  it("accepts a Python-derived profile with record families", () => {
    const decoded = decodeEntitiesProfile({ profile: PROFILE });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.profile.names).toHaveLength(1);
      expect(decoded.value.profile).toHaveProperty("communication_methods");
    }
  });

  it("fails closed when a required family array is omitted", () => {
    const { names: _, ...rest } = PROFILE;
    expect(decodeEntitiesProfile({ profile: rest }).ok).toBe(false);
  });
});
