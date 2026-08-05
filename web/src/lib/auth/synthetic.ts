/**
 * Synthetic identity provider — development only.
 *
 * Two fixed principals in the synthetic Moss home tenant. No live tenant
 * identifiers, no live personal data. The tenant id matches the synthetic
 * MOSS_TENANT used by the Python identity test suite so cross-tier fixtures
 * agree on what "home tenant" means.
 */
import type { EntraTokenClaims } from "@/contracts/identity";

/** Synthetic Moss home tenant. NOT a live Entra tenant. */
export const SYNTHETIC_MOSS_TENANT_ID = "11111111-2222-3333-4444-555555555555";

export interface SyntheticPrincipal {
  readonly key: "synthetic-a" | "synthetic-b";
  readonly label: string;
  readonly claims: EntraTokenClaims;
}

export const SYNTHETIC_PRINCIPALS: readonly SyntheticPrincipal[] = [
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

export function findSyntheticPrincipal(key: unknown): SyntheticPrincipal | undefined {
  if (typeof key !== "string") return undefined;
  return SYNTHETIC_PRINCIPALS.find((p) => p.key === key);
}
