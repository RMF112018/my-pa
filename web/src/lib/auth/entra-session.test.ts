// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthenticationResult, AuthorizationCodeRequest, AuthorizationUrlRequest } from "@azure/msal-node";
import { establishValidatedEntraSession } from "@/lib/auth/entra-session";
import {
  beginEntraAuthorization,
  completeEntraAuthorization,
  resetEntraFlowRegistry,
  type AuthorizationCodeClient,
} from "@/lib/auth/entra-code-flow";
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
  resetEntraFlowRegistry();
  resetSessionRegistry();
  vi.unstubAllEnvs();
});

function configureFlow(): void {
  vi.stubEnv("MYPA_AUTH_MODE", "entra");
  vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", TENANT);
  vi.stubEnv("MYPA_ENTRA_CLIENT_ID", "client-id");
  vi.stubEnv("MYPA_ENTRA_CLIENT_SECRET", "server-held-client-secret");
  vi.stubEnv("MYPA_ENTRA_REDIRECT_URI", "https://app.example.test/auth/callback");
  vi.stubEnv("MYPA_ENTRA_API_SCOPE", "api://my-pa/access_as_user");
  vi.stubEnv("MYPA_SESSION_SECRET", "a-session-secret-with-at-least-32-characters");
}

class FakeCodeClient implements AuthorizationCodeClient {
  start?: AuthorizationUrlRequest;
  completion?: AuthorizationCodeRequest;

  async getAuthCodeUrl(request: AuthorizationUrlRequest): Promise<string> {
    this.start = request;
    return `https://login.example.test/authorize?state=${encodeURIComponent(request.state ?? "")}`;
  }

  async acquireTokenByCode(request: AuthorizationCodeRequest): Promise<AuthenticationResult> {
    this.completion = request;
    return {
      accessToken: "validated-access-token-never-in-cookie",
      idTokenClaims: { ...CLAIMS, nonce: this.start?.nonce },
    } as unknown as AuthenticationResult;
  }
}

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

describe("authorization-code callback", () => {
  it("uses PKCE S256, validates state+nonce, consumes the code, and keeps bearer server-side", async () => {
    configureFlow();
    const client = new FakeCodeClient();
    const started = await beginEntraAuthorization(client, 100);
    expect(client.start).toMatchObject({
      state: started.state,
      codeChallengeMethod: "S256",
      redirectUri: "https://app.example.test/auth/callback",
    });
    expect(client.start?.codeChallenge).toMatch(/^[A-Za-z0-9_-]{43}$/);

    const established = await completeEntraAuthorization(
      { code: "one-time-code", state: started.state, stateCookie: started.state },
      client,
      101,
    );
    expect(client.completion?.codeVerifier).toMatch(/^[A-Za-z0-9_-]{80,90}$/);
    expect(established.cookie).not.toContain("one-time-code");
    expect(established.cookie).not.toContain("validated-access-token");
    expect(gatewayBearerForPrincipal(established.principal.principalId)).toBe(
      "validated-access-token-never-in-cookie",
    );

    await expect(
      completeEntraAuthorization(
        { code: "replayed", state: started.state, stateCookie: started.state },
        client,
        102,
      ),
    ).rejects.toThrow(/absent, expired, or already consumed/);
  });

  it("refuses a missing or mismatched callback state before code exchange", async () => {
    configureFlow();
    const client = new FakeCodeClient();
    const started = await beginEntraAuthorization(client, 100);
    await expect(
      completeEntraAuthorization(
        { code: "code", state: started.state, stateCookie: "different" },
        client,
        101,
      ),
    ).rejects.toThrow(/state/);
    expect(client.completion).toBeUndefined();
  });

  it("refuses a nonce mismatch after MSAL exchange and establishes no bearer", async () => {
    configureFlow();
    const client = new FakeCodeClient();
    const started = await beginEntraAuthorization(client, 100);
    client.acquireTokenByCode = async (request) => {
      client.completion = request;
      return {
        accessToken: "validated-access-token-never-in-cookie",
        idTokenClaims: { ...CLAIMS, nonce: "wrong" },
      } as unknown as AuthenticationResult;
    };
    await expect(
      completeEntraAuthorization(
        { code: "code", state: started.state, stateCookie: started.state },
        client,
        101,
      ),
    ).rejects.toThrow(/nonce/);
    expect(gatewayBearerForPrincipal(`entra-${CLAIMS.oid}`)).toBeNull();
  });

  it("refuses an expired request without exchanging the authorization code", async () => {
    configureFlow();
    const client = new FakeCodeClient();
    const started = await beginEntraAuthorization(client, 100);
    await expect(
      completeEntraAuthorization(
        { code: "code", state: started.state, stateCookie: started.state },
        client,
        701,
      ),
    ).rejects.toThrow(/expired/);
    expect(client.completion).toBeUndefined();
  });
});
