/**
 * Temporary compile-safe shims. Python `AuthSessionStore` is the session
 * authority; this file does not decide who is signed in.
 *
 * The process-local Maps that once registered one SID per principal are gone.
 * `registerSession` / `touchSession` / `revokeSession` MUST NOT authorize
 * anyone. Worker C/D will delete remaining imports of this module.
 */

/** Documented idle window matching Python (30 minutes). Not used for auth here. */
export const IDLE_TIMEOUT_SECONDS = 30 * 60;

/** No-op. Does not register, rotate, or authorize a session. */
export function registerSession(
  _principalId: string,
  _sid: string,
  _now?: number,
  _gatewayBearer?: string,
): void {}

/** Always undefined. Worker D will stop reading a process-local bearer. */
export function gatewayBearerForPrincipal(_principalId: string): string | undefined {
  return undefined;
}

/** Always false. Must not succeed as authority. */
export function touchSession(_sid: string, _principalId: string, _now?: number): boolean {
  return false;
}

/** No-op. Revocation is a session-service call, not a local Map delete. */
export function revokeSession(_sid: string): void {}

/** No-op. Tests still import this; there is no local registry to clear. */
export function resetSessionRegistry(): void {}
