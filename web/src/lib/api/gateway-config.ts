/**
 * The three configuration questions the BFF must answer before it can serve,
 * and the refusals it answers with when a deployment has not.
 *
 * None of them has a default that happens to work. `MYPA_AUTH_MODE` established
 * the rule in WP-05 and these follow it: an unset value is a refusal that has to
 * reach an operator, not a guess that quietly picks the permissive branch. The
 * failure mode being guarded is specific and has happened here before — a
 * fallback literal in `session.ts` meant a deployment missing one variable
 * accepted any session anyone minted, and nothing said so.
 *
 * * `MYPA_GATEWAY_URL` — where the Python gateway is. **No default at all**, not
 *   even loopback: a default would mean a deployment that configured nothing
 *   still sent requests somewhere, and "somewhere" is a decision only an
 *   operator may make. Unset is a refusal, and the refusal is never a fallback
 *   to fixtures — the two are separate switches precisely so that losing the
 *   backend cannot silently become serving synthetic data.
 * * `MYPA_GATEWAY_AUTH_MODE` — how the gateway this BFF talks to establishes its
 *   acting Principal, mirroring the Python `MY_PA_AUTH_MODE` on the other end.
 *   The value is not inferred from anything and is never chosen by a browser.
 * * `MYPA_DATA_PROVIDER` — the synthetic switch. Unset means **not synthetic**,
 *   which is the fail-closed direction: absence of a decision cannot produce
 *   fixture data. Set to anything other than `synthetic` it is a refusal rather
 *   than a silent "well, not synthetic then", because a typo that lands on the
 *   safe branch teaches nothing and a typo that lands on the unsafe branch is
 *   the whole hazard.
 */

/** Raised when the deployment has not said where the Python gateway is. */
export class MissingGatewayUrlError extends Error {
  constructor(detail: string) {
    super(
      `MYPA_GATEWAY_URL ${detail}. It must be an absolute http(s) URL naming the ` +
        "Python gateway. There is no default: a BFF that guessed a backend address " +
        "would send a principal's request somewhere nobody chose.",
    );
    this.name = "MissingGatewayUrlError";
  }
}

/** Raised when the deployment has not said how the gateway authenticates. */
export class MissingGatewayAuthModeError extends Error {
  constructor(configured: string | undefined) {
    super(
      configured === undefined || configured.trim() === ""
        ? "MYPA_GATEWAY_AUTH_MODE is not set. It must be 'local_operator' (the gateway " +
            "serves its fixed process principal and no credential is sent) or 'entra' " +
            "(the gateway requires a bearer token). There is no default, because the two " +
            "differ in what the response may truthfully claim about whose data it is."
        : "MYPA_GATEWAY_AUTH_MODE names an unknown mode. It must be one of " +
            `${GATEWAY_AUTH_MODES.join(", ")}.`,
    );
    this.name = "MissingGatewayAuthModeError";
  }
}

/** Raised when `MYPA_DATA_PROVIDER` is set to something that is not a provider. */
export class UnknownDataProviderError extends Error {
  constructor() {
    super(
      "MYPA_DATA_PROVIDER is set to a value that is not 'synthetic'. It is refused " +
        "rather than treated as unset: the only reason to set this variable is to turn " +
        "the synthetic provider on, so a value that fails to do so is a mistake an " +
        "operator has to see.",
    );
    this.name = "UnknownDataProviderError";
  }
}

/** Raised when a production build asks for the synthetic data provider. */
export class SyntheticDataInProductionError extends Error {
  constructor() {
    super(
      "MYPA_DATA_PROVIDER is 'synthetic' and NODE_ENV is 'production'. Fixture data " +
        "is development scaffolding; a production build refuses it rather than " +
        "labelling it and serving it anyway.",
    );
    this.name = "SyntheticDataInProductionError";
  }
}

/** How the Python gateway on the other end establishes its acting Principal. */
export type GatewayAuthMode = "local_operator" | "entra";

export const GATEWAY_AUTH_MODES: readonly GatewayAuthMode[] = [
  "local_operator",
  "entra",
] as const;

/**
 * The gateway's base URL, or a refusal.
 *
 * A trailing slash is stripped so the joined path is `…/v1/{capability}` and not
 * `…//v1/{capability}`, and the scheme is checked so a `file:` or `data:` value
 * cannot become a request this process makes on a caller's behalf.
 */
export function gatewayBaseUrl(): string {
  const configured = process.env.MYPA_GATEWAY_URL?.trim();
  if (!configured) throw new MissingGatewayUrlError("is not set");
  let parsed: URL;
  try {
    parsed = new URL(configured);
  } catch {
    throw new MissingGatewayUrlError("is not a URL");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new MissingGatewayUrlError("does not name an http(s) endpoint");
  }
  return `${parsed.origin}${parsed.pathname.replace(/\/+$/, "")}`;
}

/** The gateway's authentication mode, or a refusal. Never inferred. */
export function gatewayAuthMode(): GatewayAuthMode {
  const configured = process.env.MYPA_GATEWAY_AUTH_MODE?.trim();
  if (configured !== "local_operator" && configured !== "entra") {
    throw new MissingGatewayAuthModeError(process.env.MYPA_GATEWAY_AUTH_MODE);
  }
  return configured;
}

/**
 * Whether the synthetic data provider is on. Off unless explicitly turned on.
 *
 * There is deliberately no `||` and no `??` here: `unset` reaches the `false`
 * return by falling off the end of the checks, not by being coalesced with a
 * default, so nothing in this function can be edited into a fallback without the
 * edit being visible.
 */
export function syntheticDataEnabled(): boolean {
  const configured = process.env.MYPA_DATA_PROVIDER?.trim();
  if (configured === undefined || configured === "") return false;
  if (configured !== "synthetic") throw new UnknownDataProviderError();
  if (process.env.NODE_ENV === "production") throw new SyntheticDataInProductionError();
  return true;
}
