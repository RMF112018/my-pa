// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { establishValidatedEntraSession } from "@/lib/auth/entra-session";
import { gatewayBearerForPrincipal, resetSessionRegistry } from "@/lib/auth/session-registry";
import { verifySession } from "@/lib/auth/session";

const TENANT = "11111111-2222-3333-4444-555555555555";
const CLAIMS = {
  tid: TENANT,
  oid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  upn: "operator@example.test",
  name: "Operator",
};

afterEach(() => {
  resetSessionRegistry();
  vi.unstubAllEnvs();
});

describe("validated Entra session establishment", () => {
  it("binds the cookie identity and server-held gateway token to the same tid+oid", async () => {
    vi.stubEnv("MYPA_HOME_TENANT_ID", TENANT);
    vi.stubEnv("MYPA_SESSION_SECRET", "a-session-secret-with-at-least-32-characters");
    const established = await establishValidatedEntraSession({
      validationAuthority: "msal",
      accessToken: "validated-access-token-never-in-cookie",
      claims: CLAIMS,
    });
    expect((await verifySession(established.cookie))?.tid).toBe(TENANT);
    expect((await verifySession(established.cookie))?.oid).toBe(CLAIMS.oid);
    expect(established.cookie).not.toContain("validated-access-token");
    expect(gatewayBearerForPrincipal(established.principal.principalId)).toBe(
      "validated-access-token-never-in-cookie",
    );
  });

  it("refuses a foreign tenant before registering a credential", async () => {
    vi.stubEnv("MYPA_HOME_TENANT_ID", TENANT);
    vi.stubEnv("MYPA_SESSION_SECRET", "a-session-secret-with-at-least-32-characters");
    await expect(
      establishValidatedEntraSession({
        validationAuthority: "msal",
        accessToken: "validated-access-token-never-in-cookie",
        claims: { ...CLAIMS, tid: "99999999-2222-3333-4444-555555555555" },
      }),
    ).rejects.toThrow();
  });
});
