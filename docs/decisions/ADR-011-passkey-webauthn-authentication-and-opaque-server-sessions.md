# ADR-011: Passkey/WebAuthn authentication with opaque server-side sessions

- **Status:** Accepted
- **Decision date:** 2026-09-01
- **Repository basis:** `main@f4eaa4f950009847eb9bde2836f422d5cd731cbc`, tree `0fb4a0ecc416136e5a2a9e25a5d981e3d8a65ae2`
- **Scope:** Production browser authentication/session target and Principal authority. This ADR establishes architecture authority only; it does not claim the replacement runtime is implemented.

## Context

MY-PA is a fixed/single-user product whose browser Principal must remain server-derived. Current repository implementation truth at the decision basis still contains three web authentication modes (`synthetic`, `entra`, `local_operator`), an HMAC-signed cookie that carries Principal/session fields, and a process-local in-memory revocation/idle registry. Those mechanisms remain current runtime truth until later implementation packages replace them.

The post-audit frontend implementation authority requires one durable repository decision before that replacement work begins. The normal production browser target is no longer Microsoft Entra/MSAL and no production browser shared-secret/local-operator fallback is approved. The replacement must also avoid making a browser-readable bearer value authoritative for identity.

This decision is intentionally separated from implementation. `UI-IMP-WP02` through `UI-IMP-WP04` own persistence, WebAuthn ceremonies, session topology, Principal binding, and retirement of legacy production browser authentication.

## Decision

### Authentication

1. Normal production browser authentication is **WebAuthn/passkey based**.
2. The relying-party ID and allowed browser origin(s) are exact deployment configuration. Wildcard or heuristic origin acceptance is prohibited.
3. User verification is required for normal production authentication.
4. There is no public self-registration. Credential enrollment is operator-controlled and bound to the fixed MY-PA Principal.
5. Credential public keys and lifecycle state are server-owned. Registration, revocation, replacement, and recovery are authoritative only after durable server persistence succeeds.
6. Sensitive credential administration requires fresh authentication/step-up, including adding or removing a credential, regenerating recovery material, and revoking all sessions.
7. Recovery is governed. It may use additional registered authenticators/passkeys, strongly hashed one-time recovery material, and a separately controlled operator-local recovery ceremony. A production browser shared secret or `local_operator` sign-in is not an approved recovery fallback.
8. Microsoft Entra/MSAL is not the normal production application-authentication target. Existing Entra code remains legacy implementation truth only until its owning implementation package proves the replacement and removes it.
9. Synthetic authentication remains permitted only for development/test use and must remain impossible as a production fallback.

### Sessions and Principal authority

1. Successful authentication creates an **opaque random server-side session identifier (SID)**. The browser cookie carries only the opaque SID and normal cookie metadata; it does not carry authoritative Principal claims or browser-readable bearer-token authority.
2. Session state, including the Principal binding, is server-owned and looked up from the SID. The browser never selects or supplies the authoritative Principal.
3. Session state supports rotation, revocation, bounded idle expiry, and bounded absolute expiry. Revoked or expired sessions cannot be resurrected by replaying an old browser value.
4. Session and WebAuthn challenge storage must be coherent for the accepted deployment topology. A process-local registry is not sufficient when more than one relevant process/instance can serve the same session or challenge authority.
5. Authentication challenges are cryptographically random, purpose-bound, one-time, expiry-bounded, server-owned, and atomically consumed.
6. Browser storage must not persist application bearer/access/refresh tokens as application-session authority.
7. Every authenticated application capability derives the Principal from validated server session state. Caller-supplied Principal identifiers remain non-authoritative.

### Retirement boundary

The replacement sequence is deliberately gated:

- `UI-IMP-WP02` owns durable credentials, challenges, recovery material, and opaque server-session persistence/topology.
- `UI-IMP-WP03` owns WebAuthn registration/authentication and credential/recovery lifecycle.
- `UI-IMP-WP04` owns the opaque-cookie cutover, server-derived Principal integration, and retirement of production Entra/MSAL and production `local_operator` browser authentication.

Legacy authentication may not be removed merely because this ADR is accepted. Bootstrap, enrollment, recovery, revocation, rollback, and operational behavior must first be implemented and proven by the owning packages.

## Consequences

- The current `synthetic | entra | local_operator` runtime and Principal-bearing HMAC cookie are **not** reclassified as the target; they remain current implementation truth pending WP02-WP04.
- Accepting this ADR does not implement WebAuthn, credential persistence, recovery-code persistence, challenge persistence, session persistence, CSRF changes, or any BFF/runtime feature.
- Production Entra/MSAL browser sign-in is a retirement obligation rather than an architecture to repair or deepen.
- Production browser `local_operator`/shared-secret authentication is likewise a retirement obligation and must not become a recovery fallback.
- Operational bootstrap/recovery and safe migration must be proven before legacy paths are retired.
- Remote MCP OAuth/token architecture is outside this application-login decision and remains governed independently by ADR-009.
- Ingress, NAS placement, database placement, and other non-authentication topology provisions of ADR-008 remain intact unless separately superseded.

## Supersession

This ADR supersedes only the authentication/session provisions of earlier accepted decisions that conflict with the decision above.

### ADR-004

Superseded provisions:

- the title/decision characterization of the frontend identity boundary as **MSAL-shaped**;
- Decision 3 insofar as it makes Entra-shaped claims/MSAL redemption the intended production identity architecture;
- Decision 4 insofar as authoritative Principal/session fields are carried in an HMAC-signed browser cookie rather than resolved from an opaque SID and server-owned session state;
- the Consequences statement that live Entra activation is the intended completion of the application-authentication path.

Still valid from ADR-004 unless independently superseded:

- `web/` as a Next.js App Router + TypeScript + Tailwind first-party frontend;
- same-origin BFF ownership and the rule that the browser does not choose Principal authority;
- server-side guarding/fail-closed identity handling as a security invariant;
- canonical frontend contract ownership;
- PWA direction and other non-authentication frontend architecture provisions.

### ADR-008

Superseded provisions:

- the statement that pilot/production browser authentication is Entra;
- Entra-specific web egress/authorization-code language only to the extent it is presented as the enduring production application-authentication requirement.

Still valid from ADR-008 unless independently superseded:

- NAS/process placement, filesystem authority, private ingress topology, internal data-plane/edge-plane separation, Apple/TCC split, lifecycle controls, image identity, and all other non-authentication topology and operational provisions.

A later ADR is required to change this passkey/session target.