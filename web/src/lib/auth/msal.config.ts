/**
 * MSAL configuration seam — inert until real Entra registration exists.
 *
 * WP-02 ships the synthetic identity provider only. This module pins the
 * shape the real MSAL wiring will take so the swap is a configuration
 * change, not a redesign. No client id, no live tenant id, no secrets.
 */

export interface MsalSeamConfig {
  /** Entra application (client) id. Empty until registration exists. */
  readonly clientId: string;
  /** Authority URL. Empty until a real tenant is configured. */
  readonly authority: string;
  readonly redirectUri: string;
  /** Scopes the app will request when live. */
  readonly scopes: readonly string[];
  /** True when the config is complete enough to attempt a real sign-in. */
  readonly enabled: boolean;
}

export function msalSeamConfig(): MsalSeamConfig {
  const clientId = process.env.NEXT_PUBLIC_MYPA_ENTRA_CLIENT_ID ?? "";
  const tenantId = process.env.NEXT_PUBLIC_MYPA_ENTRA_TENANT_ID ?? "";
  return {
    clientId,
    authority: tenantId ? `https://login.microsoftonline.com/${tenantId}` : "",
    redirectUri: "/auth/callback",
    scopes: ["openid", "profile", "User.Read"],
    enabled: clientId.length > 0 && tenantId.length > 0,
  };
}
