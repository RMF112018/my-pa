# ADR-013: Fixed local Principal and operator auth grants

- **Status:** Accepted
- **Decision date:** 2026-09-07
- **Repository basis:** `main@80adb31a3c32b5b8d832d532ae617113bc76fa42`, tree `ad626039262b295f1cd6d8dd9a3a493d9964c86f`
- **Scope:** Production browser Principal identity, operator bootstrap/recovery grants, purpose-bound WebAuthn challenges, and provider-neutral session/attestation contracts. This ADR is an addendum to [ADR-011](ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md); it does not replace passkey authentication or opaque SIDs.

## Context

ADR-011 selected WebAuthn/passkey authentication with an opaque server-side session as the production browser target. The current identity plane still treats Entra `(tid, oid)` as the account key, and BFF attestation still signs those claims. Authentication and recovery can therefore mint a session for whatever Principal owns a credential, while the gateway `local_operator` plane already serves the fixed `LOCAL_OPERATOR_UUID`.

MY-PA remains a fixed single-operator product. The production browser Principal must be that same durable UUID, derived server-side, with no caller-selected identity and no fake Entra tenant or object IDs for the local account. First-user bootstrap and independent operator recovery need one-time, digest-backed grants that cannot choose a Principal. Ordinary passkey enrollment needs a distinct credential-administration grant. Session JSON and BFF-to-gateway attestation must name the durable Principal, not Entra claims.

This decision does not admit multi-user or multi-provider SaaS identity. Browser passkey authentication and the gateway `local_operator` transport remain distinct planes that bind to the same UUID.

## Decision

1. There is **one production Principal**: `LOCAL_OPERATOR_UUID` `24abf5d2-d0c2-5e1c-82f6-e72425e9ed37`. Browser credentials, recovery authority, and sessions that can mint or carry browser authority belong to that UUID.

2. Canonical account identity is `(identity_provider, identity_subject)` with providers `entra | synthetic | local`. The local subject is `local-operator`. Local `tid` and `oid` are both absent. Entra and synthetic accounts require nonblank `tid` and `oid` and subject `tid:oid`. No fake Entra claims are generated for the local account.

3. Operator bootstrap and operator recovery, and credential administration, use **one-time digest-backed grants** targeting `LOCAL_OPERATOR_UUID`. Raw grants are never stored. Bootstrap and recovery grants exchange once into a purpose-bound challenge, then consume on success. Credential-administration grants consume at registration options. Challenge purposes isolate bootstrap, ordinary enrollment, and operator recovery; historical generic purposes remain only for stored rows.

4. Server/BFF `PrincipalSession` is provider-neutral: required `principalId`, `identityProvider`, `identitySubject`, `displayName`, and `lifecycleState`. Provider-specific `tid`/`oid`/`upn` are present only for Entra/synthetic and absent for local. The browser cookie still carries only the opaque SID.

5. BFF-to-gateway WebAuthn attestation signs `{pid, iat}` where `pid` is the durable Principal UUID string. Attestation does not carry `tid`, `oid`, or caller-shaped `principalId`. Correlation derives from that UUID, not from Entra claims.

6. Durable auth state is classified read-only as `uninitialized | ready | inconsistent`. The classifier never mutates, merges, reassigns, or repairs rows.

## Consequences

- Account, grant, challenge, session, and attestation contracts share one Principal. Bootstrap cannot select a different one.
- Gateway `local_operator` may remain a BFF-to-gateway transport; it is not a browser authentication mode and is not a recovery fallback.
- Persistence, CLI issuance, HTTP ceremony wiring, and BFF/UI remain later work packages. Accepting this ADR does not activate production, issue live grants, or migrate a physical database.
- Multi-provider SaaS, additional production Principals, and caller-configurable Principal variables are out of scope.

## Supersession

This ADR is an addendum to ADR-011. Passkey authentication, opaque SID cookies, exact RP/origin checking, and server-derived Principal authority remain in force.

It supersedes only the implication that Entra `(tid, oid)` is the production browser identity key or the BFF attestation payload. Synthetic authentication remains development/test-only as in ADR-011. ADR-012 public-browser ingress and Cloudflare transport are unchanged. ADR-004's rule that the browser does not choose Principal remains valid.

## Implementation status

Owned by `AUTH-IMP-WP01` through `AUTH-IMP-WP10`. Production activation remains operator-gated. This decision records architecture authority; it does not claim the replacement runtime is complete or commissioned.
