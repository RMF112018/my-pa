# Frontend auth persistence substrate (UI-IMP-WP02)

**Package:** `UI-IMP-WP02 — Auth Persistence and Session Topology`  
**Architecture authority:** [ADR-011](../decisions/ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md)  
**Alembic:** `2c00c9ac64bc` on `c99cd8ed8d1c` (`identity` schema only)

This document describes the durable PostgreSQL substrate WP02 added. It does not restate ADR-011. It does not claim WebAuthn ceremonies, opaque browser-cookie cutover, or Entra/`local_operator` retirement.

## What WP02 established

PostgreSQL is the only session/challenge/credential/recovery authority for the *target* topology. There is no Redis, sidecar, or auth microservice. Process-local maps remain current *runtime* truth until WP04.

Tables (FK to `identity.user_accounts.principal_id` except where a challenge is pre-principal):

| Table | Role |
|---|---|
| `identity.webauthn_credentials` | Credential ID, COSE public key, sign count, lifecycle. Revoked rows are kept. |
| `identity.webauthn_challenges` | Purpose-bound nonce, digest, RP ID, origin, expiry, atomic consume. |
| `identity.recovery_code_sets` | Generations of recovery material per Principal. |
| `identity.recovery_codes` | SHA-256 hex of normalized codes. Never plaintext. |
| `identity.auth_sessions` | SHA-256 hex of opaque SID, idle+absolute expiry, rotation lineage, revocation. |

Runtime tables and repositories live in `src/my_pa/infrastructure/persistence/webauthn_auth.py` on `IDENTITY_METADATA`. Domain types and hashing live under `src/my_pa/domain/identity/`. Stores take a SQLAlchemy `Connection`. They are not wired to HTTP or `ApplicationService`.

## Lifecycle invariants

- **Credentials.** `credential_id` is globally unique. Active lookup excludes `revoked_at IS NOT NULL`. `record_use` and `revoke` fail closed on unknown or already-revoked rows.
- **Challenges.** Issue stores random bytes plus SHA-256 digest. Consume is a single `UPDATE … WHERE consumed_at IS NULL AND expires_at > now AND purpose = :p AND principal_id IS NOT DISTINCT FROM :pid RETURNING *`. Replay, expiry, wrong purpose, and wrong principal return `None`. Concurrent consumers: exactly one success.
- **Recovery.** Plaintext exists only in the issue return value. Consume hashes the normalized presented code and uses the same one-row `UPDATE` guard, also requiring the parent set not revoked. Revoking a set stamps `revoked_at` on the set and its unused codes.
- **Sessions.** Create returns the raw SID once; only `token_hash` is stored. Resolve requires not revoked, not superseded, and now before both idle and absolute expiry. Touch refreshes `last_seen_at` and idle expiry but never past `absolute_expires_at`. Rotate locks the current row `FOR UPDATE`, creates one successor, marks the old row revoked (`rotated`) and superseded. A concurrent rotator of the same SID fails closed and does not learn the new SID. `revoke_all_for_principal` stamps every live session for that Principal.

Default TTLs match the current web runtime numbers (8h absolute, 30m idle) so WP04 can wire without inventing policy. WP02 does not change cookies.

## Secret storage

SHA-256 hex + `hmac.compare_digest`, same family as capture-client and Apple-bridge credentials. SID material is `secrets.token_bytes(32)` presented as hex. Recovery codes are 128-bit grouped hex. Challenge bytes are stored for later WP03 ceremony binding and must not be logged.

## Concurrency and multi-instance

Coherence is the database, not process memory. Two independent store instances (two connections/engines) on the same PostgreSQL database observe the same authoritative rows. Proof: `tests/database/test_webauthn_auth_persistence.py` (concurrent consume/rotate, second-instance resolve/consume). Do not use SQLite for these tests.

## What WP03 still owns

- `navigator.credentials` and passkey UI
- registration/authentication options endpoints
- attestation/assertion verify
- RP ID/origin production configuration enforcement at the ceremony
- user verification, enrollment gating, recovery UX, step-up ceremonies
- wiring these stores into HTTP

## What WP04 still owns

- replacing the Principal-bearing HMAC cookie with an opaque SID cookie
- session-derived Principal at the BFF/middleware boundary
- retiring production Entra/MSAL and production `local_operator` browser sign-in
- making the live cookie revocable via `identity.auth_sessions`

Until WP04, `web/src/lib/auth/session.ts` and `session-registry.ts` remain current runtime truth.
