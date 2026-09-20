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
import type { PrincipalSession } from "@/contracts/identity";

import { diagnosticsPrincipalBinding, parseDiagnosticsPreference } from "./preference";

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
}): Promise<boolean> {
  let binding: string;
  try {
    binding = await diagnosticsPrincipalBinding(input.principal.principalId);
  } catch {
    return false;
  }
  return parseDiagnosticsPreference(input.cookieValue, binding);
}
