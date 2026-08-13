import { afterEach, describe, expect, it, vi } from "vitest";

import { canonicalOrigin, canonicalUrl } from "@/lib/http/canonical-origin";

describe("canonical private origin", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("accepts only an exact HTTPS hostname origin", () => {
    vi.stubEnv("MYPA_CANONICAL_ORIGIN", "https://my-pa.tail.example");
    expect(canonicalOrigin()).toBe("https://my-pa.tail.example");
    expect(canonicalUrl("/auth/callback").href).toBe(
      "https://my-pa.tail.example/auth/callback",
    );
  });

  it.each([
    "",
    "http://my-pa.tail.example",
    "https://user@my-pa.tail.example",
    "https://my-pa.tail.example:8443",
    "https://my-pa.tail.example/path",
    "https://my-pa.tail.example/?query=yes",
    "https://my-pa.tail.example/#fragment",
  ])("refuses non-canonical value %j", (value) => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_CANONICAL_ORIGIN", value);
    expect(() => canonicalOrigin()).toThrow();
  });
});
