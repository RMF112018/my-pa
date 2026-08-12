/**
 * Server-only Entra authorization-code + PKCE flow.
 *
 * The browser receives only an opaque state value and the Microsoft authorize
 * URL.  The PKCE verifier, nonce, client credential, authorization code, and
 * resulting access token stay in this Node process.  The callback consumes its
 * state before exchanging the code, so a replay cannot repeat the exchange.
 *
 * Live tenant registration remains configuration: this module contains no
 * tenant, client id, credential, or fallback.  Its injected client contract is
 * also the test seam that proves the complete protocol without contacting a
 * tenant.
 */
import {
  ConfidentialClientApplication,
  type AuthenticationResult,
  type AuthorizationCodeRequest,
  type AuthorizationUrlRequest,
} from "@azure/msal-node";

import { establishValidatedEntraSession } from "@/lib/auth/entra-session";
import { apiScope, SIGN_IN_SCOPES } from "@/lib/auth/msal.config";

export const ENTRA_FLOW_COOKIE_NAME = "mypa_entra_flow";
export const ENTRA_FLOW_MAX_AGE_SECONDS = 10 * 60;

interface PendingAuthorization {
  readonly nonce: string;
  readonly verifier: string;
  readonly expiresAt: number;
}

interface FlowRegistry {
  readonly pending: Map<string, PendingAuthorization>;
}

const FLOW_REGISTRY_KEY = Symbol.for("my-pa.web.auth.entra-code-flow.v1");
type RegistryHolder = typeof globalThis & { [FLOW_REGISTRY_KEY]?: FlowRegistry };

function registry(): FlowRegistry {
  const holder = globalThis as RegistryHolder;
  const existing = holder[FLOW_REGISTRY_KEY];
  if (existing) return existing;
  const created = { pending: new Map<string, PendingAuthorization>() };
  holder[FLOW_REGISTRY_KEY] = created;
  return created;
}

function base64url(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64url");
}

function randomOpaque(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} must be configured for Entra sign-in`);
  return value;
}

export interface EntraServerConfig {
  readonly clientId: string;
  readonly clientSecret: string;
  readonly tenantId: string;
  readonly authority: string;
  readonly redirectUri: string;
  readonly scopes: readonly string[];
}

/** Server-held configuration. No secret uses a NEXT_PUBLIC_ name. */
export function entraServerConfig(): EntraServerConfig {
  const tenantId = required("MYPA_ENTRA_HOME_TENANT_ID");
  const ownScope = apiScope();
  if (!ownScope) {
    throw new Error("MYPA_ENTRA_API_SCOPE must name this application's gateway scope");
  }
  return {
    clientId: required("MYPA_ENTRA_CLIENT_ID"),
    clientSecret: required("MYPA_ENTRA_CLIENT_SECRET"),
    tenantId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri: required("MYPA_ENTRA_REDIRECT_URI"),
    scopes: [...SIGN_IN_SCOPES, ownScope],
  };
}

export interface AuthorizationCodeClient {
  getAuthCodeUrl(request: AuthorizationUrlRequest): Promise<string>;
  acquireTokenByCode(request: AuthorizationCodeRequest): Promise<AuthenticationResult>;
}

function msalClient(config: EntraServerConfig): AuthorizationCodeClient {
  return new ConfidentialClientApplication({
    auth: {
      clientId: config.clientId,
      authority: config.authority,
      clientSecret: config.clientSecret,
    },
  });
}

export interface AuthorizationStart {
  readonly location: string;
  readonly state: string;
}

export async function beginEntraAuthorization(
  client?: AuthorizationCodeClient,
  now = Math.floor(Date.now() / 1000),
): Promise<AuthorizationStart> {
  const config = entraServerConfig();
  const state = randomOpaque(32);
  const nonce = randomOpaque(32);
  const verifier = randomOpaque(64);
  registry().pending.set(state, {
    nonce,
    verifier,
    expiresAt: now + ENTRA_FLOW_MAX_AGE_SECONDS,
  });
  try {
    const location = await (client ?? msalClient(config)).getAuthCodeUrl({
      scopes: [...config.scopes],
      redirectUri: config.redirectUri,
      responseMode: "query",
      state,
      nonce,
      codeChallenge: await challengeFor(verifier),
      codeChallengeMethod: "S256",
    });
    return { location, state };
  } catch (error) {
    registry().pending.delete(state);
    throw error;
  }
}

export interface AuthorizationCompletion {
  readonly code: string;
  readonly state: string;
  readonly stateCookie: string | undefined;
}

export async function completeEntraAuthorization(
  completion: AuthorizationCompletion,
  client?: AuthorizationCodeClient,
  now = Math.floor(Date.now() / 1000),
) {
  if (!completion.code || !completion.state || completion.stateCookie !== completion.state) {
    throw new Error("the Entra callback state is missing or does not match");
  }
  const pending = registry().pending.get(completion.state);
  // Consume before network I/O. A failed exchange is restarted, never replayed.
  registry().pending.delete(completion.state);
  if (!pending || pending.expiresAt <= now) {
    throw new Error("the Entra authorization request is absent, expired, or already consumed");
  }

  const config = entraServerConfig();
  const result = await (client ?? msalClient(config)).acquireTokenByCode({
    code: completion.code,
    scopes: [...config.scopes],
    redirectUri: config.redirectUri,
    codeVerifier: pending.verifier,
    state: completion.state,
  });
  const claims = result.idTokenClaims as Readonly<Record<string, unknown>> | undefined;
  if (!claims || claims["nonce"] !== pending.nonce) {
    throw new Error("the validated Entra result did not carry the request nonce");
  }
  return establishValidatedEntraSession({
    validationAuthority: "msal",
    accessToken: result.accessToken,
    claims,
  });
}

/** Test-only reset; it contains no credentials or result tokens. */
export function resetEntraFlowRegistry(): void {
  registry().pending.clear();
}
