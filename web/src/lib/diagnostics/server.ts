/**
 * Authenticated server resolution of the diagnostics preference.
 *
 * This runs **after** the Principal has been established, never before, and
 * never from anything the browser said other than the HttpOnly cookie it
 * cannot write. The order matters: the binding is derived from the resolved
 * Principal, so there is no point in the request at which a caller-supplied
 * identity could select which stored preference gets honoured.
 *
 * The return value is a plain boolean because the contract has two states. An
 * "unresolved" third state would have to be rendered as something, and every
 * candidate rendering is a diagnostic residue; unresolved is simply OFF.
 */
import { cache } from "react";
import { cookies } from "next/headers";

import type { PrincipalSession } from "@/contracts/identity";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";

import {
  DIAGNOSTICS_COOKIE,
  DIAGNOSTICS_OFF,
  diagnosticsPrincipalBinding,
  parseDiagnosticsPreference,
  type ResolvedDiagnosticsPreference,
} from "./preference";

/**
 * Resolve whether diagnostics are ON for this Principal on this browser.
 *
 * Any failure to compute the binding is OFF. `crypto.subtle` is present in both
 * the Node and Edge runtimes this application targets, so a throw here means
 * something is badly wrong — and the fail-closed direction for "something is
 * badly wrong" is not to start rendering engineering detail.
 */
export async function resolveDiagnosticsPreference(input: {
  readonly principal: PrincipalSession;
  readonly cookieValue: string | undefined;
}): Promise<ResolvedDiagnosticsPreference> {
  let binding: string;
  try {
    binding = await diagnosticsPrincipalBinding(input.principal.principalId);
  } catch {
    return DIAGNOSTICS_OFF;
  }
  return parseDiagnosticsPreference(input.cookieValue, binding);
}

/**
 * The resolved preference for the current request, memoised per render pass.
 *
 * Server components need this without threading a boolean down through every
 * page, and they must not each pay for a fresh session resolution. React's
 * `cache` makes the whole render tree share one answer per request.
 *
 * It resolves the Principal itself rather than taking one, because the callers
 * are leaf presentation components that have no reason to hold identity. A
 * request with no usable session resolves OFF, like every other unresolved
 * state.
 */
export const serverDiagnosticsEnabled = cache(async (): Promise<boolean> => {
  try {
    const store = await cookies();
    const principal = await resolveSessionPrincipal(store.get(SESSION_COOKIE_NAME)?.value);
    if (!principal) return false;
    const resolved = await resolveDiagnosticsPreference({
      principal,
      cookieValue: store.get(DIAGNOSTICS_COOKIE)?.value,
    });
    return resolved.enabled;
  } catch {
    return false;
  }
});
