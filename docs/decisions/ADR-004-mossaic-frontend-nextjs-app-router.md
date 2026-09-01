# ADR-004: MossAIc First-Party Frontend on Next.js App Router with MSAL-Shaped Identity

- **Status:** Accepted with authentication/session provisions partially superseded by [ADR-011](ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md)
- **Decision ID:** `PKL-MYPA-D-WP02-001`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Frontend architecture and authentication boundary. No production deployment,
  live Entra credential, or live personal-data authority.

> **Controlling supersession notice (2026-09-01):** ADR-011 supersedes this ADR's MSAL/Entra production identity target, its Entra-shaped production session model, and the use of a Principal-bearing signed browser cookie as the target session authority. The Next.js/BFF/frontend architecture and other non-authentication provisions below remain accepted. Current legacy runtime paths remain implementation truth until UI-IMP-WP02..WP04 replace them; this notice does not claim WebAuthn is already implemented.

## Context

The ratified Moss canonical product package v4.0
(`MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008`, SHA256
`60e886e9dd19c6d39929990cd939ab1eb8c9c11eea8b0fb8faffac971516d6a4`) changes the
first-party build target from the earlier React + TypeScript + Vite recommendation to
**MossAIc**: one responsive web application on **Next.js (App Router) + TypeScript +
Tailwind CSS + MSAL** with installable PWA behavior (`07_FRONTEND_ARCHITECTURE.md`).

WP-01 (merged at `21ff8dc2`) established the R0A identity plane: durable
`identity.user_accounts` keyed exclusively by validated Entra token claims `(tid, oid)`,
with fail-closed principal scoping in persistence. The frontend must now present the
five-destination shell and the authentication boundary that consumes that identity
plane — without live Entra credentials, which remain an operator-only activation step.

The historical context above is preserved as provenance. ADR-011 now controls the production browser authentication/session target.

## Decision

1. **The first-party frontend lives in `web/`** as a Next.js App Router + TypeScript +
   Tailwind CSS application, named `my-pa-web`.
2. **Five destinations, two global capabilities.** Routes `today`, `situations`,
   `review`, `library`, `system` implement the primary destinations; Capture and Reveal
   are persistent global capabilities reachable from every authenticated surface.
3. **Identity is token-claims-shaped from day one.** The session is established only
   from an Entra-shaped claim set (`tid`, `oid`, `upn`, `name`). In development the
   claims are issued by a **synthetic identity provider** (`web/src/lib/auth/synthetic.ts`)
   carrying clearly-synthetic fixtures; the MSAL configuration
   (`web/src/lib/auth/msal.config.ts`) is present but **inert** — no client ID, no
   authority, no live redemption path. Replacing the synthetic issuer with MSAL redemption
   changes one module, not the session or guard model.
   **Superseded for the production target by ADR-011.** Retained only as historical/current-legacy implementation context until WP02-WP04 complete.
4. **Server-held session, fail-closed guard.** Claims are validated server-side with the
   same rules as the Python identity plane (home-tenant `tid` check, required `oid`,
   caller-supplied `principal_id` rejection) and carried in an HMAC-signed HttpOnly
   cookie. `middleware.ts` redirects unauthenticated requests to `/sign-in`; every API
   route derives the principal from the validated session only.
   **Partially superseded by ADR-011:** fail-closed server-derived Principal authority remains valid, but the target browser cookie carries only an opaque SID and authoritative Principal/session state is server-owned.
5. **Backend-for-frontend route handlers.** The browser never calls Microsoft Graph,
   never holds refresh-token material, and never receives another principal's rows. Route
   handlers under `web/src/app/api/` are the only data plane; in WP-02 they return
   synthetic, clearly-labeled fixtures pending the Python gateway integration.
6. **Canonical contracts in TypeScript.** `web/src/contracts/` mirrors the canonical
   object/state/error/span/Situation/Frame/Trace/Review/Receipt/Disclosure vocabulary of
   `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`, with naming parity to the Python
   `my_pa.contracts` package documented in `web/src/contracts/README.md`.
7. **PWA scaffold now, offline queue later.** The manifest and a minimal service worker
   registration ship in WP-02; the encrypted principal-bound offline capture queue is
   WP-04 and is explicitly out of scope here.

## Consequences

- Development and tests run entirely on synthetic principals; two fixtures
  (`Synthetic A`, `Synthetic B`) support cross-principal UI isolation checks.
- Historical consequence: live Entra activation was originally expected to require only an app registration, MSAL config values, and swapping the synthetic issuer for the MSAL redemption path. **That production-authentication consequence is superseded by ADR-011 and must not be used as implementation authority.**
- The Python FAST/database tiers are unaffected; `web/` carries its own lint,
  typecheck, and vitest suites.

## Supersession

Supersedes the v3.0 React + Vite frontend recommendation.

Partially superseded by ADR-011 as follows: the MSAL/Entra production identity target, Entra-shaped production session model, Principal-bearing signed-cookie target, and live-Entra-completion consequence are superseded. The Next.js App Router, same-origin BFF, server-derived Principal invariant, typed-contract, PWA, and other non-authentication frontend architecture remain accepted unless separately superseded.