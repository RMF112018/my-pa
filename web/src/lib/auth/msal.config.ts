/**
 * MSAL configuration seam — inert until a real Entra registration exists.
 *
 * This module pins the shape the real MSAL wiring takes so that activating it is
 * a configuration change rather than a redesign. No client id, no live tenant
 * id, no secret.
 *
 * **Sign-in requests no Microsoft Graph scope, and that is a decision rather
 * than an omission.** This seam asked for `User.Read` until WP-05. `User.Read`
 * is a *Graph resource* scope: requesting it makes signing in depend on Graph
 * consent, so a tenant that has not consented to Graph — or an operator who has
 * deliberately left Graph off, which is this product's default — cannot sign in
 * at all. Graph is retained and off; the sign-in path must not be the thing that
 * turns it on.
 *
 * What is requested instead is the OIDC set and nothing else: `openid` and
 * `profile` are what produce an ID token with the `tid` and `oid` claims the
 * Principal is resolved from, and `offline_access` is what allows a refresh
 * without a second interactive sign-in. An application API scope is added *only*
 * when one is configured, and `apiScope` refuses a Graph resource scope
 * outright — a value pointing at Graph would reintroduce the dependency under a
 * different variable name.
 */

/** Scopes every sign-in requests. OIDC only; no resource server appears here. */
export const SIGN_IN_SCOPES: readonly string[] = ["openid", "profile", "offline_access"] as const;

/**
 * Hosts and prefixes that mean "this scope is served by Microsoft Graph".
 *
 * Both spellings, because an application scope is configured as a URI and Graph
 * is reachable under two: the resource URI and the national-cloud host set. The
 * bare-permission form (`User.Read`, `Mail.Read`) is covered too, since a scope
 * with no resource prefix resolves against the default resource, which for these
 * names is Graph.
 */
const GRAPH_MARKERS: readonly string[] = [
  "graph.microsoft.com",
  "graph.microsoft.us",
  "graph.microsoft.de",
  "microsoftgraph.com",
  "00000003-0000-0000-c000-000000000000",
] as const;

/** Permission names that are Graph's whether or not a resource is spelled out. */
const GRAPH_PERMISSION = /^[A-Za-z]+\.[A-Za-z]+(\.[A-Za-z]+)?$/;

/** `true` when `scope` names a Microsoft Graph resource. */
export function isGraphScope(scope: string): boolean {
  const lowered = scope.trim().toLowerCase();
  if (GRAPH_MARKERS.some((marker) => lowered.includes(marker))) return true;
  // A bare `Noun.Verb` permission with no resource URI in front of it.
  return !lowered.includes("/") && GRAPH_PERMISSION.test(scope.trim());
}

export interface MsalSeamConfig {
  /** Entra application (client) id. Empty until registration exists. */
  readonly clientId: string;
  /** Authority URL. Empty until a real tenant is configured. */
  readonly authority: string;
  readonly redirectUri: string;
  /** Scopes the app requests when live. Never a Graph resource scope. */
  readonly scopes: readonly string[];
  /** True when the config is complete enough to attempt a real sign-in. */
  readonly enabled: boolean;
}

/**
 * The application's own API scope, when one is configured and legitimate.
 *
 * A configured value that names Graph is dropped rather than honoured: this
 * variable exists to let the app request a token for *its own* backend, and
 * accepting a Graph URI here would be the removed Graph dependency arriving
 * through configuration instead of through code.
 */
export function apiScope(): string | null {
  // Server-side BFF flow. A gateway scope is configuration, but it is not a
  // browser setting and therefore deliberately has no NEXT_PUBLIC_ prefix.
  const configured = process.env.MYPA_ENTRA_API_SCOPE?.trim();
  if (!configured || isGraphScope(configured)) return null;
  return configured;
}

export function msalSeamConfig(): MsalSeamConfig {
  const clientId = process.env.MYPA_ENTRA_CLIENT_ID ?? "";
  const tenantId = process.env.MYPA_ENTRA_HOME_TENANT_ID ?? "";
  const redirectUri = process.env.MYPA_ENTRA_REDIRECT_URI ?? "";
  const hasCredential = (process.env.MYPA_ENTRA_CLIENT_SECRET?.trim().length ?? 0) > 0;
  const own = apiScope();
  return {
    clientId,
    authority: tenantId ? `https://login.microsoftonline.com/${tenantId}` : "",
    redirectUri,
    scopes: own ? [...SIGN_IN_SCOPES, own] : [...SIGN_IN_SCOPES],
    enabled:
      clientId.length > 0 &&
      tenantId.length > 0 &&
      redirectUri.length > 0 &&
      hasCredential &&
      own !== null,
  };
}
