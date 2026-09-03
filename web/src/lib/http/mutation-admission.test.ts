import { afterEach, describe, expect, it, vi } from "vitest";

import { admitBrowserMutation } from "@/lib/http/mutation-admission";

const CROSS_SITE_BODY = {
  error: {
    errorClass: "authorization",
    code: "cross_site_request",
    message: "this endpoint refuses cross-site requests",
  },
};

function throwOnBodyAccess(request: Request): Request {
  return new Proxy(request, {
    get(target, property, receiver) {
      if (
        property === "body" ||
        property === "json" ||
        property === "text" ||
        property === "arrayBuffer" ||
        property === "blob" ||
        property === "formData"
      ) {
        throw new Error(`admitBrowserMutation must not read Request.${String(property)}`);
      }
      const value = Reflect.get(target, property, receiver);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

async function expectCrossSiteRefusal(response: Response | null) {
  expect(response).not.toBeNull();
  expect(response!.status).toBe(403);
  await expect(response!.json()).resolves.toEqual(CROSS_SITE_BODY);
}

describe("admitBrowserMutation", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("never reads the body: missing Origin still returns 403 without throwing", async () => {
    const request = throwOnBodyAccess(
      new Request("http://localhost:3000/api/capture", {
        method: "POST",
        headers: { "sec-fetch-site": "same-origin" },
      }),
    );
    await expectCrossSiteRefusal(admitBrowserMutation(request));
  });

  it("never reads the body: matching Origin still returns null without throwing", () => {
    const request = throwOnBodyAccess(
      new Request("http://localhost:3000/api/capture", {
        method: "POST",
        headers: { origin: "http://localhost:3000", "sec-fetch-site": "same-origin" },
      }),
    );
    expect(admitBrowserMutation(request)).toBeNull();
  });

  it("refuses a missing Origin with the Work cross-site envelope", async () => {
    const request = new Request("http://localhost:3000/api/capture", { method: "POST" });
    await expectCrossSiteRefusal(admitBrowserMutation(request));
  });

  it("refuses a wrong Origin with the Work cross-site envelope", async () => {
    const request = new Request("http://localhost:3000/api/capture", {
      method: "POST",
      headers: { origin: "https://attacker.example", "sec-fetch-site": "same-origin" },
    });
    await expectCrossSiteRefusal(admitBrowserMutation(request));
  });

  it("does not let sec-fetch-site same-origin voucher a missing Origin", async () => {
    const request = new Request("http://localhost:3000/api/capture", {
      method: "POST",
      headers: { "sec-fetch-site": "same-origin" },
    });
    await expectCrossSiteRefusal(admitBrowserMutation(request));
  });

  it("admits production Origin against canonicalOrigin, not Host or X-Forwarded-Host", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_CANONICAL_ORIGIN", "https://my-pa.tail.example");
    const admitted = new Request("https://attacker.example/api/capture", {
      method: "POST",
      headers: {
        origin: "https://my-pa.tail.example",
        "sec-fetch-site": "same-origin",
        host: "attacker.example",
        "x-forwarded-host": "attacker.example",
      },
    });
    expect(admitBrowserMutation(admitted)).toBeNull();
  });

  it("refuses production Origin that merely matches a poisoned Host", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MYPA_CANONICAL_ORIGIN", "https://my-pa.tail.example");
    const refused = new Request("https://attacker.example/api/capture", {
      method: "POST",
      headers: {
        origin: "https://attacker.example",
        "sec-fetch-site": "same-origin",
        host: "attacker.example",
        "x-forwarded-host": "attacker.example",
      },
    });
    await expectCrossSiteRefusal(admitBrowserMutation(refused));
  });

  it("returns null on the same-origin happy path", () => {
    const request = new Request("http://localhost:3000/api/capture", {
      method: "POST",
      headers: { origin: "http://localhost:3000", "sec-fetch-site": "same-origin" },
    });
    expect(admitBrowserMutation(request)).toBeNull();
  });
});
