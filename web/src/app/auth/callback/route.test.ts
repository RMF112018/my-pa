// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const { complete } = vi.hoisted(() => ({ complete: vi.fn() }));
vi.mock("@/lib/auth/entra-code-flow", () => ({
  completeEntraAuthorization: complete,
  ENTRA_FLOW_COOKIE_NAME: "mypa_entra_flow",
}));

import { GET } from "@/app/auth/callback/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";

const ORIGIN = "https://app.example.test";

beforeEach(() => vi.stubEnv("MYPA_CANONICAL_ORIGIN", ORIGIN));

function callback(query: string, stateCookie?: string): NextRequest {
  const request = new NextRequest(`${ORIGIN}/auth/callback?${query}`);
  if (stateCookie) request.cookies.set("mypa_entra_flow", stateCookie);
  return request;
}

afterEach(() => {
  complete.mockReset();
  vi.unstubAllEnvs();
});

describe("Entra callback route", () => {
  it("turns provider errors into one generic redirect without reflecting details", async () => {
    const marker = "sensitive-provider-description";
    const response = await GET(callback(`error=access_denied&error_description=${marker}`));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`${ORIGIN}/sign-in?error=entra_callback`);
    expect(response.headers.get("location")).not.toContain(marker);
    expect(complete).not.toHaveBeenCalled();
  });

  it("passes only code, state, and the opaque state cookie to completion", async () => {
    complete.mockResolvedValue({ cookie: "signed-app-session", principal: {} });
    const response = await GET(callback("code=one-time-code&state=opaque-state", "opaque-state"));
    expect(complete).toHaveBeenCalledWith({
      code: "one-time-code",
      state: "opaque-state",
      stateCookie: "opaque-state",
    });
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`${ORIGIN}/today`);
    expect(response.cookies.get(SESSION_COOKIE_NAME)?.value).toBe("signed-app-session");
  });

  it("reflects neither authorization code nor exchange failure", async () => {
    complete.mockRejectedValue(new Error("token response contained a secret marker"));
    const response = await GET(callback("code=sensitive-code&state=opaque-state", "opaque-state"));
    const rendered = `${response.headers.get("location")} ${response.headers.get("set-cookie")}`;
    expect(rendered).not.toContain("sensitive-code");
    expect(rendered).not.toContain("secret marker");
    expect(response.headers.get("location")).toBe(`${ORIGIN}/sign-in?error=entra_callback`);
  });
});
