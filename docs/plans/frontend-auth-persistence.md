# Frontend auth persistence substrate (UI-IMP-WP02) and WP04 cookie cutover

**Package:** `UI-IMP-WP02 — Auth Persistence and Session Topology`  
**Architecture authority:** [ADR-011](../decisions/ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md)  
**Alembic:** `2c00c9ac64bc` on `c99cd8ed8d1c` (`identity` schema only)

This document describes the durable PostgreSQL substrate WP02 added, then the WP04 cookie cutover implemented on this branch. It does not restate ADR-011. It does not claim production activation, production Entra retirement as a completed deployment, or `PASS_VERIFIED` for production session criteria.

## What WP02 established

PostgreSQL is the only session/challenge/credential/recovery authority for the *target* topology. There is no Redis, sidecar, or auth microservice. WP02 did not wire HTTP or the browser cookie; that wiring is the WP04 cutover below.

Tables (FK to `identity.user_accounts.principal_id` except where a challenge is pre-principal):

| Table | Role |
|---|---|
| `identity.webauthn_credentials` | Credential ID, COSE public key, sign count, lifecycle. Revoked rows are kept. |
| `identity.webauthn_challenges` | Purpose-bound nonce, digest, RP ID, origin, expiry, atomic consume. |
| `identity.recovery_code_sets` | Generations of recovery material per Principal. |
| `identity.recovery_codes` | SHA-256 hex of normalized codes. Never plaintext. |
| `identity.auth_sessions` | SHA-256 hex of opaque SID, idle+absolute expiry, rotation lineage, revocation. |

Runtime tables and repositories live in `src/my_pa/infrastructure/persistence/webauthn_auth.py` on `IDENTITY_METADATA`. Domain types and hashing live under `src/my_pa/domain/identity/`. Stores take a SQLAlchemy `Connection`. They are not themselves HTTP handlers; WP04 reaches them through the Python session-service.

## Lifecycle invariants

- **Credentials.** `credential_id` is globally unique. Active lookup excludes `revoked_at IS NOT NULL`. `record_use` and `revoke` fail closed on unknown or already-revoked rows.
- **Challenges.** Issue stores random bytes plus SHA-256 digest. Consume is a single `UPDATE … WHERE consumed_at IS NULL AND expires_at > now AND purpose = :p AND principal_id IS NOT DISTINCT FROM :pid RETURNING *`. Replay, expiry, wrong purpose, and wrong principal return `None`. Concurrent consumers: exactly one success.
- **Recovery.** Plaintext exists only in the issue return value. Consume hashes the normalized presented code and uses the same one-row `UPDATE` guard, also requiring the parent set not revoked. Revoking a set stamps `revoked_at` on the set and its unused codes. Hashed recovery is live; operator-local recovery is not implemented (PFE-AC-097 remains `IMPLEMENTATION_REQUIRED`).
- **Sessions.** Create returns the raw SID once; only `token_hash` is stored. Resolve requires not revoked, not superseded, and now before both idle and absolute expiry. Touch refreshes `last_seen_at` and idle expiry but never past `absolute_expires_at`. Rotate locks the current row `FOR UPDATE`, creates one successor, marks the old row revoked (`rotated`) and superseded. A concurrent rotator of the same SID fails closed and does not learn the new SID. `revoke_all_for_principal` stamps every live session for that Principal.

Default TTLs match the current web runtime numbers (8h absolute, 30m idle). WP02 did not change cookies; WP04 now sets the live cookie to the raw SID.

## Secret storage

SHA-256 hex + `hmac.compare_digest`, same family as capture-client and Apple-bridge credentials. SID material is `secrets.token_bytes(32)` presented as hex. Recovery codes are 128-bit grouped hex. Challenge bytes are stored for ceremony binding and must not be logged.

## Concurrency and multi-instance

Coherence is the database, not process memory. Two independent store instances (two connections/engines) on the same PostgreSQL database observe the same authoritative rows. Proof: `tests/database/test_webauthn_auth_persistence.py` (concurrent consume/rotate, second-instance resolve/consume). Do not use SQLite for these tests.

## WP03 ceremony (on this branch)

Python `WebAuthnCeremonyService` verifies registration/assertion through the `webauthn` library and persists through WP02 stores. Next BFF `/api/webauthn/*` attests to the gateway. Successful authentication creates a WP02 `auth_sessions` row. On this branch the cookie is no longer a Principal-bearing HMAC token: WP04 sets `mypa_session` to the raw opaque SID (see below). Ceremony JSON may carry `issuedSid` on the loopback BFF↔Python hop; that field is stripped before the browser sees the body.

WP03 still owns navigator.credentials, passkey UI, options/verify endpoints, RP ID/origin enforcement at the ceremony, user verification, enrollment gating, recovery UX, and step-up ceremonies. Operator-local recovery remains unimplemented.

## WP04 cutover (implemented on this PR, not production-activated)

This branch replaces the Principal-bearing HMAC cookie and process-local session maps with an opaque SID cookie whose authority is PostgreSQL `AuthSessionStore`.

Runtime truth on this branch:

- Cookie `mypa_session` is the raw `AuthSessionStore` SID: 64 hex characters. HttpOnly, `SameSite=Lax`, `Secure` when `NODE_ENV === "production"`, 8h `maxAge`. It does not carry a Principal and is not an HMAC token.
- Next BFF resolves, touches, rotates, revokes, and (in synthetic mode) issues sessions through the Python session-service, authenticating with header `x-my-pa-session-service`. The BFF HMAC authenticates Next to Python; it is not the browser cookie.
- Ceremony/session JSON may include `issuedSid` on the loopback hop. Route handlers set the cookie from that value and strip `issuedSid` before the body is returned to the browser.
- Browser Entra/MSAL and browser `local_operator` sign-in are retired as web modes. Web `MYPA_AUTH_MODE` is exactly `passkey` or `synthetic` (`synthetic` is refused when `NODE_ENV === "production"`).
- Python `MY_PA_AUTH_MODE` / `MYPA_GATEWAY_AUTH_MODE` are unchanged. Gateway process identity remains a separate concern from the browser cookie.
- There is no Redis, no Next→PostgreSQL connection, no production deployment, and no WP-05 mutation-admission work in this package.
- PFE-AC-097 remains `IMPLEMENTATION_REQUIRED`: hashed recovery is live; operator-local recovery is not implemented and is not invented here.
- Production activation is not claimed. This is a repository cutover on the PR branch, not an operator-gated production session change.

Process-local maps and the HMAC cookie are not current runtime truth on this branch. Remaining compile-safe shims in `session-registry.ts` must not authorize anyone.

## What WP05 still owns

- Central mutation admission and browser security (the next executable package)
- Anything that treats this cookie cutover as a production activation or Entra production retirement
