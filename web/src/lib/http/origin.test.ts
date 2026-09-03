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

  it("refuses a missing Origin even when sec-fetch-site is same-origin", () => {
    const request = new Request("http://localhost:3000/api/session", {
      headers: { "sec-fetch-site": "same-origin" },
    });
    expect(isSameOrigin(request)).toBe(false);
  });

  it("refuses a missing Origin even when sec-fetch-site is none", () => {
    const request = new Request("http://localhost:3000/api/session", {
      headers: { "sec-fetch-site": "none" },
    });
    expect(isSameOrigin(request)).toBe(false);
  });

  it("refuses a missing Origin when sec-fetch-site is also absent", () => {
    const request = new Request("http://localhost:3000/api/session");
    expect(isSameOrigin(request)).toBe(false);
  });

  it("refuses sec-fetch-site cross-site even when Origin matches", () => {
    const request = new Request("http://localhost:3000/api/session", {
      headers: { origin: "http://localhost:3000", "sec-fetch-site": "cross-site" },
    });
    expect(isSameOrigin(request)).toBe(false);
  });

  it("refuses sec-fetch-site same-site even when Origin matches", () => {
    const request = new Request("http://localhost:3000/api/session", {
      headers: { origin: "http://localhost:3000", "sec-fetch-site": "same-site" },
    });
    expect(isSameOrigin(request)).toBe(false);
  });
});
