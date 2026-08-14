/**
 * Which identity provider this deployment runs, and which tenant is home.
 *
 * Both are configuration, both fail closed, and neither has a default that
 * happens to work. `MYPA_AUTH_MODE` unset is a refusal in the same class as
 * `MissingSessionSecretError`: a deployment that has not said how it
 * authenticates has not been configured, and guessing "synthetic" for it would
 * hand a working sign-in to anyone who could reach the page.
 *
 * There are exactly three modes and no inference between them:
 *
 * * `synthetic` — the two fixed development principals. Refused outright when
 *   `NODE_ENV === "production"`, because a production build with a
 *   passwordless sign-in button is not a misconfiguration a warning fixes.
 * * `entra` — real sign-in. The synthetic principals are unreachable in this
 *   mode; `POST /api/session` refuses a synthetic key rather than ignoring it.
 * * `local_operator` — the credentialed single-operator production mode. The
 *   server selects the repository-defined deterministic local Principal; the
 *   caller supplies only the operator credential and cannot choose identity.
 *
 * The home tenant is configuration only for the claim-based modes
 * (`MYPA_ENTRA_HOME_TENANT_ID`).
 * In `synthetic` mode it may be left unset and resolves to the synthetic
 * constant, which is the one place the synthetic tenant is allowed to be a
 * default — it is not a tenant, and the mode is already refused in production.
 * In `entra` mode it must be set, or the deployment cannot say whose tokens it
 * accepts and refuses to answer at all.
 */
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";

export type AuthMode = "synthetic" | "entra" | "local_operator";

export const AUTH_MODES: readonly AuthMode[] = ["synthetic", "entra", "local_operator"] as const;

/** Raised when the deployment has not said how it authenticates. */
export class MissingAuthModeError extends Error {
  constructor(configured: string | undefined) {
    super(
      configured === undefined || configured.trim() === ""
        ? "MYPA_AUTH_MODE is not set. It must be 'synthetic' (fixed development " +
            "principals, refused in production), 'local_operator' (credentialed single operator), " +
            "or 'entra' (real sign-in). There is no " +
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

/** Raised when `entra` mode is selected without the tenant it must accept. */
export class MissingHomeTenantError extends Error {
  constructor() {
    super(
      "MYPA_AUTH_MODE is 'entra' and MYPA_ENTRA_HOME_TENANT_ID is not set. A " +
        "deployment that cannot say which tenant is home cannot reject a foreign one.",
    );
    this.name = "MissingHomeTenantError";
  }
}

/** Raised if claim-based tenant resolution is attempted in local-operator mode. */
export class LocalOperatorHasNoHomeTenantError extends Error {
  constructor() {
    super(
      "MYPA_AUTH_MODE is 'local_operator'; its deterministic Principal is selected " +
        "server-side and no Entra-shaped home tenant may be resolved for it.",
    );
    this.name = "LocalOperatorHasNoHomeTenantError";
  }
}

/** The configured mode, or a refusal. Never a default. */
export function authMode(): AuthMode {
  const configured = process.env.MYPA_AUTH_MODE?.trim();
  if (configured !== "synthetic" && configured !== "entra" && configured !== "local_operator") {
    throw new MissingAuthModeError(process.env.MYPA_AUTH_MODE);
  }
  if (configured === "synthetic" && process.env.NODE_ENV === "production") {
    throw new SyntheticModeInProductionError();
  }
  return configured;
}

/** The tenant whose tokens this deployment accepts, or a refusal. */
export function homeTenantId(): string {
  const configured = process.env.MYPA_ENTRA_HOME_TENANT_ID?.trim();
  if (configured) return configured;
  const mode = authMode();
  if (mode === "synthetic") return SYNTHETIC_MOSS_TENANT_ID;
  if (mode === "local_operator") throw new LocalOperatorHasNoHomeTenantError();
  throw new MissingHomeTenantError();
}
