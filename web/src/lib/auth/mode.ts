/**
 * Which identity provider this deployment runs, and which tenant is home.
 *
 * Both are configuration, both fail closed, and neither has a default that
 * happens to work. `MYPA_AUTH_MODE` unset is a refusal: a deployment that has
 * not said how it authenticates has not been configured, and guessing
 * "synthetic" for it would hand a working sign-in to anyone who could reach
 * the page.
 *
 * There are exactly two web modes and no inference between them:
 *
 * * `synthetic` — the two fixed development principals. Refused outright when
 *   `NODE_ENV === "production"`, because a production build with a
 *   passwordless sign-in button is not a misconfiguration a warning fixes.
 * * `passkey` — production web authentication. Sessions are issued by Python
 *   after WebAuthn or recovery; `POST /api/session` does not mint a synthetic
 *   identity.
 *
 * `entra` and `local_operator` are not web modes. An operator who still sets
 * them gets the same refusal as any other unknown value.
 *
 * The home tenant is configuration only when one is actually configured
 * (`MYPA_ENTRA_HOME_TENANT_ID`). In `synthetic` mode it may be left unset and
 * resolves to the synthetic constant — the one place the synthetic tenant is
 * allowed to be a default, because the mode is already refused in production.
 * In `passkey` mode it is not required and is not invented.
 */
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";

export type AuthMode = "synthetic" | "passkey";

export const AUTH_MODES: readonly AuthMode[] = ["synthetic", "passkey"] as const;

/** Raised when the deployment has not said how it authenticates. */
export class MissingAuthModeError extends Error {
  constructor(configured: string | undefined) {
    super(
      configured === undefined || configured.trim() === ""
        ? "MYPA_AUTH_MODE is not set. It must be 'synthetic' (fixed development " +
            "principals, refused in production) or 'passkey' (WebAuthn). There is no " +
            "default: an unset value would silently select a passwordless sign-in."
        : `MYPA_AUTH_MODE names an unknown mode. It must be one of ${AUTH_MODES.join(", ")}.`,
    );
    this.name = "MissingAuthModeError";
  }
}

/** Raised when a production build asks for the synthetic identity provider. */
export class SyntheticModeInProductionError extends Error {
  constructor() {
    super(
      "MYPA_AUTH_MODE is 'synthetic' and NODE_ENV is 'production'. The synthetic " +
        "provider signs anyone in as a fixed principal with no credential; it is a " +
        "development mode and a production build refuses it rather than warning.",
    );
    this.name = "SyntheticModeInProductionError";
  }
}

/** The configured mode, or a refusal. Never a default. */
export function authMode(): AuthMode {
  const configured = process.env.MYPA_AUTH_MODE?.trim();
  if (configured !== "synthetic" && configured !== "passkey") {
    throw new MissingAuthModeError(process.env.MYPA_AUTH_MODE);
  }
  if (configured === "synthetic" && process.env.NODE_ENV === "production") {
    throw new SyntheticModeInProductionError();
  }
  return configured;
}

/**
 * The tenant whose tokens this deployment accepts, when that is configured.
 *
 * A set `MYPA_ENTRA_HOME_TENANT_ID` is always that value. Synthetic mode may
 * default to the synthetic Moss tenant. Passkey mode does not require the
 * variable and does not invent an Entra tenant.
 */
export function homeTenantId(): string {
  const configured = process.env.MYPA_ENTRA_HOME_TENANT_ID?.trim();
  if (configured) return configured;
  if (authMode() === "synthetic") return SYNTHETIC_MOSS_TENANT_ID;
  return "";
}
