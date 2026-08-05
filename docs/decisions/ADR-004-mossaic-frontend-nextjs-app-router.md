# ADR-004: MossAIc First-Party Frontend on Next.js App Router with MSAL-Shaped Identity

- **Status:** Accepted
- **Decision ID:** `PKL-MYPA-D-WP02-001`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Frontend architecture and authentication boundary. No production deployment,
  live Entra credential, or live personal-data authority.

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
4. **Server-held session, fail-closed guard.** Claims are validated server-side with the
   same rules as the Python identity plane (home-tenant `tid` check, required `oid`,
   caller-supplied `principal_id` rejection) and carried in an HMAC-signed HttpOnly
   cookie. `middleware.ts` redirects unauthenticated requests to `/sign-in`; every API
   route derives the principal from the validated session only.
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
- Live Entra activation requires only: an app registration, MSAL config values, and
  swapping the synthetic issuer for the MSAL redemption path — an operator-gated step.
- The Python FAST/database tiers are unaffected; `web/` carries its own lint,
  typecheck, and vitest suites.

## Supersession

Supersedes the v3.0 React + Vite frontend recommendation. Superseded in turn only by a
later accepted ADR; live-credential activation does not modify this ADR, it fulfills it.
