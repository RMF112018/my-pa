# ADR-009: OAuth refresh-token families for remote MCP

**Status:** Accepted
**Decision date:** 2026-08-16
**Repository basis:** `main@341d369d7b53d3d5d0fc6056adf72268b1ad292e`, tree `76b9168d7803ca7740a3891406cfdd874f24cdf5`

## Context

Remote MCP uses repository-owned OAuth 2.1: public Dynamic Client Registration,
Authorization Code + PKCE S256, opaque database-backed access tokens, and
exact MCP resource binding. Access tokens expire after one hour. The token
endpoint accepted only `grant_type=authorization_code`, so ordinary expiry
forced another interactive authorization. Refresh tokens were deferred when
origin OAuth replaced Entra.

Unattended ChatLLM and Agent Task use needs a renewable authorization
relationship. Lengthening access-token lifetime is not an acceptable substitute.

## Decision

1. **Access tokens stay one hour.** Production `TOKEN_LIFETIME` remains 3600
   seconds. Tests may inject a shorter lifetime only through the authorization
   server constructor, never through a production setting.

2. **Refresh is an optional rotating credential.** Authorization-code exchange
   issues a refresh token only when the durable client has `refresh_enabled`.
   Pre-existing and newly registered clients default to `refresh_enabled=false`.
   Operator CLI `set-client-refresh` is the activation gate.

3. **Families, not frozen grants.** PostgreSQL stores refresh-token families
   bound to one client, resource, and scope ceiling, plus single-use generations
   identified by SHA-256 digest. Capability grants, purposes, write kill
   switches, and global remote enablement are re-evaluated at refresh and on
   every MCP call. They are never copied into refresh state.

4. **Public-client rotation.** Refresh tokens are opaque, ≥256 bits of entropy,
   returned once, and persisted only as digests. Each successful refresh
   consumes the presented generation and mints a successor. Presenting a
   consumed generation marks `replay_detected_at`, revokes the family, revokes
   linked live access tokens, and returns generic `invalid_grant`.

5. **Lifetimes.** Idle timeout is 30 days; absolute family lifetime is 90 days.
   After absolute expiry the operator must authorize again.

6. **Protocol.** Metadata advertises `authorization_code` and `refresh_token`.
   DCR accepts `authorization_code` plus optional `refresh_token` and rejects
   other grants. Issuance still requires `refresh_enabled`. Revocation is
   non-oracular. `offline_access` is not a resource scope and is not required.

7. **Fallbacks are not implemented.** Confidential-client secrets, static
   bearers, and lengthened access tokens remain unbuilt unless isolated
   interoperability later proves rotating public refresh cannot work.

## Consequences

- Merge deploys refresh-capable code with every client refresh-disabled.
  Production client enablement, live Abacus proof, and burn-in stay
  operator-gated.
- Rollback is `set-client-refresh --no-refresh-enabled` and, if needed, revert
  the application image. Additive tables stay. Destructive schema downgrade is
  not the first rollback.
- Concurrent refresh of one generation serializes on PostgreSQL; a second
  presenter of a consumed generation is treated as replay.

## Supersession

Does not supersede ADR-001 through ADR-008. It adds a renewable OAuth
credential class beside existing opaque access tokens.
