/**
 * Identity contracts — parity with `my_pa.domain.identity.user_account`.
 *
 * Claim-based identity derives only from validated Entra token claims. The
 * production local account is the fixed operator principal authenticated by
 * passkey. Identity is never caller-supplied.
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

/** Durable account identity provider. Production browser sign-in is passkey. */
export type AccountIdentityProvider = "entra" | "synthetic" | "local";

/** The signed-in principal as exposed to the shell. Never trusted from the client. */
export interface PrincipalSession {
  /** Stable opaque my-pa identity UUID, one per durable account. */
  readonly principalId: string;
  readonly identityProvider: AccountIdentityProvider;
  readonly identitySubject: string;
  readonly displayName: string;
  readonly lifecycleState: UserLifecycleState;
  /** True while the session is issued by the synthetic development provider. */
  readonly synthetic: boolean;
  /** Entra tenant identifier. Omitted for the local operator account. */
  readonly tid?: string;
  /** Entra object identifier. Omitted for the local operator account. */
  readonly oid?: string;
  /** Current user principal name. Omitted for the local operator account. */
  readonly upn?: string;
  /** Optional mapped provider for existing callers. Never `local_operator` for production passkey. */
  readonly authenticationProvider?: "synthetic" | "entra" | "local_operator";
}

/**
 * Field names that must never be accepted from a caller as identity input.
 * Parity with `FORBIDDEN_IDENTITY_FIELDS` in the Python identity domain.
 */
export const FORBIDDEN_IDENTITY_FIELDS = ["principal_id", "principalId", "tid", "oid"] as const;
