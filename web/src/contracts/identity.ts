/**
 * Identity contracts — parity with `my_pa.domain.identity.user_account`.
 *
 * Principal identity derives ONLY from validated Entra token claims
 * `(tid, oid)`. It is never caller-supplied. `upn` and `display_name`
 * are mutable observations, not identity.
 */

/** Entra-shaped token claims. Synthetic in development; MSAL-issued later. */
export interface EntraTokenClaims {
  /** Entra tenant identifier (Moss home tenant). */
  readonly tid: string;
  /** Entra object identifier — the durable per-user subject. */
  readonly oid: string;
  /** Current user principal name (mutable observation). */
  readonly upn: string;
  /** Current display name (mutable observation). */
  readonly name: string;
}

export type ConsentState = "pending" | "granted" | "revoked";

export type UserLifecycleState =
  | "invited"
  | "active"
  | "consent_required"
  | "scope_insufficient"
  | "suspended"
  | "deprovisioned";

/** The signed-in principal as exposed to the shell. Never trusted from the client. */
export interface PrincipalSession {
  /** Stable opaque my-pa identity, one per `(tid, oid)` pair. */
  readonly principalId: string;
  readonly tid: string;
  readonly oid: string;
  readonly upn: string;
  readonly displayName: string;
  readonly lifecycleState: UserLifecycleState;
  /** True while the session is issued by the synthetic development provider. */
  readonly synthetic: boolean;
}

/**
 * Field names that must never be accepted from a caller as identity input.
 * Parity with `FORBIDDEN_IDENTITY_FIELDS` in the Python identity domain.
 */
export const FORBIDDEN_IDENTITY_FIELDS = ["principal_id", "principalId", "tid", "oid"] as const;
