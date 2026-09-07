/**
 * Unauthenticated liveness. The body never carries env values, paths, or stacks.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "@/app/api/health/route";

function request(): NextRequest {
  return new NextRequest("http://localhost:3000/api/health");
}

async function probe() {
  const response = await GET(request());
  const raw = await response.text();
  return { response, raw, body: JSON.parse(raw) as Record<string, unknown> };
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("GET /api/health", () => {
  it("answers live when NODE_ENV parses and the auth mode is a web value", async () => {
    vi.stubEnv("NODE_ENV", "test");
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    const { response, body, raw } = await probe();
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(body).toEqual({ ok: true, status: "live" });
    expect(raw).not.toMatch(/MYPA_|NODE_ENV|synthetic|passkey|secret/i);
    expect(raw).not.toContain(process.cwd());
  });

  it("answers live for passkey in production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_AUTH_MODE", "passkey");
    const { response, body } = await probe();
    expect(response.status).toBe(200);
    expect(body).toEqual({ ok: true, status: "live" });
  });

  it("answers 503 misconfigured when production asks for synthetic", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    const { response, body, raw } = await probe();
    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(body).toEqual({ error: { code: "misconfigured" } });
    expect(raw).not.toContain("synthetic");
    expect(raw).not.toContain("production");
    expect(raw).not.toMatch(/at |\.ts:\d+|stack/i);
  });

  it("answers 503 misconfigured when MYPA_AUTH_MODE is missing or invalid", async () => {
    for (const mode of ["", "entra", "local_operator", "development"]) {
      vi.stubEnv("NODE_ENV", "test");
      vi.stubEnv("MYPA_AUTH_MODE", mode);
      const { response, body, raw } = await probe();
      expect(response.status).toBe(503);
      expect(body).toEqual({ error: { code: "misconfigured" } });
      if (mode) expect(raw).not.toContain(mode);
      expect(raw).not.toContain("MYPA_AUTH_MODE");
    }
  });

  it("answers 503 misconfigured when NODE_ENV does not parse", async () => {
    vi.stubEnv("NODE_ENV", "staging");
    vi.stubEnv("MYPA_AUTH_MODE", "passkey");
    const { response, body, raw } = await probe();
    expect(response.status).toBe(503);
    expect(body).toEqual({ error: { code: "misconfigured" } });
    expect(raw).not.toContain("staging");
    expect(raw).not.toContain("passkey");
  });

  it("does not require a session cookie", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    const { response } = await probe();
    expect(response.status).toBe(200);
  });
});
