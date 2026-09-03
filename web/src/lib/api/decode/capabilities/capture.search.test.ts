// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCaptureSearch } from "./capture.search";

const MATCH = {
  capture_id: "cap_aaaa0001aaaa0001aaaa0001",
  version_id: "capver_aaaa0001aaaa0001aaaa0001",
  version_number: 1,
  character_count: 12,
  recorded_at: "2026-01-01T00:00:00Z",
};

const VALID = { matches: [MATCH], searchable_versions: 1, stored_versions: 1 };

describe("decodeCaptureSearch", () => {
  it("accepts a Python-derived success payload", () => {
    const decoded = decodeCaptureSearch(VALID);
    expect(decoded.ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCaptureSearch({ ...VALID, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when matches is omitted", () => {
    expect(decodeCaptureSearch({ searchable_versions: 0, stored_versions: 0 }).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeCaptureSearch({ searchable_versions: 0, stored_versions: 0 }).ok).toBe(false);
    const empty = decodeCaptureSearch({ matches: [], searchable_versions: 0, stored_versions: 0 });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.matches).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCaptureSearch({ ...VALID, matches: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { searchable_versions: _, ...rest } = VALID;
    expect(decodeCaptureSearch(rest).ok).toBe(false);
  });
});
