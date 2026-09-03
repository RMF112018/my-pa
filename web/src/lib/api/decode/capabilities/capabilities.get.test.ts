// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCapabilitiesGet } from "./capabilities.get";

const VALID = {
  manifest: {
    contract_version: "v1",
    contract_family: "my-pa-public-capabilities",
    capabilities: [
      {
        name: "capabilities.get",
        version: "v1",
        availability: "available",
        operator_only: false,
      },
    ],
    content_types: [{ media_type: "text/plain", availability: "available" }],
    limits: {
      max_page_size: 50,
      default_page_size: 20,
      max_fetch_bytes: 1_048_576,
      max_enrollment_depth: 8,
    },
  },
  readiness: {
    state: "degraded",
    contract_version: "v1",
    implemented_capabilities: 24,
    total_capabilities: 26,
    limitations: ["Worker-plane health is unavailable."],
  },
  worker_planes: [
    {
      plane: "capture",
      state: "unavailable",
      backlog: null,
      dead_lettered: null,
      last_heartbeat_at: null,
    },
  ],
};

describe("decodeCapabilitiesGet", () => {
  it("accepts a Python-derived success payload", () => {
    const decoded = decodeCapabilitiesGet(VALID);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.worker_planes).toHaveLength(1);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCapabilitiesGet({ ...VALID, extra: 1 }).ok).toBe(true);
  });

  it("fails closed on an empty object", () => {
    expect(decodeCapabilitiesGet({}).ok).toBe(false);
  });

  it("fails closed when worker_planes is omitted", () => {
    const { worker_planes: _, ...rest } = VALID;
    expect(decodeCapabilitiesGet(rest).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    const { worker_planes: _, ...rest } = VALID;
    expect(decodeCapabilitiesGet(rest).ok).toBe(false);
    const empty = decodeCapabilitiesGet({ ...VALID, worker_planes: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.worker_planes).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCapabilitiesGet({ ...VALID, manifest: [] }).ok).toBe(false);
    expect(decodeCapabilitiesGet({ ...VALID, worker_planes: 1 }).ok).toBe(false);
  });

  it("fails closed when a required nested field is missing", () => {
    expect(decodeCapabilitiesGet({ ...VALID, readiness: { state: "ready" } }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeCapabilitiesGet({
        ...VALID,
        readiness: { ...VALID.readiness, state: "healthy" },
      }).ok,
    ).toBe(false);
  });
});
