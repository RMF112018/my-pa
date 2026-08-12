/**
 * Synthetic identity provider — development only.
 *
 * Two fixed principals in the synthetic Moss home tenant. No live tenant
 * identifiers, no live personal data. The tenant id matches the synthetic
 * MOSS_TENANT used by the Python identity test suite so cross-tier fixtures
 * agree on what "home tenant" means.
 *
 * **The catalogue is not the admissible set** (`D-15`). WP-06's reviewer signed
 * in as `synthetic-a`, captured a note, signed in as `synthetic-b`, and read A's
 * capture back through `/api/library` — including a full-text match on A's exact
 * text. That was possible because the two tiers disagreed about how many
 * identities exist: this tier offered two sign-ins while the Python gateway, in
 * `MYPA_GATEWAY_AUTH_MODE=local_operator`, serves **one** fixed process
 * principal regardless of which browser session is signed in. Two costumes, one
 * person. It was disclosed (`LOCAL_OPERATOR_LIMITATION` on every response) and
 * not prevented, and WP-07 makes that read carry durable user-authored text.
 *
 * So the *set itself* narrows to one principal whenever the backend has one
 * identity, and every consumer — `POST /api/session`, the sign-in screen,
 * anything added later — reads the narrowed set without having to remember to
 * ask. That placement is deliberate and is WP-06's own lesson repeated: the
 * fixture gate was first written into ten route handlers and left four server
 * components serving fixtures with every route test green. A gate that has to be
 * *called* is a gate that will be missed; a set that is already narrow cannot be.
 *
 * The pin is deterministic and configuration-free — the first catalogue entry —
 * because an environment variable choosing *which* of two development principals
 * is the one real identity buys nothing an operator needs and adds a value that
 * can be set wrong (`AGENTS.md` section 2).
 *
 * `entra` is untouched: two real Principals there are two real datasets on the
 * far side, and narrowing them would delete a capability rather than a costume.
 * An unconfigured `MYPA_GATEWAY_AUTH_MODE` is also untouched, because in that
 * state no backend request is made at all — `callGateway` refuses before it
 * reaches a socket — so there is no backend data for a second identity to read.
 * The narrowing is keyed to the mode that creates the hazard, not applied
 * wherever it would be easy.
 *
 * Disclosure survives the prevention. `LOCAL_OPERATOR_LIMITATION` still states
 * that results belong to the deployment's single local-operator principal; the
 * pin makes that statement match the number of sign-ins on offer instead of
 * apologising for it.
 */
import { gatewayAuthMode, MissingGatewayAuthModeError } from "@/lib/api/gateway-config";
import type { EntraTokenClaims } from "@/contracts/identity";

/** Synthetic Moss home tenant. NOT a live Entra tenant. */
export const SYNTHETIC_MOSS_TENANT_ID = "11111111-2222-3333-4444-555555555555";

export type SyntheticPrincipalKey = "synthetic-a" | "synthetic-b";

export interface SyntheticPrincipal {
  readonly key: SyntheticPrincipalKey;
  readonly label: string;
  readonly claims: EntraTokenClaims;
}

/**
 * Every synthetic principal this build knows how to mint.
 *
 * Module-private on purpose. It is the vocabulary, not the permission: exporting
 * it would put an unnarrowed list one import away from any consumer, which is
 * exactly the shape `D-15` closes.
 */
const SYNTHETIC_PRINCIPAL_CATALOGUE: readonly SyntheticPrincipal[] = [
  {
    key: "synthetic-a",
    label: "Synthetic A — field operations",
    claims: {
      tid: SYNTHETIC_MOSS_TENANT_ID,
      oid: "aaaa0001-0000-0000-0000-000000000001",
      upn: "synthetic.a@moss.example",
      name: "Synthetic A",
    },
  },
  {
    key: "synthetic-b",
    label: "Synthetic B — preconstruction",
    claims: {
      tid: SYNTHETIC_MOSS_TENANT_ID,
      oid: "bbbb0002-0000-0000-0000-000000000002",
      upn: "synthetic.b@moss.example",
      name: "Synthetic B",
    },
  },
] as const;

/**
 * The single principal admitted when the backend has one identity.
 *
 * The first catalogue entry, named rather than indexed so the constant and the
 * reason travel together.
 */
export const PINNED_SYNTHETIC_PRINCIPAL_KEY: SyntheticPrincipalKey = "synthetic-a";

/**
 * Raised when a principal this build knows exists but may not sign in here.
 *
 * Distinct from "unknown principal", and the distinction is the honest part: the
 * key is real, the deployment is the reason it is refused, and an operator
 * reading the message learns which configuration produced the refusal. It is
 * also a refusal rather than a substitution — silently signing the caller in as
 * the pinned principal would rebind one identity to another without saying so,
 * which is its own defect and a worse one than the refusal.
 */
export class PrincipalNotAdmissibleError extends Error {
  constructor(readonly requestedKey: string) {
    super(
      "MYPA_GATEWAY_AUTH_MODE is 'local_operator', so the gateway serves one fixed " +
        "process principal regardless of which session is signed in. Exactly one " +
        `principal is admissible in that configuration ('${PINNED_SYNTHETIC_PRINCIPAL_KEY}'), ` +
        "because a second sign-in over a one-identity backend would read the first " +
        "principal's data while appearing to be someone else. The request is refused " +
        "rather than rebound to the admissible principal.",
    );
    this.name = "PrincipalNotAdmissibleError";
  }
}

/**
 * Whether the configured backend serves one identity for every session.
 *
 * Only `MissingGatewayAuthModeError` is treated as "not local_operator"; any
 * other error propagates. Swallowing everything here would turn a future failure
 * in `gatewayAuthMode` into a silently widened admissible set, which is the
 * direction this function exists to prevent.
 */
function backendServesOneIdentity(): boolean {
  try {
    return gatewayAuthMode() === "local_operator";
  } catch (error) {
    if (error instanceof MissingGatewayAuthModeError) return false;
    throw error;
  }
}

/** The principals this deployment may sign in — narrowed to one over a one-identity backend. */
export function admissibleSyntheticPrincipals(): readonly SyntheticPrincipal[] {
  if (!backendServesOneIdentity()) return SYNTHETIC_PRINCIPAL_CATALOGUE;
  return SYNTHETIC_PRINCIPAL_CATALOGUE.filter(
    (principal) => principal.key === PINNED_SYNTHETIC_PRINCIPAL_KEY,
  );
}

/**
 * The admissible principal a key names.
 *
 * `undefined` when no such principal exists at all; a thrown
 * `PrincipalNotAdmissibleError` when one exists and this deployment does not
 * admit it. Two answers because they are two different facts, and collapsing
 * them would report a configuration refusal as a typo.
 */
export function resolveAdmissibleSyntheticPrincipal(key: unknown): SyntheticPrincipal | undefined {
  if (typeof key !== "string") return undefined;
  const known = SYNTHETIC_PRINCIPAL_CATALOGUE.find((principal) => principal.key === key);
  if (!known) return undefined;
  if (!admissibleSyntheticPrincipals().some((principal) => principal.key === known.key)) {
    throw new PrincipalNotAdmissibleError(known.key);
  }
  return known;
}
