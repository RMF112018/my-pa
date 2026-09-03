import { describe, expect, it } from "vitest";

import { browserSecurityHeaders } from "@/lib/http/security-headers";

function headerMap(headers: { key: string; value: string }[]) {
  return new Map(headers.map((header) => [header.key, header.value]));
}

describe("production browser security headers", () => {
  const headers = browserSecurityHeaders();
  const byName = headerMap(headers);
  const csp = byName.get("Content-Security-Policy") ?? "";

  it("does not emit HSTS", () => {
    expect(byName.has("Strict-Transport-Security")).toBe(false);
    expect(headers.some((header) => /strict-transport-security/i.test(header.key))).toBe(
      false,
    );
  });

  it("emits enforcing CSP, not Report-Only", () => {
    expect(byName.has("Content-Security-Policy")).toBe(true);
    expect(byName.has("Content-Security-Policy-Report-Only")).toBe(false);
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("form-action 'self'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain("worker-src 'self'");
    expect(csp).toContain("style-src 'self' 'unsafe-inline'");
  });

  it("keeps production script-src free of eval and websocket holes", () => {
    expect(csp).not.toMatch(/unsafe-eval/);
    expect(csp).not.toMatch(/\bws:/);
    expect(csp).not.toMatch(/\bwss:/);
    expect(csp).toContain("script-src 'self' 'unsafe-inline'");
  });

  it("denies framing in CSP and X-Frame-Options", () => {
    expect(csp).toContain("frame-ancestors 'none'");
    expect(byName.get("X-Frame-Options")).toBe("DENY");
  });

  it("keeps WebAuthn Permissions-Policy get and create on self", () => {
    const permissions = byName.get("Permissions-Policy") ?? "";
    expect(permissions).toContain("publickey-credentials-get=(self)");
    expect(permissions).toContain("publickey-credentials-create=(self)");
  });

  it("emits nosniff and strict-origin-when-cross-origin referrer policy", () => {
    expect(byName.get("X-Content-Type-Options")).toBe("nosniff");
    expect(byName.get("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
  });

  it("does not open CORS", () => {
    expect(byName.has("Access-Control-Allow-Origin")).toBe(false);
    expect(headers.some((header) => header.value === "*")).toBe(false);
  });
});
