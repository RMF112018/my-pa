/**
 * Token-claim validation — frontend parity with
 * `my_pa.domain.identity.user_account.validate_token_claims` and
 * `reject_caller_supplied_principal`.
 *
 * Identity derives ONLY from validated claims. Any caller-supplied
 * `principal_id` / `tid` / `oid` in a request payload is rejected before
 * the claims are even considered.
 */
import { FORBIDDEN_IDENTITY_FIELDS, type EntraTokenClaims } from "@/contracts/identity";

export class TokenClaimsError extends Error {}
export class MissingClaimError extends TokenClaimsError {}
export class ForeignTenantError extends TokenClaimsError {}
export class CallerSuppliedPrincipalError extends TokenClaimsError {}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Validate Entra-shaped claims against the configured home tenant. Fail closed. */
export function validateTokenClaims(
  claims: Record<string, unknown>,
  homeTenantId: string,
): EntraTokenClaims {
  const tid = claims["tid"];
  const oid = claims["oid"];
  if (typeof tid !== "string" || tid.length === 0) {
    throw new MissingClaimError("token claims are missing a usable `tid`");
  }
  if (typeof oid !== "string" || !UUID_PATTERN.test(oid)) {
    throw new MissingClaimError("token claims are missing a usable `oid`");
  }
  if (tid.toLowerCase() !== homeTenantId.toLowerCase()) {
    throw new ForeignTenantError("token tenant is not the Moss home tenant");
  }
  const upn = typeof claims["upn"] === "string" ? (claims["upn"] as string) : "";
  const name = typeof claims["name"] === "string" ? (claims["name"] as string) : "";
  return { tid, oid, upn, name };
}

/**
 * Walk a request payload and refuse any identity-bearing field. The token is
 * the only identity input; a payload that tries to name a principal is an
 * attack or a defect, never a convenience.
 */
export function rejectCallerSuppliedPrincipal(payload: unknown, path = "$"): void {
  if (payload === null || typeof payload !== "object") return;
  if (Array.isArray(payload)) {
    payload.forEach((item, i) => rejectCallerSuppliedPrincipal(item, `${path}[${i}]`));
    return;
  }
  for (const [key, value] of Object.entries(payload as Record<string, unknown>)) {
    if ((FORBIDDEN_IDENTITY_FIELDS as readonly string[]).includes(key)) {
      throw new CallerSuppliedPrincipalError(
        `caller-supplied identity field \`${key}\` at ${path} is rejected`,
      );
    }
    rejectCallerSuppliedPrincipal(value, `${path}.${key}`);
  }
}
