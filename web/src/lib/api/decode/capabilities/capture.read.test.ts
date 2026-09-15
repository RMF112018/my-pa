// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCaptureRead } from "./capture.read";

const VALID = {
  capture_id: "cap_aaaa0001aaaa0001aaaa0001",
  version_id: "capver_aaaa0001aaaa0001aaaa0001",
  version_number: 1,
  supersedes_version_id: null,
  is_current: true,
  owner_principal_id: "prn_aaaa0001aaaa0001aaaa0001",
  project_id: null,
  classification: "synthetic_test",
  processing_policy: "local_only",
  content_sha256: "a".repeat(64),
  character_count: 12,
  text: "hello world",
  is_truncated: false,
  client_created_at: null,
  server_received_at: "2026-01-01T00:00:00Z",
  occurred_at: null,
  accepted_at: "2026-01-01T00:00:00Z",
  recorded_at: "2026-01-01T00:00:00Z",
};

describe("decodeCaptureRead", () => {
  it("accepts a Python-derived success payload including text", () => {
    const decoded = decodeCaptureRead(VALID);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.text).toBe("hello world");
      expect(decoded.value.project_id).toBeNull();
    }
  });

  it("accepts a canonical Project identifier", () => {
    const decoded = decodeCaptureRead({ ...VALID, project_id: "prj_aaaaaaaa11111111" });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.project_id).toBe("prj_aaaaaaaa11111111");
  });

  it("fails closed when project_id is missing or has the wrong non-null type", () => {
    const { project_id: _, ...rest } = VALID;
    expect(decodeCaptureRead(rest).ok).toBe(false);
    expect(decodeCaptureRead({ ...VALID, project_id: 1 }).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCaptureRead({ ...VALID, extra: 1 }).ok).toBe(true);
  });

  it("fails closed when the payload is empty", () => {
    expect(decodeCaptureRead({}).ok).toBe(false);
  });

  it("fails closed when text is omitted", () => {
    const { text: _, ...rest } = VALID;
    expect(decodeCaptureRead(rest).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { capture_id: _, ...rest } = VALID;
    expect(decodeCaptureRead(rest).ok).toBe(false);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCaptureRead({ ...VALID, character_count: "12" }).ok).toBe(false);
  });

  it("fails closed on an invalid classification", () => {
    expect(decodeCaptureRead({ ...VALID, classification: "public" }).ok).toBe(false);
  });
});
