// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCaptureList } from "./capture.list";

const ENTRY = {
  capture_id: "cap_aaaa0001aaaa0001aaaa0001",
  owner_principal_id: "prn_aaaa0001aaaa0001aaaa0001",
  created_at: "2026-01-01T00:00:00Z",
  version_count: 1,
  latest_version_id: "capver_aaaa0001aaaa0001aaaa0001",
  latest_version_number: 1,
  latest_recorded_at: "2026-01-01T00:00:00Z",
};

describe("decodeCaptureList", () => {
  it("accepts a Python-derived success payload without text", () => {
    const decoded = decodeCaptureList({ captures: [ENTRY] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect("text" in decoded.value.captures[0]!).toBe(false);
  });

  it("ignores unknown extra fields including a smuggled text field", () => {
    expect(decodeCaptureList({ captures: [{ ...ENTRY, text: "no" }], extra: 1 }).ok).toBe(true);
  });

  it("fails closed when captures is omitted", () => {
    expect(decodeCaptureList({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeCaptureList({}).ok).toBe(false);
    const empty = decodeCaptureList({ captures: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.captures).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCaptureList({ captures: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { latest_version_id: _, ...rest } = ENTRY;
    expect(decodeCaptureList({ captures: [rest] }).ok).toBe(false);
  });
});
