import { afterEach, describe, expect, it, vi } from "vitest";

import { isSameOrigin } from "@/lib/http/origin";

describe("canonical CSRF origin", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("ignores a hostile request URL and forwarding headers", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_CANONICAL_ORIGIN", "https://my-pa.tail.example");
    const request = new Request("https://attacker.example/api/session", {
      headers: {
        origin: "https://my-pa.tail.example",
        "sec-fetch-site": "same-origin",
        host: "attacker.example",
        "x-forwarded-host": "attacker.example",
      },
    });
    expect(isSameOrigin(request)).toBe(true);
  });

  it("refuses an origin that merely matches the poisoned request URL", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_CANONICAL_ORIGIN", "https://my-pa.tail.example");
    const request = new Request("https://attacker.example/api/session", {
      headers: { origin: "https://attacker.example", "sec-fetch-site": "same-origin" },
    });
    expect(isSameOrigin(request)).toBe(false);
  });
});
